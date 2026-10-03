"""Market Research Agent contracts: what was observed, how it was analysed, and the TrendBrief."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

PLATFORMS: tuple[str, ...] = ("dramabox", "reelshort", "tiktok", "google", "youtube", "douyin", "local")
TOP_GENRES = 3  # the brief documents the three most trending genres; a human picks one


class ThemeCategory(str, Enum):
    """The three Mặc Khải content lines, plus an escape hatch."""

    urban_ceo = "urban_ceo"  # Đô thị - Tổng tài
    rebirth = "rebirth_butterfly_effect"  # Tái sinh - Lội ngược dòng
    intellectual_slap = "intellectual_slap_anti_trope"  # Vả mặt - Ngược tra
    other = "other"


THEME_LABEL_VI = {
    ThemeCategory.urban_ceo: "Đô thị - Tổng tài",
    ThemeCategory.rebirth: "Tái sinh - Lội ngược dòng",
    ThemeCategory.intellectual_slap: "Vả mặt - Ngược tra",
    ThemeCategory.other: "Khác",
}


class MarketObservation(BaseModel):
    """One raw thing the Market Scan skill saw: a seed note or the visible text of a public page."""

    platform: str = "local"
    source: str = Field(description="File name of a local seed or the URL that was scanned.")
    title: str = ""
    text: str = Field(description="Raw text handed to Content Analyze (trimmed).")
    captured_at: str
    via: Literal["local", "browser", "http"] = "local"


class ContentInsight(BaseModel):
    """Content Analyze output for one reference title."""

    title: str
    platform: str = ""
    genre: str = ""
    hook: str = Field(description="What makes people press play, in one sentence.")
    pacing: str = Field("", description="How fast the first twist arrives and how episodes end.")
    tropes: list[str] = Field(default_factory=list)


class TrendCandidate(BaseModel):
    """One trending genre found in the scan, with the evidence for it and a story direction the
    Script Writer can use, rated on three axes (1-10 each)."""

    genre: str = Field("", description="The trending short-drama genre, as audiences call it (e.g. 'Tổng tài - hôn nhân hợp đồng').")
    evidence: str = Field("", description="What in the scanned data shows this genre is trending: titles, counts, platforms.")
    platforms: list[str] = Field(default_factory=list, description="Platforms where the genre was observed.")
    topic: str = Field(description="Working title or one-line story direction, in Vietnamese.")
    theme_category: ThemeCategory
    target_audience: str
    hook: str
    premise: str = Field(description="5-8 sentence treatment the Script Writer can expand: who wants what, who opposes and why, the turn.")
    anti_trope_angle: str = Field(description="How the familiar trope is refreshed (motive, choice, consequence).")
    reference_titles: list[str] = Field(default_factory=list)
    audience_fit: int = Field(ge=1, le=10, description="Fit with Vietnamese short-drama listeners.")
    momentum: int = Field(ge=1, le=10, description="How strongly the scanned sources show this trend right now.")
    production_fit: int = Field(ge=1, le=10, description="How well it works as dialogue-only audio with 2-4 recurring actors.")
    score: float = Field(0.0, description="Set by Trend Ranking.")
    rationale: str = ""


class MarketAnalysis(BaseModel):
    """Structured output of the Content Analyze LLM call."""

    insights: list[ContentInsight] = Field(default_factory=list)
    candidates: list[TrendCandidate] = Field(min_length=1, max_length=8)


class FormatSpec(BaseModel):
    medium: Literal["audio_micro_drama", "audio_long_story"] = "audio_micro_drama"
    language: Literal["vi-VN"] = "vi-VN"
    episodes: int = Field(30, ge=10, le=30)
    episode_seconds_min: int = Field(60, ge=20, le=600)
    episode_seconds_max: int = Field(120, ge=20, le=900)

    @model_validator(mode="after")
    def _range(self) -> FormatSpec:
        if self.episode_seconds_max < self.episode_seconds_min:
            raise ValueError("episode_seconds_max must be >= episode_seconds_min")
        return self


class TrendBrief(BaseModel):
    """Market Research Agent output; the Script Writer Agent's input."""

    brief_id: str
    created_at: str
    topic: str
    target_audience: str
    format_spec: FormatSpec = Field(default_factory=FormatSpec)
    theme_category: ThemeCategory
    hook: str = ""
    premise: str = ""
    anti_trope_angle: str = ""
    reference_titles: list[str] = Field(default_factory=list)
    score: float = 0.0
    candidates: list[TrendCandidate] = Field(default_factory=list, description="Every ranked candidate, best first; the brief is the first.")
    insights: list[ContentInsight] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list, description="Seed files and URLs that were scanned.")
    platforms: list[str] = Field(default_factory=list)
    notes: str = ""
    genre: str = Field("", description="Trending genre of the selected candidate.")
    guide: str = Field("", description="The research guide the editor gave the agent.")
    selected: int = Field(0, ge=0, description="Index in `candidates` of the genre the editor picked; the top-level fields mirror it.")
    scan_id: str | None = Field(None, description="The scan that produced this brief (progress, screenshots).")

    def with_selected(self, index: int) -> TrendBrief:
        """The same brief with candidate ``index`` as the direction handed to the Script Writer."""
        if not 0 <= index < len(self.candidates):
            raise ValueError(f"candidate {index} does not exist (the brief has {len(self.candidates)})")
        c = self.candidates[index]
        return self.model_copy(update={
            "selected": index, "topic": c.topic, "target_audience": c.target_audience, "theme_category": c.theme_category, "hook": c.hook,
            "premise": c.premise, "anti_trope_angle": c.anti_trope_angle, "reference_titles": list(c.reference_titles), "score": c.score, "genre": c.genre})


class ScanStep(BaseModel):
    """One source the Market Scan skill read (or tried to), as shown live in the web client."""

    platform: str
    url: str = ""
    label: str = ""
    status: Literal["pending", "running", "ok", "blocked", "error"] = "pending"
    title: str = ""
    chars: int = 0
    excerpt: str = Field("", description="First lines of the text that was read.")
    screenshot: str | None = Field(None, description="File name of the page screenshot under the scan's folder.")
    detail: str = Field("", description="Why the source was blocked or failed.")
    elapsed_s: float = 0.0


class ScanState(BaseModel):
    """Progress of one Market Research run: Market Scan -> Content Analyze -> Trend Ranking."""

    scan_id: str
    status: Literal["running", "done", "failed"] = "running"
    phase: Literal["scan", "analyze", "rank", "done"] = "scan"
    created_at: str
    finished_at: str | None = None
    guide: str = ""
    focus: str = ""
    use_browser: bool = False
    platforms: list[str] = Field(default_factory=list)
    steps: list[ScanStep] = Field(default_factory=list)
    log: list[str] = Field(default_factory=list)
    brief_id: str | None = None
    error: str | None = None
