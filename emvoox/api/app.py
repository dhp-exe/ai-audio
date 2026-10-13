"""FastAPI app for Emvoox Studio. The UI is the Next.js app in web/ (served from web/out when built); JSON API below.
The TypeScript contract for every route lives in web/lib/api.ts.

Studio
    GET  /api/config  /api/agents  /api/dashboard  /api/doctor[?live=1]
Market research
    POST /api/research/scan          GET /api/research/scans[/{id}]    GET /api/research/scans/{id}/shots/{name}
    GET /api/research/briefs[/{id}]  POST /api/research/briefs/{id}/select  DELETE /api/research/briefs/{id}   GET /api/research/seeds
Runs (the engine)
    POST /api/runs                   GET /api/runs   GET /api/runs/{id}   POST /api/runs/{id}/cancel
    GET  /api/decisions (what paused runs wait for)   POST /api/runs/{id}/decisions (answer; the run continues)
    GET  /api/series/{sid}/episodes/{n}/stems/{name} (listen to a scene before the master exists)
    GET  /api/runs/{id}/steps/{step}/log             GET /api/runs/{id}/events?after=N
Chat (the Producer agent)
    POST /api/chat/threads (first message)   GET /api/chat/threads   GET/DELETE /api/chat/threads/{id}
    POST /api/chat/threads/{id}/messages     POST /api/chat/threads/{id}/answers (questions and approvals the agent is waiting for)
    GET  /api/chat/threads/{id}/events?after=N   GET /api/chat/threads/{id}/stream (server-sent events)
Productions
    GET  /api/library   GET /api/series/{sid}   GET /api/series/{sid}/episodes/{n}   POST /api/series/{sid}/resume
    DELETE /api/series/{sid}         GET /api/series/{sid}/master/{n}.mp3
Human approval gate
    GET  /api/approvals              POST /api/series/{sid}/episodes/{n}/approve | /reject   PUT .../metadata
    GET  /api/outputs                GET /api/outputs/{sid}/{file}
Voice IPs
    GET/POST /api/characters         PUT/DELETE /api/characters/{id}?unlock=
    POST /api/characters/{id}/voices (plug in a cloned voice)   DELETE /api/characters/{id}/voices/{provider}?unlock=
    POST /api/characters/{id}/preview?provider=   POST /api/voices/preview   POST /api/characters/{id}/audition
    GET  /api/previews/{file}   GET /api/auditions/{file}
Costs
    GET  /api/costs   GET /api/usage
"""

from __future__ import annotations

import os
import re
import threading
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from emvoox import __version__, paths
from emvoox.agents import AgentError, fleet
from emvoox.agents import publisher as gate
from emvoox.casting import apply_role_tags, duplicate_actor_pins, parse_roles_text
from emvoox.config import DEFAULT_LLM_MODEL, LLM_MODEL_SUGGESTIONS, LLM_PROVIDERS, REPO_ROOT, get_settings
from emvoox.contracts.cast import EngineRef
from emvoox.contracts.jobs import Job
from emvoox.contracts.market import THEME_LABEL_VI, ThemeCategory
from emvoox.contracts.production import CharacterProfile, ProviderVoice, StoryInput, StoryOverview, StoryRole, VoiceSource
from emvoox.contracts.release import PublishMetadata
from emvoox.contracts.run import LIVE_RUN, ResearchParams, RunParams
from emvoox.engine.orchestrator import Engine
from emvoox.providers.tts import DEFAULT_MODEL, PROVIDER_NAMES, ProviderError, catalog, model_ids
from emvoox.providers.tts.catalog import gemini_voice
from emvoox.repositories import RegistryLocked, get_repositories, now_iso
from emvoox.services import chat, doctor, library, previews, research
from emvoox.services.runs import slug as _slug
from emvoox.telemetry import usage
from emvoox.telemetry.ledger import Ledger
from emvoox.worker import ensure_embedded_worker, get_queue


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    recover_interrupted_runs()
    yield


app = FastAPI(title="Emvoox Studio API", version=__version__, lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in (os.getenv("EMVOOX_CORS_ORIGINS") or os.getenv("AI_AUDIO_CORS_ORIGINS")
                                       or "http://localhost:3000,http://127.0.0.1:3000").split(",") if o.strip()],
    allow_methods=["*"], allow_headers=["*"],
)
WEB_OUT = REPO_ROOT / "web" / "out"  # Next.js static export (cd web && npm run export)

_lock = threading.Lock()


def repos():
    return get_repositories()


def _submit(job: Job) -> Job:
    """Hand a job to the workers. With the memory queue (or EMVOOX_EMBEDDED_WORKER) this process runs one itself."""
    queue = get_queue()
    queue.enqueue(job)
    s = get_settings()
    if s.queue_backend == "memory" or s.embedded_worker:
        ensure_embedded_worker(queue)
    return job


def _live_runs() -> list[dict]:
    """Runs queued or in progress, read from storage: the API holds no engine of its own."""
    r = repos()
    out = []
    for sid in r.series.list_ids():
        raw = r.runs.load_raw(sid)
        if raw and raw.get("status") in LIVE_RUN and "steps" in raw:
            out.append(raw)
    return sorted(out, key=lambda x: x.get("created_at") or "")


def _busy(sid: str) -> dict | None:
    raw = repos().runs.load_raw(sid)
    return raw if raw and raw.get("status") in (*LIVE_RUN, "waiting") and "steps" in raw else None


def recover_interrupted_runs() -> dict[str, list[str]]:
    """At startup: what happened to runs that were queued or in progress when the server last stopped.

    With the Redis queue nothing is needed here: their jobs are still in the queue, and a job whose worker died is
    delivered again. With the memory queue the jobs went with the process, so they are enqueued again: a run that
    had started continues from its checkpoint (``recover``), one that had not starts. A run recorded before the
    workflow graph has no checkpoint to continue from and is closed as interrupted (its finished steps stay done;
    Continue picks up from the cached artifacts)."""
    out: dict[str, list[str]] = {"recovered": [], "interrupted": []}
    r = repos()
    memory = get_settings().queue_backend == "memory"
    for sid in r.series.list_ids():
        data = r.runs.load_raw(sid)
        if not data or data.get("status") not in LIVE_RUN:
            continue
        if "steps" in data:
            if memory:
                _submit(Job(kind="run", action="recover" if data["status"] == "running" else "start", tenant=r.tenant, series_id=sid, run_id=data["run_id"]))
                out["recovered"].append(data["run_id"])
            continue
        data["status"] = "cancelled"
        data["error"] = "interrupted: the server stopped while this run was in progress; use Continue on the production page"
        data["finished_at"] = now_iso()
        for st in data.get("jobs") or []:
            if st.get("status") in LIVE_RUN:
                st["status"] = "skipped"
                st["finished_at"] = st.get("finished_at") or data["finished_at"]
        r.runs.save_raw(sid, data)
        out["interrupted"].append(data.get("run_id", sid))
    return out


