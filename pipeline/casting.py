"""Casting helpers shared by episodize, the orchestrator, generate-voice and the web UI.

- placeholder premade voices (available on every ElevenLabs tier) by gender
- gender guessing from Vietnamese/English descriptions
- parsing of the director's '/actor' tags in role names or descriptions
"""

from __future__ import annotations

import os
import re

from pipeline.schema import StoryRole, VoiceRegistry

# Premade ElevenLabs voices. Override with AI_AUDIO_PLACEHOLDER_VOICES_FEMALE / _MALE (comma-separated).
PLACEHOLDER_VOICES: dict[str, list[str]] = {
    "female": os.getenv("AI_AUDIO_PLACEHOLDER_VOICES_FEMALE", "cgSgspJ2msm6clMCkdW9,pFZP5JQG7iQjIQuC4Bku,EXAVITQu4vr4xnSDxMaL").split(","),
    "male": os.getenv("AI_AUDIO_PLACEHOLDER_VOICES_MALE", "nPczCjzI2devNBz1zQrb,cjVigY5qzO86Huf0OWal,pqHfZKP75CvOlQylNhV4").split(","),
}

_FEMALE = re.compile(r"\b(nữ|cô|bà|chị|em gái|girl|female|woman|actress|mẹ)\b", re.IGNORECASE)
_MALE = re.compile(r"\b(nam|anh|ông|chú|cậu|boy|male|man|ceo|tổng giám đốc|bố|cha)\b", re.IGNORECASE)
_TAG = re.compile(r"(?:^|\s)[/#@]([a-z][a-z0-9-]{0,23})\b", re.IGNORECASE)


def guess_gender(*texts: str | None) -> str:
    blob = " ".join(t for t in texts if t)
    f, m = len(_FEMALE.findall(blob)), len(_MALE.findall(blob))
    return "female" if f > m else "male"


def placeholder_voice(gender: str, index: int = 0) -> str:
    pool = PLACEHOLDER_VOICES.get(gender) or PLACEHOLDER_VOICES["male"]
    return pool[index % len(pool)].strip()


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
