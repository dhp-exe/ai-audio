"""TTS provider adapters. Skills call `get_provider(name).synthesize(req, out)` and nothing else.

Two engines: ElevenLabs (paid, account voices = the Voice IPs) and Gemini TTS (free tier, 30 fixed
prebuilt voices). See catalog.py for models and voices.
"""

from __future__ import annotations

from pipeline.providers.base import StemInfo, TtsProvider, TtsRequest
from pipeline.providers.catalog import DEFAULT_MODEL, PROVIDER_NAMES, catalog, model_ids


def get_provider(name: str) -> TtsProvider:
    if name == "elevenlabs":
        from pipeline.providers.elevenlabs import ElevenLabsProvider

        return ElevenLabsProvider()
    if name == "gemini":
        from pipeline.providers.gemini_tts import GeminiTtsProvider

        return GeminiTtsProvider()
    raise ValueError(f"unknown provider {name!r}; expected one of {PROVIDER_NAMES}")


def default_concurrency(name: str) -> int:
    """Free-tier Gemini TTS is rate limited per minute; keep it serial."""
    return 1 if name == "gemini" else 2


__all__ = ["DEFAULT_MODEL", "PROVIDER_NAMES", "StemInfo", "TtsProvider", "TtsRequest", "catalog", "default_concurrency",
           "get_provider", "model_ids"]
