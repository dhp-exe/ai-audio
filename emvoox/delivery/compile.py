"""Delivery Compile: Director metadata -> the text and settings each engine understands.

The intensity table lives in CLAUDE.md. ElevenLabs gets a numeric settings vector (stability /
similarity / style / speed). Gemini TTS has no such knobs: the same metadata is rendered as a
short Vietnamese acting direction in ``settings["style"]`` and the adapter prefixes it to the text.
WaveSpeed follows the vendor family of its model path (ElevenLabs v3 or MiniMax). Audio tags are
kept only where the model reads them; everywhere else they are removed from the text and, for
Gemini, folded into the direction.
"""

from __future__ import annotations

import re

from emvoox.contracts.production import MONOLOGUE_TAGS, Line
from emvoox.providers.tts.catalog import supports_tags, voice_family
from emvoox.text.vi_normalize import normalize_vi

_TAG_RE = re.compile(r"\[[^\[\]]+\]\s*")

EMOTION_VI = {
    "neutral": "bình thản", "happy": "vui vẻ", "sad": "buồn", "angry": "giận dữ", "fearful": "sợ hãi",
    "surprised": "ngạc nhiên", "disgusted": "khinh ghét", "tender": "dịu dàng, trìu mến", "sarcastic": "mỉa mai",
    "desperate": "tuyệt vọng",
}
INTENSITY_VI = ((3, "nhẹ"), (6, "vừa phải"), (8, "mạnh"), (10, "rất mạnh, cao trào"))
PACE_VI = {"slow": "nói chậm", "normal": "", "fast": "nói nhanh"}
VOLUME_VI = {"whisper": "thì thầm", "soft": "nhỏ nhẹ", "normal": "", "loud": "lớn tiếng", "shout": "hét lên"}
TAG_VI = {
    "sighs": "thở dài trước khi nói", "laughs": "bật cười", "chuckles": "cười khẽ", "whispers": "thì thầm",
    "crying": "vừa khóc vừa nói", "sobbing": "nức nở", "gasps": "hít một hơi sửng sốt", "clears throat": "hắng giọng",
    "exhales": "thở hắt ra", "shouting": "quát lớn", "hesitates": "ngập ngừng", "pause": "ngắt một nhịp",
    "nervously": "lo lắng, run giọng", "sarcastic": "giọng mỉa mai", "excited": "hào hứng", "angry": "giận dữ",
    "sad": "buồn bã", "tired": "mệt mỏi", "internal monologue": "độc thoại nội tâm", "introspective": "trầm tư",
}
PACE_SPEED = {"slow": 0.9, "normal": 1.0, "fast": 1.1}
MINIMAX_EMOTION = {
    "neutral": "neutral", "happy": "happy", "sad": "sad", "angry": "angry", "fearful": "fearful", "surprised": "surprised",
    "disgusted": "disgusted", "tender": "neutral", "sarcastic": "neutral", "desperate": "sad",
}
MINIMAX_VOLUME = {"whisper": 0.6, "soft": 0.8, "normal": 1.0, "loud": 1.3, "shout": 1.6}
RETRY_DIRECTION_VI = "đọc thật rõ ràng, đầy đủ từng chữ, không bỏ sót hay thêm lời nào"


def _intensity_word(i: int) -> str:
    return next(word for limit, word in INTENSITY_VI if i <= limit)


def speed_for(line: Line) -> float:
    """Speaking-rate multiplier for the unit contract (and for engines with a speed knob)."""
    return PACE_SPEED.get(line.pace, 1.0)


def gemini_style(line: Line) -> str:
    """One-sentence Vietnamese acting direction for Gemini TTS, built from the Director's metadata."""
    bits = [f"Nói tiếng Việt, giọng {EMOTION_VI[line.emotion.value]} ({_intensity_word(line.emotional_intensity)})"]
    if line.is_monologue():
        bits.append("độc thoại nội tâm, như tự nói với chính mình, mic gần")
    for key in ("pace", "volume"):
        word = (PACE_VI if key == "pace" else VOLUME_VI).get(getattr(line, key), "")
        if word:
            bits.append(word)
    for tag in line.audio_tags():
        if tag in MONOLOGUE_TAGS:
            continue  # already expressed by the monologue direction above
        hint = TAG_VI.get(tag)
        if hint and hint not in bits:
            bits.append(hint)
    if line.acoustic_direction:
        bits.append(line.acoustic_direction.strip().rstrip("."))
    return ", ".join(bits)


