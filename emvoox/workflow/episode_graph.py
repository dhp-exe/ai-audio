"""One episode: draft -> direct -> scenes in parallel -> join -> master -> episode QA -> gate.

    draft -> direct -> scenes_start -+-> scene (scene_graph, one branch per scene) -+-> scenes_join -> master -> qa -> gate
                                     +-> scene                                    --+                    ^      |
                                                                                             remaster ---+------+
                                                                                             (loudness off, bounded)

Each scene renders, checks and retries on its own (``scene_graph``); vendor requests of all scenes share the
engine's per-provider cap. The join saves the episode's plan once with every scene's retry parameters, writes
the render manifest and closes the ``voice`` step. Only then is the episode mastered. Episode QA rolls the scene
reports up and adds what only a master can answer; a loudness miss is re-mastered up to ``max_retries`` times.
The gate parks the episode for a reviewer, as before: nothing is exported without a human (D11).
"""

from __future__ import annotations

import asyncio
import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from emvoox.contracts.audio import MasteredEpisode, StemRecord, VoiceRenderResult
from emvoox.contracts.direction import DirectedConversationUnits
from emvoox.contracts.qa import QAReport, SceneApproval, SceneQAReport
from emvoox.contracts.release import ReleasePackage
from emvoox.contracts.script import EpisodeDraftResult
from emvoox.engine.orchestrator import (
    Engine,
    directed_summary,
    draft_summary,
    gate_summary,
    master_summary,
    qa_summary,
    replanned_summary,
    voice_summary,
)
from emvoox.repositories import now_iso
from emvoox.workflow.scene_graph import build_scene_graph, merge_scenes


class EpisodeState(TypedDict, total=False):
    n: int
    scenes: Annotated[dict[str, dict], merge_scenes]
    voice: dict | None  # the episode's VoiceRenderResult, summed over its scenes
    mastered: bool
    remasters: int
    stopped: bool  # the episode ended early; the reason is on the skipped steps
    done: Annotated[list[int], operator.add]
    halted: str | None


class EpisodeOutput(TypedDict, total=False):
    done: Annotated[list[int], operator.add]
    halted: str | None


def scene_ids(directed: DirectedConversationUnits) -> list[str]:
    """Scenes of the plan, in order."""
    return list(dict.fromkeys(r.scene_id for r in directed.render_plan))


