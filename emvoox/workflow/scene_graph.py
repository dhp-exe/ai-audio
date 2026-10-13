"""One scene of an episode: render -> QA -> retry -> approval, as its own branch.

    render -> check --PASS, or retries spent------------------> [announce -> approve] -> done
                 ^      |                                                       |
                 +- retry (FLAGGED, attempt < max_retries)                      +- rejected -> redo -> render

Every scene of an episode runs this graph at the same time. A scene retries only its own flagged render units,
with the Director's retry parameters (more stable settings, or a multi-speaker chunk split into lines), up to
``max_retries``. With ``scene_approval`` the scene then waits for a reviewer; a rejection re-renders the scene
(or the units the reviewer names) and asks again.

The scene never saves the episode's plan: it works from a view (``Director.replan(save=False)``) built from its
own retry parameters, and hands those parameters to the episode, which saves the plan once for all scenes.
"""

from __future__ import annotations

import asyncio
import time
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from emvoox.contracts.audio import VoiceRenderResult
from emvoox.contracts.direction import DirectedConversationUnits
from emvoox.contracts.qa import SceneApproval, SceneQAReport
from emvoox.engine.orchestrator import Engine
from emvoox.repositories import now_iso


def merge_scenes(left: dict[str, dict] | None, right: dict[str, dict] | None) -> dict[str, dict]:
    """Fan-in reducer: each branch reports under its own scene id."""
    out = {k: dict(v) for k, v in (left or {}).items()}
    for scene_id, update in (right or {}).items():
        out[scene_id] = {**out.get(scene_id, {}), **update}
    return out


class SceneState(TypedDict, total=False):
    n: int
    scene_id: str
    attempt: int
    attempts: dict[str, int]  # render unit (or line) id -> retry attempt; the Director's retry parameter
    line_mode: list[str]  # conversation chunks that must be rendered line by line
    affected: list[str]  # what the next render must redo
    worked_s: float  # time this scene spent rendering and checking (not waiting for a person)
    tally: dict  # what this scene rendered so far, across attempts
    report: dict | None
    approval: dict | None
    error: str | None
    scenes: Annotated[dict[str, dict], merge_scenes]


class SceneOutput(TypedDict, total=False):
    scenes: Annotated[dict[str, dict], merge_scenes]


def retry_parameters(directed: DirectedConversationUnits, report: SceneQAReport, attempt: int, attempts: dict[str, int],
                     line_mode: set[str]) -> set[str]:
    """Apply a report's retry instructions to the Director's parameters; returns the units to render again."""
    affected: set[str] = set()
    plan = {r.id: r for r in directed.render_plan}
    for ins in report.retry_instructions:
        for uid in ins.unit_ids:
            attempts[uid] = attempt
            if ins.action == "rerender_line_mode":
                line_mode.add(uid)
                affected.update(plan[uid].unit_ids if uid in plan else [uid])
            else:
                affected.add(uid)
    return affected


