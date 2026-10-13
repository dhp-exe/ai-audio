"""Durable runs: jobs and workers, a run that survives the death of the process running it, the Redis queue's
re-delivery, PostgreSQL as the home of documents and checkpoints, and cancelling through the queue."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
import time
from collections import Counter

import pytest
from conftest import ROOT, needs_ffmpeg, seed_registry

from emvoox.config import reset_settings
from emvoox.contracts import RunParams, StoryInput, StoryOverview, StoryRole
from emvoox.contracts.jobs import Job
from emvoox.engine.orchestrator import Engine
from emvoox.providers.llm.mock import MockLlm
from emvoox.providers.tts.mock import MockTtsProvider
from emvoox.repositories import get_repositories, reset_repositories
from emvoox.worker import MemoryQueue, RedisQueue, Worker
from emvoox.worker import queue as queue_module

STORY = StoryInput(
    overview=StoryOverview(title="Bản hợp đồng", genre="Đô thị, tổng tài", setting="Hiện đại"),
    roles=[StoryRole(name="Linh", description="Nữ 26 tuổi, kế toán, bình tĩnh, sắc sảo", actor_id="ngan"),
           StoryRole(name="Khôi", description="Nam 31 tuổi, giám đốc tài chính, toan tính")],
    script="Linh bị đổ lỗi cho một khoản thâm hụt và mất việc. Cô giữ lại một bản sao lưu, lần theo dòng tiền và phát hiện Khôi không phải kẻ chủ mưu duy nhất.",
)


def params(series_id: str = "s1", **kw) -> RunParams:
    return RunParams(**{"series_id": series_id, "episodes": 4, "produce": 1, "min_sec": 30, "max_sec": 70, "tts_provider": "mock", "llm_provider": "mock",
                        "max_retries": 3, **kw})


def job_for(engine: Engine, action: str = "start", **kw) -> Job:
    return Job(kind="run", action=action, tenant=engine.repos.tenant, series_id=engine.params.series_id, run_id=engine.run_id, **kw)


def quiet(queue, **kw) -> Worker:
    return Worker(queue, log=lambda _msg: None, **kw)


@pytest.fixture
def studio(sandbox, repos):
    seed_registry(sandbox)
    return repos


# ---------------------------------------------------------------- jobs and workers


@needs_ffmpeg
def test_a_worker_starts_a_pending_run_then_continues_it_with_a_decision(studio):
    queue = MemoryQueue()
    engine = Engine.create(params(scene_approval=True), story=STORY, repos=studio)
    assert studio.runs.load("s1").status == "pending" and studio.series.load_story("s1").overview.title == "Bản hợp đồng"  # saved before any worker exists
    queue.enqueue(job_for(engine))
    worker = quiet(queue)
    assert worker.run_once() is True and worker.run_once() is False
    st = studio.runs.load("s1")
    assert st.status == "waiting" and len(st.pending) == 2
    # the two scenes are answered one after the other; the second job arrives while nothing is running
    for d in st.pending:
        queue.enqueue(job_for(engine, "resume", resume={d.id: {"approved": True, "reviewer": "an"}}))
    assert worker.run_once() and studio.runs.load("s1").status == "waiting" and worker.run_once()
    assert studio.runs.load("s1").status == "awaiting_approval" and studio.series.load_release("s1", 1).state == "awaiting_approval"
    # a decision that is no longer open, a job for a run that was replaced: dropped, never run twice
    queue.enqueue(job_for(engine, "resume", resume={"gone": {"approved": True}}))
    queue.enqueue(Job(kind="run", series_id="s1", run_id="s1-older"))
    calls = len(MockTtsProvider.calls)
    assert worker.run_once() and worker.run_once() and len(MockTtsProvider.calls) == calls and studio.runs.load("s1").status == "awaiting_approval"


@needs_ffmpeg
def test_a_run_is_only_worked_on_by_one_worker_at_a_time(studio):
    queue = MemoryQueue()
    engine = Engine.create(params(), story=STORY, repos=studio)
    assert queue.lock_run(engine.run_id, "worker-a")
    queue.enqueue(job_for(engine))
    other = quiet(queue, worker_id="worker-b")
    assert other.run_once() and studio.runs.load("s1").status == "pending" and queue.depth() == 1  # put back, not run
    queue.unlock_run(engine.run_id, "worker-a")
    assert other.run_once() and studio.runs.load("s1").status == "awaiting_approval"


@needs_ffmpeg
def test_cancelling_through_the_queue_stops_a_queued_run_and_a_running_one(studio, monkeypatch):
    queue = MemoryQueue()
    queued = Engine.create(params("queued"), story=STORY, repos=studio)
    queue.enqueue(job_for(queued))
    queue.request_cancel(queued.run_id)
    quiet(queue).run_once()
    st = studio.runs.load("queued")
    assert st.status == "cancelled" and all(s.status == "skipped" for s in st.steps) and not MockTtsProvider.calls

    running = Engine.create(params("running", produce=2), story=STORY, repos=studio)
    real = MockTtsProvider.synthesize

    def slow(self, req, out):  # ask for the cancel as soon as audio is being rendered
        queue.request_cancel(running.run_id)
        time.sleep(0.05)
        return real(self, req, out)

    monkeypatch.setattr(MockTtsProvider, "synthesize", slow)
    queue.enqueue(job_for(running))
    quiet(queue).run_once()
    st = studio.runs.load("running")
    assert st.status == "cancelled" and all(s.status == "skipped" for s in st.steps if s.episode == 2)
    assert not queue.cancel_requested(running.run_id)


# ---------------------------------------------------------------- the worker dies


CRASH = textwrap.dedent("""
    import asyncio, os, signal, sys
    sys.path.insert(0, {tests!r})
    from test_worker import STORY, params
    from emvoox.agents.sound_engineer import SoundEngineerAgent
    from emvoox.engine.orchestrator import Engine
    from emvoox.providers.llm.mock import MockLlm
    from emvoox.repositories import get_repositories

    def die(*_a, **_kw):  # every scene is rendered and checked; the process is killed as mastering starts
        os.kill(os.getpid(), signal.SIGKILL)

    SoundEngineerAgent.assemble_audio = die
    asyncio.run(Engine(params({series!r}, force=True), story=STORY, repos=get_repositories(), llm=MockLlm()).run())
