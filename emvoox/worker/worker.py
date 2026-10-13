"""The worker: takes jobs off the queue and runs them to the end, or to the next point where a person decides.

A run job never carries the run: it names it. The worker rebuilds the engine from the saved run state
(``Engine.restore``) and lets the engine choose what to do from that state: start a pending run, continue a
waiting one with the answers the job brings, or recover a run that was in progress when its last worker died
(the workflow graph continues from its checkpoint). While it works, the worker renews the job's lease and
watches for a cancel request.
"""

from __future__ import annotations

import asyncio
import os
import socket
import sys
import threading
import time
import uuid

from emvoox.agents.base import AgentError
from emvoox.contracts.jobs import Job
from emvoox.contracts.run import LIVE_RUN, PendingDecision
from emvoox.providers.llm import LlmProvider
from emvoox.repositories import get_repositories, now_iso
from emvoox.worker.queue import LEASE_SECONDS, JobQueue, get_queue


class Worker:
    def __init__(self, queue: JobQueue | None = None, *, worker_id: str | None = None, llm: LlmProvider | None = None, log=None):
        self.queue = queue or get_queue()
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.llm = llm  # tests hand in a provider object; production resolves it from the run's parameters
        self.log = log or (lambda msg: print(f"[worker {self.worker_id}] {msg}", file=sys.stderr, flush=True))
        self.handled = 0

    # ------------------------------------------------------------------ loop
    def run_forever(self, stop: threading.Event | None = None) -> None:
        stop = stop or threading.Event()
        last_reap = 0.0
        while not stop.is_set():
            if time.time() - last_reap > LEASE_SECONDS / 2:
                try:
                    moved = self.queue.requeue_lost()
                    if moved:
                        self.log(f"re-queued {moved} job(s) whose worker stopped")
                except Exception as e:  # noqa: BLE001 - the queue being away must not kill the worker
                    self.log(f"queue unavailable: {type(e).__name__}: {e}")
                    time.sleep(2)
                last_reap = time.time()
            try:
                self.run_once(timeout=1.0)
            except Exception as e:  # noqa: BLE001
                self.log(f"job loop error: {type(e).__name__}: {e}")
                time.sleep(1)

    def run_once(self, timeout: float = 0.0) -> bool:
        """Claim and run one job. False when the queue had nothing."""
        job = self.queue.claim(self.worker_id, timeout)
        if job is None:
            return False
        if job.run_id and not self.queue.lock_run(job.run_id, self.worker_id):
            # another worker is on this run (an earlier decision is still being carried out): try again shortly
            self.queue.ack(job, self.worker_id)
            time.sleep(0.2)
            self.queue.enqueue(job)
            return True
        stop_beat = threading.Event()
        beat = threading.Thread(target=self._heartbeat, args=(job, stop_beat), daemon=True)
        beat.start()
        try:
            self.handle(job)
        except Exception as e:  # noqa: BLE001 - a job that fails is finished; its run records why
            self.log(f"{job.kind} job {job.id} failed: {type(e).__name__}: {e}")
        finally:
            stop_beat.set()
            beat.join(timeout=5)
            if job.run_id:
                self.queue.unlock_run(job.run_id, self.worker_id)
            self.queue.ack(job, self.worker_id)
            self.handled += 1
        return True

    def _heartbeat(self, job: Job, stop: threading.Event) -> None:
        while not stop.wait(LEASE_SECONDS / 3):
            try:
                self.queue.heartbeat(job, self.worker_id)
            except Exception:  # noqa: BLE001 - a missed beat is recovered by the next one
                pass

    # ------------------------------------------------------------------ jobs
    def handle(self, job: Job) -> None:
        if job.kind == "run":
            self._run(job)
        elif job.kind == "scan":
            self._scan(job)
        elif job.kind == "chat":
            self._chat(job)
        else:  # pragma: no cover - the contract forbids it
            raise ValueError(f"unknown job kind {job.kind!r}")

    def _run(self, job: Job) -> None:
        from emvoox.engine.orchestrator import Engine

        repos = get_repositories(job.tenant)
        try:
            engine = Engine.restore(repos, job.series_id or "", llm=self.llm)
        except AgentError as e:
            self.log(f"run job {job.id}: {e}")
            return
        st = engine.state
        if st.run_id != job.run_id:
            self.log(f"run job {job.id}: {job.run_id} was replaced by {st.run_id}; skipped")
            return
        if self.queue.cancel_requested(st.run_id):
            self.queue.clear_cancel(st.run_id)
            if st.status in (*LIVE_RUN, "waiting"):
                engine.close("cancelled", "cancelled before a worker continued it")
            return
        if job.action == "resume":
            # The API shows an answered run as running and takes the answered decisions off its list; the checkpoint
            # still holds them. This worker holds the run's lock, so nobody else is running it: it is waiting.
            if st.status not in ("waiting", "running") or not job.resume:
                self.log(f"run job {job.id}: {st.run_id} is {st.status}, not waiting; the decision was dropped")
                return
            resume = dict(job.resume)
            st.status = "waiting"
            known = {d.id for d in st.pending}
            st.pending += [PendingDecision(id=k, kind="scene_approval") for k in resume if k not in known]
        elif st.status not in LIVE_RUN:
            self.log(f"run job {job.id}: {st.run_id} is already {st.status}; skipped")
            return
        else:
            resume = None
        done = threading.Event()
        watcher = threading.Thread(target=self._watch_cancel, args=(engine, done), daemon=True)
        watcher.start()
        try:
            self.log(f"{job.action} {st.run_id} ({st.status})")
            asyncio.run(engine.run(resume))
            self.log(f"{st.run_id}: {engine.state.status}")
        finally:
            done.set()
            self.queue.clear_cancel(st.run_id)

    def _watch_cancel(self, engine, done: threading.Event) -> None:
        while not done.wait(0.5):
            try:
                if self.queue.cancel_requested(engine.run_id):
                    engine.cancel()
                    return
            except Exception:  # noqa: BLE001
                pass

    def _scan(self, job: Job) -> None:
        from emvoox.services.research import run_scan

        run_scan(get_repositories(job.tenant), job.payload, llm=self.llm)

    def _chat(self, job: Job) -> None:
        from emvoox.services.chat import run_chat_turn

        run_chat_turn(get_repositories(job.tenant), job.payload, llm=self.llm, queue=self.queue)


