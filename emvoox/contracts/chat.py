"""Chat contracts: a thread is one conversation between a person and the Producer agent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatThread(BaseModel):
    id: str
    title: str = ""
    user: str = ""
    status: Literal["idle", "running", "waiting", "failed"] = "idle"
    session_id: str = Field(description="The Producer's AgentSession (same id as the thread).")
    preview: str = Field("", description="The latest line, for the thread list.")
    error: str | None = None
    created_at: str = ""
    updated_at: str = ""


class ChatEvent(BaseModel):
    """What happened in a thread, in order; the client reads the tail while a turn is running."""

    seq: int
    at: str
    type: str = Field(description="user.message | agent.text | tool.called | tool.result | tool.refused | agent.spawned | agent.asked | "
                                  "agent.answered | agent.waiting | agent.finished | turn.failed")
    data: dict = Field(default_factory=dict)