def _check_engine(provider: str, model: str | None) -> str | None:
    s = get_settings()
    if provider not in PROVIDER_NAMES or (provider == "mock" and not _mock_enabled()):
        raise HTTPException(422, f"tts_provider must be one of {[p for p in PROVIDER_NAMES if p != 'mock' or _mock_enabled()]}")
    if model and provider != "wavespeed" and model not in model_ids(provider):
        raise HTTPException(422, f"unknown {provider} model {model!r}; expected one of {model_ids(provider)}")
    if provider != "mock" and not s.key_for(provider):
        raise HTTPException(422, f"{provider} has no API key: set {provider.upper()}_API_KEY in .env and restart the server")
    return model or None


def _check_llm(provider: str | None) -> str | None:
    if provider is None:
        return None
    if provider not in LLM_PROVIDERS or (provider == "mock" and not _mock_enabled()):
        raise HTTPException(422, f"llm_provider must be one of {[p for p in LLM_PROVIDERS if p != 'mock' or _mock_enabled()]}")
    if provider != "mock" and not get_settings().key_for(provider):
        raise HTTPException(422, f"the LLM provider {provider!r} has no API key in .env")
    return provider


def _mock_enabled() -> bool:
    s = get_settings()
    return (os.getenv("EMVOOX_ENABLE_MOCK", "").lower() in ("1", "true", "yes")) or s.llm_provider == "mock" or s.tts_provider == "mock"


def _actor_summary(c: CharacterProfile) -> dict:
    r = repos()
    return {"character_id": c.character_id, "display_name": c.display_name, "gender": c.gender, "age": c.age, "is_ip_asset": c.is_ip_asset,
            "persona": c.persona, "tags": c.tags, "voices": {p: v.voice_id for p, v in c.providers.items()},
            "sources": {p: v.source for p, v in c.providers.items()}, "preferred_provider": c.preferred_provider,
            "previews": {p: previews.actor_preview(r, c, p, render=False) for p in c.providers}}


def _start(params: RunParams, *, story: StoryInput | None = None, brief=None) -> dict:
    """Save the run as pending and queue it; a worker starts it."""
    r = repos()
    try:
        engine = Engine.create(params, story=story, brief=brief, repos=r)
    except AgentError as e:
        raise HTTPException(409, str(e)) from e
    _submit(Job(kind="run", action="start", tenant=r.tenant, series_id=params.series_id, run_id=engine.run_id))
    return engine.state.model_dump(mode="json")


def _waiting(sid: str) -> dict | None:
    """The series' latest run, when it is paused for a decision."""
    raw = repos().runs.load_raw(sid)
    return raw if raw and raw.get("status") == "waiting" else None


# ---------------------------------------------------------------------------------------- studio


@app.get("/api/config")
def config() -> dict:
    s = get_settings()
    r = repos()
    reg = r.registry.load()
    active = _live_runs()
    return {
        "version": __version__,
        "llm": {"provider": s.llm_provider, "model": s.llm_model, "providers": [p for p in LLM_PROVIDERS if p != "mock" or _mock_enabled()],
                "defaults": DEFAULT_LLM_MODEL, "models": LLM_MODEL_SUGGESTIONS},
        "tts": {"provider": s.tts_provider, "model": s.tts_model or DEFAULT_MODEL.get(s.tts_provider), "batching": s.tts_batching},
        "keys": s.keys_present(),
        "storage": {"backend": r.backend, "root": r.root, "tenant": r.tenant, "queue": s.queue_backend},
        "catalog": catalog(include_mock=_mock_enabled()),
        "defaults": {"episodes": 30, "produce": 3, "min_sec": 50, "max_sec": 70, "max_retries": s.qa_max_retries, "auto_approve": s.auto_approve,
                     "halt_on_qa_fail": s.halt_on_qa_fail, "qa_transcribe": s.qa_transcribe, "enable_bgm": s.enable_bgm, "enable_sfx": s.enable_sfx,
                     "research_use_browser": s.research_use_browser, "loudness_lufs": s.loudness_lufs, "true_peak_dbtp": s.true_peak_dbtp},
        "actors": [_actor_summary(c) for c in reg.characters],
        "active_run": active[0]["run_id"] if active else None,
        "active_series": active[0]["series_id"] if active else None,
        "theme_categories": [{"id": t.value, "label": THEME_LABEL_VI[t]} for t in ThemeCategory],
        "mock_enabled": _mock_enabled(),
    }


@app.get("/api/agents")
def agents() -> dict:
    """The fleet (what each agent does in the workflow graph), the agents of the runtime with the tools each may
    call, and the tool registry by area."""
    from emvoox.runtime.agents import AGENTS
    from emvoox.tools import load_builtin_tools

    registry = load_builtin_tools()
    tools = [{"name": t.name, "area": t.area, "kind": t.kind, "description": t.description, "parameters": t.spec().parameters} for t in registry.all()]
    return {"agents": fleet(),
            "runtime": [{"id": a.id, "title": a.title, "areas": a.areas, "loadable": a.loadable, "core": a.core, "max_steps": a.max_steps,
                         "max_cost_usd": a.max_cost_usd, "model": a.model,
                         "tools": [t.name for area in a.areas for t in registry.in_area(area)] + a.core} for a in AGENTS.values()],
            "tools": tools}


@app.get("/api/doctor")
def doctor_checks(live: bool = False) -> dict:
    return {"checks": doctor.run_checks(repos(), live=live)}


