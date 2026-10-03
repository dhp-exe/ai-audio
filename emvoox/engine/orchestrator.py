"""Emvoox Engine: an async state machine that runs the agent fleet for one series.

    [research] -> script -> casting -> for each episode:
        draft -> direct -> voice -> master -> qa --PASS--------------------------> gate
                             ^                  |
                             +---- FLAGGED, retry_instructions, attempt < max ----+   (else -> gate as needs_review)

Every step is one agent call run in a worker thread (``asyncio.to_thread``) so the loop stays
responsive to cancellation. Each step's output is re-validated against its declared contract
before the next agent receives it; a rejected handoff is retried once when the agent says it is
retryable, otherwise the episode stops there. Every transition is an event on the bus; the state
subscriber persists ``RunState`` after each one and the UI polls it.

Episodes are produced one after another by default (D12, vendor rate limits); ``episode_concurrency``
runs several at once. The QA retry loop re-renders only the flagged units with more stable
settings (or splits a multi-speaker chunk into lines), re-masters and re-checks, up to
``max_retries`` times; whatever is still FLAGGED goes to the human gate, and with
``halt_on_qa_fail`` the run halts there so nobody spends credits on the next episodes first.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ValidationError

from emvoox.agents import (
    AgentContext,
    AgentError,
    CastingAgent,
    DirectorAgent,
    MarketResearchAgent,
    PublisherAgent,
    QACriticAgent,
    ScriptWriterAgent,
    SoundEngineerAgent,
)
from emvoox.config import get_settings
from emvoox.contracts.audio import MasteredEpisode, VoiceRenderResult
from emvoox.contracts.cast import ResolvedCast
from emvoox.contracts.direction import DirectedConversationUnits
from emvoox.contracts.market import FormatSpec, TrendBrief
from emvoox.contracts.production import StoryInput
from emvoox.contracts.qa import QAReport
from emvoox.contracts.release import ReleasePackage
from emvoox.contracts.run import (
    EPISODE_STEPS,
    STEP_AGENT,
    STEP_LABEL,
    PipelineEvent,
    RunParams,
    RunState,
    RunTotals,
    StepState,
)
from emvoox.contracts.script import EpisodeDraftResult, ScriptPackage
from emvoox.engine.events import EventBus
from emvoox.providers.llm import LlmClient, LlmProvider, get_llm_provider
from emvoox.repositories import Repositories, get_repositories, now_iso
from emvoox.telemetry.ledger import Ledger


class ContractRejected(AgentError):
    """An agent's output failed the handoff validation."""


class RunHalted(Exception):
    pass


def _engine_ref(provider: str, model: str | None) -> str:
    return f"{provider}/{model}" if model else provider


