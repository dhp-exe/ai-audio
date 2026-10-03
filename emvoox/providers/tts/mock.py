"""Offline voice engine: a tone per voice instead of speech, at the canonical stem format.

For tests and the demo. Duration follows the text (about 3.6 words per second) so timelines,
loudness and QA behave like a real run. ``faults`` makes a unit come out broken on its first
attempt so the QA retry loop can be exercised:

    MockTtsProvider.faults = {"ep01_sc01_l002": "clip"}      # clip | truncate | silence | error; "clip*" = every attempt
    EMVOOX_MOCK_TTS_FAULTS="ep01_sc01_l002:clip,ep01_sc02_l001:truncate"
"""

from __future__ import annotations

import hashlib
import math
import os
import threading
import wave
from array import array
from pathlib import Path
from typing import ClassVar

from emvoox.providers.tts.base import ProviderError, StemInfo, TtsRequest

SAMPLE_RATE = 44_100
WORDS_PER_SEC = 3.6


def _env_faults() -> dict[str, str]:
    out: dict[str, str] = {}
    for part in os.getenv("EMVOOX_MOCK_TTS_FAULTS", "").split(","):
        if ":" in part:
            unit, kind = part.strip().split(":", 1)
            out[unit] = kind
    return out


class MockTtsProvider:
    name = "mock"
    faults: ClassVar[dict[str, str]] = {}
    calls: ClassVar[list[str]] = []
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def synthesize(self, req: TtsRequest, out: Path) -> StemInfo:
        unit = req.line_id or ""
        with self._lock:
            self.calls.append(unit)
        spec = {**_env_faults(), **self.faults}.get(unit) or ""
        fault = spec.rstrip("*") if spec and (req.attempt == 0 or spec.endswith("*")) else None  # "clip*" = broken on every attempt
        if fault == "error":
            raise ProviderError("mock: injected provider failure", retryable=True, status=503)
        words = max(1, len(req.text.split()))
        seconds = max(0.5, words / WORDS_PER_SEC)
        amplitude = 0.25
        if fault == "truncate":
            seconds = 0.12
        elif fault == "silence":
            amplitude = 0.0
        elif fault == "clip":
            amplitude = 1.6  # far over full scale: hard-clipped
        voices = [v for _, v in req.speakers] or [req.voice_id]
        freq = 140.0 + (int(hashlib.sha256(voices[0].encode()).hexdigest(), 16) % 160)
        n = int(seconds * SAMPLE_RATE)
        samples = array("h")
        two_pi_f = 2 * math.pi * freq / SAMPLE_RATE
        syllable = 2 * math.pi * 4.0 / SAMPLE_RATE  # 4 Hz envelope so the tone pulses like syllables
        fade = int(0.01 * SAMPLE_RATE)
        for i in range(n):
            env = 0.6 + 0.4 * math.sin(syllable * i)
            edge = min(1.0, i / fade, (n - i) / fade) if fade else 1.0
            v = amplitude * env * edge * math.sin(two_pi_f * i)
            samples.append(int(max(-1.0, min(1.0, v)) * 32767))
        out.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(samples.tobytes())
        return {"duration_ms": int(seconds * 1000), "characters_billed": len(req.text), "elapsed_s": 0.0, "mock_fault": fault}

    @classmethod
    def reset(cls) -> None:
        cls.faults = {}
        cls.calls = []