@app.get("/api/dashboard")
def dashboard() -> dict:
    r = repos()
    live_runs = _live_runs()
    active = {x["series_id"]: x["run_id"] for x in live_runs}
    series = library.list_series(r, active)
    costs = usage.cost_summary(r, vendor_counters=False)
    attention = []
    for item in library.approvals(r):
        if item["state"] in ("needs_review", "awaiting_approval"):
            attention.append({"series_id": item["series_id"], "title": item["series_title"], "episode": item["episode_number"], "state": item["state"],
                              "reason": item["reason"], "at": item["updated_at"]})
    runs = []
    titles = {s["series_id"]: s["title"] for s in series}
    for sid in r.series.list_ids():
        raw = r.runs.load_raw(sid)
        if raw:
            runs.append(library.run_summary(raw, titles.get(sid)))
    live = [library.run_summary(x, titles.get(x["series_id"])) for x in live_runs]
    live_ids = {x["run_id"] for x in live}
    return {
        "kpis": {"series": len(series), "episodes_planned": sum(s["planned"] for s in series), "episodes_mastered": sum(s["produced"] for s in series),
                 "awaiting_approval": sum(s["awaiting"] for s in series), "needs_review": sum(s["needs_review"] for s in series),
                 "approved": sum(s["approved"] for s in series), "cost_month_usd": costs["totals"]["cost_month_usd"],
                 "cost_total_usd": costs["totals"]["cost_usd"], "audio_minutes": round(sum(s["duration_ms_total"] for s in series) / 60000, 1)},
        "active_runs": live,
        "recent_runs": sorted([x for x in runs if x["run_id"] not in live_ids], key=lambda x: x.get("created_at") or "", reverse=True)[:8],
        "productions": series[:12],
        "attention": attention[:12],
        "cost_by_day": [{"date": d["date"], "cost_usd": round(d["llm_usd"] + d["tts_usd"], 6)} for d in costs["by_day"]],
    }


# ---------------------------------------------------------------------------------------- market research


class ScanIn(BaseModel):
    seeds: str = ""
    platforms: list[str] = Field(default_factory=list)
    use_browser: bool | None = None
    focus: str = ""
    guide: str = ""
    llm_provider: str | None = None
    wait: bool = False  # true = answer only when the scan has finished (scripts, tests)
    agent: bool = False  # true = the tool loop: the model decides what to read and search


_SCAN_ID = re.compile(r"scan-[0-9]{8}-[0-9]{6}(-[0-9]+)?")
_scan_lock = threading.Lock()


def _scan_or_404(scan_id: str):
    s = repos().research.load_scan(scan_id) if _SCAN_ID.fullmatch(scan_id) else None
    if s is None:
        raise HTTPException(404, f"no scan {scan_id!r}")
    return s


@app.post("/api/research/scan")
def research_scan(body: ScanIn) -> dict:
    """Start the Market Research Agent. Returns the scan at once; poll GET /api/research/scans/{id} for its progress."""
    r = repos()
    s = get_settings()
    provider = _check_llm(body.llm_provider) or s.llm_provider
    if provider != "mock" and not s.key_for(provider):
        raise HTTPException(422, f"the LLM provider {provider!r} has no API key in .env")
    use_browser = s.research_use_browser if body.use_browser is None else body.use_browser
    if not body.seeds.strip() and not use_browser and not r.research.seed_files():
        raise HTTPException(422, "Nothing to analyse: paste seed notes, add files under data/inputs/trends/, or turn on the browser scan.")
    with _scan_lock:
        if any(sc.status == "running" and time.time() - datetime.fromisoformat(sc.created_at).timestamp() < 900 for sc in r.research.list_scans(5)):
            raise HTTPException(409, "A market scan is already running; wait for it to finish.")
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        scan_id = f"scan-{stamp}"
        n = 1
        while r.research.load_scan(scan_id) is not None:
            n += 1
            scan_id = f"scan-{stamp}-{n}"
        payload = {"scan_id": scan_id, "llm_provider": provider, "seeds": body.seeds, "platforms": body.platforms, "use_browser": body.use_browser,
                   "focus": body.focus, "guide": body.guide, "agent": body.agent}
        if body.wait:
            research.run_scan(r, payload)
        else:
            from emvoox.contracts.market import ScanState

            r.research.save_scan(ScanState(scan_id=scan_id, created_at=now_iso(), guide=body.guide, focus=body.focus, use_browser=use_browser,
                                           platforms=body.platforms, mode="agent" if body.agent else "fixed"))  # visible before a worker's first write
            _submit(Job(kind="scan", tenant=r.tenant, payload=payload))
    return _scan_or_404(scan_id).model_dump(mode="json")


@app.get("/api/research/scans")
def research_scans() -> dict:
    return {"scans": [sc.model_dump(mode="json") for sc in repos().research.list_scans(10)]}


@app.get("/api/research/scans/{scan_id}")
def research_scan_state(scan_id: str) -> dict:
    return _scan_or_404(scan_id).model_dump(mode="json")


@app.get("/api/research/scans/{scan_id}/shots/{name}")
def research_scan_shot(scan_id: str, name: str):
    _scan_or_404(scan_id)
    try:
        key = paths.scan_shot(scan_id, name)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    r = repos()
    if not r.blobs.exists(key):
        raise HTTPException(404, "no such screenshot")
    return FileResponse(r.blobs.local(key), media_type="image/jpeg")


class SelectIn(BaseModel):
    index: int = Field(ge=0)


@app.post("/api/research/briefs/{brief_id}/select")
def research_brief_select(brief_id: str, body: SelectIn) -> dict:
    """The editor picks one of the trending genres; that one is what the Script Writer receives."""
    try:
        b = repos().research.select_candidate(brief_id, body.index)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if b is None:
        raise HTTPException(404, f"no brief {brief_id!r}")
    return b.model_dump(mode="json")


@app.get("/api/research/briefs")
def research_briefs() -> dict:
    return {"briefs": [b.model_dump(mode="json") for b in repos().research.list_briefs()]}


@app.get("/api/research/briefs/{brief_id}")
def research_brief(brief_id: str) -> dict:
    b = repos().research.load_brief(brief_id)
    if not b:
        raise HTTPException(404, "unknown brief")
    return b.model_dump(mode="json")


@app.delete("/api/research/briefs/{brief_id}")
def research_brief_delete(brief_id: str) -> dict:
    repos().research.delete_brief(brief_id)
    return {"ok": True}


@app.get("/api/research/seeds")
def research_seeds() -> dict:
    return {"seeds": [{"name": n, "chars": len(t)} for n, t in repos().research.seed_files()]}


# ---------------------------------------------------------------------------------------- runs