class Engine:
    def __init__(self, params: RunParams, *, story: StoryInput | str | None = None, brief: TrendBrief | None = None,
                 repos: Repositories | None = None, llm: LlmProvider | str | None = None, episode_concurrency: int = 1,
                 on_event: Callable[[PipelineEvent], None] | None = None):
        self.params = params
        self.story = story
        self.brief = brief
        self.repos = repos or get_repositories()
        self.settings = get_settings()
        self.episode_concurrency = max(1, episode_concurrency)
        llm_name = (llm if isinstance(llm, str) else None) or params.llm_provider or self.settings.llm_provider
        self._llm_provider = llm if llm is not None and not isinstance(llm, str) else None
        self._llm_name = llm_name
        self.run_id = f"{params.series_id}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
        self.state = RunState(run_id=self.run_id, series_id=params.series_id, created_at=now_iso(), params=params, steps=self._build_steps())
        self.bus = EventBus()
        self.bus.subscribe(self._persist)
        if on_event:
            self.bus.subscribe(on_event)
        self.ledger = Ledger(self.repos.telemetry, run_id=self.run_id, series_id=params.series_id)
        self.cancel_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.agents = {
            "market_research": MarketResearchAgent(), "script_writer": ScriptWriterAgent(), "casting": CastingAgent(),
            "director": DirectorAgent(), "sound_engineer": SoundEngineerAgent(), "qa_critic": QACriticAgent(), "publisher": PublisherAgent(),
        }

    # ------------------------------------------------------------------ state
    def _build_steps(self) -> list[StepState]:
        p = self.params
        steps: list[StepState] = []
        series_steps = (["research"] if p.source == "research" else []) + ["script", "casting"]
        for s in series_steps:
            steps.append(StepState(id=s, step=s, agent=STEP_AGENT[s], label=STEP_LABEL[s]))
        for n in p.episode_numbers():
            for s in EPISODE_STEPS:
                steps.append(StepState(id=f"ep{n:02d}.{s}", step=s, agent=STEP_AGENT[s], label=STEP_LABEL[s], episode=n))
        return steps

    def _totals(self) -> RunTotals:
        t = RunTotals(qa_retries=self.state.totals.qa_retries)
        for r in self.ledger.records:
            t.cost_usd += r.cost_usd
            if r.kind == "llm":
                t.llm_calls += 1
                t.tokens_in += r.tokens_in
                t.tokens_out += r.tokens_out
            elif r.kind in ("tts", "sfx"):
                t.tts_requests += r.requests
                t.tts_characters += r.characters
                t.audio_ms += r.audio_ms
        t.cost_usd = round(t.cost_usd, 6)
        return t

    def _persist(self, event: PipelineEvent) -> None:
        with self._lock:
            self.state.totals = self._totals()
            self.repos.runs.save(self.state)
            self.repos.runs.append_event(event)

    def emit(self, type_: str, *, step: StepState | None = None, message: str = "", status: str | None = None, **data: Any) -> None:
        self.bus.publish(PipelineEvent(at=now_iso(), run_id=self.run_id, series_id=self.params.series_id, type=type_,
                                       step_id=step.id if step else None, agent=step.agent if step else None,
                                       episode=step.episode if step else None, status=status or (step.status if step else self.state.status),
                                       message=message, data=data))

    def context(self, step: StepState | None = None, llm: LlmClient | None = None) -> AgentContext:
        sid = self.params.series_id

        def log(msg: str) -> None:
            if step is None:
                return
            stamp = datetime.now(UTC).strftime("%H:%M:%S")
            self.repos.runs.append_log(sid, step.id, f"[{stamp}] {msg}\n")

        ctx = AgentContext(settings=self.settings, repos=self.repos, llm=llm or self.llm, ledger=self.ledger, params=self.params, run_id=self.run_id,
                           log=log, cancel=self.cancel_event, notes=self.state.notes)
        return ctx

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> RunState:
        """Run in a background thread with its own event loop; returns the live state at once."""
        self._thread = threading.Thread(target=lambda: asyncio.run(self.run()), name=f"emvoox-{self.run_id}", daemon=True)
        self._thread.start()
        return self.state

    def wait(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def cancel(self) -> None:
        self.cancel_event.set()

    def _setup_llm(self) -> None:
        provider = self._llm_provider or get_llm_provider(self._llm_name)
        if provider.name != "mock" and not self.settings.key_for(provider.name):
            raise AgentError(f"the LLM provider {provider.name!r} has no API key in .env")
        self.llm = LlmClient(provider, self.ledger, model=self.params.llm_model)
        self.state.engine = {"llm": _engine_ref(provider.name, self.llm.model), "tts": _engine_ref(self.params.tts_provider, self.params.tts_model),
                             "storage": self.repos.backend}

    async def run(self) -> RunState:
        st = self.state
        st.status = "running"
        self.repos.runs.reset_events(self.params.series_id)
        self.emit("run.started", message=f"{len(st.steps)} step(s)")
        try:
            self._setup_llm()
            self._write_inputs()
            await self._series()
            eps = self.params.episode_numbers()
            if self.episode_concurrency == 1:
                for n in eps:
                    if self.cancel_event.is_set():
                        break
                    await self._episode(n)
            else:
                sem = asyncio.Semaphore(self.episode_concurrency)

                async def one(n: int) -> None:
                    async with sem:
                        if not self.cancel_event.is_set():
                            await self._episode(n)

                await asyncio.gather(*(one(n) for n in eps))
            self._finish()
        except RunHalted as e:
            st.status = "halted"
            st.error = str(e)
        except AgentError as e:
            st.status = "failed"
            st.error = str(e)
        except Exception as e:  # noqa: BLE001
            st.status = "failed"
            st.error = f"{type(e).__name__}: {e}"
        finally:
            for s in st.steps:
                if s.status in ("pending", "running"):
                    s.status = "skipped"
            if self.cancel_event.is_set() and st.status == "running":
                st.status = "cancelled"
            st.finished_at = now_iso()
            self.emit("run.finished", message=st.error or st.status, status=st.status)
        return st

    def _finish(self) -> None:
        st = self.state
        failed = [s.id for s in st.steps if s.status == "failed"]
        if self.cancel_event.is_set():
            st.status = "cancelled"
        elif failed:
            st.status = "failed"
            st.error = f"{len(failed)} step(s) failed: {', '.join(failed[:5])}"
        elif any(s.step == "gate" and s.status == "waiting" for s in st.steps):
            st.status = "awaiting_approval"
        else:
            st.status = "done"

    def _write_inputs(self) -> None:
        sid = self.params.series_id
        if isinstance(self.story, StoryInput):
            self.repos.series.save_story(sid, self.story)
        elif isinstance(self.story, str) and self.story.strip():
            self.repos.docs.delete(f"series/{sid}/story.json")
            self.repos.series.save_story_raw(sid, self.story)
        if self.params.source == "brief" and self.brief is None:
            self.brief = self.repos.research.load_brief(self.params.brief_id or "")
            if self.brief is None:
                raise AgentError(f"trend brief {self.params.brief_id!r} not found")

    # ------------------------------------------------------------------ step runner
    async def _step(self, step: StepState, fn: Callable[..., Any], *args: Any, contract: type[BaseModel] | None = None,
                    check: Callable[[Any], None] | None = None, retries: int = 1, summary: Callable[[Any], dict] | None = None,
                    llm: LlmClient | None = None, **kwargs: Any) -> Any:
        """Run one agent call as ``step``. Returns the validated output, or None when the step failed."""
        ctx = self.context(step, llm)
        for attempt in range(retries + 1):
            if self.cancel_event.is_set():
                step.status = "skipped"
                return None
            step.status = "running"
            step.attempts += 1
            step.started_at = step.started_at or now_iso()
            step.error = None
            self.emit("step.started", step=step, attempt=step.attempts)
            mark = self.ledger.mark()
            t0 = time.time()
            try:
                result = await asyncio.to_thread(fn, ctx, *args, **kwargs)
                if contract is not None:
                    try:  # the handoff: the next agent only ever receives a contract-valid payload
                        result = contract.model_validate(result.model_dump() if isinstance(result, BaseModel) else result)
                    except ValidationError as e:
                        raise ContractRejected(f"{contract.__name__} rejected: {str(e)[:400]}", retryable=True) from e
                if check is not None:
                    check(result)
            except AgentError as e:
                elapsed = time.time() - t0
                step.elapsed_s = round(step.elapsed_s + elapsed, 2)
                step.cost_usd = round(step.cost_usd + self.ledger.cost_since(mark), 6)
                self.ledger.agent(agent=step.agent, skill=step.step, elapsed_s=round(elapsed, 2), episode=step.episode, ok=False, note=str(e)[:160])
                ctx.log(f"ERROR {e}")
                if isinstance(e, ContractRejected):
                    self.emit("contract.rejected", step=step, message=str(e)[:300])
                if e.retryable and attempt < retries and not self.cancel_event.is_set():
                    self.emit("step.retry", step=step, message=str(e)[:300])
                    continue
                step.status = "failed"
                step.error = str(e)[:500]
                step.finished_at = now_iso()
                self.emit("step.failed", step=step, message=step.error)
                return None
            except Exception as e:  # noqa: BLE001 - an unexpected bug fails the step, not the process
                step.status = "failed"
                step.error = f"{type(e).__name__}: {str(e)[:400]}"
                step.finished_at = now_iso()
                ctx.log(f"ERROR {step.error}")
                self.emit("step.failed", step=step, message=step.error)
                return None
            elapsed = time.time() - t0
            step.elapsed_s = round(step.elapsed_s + elapsed, 2)
            step.cost_usd = round(step.cost_usd + self.ledger.cost_since(mark), 6)
            self.ledger.agent(agent=step.agent, skill=step.step, elapsed_s=round(elapsed, 2), episode=step.episode)
            step.summary = summary(result) if summary else {}
            step.status = "done"
            step.finished_at = now_iso()
            self.emit("step.finished", step=step)
            return result
        return None

    def _skip_rest(self, n: int, after: str, reason: str) -> None:
        for s in EPISODE_STEPS[EPISODE_STEPS.index(after) + 1:]:
            st = self.state.step(f"ep{n:02d}.{s}")
            if st.status == "pending":
                st.status = "skipped"
                st.error = reason
        self.emit("episode.stopped", message=reason, episode=n)

    # ------------------------------------------------------------------ series steps
    async def _series(self) -> None:
        p = self.params
        if p.source == "research":
            step = self.state.step("research")
            fmt = FormatSpec(episodes=min(30, max(10, p.episodes)), episode_seconds_min=p.min_sec, episode_seconds_max=p.max_sec)
            self.brief = await self._step(step, self.agents["market_research"].run, p.research, fmt=fmt, contract=TrendBrief,
                                          summary=lambda b: {"brief_id": b.brief_id, "topic": b.topic, "theme": b.theme_category.value, "score": b.score,
                                                             "sources": len(b.sources)})
            if self.brief is None:
                raise AgentError("market research failed")
        story = self.story if isinstance(self.story, StoryInput) else None
        pkg = await self._step(self.state.step("script"), self.agents["script_writer"].write_series, story=story, brief=self.brief, contract=ScriptPackage,
                               summary=lambda s: {"title": s.bible.title, "episodes": len(s.bible.episodes), "mode": s.bible.mode,
                                                  "roles": len(s.bible.roles), "reused": s.outline_reused, "from_brief": s.adapted_from_brief})
        if pkg is None:
            raise AgentError("the Script Writer could not produce a series bible")
        if len(pkg.bible.episodes) < max(self.params.episode_numbers() or [0]):
            raise AgentError(f"the bible plans {len(pkg.bible.episodes)} episode(s); cannot produce {self.params.episode_numbers()}")

        def check_cast(c: ResolvedCast) -> None:
            roles = {r.role_name for r in pkg.bible.roles}
            missing = roles - {m.role_name for m in c.members}
            if missing:
                raise ContractRejected(f"roles left uncast: {sorted(missing)}", retryable=True)

        cast = await self._step(self.state.step("casting"), self.agents["casting"].run, contract=ResolvedCast, check=check_cast,
                                summary=lambda c: {"members": len(c.members), "providers": c.providers(),
                                                   "placeholders": [m.actor_id for m in c.members if m.voice_source == "placeholder"],
                                                   "cloned": [m.actor_id for m in c.members if m.voice_source == "cloned"]})
        if cast is None:
            raise AgentError("casting failed")
        self.cast = cast
        self.state.casting = [{"role": m.role_name, "type": m.role_type, "actor": m.actor_id, "actor_name": m.display_name, "assigned_by": m.assigned_by,
                               "reason": m.reason, "provider": m.provider, "model": m.model_id, "voice": m.voice_id, "voice_source": m.voice_source}
                              for m in cast.members]
        self.emit("cast.resolved", message=f"{len(cast.members)} role(s)")

    # ------------------------------------------------------------------ episode steps
    def _check_directed(self, n: int) -> Callable[[DirectedConversationUnits], None]:
        def check(d: DirectedConversationUnits) -> None:
            if d.episode_number != n or d.series_id != self.params.series_id:
                raise ContractRejected(f"directed units belong to {d.series_id}/ep{d.episode_number:02d}, expected ep{n:02d}", retryable=True)
            unknown = d.speakers() - self.cast.actor_ids()
            if unknown:
                raise ContractRejected(f"speakers outside the resolved cast: {sorted(unknown)}", retryable=True)
            for u in d.spoken():
                m = self.cast.member(u.speaker_id)
                if (u.provider, u.voice_id) != (m.provider, m.voice_id):
                    raise ContractRejected(f"{u.unit_id}: voice {u.provider}/{u.voice_id} differs from the cast's {m.provider}/{m.voice_id}", retryable=True)
        return check

    async def _episode(self, n: int) -> None:
        e = f"ep{n:02d}"
        S = self.state.step  # noqa: N806
        sw, director, sound, qa, pub = (self.agents[k] for k in ("script_writer", "director", "sound_engineer", "qa_critic", "publisher"))

        draft = await self._step(S(f"{e}.draft"), sw.write_episode, n, contract=EpisodeDraftResult,
                                 summary=lambda d: {"words": d.words, "scenes": d.scenes, "est_sec": d.estimated_duration_sec, "reused": d.reused,
                                                    "hook": d.cliffhanger.hook_score if d.cliffhanger else None, "rewrites": d.rewrites})
        if draft is None:
            return self._skip_rest(n, "draft", "draft failed")

        directed = await self._step(S(f"{e}.direct"), director.run, n, self.cast, contract=DirectedConversationUnits, check=self._check_directed(n),
                                    summary=lambda d: {"units": len(d.units), "requests": len(d.render_plan), "batching": d.batching,
                                                       "characters": d.characters()})
        if directed is None:
            return self._skip_rest(n, "direct", "the Director's output was rejected")

        def voice_summary(v: VoiceRenderResult) -> dict:
            return {"planned": v.planned, "rendered": v.rendered, "cached": v.cached, "failed": v.failed, "characters": v.characters,
                    "placeholder_voices": v.placeholder_voices}

        voice = await self._step(S(f"{e}.voice"), sound.generate_voice, directed, self.cast, force=self.params.force, contract=VoiceRenderResult,
                                 summary=voice_summary)
        if voice is None:
            return self._skip_rest(n, "voice", "voice rendering failed")
        if voice.failed and voice.rendered == 0 and voice.cached == 0:
            S(f"{e}.voice").status = "failed"
            S(f"{e}.voice").error = "; ".join(f"{k}: {v}" for k, v in list(voice.errors.items())[:3])
            self.emit("step.failed", step=S(f"{e}.voice"), message=S(f"{e}.voice").error)
            return self._skip_rest(n, "voice", "no stem could be rendered")
        if voice.failed:
            S(f"{e}.voice").status = "warn"

        def master_summary(m: MasteredEpisode) -> dict:
            return {"duration_ms": m.duration_ms, "lufs": m.loudness.integrated_lufs, "true_peak": m.loudness.true_peak_dbtp, "stems": m.stems,
                    "bgm": m.bgm, "sfx": m.sfx, "attempt": m.attempt}

        mastered = None if voice.failed else await self._step(S(f"{e}.master"), sound.assemble_audio, directed, voice, contract=MasteredEpisode,
                                                               retries=0, summary=master_summary)
        if voice.failed:
            S(f"{e}.master").status = "skipped"
            S(f"{e}.master").error = "stems missing; QA decides what to re-render"

        def qa_summary(r: QAReport) -> dict:
            return {"status": r.status, "score": r.score, "issues": len(r.error_logs), "attempt": r.attempt,
                    "codes": sorted({i.code for i in r.error_logs}), "retry": [f"{x.action}:{len(x.unit_ids)}" for x in r.retry_instructions]}

        attempt = 0
        report = await self._step(S(f"{e}.qa"), qa.run, directed, self.cast, mastered, attempt=attempt, contract=QAReport, retries=0, summary=qa_summary)
        if report is None:
            return self._skip_rest(n, "qa", "QA could not run")

        line_mode: set[str] = set()
        attempts: dict[str, int] = {}
        while report.status == "FLAGGED" and report.retry_instructions and attempt < self.params.max_retries and not self.cancel_event.is_set():
            attempt += 1
            self.state.totals.qa_retries += 1
            self.emit("qa.flagged", step=S(f"{e}.qa"), message=f"score {report.score}; retry {attempt}/{self.params.max_retries}",
                      codes=sorted({i.code for i in report.error_logs}))
            affected: set[str] = set()
            old_plan = {r.id: r for r in directed.render_plan}
            remaster_only = all(x.action == "reassemble" for x in report.retry_instructions)
            for ins in report.retry_instructions:
                for uid in ins.unit_ids:
                    attempts[uid] = attempt
                    if ins.action == "rerender_line_mode":
                        line_mode.add(uid)
                        affected.update(old_plan[uid].unit_ids if uid in old_plan else [uid])
                    else:
                        affected.add(uid)
            if not remaster_only:
                directed = await self._step(S(f"{e}.direct"), director.replan, n, self.cast, line_mode=set(line_mode), attempts=dict(attempts),
                                            contract=DirectedConversationUnits, check=self._check_directed(n), retries=0,
                                            summary=lambda d: {"units": len(d.units), "requests": len(d.render_plan), "batching": d.batching,
                                                               "characters": d.characters(), "replanned": True})
                if directed is None:
                    break
                new_ids = {r.id for r in directed.render_plan}
                only = {uid for uid in affected if uid in new_ids}
                voice = await self._step(S(f"{e}.voice"), sound.generate_voice, directed, self.cast, only=only, force=True,
                                         contract=VoiceRenderResult, summary=voice_summary)
                if voice is None:
                    break
            mastered = await self._step(S(f"{e}.master"), sound.assemble_audio, directed, voice, attempt=attempt, contract=MasteredEpisode,
                                        retries=0, summary=master_summary)
            report = await self._step(S(f"{e}.qa"), qa.run, directed, self.cast, mastered, attempt=attempt, contract=QAReport, retries=0, summary=qa_summary)
            if report is None:
                return self._skip_rest(n, "qa", "QA could not run")
        if report.status == "FLAGGED":
            S(f"{e}.qa").status = "warn"

        gate = S(f"{e}.gate")
        exhausted = report.status == "FLAGGED" and attempt >= self.params.max_retries
        pkg = await self._step(gate, pub.approval_gate, mastered, report, exhausted=exhausted, contract=ReleasePackage, retries=0,
                               summary=lambda r: {"state": r.state, "qa": r.qa_status, "score": r.qa_score, "attempts": r.qa_attempts, "reason": r.reason})
        if pkg is None:
            return None
        gate.status = "approved" if pkg.state == "approved" else "waiting"
        self.emit("gate.approved" if pkg.state == "approved" else "gate.waiting", step=gate, message=pkg.reason)
        if report.status == "FLAGGED" and self.params.halt_on_qa_fail:
            for s in self.state.steps:
                if s.episode and s.episode > n and s.status == "pending":
                    s.status = "skipped"
                    s.error = f"run halted: {e} needs human review"
            raise RunHalted(f"{e} is still FLAGGED after {attempt} automatic retr{'y' if attempt == 1 else 'ies'}; review it on the Approvals page, "
                            "then continue the series")
        return None


# ---------------------------------------------------------------------- CLI


def _parse_only(spec: str | None) -> list[int] | None:
    if not spec:
        return None
    out: list[int] = []
    for part in spec.split(","):
        lo, _, hi = part.strip().partition("-")
        out.extend(range(int(lo), int(hi or lo) + 1))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the Emvoox agent pipeline for one series.")
    ap.add_argument("--series", required=True)
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--story", help="story text (.txt) or StoryInput (.json)")
    src.add_argument("--brief", help="TrendBrief id from data/research/briefs/")
    src.add_argument("--research", action="store_true", help="start with the Market Research Agent")
    ap.add_argument("--seeds", default="", help="research: trend notes to analyse (text)")
    ap.add_argument("--browser", action="store_true", help="research: also scan public platform pages with Playwright")
    ap.add_argument("--episodes", type=int, default=30)
    ap.add_argument("--produce", type=int, default=None)
    ap.add_argument("--only", help="episode numbers to produce, e.g. 6-10 or 3,7 (resume an existing series)")
    ap.add_argument("--min-sec", type=int, default=50)
    ap.add_argument("--max-sec", type=int, default=70)
    ap.add_argument("--tts", default=None, help="gemini | elevenlabs | wavespeed | mock (default EMVOOX_TTS_PROVIDER)")
    ap.add_argument("--tts-model", default=None)
    ap.add_argument("--batching", choices=["auto", "line", "scene"], default=None)
    ap.add_argument("--llm", default=None, help="gemini | wavespeed | openai | anthropic | mock (default EMVOOX_LLM_PROVIDER)")
    ap.add_argument("--llm-model", default=None)
    ap.add_argument("--max-retries", type=int, default=None)
    ap.add_argument("--auto-approve", action="store_true")
    ap.add_argument("--no-halt", action="store_true", help="keep producing after an episode stays FLAGGED")
    ap.add_argument("--tier", choices=["test", "final"], default="test")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    s = get_settings()
    repos = get_repositories()
    only = _parse_only(a.only)
    episodes = a.episodes
    bible = repos.series.load_bible(a.series)
    if only and bible is not None:
        episodes = len(bible.episodes) or episodes
    provider = a.tts or s.tts_provider
    model = a.tts_model or (s.tts_model if provider == s.tts_provider else None)
    story: StoryInput | str | None = None
    source = "existing" if (only and bible) else "story"
    if a.story:
        from pathlib import Path

        text = Path(a.story).read_text(encoding="utf-8")
        story = StoryInput.model_validate_json(text) if a.story.endswith(".json") else text
        source = "story"
    elif a.brief:
        source = "brief"
    elif a.research:
        source = "research"
    params = RunParams(series_id=a.series, episodes=episodes, produce=a.produce, only=only, min_sec=a.min_sec, max_sec=a.max_sec, force=a.force,
                       source=source, brief_id=a.brief, research={"seeds": a.seeds, "use_browser": a.browser or None},  # type: ignore[arg-type]
                       tts_provider=provider, tts_model=model, tts_batching=a.batching or s.tts_batching, tier=a.tier,
                       llm_provider=a.llm, llm_model=a.llm_model, max_retries=a.max_retries if a.max_retries is not None else s.qa_max_retries,
                       auto_approve=a.auto_approve or s.auto_approve, halt_on_qa_fail=not a.no_halt and s.halt_on_qa_fail)

    def show(ev: PipelineEvent) -> None:
        if ev.type in ("step.finished", "step.failed", "step.retry", "contract.rejected", "qa.flagged", "gate.waiting", "gate.approved", "run.finished"):
            print(f"{ev.at[11:19]} {ev.type:<18} {ev.step_id or '':<12} {ev.status or '':<10} {ev.message[:110]}", file=sys.stderr)

    engine = Engine(params, story=story, repos=repos, on_event=show)
    st = asyncio.run(engine.run())
    print(json.dumps({"ok": st.status in ("done", "awaiting_approval"), "run_id": st.run_id, "status": st.status, "error": st.error,
                      "cost_usd": st.totals.cost_usd, "qa_retries": st.totals.qa_retries}))
    return 0 if st.status in ("done", "awaiting_approval") else 1


if __name__ == "__main__":
    sys.exit(main())
