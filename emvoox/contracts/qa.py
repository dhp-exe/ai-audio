"""QA Critic Agent contracts: the report, its timestamped issues and the retry instructions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

IssueCode = Literal[
    "missing_stem", "missing_sentence", "clipping", "long_silence", "duration_off", "loudness_off",
    "true_peak_over", "speaker_mismatch", "placeholder_voice", "mispronunciation", "direction_leak",
    "master_missing", "master_duration_off",
]
# Which pipeline step a retry goes back to, and what it does there.
RetryAction = Literal["rerender", "rerender_line_mode", "reassemble", "redirect"]
RETRY_STEP = {"rerender": "voice", "rerender_line_mode": "voice", "reassemble": "master", "redirect": "direct"}


class QAIssue(BaseModel):
    code: IssueCode
    severity: Literal["blocker", "major", "minor"] = "major"
    message: str
    unit_id: str | None = Field(None, description="Render unit (stem) the issue is on.")
    line_id: str | None = None
    at_ms: int | None = Field(None, ge=0, description="Position in the master, when the unit is on the timeline.")
    value: float | str | None = None


class RetryInstruction(BaseModel):
    action: RetryAction
    step: Literal["direct", "voice", "master"]
    unit_ids: list[str] = Field(default_factory=list)
    params: dict[str, float | int | str | bool] = Field(default_factory=dict, description="Modified TTS / assembly parameters for the retry.")
    reason: str = ""

    @model_validator(mode="after")
    def _step(self) -> RetryInstruction:
        if RETRY_STEP[self.action] != self.step:
            raise ValueError(f"action {self.action!r} belongs to step {RETRY_STEP[self.action]!r}")
        return self


class HumanVerdict(BaseModel):
    verdict: Literal["approved", "rejected"]
    reviewer: str | None = None
    lines: list[str] = Field(default_factory=list)
    notes: str = ""
    at: str


class QAReport(BaseModel):
    """QA Critic Agent output."""

    series_id: str
    episode_number: int = Field(ge=1, le=99)
    attempt: int = Field(0, ge=0, description="0 = first render, n = after the n-th automatic retry.")
    status: Literal["PASS", "FLAGGED"]
    score: int = Field(ge=0, le=100)
    checks: dict[str, dict] = Field(default_factory=dict)
    error_logs: list[QAIssue] = Field(default_factory=list)
    retry_instructions: list[RetryInstruction] = Field(default_factory=list)
    review_lines: list[str] = Field(default_factory=list, description="Lines a human should listen to (peaks, intense monologues).")
    human: HumanVerdict | None = None
    generated_at: str = ""

    @model_validator(mode="after")
    def _consistent(self) -> QAReport:
        blockers = [i for i in self.error_logs if i.severity in ("blocker", "major")]
        if self.status == "PASS" and blockers:
            raise ValueError("a PASS report cannot carry blocker/major issues")
        return self

    def failed_checks(self) -> list[str]:
        return [k for k, v in self.checks.items() if isinstance(v, dict) and v.get("ok") is False]
