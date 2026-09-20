"""Common request/response shapes and audio helpers for TTS providers."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

StemInfo = dict[str, Any]  # {"duration_ms": int, "characters_billed": int, "alignment"?: {...}, ...}


@dataclass(frozen=True)
class TtsRequest:
    provider: str
    model_id: str
    voice_id: str
    text: str
    settings: dict = field(default_factory=dict)
    line_id: str | None = None
    previous_text: str | None = None  # prosody context (same speaker), not part of the cache hash
    next_text: str | None = None

    def content_hash(self) -> str:
        payload = json.dumps(
            {"provider": self.provider, "model_id": self.model_id, "voice_id": self.voice_id,
             "text": self.text, "settings": dict(sorted(self.settings.items()))},
            sort_keys=True, ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict:
        return {"provider": self.provider, "model_id": self.model_id, "voice_id": self.voice_id,
                "text": self.text, "settings": self.settings, "line_id": self.line_id}


class TtsProvider(Protocol):
    name: str

    def synthesize(self, req: TtsRequest, out: Path) -> StemInfo: ...


class ProviderError(RuntimeError):
    """Vendor call failed after retries. `retryable` tells the caller whether a fallback provider makes sense."""

    def __init__(self, message: str, *, retryable: bool = False, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


# ---- audio helpers ---------------------------------------------------------------------


def to_stem_wav(audio_bytes: bytes, out: Path, *, src_suffix: str) -> None:
    """Write provider audio (wav/mp3/pcm...) as the canonical stem: WAV 44.1 kHz / 16-bit / mono."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=src_suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = Path(tmp.name)
    try:
        cmd = ["ffmpeg", "-v", "error", "-y"]
        if src_suffix == ".pcm":
            cmd += ["-f", "s16le", "-ar", "44100", "-ac", "1"]
        cmd += ["-i", str(tmp_path), "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", str(out)]
        subprocess.run(cmd, check=True)
    finally:
        tmp_path.unlink(missing_ok=True)


def duration_ms(path: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return int(round(float(out) * 1000))
