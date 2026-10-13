"""What is added to an agent's context besides its conversation: its long-term memory, and the compaction that
keeps a long conversation inside the model's window. (Phase 5 fills these in; the chat already calls them.)"""

from __future__ import annotations

from emvoox.contracts.agentic import AgentSession
from emvoox.providers.llm import LlmClient
from emvoox.repositories import Repositories


def memory_context(repos: Repositories, session: AgentSession) -> str:
    return ""


def before_model(repos: Repositories, llm: LlmClient, session: AgentSession) -> None:
    return None
