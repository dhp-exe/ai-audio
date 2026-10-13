"""Production tools: start and continue a production run. They spend vendor money, so they are ``external``:
every call waits for a person's approval before it runs. A run is started, not awaited: it works in the
background, and pauses there for the decisions that are a person's to take (scenes, budget, the episode gate).
An agent never answers those decisions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from emvoox.contracts.production import StoryInput, StoryOverview
from emvoox.contracts.run import RunParams
from emvoox.services import library
from emvoox.services.runs import busy, new_series_id, start_run
from emvoox.tools.base import ToolContext, ToolError, tool


class StartProductionArgs(BaseModel):
    source: Literal["brief", "story"] = Field(description="'brief' = produce from a saved trend brief; 'story' = produce the person's own story.")
    brief_id: str | None = Field(None, description="source=brief: the trend brief id.")
    genre_index: int | None = Field(None, ge=0, le=2, description="source=brief: which of the brief's three genres to produce (0 = the top one). "
                                    "Leave empty to keep the genre already selected in the brief.")
    title: str = Field("", description="source=story: the series title.")
    story: str = Field("", description="source=story: the story, treatment or script in Vietnamese (at least a few sentences).")
    episodes: int = Field(10, ge=1, le=30, description="Episodes to plan for the series.")
    produce: int = Field(1, ge=1, le=30, description="Episodes to produce now. Start with 1 so the person can listen before more is spent.")
    scene_approval: bool = Field(False, description="True = pause each scene for the person's approval before the episode is mastered.")
    max_cost_usd: float | None = Field(None, gt=0, description="Budget cap for this run in USD; the run pauses for a decision when it is reached.")


class ContinueProductionArgs(BaseModel):
    series_id: str = Field(description="The production to continue.")
    produce: int = Field(1, ge=1, le=10, description="How many of the remaining episodes to produce now.")
    max_cost_usd: float | None = Field(None, gt=0, description="Budget cap for this run in USD.")


def _submit(ctx: ToolContext):
    if ctx.submit is None:
        raise ToolError("production runs cannot be started from here")
    return ctx.submit


@tool("production_start", area="production", kind="external",
      description="Start producing a new series: script, casting, then the episodes (voice, QA, master). It runs in the background and costs money; "
                  "the person must approve this call. Returns the series id to follow with library_run_status.")
def start(ctx: ToolContext, args: StartProductionArgs) -> dict:
    s = ctx.settings
    story, brief, base = None, None, args.title
    if args.source == "brief":
        brief = ctx.repos.research.load_brief(args.brief_id or "")
        if brief is None:
            raise ToolError(f"no trend brief with id {args.brief_id!r}; call library_list_briefs to see the ids")
        if args.genre_index is not None and args.genre_index != brief.selected:
            try:
                brief = brief.with_selected(args.genre_index)
            except ValueError as e:
                raise ToolError(str(e)) from e
            ctx.repos.research.save_brief(brief)
        base = brief.topic.split(":")[0]
    else:
        if not args.title.strip() or len(args.story.strip()) < 50:
            raise ToolError("a story needs a title and at least 50 characters of story; ask the person for them")
        story = StoryInput(overview=StoryOverview(title=args.title.strip()), roles=[], script=args.story.strip())
    series_id = new_series_id(base)
    try:
        params = RunParams(series_id=series_id, episodes=args.episodes, produce=min(args.produce, args.episodes), source=args.source,
                           brief_id=brief.brief_id if brief else None, tts_provider=s.tts_provider, tts_model=s.tts_model, tts_batching=s.tts_batching,  # type: ignore[arg-type]
                           max_retries=s.qa_max_retries, auto_approve=False, halt_on_qa_fail=s.halt_on_qa_fail, scene_approval=args.scene_approval,
                           max_cost_usd=args.max_cost_usd)
    except ValidationError as e:
        raise ToolError(f"these settings are not valid: {str(e)[:300]}") from e
    state = start_run(ctx.repos, params, _submit(ctx), story=story, brief=brief)
    ctx.session.data.setdefault("runs", []).append({"series_id": series_id, "run_id": state.run_id})
    return {"started": True, "series_id": series_id, "run_id": state.run_id, "episodes_planned": params.episodes, "producing_now": params.episode_numbers(),
            "note": "The run works in the background. It will pause for the person's decisions; nothing is published without their approval."}


@tool("production_continue", area="production", kind="external",
      description="Produce the next episodes of an existing series. Costs money; the person must approve this call.")
def continue_series(ctx: ToolContext, args: ContinueProductionArgs) -> dict:
    s = ctx.settings
    summary = library.series_summary(ctx.repos, args.series_id)
    bible = ctx.repos.series.load_bible(args.series_id)
    if not summary or bible is None:
        raise ToolError(f"production {args.series_id!r} has no outline yet; start it with production_start")
    if busy(ctx.repos, args.series_id):
        raise ToolError(f"production {args.series_id!r} already has a run that is {busy(ctx.repos, args.series_id)['status']}")
    only = summary["remaining"][: args.produce]
    if not only:
        raise ToolError("every planned episode of this production already has a master")
    params = RunParams(series_id=args.series_id, episodes=len(bible.episodes), min_sec=bible.episode_format.min_duration_sec,
                       max_sec=bible.episode_format.max_duration_sec, source="existing", only=only, tts_provider=s.tts_provider, tts_model=s.tts_model,
                       tts_batching=s.tts_batching, max_retries=s.qa_max_retries, halt_on_qa_fail=s.halt_on_qa_fail, max_cost_usd=args.max_cost_usd)  # type: ignore[arg-type]
    state = start_run(ctx.repos, params, _submit(ctx))
    ctx.session.data.setdefault("runs", []).append({"series_id": args.series_id, "run_id": state.run_id})
    return {"started": True, "series_id": args.series_id, "run_id": state.run_id, "producing_now": only}
