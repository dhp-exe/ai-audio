"""Engine contracts: run parameters, step and run state, and the events the bus carries."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from emvoox.contracts.cast import EngineRef

StepStatus = Literal["pending", "running", "done", "warn", "failed", "skipped", "waiting", "approved", "rejected"]
RunStatus = Literal["pending", "running", "done", "failed", "cancelled", "halted", "awaiting_approval"]
LIVE_RUN = ("pending", "running")

SERIES_STEPS: tuple[str, ...] = ("research", "script", "casting")
EPISODE_STEPS: tuple[str, ...] = ("draft", "direct", "voice", "master", "qa", "gate")
STEP_AGENT = {
    "research": "market_research", "script": "script_writer", "casting": "casting", "draft": "script_writer",
    "direct": "director", "voice": "sound_engineer", "master": "sound_engineer", "qa": "qa_critic", "gate": "publisher",
}
STEP_LABEL = {
    "research": "Trend brief", "script": "Story + bible", "casting": "Cast + engine policy", "draft": "Draft",
    "direct": "Direct", "voice": "Voice", "master": "Master", "qa": "QA", "gate": "Approval gate",
}


class ResearchParams(BaseModel):
    seeds: str = Field("", description="Free-text trend notes pasted by a human (optional).")
    platforms: list[str] = Field(default_factory=list)
    use_browser: bool | None = Field(None, description="None = EMVOOX_RESEARCH_USE_BROWSER.")
    focus: str = Field("", description="Optional steer, e.g. a theme category or audience.")


class RunParams(BaseModel):
    series_id: str
    # what to produce
    episodes: int = Field(30, ge=1, le=99)
    produce: int | None = Field(None, ge=1, le=99, description="Produce the first N episodes now; None = all.")
    only: list[int] | None = Field(None, description="Explicit episode numbers (resume); overrides `produce`.")
    min_sec: int = Field(50, ge=20, le=600)
    max_sec: int = Field(70, ge=20, le=900)
    force: bool = False
    # where the story comes from
    source: Literal["story", "brief", "research", "existing"] = "story"
    brief_id: str | None = None
    research: ResearchParams = Field(default_factory=ResearchParams)
    # engines
    tts_provider: str = "gemini"
    tts_model: str | None = None
    tts_batching: Literal["auto", "line", "scene"] = "auto"
    engine_by_role_type: dict[str, EngineRef] = Field(default_factory=dict)
    engine_by_actor: dict[str, EngineRef] = Field(default_factory=dict)
    tier: Literal["test", "final"] = "test"
    llm_provider: str | None = None
    llm_model: str | None = None
    # QA loop and gate
    max_retries: int = Field(3, ge=0, le=5)
    auto_approve: bool = False
    halt_on_qa_fail: bool = True

    @model_validator(mode="after")
    def _checks(self) -> RunParams:
        from emvoox.providers.tts.catalog import PROVIDER_NAMES, model_ids, supports_scene_batching

        if self.tts_provider not in PROVIDER_NAMES:
            raise ValueError(f"tts_provider must be one of {PROVIDER_NAMES}, got {self.tts_provider!r}")
        self.tts_model = self.tts_model or None
        if self.tts_model and self.tts_model not in model_ids(self.tts_provider):
            raise ValueError(f"{self.tts_model!r} is not a {self.tts_provider} model; expected one of {model_ids(self.tts_provider)}")
        if self.tts_batching == "scene" and not supports_scene_batching(self.tts_provider):
            raise ValueError("scene batching needs an engine with multi-speaker requests (Gemini)")
        if self.max_sec < self.min_sec:
            raise ValueError("max_sec must be >= min_sec")
        if self.source == "brief" and not self.brief_id:
            raise ValueError("source 'brief' needs a brief_id")
        return self

    def episode_numbers(self) -> list[int]:
        if self.only:
            return sorted({n for n in self.only if 1 <= n <= self.episodes})
        produce = self.produce or self.episodes
        return list(range(1, min(produce, self.episodes) + 1))


class StepState(BaseModel):
    id: str = Field(description="'research' | 'script' | 'casting' | 'ep01.draft' ...")
    step: str
    agent: str
    label: str
    episode: int | None = None
    status: StepStatus = "pending"
    attempts: int = Field(0, description="Times this step ran in this run (retries included).")
    started_at: str | None = None
    finished_at: str | None = None
    elapsed_s: float = 0.0
    summary: dict = Field(default_factory=dict)
    error: str | None = None
    cost_usd: float = 0.0
    log_key: str | None = None


class RunTotals(BaseModel):
    cost_usd: float = 0.0
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tts_requests: int = 0
    tts_characters: int = 0
    audio_ms: int = 0
    qa_retries: int = 0


class RunState(BaseModel):
    run_id: str
    series_id: str
    status: RunStatus = "pending"
    error: str | None = None
    created_at: str
    finished_at: str | None = None
    params: RunParams
    steps: list[StepState] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    casting: list[dict] = Field(default_factory=list)
    totals: RunTotals = Field(default_factory=RunTotals)
    engine: dict = Field(default_factory=dict, description="LLM/TTS providers and models actually used.")

    def step(self, step_id: str) -> StepState:
        for s in self.steps:
            if s.id == step_id:
                return s
        raise KeyError(step_id)

    def episodes(self) -> list[int]:
        return sorted({s.episode for s in self.steps if s.episode})


class PipelineEvent(BaseModel):
    seq: int = 0
    at: str
    run_id: str
    series_id: str
    type: str = Field(description="run.started | step.started | step.finished | step.failed | step.retry | contract.rejected | "
                                  "qa.flagged | gate.waiting | gate.approved | gate.rejected | run.finished ...")
    step_id: str | None = None
    agent: str | None = None
    episode: int | None = None
    status: str | None = None
    message: str = ""
    data: dict = Field(default_factory=dict)
