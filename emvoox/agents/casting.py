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
from emvoox.casting import gender_of, guess_gender, placeholder_voice
from emvoox.contracts.cast import CastingProposal, CastMember, EnginePolicy, EngineRef, ResolvedCast
from emvoox.contracts.production import CharacterProfile, ProviderVoice, RoleCast, SeriesBible, VoiceRegistry, slugify_id
from emvoox.providers.llm import LlmError
from emvoox.providers.tts.catalog import DEFAULT_MODEL, PROVIDER_LABEL, PROVIDER_NAMES, voice_family
from emvoox.repositories import now_iso

CASTING_SYSTEM = """Bạn là giám đốc casting của Emvoox, xưởng micro-drama AUDIO tiếng Việt với các Diễn viên AI (Voice IP) cố định.

Bạn nhận danh sách VAI cần phân và danh sách DIỄN VIÊN còn trống. Với mỗi vai, chọn actor_id phù hợp nhất theo giới tính, tuổi, tính cách và chất giọng.
- Mỗi diễn viên chỉ đóng MỘT vai trong series. Không dùng actor_id ngoài danh sách.
- Giới tính phải khớp. Nếu không còn diễn viên phù hợp, để actor_id = null (hệ thống sẽ gán giọng tạm).
- reason: một câu ngắn bằng tiếng Việt.
Trả về CastingProposal với đúng một assignment cho mỗi vai, role_name giữ nguyên văn.
"""


GENDER_VI = {"female": "nữ", "male": "nam"}


def role_gender(r: RoleCast) -> str | None:
    """The role's gender: what the Script Writer stated, else what its name and description say, else unknown."""
    return r.gender or gender_of(r.role_name, r.description)


