"""TTS provider adapters. The Sound Engineer calls ``get_provider(name).synthesize(req, out)`` and nothing else.

Adding an engine (for example a self-hosted cloned-voice model) is one class with
``name`` and ``synthesize(req: TtsRequest, out: Path) -> StemInfo`` plus one line:

    from emvoox.providers.tts import register_provider
    register_provider("my-engine", MyEngineProvider)

and a catalog entry (models, label) in ``catalog.py`` so the UI and the engine policy know it.
"""

from __future__ import annotations

from collections.abc import Callable

from emvoox.providers.tts.base import ProviderError, StemInfo, TtsProvider, TtsRequest
from emvoox.providers.tts.catalog import DEFAULT_MODEL, PROVIDER_NAMES, catalog, model_ids

_factories: dict[str, Callable[[], TtsProvider]] = {}


def register_provider(name: str, factory: Callable[[], TtsProvider]) -> None:
    _factories[name] = factory


def get_provider(name: str) -> TtsProvider:
    if name in _factories:
        return _factories[name]()
    if name == "elevenlabs":
        from emvoox.providers.tts.elevenlabs import ElevenLabsProvider

        return ElevenLabsProvider()
    if name == "gemini":
        from emvoox.providers.tts.gemini import GeminiTtsProvider

        return GeminiTtsProvider()
    if name == "wavespeed":
        from emvoox.providers.tts.wavespeed import WaveSpeedTtsProvider

        return WaveSpeedTtsProvider()
    if name == "mock":
        from emvoox.providers.tts.mock import MockTtsProvider

        return MockTtsProvider()
    raise ValueError(f"unknown provider {name!r}; expected one of {PROVIDER_NAMES}")


def default_concurrency(name: str) -> int:
    """Free-tier Gemini TTS is rate limited per minute; keep it serial."""
    return 1 if name == "gemini" else 2


__all__ = ["DEFAULT_MODEL", "PROVIDER_NAMES", "ProviderError", "StemInfo", "TtsProvider", "TtsRequest", "catalog", "default_concurrency",
           "get_provider", "model_ids", "register_provider"]
