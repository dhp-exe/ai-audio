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


class SceneApproval(BaseModel):
    """A reviewer's decision on one scene, taken while the run is paused for it."""

    approved: bool
    reviewer: str = ""
    notes: str = ""
    unit_ids: list[str] = Field(default_factory=list, description="Rejected: the render units to redo; empty = the whole scene.")
    at: str = ""


class SceneQAReport(BaseModel):
    """QA Critic Agent output for one scene: the stem checks of that scene's render units. The episode
    ``QAReport`` rolls these up and adds the checks only a master can answer (loudness, true peak, duration)."""

    series_id: str
    episode_number: int = Field(ge=1, le=99)
    scene_id: str
    attempt: int = Field(0, ge=0, description="0 = first render, n = after the n-th retry of this scene.")
    status: Literal["PASS", "FLAGGED"]
    score: int = Field(ge=0, le=100)
    units: list[str] = Field(default_factory=list, description="Render units of the scene that were checked.")
    checks: dict[str, dict] = Field(default_factory=dict)
    error_logs: list[QAIssue] = Field(default_factory=list)
    retry_instructions: list[RetryInstruction] = Field(default_factory=list)
    review_lines: list[str] = Field(default_factory=list)
    approval: SceneApproval | None = None
    generated_at: str = ""

    @model_validator(mode="after")
    def _consistent(self) -> SceneQAReport:
        if self.status == "PASS" and any(i.severity in ("blocker", "major") for i in self.error_logs):
            raise ValueError("a PASS report cannot carry blocker/major issues")
        if any(r.action == "reassemble" for r in self.retry_instructions):
            raise ValueError("a scene cannot ask for a re-master; that is decided on the episode")
        return self


class QAReport(BaseModel):
    """QA Critic Agent output for one episode: the roll-up of its scene reports plus the master checks."""

    series_id: str
    episode_number: int = Field(ge=1, le=99)
    attempt: int = Field(0, ge=0, description="0 = first render, n = after the n-th automatic retry.")
    status: Literal["PASS", "FLAGGED"]
    score: int = Field(ge=0, le=100)
    checks: dict[str, dict] = Field(default_factory=dict)
    error_logs: list[QAIssue] = Field(default_factory=list)
    retry_instructions: list[RetryInstruction] = Field(default_factory=list)
    review_lines: list[str] = Field(default_factory=list, description="Lines a human should listen to (peaks, intense monologues).")
    scenes: list[dict] = Field(default_factory=list, description="Per scene: scene_id, status, score, attempt, issues, approved_by.")
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
