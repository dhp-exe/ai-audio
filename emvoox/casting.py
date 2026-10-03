"""Casting helpers shared by episodize, the orchestrator, generate-voice and the web UI.

- placeholder voices by gender for both engines (ElevenLabs premade voices, Gemini prebuilt voices)
- gender guessing from Vietnamese/English descriptions
- parsing of the director's '/actor' tags in role names or descriptions
- the one-actor-one-role rule for user pins
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable

from pipeline.providers.catalog import gemini_voices
from pipeline.schema import StoryRole, VoiceRegistry

# Premade ElevenLabs voices (available on every tier). Override with AI_AUDIO_PLACEHOLDER_VOICES_FEMALE / _MALE.
PLACEHOLDER_VOICES: dict[str, list[str]] = {
    "female": os.getenv("AI_AUDIO_PLACEHOLDER_VOICES_FEMALE", "cgSgspJ2msm6clMCkdW9,pFZP5JQG7iQjIQuC4Bku,EXAVITQu4vr4xnSDxMaL").split(","),
    "male": os.getenv("AI_AUDIO_PLACEHOLDER_VOICES_MALE", "nPczCjzI2devNBz1zQrb,cjVigY5qzO86Huf0OWal,pqHfZKP75CvOlQylNhV4").split(","),
}
# Gemini prebuilt voices used for roles without a Voice IP, in preference order.
GEMINI_PLACEHOLDER_VOICES: dict[str, list[str]] = {
    "female": ["Aoede", "Callirrhoe", "Zephyr", "Autonoe", "Laomedeia", "Achernar", "Sulafat", "Kore"],
    "male": ["Puck", "Umbriel", "Iapetus", "Schedar", "Achird", "Fenrir", "Zubenelgenubi", "Charon"],
}

_FEMALE = re.compile(r"\b(nữ|cô|bà|chị|em gái|girl|female|woman|actress|mẹ)\b", re.IGNORECASE)
_MALE = re.compile(r"\b(nam|anh|ông|chú|cậu|boy|male|man|ceo|tổng giám đốc|bố|cha)\b", re.IGNORECASE)
_TAG = re.compile(r"(?:^|\s)[/#@]([a-z][a-z0-9-]{0,23})\b", re.IGNORECASE)


def guess_gender(*texts: str | None) -> str:
    blob = " ".join(t for t in texts if t)
    f, m = len(_FEMALE.findall(blob)), len(_MALE.findall(blob))
    return "female" if f > m else "male"


def placeholder_voice(gender: str, index: int = 0, provider: str = "elevenlabs", exclude: Iterable[str] = ()) -> str:
    """A stand-in voice of the given gender. `exclude` skips voices already used by the cast so
    two roles never share one; falls back to round-robin when the pool is exhausted."""
    gender = gender if gender in ("female", "male") else "male"
    if provider == "gemini":
        pool = GEMINI_PLACEHOLDER_VOICES[gender] + [v["id"] for v in gemini_voices(gender) if v["id"] not in GEMINI_PLACEHOLDER_VOICES[gender]]
    else:
        pool = [v.strip() for v in PLACEHOLDER_VOICES[gender]]
    ex = {e.lower() for e in exclude}
    free = [v for v in pool if v.lower() not in ex]
    pool = free or pool
    return pool[index % len(pool)]


def extract_actor_tag(text: str, registry: VoiceRegistry | None = None) -> tuple[str, str | None]:
    """Find '/ngan' (or '#ngan', '@ngan') in text. Returns (text without the tag, actor_id or None).
    When a registry is given, only ids that exist are accepted."""
    for m in _TAG.finditer(text):
        cand = m.group(1).lower()
        if registry is None or cand in registry.ids():
            cleaned = (text[: m.start()] + " " + text[m.end():]).strip()
            return re.sub(r"\s{2,}", " ", cleaned), cand
    return text, None


def apply_role_tags(roles: list[StoryRole], registry: VoiceRegistry) -> list[StoryRole]:
    """Resolve '/actor' tags in role names/descriptions into actor_id (explicit actor_id wins)."""
    out: list[StoryRole] = []
    for r in roles:
        name, tag1 = extract_actor_tag(r.name, registry)
        desc, tag2 = extract_actor_tag(r.description, registry)
        actor = r.actor_id or tag1 or tag2
        out.append(StoryRole(name=name, description=desc, actor_id=actor))
    return out


def duplicate_actor_pins(roles: list[StoryRole]) -> dict[str, list[str]]:
    """actor_id -> role names, for actors pinned to more than one role (one actor plays one role)."""
    seen: dict[str, list[str]] = {}
    for r in roles:
        if r.actor_id:
            seen.setdefault(r.actor_id, []).append(r.name)
    return {a: names for a, names in seen.items() if len(names) > 1}


def parse_roles_text(text: str) -> list[StoryRole]:
    """Parse a free-text character section: one role per line, 'Name (note): description'."""
    roles: list[StoryRole] = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("-•* ").strip()
        if not line or ":" not in line:
            continue
        name, desc = line.split(":", 1)
        name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()  # drop '(Nam chính)' suffix
        if name:
            roles.append(StoryRole(name=name, description=desc.strip()))
    return roles
