"""Casting helpers shared by the Script Writer, the Casting Agent, the Sound Engineer and the API.

- placeholder voices by gender for both engines (ElevenLabs premade voices, Gemini prebuilt voices)
- gender guessing from Vietnamese/English descriptions
- parsing of the director's '/actor' tags in role names or descriptions
- the one-actor-one-role rule for user pins
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable

from emvoox.contracts.production import StoryRole, VoiceRegistry
from emvoox.providers.tts.catalog import gemini_voices

# Premade ElevenLabs voices (available on every tier). Override with AI_AUDIO_PLACEHOLDER_VOICES_FEMALE / _MALE.
PLACEHOLDER_VOICES: dict[str, list[str]] = {
    "female": (os.getenv("EMVOOX_PLACEHOLDER_VOICES_FEMALE") or os.getenv("AI_AUDIO_PLACEHOLDER_VOICES_FEMALE")
               or "cgSgspJ2msm6clMCkdW9,pFZP5JQG7iQjIQuC4Bku,EXAVITQu4vr4xnSDxMaL").split(","),
    "male": (os.getenv("EMVOOX_PLACEHOLDER_VOICES_MALE") or os.getenv("AI_AUDIO_PLACEHOLDER_VOICES_MALE")
             or "nPczCjzI2devNBz1zQrb,cjVigY5qzO86Huf0OWal,pqHfZKP75CvOlQylNhV4").split(","),
}
# Gemini prebuilt voices used for roles without a Voice IP, in preference order.
GEMINI_PLACEHOLDER_VOICES: dict[str, list[str]] = {
    "female": ["Aoede", "Callirrhoe", "Zephyr", "Autonoe", "Laomedeia", "Achernar", "Sulafat", "Kore"],
    "male": ["Puck", "Umbriel", "Iapetus", "Schedar", "Achird", "Fenrir", "Zubenelgenubi", "Charon"],
}

# Fallback gender reading for roles whose gender nobody stated (the Script Writer normally fills RoleCast.gender).
# Strong words describe the role itself; weak ones are pronouns and kinship terms that may refer to someone else.
_STRONG_F = re.compile(r"\b(nữ|tiểu thư|thiên kim|phu nhân|cô gái|nữ chính|nữ hoàng|công chúa|bà chủ|female|woman|girl|actress)\b", re.IGNORECASE)
_STRONG_M = re.compile(r"\b(nam|tổng tài|thiếu gia|chàng trai|nam chính|ông chủ|tổng giám đốc|chủ tịch|ceo|male|man|boy|actor)\b", re.IGNORECASE)
_WEAK_F = re.compile(r"\b(cô|bà|chị|nàng|mẹ|vợ|em gái|con gái|bạn gái|hôn thê|she|her)\b", re.IGNORECASE)
_WEAK_M = re.compile(r"\b(anh|ông|chú|cậu|hắn|bố|cha|chồng|em trai|con trai|bạn trai|hôn phu|he|his)\b", re.IGNORECASE)
# Phrases that contain a gender word but say nothing about gender.
_NOISE = re.compile(r"miền nam|việt nam|phương nam|phía nam|tiếng anh|cô đơn|cô độc|cô lập|cô đọng", re.IGNORECASE)
_LEAD = re.compile(r"^\W*(nữ|nam)\b", re.IGNORECASE)
# Common Vietnamese given names (the last word of a name); a tie-breaker only.
_NAMES_F = set("vy vi lan mai hoa hương hồng ngân linh trang thảo nhi my mỹ ngọc yến uyên quyên hà hạnh diệp trâm thư nga loan oanh như quỳnh chi "
               "châu trinh tuyết mạn vân hằng nhung thu xuân diễm kiều tiên ly lệ thy hân vy trúc đào liên huyền phương thùy thúy dung nguyệt".split())
_NAMES_M = set("tuấn phong khải dương hùng dũng cường khoa khôi khang long sơn thành thắng trung tùng vũ hải huy hoàng đức đạt bảo quân kiên "
               "nghĩa phúc quang tài thịnh toàn trí việt thần hào hiếu lộc nhân tiến vinh nam kiệt đăng duy trường hưng thiên".split())
_TAG = re.compile(r"(?:^|\s)[/#@]([a-z][a-z0-9-]{0,23})\b", re.IGNORECASE)


def gender_of(name: str | None, *texts: str | None) -> str | None:
    """'female' / 'male' when the name and descriptions give a reason to say so, else None.

    Order: a description that opens with 'Nữ'/'Nam' decides; then a recognisable given name; then words
    that describe the role itself (tiểu thư, tổng tài...); then pronouns and kinship words."""
    descs = [_NOISE.sub(" ", t) for t in texts if t]
    for d in descs:
        lead = _LEAD.match(d)
        if lead:
            return "female" if lead.group(1).lower() == "nữ" else "male"
    blob = " ".join(descs)
    given = (name or "").strip().lower().split()[-1:] or [""]
    if given[0] in _NAMES_F:
        return "female"
    if given[0] in _NAMES_M:
        return "male"
    f, m = len(_STRONG_F.findall(blob)), len(_STRONG_M.findall(blob))
    if f != m:
        return "female" if f > m else "male"
    # pronouns and kinship words last: "bị chồng phản bội" is about someone else, so they only count when nothing better exists
    blob = f"{_NOISE.sub(' ', name or '')} {blob}"  # the name may carry a title: 'Bà Lý', 'Ông Trùm'
    f, m = len(_WEAK_F.findall(blob)), len(_WEAK_M.findall(blob))
    return None if f == m else ("female" if f > m else "male")


def guess_gender(*texts: str | None) -> str:
    """Best guess from free text (first argument may be a name); 'male' only when nothing at all points either way."""
    first, rest = (texts[0] if texts else None), texts[1:]
    return gender_of(first, *rest) or gender_of(None, *texts) or "male"


def placeholder_voice(gender: str, index: int = 0, provider: str = "elevenlabs", exclude: Iterable[str] = ()) -> str:
    """A stand-in voice of the given gender. `exclude` skips voices already used by the cast so
    two roles never share one; falls back to round-robin when the pool is exhausted."""
    gender = gender if gender in ("female", "male") else "male"
    if provider == "mock":
        pool = [f"mock-{gender}-{i}" for i in range(1, 9)]
    elif provider == "gemini":
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


# ---- the roster limit: named roles never outnumber the Voice IPs

MAIN_ROLE_TYPES = ("protagonist", "antagonist", "supporting")


def roster_capacity(registry: VoiceRegistry) -> dict[str, int]:
    """How many female and male Voice IPs the studio has: the most named roles of each gender a story may have."""
    cap = {"female": 0, "male": 0}
    for c in registry.actors():
        g = c.gender if c.gender in cap else guess_gender(c.display_name, c.voice_description, c.persona)
        cap[g] += 1
    return cap


def roster_rule_vi(cap: dict[str, int]) -> str:
    """The limit as an instruction for the Script Writer's prompts."""
    return (f"GIỚI HẠN DIỄN VIÊN: studio có {cap['female']} diễn viên nữ và {cap['male']} diễn viên nam cố định (Voice IP). Câu chuyện chỉ được có tối đa "
            f"{cap['female']} vai nữ và {cap['male']} vai nam CÓ TÊN (protagonist, antagonist, supporting). Không thêm nhân vật có tên vượt giới hạn này; "
            "hãy gộp hoặc bỏ vai thừa. Nhân vật nền không quan trọng với cốt truyện (người qua đường, nhân viên, đám đông, giọng qua điện thoại) "
            "đặt role_type = minor, chỉ dùng khi thật cần, mỗi vai vài câu.")


def over_capacity(roles: list, cap: dict[str, int]) -> list:
    """Named (non-minor) roles beyond the roster, least important first to go: pinned roles and the
    protagonist are kept, then antagonists, then supporting roles in script order. ``roles`` are
    RoleCast-like objects (role_name, role_type, gender, description, actor_id)."""
    if not any(cap.values()):
        return []  # no Voice IPs at all (offline demo, empty store): there is no roster to respect
    order = {"protagonist": 0, "antagonist": 1, "supporting": 2}
    main = [r for r in roles if r.role_type in MAIN_ROLE_TYPES]
    ranked = sorted(main, key=lambda r: (0 if getattr(r, "actor_id", None) else 1, order[r.role_type], roles.index(r)))
    seen = {"female": 0, "male": 0}
    extra = []
    for r in ranked:
        g = r.gender or guess_gender(r.role_name, r.description)
        seen[g] += 1
        if seen[g] > cap.get(g, 0) and r.role_type != "protagonist":
            extra.append(r)
    return extra
