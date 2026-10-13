"""Read-only tools over what the studio already has: productions, trend briefs, Voice IPs, runs."""

from __future__ import annotations

from pydantic import BaseModel, Field

from emvoox.services import library
from emvoox.tools.base import ToolContext, ToolError, tool


class NoArgs(BaseModel):
    pass


class SeriesArgs(BaseModel):
    series_id: str = Field(description="The production's id.")


@tool("library_list_series", area="library", kind="read", description="List the studio's productions: id, title, episodes planned, mastered, "
      "waiting for approval and approved.")
def list_series(ctx: ToolContext, args: NoArgs) -> dict:
    return {"series": [{"series_id": s["series_id"], "title": s["title"], "planned": s["planned"], "mastered": s["produced"],
                        "awaiting_approval": s["awaiting"], "needs_review": s["needs_review"], "approved": s["approved"]}
                       for s in library.list_series(ctx.repos)]}


@tool("library_get_series", area="library", kind="read", description="One production in detail: logline, roles and their actors, and each "
      "episode's state (drafted, mastered, QA, approval).")
def get_series(ctx: ToolContext, args: SeriesArgs) -> dict:
    d = library.series_detail(ctx.repos, args.series_id)
    if not d:
        raise ToolError(f"no production with id {args.series_id!r}; call library_list_series to see the ids")
    return {"series_id": args.series_id, "title": d.get("title"), "logline": d.get("logline"),
            "roles": [{"name": r.get("role"), "type": r.get("type"), "actor": r.get("actor_name") or r.get("actor")} for r in d.get("roles", [])],
            "episodes": [{"number": e["number"], "title": e.get("title"), "mastered": e.get("master"), "qa": (e.get("qa") or {}).get("status"),
                          "release": (e.get("release") or {}).get("state")} for e in d.get("episodes", [])]}


@tool("library_list_briefs", area="library", kind="read", description="List the saved trend briefs (market research results): id, date, the "
      "selected genre and story direction, and the three ranked genres.")
def list_briefs(ctx: ToolContext, args: NoArgs) -> dict:
    briefs = sorted(ctx.repos.research.list_briefs(), key=lambda b: b.created_at, reverse=True)[:10]
    return {"briefs": [{"brief_id": b.brief_id, "created_at": b.created_at, "genre": b.genre, "topic": b.topic, "guide": b.guide,
                        "genres": [{"index": i, "genre": c.genre, "topic": c.topic, "score": c.score} for i, c in enumerate(b.candidates)]}
                       for b in briefs]}


@tool("library_list_voice_ips", area="library", kind="read", description="List the Voice IPs (the studio's fixed virtual actors): id, name, "
      "gender, age, persona, and which engines have a voice for them.")
def list_voice_ips(ctx: ToolContext, args: NoArgs) -> dict:
    reg = ctx.repos.registry.load()
    return {"voice_ips": [{"id": c.character_id, "name": c.display_name, "gender": c.gender, "age": c.age, "persona": c.persona,
                           "engines": sorted(c.providers), "cloned_on": sorted(c.cloned_providers())} for c in reg.actors()]}


@tool("library_run_status", area="library", kind="read", description="The state of a production's latest run: status, what it is waiting for, "
      "each episode step, cost so far.")
def run_status(ctx: ToolContext, args: SeriesArgs) -> dict:
    st = ctx.repos.runs.load(args.series_id)
    if st is None:
        raise ToolError(f"production {args.series_id!r} has no run yet")
    return {"run_id": st.run_id, "status": st.status, "error": st.error, "cost_usd": st.totals.cost_usd, "budget_usd": st.budget_usd,
            "waiting_for": [{"kind": d.kind, "episode": d.episode, "scene": d.scene_id, "message": d.message} for d in st.pending],
            "steps": [{"id": s.id, "status": s.status} for s in st.steps if s.status != "pending"],
            "scenes": [{"id": s.id, "status": s.status, "attempt": s.attempt, "score": s.score} for s in st.scenes]}
