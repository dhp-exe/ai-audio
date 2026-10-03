"""Sound Engineer Agent contracts: voice render result and the mastered episode."""

from __future__ import annotations

from pydantic import BaseModel, Field


class StemRecord(BaseModel):
    """One rendered (or cached) render unit."""

    unit_id: str
    stem: str
    provider: str
    model_id: str
    voice_id: str
    duration_ms: int = 0
    characters: int = 0
    cached: bool = False
    placeholder: bool = False
    attempt: int = 0


class VoiceRenderResult(BaseModel):
    series_id: str
    episode_number: int
    planned: int
    rendered: int
    cached: int
    failed: list[str] = Field(default_factory=list)
    characters: int = 0
    cost_usd: float = 0.0
    placeholder_voices: list[str] = Field(default_factory=list)
    stems: list[StemRecord] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)


class LoudnessMetrics(BaseModel):
    integrated_lufs: float
    true_peak_dbtp: float
    lra: float | None = None
    target_lufs: float = -16.0
    target_true_peak_dbtp: float = -1.5


class MasteredEpisode(BaseModel):
    """Sound Engineer Agent output: where the compiled master lives and what it measures."""

    series_id: str
    episode_number: int = Field(ge=1, le=99)
    title: str = ""
    wav_path: str = Field(description="Storage key of the stereo WAV master.")
    mp3_path: str = Field(description="Storage key of the MP3 master.")
    timeline_path: str
    duration_ms: int = Field(gt=0)
    loudness: LoudnessMetrics
    stems: int = Field(ge=1)
    rendered: int = 0
    cached: int = 0
    characters: int = 0
    silence_ms: int = 0
    bgm: bool = False
    sfx: int = 0
    placeholder_voices: list[str] = Field(default_factory=list)
    attempt: int = 0
    mastered_at: str = ""