def build_scene_graph(eng: Engine):
    director, sound, qa = (eng.agents[k] for k in ("director", "sound_engineer", "qa_critic"))
    sid = eng.params.series_id

    def voice_step(n: int):
        return eng.state.step(f"ep{n:02d}.voice")

    def view(state: SceneState) -> DirectedConversationUnits:
        """The episode's plan with this scene's retry parameters applied. Never saved."""
        n = state["n"]
        if not state.get("attempts") and not state.get("line_mode"):
            directed = eng.repos.series.load_directed(sid, n)
            if directed is None:
                raise ValueError(f"ep{n:02d} has no directed plan")
            return directed
        return director.replan(eng.context(voice_step(n)), n, eng.cast, line_mode=set(state.get("line_mode") or []),
                               attempts=dict(state.get("attempts") or {}), save=False)

    async def render(state: SceneState) -> dict:
        n, scene_id, attempt = state["n"], state["scene_id"], state.get("attempt", 0)
        scene = eng.scene(n, scene_id)
        if eng.cancel_event.is_set():
            return {"error": "cancelled"}
        directed = await asyncio.to_thread(view, state)
        ids = [r.id for r in directed.render_plan if r.scene_id == scene_id]
        only = set(ids) if attempt == 0 else ({u for u in state.get("affected") or [] if u in ids} or set(ids))
        scene.status, scene.attempt, scene.units = "rendering", attempt, len(ids)
        eng.touch()
        t0 = time.time()
        result, error = await eng._call(voice_step(n), "sound_engineer", "generate_voice", sound.generate_voice, directed, eng.cast, only=only,
                                        force=eng.params.force, manifest=False, contract=VoiceRenderResult, note=scene_id)
        if error:
            return {"error": error}
        prev = state.get("tally") or {}
        stems = {s["unit_id"]: s for s in prev.get("stems", []) if s["unit_id"] in ids}
        stems.update({s.unit_id: s.model_dump(mode="json") for s in result.stems})
        ok = {s.unit_id for s in result.stems}
        tally = {
            "planned": len(ids), "rendered": prev.get("rendered", 0) + result.rendered, "cached": result.cached if attempt == 0 else prev.get("cached", 0),
            "characters": prev.get("characters", 0) + result.characters, "cost_usd": round(prev.get("cost_usd", 0.0) + result.cost_usd, 6),
            "failed": sorted({u for u in prev.get("failed", []) if u in ids and u not in ok} | set(result.failed)),
            "placeholder_voices": sorted(set(prev.get("placeholder_voices", [])) | set(result.placeholder_voices)),
            "errors": {**{k: v for k, v in prev.get("errors", {}).items() if k in ids and k not in ok}, **result.errors},
            "stems": sorted(stems.values(), key=lambda s: s["unit_id"]),
        }
        return {"tally": tally, "error": None, "worked_s": state.get("worked_s", 0.0) + time.time() - t0}

    async def check(state: SceneState) -> dict:
        n, scene_id, attempt = state["n"], state["scene_id"], state.get("attempt", 0)
        scene = eng.scene(n, scene_id)
        if state.get("error"):
            return {}
        scene.status = "checking"
        eng.touch()
        t0 = time.time()
        directed = await asyncio.to_thread(view, state)
        report, error = await eng._call(eng.state.step(f"ep{n:02d}.qa"), "qa_critic", "review_scene", qa.review_scene, directed, eng.cast, scene_id,
                                        attempt=attempt, contract=SceneQAReport, note=scene_id)
        if error:
            return {"error": error}
        scene.status, scene.score = ("passed" if report.status == "PASS" else "flagged"), report.score
        scene.issues = sorted({i.code for i in report.error_logs})
        eng.emit("scene.qa", step=voice_step(n), status=report.status, message=f"{scene_id}: {report.status} score {report.score}", scene=scene_id,
                 attempt=attempt, score=report.score, codes=scene.issues)
        return {"report": report.model_dump(mode="json"), "worked_s": state.get("worked_s", 0.0) + time.time() - t0}

    def after_check(state: SceneState) -> str:
        if state.get("error"):
            return "done"
        report = SceneQAReport.model_validate(state["report"])
        if report.status == "FLAGGED" and report.retry_instructions and state.get("attempt", 0) < eng.params.max_retries and not eng.cancel_event.is_set():
            return "retry"
        return "announce" if eng.params.scene_approval else "done"

    async def retry(state: SceneState) -> dict:
        n, scene_id = state["n"], state["scene_id"]
        report = SceneQAReport.model_validate(state["report"])
        attempt = state.get("attempt", 0) + 1
        attempts, line_mode = dict(state.get("attempts") or {}), set(state.get("line_mode") or [])
        directed = await asyncio.to_thread(view, state)
        affected = retry_parameters(directed, report, attempt, attempts, line_mode)
        eng.state.totals.qa_retries += 1
        eng.scene(n, scene_id).status = "retrying"
        eng.emit("qa.flagged", step=eng.state.step(f"ep{n:02d}.qa"), message=f"{scene_id}: score {report.score}; retry {attempt}/{eng.params.max_retries}",
                 codes=sorted({i.code for i in report.error_logs}), scene=scene_id)
        return {"attempt": attempt, "attempts": attempts, "line_mode": sorted(line_mode), "affected": sorted(affected)}

    async def announce(state: SceneState) -> dict:
        """Its own node: a paused node runs again from its start whenever any branch is resumed."""
        n, scene_id = state["n"], state["scene_id"]
        eng.scene(n, scene_id).status = "waiting"
        eng.emit("scene.waiting", step=voice_step(n), message=f"{scene_id} is waiting for approval", scene=scene_id)
        return {}

    async def approve(state: SceneState) -> dict:
        n, scene_id = state["n"], state["scene_id"]
        report = SceneQAReport.model_validate(state["report"])
        answer = interrupt({"kind": "scene_approval", "series_id": sid, "episode": n, "scene_id": scene_id, "qa_status": report.status,
                            "score": report.score, "attempt": report.attempt, "issues": sorted({i.code for i in report.error_logs}), "units": report.units})
        answer = answer if isinstance(answer, dict) else {"approved": bool(answer)}
        decision = SceneApproval(approved=bool(answer.get("approved")), reviewer=str(answer.get("reviewer") or ""), notes=str(answer.get("notes") or ""),
                                 unit_ids=[u for u in answer.get("unit_ids") or [] if u in report.units], at=now_iso())
        scene = eng.scene(n, scene_id)
        scene.reviewer = decision.reviewer or None
        if decision.approved:
            scene.status = "approved"
            eng.repos.series.save_scene_qa(report.model_copy(update={"approval": decision}))
        eng.emit("scene.approved" if decision.approved else "scene.rejected", step=voice_step(n), message=f"{scene_id}: {decision.notes}".rstrip(": "),
                 scene=scene_id, reviewer=decision.reviewer)
        return {"approval": decision.model_dump(mode="json")}

    async def redo(state: SceneState) -> dict:
        """A reviewer rejected the scene: render the named units (or all of it) again, one attempt further."""
        report = SceneQAReport.model_validate(state["report"])
        decision = SceneApproval.model_validate(state["approval"])
        attempt = state.get("attempt", 0) + 1
        attempts = dict(state.get("attempts") or {})
        units = decision.unit_ids or report.units
        for uid in units:
            attempts[uid] = attempt
        eng.scene(state["n"], state["scene_id"]).status = "retrying"
        return {"attempt": attempt, "attempts": attempts, "affected": sorted(units), "approval": None}

    async def done(state: SceneState) -> dict:
        n, scene_id = state["n"], state["scene_id"]
        if state.get("error"):
            scene = eng.scene(n, scene_id)
            scene.status, scene.error = "failed", state["error"]
            eng.emit("scene.failed", step=voice_step(n), message=f"{scene_id}: {state['error']}", scene=scene_id)
        return {"scenes": {scene_id: {
            "attempt": state.get("attempt", 0), "attempts": state.get("attempts") or {}, "line_mode": state.get("line_mode") or [],
            "tally": state.get("tally"), "report": state.get("report"), "approval": state.get("approval"), "error": state.get("error"),
            "worked_s": round(state.get("worked_s", 0.0), 2)}}}

    g = StateGraph(SceneState, output_schema=SceneOutput)
    for name, fn in (("render", render), ("check", check), ("retry", retry), ("announce", announce), ("approve", approve), ("redo", redo), ("done", done)):
        g.add_node(name, fn)
    g.add_edge(START, "render")
    g.add_edge("render", "check")
    g.add_conditional_edges("check", after_check, ["retry", "announce", "done"])
    g.add_edge("retry", "render")
    g.add_edge("announce", "approve")
    g.add_conditional_edges("approve", lambda s: "done" if (s.get("approval") or {}).get("approved") else "redo", ["done", "redo"])
    g.add_edge("redo", "render")
    g.add_edge("done", END)
    return g.compile()
