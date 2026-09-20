"""Director metadata -> provider text and settings. The intensity table lives in CLAUDE.md.

ElevenLabs gets a numeric settings vector (stability / similarity / style). Gemini TTS has no such
knobs: the same metadata is rendered as a short Vietnamese acting direction in `settings["style"]`
and the adapter prefixes it to the text. Audio tags are kept only on eleven_v3; on every other
model they are removed from the text and, for Gemini, folded into the direction.
"""

from __future__ import annotations

import re

from pipeline.schema import MONOLOGUE_TAGS, Line
from pipeline.text.vi_normalize import normalize_vi

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
PACE_SPEED = {"slow": 0.85, "normal": 1.0, "fast": 1.15}


def _intensity_word(i: int) -> str:
    return next(word for limit, word in INTENSITY_VI if i <= limit)


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
        hint = TAG_VI.get(tag)
        if hint and hint not in bits:
            bits.append(hint)
    if line.acoustic_direction:
        bits.append(line.acoustic_direction.strip().rstrip("."))
    return ", ".join(bits)


def settings_for_line(line: Line, provider: str, model_id: str, defaults: dict | None = None) -> dict:
    i = line.emotional_intensity
    mono = line.is_monologue()
    s: dict = dict(defaults or {})
    if provider == "elevenlabs":
        if model_id == "eleven_v3":
            # v3 stability is discrete: 0.0 Creative / 0.5 Natural / 1.0 Robust.
            stability, similarity = (0.5, 0.80) if i <= 3 else (0.5, 0.75) if i <= 6 else (0.0, 0.65) if i <= 8 else (0.0, 0.55)
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
    else:
        raise ValueError(f"unknown provider {provider}")
    return s


def text_for_provider(line: Line, provider: str, model_id: str, *, normalize: bool = True) -> str:
    text = normalize_vi(line.tts_text) if normalize else line.tts_text
    if provider == "elevenlabs" and model_id == "eleven_v3":
        if line.is_monologue() and not any(t in line.audio_tags() for t in MONOLOGUE_TAGS):
            text = f"[{MONOLOGUE_TAGS[1]}] {text}"
        return text
    return _TAG_RE.sub("", text).strip()  # tags unsupported on v2 / flash / Gemini (folded into the style there)
