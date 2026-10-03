"""AI Director Agent: raw screenplay -> Directed Conversation Units the Sound Engineer can render as is.

Skills
    Parse Script      LLM structured output: scenes, lines, speaker, emotion, intensity 1-10, audio
                      tags, acoustic direction, pause after each line (EpisodeScript). Speaker labels
                      in the screenplay are ROLE names; the output carries the ACTOR id.
    Delivery Compile  per line and per engine: normalized text, tags kept or folded into a direction,
                      engine settings (stability / style / speed, or a Vietnamese acting direction)
    Render Plan       group lines into TTS requests: one per line, or one multi-speaker conversation
                      chunk per run of lines on engines that support it

The orchestrator validates the returned ``DirectedConversationUnits`` before the Sound Engineer
sees it. ``replan`` rebuilds the units from the saved script without another LLM call; the QA retry
loop uses it to re-render flagged units with adjusted parameters.
"""

from __future__ import annotations

from emvoox import paths
from emvoox.agents.base import Agent, AgentContext, AgentError, Skill
from emvoox.contracts.cast import ResolvedCast
from emvoox.contracts.direction import ConversationUnit, DirectedConversationUnits, RenderUnit
from emvoox.contracts.production import APPROVED_AUDIO_TAGS, PROTAGONIST_ALIAS, EpisodeScript, LineType, SeriesBible
from emvoox.delivery.compile import RETRY_DIRECTION_VI, gemini_style, retry_settings, settings_for_line, speed_for, text_for_provider
from emvoox.delivery.plan import build_transcript, chunk_episode
from emvoox.delivery.screenplay import parse_screenplay
from emvoox.providers.llm import LlmBlocked, LlmError, LlmSchemaError, LlmTruncated
from emvoox.providers.tts.catalog import supports_scene_batching, supports_tags
from emvoox.repositories import now_iso

SYSTEM_PROMPT = """Bạn là Đạo diễn AI cho một series phim ngắn dạng audio bằng tiếng Việt. Bạn chuyển kịch bản thô của một tập thành JSON sản xuất để hệ thống TTS + dựng âm thanh render tự động.

Quy tắc bắt buộc:
- Mỗi VAI trong kịch bản do một DIỄN VIÊN AI (actor_id) thể hiện theo bảng phân vai bên dưới. `character_id` PHẢI là actor_id; `role_name` là tên vai. Không bịa vai mới; nếu gặp người nói lạ, gán cho vai gần nhất và ghi vào director_notes.
- Dòng có nhãn "(nội tâm)" là độc thoại nội tâm ngôi thứ nhất của nhân vật chính: type="monologue", character_id="{alias}". KHÔNG có người dẫn chuyện ngôi thứ ba.
- `text` là lời thoại nguyên văn (tiếng Việt, không tag). `tts_text` là cùng câu đó chuẩn bị cho máy đọc: có thể thêm tag và dấu câu để diễn, viết số bằng chữ.
- emotional_intensity 1-10 tính tương đối trên toàn series; chỉ dành 9-10 cho tối đa hai khoảnh khắc đỉnh của tập.
- acoustic_direction: ghi chú ngắn về cách diễn và không gian. pause_after_ms: 300-500 giữa các câu, tới 1500 sau khoảnh khắc quan trọng.
- Nhạc nền và hiệu ứng đang TẮT: bgm = null, sfx = [], ambience_tag = null.
- Không xuất thông tin thời gian tuyệt đối. Không thêm lời thoại không có trong kịch bản; được phép tách câu dài thành nhiều dòng.
- scene_id tuần tự sc01, sc02...; line_id dạng ep{{NN}}_sc{{NN}}_l{{NNN}}, đánh số lại từ l001 ở mỗi cảnh.
- Dòng thoại cuối cùng phải là cliffhanger; ghi lại vào trường cliffhanger.
"""