def actor_gender(c: CharacterProfile) -> str:
    return c.gender or guess_gender(c.display_name, c.voice_description, c.persona)


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
        """Named roles (protagonist, antagonist, supporting) are always played by Voice IPs: pins first, then the LLM's
        proposal, then a gender rule. Background roles (minor) take a Voice IP that is still free, else a temporary
        voice that exists only in this production's cast. No character is ever added to the registry here."""
        roles = [r.model_copy() for r in bible.roles]
        used: set[str] = set()
        previous = ctx.repos.series.load_cast(ctx.series_id)
        temporary = {m.actor_id for m in previous.members if not m.is_ip_asset} if previous else set()
        for r in roles:  # pins and earlier casting survive when still valid, so a series keeps its voices across runs
            if r.actor_id and r.actor_id not in used and (r.actor_id in registry.ids() or (r.actor_id in temporary and r.role_type == "minor")):
                used.add(r.actor_id)
            elif r.actor_id:
                ctx.log(f"casting: {r.role_name}: {r.actor_id!r} is unknown or already cast; recasting")
                r.actor_id, r.assigned_by = None, "ai"
        order = {"protagonist": 0, "antagonist": 1, "supporting": 2, "minor": 3}
        open_roles = sorted([r for r in roles if not r.actor_id], key=lambda r: order[r.role_type])
        named = [r for r in open_roles if r.role_type != "minor"]
        free = [c for c in registry.actors() if c.character_id not in used]
        if named and free:
            proposal = self._propose(ctx, bible, named, free)
            by_role = {a.role_name: a for a in proposal.assignments} if proposal else {}
            for r in named:
                a = by_role.get(r.role_name)
                actor = next((c for c in free if a and c.character_id == a.actor_id), None)
                if actor is None or actor.character_id in used:
                    continue
                want = role_gender(r)
                if want and actor_gender(actor) != want:  # never trust a proposal that puts a male voice on a female role
                    ctx.log(f"casting: {r.role_name}: proposal {actor.character_id!r} rejected (role is {want}, actor is {actor_gender(actor)})")
                    continue
                r.actor_id, r.assigned_by, r.reason = actor.character_id, "ai", a.reason
                used.add(actor.character_id)
        for r in [x for x in open_roles if not x.actor_id]:  # rule-based: named roles first, then background roles, by gender
            gender = role_gender(r) or guess_gender(r.role_name, r.description)
            pick = next((c for c in free if c.character_id not in used and actor_gender(c) == gender), None)
            if pick:
                r.actor_id, r.assigned_by, r.reason = pick.character_id, "rule", f"khớp giới tính ({gender}); diễn viên còn trống"
                used.add(pick.character_id)
        for r in [x for x in roles if not x.actor_id]:  # no Voice IP left: a temporary voice for this production only
            cid = slugify_id(r.role_name)
            while cid in registry.ids() or cid in used:
                cid = (cid[:21] + "-2") if not cid[-1].isdigit() else cid[:-1] + str(int(cid[-1]) + 1)
            r.actor_id, r.assigned_by, r.reason = cid, "placeholder", "vai nền; giọng tạm chỉ dùng cho sản phẩm này"
            used.add(cid)
            if r.role_type != "minor":
                ctx.note(f"{r.role_name} ({r.role_type}): no Voice IP of the right gender is free, so it plays with a temporary voice. "
                         "Add a Voice IP or pin an actor to this role.")
        for r in roles:
            ctx.log(f"casting: {r.role_name} -> {r.actor_id} ({r.assigned_by}{'; ' + r.reason[:70] if r.reason else ''})")
        return roles

    def _propose(self, ctx: AgentContext, bible: SeriesBible, open_roles: list[RoleCast], free: list[CharacterProfile]) -> CastingProposal | None:
        roles_txt = "\n".join(f"- {r.role_name} ({r.role_type}, giới tính: {GENDER_VI.get(role_gender(r) or '', 'chưa rõ')}): {r.description}" for r in open_roles)
        roster = "\n".join(c.casting_card() for c in free)
        user = f"Series: {bible.title}\nTiền đề: {bible.premise}\n\nVAI CẦN PHÂN\n{roles_txt}\n\nDIỄN VIÊN CÒN TRỐNG\n{roster}\n\nHãy trả về CastingProposal."
        try:
            return ctx.llm.structured(
                agent=self.id, skill="casting_match", system=CASTING_SYSTEM, user=user, schema=CastingProposal, temperature=0.2,
                context={"roles": [{"name": r.role_name, "gender": role_gender(r) or guess_gender(r.role_name, r.description)} for r in open_roles],
                         "roster": [{"id": c.character_id, "gender": actor_gender(c)} for c in free]})
        except LlmError as e:
            ctx.log(f"casting: LLM proposal unavailable ({type(e).__name__}: {str(e)[:100]}); using the rule-based match")
            return None

    # ---- skill: Engine Policy
    def build_policy(self, ctx: AgentContext) -> EnginePolicy:
        p = ctx.params
        s = ctx.settings  # a run that names no model uses the one configured in .env for that engine (EMVOOX_TTS_MODEL)
        model = p.tts_model or (s.tts_model if p.tts_provider == s.tts_provider else None)
        return EnginePolicy(default=EngineRef(provider=p.tts_provider, model=model), by_role_type=dict(p.engine_by_role_type),
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
        earlier = ctx.repos.series.load_cast(ctx.series_id)
        previous = {m.actor_id: m for m in earlier.members if not m.is_ip_asset} if earlier else {}
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
            stored = profile.providers.get(provider) if profile else None
            model = ref.model or (stored.model_id if stored else None) or DEFAULT_MODEL[provider]
            family = voice_family(provider, model)  # whose voice ids this model speaks (WaveSpeed: the vendor of the model path)
            # a stored voice only fits models of its own family: an ElevenLabs id means nothing to Gemini TTS, and vice versa
            voice = stored if stored is not None and voice_family(provider, stored.model_id) == family else None
            source = voice.source if voice else "placeholder"
            if voice is None:
                same = profile.providers.get(family) if profile and family != provider else None
                if same is not None:
                    # WaveSpeed serves the vendor's own voices: the actor's ElevenLabs id or Gemini voice name works through the gateway
                    voice = ProviderVoice(voice_id=same.voice_id, model_id=model, voice_url=same.voice_url,
                                          fallback_voice_id=same.fallback_voice_id, source=same.source, label=same.label, added_at=now_iso())
                    if stored is None:
                        registry_repo.set_provider_voice(r.actor_id, provider, voice)
                    ctx.note(f"{r.actor_id}: using its {PROVIDER_LABEL[family]} voice {same.voice_id} through {PROVIDER_LABEL[provider]} ({model}).")
                    source = voice.source
                else:
                    gender = (profile.gender if profile and profile.gender else None) or role_gender(r) or guess_gender(
                        r.role_name, r.description, profile.voice_description if profile else None, profile.persona if profile else None)
                    if not (profile and profile.gender) and not role_gender(r):
                        ctx.note(f"{r.role_name}: gender is not stated anywhere; assumed {gender} when choosing its voice.")
                    pool = "gemini" if family == "gemini" else provider
                    vid = placeholder_voice(gender, counters[gender], pool, exclude=used_voices.get(provider, set()))
                    counters[gender] += 1
                    voice = ProviderVoice(voice_id=vid, model_id=model, source="placeholder" if profile is None else ("prebuilt" if family == "gemini" else "premade"),
                                          added_at=now_iso())
                    if profile is None:  # a temporary voice lives in this production's cast only; it is never written to the Voice IP registry
                        kept = previous.get(r.actor_id)
                        if kept is not None and kept.provider == provider and voice_family(provider, kept.model_id) == family:
                            voice = voice.model_copy(update={"voice_id": kept.voice_id})  # same voice as the series' earlier episodes
                        ctx.note(f"Temporary voice for the background role {r.role_name}: {voice.voice_id} on {PROVIDER_LABEL[provider]} (this production only).")
                        source = "placeholder"
                    else:
                        if stored is None:  # never overwrite a plugged-in voice of another model family
                            registry_repo.set_provider_voice(r.actor_id, provider, voice)
                        ctx.note(f"{r.actor_id}: no {PROVIDER_LABEL[provider]} voice yet; auto-assigned {vid}. Pick a preferred one on the Voice IPs page.")
                        source = voice.source
                reg = registry_repo.load()
                profile = reg.get(r.actor_id) if r.actor_id in reg.ids() else None
                used_voices.setdefault(provider, set()).add(voice.voice_id)
            if provider == "gemini" and source == "premade":
                source = "prebuilt"
            model_id = model
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
