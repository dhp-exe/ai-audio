"""Casting & Voice IP Curator Agent: story roles -> fixed Virtual Actor voices on a concrete engine.

Skills
    Voice Registry   load and validate the locked Voice IP registry (assets/voice_registry.json);
                     give roles without an IP a one-off entry; add a voice on a new engine when an
                     actor has none there (an addition, so the lock is not involved)
    Casting Match    role -> actor: the director's pins first, then an LLM proposal over the free
                     actors (gender, age, personality, timbre), then a rule-based match, then a
                     placeholder. One actor plays one role per series.
    Engine Policy    actor -> (provider, model, voice, settings). Precedence: by_actor > the actor's
                     cloned / preferred voice > by_role_type > the run's default engine.

A voice produced by the cloning track is used as soon as it is in the registry: Engine Policy
prefers a ``source: "cloned"`` voice whenever that engine's key is configured.
"""

from __future__ import annotations

from emvoox.agents.base import Agent, AgentContext, AgentError, Skill
from emvoox.casting import guess_gender, placeholder_voice
from emvoox.contracts.cast import CastingProposal, CastMember, EnginePolicy, EngineRef, ResolvedCast
from emvoox.contracts.production import CharacterProfile, ProviderVoice, RoleCast, SeriesBible, VoiceRegistry, slugify_id
from emvoox.providers.llm import LlmError
from emvoox.providers.tts.catalog import DEFAULT_MODEL, PROVIDER_LABEL, PROVIDER_NAMES
from emvoox.repositories import now_iso

CASTING_SYSTEM = """Bạn là giám đốc casting của Emvoox, xưởng micro-drama AUDIO tiếng Việt với các Diễn viên AI (Voice IP) cố định.

Bạn nhận danh sách VAI cần phân và danh sách DIỄN VIÊN còn trống. Với mỗi vai, chọn actor_id phù hợp nhất theo giới tính, tuổi, tính cách và chất giọng.
- Mỗi diễn viên chỉ đóng MỘT vai trong series. Không dùng actor_id ngoài danh sách.
- Giới tính phải khớp. Nếu không còn diễn viên phù hợp, để actor_id = null (hệ thống sẽ gán giọng tạm).
- reason: một câu ngắn bằng tiếng Việt.
Trả về CastingProposal với đúng một assignment cho mỗi vai, role_name giữ nguyên văn.
"""


