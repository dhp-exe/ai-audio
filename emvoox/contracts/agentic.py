"""Contracts of the agent runtime: what a model is offered, what it asks for, and a conversation that can pause.

A *session* is one agent working on one task: its messages (the model's turns, the tool calls and their results),
what it is waiting for, and what it has spent. It is a plain document, so a worker can stop after any turn and
another can continue it.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ToolKind = Literal["core", "read", "write", "external"]


class ToolSpec(BaseModel):
    """A tool as the model sees it."""

    name: str
    description: str
    parameters: dict = Field(description="JSON Schema of the arguments.")


class ToolCall(BaseModel):
    id: str
    name: str
    args: dict = Field(default_factory=dict)
    error: str | None = Field(None, description="Set when the model's arguments were not valid JSON.")


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list, description="assistant: the tools it asked for in this turn.")
    tool_call_id: str | None = Field(None, description="tool: the call this is the result of.")
    name: str | None = Field(None, description="tool: the tool's name.")
    provider_data: dict | None = Field(None, description="assistant: what the vendor needs back verbatim on the next call (e.g. thought signatures).")
    at: str = ""


class ChatReply(BaseModel):
    """One model turn: text, tool calls, or both."""

    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    stop_reason: str = ""
    provider_data: dict | None = None


class AgentSpec(BaseModel):
    """An agent is configuration: who it is, which tools it may use, what it may spend."""

    id: str
    title: str
    prompt: str = Field(description="System prompt (Vietnamese; tool names stay English).")
    areas: list[str] = Field(default_factory=list, description="Tool areas loaded from the start.")
    loadable: list[str] = Field(default_factory=list, description="Tool areas it may load on demand with load_tools.")
    core: list[str] = Field(default_factory=lambda: ["load_tools"], description="Core tools it is given.")
    model: str | None = Field(None, description="Model id for this agent's loop; None = the run's model.")
    max_steps: int = Field(12, ge=1, le=60, description="Model turns per task.")
    max_cost_usd: float | None = Field(None, gt=0, description="Spend per task (model and tools).")
    memory: bool = Field(False, description="Give the agent its long-term memory (remember / recall).")


class PendingAction(BaseModel):
    """What a waiting session needs from a person."""

    id: str = Field(description="The tool call it belongs to; answer with this id.")
    kind: Literal["question", "tool_approval"]
    tool: str
    args: dict = Field(default_factory=dict)
    message: str = ""
    options: list[str] = Field(default_factory=list)
    asked_at: str = ""


class AgentSession(BaseModel):
    id: str
    agent_id: str
    status: Literal["idle", "running", "waiting", "done", "stopped", "failed"] = "idle"
    mode: Literal["auto", "manual"] = Field("auto", description="manual = write tools wait for approval too.")
    messages: list[ChatMessage] = Field(default_factory=list)
    summary: str = Field("", description="Compaction: what the dropped turns contained.")
    pending: list[PendingAction] = Field(default_factory=list)
    loaded: list[str] = Field(default_factory=list, description="Tool areas loaded so far.")
    tainted: bool = Field(False, description="The session has read text from outside (a web page): it may not widen its own tools.")
    steps: int = 0
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    result: str = Field("", description="The agent's final answer.")
    stop_reason: str = ""
    error: str | None = None
    data: dict[str, Any] = Field(default_factory=dict, description="Small values tools keep between calls (ids, never page text).")
    parent_id: str | None = None
    created_at: str = ""
    updated_at: str = ""
