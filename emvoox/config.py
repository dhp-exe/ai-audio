"""Environment-backed settings. Load once; never read os.environ in agents directly.

Variables are named ``EMVOOX_*``; the pre-refactor ``AI_AUDIO_*`` names are still read as a
fallback so an existing ``.env`` keeps working. Vendor keys keep their vendor names.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

LLM_PROVIDERS: tuple[str, ...] = ("gemini", "wavespeed", "openai", "anthropic", "mock")
DEFAULT_LLM_MODEL = {
    "gemini": "gemini-3.1-flash-lite",
    "wavespeed": "google/gemini-3.1-flash-lite",
    "openai": "gpt-5-mini",
    "anthropic": "claude-opus-5",
    "mock": "mock-llm",
}


def _env(name: str, default: str | None = None) -> str | None:
    """EMVOOX_<NAME>, then the legacy AI_AUDIO_<NAME>, then the default."""
    for key in (f"EMVOOX_{name}", f"AI_AUDIO_{name}"):
        v = os.getenv(key)
        if v is not None and v.strip() != "":
            return v.strip()
    return default


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    # storage
    data_dir: Path
    storage_backend: str  # local | v1ron (not available yet)
    doc_store: str  # json | sqlite
    # keys
    gemini_api_key: str | None
    elevenlabs_api_key: str | None
    wavespeed_api_key: str | None
    openai_api_key: str | None
    anthropic_api_key: str | None
    # LLM
    llm_provider: str
    llm_model: str
    llm_temperature: float
    # TTS
    tts_provider: str  # gemini | elevenlabs | wavespeed | mock
    tts_model: str | None  # None = provider default (catalog.DEFAULT_MODEL)
    tts_batching: str  # auto | line | scene
    prefer_cloned_voices: bool
    # assembly
    enable_bgm: bool
    enable_sfx: bool
    bgm_gain_db: float
    padding_ms: int
    padding_min_ms: int
    padding_max_ms: int
    use_director_pauses: bool
    scene_gap_ms: int
    loudness_lufs: float
    true_peak_dbtp: float
    mp3_bitrate: str
    normalize_vi: bool
    # QA + gate
    qa_max_retries: int
    qa_pass_score: int
    qa_transcribe: bool
    cliffhanger_check: bool
    cliffhanger_min_score: int
    auto_approve: bool
    halt_on_qa_fail: bool
    # market research
    research_use_browser: bool

    def require(self, name: str) -> str:
        value = getattr(self, name)
        if not value:
            raise RuntimeError(f"Missing required setting {name}; set it in .env (see .env.example)")
        return value

    def key_for(self, provider: str) -> str | None:
        return {
            "gemini": self.gemini_api_key, "elevenlabs": self.elevenlabs_api_key, "wavespeed": self.wavespeed_api_key,
            "openai": self.openai_api_key, "anthropic": self.anthropic_api_key, "mock": "mock",
        }.get(provider)

    def keys_present(self) -> dict[str, bool]:
        return {p: bool(self.key_for(p)) for p in ("gemini", "elevenlabs", "wavespeed", "openai", "anthropic")}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    if os.getenv("EMVOOX_SKIP_DOTENV", "").lower() not in ("1", "true", "yes"):  # tests run with no vendor keys
        load_dotenv(REPO_ROOT / ".env")
        load_dotenv()
    llm_provider = (_env("LLM_PROVIDER", "gemini") or "gemini").lower()
    llm_model = _env("LLM_MODEL")
    if not llm_model or llm_provider == "mock" or (llm_provider == "wavespeed" and "/" not in llm_model):
        # a bare Gemini id left in .env must not be sent to a gateway that expects vendor/model
        llm_model = DEFAULT_LLM_MODEL.get(llm_provider, DEFAULT_LLM_MODEL["gemini"])
    tts_provider = (_env("TTS_PROVIDER", "gemini") or "gemini").lower()
    tts_model = _env("TTS_MODEL")
    if tts_model and tts_provider != "wavespeed":
        from emvoox.providers.tts.catalog import model_ids

        if tts_model not in model_ids(tts_provider):
            tts_model = None  # a model of another engine (e.g. a legacy eleven_v3 default) never leaks into this one
    return Settings(
        data_dir=Path(_env("DATA_DIR") or (REPO_ROOT / "data")).expanduser().resolve(),
        storage_backend=(_env("STORAGE", "local") or "local").lower(),
        doc_store=(_env("DOC_STORE", "json") or "json").lower(),
        gemini_api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or None,
        elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY") or None,
        wavespeed_api_key=os.getenv("WAVESPEED_API_KEY") or None,
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        llm_provider=llm_provider,
        llm_model=llm_model,
        llm_temperature=float(_env("LLM_TEMPERATURE", "0.4") or 0.4),
        tts_provider=tts_provider,
        tts_model=tts_model,
        tts_batching=_env("TTS_BATCHING", "auto") or "auto",
        prefer_cloned_voices=_bool(_env("PREFER_CLONED_VOICES"), True),
        enable_bgm=_bool(os.getenv("ENABLE_BGM"), False),
        enable_sfx=_bool(os.getenv("ENABLE_SFX"), False),
        bgm_gain_db=float(_env("BGM_GAIN_DB", "-20") or -20),
        padding_ms=int(_env("PADDING_MS", "400") or 400),
        padding_min_ms=int(_env("PADDING_MIN_MS", "300") or 300),
        padding_max_ms=int(_env("PADDING_MAX_MS", "500") or 500),
        use_director_pauses=_bool(_env("USE_DIRECTOR_PAUSES"), True),
        scene_gap_ms=int(_env("SCENE_GAP_MS", "800") or 800),
        loudness_lufs=float(_env("LOUDNESS_LUFS", "-16") or -16),
        true_peak_dbtp=float(_env("TRUE_PEAK_DBTP", "-1.5") or -1.5),
        mp3_bitrate=_env("MP3_BITRATE", "192k") or "192k",
        normalize_vi=_bool(_env("NORMALIZE_VI"), True),
        qa_max_retries=int(_env("QA_MAX_RETRIES", "3") or 3),
        qa_pass_score=int(_env("QA_PASS_SCORE", "80") or 80),
        qa_transcribe=_bool(_env("QA_TRANSCRIBE"), False),
        cliffhanger_check=_bool(_env("CLIFFHANGER_CHECK"), True),
        cliffhanger_min_score=int(_env("CLIFFHANGER_MIN_SCORE", "6") or 6),
        auto_approve=_bool(_env("AUTO_APPROVE"), False),
        halt_on_qa_fail=_bool(_env("HALT_ON_QA_FAIL"), True),
        research_use_browser=_bool(_env("RESEARCH_USE_BROWSER"), False),
    )


def reset_settings() -> None:
    """Drop the cached settings (tests and the demo switch data dirs and keys)."""
    get_settings.cache_clear()