class CastingAgent(Agent):
    id = "casting"
    title = "Casting & Voice IP Curator Agent"
    description = "Matches story roles to fixed Virtual Actor voice profiles and resolves the engine, model and voice for each."
    skills = (
        Skill("voice_registry", "Voice Registry", "Read and curate the locked Voice IP registry; add missing engine voices and one-off placeholders."),
        Skill("casting_match", "Casting Match", "Role -> actor by pins, LLM proposal, rules, then placeholder. One actor per role."),
        Skill("engine_policy", "Engine Policy", "Actor -> provider/model/voice/settings; cloned IP voices win when their engine is available."),
    )
    consumes = "SeriesBible"
    produces = ResolvedCast

    # ---- skill: Voice Registry
    def voice_registry(self, ctx: AgentContext) -> VoiceRegistry:
        reg = ctx.repos.registry.load()
        ids = [c.character_id for c in reg.characters]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            raise AgentError(f"Voice IP registry has duplicate ids: {dup}")
        return reg

    # ---- skill: Casting Match
    def casting_match(self, ctx: AgentContext, bible: SeriesBible, registry: VoiceRegistry) -> list[RoleCast]:
        roles = [r.model_copy() for r in bible.roles]
        used: set[str] = set()
        for r in roles:  # pins and earlier casting survive when still valid
            if r.actor_id and r.actor_id in registry.ids() and r.actor_id not in used:
                used.add(r.actor_id)
            elif r.actor_id:
                ctx.log(f"casting: {r.role_name}: {r.actor_id!r} is unknown or already cast; recasting")
                r.actor_id, r.assigned_by = None, "ai"
        open_roles = [r for r in roles if not r.actor_id]
        free = [c for c in registry.actors() if c.character_id not in used]
        if open_roles and free:
            proposal = self._propose(ctx, bible, open_roles, free)
            by_role = {a.role_name: a for a in proposal.assignments} if proposal else {}
            for r in open_roles:
                a = by_role.get(r.role_name)
                if a and a.actor_id and a.actor_id in {c.character_id for c in free} and a.actor_id not in used:
                    r.actor_id, r.assigned_by, r.reason = a.actor_id, "ai", a.reason
                    used.add(a.actor_id)
            for r in [x for x in open_roles if not x.actor_id]:  # rule-based match for whatever the model left open
                gender = guess_gender(r.role_name, r.description)
                pick = next((c for c in free if c.character_id not in used and (c.gender or guess_gender(c.voice_description, c.persona)) == gender), None)
                if pick:
                    r.actor_id, r.assigned_by, r.reason = pick.character_id, "rule", f"khớp giới tính ({gender}); diễn viên còn trống"
                    used.add(pick.character_id)
        for r in [x for x in roles if not x.actor_id]:  # no Voice IP fits: a one-off character with a placeholder voice
            cid = slugify_id(r.role_name)
            while cid in registry.ids() or cid in used:
                cid = (cid[:21] + "-2") if not cid[-1].isdigit() else cid[:-1] + str(int(cid[-1]) + 1)
            r.actor_id, r.assigned_by, r.reason = cid, "placeholder", "không còn Voice IP phù hợp; dùng giọng tạm"
            used.add(cid)
        for r in roles:
            ctx.log(f"casting: {r.role_name} -> {r.actor_id} ({r.assigned_by}{'; ' + r.reason[:70] if r.reason else ''})")
        return roles

    def _propose(self, ctx: AgentContext, bible: SeriesBible, open_roles: list[RoleCast], free: list[CharacterProfile]) -> CastingProposal | None:
        roles_txt = "\n".join(f"- {r.role_name} ({r.role_type}): {r.description}" for r in open_roles)
        roster = "\n".join(c.casting_card() for c in free)
        user = f"Series: {bible.title}\nTiền đề: {bible.premise}\n\nVAI CẦN PHÂN\n{roles_txt}\n\nDIỄN VIÊN CÒN TRỐNG\n{roster}\n\nHãy trả về CastingProposal."
        try:
            return ctx.llm.structured(
                agent=self.id, skill="casting_match", system=CASTING_SYSTEM, user=user, schema=CastingProposal, temperature=0.2,
                context={"roles": [{"name": r.role_name, "gender": guess_gender(r.role_name, r.description)} for r in open_roles],
                         "roster": [{"id": c.character_id, "gender": c.gender or guess_gender(c.voice_description, c.persona)} for c in free]})
        except LlmError as e:
            ctx.log(f"casting: LLM proposal unavailable ({type(e).__name__}: {str(e)[:100]}); using the rule-based match")
            return None

    # ---- skill: Engine Policy
    def build_policy(self, ctx: AgentContext) -> EnginePolicy:
        p = ctx.params
        return EnginePolicy(default=EngineRef(provider=p.tts_provider, model=p.tts_model), by_role_type=dict(p.engine_by_role_type),
                            by_actor=dict(p.engine_by_actor), prefer_cloned=ctx.settings.prefer_cloned_voices, tier=p.tier, batching=p.tts_batching)

    def _available(self, ctx: AgentContext, provider: str) -> bool:
        return provider in PROVIDER_NAMES and bool(ctx.settings.key_for(provider))

    def _engine_for(self, ctx: AgentContext, policy: EnginePolicy, role: RoleCast, profile: CharacterProfile | None) -> tuple[EngineRef, str]:
        """(engine, why) for one role, in precedence order. Unavailable engines are skipped with a note."""
        candidates: list[tuple[EngineRef, str]] = []
        if role.actor_id in policy.by_actor:
            candidates.append((policy.by_actor[role.actor_id], "by_actor"))
        if policy.prefer_cloned and profile is not None:
            if profile.preferred_provider and profile.preferred_provider in profile.providers:
                candidates.append((EngineRef(provider=profile.preferred_provider), "preferred voice"))
            for prov in profile.cloned_providers():
                candidates.append((EngineRef(provider=prov), "cloned voice"))
        if role.role_type in policy.by_role_type:
            candidates.append((policy.by_role_type[role.role_type], "by_role_type"))
        for ref, why in candidates:
            if self._available(ctx, ref.provider):
                return ref, why
            ctx.note(f"{role.actor_id}: {PROVIDER_LABEL.get(ref.provider, ref.provider)} ({why}) has no API key configured; using the run's default engine instead.")
        return policy.default, "default"

    def engine_policy(self, ctx: AgentContext, bible: SeriesBible, roles: list[RoleCast], policy: EnginePolicy) -> list[CastMember]:
        if not self._available(ctx, policy.default.provider):
            raise AgentError(f"the run's TTS engine {policy.default.provider!r} has no API key configured in .env")
        registry_repo = ctx.repos.registry
        reg = registry_repo.load()
        used_voices: dict[str, set[str]] = {}
        counters = {"female": 0, "male": 0}
        members: list[CastMember] = []
        resolved: list[tuple[RoleCast, EngineRef, str]] = []
        for r in roles:
            profile = reg.get(r.actor_id) if r.actor_id in reg.ids() else None
            ref, why = self._engine_for(ctx, policy, r, profile)
            resolved.append((r, ref, why))
            if profile and ref.provider in profile.providers:
                used_voices.setdefault(ref.provider, set()).add(profile.providers[ref.provider].voice_id)

        for r, ref, why in resolved:
            provider = ref.provider
            profile = reg.get(r.actor_id) if r.actor_id in reg.ids() else None
            voice = profile.providers.get(provider) if profile else None
            source = voice.source if voice else "placeholder"
            if voice is None:
                el = profile.providers.get("elevenlabs") if profile else None
                if provider == "wavespeed" and el is not None:
                    # WaveSpeed's ElevenLabs endpoint accepts any ElevenLabs voice id: the same IP voice, through the gateway
                    voice = ProviderVoice(voice_id=el.voice_id, model_id=DEFAULT_MODEL["wavespeed"], voice_url=el.voice_url,
                                          fallback_voice_id=el.fallback_voice_id, source=el.source, label=el.label, added_at=now_iso())
                    registry_repo.set_provider_voice(r.actor_id, provider, voice)
                    ctx.note(f"{r.actor_id}: no WaveSpeed voice yet; reusing its ElevenLabs voice {el.voice_id} through WaveSpeed.")
                    source = voice.source
                else:
                    gender = (profile.gender if profile and profile.gender else None) or guess_gender(
                        r.role_name, r.description, profile.voice_description if profile else None, profile.persona if profile else None)
                    vid = placeholder_voice(gender, counters[gender], provider, exclude=used_voices.get(provider, set()))
                    counters[gender] += 1
                    model = ref.model or DEFAULT_MODEL[provider]
                    voice = ProviderVoice(voice_id=vid, model_id=model, source="placeholder" if profile is None else ("prebuilt" if provider == "gemini" else "premade"),
                                          added_at=now_iso())
                    if profile is None:
                        registry_repo.upsert(CharacterProfile(
                            character_id=r.actor_id, display_name=r.role_name, persona=r.description,
                            voice_description=f"PLACEHOLDER ({gender} {provider} {vid}). Vai: {r.description[:120]}",
                            gender=gender, providers={provider: voice}, is_ip_asset=False))
                        ctx.note(f"Placeholder voice for {r.role_name} ({r.actor_id}): {vid} on {PROVIDER_LABEL[provider]}. Replace it on the Voice IPs page before publishing.")
                        source = "placeholder"
                    else:
                        registry_repo.set_provider_voice(r.actor_id, provider, voice)
                        ctx.note(f"{r.actor_id}: no {PROVIDER_LABEL[provider]} voice yet; auto-assigned {vid}. Pick a preferred one on the Voice IPs page.")
                        source = voice.source
                reg = registry_repo.load()
                profile = reg.get(r.actor_id)
                used_voices.setdefault(provider, set()).add(voice.voice_id)
            if provider == "gemini" and source == "premade":
                source = "prebuilt"
            model_id = ref.model or voice.model_id or DEFAULT_MODEL[provider]
            members.append(CastMember(
                role_name=r.role_name, role_type=r.role_type, actor_id=r.actor_id or "", display_name=profile.display_name if profile else r.role_name,
                assigned_by=r.assigned_by, reason=r.reason,
                provider=provider, model_id=model_id, voice_id=voice.voice_id, voice_source=source,
                fallback_voice_id=voice.fallback_voice_id, voice_settings=dict(voice.default_settings),
                is_ip_asset=profile.is_ip_asset if profile else False))
            ctx.log(f"engine policy: {r.actor_id} -> {provider}/{model_id} voice {voice.voice_id} [{source}; {why}]")
        return members

    # ---- agent entry point
    def run(self, ctx: AgentContext) -> ResolvedCast:
        repo = ctx.repos.series
        bible = repo.load_bible(ctx.series_id)
        if bible is None or not bible.roles:
            raise AgentError("series has no roles to cast; the Script Writer must run first")
        registry = self.voice_registry(ctx)
        roles = self.casting_match(ctx, bible, registry)
        policy = self.build_policy(ctx)
        members = self.engine_policy(ctx, bible, roles, policy)

        prot = next((r for r in roles if r.role_name == bible.protagonist_role), None) or next((r for r in roles if r.role_type == "protagonist"), roles[0])
        bible.roles = roles
        bible.cast = [r.actor_id for r in roles if r.actor_id]
        bible.protagonist_id = prot.actor_id or ""
        bible.protagonist_role = prot.role_name
        repo.save_bible(bible)
        try:
            cast = ResolvedCast(series_id=ctx.series_id, engine_policy=policy, protagonist_id=bible.protagonist_id, members=members,
                                notes=list(ctx.notes), resolved_at=now_iso())
        except ValueError as e:
            raise AgentError(f"cast rejected: {e}") from e
        repo.save_cast(cast)
        return cast