def _v3_settings(i: int) -> tuple[float, float]:
    # v3 stability is discrete: 0.0 Creative / 0.5 Natural / 1.0 Robust.
    return (0.5, 0.80) if i <= 3 else (0.5, 0.75) if i <= 6 else (0.0, 0.65) if i <= 8 else (0.0, 0.55)


def settings_for_line(line: Line, provider: str, model_id: str, defaults: dict | None = None) -> dict:
    """Engine settings for one line. ``defaults`` are the voice's own settings from the registry
    (the identity anchor of a cloned voice): what they pin is never overridden by the line."""
    i = line.emotional_intensity
    mono = line.is_monologue()
    s: dict = dict(defaults or {})
    if provider == "elevenlabs":
        if model_id == "eleven_v3":
            stability, similarity = _v3_settings(i)
            s.setdefault("stability", stability)
            s.setdefault("similarity_boost", similarity)
        else:  # eleven_multilingual_v2 / flash: continuous
            base = 0.85 - 0.055 * i
            s.setdefault("stability", round(max(0.3, min(0.8, base - (0.1 if mono else 0.0))), 2))
            s.setdefault("similarity_boost", 0.75)
            s.setdefault("style", round(min(0.6, 0.05 * i + (0.1 if mono else 0.0)), 2))
        s.setdefault("use_speaker_boost", True)
    elif provider == "gemini":
        s.setdefault("style", gemini_style(line))
    elif provider == "wavespeed":
        if model_id.startswith("elevenlabs/"):
            s.setdefault("stability", _v3_settings(i)[0])
        elif voice_family(provider, model_id) == "gemini":
            s.setdefault("style", gemini_style(line))
        elif model_id.startswith("minimax/"):
            s.setdefault("emotion", MINIMAX_EMOTION[line.emotion.value])
            s.setdefault("speed", speed_for(line))
            s.setdefault("volume", MINIMAX_VOLUME[line.volume])
    elif provider == "mock":
        pass
    else:
        raise ValueError(f"unknown provider {provider}")
    return s


def retry_settings(settings: dict, provider: str, model_id: str, attempt: int) -> dict:
    """Settings for the n-th automatic retry of a unit the QA Critic flagged: each attempt moves
    the engine toward its most literal, stable delivery."""
    if attempt <= 0:
        return dict(settings)
    s = dict(settings)
    v3_like = (provider == "elevenlabs" and model_id == "eleven_v3") or (provider == "wavespeed" and model_id.startswith("elevenlabs/"))
    if v3_like:
        s["stability"] = 0.5 if attempt == 1 else 1.0
    elif provider == "elevenlabs":
        s["stability"] = round(min(0.9, float(s.get("stability", 0.5)) + 0.15 * attempt), 2)
        s["style"] = round(max(0.0, float(s.get("style", 0.0)) - 0.15 * attempt), 2)
    elif voice_family(provider, model_id) == "gemini":
        style = str(s.get("style", "")).rstrip(":;,. ")
        s["style"] = f"{style}, {RETRY_DIRECTION_VI}" if style else RETRY_DIRECTION_VI.capitalize()
    elif provider == "wavespeed" and model_id.startswith("minimax/"):
        s["speed"] = 1.0
        s["emotion"] = "neutral"
    return s


def text_for_provider(line: Line, provider: str, model_id: str, *, normalize: bool = True) -> str:
    text = normalize_vi(line.tts_text) if normalize else line.tts_text
    if supports_tags(provider, model_id):
        if line.is_monologue() and not any(t in line.audio_tags() for t in MONOLOGUE_TAGS):
            text = f"[{MONOLOGUE_TAGS[1]}] {text}"
        return text
    return _TAG_RE.sub("", text).strip()  # tags unsupported on v2 / flash / Gemini / MiniMax (folded into the style on Gemini)
