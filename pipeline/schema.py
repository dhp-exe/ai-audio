"""Single source of truth for data that crosses stage boundaries.

- ``StoryInput``     : the sectioned story the director fills in (overview, roles, script).
- ``SeriesOutline``  : what the episodize LLM call returns (casting + episode plan).
- ``EpisodeDraft``   : what the per-episode drafting call returns (structured scenes/lines).
- ``SeriesBible``    : ``series/<id>/series.json``.
- ``EpisodeScript``  : what the AI Director must return (structured output contract).
- ``VoiceRegistry``  : ``library/voice-ips.json`` (global, locked Voice IP registry of *actors*).
- ``Timeline``       : computed after TTS by assemble-audio; absolute placement of every stem.

Vocabulary: a **role** is a character in the story ("Tô Mạn"); an **actor** is a Voice IP in the
registry ("ngan"). Casting maps roles to actors. Stems and ``character_id`` always carry the actor id.

Decisions baked in (docs/IMPLEMENTATION_PLAN.md section 0):
    D1 Vietnamese-first (language fixed to "vi-VN").
    D3 No third-person narrator. Inner voice = ``type: monologue`` on the protagonist, with the
       alias ``character_id: "protagonist"`` resolved to the real id by parse-script.
    D4 No speech-to-speech.
    D5/D6 BGM and SFX are optional in the schema and disabled by config.

Run ``python -m pipeline.schema`` to print the JSON Schema for EpisodeScript.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SCHEMA_VERSION = "1.0"
LANGUAGE = "vi-VN"

CHARACTER_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,23}$")
LINE_ID_RE = re.compile(r"^ep\d{2}_sc\d{2}_l\d{3}$")
SCENE_ID_RE = re.compile(r"^sc\d{2}$")

# The Director may address the first-person narrator/inner voice by this alias. parse-script
# rewrites it to SeriesBible.protagonist_id before saving, so stems carry the real actor id.
PROTAGONIST_ALIAS = "protagonist"

APPROVED_AUDIO_TAGS: frozenset[str] = frozenset(
    {
        "internal monologue", "introspective", "sighs", "laughs", "chuckles", "whispers", "crying",
        "sobbing", "gasps", "clears throat", "exhales", "shouting", "hesitates", "pause", "nervously",
        "sarcastic", "excited", "angry", "sad", "tired",
    }
)
MONOLOGUE_TAGS = ("internal monologue", "introspective")
_TAG_RE = re.compile(r"\[([^\[\]]+)\]")


def slugify_id(name: str) -> str:
    """'Tô Mạn' -> 'to-man'; usable as a character_id (filename field)."""
    s = unicodedata.normalize("NFD", name)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if not s or not s[0].isalpha():
        s = "r-" + s
    return s[:24].rstrip("-")


class LineType(str, Enum):
    dialogue = "dialogue"
    monologue = "monologue"  # first-person inner voice of the protagonist ("Tôi")
    pause = "pause"


class Emotion(str, Enum):
    neutral = "neutral"
    happy = "happy"
    sad = "sad"
    angry = "angry"
    fearful = "fearful"
    surprised = "surprised"
    disgusted = "disgusted"
    tender = "tender"
    sarcastic = "sarcastic"
    desperate = "desperate"


class SfxCue(BaseModel):
    tag: str = Field(description="Library key, lowercase kebab-case, e.g. 'door-slam'.")
    position: Literal["before", "during", "after"]
    offset_ms: int = Field(0, ge=0, le=10_000)
    description: str = Field(description="Human/generator description of the sound.")

    @field_validator("tag")
    @classmethod
    def _tag_format(cls, v: str) -> str:
        if not CHARACTER_ID_RE.match(v):
            raise ValueError(f"sfx tag must be lowercase kebab-case: {v!r}")
        return v


class Line(BaseModel):
    line_id: str
    type: LineType
    character_id: str = Field(description=f"Actor id from the registry, or '{PROTAGONIST_ALIAS}' for monologue lines.")
    role_name: str | None = Field(None, description="The story role this line belongs to, e.g. 'Tô Mạn'.")
    text: str = Field(description="Clean Vietnamese line without tags. Used for subtitles and QA.")
    tts_text: str = Field(description="Text sent to TTS. May contain approved [audio tags].")
    emotion: Emotion
    emotional_intensity: int = Field(ge=1, le=10)
    acoustic_direction: str = Field(description="Free-text delivery note: mic distance, texture, room.")
    pace: Literal["slow", "normal", "fast"] = "normal"
    volume: Literal["whisper", "soft", "normal", "loud", "shout"] = "normal"
    pause_after_ms: int = Field(400, ge=0, le=5000)
    sfx: list[SfxCue] = Field(default_factory=list)

    @field_validator("line_id")
    @classmethod
    def _line_id_format(cls, v: str) -> str:
        if not LINE_ID_RE.match(v):
            raise ValueError(f"line_id must match epNN_scNN_lNNN: {v!r}")
        return v

    @field_validator("character_id")
    @classmethod
    def _character_id_format(cls, v: str) -> str:
        v = v.strip().lower()
        if not CHARACTER_ID_RE.match(v):
            v = slugify_id(v)  # tolerate a role name; parse-script maps it to the actor afterwards
        return v

    @model_validator(mode="after")
    def _consistency(self) -> Line:
        if self.type == LineType.pause:
            if self.text.strip() or self.tts_text.strip():
                raise ValueError(f"{self.line_id}: pause lines must have empty text")
        else:
            if not self.text.strip():
                raise ValueError(f"{self.line_id}: text is required")
            if not self.tts_text.strip():
                raise ValueError(f"{self.line_id}: tts_text is required")
        bad = [t for t in self.audio_tags() if t not in APPROVED_AUDIO_TAGS]
        if bad:
            raise ValueError(f"{self.line_id}: unapproved audio tags {bad}")
        return self

    def audio_tags(self) -> list[str]:
        return [m.group(1).strip().lower() for m in _TAG_RE.finditer(self.tts_text)]

    def is_monologue(self) -> bool:
        return self.type == LineType.monologue


class BgmCue(BaseModel):
    action: Literal["start", "continue", "swell", "fade_out", "stop"]
    mood: str
    energy: int = Field(ge=1, le=10)
    track_hint: str


class Scene(BaseModel):
    scene_id: str
    title: str
    location: str
    time_of_day: Literal["dawn", "morning", "afternoon", "evening", "night", "unspecified"]
    ambience_tag: str | None = None
    ambience_level: float = Field(0.2, ge=0.0, le=1.0)
    bgm: BgmCue | None = None
    lines: list[Line] = Field(min_length=1)

    @field_validator("scene_id")
    @classmethod
    def _scene_id_format(cls, v: str) -> str:
        if not SCENE_ID_RE.match(v):
            raise ValueError(f"scene_id must match scNN: {v!r}")
        return v


class EpisodeScript(BaseModel):
    """The AI Director's output. One file per episode."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    language: Literal["vi-VN"] = LANGUAGE
    series_id: str
    episode_number: int = Field(ge=1, le=99)
    title: str
    logline: str
    target_duration_sec: int = Field(ge=30, le=1800)
    characters_used: list[str]
    scenes: list[Scene] = Field(min_length=1)
    cliffhanger: str
    director_notes: str = ""

    @model_validator(mode="after")
    def _cross_checks(self) -> EpisodeScript:
        seen: set[str] = set()
        ep = f"ep{self.episode_number:02d}"
        for si, scene in enumerate(self.scenes, start=1):
            if scene.scene_id != f"sc{si:02d}":
                raise ValueError(f"scenes must be sequential; expected sc{si:02d} got {scene.scene_id}")
            for li, line in enumerate(scene.lines, start=1):
                expected = f"{ep}_{scene.scene_id}_l{li:03d}"
                if line.line_id != expected:
                    raise ValueError(f"line_id mismatch: expected {expected} got {line.line_id}")
                if line.line_id in seen:
                    raise ValueError(f"duplicate line_id {line.line_id}")
                seen.add(line.line_id)
                if line.type == LineType.pause:
                    continue
                if line.character_id != PROTAGONIST_ALIAS and line.character_id not in self.characters_used:
                    raise ValueError(f"{line.line_id}: character {line.character_id!r} not in characters_used")
        return self

    def all_lines(self) -> list[tuple[Scene, Line]]:
        return [(s, ln) for s in self.scenes for ln in s.lines]

    def resolve_protagonist(self, protagonist_id: str) -> int:
        n = 0
        for _, ln in self.all_lines():
            if ln.character_id == PROTAGONIST_ALIAS:
                ln.character_id = protagonist_id
                n += 1
        if n and protagonist_id not in self.characters_used:
            self.characters_used.append(protagonist_id)
        return n

    def remap_characters(self, mapping: dict[str, str]) -> int:
        """Rewrite character_ids via mapping (role slug / role name -> actor id). Returns lines changed."""
        n = 0
        for _, ln in self.all_lines():
            if ln.character_id in mapping and mapping[ln.character_id] != ln.character_id:
                ln.character_id = mapping[ln.character_id]
                n += 1
        return n