class RoleIn(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    actor_id: str | None = None


class StartRun(BaseModel):
    series_id: str | None = None
    source: str = "story"  # story | brief | research
    brief_id: str | None = None
    research: ResearchParams | None = None
    title: str = ""
    total_minutes: int | None = Field(None, ge=1, le=600)
    genre: str = ""
    setting: str = ""
    roles: list[RoleIn] = Field(default_factory=list)
    roles_text: str = ""
    script: str = ""
    episodes: int = Field(30, ge=1, le=99)
    produce: int | None = Field(None, ge=1, le=99)
    min_sec: int = Field(50, ge=20, le=600)
    max_sec: int = Field(70, ge=20, le=900)
    force: bool = False
    tts_provider: str = "gemini"
    tts_model: str | None = None
    tts_batching: str = "auto"
    tier: str = "test"
    engine_by_role_type: dict[str, EngineRef] = Field(default_factory=dict)
    llm_provider: str | None = None
    llm_model: str | None = None
    max_retries: int = Field(3, ge=0, le=5)
    auto_approve: bool = False
    halt_on_qa_fail: bool = True
    scene_approval: bool = False
    max_cost_usd: float | None = Field(None, gt=0)


@app.post("/api/runs")
def start_run(body: StartRun) -> dict:
    with _lock:
        r = repos()
        if body.source not in ("story", "brief", "research"):
            raise HTTPException(422, "source must be story, brief or research")
        model = _check_engine(body.tts_provider, body.tts_model)
        for ref in body.engine_by_role_type.values():
            _check_engine(ref.provider, ref.model)
        _check_llm(body.llm_provider)
        story: StoryInput | None = None
        brief = None
        if body.source == "story":
            if not body.title.strip() or len(body.script.strip()) < 50:
                raise HTTPException(422, "a story needs a title and a script of at least 50 characters")
            reg = r.registry.load()
            roles = [StoryRole(name=x.name, description=x.description, actor_id=x.actor_id or None) for x in body.roles]
            if body.roles_text.strip():
                roles += parse_roles_text(body.roles_text)
            try:
                roles = apply_role_tags(roles, reg)
            except ValueError as e:
                raise HTTPException(422, str(e)) from e
            bad = [x.actor_id for x in roles if x.actor_id and x.actor_id not in reg.ids()]
            if bad:
                raise HTTPException(422, f"unknown Voice IP id(s): {bad}")
            dup = duplicate_actor_pins(roles)
            if dup:
                raise HTTPException(422, "one Voice IP can play only one role; pinned twice: " + "; ".join(f"{a} -> {', '.join(n)}" for a, n in dup.items()))
            story = StoryInput(overview=StoryOverview(title=body.title, total_minutes=body.total_minutes, genre=body.genre, setting=body.setting),
                               roles=roles, script=body.script)
            base = body.title
        elif body.source == "brief":
            brief = r.research.load_brief(body.brief_id or "")
            if brief is None:
                raise HTTPException(404, f"unknown trend brief {body.brief_id!r}")
            base = brief.topic.split(":")[0]
        else:
            base = "research"
        sid = _slug(body.series_id) if body.series_id else _slug(base) + "-" + datetime.now(UTC).strftime("%m%d%H%M")
        if _busy(sid):
            raise HTTPException(409, f"series '{sid}' already has a run that is {_busy(sid)['status']}: {_busy(sid)['run_id']}")
        if r.series.load_bible(sid) is not None and not body.force:
            raise HTTPException(409, f"series '{sid}' already exists; continue it from Productions, or tick 'overwrite'")
        try:
            params = RunParams(series_id=sid, episodes=body.episodes, produce=body.produce, min_sec=body.min_sec, max_sec=body.max_sec, force=body.force,
                               source=body.source, brief_id=body.brief_id, research=body.research or ResearchParams(),  # type: ignore[arg-type]
                               tts_provider=body.tts_provider, tts_model=model, tts_batching=body.tts_batching, tier=body.tier,  # type: ignore[arg-type]
                               engine_by_role_type=body.engine_by_role_type, llm_provider=body.llm_provider, llm_model=body.llm_model or None,
                               max_retries=body.max_retries, auto_approve=body.auto_approve, halt_on_qa_fail=body.halt_on_qa_fail,
                               scene_approval=body.scene_approval, max_cost_usd=body.max_cost_usd)
        except ValidationError as e:
            raise HTTPException(422, str(e)) from e
        return _start(params, story=story, brief=brief)


@app.get("/api/runs")
def list_runs() -> dict:
    r = repos()
    live = {x["run_id"]: x for x in _live_runs()}
    recent = []
    for sid in r.series.list_ids():
        raw = r.runs.load_raw(sid)
        if raw and raw.get("run_id") not in live:
            bible = r.docs.get(paths.bible(sid)) or {}
            recent.append(library.run_summary(raw, bible.get("title")))
    recent.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return {"active": list(live.values()), "recent": recent}


def _get_run(run_id: str) -> dict:
    r = repos()
    for sid in r.series.list_ids():
        if run_id.startswith(sid + "-"):
            raw = r.runs.load_raw(sid)
            if raw and raw.get("run_id") == run_id:
                return raw
    raise HTTPException(404, "run not found")


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    d = _get_run(run_id)
    if "steps" not in d:  # a run recorded before the Emvoox engine: show its jobs as steps
        d = {**d, "steps": [{"id": j.get("id"), "step": j.get("stage"), "agent": j.get("stage"), "label": j.get("label", j.get("stage")),
                             "episode": j.get("episode"), "status": j.get("status"), "attempts": 1, "started_at": j.get("started_at"),
                             "finished_at": j.get("finished_at"), "elapsed_s": 0, "summary": j.get("summary") or {}, "error": j.get("error"),
                             "cost_usd": 0, "log_key": j.get("log_path")} for j in d.get("jobs", [])],
             "totals": {"cost_usd": 0, "llm_calls": 0, "tokens_in": 0, "tokens_out": 0, "tts_requests": 0, "tts_characters": 0, "audio_ms": 0, "qa_retries": 0},
             "engine": {}, "notes": d.get("notes", []), "casting": d.get("casting", [])}
    return d


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict:
    raw = _get_run(run_id)
    if raw.get("status") in LIVE_RUN and "steps" in raw:
        get_queue().request_cancel(run_id)  # the worker on it stops after the current step; a queued run is closed when claimed
        return {"ok": True}
    if raw.get("status") != "waiting":
        raise HTTPException(404, "run not active")
    # a waiting run holds no worker: close it in place; its artifacts stay and Continue picks them up
    raw.update({"status": "cancelled", "error": "cancelled while waiting for a decision", "finished_at": now_iso(), "pending": []})
    for s in raw.get("steps") or []:
        if s.get("status") in ("pending", "running"):
            s["status"] = "skipped"
    repos().runs.save_raw(raw["series_id"], raw)
    return {"ok": True}


class DecisionIn(BaseModel):
    id: str = Field(min_length=1)
    approved: bool
    reviewer: str = Field(min_length=1)
    notes: str = ""
    unit_ids: list[str] = Field(default_factory=list, description="Rejecting a scene: the render units to redo; empty = the whole scene.")
    max_cost_usd: float | None = Field(None, gt=0, description="Approving a budget decision: the new cap.")


class DecideIn(BaseModel):
    decisions: list[DecisionIn] = Field(min_length=1)


@app.get("/api/decisions")
def decisions() -> dict:
    """Everything a paused run is waiting for a person to decide, across series."""
    r = repos()
    items = []
    for sid in r.series.list_ids():
        raw = _waiting(sid)
        if not raw:
            continue
        title = (r.docs.get(paths.bible(sid)) or {}).get("title") or sid
        for d in raw.get("pending") or []:
            item = {**d, "run_id": raw["run_id"], "series_id": sid, "series_title": title}
            if d.get("kind") == "scene_approval":
                item["scene"] = library.scene_detail(r, sid, d["episode"], d["scene_id"])
            items.append(item)
    return {"items": sorted(items, key=lambda i: (i.get("asked_at") or "", i["series_id"], i.get("episode") or 0, i.get("scene_id") or ""))}


@app.post("/api/runs/{run_id}/decisions")
def decide(run_id: str, body: DecideIn) -> dict:
    """Answer one or more of a waiting run's decisions; the run continues, and the ones left out stay open."""
    with _lock:
        raw = _get_run(run_id)
        open_ids = {d["id"] for d in raw.get("pending") or []}
        # "running" with open decisions = an earlier answer is being carried out; the rest can still be answered
        if raw.get("status") not in ("waiting", "running") or not open_ids:
            raise HTTPException(409, f"run {run_id} is not waiting for a decision (status: {raw.get('status')})")
        unknown = [d.id for d in body.decisions if d.id not in open_ids]
        if unknown:
            raise HTTPException(422, f"not an open decision of this run: {unknown}")
        answers = {d.id: d.model_dump(exclude={"id"}, exclude_none=True) for d in body.decisions}
        r = repos()
        _submit(Job(kind="run", action="resume", tenant=r.tenant, series_id=raw["series_id"], run_id=run_id, resume=answers))
        # shown as running at once; the worker that takes the job continues the run from its checkpoint
        raw["status"] = "running"
        raw["pending"] = [d for d in raw["pending"] if d["id"] not in answers]
        r.runs.save_raw(raw["series_id"], raw)
        return raw


@app.get("/api/series/{sid}/episodes/{n}/stems/{name}")
def stem_audio(sid: str, n: int, name: str):
    """One rendered stem, so a reviewer can listen to a scene before the episode is mastered."""
    r = repos()
    if not paths.is_stem_name(name):
        raise HTTPException(404, "not a stem")
    key = paths.stem(sid, n, name)
    if not r.blobs.exists(key):
        raise HTTPException(404, "stem not rendered")
    return FileResponse(r.blobs.local(key), media_type="audio/wav")


@app.get("/api/runs/{run_id}/steps/{step_id}/log", response_class=PlainTextResponse)
def step_log(run_id: str, step_id: str) -> str:
    d = _get_run(run_id)
    text = repos().runs.read_log(d["series_id"], step_id)
    if text is None:  # pre-Emvoox runs logged next to the series under logs/<job>.log too
        return "(no log yet)"
    return text[-30000:]


@app.get("/api/runs/{run_id}/events")
def run_events(run_id: str, after: int = 0) -> dict:
    d = _get_run(run_id)
    events = [e for e in repos().runs.events(d["series_id"], after) if e.get("run_id") == run_id]
    return {"events": events[-500:]}


# ---------------------------------------------------------------------------------------- chat


class ChatMessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    user: str = ""
    mode: str = Field("auto", pattern="^(auto|manual)$")  # manual: the agent's write tools wait for approval too


class ChatAnswerIn(BaseModel):
    id: str = Field(min_length=1)
    answer: str | None = None  # a question the agent asked
    approved: bool | None = None  # a tool call that needs approval
    notes: str = ""
    reviewer: str = ""


class ChatAnswersIn(BaseModel):
    answers: list[ChatAnswerIn] = Field(min_length=1)


def _chat(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except chat.ChatError as e:
        raise HTTPException(e.status, str(e)) from e


@app.post("/api/chat/threads")
def chat_start(body: ChatMessageIn) -> dict:
    """Start a conversation with the Producer agent. The reply arrives on the thread; poll it or read its events."""
    thread = _chat(chat.create_thread, repos(), body.text, _submit, user=body.user, mode=body.mode)
    return chat.thread_view(repos(), thread.id)


@app.get("/api/chat/threads")
def chat_threads() -> dict:
    return {"threads": [t.model_dump(mode="json") for t in repos().chat.list()]}


@app.get("/api/chat/threads/{thread_id}")
def chat_thread(thread_id: str) -> dict:
    return _chat(chat.thread_view, repos(), thread_id)


@app.delete("/api/chat/threads/{thread_id}")
def chat_delete(thread_id: str) -> dict:
    r = repos()
    thread = r.chat.load(thread_id)
    if thread is None:
        raise HTTPException(404, "no such conversation")
    if thread.status == "running":
        raise HTTPException(409, "the Producer is still working in this conversation")
    r.chat.delete(thread_id)
    r.sessions.delete(thread_id)
    return {"ok": True}


@app.post("/api/chat/threads/{thread_id}/messages")
def chat_message(thread_id: str, body: ChatMessageIn) -> dict:
    with _lock:
        _chat(chat.post_message, repos(), thread_id, body.text, _submit)
    return chat.thread_view(repos(), thread_id)


@app.post("/api/chat/threads/{thread_id}/answers")
def chat_answers(thread_id: str, body: ChatAnswersIn) -> dict:
    """Answer what the agent is waiting for: a question (``answer``), or a tool call that needs approval (``approved``)."""
    answers = {a.id: a.model_dump(exclude={"id"}, exclude_none=True) for a in body.answers}
    with _lock:
        _chat(chat.answer, repos(), thread_id, answers, _submit)
    return chat.thread_view(repos(), thread_id)


@app.get("/api/chat/threads/{thread_id}/events")
def chat_events(thread_id: str, after: int = 0) -> dict:
    r = repos()
    thread = r.chat.load(thread_id)
    if thread is None:
        raise HTTPException(404, "no such conversation")
    return {"status": thread.status, "events": r.chat.events(thread_id, after)[-500:]}


@app.get("/api/chat/threads/{thread_id}/stream")
def chat_stream(thread_id: str, after: int = 0):
    """The thread's events as they happen (text/event-stream). Ends when the agent's turn does."""
    r = repos()
    if r.chat.load(thread_id) is None:
        raise HTTPException(404, "no such conversation")

    def events():
        import json as _json

        last, idle = after, 0
        while idle < 1200:  # ten minutes without anything new: the client reconnects
            fresh = r.chat.events(thread_id, last)
            for e in fresh:
                last = e["seq"]
                yield f"id: {e['seq']}\nevent: {e['type']}\ndata: {_json.dumps(e, ensure_ascii=False)}\n\n"
            thread = r.chat.load(thread_id)
            if thread is None or (thread.status != "running" and not fresh):
                yield f"event: turn.end\ndata: {_json.dumps({'status': thread.status if thread else 'deleted'})}\n\n"
                return
            idle = 0 if fresh else idle + 1
            time.sleep(0.5)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------------------- productions


@app.get("/api/library")
def get_library() -> dict:
    return {"series": library.list_series(repos(), {x["series_id"]: x["run_id"] for x in _live_runs()})}


@app.get("/api/series/{sid}")
def get_series(sid: str) -> dict:
    live = next((x for x in _live_runs() if x["series_id"] == sid), None)
    d = library.series_detail(repos(), sid, active_run=live["run_id"] if live else None)
    if not d:
        raise HTTPException(404, "unknown series")
    if live:
        d["run_state"] = live
    return d


@app.get("/api/series/{sid}/episodes/{n}")
def get_episode(sid: str, n: int) -> dict:
    d = library.episode_detail(repos(), sid, n)
    if not d:
        raise HTTPException(404, "nothing produced for this episode yet")
    return d


class ResumeIn(BaseModel):
    episodes: list[int] | None = None
    next: int | None = Field(None, ge=1, le=99)
    tts_provider: str | None = None
    tts_model: str | None = None
    tts_batching: str = "auto"
    force: bool = False
    auto_approve: bool | None = None
    max_retries: int | None = Field(None, ge=0, le=5)
    llm_provider: str | None = None
    scene_approval: bool = False
    max_cost_usd: float | None = Field(None, gt=0)


@app.post("/api/series/{sid}/resume")
def resume_series(sid: str, body: ResumeIn) -> dict:
    with _lock:
        r = repos()
        if _waiting(sid):
            raise HTTPException(409, "this series has a run waiting for a decision; answer it on the Approvals page first")
        if _busy(sid):
            raise HTTPException(409, f"a run is already in progress for this series: {_busy(sid)['run_id']}")
        s = library.series_summary(r, sid)
        bible = r.series.load_bible(sid)
        if not s or bible is None:
            raise HTTPException(404, "series has no outline yet; start it from New production")
        last = s.get("run") or {}
        provider = body.tts_provider or last.get("tts_provider") or get_settings().tts_provider
        model = _check_engine(provider, body.tts_model or (last.get("tts_model") if provider == last.get("tts_provider") else None))
        _check_llm(body.llm_provider)
        if body.episodes:
            only = sorted({n for n in body.episodes if 1 <= n <= s["planned"]})
        else:
            pool = s["remaining"] if not body.force else list(range(1, s["planned"] + 1))
            only = pool[: (body.next or 5)]
        if not only:
            raise HTTPException(409, "nothing left to produce: every planned episode already has a master (tick overwrite to re-render)")
        st = get_settings()
        try:
            params = RunParams(series_id=sid, episodes=len(bible.episodes), min_sec=bible.episode_format.min_duration_sec,
                               max_sec=bible.episode_format.max_duration_sec, force=body.force, source="existing", tts_provider=provider, tts_model=model,
                               tts_batching=body.tts_batching, only=only, llm_provider=body.llm_provider,  # type: ignore[arg-type]
                               auto_approve=st.auto_approve if body.auto_approve is None else body.auto_approve,
                               max_retries=st.qa_max_retries if body.max_retries is None else body.max_retries, halt_on_qa_fail=st.halt_on_qa_fail,
                               scene_approval=body.scene_approval, max_cost_usd=body.max_cost_usd)
        except ValidationError as e:
            raise HTTPException(422, str(e)) from e
        return _start(params)


@app.delete("/api/series/{sid}")
def delete_series(sid: str) -> dict:
    if any(x["series_id"] == sid for x in _live_runs()):
        raise HTTPException(409, "a run is in progress for this series")
    if _waiting(sid):
        raise HTTPException(409, "this series has a run waiting for a decision; answer or cancel it first")
    r = repos()
    if sid not in r.series.list_ids():
        raise HTTPException(404, "unknown series")
    library.delete_series(r, sid)
    return {"ok": True}


@app.get("/api/series/{sid}/master/{n}.mp3")
def master(sid: str, n: int):
    r = repos()
    key = paths.master(sid, n, "mp3")
    if not r.blobs.exists(key):
        raise HTTPException(404, "master not rendered")
    return FileResponse(r.blobs.local(key), media_type="audio/mpeg", filename=f"{sid}_ep{n:02d}.mp3")


# ---------------------------------------------------------------------------------------- human approval gate


@app.get("/api/approvals")
def approvals() -> dict:
    return {"items": library.approvals(repos())}


class ApproveIn(BaseModel):
    reviewer: str = Field(min_length=1)
    notes: str = ""
    metadata: PublishMetadata | None = None


class RejectIn(BaseModel):
    reviewer: str = Field(min_length=1)
    notes: str = ""
    lines: list[str] = Field(default_factory=list)


@app.post("/api/series/{sid}/episodes/{n}/approve")
def approve(sid: str, n: int, body: ApproveIn) -> dict:
    try:
        return gate.approve(repos(), sid, n, reviewer=body.reviewer, notes=body.notes, metadata=body.metadata).model_dump(mode="json")
    except AgentError as e:
        raise HTTPException(409, str(e)) from e


@app.post("/api/series/{sid}/episodes/{n}/reject")
def reject(sid: str, n: int, body: RejectIn) -> dict:
    try:
        return gate.reject(repos(), sid, n, reviewer=body.reviewer, notes=body.notes, lines=body.lines).model_dump(mode="json")
    except AgentError as e:
        raise HTTPException(409, str(e)) from e


@app.put("/api/series/{sid}/episodes/{n}/metadata")
def save_metadata(sid: str, n: int, body: PublishMetadata) -> dict:
    try:
        return gate.update_metadata(repos(), sid, n, body).model_dump(mode="json")
    except AgentError as e:
        raise HTTPException(409, str(e)) from e


@app.get("/api/outputs")
def outputs() -> dict:
    items = repos().outputs.list()
    for i in items:
        i["url"] = f"/api/outputs/{i['series_id']}/{i['file']}"
    return {"items": items}


@app.get("/api/outputs/{sid}/{name}")
def output_file(sid: str, name: str):
    p = repos().outputs.file(sid, name)
    if p is None:
        raise HTTPException(404)
    return FileResponse(p, filename=f"{sid}_{Path(name).name}")


# ---------------------------------------------------------------------------------------- voice IPs


class VoiceIn(BaseModel):
    voice_id: str = Field(min_length=1)
    model_id: str | None = None
    voice_url: str | None = None
    fallback_voice_id: str | None = None
    source: VoiceSource | None = None
    label: str | None = None


class CharacterIn(BaseModel):
    character_id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,23}$")
    display_name: str = Field(min_length=1)
    persona: str = ""
    voice_description: str = ""
    gender: str | None = None
    age: str | None = None
    tags: list[str] = Field(default_factory=list)
    is_ip_asset: bool = True
    providers: dict[str, VoiceIn] = Field(default_factory=dict)


def _voice(provider: str, v: VoiceIn, existing: ProviderVoice | None = None) -> ProviderVoice:
    if provider not in PROVIDER_NAMES:
        raise HTTPException(422, f"unknown provider {provider!r}")
    vid = v.voice_id.strip()
    model = (v.model_id or "").strip() or DEFAULT_MODEL[provider]
    if provider != "wavespeed" and model not in model_ids(provider):
        raise HTTPException(422, f"unknown {provider} model {model!r}")
    if provider == "wavespeed" and "/" not in model:
        raise HTTPException(422, "a WaveSpeed model is a path such as elevenlabs/eleven-v3 or minimax/speech-2.6-hd")
    if provider == "gemini":
        info = gemini_voice(vid)
        if not info:
            raise HTTPException(422, f"{vid!r} is not a Gemini prebuilt voice")
        vid = info["id"]
    default_source = "prebuilt" if provider == "gemini" else "premade"
    same = existing is not None and existing.voice_id == vid and existing.model_id == model
    return ProviderVoice(voice_id=vid, model_id=model, voice_url=v.voice_url or (existing.voice_url if same else None),
                         fallback_voice_id=(v.fallback_voice_id or (existing.fallback_voice_id if same else None))
                         if provider in ("elevenlabs", "wavespeed") else None,
                         default_settings=existing.default_settings if same else {},
                         source=v.source or (existing.source if same else default_source), label=v.label or (existing.label if same else None),
                         added_at=existing.added_at if same else now_iso())


def _profile(body: CharacterIn, existing: CharacterProfile | None = None) -> CharacterProfile:
    provs = {k: _voice(k, v, existing.providers.get(k) if existing else None) for k, v in body.providers.items() if v.voice_id.strip()}
    return CharacterProfile(
        character_id=body.character_id, display_name=body.display_name, persona=body.persona, voice_description=body.voice_description,
        gender=body.gender or None, age=body.age or None, tags=[t.strip() for t in body.tags if t.strip()], is_ip_asset=body.is_ip_asset,  # type: ignore[arg-type]
        providers=provs, preferred_provider=existing.preferred_provider if existing and existing.preferred_provider in provs else None)


def _appearances() -> dict[str, list[dict]]:
    r = repos()
    out: dict[str, list[dict]] = {}
    for sid in r.series.list_ids():
        b = r.docs.get(paths.bible(sid)) or {}
        for role in b.get("roles", []):
            if role.get("actor_id"):
                out.setdefault(role["actor_id"], []).append({"series_id": sid, "title": b.get("title") or sid, "role": role.get("role_name")})
    return out


@app.get("/api/characters")
def list_characters() -> dict:
    r = repos()
    reg = r.registry.load()
    seen = _appearances()
    chars = []
    for c in reg.characters:
        d = c.model_dump(mode="json")
        d["previews"] = {p: previews.actor_preview(r, c, p, render=False) for p in c.providers}
        d["series"] = seen.get(c.character_id, [])
        chars.append(d)
    return {"locked": reg.locked, "default_provider": reg.default_provider, "characters": chars, "changelog": reg.changelog[-30:]}


@app.post("/api/characters")
def add_character(body: CharacterIn) -> dict:
    r = repos()
    if body.character_id in r.registry.load().ids():
        raise HTTPException(409, f"{body.character_id} already exists; edit it instead")
    _, entry = r.registry.upsert(_profile(body))
    return {"ok": True, "changelog": entry}


@app.put("/api/characters/{cid}")
def edit_character(cid: str, body: CharacterIn, unlock: bool = False) -> dict:
    if body.character_id != cid:
        raise HTTPException(422, "character_id cannot be changed")
    r = repos()
    reg = r.registry.load()
    if cid not in reg.ids():
        raise HTTPException(404, "unknown character")
    existing = reg.get(cid)
    profile = _profile(body, existing)
    removed = [p for p in existing.providers if p not in profile.providers]
    if removed and reg.locked and existing.is_ip_asset and not unlock:
        raise HTTPException(423, f"{cid} is a locked IP asset; unlock to remove its {', '.join(removed)} voice")
    try:
        reg, entry = r.registry.upsert(profile, unlock=unlock)
        for p in removed:
            r.registry.remove_provider_voice(cid, p, unlock=True)
    except RegistryLocked as e:
        raise HTTPException(423, str(e)) from e
    return {"ok": True, "changelog": entry + (f"; removed {', '.join(removed)}" if removed else "")}


@app.delete("/api/characters/{cid}")
def delete_character(cid: str, unlock: bool = False) -> dict:
    r = repos()
    try:
        r.registry.remove(cid, unlock=unlock)
    except KeyError as e:
        raise HTTPException(404, "unknown character") from e
    except RegistryLocked as e:
        raise HTTPException(423, str(e)) from e
    r.assets.delete_previews(f"{cid}_")
    return {"ok": True}


class PlugVoiceIn(BaseModel):
    provider: str
    voice_id: str = Field(min_length=1)
    model_id: str | None = None
    source: VoiceSource = "cloned"
    label: str | None = None
    voice_url: str | None = None
    fallback_voice_id: str | None = None
    make_preferred: bool = True
    unlock: bool = False


@app.post("/api/characters/{cid}/voices")
def plug_voice(cid: str, body: PlugVoiceIn) -> dict:
    """Plug a voice (typically the cloning track's output) into an actor. The next run uses it: the
    Casting Agent's Engine Policy prefers cloned voices and the actor's preferred engine."""
    r = repos()
    reg = r.registry.load()
    if cid not in reg.ids():
        raise HTTPException(404, "unknown character")
    if body.provider == "mock" and not _mock_enabled():
        raise HTTPException(422, "unknown provider 'mock'")
    voice = _voice(body.provider, VoiceIn(voice_id=body.voice_id, model_id=body.model_id, voice_url=body.voice_url,
                                          fallback_voice_id=body.fallback_voice_id, source=body.source, label=body.label))
    try:
        _, entry = r.registry.set_provider_voice(cid, body.provider, voice, unlock=body.unlock, make_preferred=body.make_preferred)
    except RegistryLocked as e:
        raise HTTPException(423, str(e) + ". Tick 'unlock' to replace the locked voice (the change is recorded in the changelog).") from e
    r.assets.delete_previews(f"{cid}_{body.provider}")
    return {"ok": True, "changelog": entry}


@app.delete("/api/characters/{cid}/voices/{provider}")
def remove_voice(cid: str, provider: str, unlock: bool = False) -> dict:
    r = repos()
    try:
        r.registry.remove_provider_voice(cid, provider, unlock=unlock)
    except KeyError as e:
        raise HTTPException(404, "unknown character") from e
    except RegistryLocked as e:
        raise HTTPException(423, str(e)) from e
    return {"ok": True}


def _provider_error(e: ProviderError) -> HTTPException:
    return HTTPException(402 if e.status == 402 else (429 if e.status == 429 else 502), str(e))


@app.post("/api/characters/{cid}/preview")
def character_preview(cid: str, provider: str = "gemini") -> dict:
    r = repos()
    reg = r.registry.load()
    if cid not in reg.ids():
        raise HTTPException(404, "unknown character")
    _check_engine(provider, None)
    c = reg.get(cid)
    if provider not in c.providers:
        raise HTTPException(422, f"{cid} has no {provider} voice")
    try:
        p = previews.actor_preview(r, c, provider)
    except ProviderError as e:
        raise _provider_error(e) from e
    return {"ok": True, "character_id": cid, "provider": provider, "preview": p}


class VoicePreviewIn(BaseModel):
    provider: str
    voice_id: str = Field(min_length=1)
    model_id: str | None = None


@app.post("/api/voices/preview")
def voice_preview(body: VoicePreviewIn) -> dict:
    model = _check_engine(body.provider, body.model_id)
    vid = body.voice_id.strip()
    if body.provider == "gemini":
        info = gemini_voice(vid)
        if not info:
            raise HTTPException(422, f"{vid!r} is not a Gemini prebuilt voice")
        vid = info["id"]
    try:
        p = previews.voice_preview(repos(), body.provider, vid, model)
    except ProviderError as e:
        raise _provider_error(e) from e
    return {"ok": True, "preview": p}


@app.get("/api/previews/{name}")
def preview_file(name: str):
    r = repos()
    key = paths.preview(Path(name).name)
    if not r.blobs.exists(key):
        raise HTTPException(404)
    return FileResponse(r.blobs.local(key), media_type="audio/wav")


class AuditionIn(BaseModel):
    text: str = Field("Xin chào, tôi là diễn viên của bạn. Hôm nay chúng ta kể một câu chuyện mới.", min_length=1, max_length=300)
    provider: str = "gemini"


@app.post("/api/characters/{cid}/audition")
def audition(cid: str, body: AuditionIn) -> dict:
    from emvoox.providers.tts import TtsRequest, get_provider
    from emvoox.text.vi_normalize import normalize_vi

    r = repos()
    reg = r.registry.load()
    if cid not in reg.ids():
        raise HTTPException(404, "unknown character")
    _check_engine(body.provider, None)
    pv = reg.get(cid).providers.get(body.provider)
    if not pv:
        raise HTTPException(422, f"{cid} has no {body.provider} voice")
    name = f"{cid}-{body.provider}-{int(time.time())}.wav"
    req = TtsRequest(provider=body.provider, model_id=pv.model_id, voice_id=pv.voice_id, text=normalize_vi(body.text),
                     settings=previews.preview_settings(body.provider, pv.model_id))
    try:
        t0 = time.time()
        info = get_provider(body.provider).synthesize(req, r.assets.audition_path(name))
    except ProviderError as e:
        raise _provider_error(e) from e
    Ledger(r.telemetry).tts(agent="studio", skill="audition", provider=body.provider, model=pv.model_id, characters=len(req.text),
                            audio_ms=int(info.get("duration_ms") or 0), elapsed_s=round(time.time() - t0, 2))
    return {"ok": True, "url": f"/api/auditions/{name}", "duration_ms": info.get("duration_ms"), "characters_billed": info.get("characters_billed")}


@app.get("/api/auditions/{name}")
def audition_file(name: str):
    r = repos()
    key = paths.audition(Path(name).name)
    if not r.blobs.exists(key):
        raise HTTPException(404)
    return FileResponse(r.blobs.local(key), media_type="audio/wav")


# ---------------------------------------------------------------------------------------- costs


@app.get("/api/costs")
def costs() -> dict:
    return usage.cost_summary(repos())


@app.get("/api/usage")
def usage_summary() -> dict:
    return usage.quota_summary(repos())


# ---------------------------------------------------------------------------------------- web app
# Next.js static export, mounted last so /api/* wins. Build: cd web && npm install && npm run export

if WEB_OUT.exists():
    app.mount("/", StaticFiles(directory=str(WEB_OUT), html=True), name="web")
else:
    @app.get("/", response_class=HTMLResponse)
    def index_placeholder() -> str:
        return ("<!doctype html><meta charset=utf-8><title>Emvoox Studio</title>"
                "<body style='font:15px/1.5 system-ui;padding:40px;max-width:640px'><h1>Web app not built yet</h1>"
                "<p>Run <code>cd web && npm install && npm run export</code> once, then reload. "
                "For development use <code>npm run dev</code> in <code>web/</code> (http://localhost:3000).</p></body>")