_TAGS = ", ".join(f"[{t}]" for t in sorted(APPROVED_AUDIO_TAGS))
TAG_RULES_TAGGED = ("Máy đọc hiểu tag âm thanh. Trong tts_text CHỈ được dùng các tag sau, đặt trước phần lời bị ảnh hưởng: " + _TAGS
                    + ". Tối đa hai tag mỗi dòng. Dòng monologue nên bắt đầu bằng [internal monologue] hoặc [introspective].")
TAG_RULES_DIRECTED = ("Máy đọc diễn theo chỉ dẫn bằng lời: tag trong ngoặc vuông sẽ được đổi thành chỉ dẫn diễn xuất chứ không đọc lên, nên CHỈ dùng các tag sau, "
                      "tối đa hai tag mỗi dòng: " + _TAGS + ". Hãy viết acoustic_direction thật cụ thể (nhịp, âm lượng, cảm xúc) vì máy đọc dựa vào đó.")


WAVESPEED_DIALOGUE_STYLE_VI = "Đọc đoạn hội thoại tiếng Việt như phim truyền hình, diễn xuất tự nhiên; giữa các câu ngắt nghỉ khoảng nửa giây."

class DirectorAgent(Agent):
    id = "director"
    title = "AI Director Agent"
    description = "Turns each screenplay into ordered, fully specified conversation units and a render plan."
    skills = (
        Skill("parse_script", "Parse Script", "Screenplay -> scenes and lines with speaker, emotion, intensity, tags, direction and pauses."),
        Skill("delivery_compile", "Delivery Compile", "Per-engine text and settings for every line (tags, direction, stability, speed)."),
        Skill("render_plan", "Render Plan", "Group lines into TTS requests: per line, or multi-speaker conversation chunks."),
    )
    consumes = "raw screenplay + ResolvedCast"
    produces = DirectedConversationUnits

    # ---- skill: Parse Script
    def build_prompt(self, ctx: AgentContext, raw: str, bible: SeriesBible, cast: ResolvedCast, episode: int) -> tuple[str, str]:
        registry = ctx.repos.registry.load()
        tagged = any(supports_tags(m.provider, m.model_id) for m in cast.members)
        rows = []
        for m in cast.members:
            actor = registry.get(m.actor_id) if m.actor_id in registry.ids() else None
            rows.append(f"- VAI \"{m.role_name}\" ({m.role_type}) -> actor_id: {m.actor_id}"
                        + (f" | {actor.display_name}, giọng: {actor.voice_description}" if actor else "")
                        + (" [NHÂN VẬT CHÍNH, kể chuyện ngôi thứ nhất]" if m.actor_id == cast.protagonist_id else ""))
        plan = bible.episodes[episode - 1] if len(bible.episodes) >= episode else None
        system = (SYSTEM_PROMPT.format(alias=PROTAGONIST_ALIAS) + "\n" + (TAG_RULES_TAGGED if tagged else TAG_RULES_DIRECTED)
                  + f"\n\nSeries: {bible.title}\nTiền đề: {bible.premise}\nGiọng điệu: {bible.tone}\n\nBẢNG PHÂN VAI:\n" + "\n".join(rows) + "\n")
        user = (f"series_id: {bible.series_id}\nepisode_number: {episode}\ntarget_duration_sec: {bible.episode_format.max_duration_sec}\n"
                + (f"Cliffhanger dự kiến: {plan.cliffhanger}\n" if plan else "")
                + f"\nKịch bản thô:\n<script>\n{raw}\n</script>\n\nHãy trả về EpisodeScript.")
        return system, user

    def _finalize(self, script: EpisodeScript, bible: SeriesBible, cast: ResolvedCast, episode: int) -> EpisodeScript:
        """Post-conditions the schema cannot express: every speaker is a cast actor of this series."""
        script.resolve_protagonist(cast.protagonist_id)
        mapping = bible.role_to_actor()
        for m in cast.members:  # the cast is the source of truth for role -> actor
            mapping.update({m.role_name: m.actor_id, m.role_name.lower(): m.actor_id, m.actor_id: m.actor_id})
        script.remap_characters(mapping)
        actor_to_role = {m.actor_id: m.role_name for m in cast.members}
        for _, ln in script.all_lines():
            if ln.type != LineType.pause and ln.character_id in actor_to_role:
                ln.role_name = ln.role_name or actor_to_role[ln.character_id]
        used = {ln.character_id for _, ln in script.all_lines() if ln.type != LineType.pause}
        off_cast = sorted(used - cast.actor_ids())
        if off_cast:
            raise AgentError(f"episode {episode}: speakers not in the resolved cast: {off_cast} (cast: {sorted(cast.actor_ids())})", retryable=True)
        if script.series_id != bible.series_id or script.episode_number != episode:
            script.series_id, script.episode_number = bible.series_id, episode
        script.characters_used = sorted(used)
        return EpisodeScript.model_validate(script.model_dump())

    def parse_script(self, ctx: AgentContext, episode: int, bible: SeriesBible, cast: ResolvedCast, raw: str) -> EpisodeScript:
        system, user = self.build_prompt(ctx, raw, bible, cast, episode)
        role_to_actor = {m.role_name: m.actor_id for m in cast.members}
        plan = bible.episodes[episode - 1] if len(bible.episodes) >= episode else None
        mock_ctx = {"raw": raw, "series_id": bible.series_id, "episode": episode, "target_duration_sec": bible.episode_format.max_duration_sec,
                    "role_to_actor": role_to_actor, "cliffhanger": plan.cliffhanger if plan else ""}
        last: Exception | None = None
        for attempt in range(2):
            try:
                script = ctx.llm.structured(agent=self.id, skill="parse_script", system=system, user=user, schema=EpisodeScript,
                                            episode=episode, context=mock_ctx)
                return self._finalize(script, bible, cast, episode)
            except (LlmSchemaError, AgentError, ValueError) as e:
                last = e
                ctx.log(f"ep{episode:02d}: Director output rejected (attempt {attempt + 1}): {str(e)[:200]}")
            except (LlmBlocked, LlmTruncated) as e:
                raise AgentError(f"episode {episode}: {e}") from e
            except LlmError as e:
                raise AgentError(f"episode {episode}: {e}", retryable=True) from e
        # Two rejected answers: direct by rules so production is not blocked; the lines stay verbatim.
        try:
            script = parse_screenplay(raw, series_id=bible.series_id, episode_number=episode, role_to_actor=role_to_actor,
                                      target_duration_sec=bible.episode_format.max_duration_sec, cliffhanger=plan.cliffhanger if plan else "")
            ctx.note(f"ep{episode:02d}: the Director's LLM output was rejected twice ({str(last)[:120]}); directed by rules with neutral delivery.")
            return self._finalize(script, bible, cast, episode)
        except (ValueError, AgentError) as e:
            raise AgentError(f"episode {episode}: could not direct the screenplay: {last}; rule-based fallback: {e}", retryable=True) from e

    # ---- skill: Delivery Compile
    def delivery_compile(self, ctx: AgentContext, script: EpisodeScript, cast: ResolvedCast) -> list[ConversationUnit]:
        normalize = ctx.settings.normalize_vi
        units: list[ConversationUnit] = []
        for order, (scene, line) in enumerate(script.all_lines(), start=1):
            if line.type == LineType.pause:
                units.append(ConversationUnit(unit_id=line.line_id, scene_id=scene.scene_id, order=order, type=line.type, pause_after_ms=line.pause_after_ms))
                continue
            m = cast.member(line.character_id)
            settings = settings_for_line(line, m.provider, m.model_id, m.voice_settings)
            units.append(ConversationUnit(
                unit_id=line.line_id, scene_id=scene.scene_id, order=order, type=line.type, speaker_id=line.character_id,
                role_name=line.role_name or m.role_name, text=line.text, tts_text=text_for_provider(line, m.provider, m.model_id, normalize=normalize),
                emotion_tag=line.emotion, emotional_intensity=line.emotional_intensity, audio_tags=line.audio_tags(),
                direction=line.acoustic_direction, pause_after_ms=line.pause_after_ms, speed=speed_for(line), volume=line.volume,
                provider=m.provider, model_id=m.model_id, voice_id=m.voice_id, settings=settings,
                sfx=list(line.sfx) if ctx.settings.enable_sfx else []))
        return units

    # ---- skill: Render Plan
    def render_plan(self, ctx: AgentContext, script: EpisodeScript, cast: ResolvedCast, units: list[ConversationUnit], *,
                    line_mode: set[str] | None = None, attempts: dict[str, int] | None = None) -> tuple[list[RenderUnit], str]:
        """(render units in episode order, batching summary). ``line_mode`` holds chunk ids that must be
        rendered line by line; ``attempts`` maps render unit ids (or line ids) to their retry attempt."""
        line_mode, attempts = line_mode or set(), attempts or {}
        batching = cast.engine_policy.batching
        by_id = {u.unit_id: u for u in units}
        descriptions = {c.character_id: c.voice_description for c in ctx.repos.registry.load().characters}

        def can_batch(line) -> bool:
            m = cast.member(line.character_id)
            return batching != "line" and supports_scene_batching(m.provider, m.model_id)

        chunk_of: dict[str, object] = {}
        line_attempt: dict[str, int] = {}
        for chunk in chunk_episode(script, can_batch=can_batch):
            models = {cast.member(a).model_id for a in chunk.actors}
            if chunk.chunk_id in line_mode or len(models) > 1:
                for lid in chunk.line_ids:  # rendered line by line below, carrying the chunk's retry attempt
                    line_attempt[lid] = attempts.get(chunk.chunk_id, 0)
                continue
            for lid in chunk.line_ids:
                chunk_of[lid] = chunk
        plan: list[RenderUnit] = []
        done: set[str] = set()
        for u in units:
            if not u.is_spoken():
                continue
            chunk = chunk_of.get(u.unit_id)
            if chunk is not None:
                if chunk.chunk_id in done:  # type: ignore[attr-defined]
                    continue
                done.add(chunk.chunk_id)  # type: ignore[attr-defined]
                member = cast.member(chunk.actors[0])  # type: ignore[attr-defined]
                model_id = member.model_id
                header, transcript, speakers = build_transcript(chunk, cast, model_id, normalize=ctx.settings.normalize_vi, descriptions=descriptions)  # type: ignore[arg-type]
                attempt = attempts.get(chunk.chunk_id, 0)  # type: ignore[attr-defined]
                if attempt:
                    header = header.replace(". Diễn xuất theo", f", {RETRY_DIRECTION_VI}. Diễn xuất theo", 1)
                settings: dict = {"style": header}
                if member.provider == "wavespeed" and len(speakers) > 1:
                    # WaveSpeed's Gemini TTS takes dialogue as turns with their own direction; the long header would be billed and cut at 2,000 characters
                    settings = {"style": WAVESPEED_DIALOGUE_STYLE_VI + (f" {RETRY_DIRECTION_VI.capitalize()}." if attempt else ""),
                                "turn_styles": [gemini_style(ln) for ln in chunk.lines]}  # type: ignore[attr-defined]
                plan.append(RenderUnit(
                    id=chunk.chunk_id, kind="conversation", scene_id=chunk.scene_id, unit_ids=chunk.line_ids, speakers=list(chunk.actors),  # type: ignore[attr-defined]
                    provider=member.provider, model_id=model_id, voice_id=chunk.chunk_id if len(speakers) > 1 else speakers[0][1],  # type: ignore[attr-defined]
                    text=transcript, settings=settings, speaker_voices=list(speakers),
                    stem=paths.chunk_stem_name_from_id(chunk.chunk_id), pause_after_ms=chunk.pause_after_ms, attempt=attempt))  # type: ignore[attr-defined]
                continue
            unit = by_id[u.unit_id]
            attempt = max(attempts.get(unit.unit_id, 0), line_attempt.get(unit.unit_id, 0))
            plan.append(RenderUnit(
                id=unit.unit_id, kind="line", scene_id=unit.scene_id, unit_ids=[unit.unit_id], speakers=[unit.speaker_id],
                provider=unit.provider, model_id=unit.model_id, voice_id=unit.voice_id, text=unit.tts_text,
                settings=retry_settings(unit.settings, unit.provider, unit.model_id, attempt),
                stem=paths.stem_name_from_line_id(unit.unit_id, unit.speaker_id, unit.type.value), pause_after_ms=unit.pause_after_ms,
                attempt=attempt))
        kinds = {r.kind for r in plan}
        return plan, ("mixed" if len(kinds) > 1 else "scene" if kinds == {"conversation"} else "line")

    def _assemble(self, ctx: AgentContext, script: EpisodeScript, cast: ResolvedCast, *, line_mode: set[str] | None = None,
                  attempts: dict[str, int] | None = None) -> DirectedConversationUnits:
        units = self.delivery_compile(ctx, script, cast)
        plan, batching = self.render_plan(ctx, script, cast, units, line_mode=line_mode, attempts=attempts)
        mood = None
        if ctx.settings.enable_bgm:
            mood = next((s.bgm.mood for s in script.scenes if s.bgm), None) or "default"
        try:
            return DirectedConversationUnits(
                series_id=script.series_id, episode_number=script.episode_number, title=script.title, target_duration_sec=script.target_duration_sec,
                batching=batching, units=units, render_plan=plan, cliffhanger=script.cliffhanger, director_notes=script.director_notes,
                bgm_mood=mood, directed_at=now_iso())
        except ValueError as e:
            raise AgentError(f"episode {script.episode_number}: directed units failed validation: {str(e)[:300]}", retryable=True) from e

    # ---- agent entry points
    def run(self, ctx: AgentContext, episode: int, cast: ResolvedCast) -> DirectedConversationUnits:
        repo = ctx.repos.series
        bible = repo.load_bible(ctx.series_id)
        raw = repo.load_raw_script(ctx.series_id, episode)
        if bible is None or raw is None:
            raise AgentError(f"episode {episode}: no screenplay to direct; the Script Writer must run first")
        script = self.parse_script(ctx, episode, bible, cast, raw)
        repo.save_script(script)
        directed = self._assemble(ctx, script, cast)
        repo.save_directed(directed)
        peaks = [u.unit_id for u in directed.units if u.emotional_intensity >= 9]
        ctx.log(f"ep{episode:02d}: {len(directed.units)} unit(s) in {len(script.scenes)} scene(s), {len(directed.render_plan)} request(s) "
                f"({directed.batching}), {directed.characters()} characters, {len(peaks)} peak line(s)")
        return directed

    def replan(self, ctx: AgentContext, episode: int, cast: ResolvedCast, *, line_mode: set[str] | None = None,
               attempts: dict[str, int] | None = None) -> DirectedConversationUnits:
        """Recompile and replan the saved script with retry parameters. No LLM call."""
        repo = ctx.repos.series
        script = repo.load_script(ctx.series_id, episode)
        if script is None:
            raise AgentError(f"episode {episode}: nothing to replan; the episode has not been directed")
        directed = self._assemble(ctx, script, cast, line_mode=line_mode, attempts=attempts)
        repo.save_directed(directed)
        ctx.log(f"ep{episode:02d}: replanned, {len(directed.render_plan)} request(s) ({directed.batching}); "
                f"line mode for {sorted(line_mode or [])}; retry attempts {attempts or {}}")
        return directed
