"""Casting & Voice IP Curator contracts: the engine policy and the resolved cast."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from emvoox.contracts.production import CHARACTER_ID_RE, VoiceSource


class EngineRef(BaseModel):
    provider: str
    model: str | None = Field(None, description="None = the engine's default model.")


class EnginePolicy(BaseModel):
    """Which TTS engine renders which actor. Precedence: by_actor > the actor's cloned/preferred
    voice (when ``prefer_cloned``) > by_role_type > default."""

    default: EngineRef
    by_role_type: dict[str, EngineRef] = Field(default_factory=dict)
    by_actor: dict[str, EngineRef] = Field(default_factory=dict)
    prefer_cloned: bool = True
    tier: Literal["test", "final"] = Field("test", description="'final' refuses placeholder voices.")
    batching: Literal["auto", "line", "scene"] = "auto"


class CastingAssignment(BaseModel):
    role_name: str
    actor_id: str | None = Field(None, description="Registry actor id, or null when no registered Voice IP fits.")
    reason: str = ""


class CastingProposal(BaseModel):
    """Structured output of the Casting Match LLM call."""

    assignments: list[CastingAssignment] = Field(min_length=1)


class CastMember(BaseModel):
    """One story role, the Voice IP playing it, and the exact voice the Sound Engineer will call."""

    role_name: str
    role_type: Literal["protagonist", "antagonist", "supporting", "minor"]
    actor_id: str
    display_name: str = ""
    assigned_by: Literal["user", "ai", "rule", "placeholder"] = "ai"
    reason: str = ""
    provider: str
    model_id: str
    voice_id: str
    voice_source: VoiceSource = "premade"
    fallback_voice_id: str | None = None
    voice_settings: dict[str, float | int | str | bool] = Field(
        default_factory=dict, description="Identity anchor for this voice (stability, similarity_boost, style, speed); per-line delivery moves around it.")
    is_ip_asset: bool = True

    @model_validator(mode="after")
    def _ids(self) -> CastMember:
        if not CHARACTER_ID_RE.match(self.actor_id):
            raise ValueError(f"actor_id must be a registry id: {self.actor_id!r}")
        if not self.voice_id.strip():
            raise ValueError(f"{self.actor_id}: voice_id is required")
        return self


class ResolvedCast(BaseModel):
    """Casting Agent output: character-to-voice mapping, voice parameters and provider selection."""

    series_id: str
    engine_policy: EnginePolicy
    protagonist_id: str
    members: list[CastMember] = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)
    resolved_at: str = ""

    @model_validator(mode="after")
    def _checks(self) -> ResolvedCast:
        actors = [m.actor_id for m in self.members]
        dup = sorted({a for a in actors if actors.count(a) > 1})
        if dup:
            raise ValueError(f"actor(s) cast in more than one role: {dup}")
        if self.protagonist_id not in actors:
            raise ValueError(f"protagonist_id {self.protagonist_id!r} is not in the cast")
        if self.engine_policy.tier == "final":
            # background roles may keep a temporary voice; a named role must be played by a Voice IP
            ph = [m.actor_id for m in self.members if m.voice_source == "placeholder" and m.role_type != "minor"]
            if ph:
                raise ValueError(f"tier 'final' forbids temporary voices on named roles: {ph}")
        return self

    def member(self, actor_id: str) -> CastMember:
        for m in self.members:
            if m.actor_id == actor_id:
                return m
        raise KeyError(actor_id)

    def actor_ids(self) -> set[str]:
        return {m.actor_id for m in self.members}

    def providers(self) -> list[str]:
        return sorted({m.provider for m in self.members})
