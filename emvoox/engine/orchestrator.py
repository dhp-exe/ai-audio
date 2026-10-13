"""Emvoox Engine: runs the agent fleet for one series on the workflow graph.

    [research] -> script -> casting -> for each episode:
        draft -> direct -> scenes in parallel (render -> QA -> retry -> [approval]) -> join -> master -> episode QA -> gate

The order, the fan-out, the pauses and the checkpoints live in ``emvoox/workflow`` (LangGraph). This module is
what the graph's nodes run *with*: the run's state and events, the ledger, the agents, and ``_step``, which runs
one agent call in a worker thread, re-validates its output against the declared contract before the next agent
receives it, retries a rejected handoff once when the agent says it is retryable, and records time and cost.

Every transition is an event on the bus; the state subscriber persists ``RunState`` after each one and the UI
polls it. A run ends, or waits for a person (a scene to approve, a budget to raise) and is continued with
``Engine.run(resume=...)``, in this process or, through ``Engine.restore``, in another one.
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
from emvoox.contracts.market import TrendBrief
from emvoox.contracts.production import StoryInput
from emvoox.contracts.qa import QAReport
from emvoox.contracts.release import ReleasePackage
from emvoox.contracts.run import (
    EPISODE_STEPS,
    STEP_AGENT,
    STEP_LABEL,
    PendingDecision,
    PipelineEvent,
    RunParams,
    RunState,
    RunTotals,
    SceneRun,
    StepState,
)
from emvoox.contracts.script import EpisodeDraftResult
from emvoox.engine.events import EventBus
from emvoox.providers.llm import LlmClient, LlmProvider, get_llm_provider
from emvoox.repositories import Repositories, get_repositories, now_iso
from emvoox.telemetry.ledger import Ledger
from emvoox.workflow.limits import ProviderLimiter


class ContractRejected(AgentError):
    """An agent's output failed the handoff validation."""


class RunHalted(Exception):
    pass


class RunInterrupted(AgentError):
    """A run found in progress with nothing to continue from."""


def _engine_ref(provider: str, model: str | None) -> str:
    return f"{provider}/{model}" if model else provider


# Step summaries shown on the run board; shared by the native engine and the workflow graph.
def draft_summary(d: EpisodeDraftResult) -> dict:
    return {"words": d.words, "scenes": d.scenes, "est_sec": d.estimated_duration_sec, "reused": d.reused,
            "hook": d.cliffhanger.hook_score if d.cliffhanger else None, "rewrites": d.rewrites}


def directed_summary(d: DirectedConversationUnits) -> dict:
    return {"units": len(d.units), "requests": len(d.render_plan), "batching": d.batching, "characters": d.characters()}


def replanned_summary(d: DirectedConversationUnits) -> dict:
    return {**directed_summary(d), "replanned": True}


def voice_summary(v: VoiceRenderResult) -> dict:
    return {"planned": v.planned, "rendered": v.rendered, "cached": v.cached, "failed": v.failed, "characters": v.characters,
            "placeholder_voices": v.placeholder_voices}


def master_summary(m: MasteredEpisode) -> dict:
    return {"duration_ms": m.duration_ms, "lufs": m.loudness.integrated_lufs, "true_peak": m.loudness.true_peak_dbtp, "stems": m.stems,
            "bgm": m.bgm, "sfx": m.sfx, "attempt": m.attempt}


def qa_summary(r: QAReport) -> dict:
    return {"status": r.status, "score": r.score, "issues": len(r.error_logs), "attempt": r.attempt,
            "codes": sorted({i.code for i in r.error_logs}), "retry": [f"{x.action}:{len(x.unit_ids)}" for x in r.retry_instructions]}


def gate_summary(r: ReleasePackage) -> dict:
    return {"state": r.state, "qa": r.qa_status, "score": r.qa_score, "attempts": r.qa_attempts, "reason": r.reason}