# ---------------------------------------------------------------------- the worker inside the API process
_embedded: tuple[threading.Thread, threading.Event, Worker] | None = None
_lock = threading.Lock()


def ensure_embedded_worker(queue: JobQueue | None = None, llm: LlmProvider | None = None) -> Worker:
    """Start (once) a worker thread in this process. The memory queue needs it; with Redis it is a convenience."""
    global _embedded
    with _lock:
        if _embedded is None or not _embedded[0].is_alive():
            worker = Worker(queue, llm=llm, log=lambda msg: None)
            stop = threading.Event()
            thread = threading.Thread(target=worker.run_forever, args=(stop,), name="emvoox-worker", daemon=True)
            thread.start()
            _embedded = (thread, stop, worker)
        return _embedded[2]


def stop_embedded_worker() -> None:
    global _embedded
    with _lock:
        if _embedded is not None:
            _embedded[1].set()
            wake = getattr(_embedded[2].queue, "wake", None)
            if callable(wake):
                wake()
            _embedded[0].join(timeout=30)
            _embedded = None


def main(argv: list[str] | None = None) -> int:
    """python -m emvoox worker: run jobs until interrupted."""
    worker = Worker()
    worker.log(f"queue: {worker.queue.name}; started {now_iso()}")
    if worker.queue.name == "memory":
        worker.log("EMVOOX_QUEUE=memory has no jobs outside the API process; set EMVOOX_QUEUE=redis to use separate workers")
        return 1
    stop = threading.Event()
    try:
        worker.run_forever(stop)
    except KeyboardInterrupt:
        stop.set()
    return 0