# --------------------------------------------------------------------------------------
# Story input (what the director fills in) and the series bible
# --------------------------------------------------------------------------------------


class StoryOverview(BaseModel):
    title: str
    total_minutes: int | None = Field(None, ge=1, le=600, description="Expected total length of the story audio.")
    genre: str = ""
    setting: str = ""


class StoryRole(BaseModel):
    name: str = Field(min_length=1, description="Role name exactly as used in the script, e.g. 'Tô Mạn'.")
    description: str = ""
    actor_id: str | None = Field(None, description="Voice IP the director assigned (e.g. from '/ngan'). None = AI chooses.")

    @field_validator("actor_id")
    @classmethod
    def _aid(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lstrip("/#").lower()
        if not v:
            return None
        if not CHARACTER_ID_RE.match(v):
            raise ValueError(f"actor_id must be a registry id: {v!r}")
        return v


class StoryInput(BaseModel):
    """series/<id>/story.json. Sections mirror the web form."""

    overview: StoryOverview
    roles: list[StoryRole] = Field(default_factory=list)
    script: str = Field(min_length=50, description="The whole story, scene by scene.")

    def to_text(self) -> str:
        o = self.overview
        parts = [f"TÊN: {o.title}"]
        if o.total_minutes:
            parts.append(f"THỜI LƯỢNG DỰ KIẾN: {o.total_minutes} phút")
        if o.genre:
            parts.append(f"THỂ LOẠI: {o.genre}")
        if o.setting:
            parts.append(f"BỐI CẢNH: {o.setting}")
        if self.roles:
            parts.append("\nNHÂN VẬT:")
            for r in self.roles:
                tag = f"  [diễn viên chỉ định: {r.actor_id}]" if r.actor_id else ""
                parts.append(f"- {r.name}: {r.description}{tag}")
        parts.append("\nKỊCH BẢN:\n" + self.script.strip())
        return "\n".join(parts) + "\n"

    def script_words(self) -> int:
        return len(self.script.split())


class RoleCast(BaseModel):
    role_name: str
    role_type: Literal["protagonist", "antagonist", "supporting", "minor"]
    actor_id: str | None = Field(None, description="Registry actor id, or null if no registered voice fits.")
    assigned_by: Literal["user", "ai", "placeholder"] = "ai"
    reason: str = ""

    @field_validator("actor_id")
    @classmethod
    def _aid(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower()
        if v in ("", "null", "none"):
            return None
        if not CHARACTER_ID_RE.match(v):
            raise ValueError(f"actor_id must be a registry id: {v!r}")
        return v


class EpisodeFormat(BaseModel):
    count: int = Field(30, ge=1, le=99)
    min_duration_sec: int = Field(50, ge=20)
    max_duration_sec: int = Field(70, ge=20)
    ends_on_cliffhanger: bool = True


class EpisodePlan(BaseModel):
    number: int = Field(ge=1, le=99)
    title: str
    logline: str
    key_beats: list[str] = Field(min_length=1, max_length=6)
    cliffhanger: str
    source_span: str = Field("", description="Which part of the input script this episode covers (scene numbers / first-last line). Empty when written from a treatment.")


class NewCharacter(BaseModel):
    """A role with no Voice IP. The orchestrator's cast job gives it a placeholder voice."""

    character_id: str
    display_name: str
    persona: str
    voice_description: str

    @field_validator("character_id")
    @classmethod
    def _cid(cls, v: str) -> str:
        v = v.strip().lower()
        if not CHARACTER_ID_RE.match(v):
            raise ValueError(f"character_id must be lowercase [a-z0-9-]: {v!r}")
        return v


class SeriesOutline(BaseModel):
    """Stage 1 of episodize: story input + actor roster -> casting + episode plan."""

    title: str
    logline: str
    premise: str
    tone: str
    genre: list[str] = Field(min_length=1, max_length=4)
    protagonist_role: str = Field(description="role_name of the first-person protagonist.")
    roles: list[RoleCast] = Field(min_length=1)
    episodes: list[EpisodePlan] = Field(min_length=1)

    @model_validator(mode="after")
    def _checks(self) -> SeriesOutline:
        names = {r.role_name for r in self.roles}
        if self.protagonist_role not in names:
            raise ValueError(f"protagonist_role {self.protagonist_role!r} not in roles")
        actors = [r.actor_id for r in self.roles if r.actor_id]
        dup = {a for a in actors if actors.count(a) > 1}
        if dup:
            raise ValueError(f"actor(s) cast in more than one role: {sorted(dup)}")
        for i, ep in enumerate(self.episodes, start=1):
            if ep.number != i:
                raise ValueError(f"episodes must be sequential; expected {i} got {ep.number}")
        return self


class DraftLine(BaseModel):
    speaker: str = Field(min_length=1, description="Role name exactly as in the cast list, e.g. 'Tô Mạn'.")
    internal: bool = Field(False, description="True for first-person inner monologue (protagonist only).")
    direction: str = Field("", description="Short delivery note or empty.")
    text: str = Field(min_length=1)

    @field_validator("speaker")
    @classmethod
    def _spk(cls, v: str) -> str:
        return v.strip()


class DraftScene(BaseModel):
    heading: str
    atmosphere: str = ""
    lines: list[DraftLine] = Field(min_length=1)


class EpisodeDraft(BaseModel):
    episode_number: int = Field(ge=1, le=99)
    title: str
    estimated_duration_sec: int = Field(ge=20, le=900)
    scenes: list[DraftScene] = Field(min_length=1, max_length=8)

    def word_count(self) -> int:
        return sum(len(ln.text.split()) for sc in self.scenes for ln in sc.lines)

    def speakers(self) -> set[str]:
        return {ln.speaker for sc in self.scenes for ln in sc.lines}

    def render(self) -> str:
        out = [f"TẬP {self.episode_number:02d} - {self.title.strip()}", ""]
        for i, sc in enumerate(self.scenes, start=1):
            out.append(f"CẢNH {i}. {sc.heading.strip()}")
            if sc.atmosphere.strip():
                out.append(f"({sc.atmosphere.strip()})")
            for ln in sc.lines:
                label = ln.speaker.upper()
                if ln.internal:
                    label += " (nội tâm)"
                elif ln.direction.strip():
                    label += f" ({ln.direction.strip()})"
                out.append(f"{label}: {ln.text.strip()}")
            out.append("")
        return "\n".join(out).rstrip() + "\n"


class SeriesBible(BaseModel):
    """series/<id>/series.json"""

    series_id: str
    language: Literal["vi-VN"] = LANGUAGE
    title: str
    logline: str = ""
    premise: str
    tone: str
    genre: list[str] = Field(default_factory=list)
    overview: StoryOverview | None = None
    mode: Literal["segment", "write"] = "write"
    protagonist_id: str = Field(description="Actor id of the protagonist.")
    protagonist_role: str = ""
    roles: list[RoleCast] = Field(default_factory=list, description="Story roles and the actors playing them.")
    cast: list[str] = Field(description="Actor ids used in this series (every role's actor).")
    pending_characters: list[NewCharacter] = Field(default_factory=list)
    episode_format: EpisodeFormat = Field(default_factory=EpisodeFormat)
    episodes: list[EpisodePlan] = Field(default_factory=list)
    changelog: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _checks(self) -> SeriesBible:
        if self.protagonist_id not in self.cast:
            raise ValueError(f"protagonist_id {self.protagonist_id!r} must be in cast")
        return self

    def role_to_actor(self) -> dict[str, str]:
        """role name, its slug and its actor id all map to the actor id."""
        m: dict[str, str] = {}
        for r in self.roles:
            if r.actor_id:
                m[r.role_name] = r.actor_id
                m[r.role_name.lower()] = r.actor_id
                m[slugify_id(r.role_name)] = r.actor_id
                m[r.actor_id] = r.actor_id
        return m

    def actor_to_role(self) -> dict[str, str]:
        return {r.actor_id: r.role_name for r in self.roles if r.actor_id}


# --------------------------------------------------------------------------------------
# Voice IP registry (library/voice-ips.json, global and locked)
# --------------------------------------------------------------------------------------


class ProviderVoice(BaseModel):
    voice_id: str = Field(description="ElevenLabs voice_id, or a Gemini prebuilt voice name (e.g. 'Leda').")
    model_id: str = Field(description="e.g. 'eleven_v3', 'eleven_multilingual_v2', 'gemini-2.5-flash-preview-tts'")
    voice_url: str | None = Field(None, description="Vendor page for the voice, for humans.")
    fallback_voice_id: str | None = Field(None, description="Premade voice used when the account tier rejects voice_id (HTTP 402).")
    default_settings: dict[str, float | int | str | bool] = Field(default_factory=dict)


class CharacterProfile(BaseModel):
    """An actor: a fixed Voice IP that plays roles across series."""

    character_id: str
    display_name: str
    persona: str = Field(description="Personality features. Used for casting and the Director prompt.")
    voice_description: str = Field(description="Timbre, age, accent. Used for casting and QA.")
    gender: Literal["female", "male", "other"] | None = None
    age: str | None = Field(None, description="Free text, e.g. '23', 'early 30s'.")
    tags: list[str] = Field(default_factory=list, description="Casting tags, e.g. ['cute', 'innocent', 'ceo'].")
    language: str = Field(LANGUAGE, description="BCP-47 primary language for this voice.")
    providers: dict[str, ProviderVoice] = Field(default_factory=dict)
    is_ip_asset: bool = True

    @field_validator("character_id")
    @classmethod
    def _cid(cls, v: str) -> str:
        if not CHARACTER_ID_RE.match(v):
            raise ValueError(f"character_id must be lowercase [a-z0-9-]: {v!r}")
        return v

    def casting_card(self) -> str:
        bits = [self.display_name]
        if self.gender:
            bits.append({"female": "nữ", "male": "nam", "other": "khác"}[self.gender])
        if self.age:
            bits.append(f"{self.age} tuổi")
        card = f"- {self.character_id}: {', '.join(bits)}. Tính cách: {self.persona} Giọng: {self.voice_description}"
        if self.tags:
            card += f" Tags: {', '.join(self.tags)}"
        return card


class VoiceRegistry(BaseModel):
    locked: bool = True
    default_provider: str = "elevenlabs"
    characters: list[CharacterProfile]
    changelog: list[str] = Field(default_factory=list)

    def get(self, character_id: str) -> CharacterProfile:
        for c in self.characters:
            if c.character_id == character_id:
                return c
        raise KeyError(character_id)

    def ids(self) -> set[str]:
        return {c.character_id for c in self.characters}

    def actors(self) -> list[CharacterProfile]:
        return [c for c in self.characters if c.is_ip_asset]


# --------------------------------------------------------------------------------------
# Timeline (computed post-TTS by assemble-audio)
# --------------------------------------------------------------------------------------


class TimelineClip(BaseModel):
    kind: Literal["stem", "silence", "sfx", "bgm", "ambience"]
    path: str | None = None
    start_ms: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    gain_db: float = 0.0
    fade_in_ms: int = 0
    fade_out_ms: int = 0
    line_id: str | None = None
    scene_id: str | None = None


class Timeline(BaseModel):
    series_id: str
    episode_number: int
    sample_rate: int = 44100
    total_duration_ms: int
    clips: list[TimelineClip]


def episode_json_schema() -> dict:
    return EpisodeScript.model_json_schema()


if __name__ == "__main__":
    json.dump(episode_json_schema(), sys.stdout, indent=2, ensure_ascii=False)
    print()