class Engine:
    """Runs one series: owns the run's state, events, ledger and agents, and drives the workflow graph.

    ``run()`` executes until the run ends or has to wait for a person (``status == "waiting"``, with the open
    decisions in ``state.pending``). What it does follows from the saved state, so any process can pick a run up:

        pending   start it (``Engine.create`` saved it for a worker, or this engine was just built)
        waiting   continue it with ``run(resume={decision id: answer})``; decisions left out stay open
        running   the process that was running it died: recover from the workflow graph's last checkpoint

    ``Engine.restore`` rebuilds the engine of a series' latest run from storage.
    """

    def __init__(self, params: RunParams, *, story: StoryInput | str | None = None, brief: TrendBrief | None = None,
                 repos: Repositories | None = None, llm: LlmProvider | str | None = None,
                 on_event: Callable[[PipelineEvent], None] | None = None, state: RunState | None = None):
        self.params = params
        self.story = story
        self.brief = brief
        self.repos = repos or get_repositories()
        self.settings = get_settings()
        llm_name = (llm if isinstance(llm, str) else None) or params.llm_provider or self.settings.llm_provider
        self._llm_provider = llm if llm is not None and not isinstance(llm, str) else None
        self._llm_name = llm_name
        if state is None:
            self.run_id = f"{params.series_id}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
            self.state = RunState(run_id=self.run_id, series_id=params.series_id, created_at=now_iso(), params=params, steps=self._build_steps(),
                                  budget_usd=params.max_cost_usd)
        else:
            self.run_id, self.state = state.run_id, state
        self._restored = state is not None
        self._prepared = state is not None
        self._base_totals = self.state.totals.model_copy()  # what earlier processes of this run already spent
        self.bus = EventBus(start=len(self.repos.runs.events(params.series_id)) if state is not None else 0)
        self.bus.subscribe(self._persist)
        if on_event:
            self.bus.subscribe(on_event)
        self.ledger = Ledger(self.repos.telemetry, run_id=self.run_id, series_id=params.series_id)
        self.limiter = ProviderLimiter()  # scenes render in parallel and share one cap per provider
        self.cancel_event = threading.Event()
        self._lock = threading.Lock()
        self._cast: ResolvedCast | None = None
        self.agents = {
            "market_research": MarketResearchAgent(), "script_writer": ScriptWriterAgent(), "casting": CastingAgent(),
            "director": DirectorAgent(), "sound_engineer": SoundEngineerAgent(), "qa_critic": QACriticAgent(), "publisher": PublisherAgent(),
        }

    @classmethod
    def create(cls, params: RunParams, *, story: StoryInput | str | None = None, brief: TrendBrief | None = None,
               repos: Repositories | None = None) -> Engine:
        """Save a new run in state ``pending`` (its inputs written, its event log reset) for a worker to start."""
        engine = cls(params, story=story, brief=brief, repos=repos)
        engine.prepare()
        return engine

    def prepare(self) -> None:
        if self._prepared:
            return
        self._write_inputs()
        self.repos.runs.reset_events(self.params.series_id)
        self.repos.runs.save(self.state)
        self._prepared = True

    @classmethod
    def restore(cls, repos: Repositories, series_id: str, *, llm: LlmProvider | str | None = None,
                on_event: Callable[[PipelineEvent], None] | None = None) -> Engine:
        """The engine of the series' latest run, rebuilt from storage (to continue a run that is waiting)."""
        state = repos.runs.load(series_id)
        if state is None:
            raise AgentError(f"series {series_id!r} has no saved run")
        return cls(state.params, repos=repos, llm=llm, on_event=on_event, state=state)

    # ------------------------------------------------------------------ state
    @property
    def cast(self) -> ResolvedCast:
        if self._cast is None:
            self._cast = self.repos.series.load_cast(self.params.series_id)
            if self._cast is None:
                raise AgentError(f"series {self.params.series_id!r} has no resolved cast yet")
        return self._cast

    @cast.setter
    def cast(self, value: ResolvedCast) -> None:
        self._cast = value

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

    def scene(self, episode: int, scene_id: str) -> SceneRun:
        return self.state.scene(episode, scene_id)

    def _totals(self) -> RunTotals:
        t = self._base_totals.model_copy(update={"qa_retries": self.state.totals.qa_retries})
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

    def spent(self) -> float:
        return self._totals().cost_usd

    def over_budget(self) -> bool:
        cap = self.state.budget_usd
        return cap is not None and self.spent() >= cap

    def _persist(self, event: PipelineEvent) -> None:
        with self._lock:
            self.state.totals = self._totals()
            self.repos.runs.save(self.state)
            self.repos.runs.append_event(event)

    def touch(self) -> None:
        """Save the run board after a change that is not worth an event (a scene moving between phases)."""
        with self._lock:
            self.repos.runs.save(self.state)

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

        return AgentContext(settings=self.settings, repos=self.repos, llm=llm or self.llm, ledger=self.ledger, params=self.params, run_id=self.run_id,
                            log=log, cancel=self.cancel_event, notes=self.state.notes, limiter=self.limiter)

    # ------------------------------------------------------------------ lifecycle
    def cancel(self) -> None:
        self.cancel_event.set()

    def close(self, status: str, error: str | None = None) -> RunState:
        """End the run where it stands (cancelled while queued or waiting, or found without a checkpoint)."""
        st = self.state
        st.status, st.error, st.pending = status, error, []  # type: ignore[assignment]
        for s in st.steps:
            if s.status in ("pending", "running"):
                s.status = "skipped"
        st.finished_at = now_iso()
        self.emit("run.finished", message=error or status, status=status)
        return st

    def load_brief(self) -> TrendBrief | None:
        """The brief this run writes from: handed in, produced by its research step, or named by its parameters."""
        if self.brief is None:
            p = self.params
            if p.source == "brief":
                self.brief = self.repos.research.load_brief(p.brief_id or "")
            elif p.source == "research":
                self.brief = self.repos.series.load_trend_brief(p.series_id)
        return self.brief

    @property
    def thread_id(self) -> str:
        """The run's checkpoint thread; carries the tenant because tenants may share one checkpoint database."""
        return f"{self.repos.tenant}:{self.run_id}"

    def _setup_llm(self) -> None:
        provider = self._llm_provider or get_llm_provider(self._llm_name)
        if provider.name != "mock" and not self.settings.key_for(provider.name):
            raise AgentError(f"the LLM provider {provider.name!r} has no API key in .env")
        self.llm = LlmClient(provider, self.ledger, model=self.params.llm_model)
        self.state.engine = {"llm": _engine_ref(provider.name, self.llm.model), "tts": _engine_ref(self.params.tts_provider, self.params.tts_model),
                             "storage": self.repos.backend}

    async def run(self, resume: dict | None = None) -> RunState:
        """Run until the end, or until a person has to decide. ``resume`` = {pending decision id: answer} continues
        a waiting run; decisions left out stay open."""
        from langgraph.types import Command

        from emvoox.workflow.checkpoints import open_checkpointer
        from emvoox.workflow.series_graph import build_run_graph

        st = self.state
        if resume is not None:
            if st.status != "waiting" or not st.pending:
                raise AgentError(f"run {self.run_id} is not waiting for a decision")
            unknown = set(resume) - {d.id for d in st.pending}
            if unknown:
                raise AgentError(f"unknown decision id(s): {sorted(unknown)}")
            mode = "resume"
        elif st.status == "waiting":
            raise AgentError(f"run {self.run_id} is waiting for a decision; continue it with run(resume=...)")
        elif st.status == "running" and self._restored:
            mode = "recover"
        elif st.status == "pending":
            mode = "start"
        else:
            raise AgentError(f"run {self.run_id} is already {st.status}")
        if mode == "start":
            self.prepare()
        st.status = "running"
        if mode == "start":
            self.emit("run.started", message=f"{len(st.steps)} step(s)")
        elif mode == "resume":
            st.pending = [d for d in st.pending if d.id not in resume]
            self.emit("run.resumed", message=f"{len(resume)} decision(s)")
        else:
            self.emit("run.recovered", message="continuing from the last checkpoint after the worker stopped")
        waiting = False
        try:
            self._setup_llm()
            config = {"configurable": {"thread_id": self.thread_id}, "recursion_limit": 40 + 12 * len(self.params.episode_numbers())}
            async with open_checkpointer(self.repos) as saver:
                graph = build_run_graph(self, saver)
                if mode == "recover" and await saver.aget_tuple(config) is None:
                    raise RunInterrupted("interrupted: the server stopped while this run was in progress and it left no checkpoint; "
                                         "use Continue on the production page")
                # None continues the graph from its checkpoint: the node that was running when the worker died runs again
                payload = Command(resume=resume) if mode == "resume" else ({"done": []} if mode == "start" else None)
                out = await graph.ainvoke(payload, config)
                interrupts = out.get("__interrupt__") or []
                if not interrupts:
                    await saver.adelete_thread(self.thread_id)  # a finished run keeps no checkpoint
            if interrupts:
                waiting = True
                st.pending = sorted((self._pending(i) for i in interrupts), key=lambda d: (d.episode or 0, d.scene_id or ""))
                st.status = "waiting"
                self.emit("run.waiting", message=f"{len(st.pending)} decision(s) needed: " + ", ".join(sorted({d.kind for d in st.pending})))
            elif out.get("failed"):
                st.status, st.error = "failed", out["failed"]
            elif out.get("halted"):
                st.status, st.error = "halted", out["halted"]
            else:
                self._finish()
        except AgentError as e:
            st.status = "cancelled" if isinstance(e, RunInterrupted) else "failed"
            st.error = str(e)
        except Exception as e:  # noqa: BLE001
            st.status = "failed"
            st.error = f"{type(e).__name__}: {e}"
        finally:
            if not waiting:
                st.pending = []
                for s in st.steps:
                    if s.status in ("pending", "running"):
                        s.status = "skipped"
                if self.cancel_event.is_set() and st.status == "running":
                    st.status = "cancelled"
                st.finished_at = now_iso()
                self.emit("run.finished", message=st.error or st.status, status=st.status)
        return st

    def _pending(self, i: Any) -> PendingDecision:
        v = i.value if isinstance(i.value, dict) else {"value": i.value}
        kind = v.get("kind", "scene_approval")
        if kind == "budget":
            message = f"The run has spent ${v.get('spent_usd')} of its ${v.get('budget_usd')} budget. Allow more, or stop."
        else:
            message = (f"ep{v.get('episode', 0):02d} {v.get('scene_id')}: QA {v.get('qa_status')} (score {v.get('score')}). "
                       "Approve the scene, or reject it to render it again.")
        return PendingDecision(id=i.id, kind=kind, episode=v.get("episode"), scene_id=v.get("scene_id"), message=message,
                               data={k: x for k, x in v.items() if k not in ("kind", "episode", "scene_id", "series_id")}, asked_at=now_iso())

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
        if self.params.source == "brief" and self.load_brief() is None:
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

    async def _call(self, step: StepState, agent: str, skill: str, fn: Callable[..., Any], *args: Any, contract: type[BaseModel] | None = None,
                    note: str = "", **kwargs: Any) -> tuple[Any, str | None]:
        """One agent call inside a step that several branches share (a scene of the voice step): validated and
        recorded in the ledger like a step, but the step's own status belongs to whoever opened it.
        Returns (result, None) or (None, error)."""
        ctx = self.context(step)
        t0 = time.time()
        try:
            result = await asyncio.to_thread(fn, ctx, *args, **kwargs)
            if contract is not None:
                result = contract.model_validate(result.model_dump() if isinstance(result, BaseModel) else result)
        except Exception as e:  # noqa: BLE001 - a failing branch reports to its join; it must not cancel its siblings
            error = f"{type(e).__name__}: {str(e)[:400]}"
            self.ledger.agent(agent=agent, skill=skill, elapsed_s=round(time.time() - t0, 2), episode=step.episode, ok=False, note=f"{note}: {error}"[:160])
            ctx.log(f"ERROR {note}: {error}")
            return None, error
        self.ledger.agent(agent=agent, skill=skill, elapsed_s=round(time.time() - t0, 2), episode=step.episode, note=note)
        return result, None

    def _skip_rest(self, n: int, after: str, reason: str) -> None:
        for s in EPISODE_STEPS[EPISODE_STEPS.index(after) + 1:]:
            st = self.state.step(f"ep{n:02d}.{s}")
            if st.status == "pending":
                st.status = "skipped"
                st.error = reason
        self.emit("episode.stopped", message=reason, episode=n)

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
    ap.add_argument("--scene-approval", action="store_true", help="pause every scene for a reviewer after its QA (answer with: emvoox decide)")
    ap.add_argument("--max-cost", type=float, default=None, help="budget cap in USD; reaching it pauses the run for a decision")
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
                       auto_approve=a.auto_approve or s.auto_approve, halt_on_qa_fail=not a.no_halt and s.halt_on_qa_fail,
                       scene_approval=a.scene_approval, max_cost_usd=a.max_cost)

    def show(ev: PipelineEvent) -> None:
        if ev.type in ("step.finished", "step.failed", "step.retry", "contract.rejected", "qa.flagged", "gate.waiting", "gate.approved", "run.finished",
                       "scene.qa", "scene.waiting", "scene.approved", "scene.rejected", "scene.failed", "budget.waiting", "budget.raised", "run.waiting"):
            print(f"{ev.at[11:19]} {ev.type:<18} {ev.step_id or '':<12} {ev.status or '':<10} {ev.message[:110]}", file=sys.stderr)

    engine = Engine(params, story=story, repos=repos, on_event=show)
    st = asyncio.run(engine.run())
    return report(st)


def report(st: RunState) -> int:
    """The one-line JSON summary of a run. A run that waits for a decision is not a failure."""
    ok = st.status in ("done", "awaiting_approval", "waiting")
    print(json.dumps({"ok": ok, "run_id": st.run_id, "status": st.status, "error": st.error, "cost_usd": st.totals.cost_usd,
                      "qa_retries": st.totals.qa_retries, "pending": [d.model_dump(mode="json", exclude={"data", "asked_at"}) for d in st.pending]},
                     ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
