"""A whole run: research -> script -> casting, then one episode after another.

    [research] -> script -> casting -> pick -+-> episode (episode_graph) -> pick ...
                                             +-> budget (pause: the run reached its cap) -> pick
                                             +-> END (nothing left, halted, cancelled)

Episodes are produced in order; the parallelism is inside an episode, across its scenes. Before each episode the
run compares what it has spent with its budget (``RunParams.max_cost_usd``) and pauses for a decision when the cap
is reached: a reviewer raises the cap, or the run halts.

This is the graph a checkpoint belongs to (thread = run id), so a pause anywhere below it (a scene waiting for
approval, the budget) survives the process and resumes from where it stopped.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt

from emvoox.contracts.cast import ResolvedCast
from emvoox.contracts.market import FormatSpec, TrendBrief
from emvoox.contracts.production import StoryInput
from emvoox.contracts.script import ScriptPackage
from emvoox.engine.orchestrator import ContractRejected, Engine
from emvoox.workflow.episode_graph import build_episode_graph


class RunGraphState(TypedDict, total=False):
    done: Annotated[list[int], operator.add]
    current: int | None
    halted: str | None
    failed: str | None


def build_run_graph(eng: Engine, checkpointer: Any = None):
    p = eng.params

    async def research(state: RunGraphState) -> dict:
        fmt = FormatSpec(episodes=min(30, max(10, p.episodes)), episode_seconds_min=p.min_sec, episode_seconds_max=p.max_sec)
        brief = await eng._step(eng.state.step("research"), eng.agents["market_research"].run, p.research, fmt=fmt, contract=TrendBrief,
                                summary=lambda b: {"brief_id": b.brief_id, "topic": b.topic, "theme": b.theme_category.value, "score": b.score,
                                                   "sources": len(b.sources)})
        if brief is None:
            return {"failed": "market research failed"}
        eng.brief = brief
        return {}

    async def script(state: RunGraphState) -> dict:
        story = eng.story if isinstance(eng.story, StoryInput) else None
        brief = eng.load_brief()
        pkg = await eng._step(eng.state.step("script"), eng.agents["script_writer"].write_series, story=story, brief=brief, contract=ScriptPackage,
                              summary=lambda s: {"title": s.bible.title, "episodes": len(s.bible.episodes), "mode": s.bible.mode,
                                                 "roles": len(s.bible.roles), "reused": s.outline_reused, "from_brief": s.adapted_from_brief})
        if pkg is None:
            return {"failed": "the Script Writer could not produce a series bible"}
        if len(pkg.bible.episodes) < max(p.episode_numbers() or [0]):
            return {"failed": f"the bible plans {len(pkg.bible.episodes)} episode(s); cannot produce {p.episode_numbers()}"}
        return {}

    async def casting(state: RunGraphState) -> dict:
        bible = eng.repos.series.load_bible(p.series_id)

        def check_cast(c: ResolvedCast) -> None:
            missing = {r.role_name for r in bible.roles} - {m.role_name for m in c.members}
            if missing:
                raise ContractRejected(f"roles left uncast: {sorted(missing)}", retryable=True)

        cast = await eng._step(eng.state.step("casting"), eng.agents["casting"].run, contract=ResolvedCast, check=check_cast,
                               summary=lambda c: {"members": len(c.members), "providers": c.providers(),
                                                  "placeholders": [m.actor_id for m in c.members if m.voice_source == "placeholder"],
                                                  "cloned": [m.actor_id for m in c.members if m.voice_source == "cloned"]})
        if cast is None:
            return {"failed": "casting failed"}
        eng.cast = cast
        eng.state.casting = [{"role": m.role_name, "type": m.role_type, "actor": m.actor_id, "actor_name": m.display_name, "assigned_by": m.assigned_by,
                              "reason": m.reason, "provider": m.provider, "model": m.model_id, "voice": m.voice_id, "voice_source": m.voice_source}
                             for m in cast.members]
        eng.emit("cast.resolved", message=f"{len(cast.members)} role(s)")
        return {}

    async def pick(state: RunGraphState) -> dict:
        left = [n for n in p.episode_numbers() if n not in (state.get("done") or [])]
        return {"current": left[0] if left else None}

    def after_pick(state: RunGraphState):
        n = state.get("current")
        if n is None or state.get("halted") or state.get("failed") or eng.cancel_event.is_set():
            return END
        if eng.over_budget():
            return "announce_budget"
        return Send("episode", {"n": n})

    async def announce_budget(state: RunGraphState) -> dict:
        eng.emit("budget.waiting", message=f"spent ${eng.spent():.4f} of the ${eng.state.budget_usd:.2f} budget before ep{state['current']:02d}")
        return {}

    async def budget(state: RunGraphState) -> dict:
        spent, cap = eng.spent(), eng.state.budget_usd
        answer = interrupt({"kind": "budget", "series_id": p.series_id, "episode": state.get("current"), "spent_usd": round(spent, 4), "budget_usd": cap})
        answer = answer if isinstance(answer, dict) else {"approved": bool(answer)}
        if not answer.get("approved"):
            return {"halted": f"the run reached its budget (${spent:.4f} of ${cap:.2f}) and was not allowed to spend more"}
        new_cap = float(answer.get("max_cost_usd") or 0)
        if new_cap <= spent:
            new_cap = round(max(spent, cap or 0) * 2, 2) or 1.0  # "continue" without a figure: double it
        eng.state.budget_usd = new_cap
        eng.emit("budget.raised", message=f"budget raised to ${new_cap:.2f} by {answer.get('reviewer') or 'a reviewer'}", budget_usd=new_cap,
                 reviewer=answer.get("reviewer"))
        return {}

    def unless_failed(nxt: str):
        return lambda state: END if state.get("failed") else nxt

    g = StateGraph(RunGraphState)
    first = "script"
    if p.source == "research":
        g.add_node("research", research)
        g.add_conditional_edges("research", unless_failed("script"), ["script", END])
        first = "research"
    g.add_node("script", script)
    g.add_node("casting", casting)
    g.add_node("pick", pick)
    g.add_node("announce_budget", announce_budget)
    g.add_node("budget", budget)
    g.add_node("episode", build_episode_graph(eng))
    g.add_edge(START, first)
    g.add_conditional_edges("script", unless_failed("casting"), ["casting", END])
    g.add_conditional_edges("casting", unless_failed("pick"), ["pick", END])
    g.add_conditional_edges("pick", after_pick, ["announce_budget", "episode", END])
    g.add_edge("announce_budget", "budget")
    g.add_conditional_edges("budget", lambda s: END if s.get("halted") else "pick", ["pick", END])
    g.add_edge("episode", "pick")
    return g.compile(checkpointer=checkpointer)

