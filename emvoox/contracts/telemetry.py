"""Cost & audit telemetry: one record per LLM call, TTS request or agent step."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class UsageRecord(BaseModel):
    at: str
    kind: Literal["llm", "tts", "sfx", "agent"]
    run_id: str | None = None
    series_id: str | None = None
    episode: int | None = None
    agent: str | None = None
    skill: str | None = None
    provider: str | None = None
    model: str | None = None
    requests: int = 1
    tokens_in: int = 0
    tokens_out: int = 0
    characters: int = 0
    audio_ms: int = 0
    elapsed_s: float = 0.0
    cost_usd: float = Field(0.0, description="Estimate from emvoox/telemetry/pricing.py; not a vendor invoice.")
    ok: bool = True
    note: str = ""
    unit_id: str | None = None
