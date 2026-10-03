"""LLM abstraction: one structured-output call, any vendor.

Agents call ``LlmClient.structured(...)`` and get a validated Pydantic instance back. The client
picks the adapter (Gemini, WaveSpeed, any OpenAI-compatible endpoint, Claude, or the offline mock),
re-validates the output against the schema and writes the call to the telemetry ledger.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LlmError(RuntimeError):
    """Base class for LLM failures the caller should surface."""


class LlmTruncated(LlmError):
    """Response hit max_output_tokens; split the input or raise the limit."""


class LlmBlocked(LlmError):
    """Prompt or response blocked by safety filters."""


class LlmSchemaError(LlmError):
    """Model returned JSON that does not satisfy the Pydantic contract."""


@dataclass(frozen=True)
class Usage:
    model: str
    prompt_tokens: int
    output_tokens: int
    thinking_tokens: int
    elapsed_s: float
    provider: str = "gemini"

    def as_dict(self) -> dict:
        return self.__dict__.copy()


class LlmProvider(Protocol):
    name: str

    def generate_structured(self, *, system: str, user: str, schema: type[T], model: str | None = None,
                            temperature: float | None = None, max_output_tokens: int = 65_536,
                            context: dict | None = None) -> tuple[T, Usage]:
        """Return (validated instance, usage). ``context`` is structured task data for offline
        adapters; network adapters ignore it."""
        ...


def schema_instructions(schema: type[BaseModel]) -> str:
    """Prompt suffix for endpoints that only offer JSON mode: the JSON Schema the reply must satisfy."""
    return ("\n\nReturn ONE JSON object and nothing else (no markdown fences, no commentary). "
            "It must validate against this JSON Schema:\n" + json.dumps(schema.model_json_schema(), ensure_ascii=False))


def extract_json(text: str) -> str:
    """Tolerate a fenced or prefixed reply from JSON-mode endpoints."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    start, end = t.find("{"), t.rfind("}")
    return t[start:end + 1] if start != -1 and end > start else t


def transcribe_supported(provider: object) -> bool:
    return callable(getattr(provider, "transcribe", None))


AudioPath = Path
