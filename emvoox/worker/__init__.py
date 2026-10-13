"""Durable execution: a queue of jobs and the workers that run them.

    queue.py    JobQueue protocol; MemoryQueue (inside one process) and RedisQueue (shared, survives restarts)
    worker.py   Worker: claims a job, runs it (a run, a market scan), keeps its lease alive, honours cancel requests

The API never runs an engine itself: it saves a run in state ``pending`` and enqueues a job. With the memory queue
the API process hosts the worker thread; with Redis, ``python -m emvoox worker`` processes do the work and a job
whose worker dies is delivered again, where the run continues from its checkpoint.
"""

from emvoox.worker.queue import JobQueue, MemoryQueue, RedisQueue, get_queue, reset_queue
from emvoox.worker.worker import Worker, ensure_embedded_worker, stop_embedded_worker

__all__ = ["JobQueue", "MemoryQueue", "RedisQueue", "Worker", "ensure_embedded_worker", "get_queue", "reset_queue", "stop_embedded_worker"]
