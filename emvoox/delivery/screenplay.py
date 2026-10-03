"""Rule-based reading of the raw screenplay format the Script Writer renders (``EpisodeDraft.render``).

    TẬP 01 - Bản hợp đồng

    CẢNH 1. Sân thượng. Đêm.
    (gió, tiếng thành phố xa)
    LINH (nội tâm): Ba năm. Tôi đã xóa số.
    KHÔI (khẽ, kìm nén): Anh xin lỗi.

Used by the offline mock LLM and as the Director's fallback when the LLM's EpisodeScript is rejected
twice: the lines are kept verbatim and get neutral, safe delivery defaults.
"""

from __future__ import annotations

import re

from emvoox.contracts.production import PROTAGONIST_ALIAS, EpisodeScript, slugify_id

_TITLE = re.compile(r"^TẬP\s+(\d+)\s*[-–:]\s*(.+)$", re.IGNORECASE)
_SCENE = re.compile(r"^CẢNH\s+(\d+)\s*[.:\-]\s*(.*)$", re.IGNORECASE)
_LINE = re.compile(r"^([^:()]{1,60}?)\s*(?:\(([^)]*)\))?\s*:\s*(.+)$")
_INNER = re.compile(r"nội\s*tâm", re.IGNORECASE)

# keyword -> (emotion, intensity) for the direction in parentheses; first match wins
_EMOTION_HINTS: tuple[tuple[str, str, int], ...] = (
    ("hét", "angry", 8), ("quát", "angry", 8), ("giận", "angry", 7), ("lạnh", "sarcastic", 6), ("mỉa", "sarcastic", 6),
    ("khóc", "sad", 7), ("nghẹn", "sad", 7), ("buồn", "sad", 5), ("run", "fearful", 7), ("sợ", "fearful", 7),
    ("hoảng", "fearful", 8), ("sốc", "surprised", 7), ("ngạc nhiên", "surprised", 6), ("cười", "happy", 5), ("vui", "happy", 5),
    ("dịu", "tender", 4), ("khẽ", "tender", 4), ("thì thầm", "tender", 4), ("tuyệt vọng", "desperate", 8), ("van", "desperate", 7),
)
_TIME = (("đêm", "night"), ("tối", "evening"), ("chiều", "afternoon"), ("sáng", "morning"), ("bình minh", "dawn"))


def _delivery(direction: str, inner: bool) -> tuple[str, int, str, str]:
    d = direction.lower()
    emotion, intensity = "neutral", 4
    for word, emo, level in _EMOTION_HINTS:
        if word in d:
            emotion, intensity = emo, level
            break
    volume = "whisper" if "thì thầm" in d else "soft" if inner or any(w in d for w in ("khẽ", "nhỏ", "dịu")) else \
        "loud" if any(w in d for w in ("hét", "quát", "lớn")) else "normal"
    pace = "slow" if inner or any(w in d for w in ("chậm", "ngập ngừng")) else "fast" if any(w in d for w in ("nhanh", "gấp", "dồn")) else "normal"
    return emotion, intensity, pace, volume


def parse_screenplay(raw: str, *, series_id: str, episode_number: int, target_duration_sec: int,
                     role_to_actor: dict[str, str], protagonist_id: str = "", cliffhanger: str = "") -> EpisodeScript:
    """Raw screenplay text -> EpisodeScript. Unknown speakers raise ``ValueError``."""
    lookup = {k.lower(): v for k, v in role_to_actor.items()}
    title = f"Tập {episode_number}"
    scenes: list[dict] = []
    ep = f"ep{episode_number:02d}"
    for raw_line in raw.splitlines():
        text = raw_line.strip()
        if not text:
            continue
        m = _TITLE.match(text)
        if m and not scenes:
            title = m.group(2).strip()
            continue
        m = _SCENE.match(text)
        if m:
            heading = m.group(2).strip() or f"Cảnh {len(scenes) + 1}"
            tod = next((t for word, t in _TIME if word in heading.lower()), "unspecified")
            scenes.append({"scene_id": f"sc{len(scenes) + 1:02d}", "title": heading[:80], "location": heading.split(".")[0][:80] or heading[:80],
                           "time_of_day": tod, "lines": []})
            continue
        if text.startswith("(") and text.endswith(")"):
            continue  # atmosphere line: no narrator in this format (D3), BGM/SFX are disabled (D5/D6)
        m = _LINE.match(text)
        if not m:
            continue
        speaker, direction, spoken = m.group(1).strip(), (m.group(2) or "").strip(), m.group(3).strip()
        if not scenes:
            scenes.append({"scene_id": "sc01", "title": "Cảnh 1", "location": "Không xác định", "time_of_day": "unspecified", "lines": []})
        inner = bool(_INNER.search(direction))
        actor = lookup.get(speaker.lower()) or lookup.get(slugify_id(speaker))
        if actor is None:
            raise ValueError(f"speaker {speaker!r} is not in the cast")
        emotion, intensity, pace, volume = _delivery(direction, inner)
        sc = scenes[-1]
        n = len(sc["lines"]) + 1
        sc["lines"].append({
            "line_id": f"{ep}_{sc['scene_id']}_l{n:03d}",
            "type": "monologue" if inner else "dialogue",
            "character_id": (protagonist_id or PROTAGONIST_ALIAS) if inner else actor,
            "role_name": None,  # the Director fills it from the cast
            "text": spoken,
            "tts_text": ("[introspective] " if inner else "") + spoken,
            "emotion": emotion, "emotional_intensity": intensity,
            "acoustic_direction": "nội tâm, mic gần" if inner else (direction or "tự nhiên"),
            "pace": pace, "volume": volume, "pause_after_ms": 500 if inner else 400, "sfx": [],
        })
    scenes = [s for s in scenes if s["lines"]]
    if not scenes:
        raise ValueError("no dialogue lines found in the screenplay")
    used = sorted({ln["character_id"] for s in scenes for ln in s["lines"] if ln["character_id"] != PROTAGONIST_ALIAS})
    last = scenes[-1]["lines"][-1]
    last["pause_after_ms"] = 500
    return EpisodeScript.model_validate({
        "series_id": series_id, "episode_number": episode_number, "title": title, "logline": scenes[0]["lines"][0]["text"][:160],
        "target_duration_sec": target_duration_sec, "characters_used": used, "scenes": scenes,
        "cliffhanger": cliffhanger or last["text"], "director_notes": "rule-based direction (no LLM)",
    })
