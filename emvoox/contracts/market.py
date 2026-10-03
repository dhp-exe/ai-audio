"""Market Research Agent contracts: what was observed, how it was analysed, and the TrendBrief."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

PLATFORMS: tuple[str, ...] = ("dramabox", "reelshort", "tiktok", "douyin", "youtube", "local")


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
    """A story direction proposed from the insights, rated on three axes (1-10 each)."""

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
