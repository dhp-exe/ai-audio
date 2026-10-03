"""The run log: every LLM call, TTS request and agent step, with tokens, characters, time and cost.

One ``Ledger`` is created per run (or per API request) and handed to the agents through the
``AgentContext``; it stamps each record with the run, series and episode it belongs to.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from emvoox.contracts.telemetry import UsageRecord
from emvoox.repositories import now_iso
from emvoox.repositories.repos import TelemetryRepository
from emvoox.telemetry import pricing


class Ledger:
    def __init__(self, repo: TelemetryRepository, *, run_id: str | None = None, series_id: str | None = None,
                 on_record: Callable[[UsageRecord], None] | None = None):
        self.repo = repo
        self.run_id = run_id
        self.series_id = series_id
        self._on_record = on_record
        self._lock = threading.Lock()
        self.records: list[UsageRecord] = []

    def _add(self, rec: UsageRecord) -> UsageRecord:
        with self._lock:
            self.records.append(rec)
        self.repo.record(rec)
        if self._on_record:
            self._on_record(rec)
        return rec

    def llm(self, *, agent: str, skill: str, provider: str, model: str, tokens_in: int, tokens_out: int, elapsed_s: float,
            episode: int | None = None, ok: bool = True, note: str = "") -> UsageRecord:
        return self._add(UsageRecord(
            at=now_iso(), kind="llm", run_id=self.run_id, series_id=self.series_id, episode=episode, agent=agent, skill=skill,
            provider=provider, model=model, tokens_in=tokens_in, tokens_out=tokens_out, elapsed_s=elapsed_s,
            cost_usd=pricing.llm_cost(model, tokens_in, tokens_out), ok=ok, note=note))

    def tts(self, *, agent: str, skill: str, provider: str, model: str, characters: int, audio_ms: int, elapsed_s: float,
            episode: int | None = None, unit_id: str | None = None, tokens_in: int = 0, tokens_out: int = 0,
            kind: str = "tts", ok: bool = True, note: str = "") -> UsageRecord:
        return self._add(UsageRecord(
            at=now_iso(), kind=kind, run_id=self.run_id, series_id=self.series_id, episode=episode, agent=agent, skill=skill,  # type: ignore[arg-type]
            provider=provider, model=model, characters=characters, audio_ms=audio_ms, tokens_in=tokens_in, tokens_out=tokens_out,
            elapsed_s=elapsed_s, unit_id=unit_id, ok=ok, note=note,
            cost_usd=pricing.tts_cost(provider, model, characters=characters, audio_ms=audio_ms, tokens_in=tokens_in, tokens_out=tokens_out)))

    def agent(self, *, agent: str, skill: str, elapsed_s: float, episode: int | None = None, ok: bool = True, note: str = "") -> UsageRecord:
        """Execution time of one agent step. Carries no vendor cost itself (requests=0)."""
        return self._add(UsageRecord(at=now_iso(), kind="agent", run_id=self.run_id, series_id=self.series_id, episode=episode,
                                     agent=agent, skill=skill, requests=0, elapsed_s=elapsed_s, ok=ok, note=note))

    def cost_since(self, index: int) -> float:
        with self._lock:
            return round(sum(r.cost_usd for r in self.records[index:]), 6)

    def mark(self) -> int:
        with self._lock:
            return len(self.records)