def build_episode_graph(eng: Engine):
    sw, director, sound, qa, pub = (eng.agents[k] for k in ("script_writer", "director", "sound_engineer", "qa_critic", "publisher"))
    sid = eng.params.series_id

    def S(n: int, step: str):  # noqa: N802
        return eng.state.step(f"ep{n:02d}.{step}")

    def directed_of(n: int) -> DirectedConversationUnits:
        d = eng.repos.series.load_directed(sid, n)
        if d is None:
            raise ValueError(f"ep{n:02d} has no directed plan")
        return d

    def stop(n: int, after: str, reason: str) -> dict:
        eng._skip_rest(n, after, reason)
        return {"stopped": True, "done": [n]}

    async def draft(state: EpisodeState) -> dict:
        n = state["n"]
        d = await eng._step(S(n, "draft"), sw.write_episode, n, contract=EpisodeDraftResult, summary=draft_summary)
        return {} if d is not None else stop(n, "draft", "draft failed")

    async def direct(state: EpisodeState) -> dict:
        n = state["n"]
        d = await eng._step(S(n, "direct"), director.run, n, eng.cast, contract=DirectedConversationUnits, check=eng._check_directed(n),
                            summary=directed_summary)
        return {} if d is not None else stop(n, "direct", "the Director's output was rejected")

    async def scenes_start(state: EpisodeState) -> dict:
        """Opens the voice step once for all scenes."""
        n = state["n"]
        step = S(n, "voice")
        if eng.cancel_event.is_set():
            step.status = "skipped"
            return stop(n, "voice", "cancelled")
        step.status = "running"
        step.attempts += 1
        step.started_at = step.started_at or now_iso()
        step.error = None
        eng.emit("step.started", step=step, attempt=step.attempts)
        return {}

    def fan_out(state: EpisodeState):
        if state.get("stopped"):
            return END
        n = state["n"]
        return [Send("scene", {"n": n, "scene_id": scene_id}) for scene_id in scene_ids(directed_of(n))]

    async def scenes_join(state: EpisodeState) -> dict:
        """Every scene is back: save the plan once, write the manifest, close the voice step."""
        n = state["n"]
        step = S(n, "voice")
        scenes = state.get("scenes") or {}
        # scenes work side by side and may wait days for a reviewer: the step's time is the longest scene's working time
        step.elapsed_s = round(step.elapsed_s + max([s.get("worked_s", 0.0) for s in scenes.values()] or [0.0]), 2)
        step.cost_usd = round(step.cost_usd + sum((s.get("tally") or {}).get("cost_usd", 0.0) for s in scenes.values()), 6)
        errors = {k: v["error"] for k, v in scenes.items() if v.get("error")}
        if errors:
            step.status, step.error, step.finished_at = "failed", "; ".join(f"{k}: {v}" for k, v in errors.items())[:500], now_iso()
            eng.emit("step.failed", step=step, message=step.error)
            return stop(n, "voice", "a scene could not be rendered")
        attempts = {k: v for s in scenes.values() for k, v in s["attempts"].items()}
        line_mode = {u for s in scenes.values() for u in s["line_mode"]}
        if attempts or line_mode:  # some scene retried: the saved plan must be the one the stems were rendered from
            directed = await eng._step(S(n, "direct"), director.replan, n, eng.cast, line_mode=line_mode, attempts=attempts,
                                       contract=DirectedConversationUnits, check=eng._check_directed(n), retries=0, summary=replanned_summary)
            if directed is None:
                step.status, step.error, step.finished_at = "failed", "the retried plan was rejected", now_iso()
                eng.emit("step.failed", step=step, message=step.error)
                return stop(n, "voice", "the retried plan was rejected")
        else:
            directed = directed_of(n)
        await asyncio.to_thread(sound.write_manifest, eng.context(step), directed)
        tallies = [s["tally"] for s in scenes.values()]
        voice = VoiceRenderResult(
            series_id=sid, episode_number=n, planned=sum(t["planned"] for t in tallies), rendered=sum(t["rendered"] for t in tallies),
            cached=sum(t["cached"] for t in tallies), failed=sorted(u for t in tallies for u in t["failed"]),
            characters=sum(t["characters"] for t in tallies), cost_usd=round(sum(t["cost_usd"] for t in tallies), 6),
            placeholder_voices=sorted({v for t in tallies for v in t["placeholder_voices"]}),
            stems=sorted((StemRecord.model_validate(s) for t in tallies for s in t["stems"]), key=lambda s: s.unit_id),
            errors={k: v for t in tallies for k, v in t["errors"].items()})
        retries = sum(s["attempt"] for s in scenes.values())
        step.summary = {**voice_summary(voice), "scenes": len(scenes), "scene_retries": retries,
                        "flagged_scenes": sorted(k for k, s in scenes.items() if (s.get("report") or {}).get("status") == "FLAGGED")}
        step.status, step.finished_at = ("warn" if voice.failed or step.summary["flagged_scenes"] else "done"), now_iso()
        eng.emit("step.finished", step=step)
        return {"voice": voice.model_dump(mode="json")}

    async def master(state: EpisodeState) -> dict:
        n = state["n"]
        voice = VoiceRenderResult.model_validate(state["voice"])
        if voice.failed:
            S(n, "master").status = "skipped"
            S(n, "master").error = "stems missing; see the scene reports"
            return {"mastered": False}
        m = await eng._step(S(n, "master"), sound.assemble_audio, directed_of(n), voice, attempt=state.get("remasters", 0), contract=MasteredEpisode,
                            retries=0, summary=master_summary)
        return {"mastered": m is not None}

    def episode_attempt(state: EpisodeState) -> int:
        return max([s["attempt"] for s in (state.get("scenes") or {}).values()] + [state.get("remasters", 0)])

    async def qa_node(state: EpisodeState) -> dict:
        n = state["n"]
        reports = [SceneQAReport.model_validate(s["report"]) for s in (state.get("scenes") or {}).values() if s.get("report")]
        approvals = {k: SceneApproval.model_validate(s["approval"]) for k, s in (state.get("scenes") or {}).items() if s.get("approval")}
        reports = [r.model_copy(update={"approval": approvals[r.scene_id]}) if r.scene_id in approvals else r for r in reports]
        mastered = eng.repos.series.load_mastered(sid, n) if state.get("mastered") else None
        report = await eng._step(S(n, "qa"), qa.run, directed_of(n), eng.cast, mastered, attempt=episode_attempt(state), scenes=reports,
                                 contract=QAReport, retries=0, summary=qa_summary)
        return {} if report is not None else stop(n, "qa", "QA could not run")

    def report_of(n: int) -> QAReport:
        r = eng.repos.series.load_qa(sid, n)
        if r is None:
            raise ValueError(f"ep{n:02d} has no QA report")
        return r

    def after_qa(state: EpisodeState) -> str:
        if state.get("stopped"):
            return END
        report = report_of(state["n"])
        remaster_only = bool(report.retry_instructions) and all(x.action == "reassemble" for x in report.retry_instructions)
        again = report.status == "FLAGGED" and remaster_only and state.get("remasters", 0) < eng.params.max_retries
        return "remaster" if again and not eng.cancel_event.is_set() else "gate"

    async def remaster(state: EpisodeState) -> dict:
        n = state["n"]
        report = report_of(n)
        remasters = state.get("remasters", 0) + 1
        eng.state.totals.qa_retries += 1
        eng.emit("qa.flagged", step=S(n, "qa"), message=f"score {report.score}; re-master {remasters}/{eng.params.max_retries}",
                 codes=sorted({i.code for i in report.error_logs}))
        return {"remasters": remasters}

    async def gate(state: EpisodeState) -> dict:
        n = state["n"]
        e = f"ep{n:02d}"
        report = report_of(n)
        attempt = episode_attempt(state)
        if report.status == "FLAGGED":
            S(n, "qa").status = "warn"
        step = S(n, "gate")
        exhausted = report.status == "FLAGGED" and attempt >= eng.params.max_retries
        mastered = eng.repos.series.load_mastered(sid, n) if state.get("mastered") else None
        pkg = await eng._step(step, pub.approval_gate, mastered, report, exhausted=exhausted, contract=ReleasePackage, retries=0, summary=gate_summary)
        if pkg is None:
            return {"done": [n]}
        step.status = "approved" if pkg.state == "approved" else "waiting"
        eng.emit("gate.approved" if pkg.state == "approved" else "gate.waiting", step=step, message=pkg.reason)
        if report.status == "FLAGGED" and eng.params.halt_on_qa_fail:
            for s in eng.state.steps:
                if s.episode and s.episode > n and s.status == "pending":
                    s.status = "skipped"
                    s.error = f"run halted: {e} needs human review"
            return {"done": [n], "halted": f"{e} is still FLAGGED after {attempt} automatic retr{'y' if attempt == 1 else 'ies'}; review it on the "
                                           "Approvals page, then continue the series"}
        return {"done": [n]}

    def unless_stopped(nxt: str):
        return lambda state: END if state.get("stopped") else nxt

    g = StateGraph(EpisodeState, output_schema=EpisodeOutput)
    g.add_node("draft", draft)
    g.add_node("direct", direct)
    g.add_node("scenes_start", scenes_start)
    g.add_node("scene", build_scene_graph(eng))
    g.add_node("scenes_join", scenes_join)
    g.add_node("master", master)
    g.add_node("qa", qa_node)
    g.add_node("remaster", remaster)
    g.add_node("gate", gate)
    g.add_edge(START, "draft")
    g.add_conditional_edges("draft", unless_stopped("direct"), ["direct", END])
    g.add_conditional_edges("direct", unless_stopped("scenes_start"), ["scenes_start", END])
    g.add_conditional_edges("scenes_start", fan_out, ["scene", END])
    g.add_edge("scene", "scenes_join")
    g.add_conditional_edges("scenes_join", unless_stopped("master"), ["master", END])
    g.add_edge("master", "qa")
    g.add_conditional_edges("qa", after_qa, ["remaster", "gate", END])
    g.add_edge("remaster", "master")
    g.add_edge("gate", END)
    return g.compile()
