"""AI Director output contract: Directed Conversation Units plus the render plan.

A *conversation unit* is one line of the episode with everything the Sound Engineer needs to say it:
who speaks, the exact text for the engine, the emotion, pacing and the silence that follows. The
*render plan* groups units into TTS requests (one line, or a multi-speaker conversation chunk).
The orchestrator validates this payload before the Sound Engineer sees it.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from emvoox.contracts.production import LINE_ID_RE, SCENE_ID_RE, Emotion, LineType, SfxCue

SCHEMA_VERSION = "2.0"
RENDER_ID_RE = re.compile(r"^ep\d{2}_sc\d{2}_(l\d{3}|c\d{2})$")


class ConversationUnit(BaseModel):
    unit_id: str = Field(description="Same as the line id: epNN_scNN_lNNN.")
    scene_id: str
    order: int = Field(ge=1, description="1-based position in the episode.")
    type: LineType
    speaker_id: str = Field("", description="Actor id from the resolved cast; empty for pause units.")
    role_name: str | None = None
    text: str = Field("", description="Clean line, no tags. Subtitles and QA use this.")
    tts_text: str = Field("", description="Text compiled for the unit's engine (normalized; tags kept only where the engine reads them).")
    emotion_tag: Emotion = Emotion.neutral
    emotional_intensity: int = Field(5, ge=1, le=10)
    audio_tags: list[str] = Field(default_factory=list, description="Non-verbal cues such as 'sighs', 'whispers'.")
    direction: str = Field("", description="Natural-language delivery note (Vietnamese).")
    pause_after_ms: int = Field(400, ge=0, le=5000)
    speed: float = Field(1.0, ge=0.7, le=1.3, description="Speaking-rate multiplier.")
    pitch: int = Field(0, ge=-6, le=6, description="Semitone offset; applied on engines that support it, otherwise folded into the direction.")
    volume: Literal["whisper", "soft", "normal", "loud", "shout"] = "normal"
    provider: str = ""
    model_id: str = ""
    voice_id: str = ""
    settings: dict[str, float | int | str | bool] = Field(default_factory=dict)
    sfx: list[SfxCue] = Field(default_factory=list, description="Sound-effect cues; empty while ENABLE_SFX is off.")

    @model_validator(mode="after")
    def _checks(self) -> ConversationUnit:
        if not LINE_ID_RE.match(self.unit_id):
            raise ValueError(f"unit_id must match epNN_scNN_lNNN: {self.unit_id!r}")
        if not SCENE_ID_RE.match(self.scene_id):
            raise ValueError(f"scene_id must match scNN: {self.scene_id!r}")
        if self.type == LineType.pause:
            if self.text.strip() or self.tts_text.strip():
                raise ValueError(f"{self.unit_id}: pause units carry no text")
        else:
            if not self.speaker_id:
                raise ValueError(f"{self.unit_id}: speaker_id is required")
            if not self.text.strip() or not self.tts_text.strip():
                raise ValueError(f"{self.unit_id}: text and tts_text are required")
            if not (self.provider and self.model_id and self.voice_id):
                raise ValueError(f"{self.unit_id}: provider, model_id and voice_id must be resolved")
        return self

    def is_spoken(self) -> bool:
        return self.type != LineType.pause


class RenderUnit(BaseModel):
    """One TTS request: a single line, or a conversation chunk of several lines of one scene."""

    id: str
    kind: Literal["line", "conversation"]
    scene_id: str
    unit_ids: list[str] = Field(min_length=1)
    speakers: list[str] = Field(min_length=1)
    provider: str
    model_id: str
    voice_id: str = Field(description="Voice for a line; the chunk id for a multi-speaker conversation.")
    text: str
    settings: dict[str, float | int | str | bool | list[str]] = Field(default_factory=dict)
    speaker_voices: list[tuple[str, str]] = Field(default_factory=list, description="(label, voice) pairs of a multi-speaker request.")
    stem: str = Field(description="Stem file name under stems/epNN/.")
    pause_after_ms: int = Field(400, ge=0, le=5000)
    attempt: int = Field(0, ge=0, description="Bumped by the retry loop; part of the cache hash so a retry really re-renders.")

    @model_validator(mode="after")
    def _checks(self) -> RenderUnit:
        if not RENDER_ID_RE.match(self.id):
            raise ValueError(f"render unit id must match epNN_scNN_lNNN or epNN_scNN_cNN: {self.id!r}")
        if self.kind == "line" and len(self.unit_ids) != 1:
            raise ValueError(f"{self.id}: a line unit covers exactly one conversation unit")
        if not self.text.strip():
            raise ValueError(f"{self.id}: empty text")
        if not self.stem.endswith(".wav"):
            raise ValueError(f"{self.id}: stem must be a .wav file name")
        return self


class DirectedConversationUnits(BaseModel):
    """AI Director Agent output for one episode."""

    schema_version: Literal["2.0"] = SCHEMA_VERSION
    series_id: str
    episode_number: int = Field(ge=1, le=99)
    title: str
    target_duration_sec: int = Field(ge=20, le=1800)
    batching: Literal["line", "scene", "mixed"] = "line"
    units: list[ConversationUnit] = Field(min_length=1)
    render_plan: list[RenderUnit] = Field(min_length=1)
    cliffhanger: str = ""
    director_notes: str = ""
    bgm_mood: str | None = Field(None, description="Mood folder under assets/bgm/ for the music bed; null = no bed.")
    directed_at: str = ""

    @model_validator(mode="after")
    def _cross_checks(self) -> DirectedConversationUnits:
        prefix = f"ep{self.episode_number:02d}_"
        ids = [u.unit_id for u in self.units]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate unit ids")
        for i, u in enumerate(self.units, start=1):
            if not u.unit_id.startswith(prefix):
                raise ValueError(f"{u.unit_id}: does not belong to episode {self.episode_number}")
            if u.order != i:
                raise ValueError(f"{u.unit_id}: order must be {i}, got {u.order}")
        spoken = [u.unit_id for u in self.units if u.is_spoken()]
        if not spoken:
            raise ValueError("episode has no spoken units")
        covered: list[str] = [uid for r in self.render_plan for uid in r.unit_ids]
        if sorted(covered) != sorted(spoken):
            missing = sorted(set(spoken) - set(covered))
            extra = sorted(set(covered) - set(spoken))
            twice = sorted({c for c in covered if covered.count(c) > 1})
            raise ValueError(f"render plan must cover every spoken unit exactly once (missing={missing[:5]}, unknown={extra[:5]}, twice={twice[:5]})")
        rids = [r.id for r in self.render_plan]
        if len(set(rids)) != len(rids):
            raise ValueError("duplicate render unit ids")
        return self

    def unit(self, unit_id: str) -> ConversationUnit:
        for u in self.units:
            if u.unit_id == unit_id:
                return u
        raise KeyError(unit_id)

    def spoken(self) -> list[ConversationUnit]:
        return [u for u in self.units if u.is_spoken()]

    def render_unit_for(self, unit_id: str) -> RenderUnit:
        for r in self.render_plan:
            if unit_id in r.unit_ids:
                return r
        raise KeyError(unit_id)

    def speakers(self) -> set[str]:
        return {u.speaker_id for u in self.spoken()}

    def characters(self) -> int:
        return sum(len(r.text) for r in self.render_plan)
