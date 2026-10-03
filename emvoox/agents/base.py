"""Agent base: what every agent in the fleet has in common.

An agent owns a small set of *skills* (plain methods) and one output contract. It receives an
``AgentContext`` with everything it may touch: repositories, the LLM client, the telemetry ledger,
the run parameters and a log sink. Agents never import each other and never read files directly;
they exchange Pydantic payloads through the engine.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel

from emvoox.config import Settings
from emvoox.contracts.run import RunParams
from emvoox.providers.llm import LlmClient
from emvoox.repositories import Repositories
from emvoox.telemetry.ledger import Ledger


class AgentError(RuntimeError):
    """An agent could not produce its output. ``retryable`` tells the engine whether running the
    step again can help (a rejected LLM answer can; a missing key cannot)."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    description: str


@dataclass
class AgentContext:
    settings: Settings
    repos: Repositories
    llm: LlmClient
    ledger: Ledger
    params: RunParams
    run_id: str = ""
    log: Callable[[str], None] = field(default=lambda _msg: None)
    cancel: threading.Event = field(default_factory=threading.Event)
    notes: list[str] = field(default_factory=list)

    @property
    def series_id(self) -> str:
        return self.params.series_id

    def note(self, text: str) -> None:
        """A message for the run board (placeholder voices, fallbacks, things a human should know)."""
        if text not in self.notes:
            self.notes.append(text)
        self.log(f"NOTE {text}")


class Agent:
    id: str = ""
    title: str = ""
    description: str = ""
    skills: tuple[Skill, ...] = ()
    consumes: str = ""
    produces: type[BaseModel] | None = None

    def describe(self) -> dict:
        return {
            "id": self.id, "title": self.title, "description": self.description, "consumes": self.consumes,
            "produces": self.produces.__name__ if self.produces else None,
            "skills": [{"id": s.id, "name": s.name, "description": s.description} for s in self.skills],
        }
