"""Job queues. A job is claimed by one worker at a time and stays claimed while that worker renews its lease.

``MemoryQueue`` lives in one process: no lease is needed, and a restart loses the queue (the API re-enqueues
unfinished runs at startup). ``RedisQueue`` is shared and durable: a claimed job sits in the worker's processing
list with a lease key; when the worker dies the lease expires and any worker's ``requeue_lost`` puts the job back.

Both also carry two small signals: a cancel request per run, and a lock so that two jobs of the same run (two
decisions answered in quick succession) are never executed at the same time.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Protocol

from emvoox.config import get_settings
from emvoox.contracts.jobs import Job
from emvoox.repositories import now_iso

LEASE_SECONDS = 30


class JobQueue(Protocol):
    name: str

    def enqueue(self, job: Job) -> Job: ...

    def claim(self, worker_id: str, timeout: float = 1.0) -> Job | None: ...

    def heartbeat(self, job: Job, worker_id: str) -> None: ...

    def ack(self, job: Job, worker_id: str) -> None: ...

    def requeue_lost(self) -> int:
        """Put back jobs whose worker stopped renewing its lease. Returns how many."""
        ...

    def lock_run(self, run_id: str, worker_id: str) -> bool: ...

    def unlock_run(self, run_id: str, worker_id: str) -> None: ...

    def request_cancel(self, run_id: str) -> None: ...

    def cancel_requested(self, run_id: str) -> bool: ...

    def clear_cancel(self, run_id: str) -> None: ...

    def depth(self) -> int: ...


class MemoryQueue:
    name = "memory"

    def __init__(self) -> None:
        self._jobs: deque[Job] = deque()
        self._cond = threading.Condition()
        self._locks: dict[str, str] = {}
        self._cancel: set[str] = set()

    def enqueue(self, job: Job) -> Job:
        job.enqueued_at = job.enqueued_at or now_iso()
        with self._cond:
            self._jobs.append(job)
            self._cond.notify()
        return job

    def claim(self, worker_id: str, timeout: float = 1.0) -> Job | None:
        with self._cond:
            if not self._jobs:
                self._cond.wait(timeout)
            if not self._jobs:
                return None
            job = self._jobs.popleft()
            job.deliveries += 1
            return job

    def heartbeat(self, job: Job, worker_id: str) -> None:
        return None

    def ack(self, job: Job, worker_id: str) -> None:
        return None

    def requeue_lost(self) -> int:
        return 0

    def lock_run(self, run_id: str, worker_id: str) -> bool:
        with self._cond:
            if self._locks.get(run_id, worker_id) != worker_id:
                return False
            self._locks[run_id] = worker_id
            return True

    def unlock_run(self, run_id: str, worker_id: str) -> None:
        with self._cond:
            if self._locks.get(run_id) == worker_id:
                del self._locks[run_id]

    def request_cancel(self, run_id: str) -> None:
        with self._cond:
            self._cancel.add(run_id)

    def cancel_requested(self, run_id: str) -> bool:
        with self._cond:
            return run_id in self._cancel

    def clear_cancel(self, run_id: str) -> None:
        with self._cond:
            self._cancel.discard(run_id)

    def depth(self) -> int:
        with self._cond:
            return len(self._jobs)

    def wake(self) -> None:
        """Let a worker waiting in ``claim`` notice that it was asked to stop."""
        with self._cond:
            self._cond.notify_all()


# Take the oldest job and give it a lease in one step, so a job is never claimed without one.
_CLAIM = """
local raw = redis.call('LMOVE', KEYS[1], KEYS[2], 'RIGHT', 'LEFT')
if not raw then return nil end
local job = cjson.decode(raw)
redis.call('SET', ARGV[1] .. job['id'], ARGV[2], 'EX', tonumber(ARGV[3]))
return raw
"""


class RedisQueue:
    name = "redis"

    def __init__(self, url: str, prefix: str = "emvoox"):
        try:
            import redis
        except ImportError as e:  # pragma: no cover - depends on the install
            raise RuntimeError("EMVOOX_QUEUE=redis needs: pip install -e '.[durable]'") from e
        self.r = redis.Redis.from_url(url, decode_responses=True)
        self.p = prefix
        self._claim = self.r.register_script(_CLAIM)

    def _k(self, *parts: str) -> str:
        return ":".join((self.p, *parts))

    def enqueue(self, job: Job) -> Job:
        job.enqueued_at = job.enqueued_at or now_iso()
        self.r.lpush(self._k("jobs"), job.model_dump_json())
        return job

    def claim(self, worker_id: str, timeout: float = 1.0) -> Job | None:
        deadline = time.time() + timeout
        while True:
            raw = self._claim(keys=[self._k("jobs"), self._k("processing", worker_id)], args=[self._k("lease", ""), worker_id, LEASE_SECONDS])
            if raw:
                job = Job.model_validate_json(raw)
                job.deliveries += 1
                self.r.hset(self._k("raw"), job.id, raw)  # the exact entry to remove from the processing list on ack
                return job
            if time.time() >= deadline:
                return None
            time.sleep(0.2)

    def heartbeat(self, job: Job, worker_id: str) -> None:
        self.r.set(self._k("lease", job.id), worker_id, ex=LEASE_SECONDS)
        if job.run_id:
            self.r.expire(self._k("runlock", job.run_id), LEASE_SECONDS)

    def ack(self, job: Job, worker_id: str) -> None:
        raw = self.r.hget(self._k("raw"), job.id)
        pipe = self.r.pipeline()
        if raw:
            pipe.lrem(self._k("processing", worker_id), 1, raw)
        pipe.hdel(self._k("raw"), job.id)
        pipe.delete(self._k("lease", job.id))
        pipe.execute()

    def requeue_lost(self) -> int:
        moved = 0
        for key in self.r.scan_iter(match=self._k("processing", "*")):
            for raw in self.r.lrange(key, 0, -1):
                job = Job.model_validate_json(raw)
                if self.r.exists(self._k("lease", job.id)):
                    continue
                if self.r.lrem(key, 1, raw):  # whoever removes it re-queues it: two reapers cannot both do so
                    job.deliveries += 1
                    job.action = "recover" if job.kind == "run" else job.action
                    pipe = self.r.pipeline()
                    pipe.rpush(self._k("jobs"), job.model_dump_json())  # ahead of new work
                    pipe.hdel(self._k("raw"), job.id)
                    if job.run_id:
                        pipe.delete(self._k("runlock", job.run_id))
                    pipe.execute()
                    moved += 1
        return moved

    def lock_run(self, run_id: str, worker_id: str) -> bool:
        key = self._k("runlock", run_id)
        return bool(self.r.set(key, worker_id, nx=True, ex=LEASE_SECONDS)) or self.r.get(key) == worker_id

    def unlock_run(self, run_id: str, worker_id: str) -> None:
        key = self._k("runlock", run_id)
        if self.r.get(key) == worker_id:
            self.r.delete(key)

    def request_cancel(self, run_id: str) -> None:
        self.r.set(self._k("cancel", run_id), "1", ex=86_400)

    def cancel_requested(self, run_id: str) -> bool:
        return bool(self.r.exists(self._k("cancel", run_id)))

    def clear_cancel(self, run_id: str) -> None:
        self.r.delete(self._k("cancel", run_id))

    def depth(self) -> int:
        return int(self.r.llen(self._k("jobs")))


_queue: JobQueue | None = None
_lock = threading.Lock()


def get_queue() -> JobQueue:
    """The process-wide queue for EMVOOX_QUEUE (memory | redis)."""
    global _queue
    with _lock:
        if _queue is None:
            s = get_settings()
            if s.queue_backend == "memory":
                _queue = MemoryQueue()
            elif s.queue_backend == "redis":
                _queue = RedisQueue(s.redis_url)
            else:
                raise ValueError(f"EMVOOX_QUEUE must be memory or redis, got {s.queue_backend!r}")
        return _queue


def reset_queue() -> None:
    global _queue
    with _lock:
        _queue = None
