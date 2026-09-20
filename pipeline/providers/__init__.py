"""TTS provider adapters. Skills call `get_provider(name).synthesize(req, out)` and nothing else."""

from __future__ import annotations

from pipeline.providers.base import StemInfo, TtsProvider, TtsRequest

PROVIDER_NAMES = ("elevenlabs", "minimax")


def get_provider(name: str) -> TtsProvider:
    if name == "elevenlabs":
        from pipeline.providers.elevenlabs import ElevenLabsProvider

        return ElevenLabsProvider()
    if name == "minimax":
        from pipeline.providers.minimax import MiniMaxProvider

        return MiniMaxProvider()
    raise ValueError(f"unknown provider {name!r}; expected one of {PROVIDER_NAMES}")


__all__ = ["PROVIDER_NAMES", "StemInfo", "TtsProvider", "TtsRequest", "get_provider"]