""")


def crash_a_run(series: str, env: dict | None = None) -> None:
    code = CRASH.format(tests=str(ROOT / "tests"), series=series)
    proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT), **(env or {})}, capture_output=True, timeout=180)
    assert proc.returncode == -9, proc.stderr.decode()[-2000:]


def tts_spend(repos, series: str) -> Counter:
    return Counter(r["unit_id"] for r in repos.docs.read_log(f"series/{series}/run.log.jsonl") if r["kind"] == "tts")


@needs_ffmpeg
def test_a_run_whose_process_was_killed_is_recovered_without_paying_twice(studio):
    crash_a_run("s1")
    st = studio.runs.load("s1")
    assert st.status == "running" and st.step("ep01.voice").status == "done" and st.step("ep01.master").status == "running"  # left exactly as it died
    before = tts_spend(studio, "s1")
    assert before and set(before.values()) == {1}

    queue = MemoryQueue()
    queue.enqueue(Job(kind="run", action="recover", series_id="s1", run_id=st.run_id))
    quiet(queue, llm=MockLlm()).run_once()
    st = studio.runs.load("s1")
    assert st.status == "awaiting_approval", st.error
    assert tts_spend(studio, "s1") == before  # even with --force: nothing this run already rendered was rendered again
    assert studio.series.load_mastered("s1", 1) and studio.series.load_qa("s1", 1).status == "PASS"
    types = [e["type"] for e in studio.runs.events("s1")]
    assert types.count("run.started") == 1 and types.count("run.recovered") == 1 and types[-1] == "run.finished"
    assert st.totals.tts_requests == sum(before.values()) and st.step("ep01.master").attempts == 2  # the step that was running ran again


@needs_ffmpeg
def test_at_startup_the_api_recovers_runs_left_in_progress(studio):
    from fastapi.testclient import TestClient

    from emvoox.api import app as webapp

    crash_a_run("s1")
    run_id = studio.runs.load("s1").run_id
    never_started = Engine.create(params("s2"), story=STORY, repos=studio)  # queued when the server stopped: its job went with the memory queue
    assert webapp.recover_interrupted_runs() == {"recovered": [run_id, never_started.run_id], "interrupted": []}
    client = TestClient(webapp.app)
    deadline = time.time() + 120
    while time.time() < deadline and {client.get(f"/api/runs/{r}").json()["status"] for r in (run_id, never_started.run_id)} != {"awaiting_approval"}:
        time.sleep(0.3)
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "awaiting_approval"
    assert client.get(f"/api/runs/{never_started.run_id}").json()["status"] == "awaiting_approval"


def test_a_run_left_in_progress_without_a_checkpoint_is_closed_not_restarted(studio):
    engine = Engine.create(params(), story=STORY, repos=studio)
    engine.state.status = "running"  # e.g. recorded by a version that had no checkpoints
    studio.runs.save(engine.state)
    queue = MemoryQueue()
    queue.enqueue(job_for(engine, "recover"))
    quiet(queue, llm=MockLlm()).run_once()
    st = studio.runs.load("s1")
    assert st.status == "cancelled" and "no checkpoint" in st.error and not MockTtsProvider.calls


# ---------------------------------------------------------------- Redis


def test_redis_queue_delivers_in_order_and_gives_back_what_a_dead_worker_held(redis_url, monkeypatch):
    queue = RedisQueue(redis_url, prefix="emvoox-test")
    jobs = [queue.enqueue(Job(kind="run", series_id=f"s{i}", run_id=f"s{i}-1")) for i in (1, 2, 3)]
    assert queue.depth() == 3
    first = queue.claim("worker-a", timeout=1)
    assert first.id == jobs[0].id and first.deliveries == 1 and queue.depth() == 2
    queue.ack(first, "worker-a")
    second = queue.claim("worker-a", timeout=1)  # worker-a dies here: no ack, no more heartbeats
    assert second.id == jobs[1].id and queue.requeue_lost() == 0  # its lease is still alive
    queue.r.delete(queue._k("lease", second.id))  # ... until it expires
    assert queue.requeue_lost() == 1 and queue.requeue_lost() == 0
    again = queue.claim("worker-b", timeout=1)
    assert again.id == second.id and again.action == "recover" and again.deliveries == 2  # ahead of newer work, and told to recover
    queue.ack(again, "worker-b")
    assert queue.claim("worker-b", timeout=1).id == jobs[2].id and queue.claim("worker-b", timeout=0.3) is None
    # the per-run lock and the cancel signal
    assert queue.lock_run("r1", "worker-a") and queue.lock_run("r1", "worker-a") and not queue.lock_run("r1", "worker-b")
    queue.unlock_run("r1", "worker-b")
    assert not queue.lock_run("r1", "worker-b")
    queue.unlock_run("r1", "worker-a")
    assert queue.lock_run("r1", "worker-b")
    queue.request_cancel("r1")
    assert queue.cancel_requested("r1") and not queue.cancel_requested("r2")
    queue.clear_cancel("r1")
    assert not queue.cancel_requested("r1")


@needs_ffmpeg
def test_with_redis_a_second_worker_finishes_what_a_killed_one_started(studio, redis_url, monkeypatch):
    """Two real mechanisms together: the job comes back because its lease ran out, and the run continues from its checkpoint."""
    monkeypatch.setattr(queue_module, "LEASE_SECONDS", 1)
    queue = RedisQueue(redis_url, prefix="emvoox-test")
    crash_a_run("s1")
    st = studio.runs.load("s1")
    # what Redis looks like after that death: the job is in the dead worker's processing list, its lease gone
    job = Job(kind="run", action="start", series_id="s1", run_id=st.run_id)
    queue.enqueue(job)
    assert queue.claim("dead-worker", timeout=1).id == job.id
    time.sleep(1.2)
    survivor = quiet(queue, llm=MockLlm(), worker_id="survivor")
    stop = threading.Event()
    thread = threading.Thread(target=survivor.run_forever, args=(stop,), daemon=True)
    thread.start()
    deadline = time.time() + 120
    while time.time() < deadline and studio.runs.load("s1").status == "running":
        time.sleep(0.3)
    stop.set()
    thread.join(timeout=10)
    assert studio.runs.load("s1").status == "awaiting_approval" and set(tts_spend(studio, "s1").values()) == {1}
    assert queue.depth() == 0 and not queue.r.lrange(queue._k("processing", "dead-worker"), 0, -1)


# ---------------------------------------------------------------- PostgreSQL


@needs_ffmpeg
def test_with_postgres_run_state_and_checkpoints_live_in_the_database(sandbox, postgres_dsn, monkeypatch):
    import uuid

    import psycopg

    tenant = f"t-{uuid.uuid4().hex[:10]}"
    monkeypatch.setenv("EMVOOX_STORAGE", "postgres")
    monkeypatch.setenv("EMVOOX_DATABASE_URL", postgres_dsn)
    monkeypatch.setenv("EMVOOX_TENANT", tenant)
    reset_settings()
    reset_repositories()
    repos = get_repositories()
    try:
        assert repos.backend == "postgres" and repos.tenant == tenant
        seed_registry(sandbox)
        import json

        repos.docs.put("assets/voice_registry.json", json.loads((sandbox / "assets" / "voice_registry.json").read_text()))
        queue = MemoryQueue()
        engine = Engine.create(params(scene_approval=True), story=STORY, repos=repos)
        queue.enqueue(job_for(engine))
        quiet(queue, llm=MockLlm()).run_once()
        st = repos.runs.load("s1")
        assert st.status == "waiting" and len(st.pending) == 2
        assert not (sandbox / "tenants" / tenant / "series" / "s1" / "pipeline_run.json").exists()  # documents are rows, not files
        assert (sandbox / "tenants" / tenant / "series" / "s1" / "stems" / "ep01").is_dir()  # media stays on disk, under the tenant
        with psycopg.connect(postgres_dsn) as conn:
            thread = f"{tenant}:{st.run_id}"
            assert conn.execute("SELECT count(*) FROM checkpoints WHERE thread_id = %s", (thread,)).fetchone()[0] > 0
            assert conn.execute("SELECT count(*) FROM documents WHERE tenant = %s AND key = %s", (tenant, "series/s1/pipeline_run.json")).fetchone()[0] == 1
        reset_repositories()  # another process: new pool, new engine, same database
        repos = get_repositories()
        queue.enqueue(Job(kind="run", action="resume", tenant=tenant, series_id="s1", run_id=st.run_id,
                          resume={d.id: {"approved": True, "reviewer": "an"} for d in st.pending}))
        quiet(queue, llm=MockLlm()).run_once()
        assert repos.runs.load("s1").status == "awaiting_approval"
        with psycopg.connect(postgres_dsn) as conn:  # a finished run keeps no checkpoint
            assert conn.execute("SELECT count(*) FROM checkpoints WHERE thread_id = %s", (thread,)).fetchone()[0] == 0
    finally:
        repos.docs.delete_prefix("")
        reset_repositories()
