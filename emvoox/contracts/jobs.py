"""What the API hands to a worker: one unit of work that outlives the process that asked for it."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field


class Job(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    kind: Literal["run", "scan", "chat"]
    action: Literal["start", "resume", "recover"] = "start"
    tenant: str = "default"
    series_id: str | None = None
    run_id: str | None = Field(None, description="run: the run this job belongs to; the lock that keeps one worker on a run at a time.")
    resume: dict | None = Field(None, description="run + resume: {pending decision id: answer}.")
    payload: dict = Field(default_factory=dict, description="scan: the scan request. chat: the thread to continue.")
    enqueued_at: str = ""
    deliveries: int = Field(0, description="Times a worker took this job (more than one = an earlier worker died on it).")
