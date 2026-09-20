"""Director metadata -> provider text and settings. The intensity table lives in CLAUDE.md."""

from __future__ import annotations

import re

from pipeline.schema import MONOLOGUE_TAGS, Line
from pipeline.text.vi_normalize import normalize_vi

_TAG_RE = re.compile(r"\[[^\[\]]+\]\s*")

MINIMAX_EMOTION = {
    "neutral": "neutral", "happy": "happy", "sad": "sad", "angry": "angry",
    "fearful": "fearful", "surprised": "surprised", "disgusted": "disgusted",
    "tender": "happy", "sarcastic": "neutral", "desperate": "sad",
}
PACE_SPEED = {"slow": 0.85, "normal": 1.0, "fast": 1.15}
VOLUME_GAIN = {"whisper": 0.5, "soft": 0.8, "normal": 1.0, "loud": 1.3, "shout": 1.6}


def settings_for_line(line: Line, provider: str, model_id: str, defaults: dict | None = None) -> dict:
    i = line.emotional_intensity
    mono = line.is_monologue()
    s: dict = dict(defaults or {})
    if provider == "elevenlabs":
        if model_id == "eleven_v3":
            # v3 stability is discrete: 0.0 Creative / 0.5 Natural / 1.0 Robust.
            if i <= 3:
                s.setdefault("stability", 0.5); s.setdefault("similarity_boost", 0.80)
            elif i <= 6:
                s.setdefault("stability", 0.5); s.setdefault("similarity_boost", 0.75)
            elif i <= 8:
                s.setdefault("stability", 0.0); s.setdefault("similarity_boost", 0.65)
            else:
                s.setdefault("stability", 0.0); s.setdefault("similarity_boost", 0.55)
        else:  # eleven_multilingual_v2 and other continuous models
            base = 0.85 - 0.055 * i
            s.setdefault("stability", round(max(0.3, min(0.8, base - (0.1 if mono else 0.0))), 2))
            s.setdefault("similarity_boost", 0.75)
            s.setdefault("style", round(min(0.6, 0.05 * i + (0.1 if mono else 0.0)), 2))
        s.setdefault("use_speaker_boost", True)
    elif provider == "minimax":
        s.setdefault("emotion", MINIMAX_EMOTION[line.emotion.value])
        s.setdefault("speed", round(PACE_SPEED[line.pace] * (0.95 if mono else 1.0), 2))
        s.setdefault("vol", VOLUME_GAIN[line.volume])
    else:
        raise ValueError(f"unknown provider {provider}")
    return s


def text_for_provider(line: Line, provider: str, model_id: str, *, normalize: bool = True) -> str:
    text = normalize_vi(line.tts_text) if normalize else line.tts_text
    if provider == "elevenlabs" and model_id == "eleven_v3":
        if line.is_monologue() and not any(t in line.audio_tags() for t in MONOLOGUE_TAGS):
            text = f"[{MONOLOGUE_TAGS[1]}] {text}"
        return text
    return _TAG_RE.sub("", text).strip()  # tags unsupported on v2 / MiniMax
