"""Tools: what a model may call. A tool is a function with typed arguments, an area and a kind.

    kind      what the permission gate does with a call
    core      runs; controls the loop itself (load_tools, ask_user, spawn_subagent, remember, recall)
    read      runs at once
    write     runs at once in auto mode; waits for a person in manual mode
    external  spends money or publishes: always waits for a person

Adding a tool = one decorated function in a module of ``emvoox/tools`` (or anywhere that is imported):

    class SearchArgs(BaseModel):
        query: str = Field(description="...")

    @tool("research_search", area="research", kind="read", description="...", untrusted=True)
    def research_search(ctx: ToolContext, args: SearchArgs) -> dict: ...

The runtime validates the model's arguments against the Pydantic model before the function runs, and hands the
return value back to the model as JSON. ``untrusted=True`` marks a tool whose result contains text from outside
(a web page): after it has run, the session may not widen its own tools.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from emvoox.config import Settings
from emvoox.contracts.agentic import AgentSession, AgentSpec, ToolKind, ToolSpec
from emvoox.contracts.jobs import Job
from emvoox.providers.llm import LlmClient
from emvoox.repositories import Repositories
from emvoox.telemetry.ledger import Ledger


class ToolError(Exception):
    """The tool could not do what was asked. The message goes back to the model, which may try something else."""


@dataclass
class ToolContext:
    """Everything a tool may touch. Like an agent, a tool reaches storage only through ``repos``."""

    settings: Settings
    repos: Repositories
    llm: LlmClient
    ledger: Ledger
    session: AgentSession
    spec: AgentSpec
    user: str = ""
    submit: Callable[[Job], Any] | None = None  # hand a job to the workers (start a production run)
    log: Callable[[str], None] = field(default=lambda _msg: None)
    emit: Callable[..., None] = field(default=lambda *_a, **_kw: None)
    cancel: threading.Event = field(default_factory=threading.Event)

    def agent_context(self, series_id: str = "research"):
        """The context an agent skill expects, for tools that wrap one."""
        from emvoox.agents.base import AgentContext
        from emvoox.contracts.run import RunParams

        return AgentContext(settings=self.settings, repos=self.repos, llm=self.llm, ledger=self.ledger,
                            params=RunParams(series_id=series_id, tts_provider="mock"), log=self.log, cancel=self.cancel)


@dataclass(frozen=True)
class Tool:
    name: str
    area: str
    kind: ToolKind
    description: str
    args: type[BaseModel]
    fn: Callable[[ToolContext, Any], Any]
    untrusted: bool = False

    def spec(self) -> ToolSpec:
        schema = self.args.model_json_schema()
        schema.pop("title", None)
        for prop in (schema.get("properties") or {}).values():
            prop.pop("title", None)
        return ToolSpec(name=self.name, description=self.description, parameters=schema)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, t: Tool) -> Tool:
        if t.name in self._tools and self._tools[t.name].fn is not t.fn:
            raise ValueError(f"tool {t.name!r} is already registered")
        self._tools[t.name] = t
        return t

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def areas(self) -> list[str]:
        return sorted({t.area for t in self._tools.values()})

    def in_area(self, area: str) -> list[Tool]:
        return sorted((t for t in self._tools.values() if t.area == area), key=lambda t: t.name)

    def all(self) -> list[Tool]:
        return sorted(self._tools.values(), key=lambda t: (t.area, t.name))


REGISTRY = ToolRegistry()


def tool(name: str, *, area: str, kind: ToolKind, description: str, untrusted: bool = False, args: type[BaseModel] | None = None,
         registry: ToolRegistry | None = None):
    """Register ``fn(ctx: ToolContext, args: <BaseModel>)`` as a model-callable tool. The arguments model is read
    from the annotation of the function's second parameter; pass ``args=`` when that model is not importable by
    name (defined inside a function)."""

    def wrap(fn: Callable[[ToolContext, Any], Any]):
        import inspect
        import typing

        model = args
        if model is None:
            params = list(inspect.signature(fn).parameters)
            try:
                model = typing.get_type_hints(fn).get(params[1]) if len(params) > 1 else None
            except NameError:
                model = None
        if not (isinstance(model, type) and issubclass(model, BaseModel)):
            raise TypeError(f"tool {name!r}: the second parameter must be annotated with a Pydantic model (or pass args=)")
        (registry or REGISTRY).register(Tool(name=name, area=area, kind=kind, description=description, args=model, fn=fn, untrusted=untrusted))
        return fn

    return wrap


def load_builtin_tools() -> ToolRegistry:
    """Import the tool modules that ship with the engine (idempotent)."""
    from emvoox.tools import core, library, production, research  # noqa: F401

    return REGISTRY
