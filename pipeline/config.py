"""Environment-backed settings. Load once; never read os.environ in skills directly.

Defaults encode the section-0 decisions in docs/IMPLEMENTATION_PLAN.md.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    # keys
    gemini_api_key: str | None
    elevenlabs_api_key: str | None
    # LLM (D10)
    llm_model: str
    llm_temperature: float
    # TTS (D4)
    tts_provider: str  # elevenlabs | gemini
    tts_model: str | None  # None = provider default (catalog.DEFAULT_MODEL)
    # assembly (D5, D6, D8, D9)
    enable_bgm: bool
    enable_sfx: bool
    padding_ms: int
    padding_min_ms: int
    padding_max_ms: int
    use_director_pauses: bool
    scene_gap_ms: int
    loudness_lufs: float
    true_peak_dbtp: float
    mp3_bitrate: str
    # normalization (D1)
    normalize_vi: bool

    def require(self, name: str) -> str:
        value = getattr(self, name)
        if not value:
            raise RuntimeError(f"Missing required setting {name}; set it in .env (see .env.example)")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv()
    return Settings(
        gemini_api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"),
        elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY"),
        llm_model=os.getenv("AI_AUDIO_LLM_MODEL", "gemini-3.1-flash-lite"),
        llm_temperature=float(os.getenv("AI_AUDIO_LLM_TEMPERATURE", "0.4")),
        tts_provider=os.getenv("AI_AUDIO_TTS_PROVIDER", "elevenlabs"),
        tts_model=os.getenv("AI_AUDIO_TTS_MODEL") or None,
        enable_bgm=_bool("ENABLE_BGM", False),
        enable_sfx=_bool("ENABLE_SFX", False),
        padding_ms=int(os.getenv("AI_AUDIO_PADDING_MS", "400")),
        padding_min_ms=int(os.getenv("AI_AUDIO_PADDING_MIN_MS", "300")),
        padding_max_ms=int(os.getenv("AI_AUDIO_PADDING_MAX_MS", "500")),
        use_director_pauses=_bool("AI_AUDIO_USE_DIRECTOR_PAUSES", True),
        scene_gap_ms=int(os.getenv("AI_AUDIO_SCENE_GAP_MS", "800")),
        loudness_lufs=float(os.getenv("AI_AUDIO_LOUDNESS_LUFS", "-16")),
        true_peak_dbtp=float(os.getenv("AI_AUDIO_TRUE_PEAK_DBTP", "-1.5")),
        mp3_bitrate=os.getenv("AI_AUDIO_MP3_BITRATE", "192k"),
        normalize_vi=_bool("AI_AUDIO_NORMALIZE_VI", True),
    )
