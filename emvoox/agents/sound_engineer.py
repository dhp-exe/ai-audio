"""Sound Engineer Agent: render plan -> stems -> timeline -> mastered episode.

Skills
    Generate Voice   execute the Director's render plan through the TTS adapters: one WAV stem per
                     render unit (44.1 kHz / 16-bit / mono), a sidecar per stem (hash, request, cost,
                     alignment), content-hash cache, bounded thread pool, and the ElevenLabs
                     "paid plan required" fallback to the actor's premade voice (flagged)
    Generate SFX     place sound-effect cues: a library clip from assets/sfx/<tag>.wav, or one
                     generated with ElevenLabs sound effects when ENABLE_SFX is on and the key exists
    Assemble Audio   timeline from measured durations, silence gaps, optional music bed ducked under
                     the speech, two-pass loudnorm to -16 LUFS / -1.5 dBTP, stereo WAV + MP3
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

from emvoox import paths
from emvoox.agents.base import Agent, AgentContext, AgentError, Skill
from emvoox.audio.ffmpeg import AudioToolError, measure_ebur128
from emvoox.audio.mix import SfxPlacement, render_master
from emvoox.audio.timeline import MissingStems, build_timeline, unit_offsets
from emvoox.casting import guess_gender, placeholder_voice
from emvoox.contracts.audio import LoudnessMetrics, MasteredEpisode, StemRecord, VoiceRenderResult
from emvoox.contracts.cast import ResolvedCast
from emvoox.contracts.direction import DirectedConversationUnits, RenderUnit
from emvoox.providers.tts import ProviderError, TtsRequest, default_concurrency, get_provider
from emvoox.repositories import now_iso


def request_for(r: RenderUnit) -> TtsRequest:
    return TtsRequest(provider=r.provider, model_id=r.model_id, voice_id=r.voice_id, text=r.text, settings=dict(r.settings),
                      line_id=r.id, speakers=tuple((a, b) for a, b in r.speaker_voices), attempt=r.attempt)


class SoundEngineerAgent(Agent):
    id = "sound_engineer"
    title = "Sound Engineer Agent"
    description = "Calls the TTS engines for every render unit, places SFX, and masters the episode with FFmpeg."
    skills = (
        Skill("generate_voice", "Generate Voice", "Render each unit of the plan through its engine; cached by content hash."),
        Skill("generate_sfx", "Generate SFX", "Sound-effect clips from the library, or generated (ElevenLabs) when enabled."),
        Skill("assemble_audio", "Assemble Audio", "Timeline, silence gaps, ducked music bed, two-pass loudnorm, WAV + MP3 master."),
    )
    consumes = "DirectedConversationUnits"
    produces = MasteredEpisode

    # ---- skill: Generate Voice
    def is_cached(self, ctx: AgentContext, sid: str, n: int, r: RenderUnit) -> bool:
        if not ctx.repos.series.stem_exists(sid, n, r.stem):
            return False
        meta = ctx.repos.series.stem_meta(sid, n, r.stem)
        return bool(meta) and meta.get("hash") == request_for(r).content_hash()

    def generate_voice(self, ctx: AgentContext, directed: DirectedConversationUnits, cast: ResolvedCast, *,
                       only: set[str] | None = None, force: bool = False) -> VoiceRenderResult:
        sid, n = directed.series_id, directed.episode_number
        repo = ctx.repos.series
        units = [r for r in directed.render_plan if not only or r.id in only]
        todo = [r for r in units if force or not self.is_cached(ctx, sid, n, r)]
        cached = len(units) - len(todo)
        ctx.log(f"generate voice: {len(units)} unit(s), {len(todo)} to render, {cached} cached")

        def render(r: RenderUnit) -> StemRecord:
            if ctx.cancel.is_set():
                raise AgentError("cancelled")
            req = request_for(r)
            out = repo.stem_path(sid, n, r.stem)
            engine = get_provider(r.provider)
            t0 = time.time()
            placeholder = False
            try:
                info = engine.synthesize(req, out)
            except ProviderError as e:
                if r.provider == "elevenlabs" and e.status == 402 and r.kind == "line":
                    # The plan refuses this voice (library/PVC voice on the Free tier): render with the actor's
                    # premade fallback so the episode completes; QA flags the stem as a placeholder.
                    m = cast.member(r.speakers[0])
                    alt = m.fallback_voice_id or placeholder_voice(guess_gender(m.role_name, m.display_name))
                    req = TtsRequest(provider=req.provider, model_id=req.model_id, voice_id=alt, text=req.text, settings=req.settings,
                                     line_id=req.line_id, attempt=req.attempt)
                    info = engine.synthesize(req, out)
                    info["voice_fallback"] = {"requested": r.voice_id, "used": alt, "reason": str(e)[:160]}
                    placeholder = True
                else:
                    raise
            elapsed = time.time() - t0
            ctx.repos.blobs.commit(paths.stem(sid, n, r.stem))
            meta = {"hash": request_for(r).content_hash(), "request": req.as_dict(), "rendered_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "elapsed_s": round(elapsed, 2), "unit_id": r.id, "line_ids": r.unit_ids, "actors": r.speakers, "scene_id": r.scene_id,
                    "kind": r.kind, "attempt": r.attempt, **{k: v for k, v in info.items() if k != "prompt"}}
            repo.save_stem_meta(sid, n, r.stem, meta)
            ctx.ledger.tts(agent=self.id, skill="generate_voice", provider=r.provider, model=r.model_id, characters=int(info.get("characters_billed") or len(req.text)),
                           audio_ms=int(info.get("duration_ms") or 0), elapsed_s=round(elapsed, 2), episode=n, unit_id=r.id,
                           tokens_in=int(info.get("tokens_in") or 0), tokens_out=int(info.get("tokens_out") or 0))
            return StemRecord(unit_id=r.id, stem=r.stem, provider=r.provider, model_id=r.model_id, voice_id=req.voice_id,
                              duration_ms=int(info.get("duration_ms") or 0), characters=len(req.text), placeholder=placeholder, attempt=r.attempt)

        providers = {r.provider for r in todo}
        workers = min(default_concurrency(p) for p in providers) if providers else 1
        stems: list[StemRecord] = []
        failed: list[str] = []
        errors: dict[str, str] = {}
        mark = ctx.ledger.mark()
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {pool.submit(render, r): r.id for r in todo}
            for fut in as_completed(futures):
                uid = futures[fut]
                try:
                    rec = fut.result()
                except Exception as e:  # noqa: BLE001 - record and continue; QA reports the gap
                    failed.append(uid)
                    errors[uid] = f"{type(e).__name__}: {str(e)[:300]}"
                    ctx.log(f"  {uid}: FAILED {errors[uid]}")
                    continue
                stems.append(rec)
                ctx.log(f"  {uid}: {rec.duration_ms} ms, {rec.characters} chars, {rec.provider}/{rec.model_id}{' (placeholder voice)' if rec.placeholder else ''}")
        for r in units:
            if r.id not in {s.unit_id for s in stems} and r.id not in failed:
                stems.append(StemRecord(unit_id=r.id, stem=r.stem, provider=r.provider, model_id=r.model_id, voice_id=r.voice_id, cached=True, attempt=r.attempt))
        repo.save_manifest(sid, n, {
            "version": 2, "batching": directed.batching, "episode": n, "written_at": now_iso(),
            "units": [{"id": r.id, "kind": r.kind, "path": r.stem, "scene_id": r.scene_id, "line_ids": r.unit_ids, "actors": r.speakers,
                       "pause_after_ms": r.pause_after_ms, "provider": r.provider, "model_id": r.model_id, "attempt": r.attempt}
                      for r in directed.render_plan]})
        placeholders = sorted({s.voice_id for s in stems if s.placeholder})
        if placeholders:
            ctx.note(f"ep{n:02d}: the ElevenLabs plan refused voice(s); rendered with premade fallbacks {placeholders}. Upgrade the plan and re-run to use the real Voice IPs.")
        return VoiceRenderResult(series_id=sid, episode_number=n, planned=len(units), rendered=len(todo) - len(failed), cached=cached,
                                 failed=sorted(failed), characters=sum(s.characters for s in stems if not s.cached),
                                 cost_usd=ctx.ledger.cost_since(mark), placeholder_voices=placeholders, stems=sorted(stems, key=lambda s: s.unit_id),
                                 errors=errors)

    # ---- skill: Generate SFX
    def generate_sfx(self, ctx: AgentContext, directed: DirectedConversationUnits, offsets: dict[str, int]) -> list[SfxPlacement]:
        if not ctx.settings.enable_sfx:
            return []
        placements: list[SfxPlacement] = []
        for u in directed.units:
            for cue in u.sfx:
                path = ctx.repos.assets.sfx_path(cue.tag)
                if path is None and ctx.settings.elevenlabs_api_key:
                    path = self._generate_sfx_clip(ctx, cue.tag, cue.description, directed.episode_number)
                if path is None:
                    ctx.log(f"sfx: no clip for {cue.tag!r} (add assets/sfx/{cue.tag}.wav); skipped")
                    continue
                try:
                    r = directed.render_unit_for(u.unit_id)
                except KeyError:
                    continue
                base = offsets.get(r.id, 0)
                at = base + cue.offset_ms if cue.position != "after" else base + cue.offset_ms + 500
                placements.append(SfxPlacement(path=path, at_ms=max(0, at - (300 if cue.position == "before" else 0))))
        ctx.log(f"sfx: {len(placements)} cue(s) placed")
        return placements

    def _generate_sfx_clip(self, ctx: AgentContext, tag: str, description: str, episode: int):
        try:
            from elevenlabs.client import ElevenLabs

            from emvoox.providers.tts.base import to_stem_wav

            t0 = time.time()
            audio = b"".join(ElevenLabs(api_key=ctx.settings.elevenlabs_api_key).text_to_sound_effects.convert(
                text=description, duration_seconds=2.0, output_format="mp3_44100_128"))
            out = ctx.repos.assets.sfx_write_path(tag)
            to_stem_wav(audio, out, src_suffix=".mp3")
            ctx.repos.blobs.commit(paths.sfx(tag))
            ctx.ledger.tts(agent=self.id, skill="generate_sfx", provider="elevenlabs", model="eleven_text_to_sound_v2", characters=len(description),
                           audio_ms=2000, elapsed_s=round(time.time() - t0, 2), episode=episode, kind="sfx")
            ctx.log(f"sfx: generated {tag!r} into the library")
            return out
        except Exception as e:  # noqa: BLE001 - an effect is never worth failing the episode for
            ctx.log(f"sfx: could not generate {tag!r}: {type(e).__name__}: {str(e)[:120]}")
            return None

    # ---- skill: Assemble Audio
    def assemble_audio(self, ctx: AgentContext, directed: DirectedConversationUnits, voice: VoiceRenderResult | None = None, *,
                       attempt: int = 0, overrides: dict | None = None) -> MasteredEpisode:
        s = ctx.settings
        o = overrides or {}
        sid, n = directed.series_id, directed.episode_number
        repo = ctx.repos.series
        try:
            tl = build_timeline(directed, lambda name: ctx.repos.blobs.local(paths.stem(sid, n, name)),
                                padding_ms=int(o.get("padding_ms", s.padding_ms)), padding_min=s.padding_min_ms, padding_max=s.padding_max_ms,
                                use_director_pauses=s.use_director_pauses and not o.get("fixed_padding"), scene_gap_ms=int(o.get("scene_gap_ms", s.scene_gap_ms)))
        except MissingStems as e:
            raise AgentError(str(e), retryable=True) from e
        repo.save_timeline(tl)
        bgm = None
        if s.enable_bgm and directed.bgm_mood:
            tracks = ctx.repos.assets.bgm_tracks(directed.bgm_mood) or ctx.repos.assets.bgm_tracks("default")
            bgm = tracks[n % len(tracks)] if tracks else None
            if bgm is None:
                ctx.log(f"bgm: no track under assets/bgm/{directed.bgm_mood}/ or assets/bgm/default/; speech only")
        sfx = self.generate_sfx(ctx, directed, unit_offsets(tl))
        wav_key, mp3_key = paths.master(sid, n, "wav"), paths.master(sid, n, "mp3")
        lufs = float(o.get("lufs", s.loudness_lufs))
        tp = float(o.get("true_peak", s.true_peak_dbtp))
        try:
            render_master(tl, ctx.repos.blobs.path(wav_key), ctx.repos.blobs.path(mp3_key), lufs=lufs, tp=tp, mp3_bitrate=s.mp3_bitrate,
                          bgm=bgm, bgm_gain_db=s.bgm_gain_db, sfx=sfx)
        except AudioToolError as e:
            raise AgentError(f"mastering failed: {e}", retryable=True) from e
        measured = measure_ebur128(ctx.repos.blobs.local(wav_key)) or {"integrated_lufs": lufs, "true_peak_dbtp": tp, "lra": None}
        stems = sum(1 for c in tl.clips if c.kind == "stem")
        mastered = MasteredEpisode(
            series_id=sid, episode_number=n, title=directed.title, wav_path=wav_key, mp3_path=mp3_key, timeline_path=paths.timeline(sid, n),
            duration_ms=tl.total_duration_ms, loudness=LoudnessMetrics(**measured, target_lufs=lufs, target_true_peak_dbtp=tp),
            stems=stems, rendered=voice.rendered if voice else 0, cached=voice.cached if voice else 0, characters=voice.characters if voice else 0,
            silence_ms=sum(c.duration_ms for c in tl.clips if c.kind == "silence"), bgm=bgm is not None, sfx=len(sfx),
            placeholder_voices=voice.placeholder_voices if voice else [], attempt=attempt, mastered_at=now_iso())
        repo.save_mastered(mastered)
        ctx.log(f"master: {tl.total_duration_ms / 1000:.1f}s, {stems} stem(s), {measured['integrated_lufs']:.1f} LUFS / {measured['true_peak_dbtp']:.1f} dBTP"
                f"{', music bed' if bgm else ''}{f', {len(sfx)} sfx' if sfx else ''}")
        return mastered
