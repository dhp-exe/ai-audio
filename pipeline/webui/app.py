"""FastAPI app for the pipeline web client. The UI is the Next.js app in web/ (served from web/out when built); JSON API below.

Config / engines
    GET  /api/config                          LLM + TTS defaults, key presence, engine catalog, actor roster (+ preview urls)
    GET  /api/usage                           per-model usage, limits and status (Usage page)

Pipeline
    POST /api/runs                            start a run with a sectioned story (see StartRun; tts_provider/tts_model per run)
    GET  /api/runs                            active + persisted runs
    GET  /api/runs/{run_id}                   run state
    POST /api/runs/{run_id}/cancel
    GET  /api/runs/{run_id}/jobs/{job_id}/log

Story library (series/<id>/)
    GET    /api/library                       every series with progress and last run
    GET    /api/series/{sid}                  detail: story, bible, per-episode status, run state
    POST   /api/series/{sid}/resume           continue: {next: N} or {episodes: [..]} (+ engine)
    DELETE /api/series/{sid}
    GET    /api/series/{sid}/master/{ep}.mp3
    GET    /api/series/{sid}/episode/{ep}

Character IPs (library/voice-ips.json)
    GET    /api/characters                    roster with cached preview urls per engine
    POST   /api/characters                    add
    PUT    /api/characters/{id}?unlock=1      edit (unlock needed to change an IP asset's voice)
    DELETE /api/characters/{id}?unlock=1
    POST   /api/characters/{id}/preview?provider=   render the ~5 s preview once, then always the cached file
    POST   /api/voices/preview                {provider, voice_id, model_id} generic voice preview (voice picker)
    POST   /api/characters/{id}/audition      {text, provider} custom line (spends credits on ElevenLabs)
    GET    /api/previews/{file}, /api/auditions/{file}
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from pipeline import naming, previews, stories, usage
from pipeline import registry as registry_io
from pipeline.casting import apply_role_tags, duplicate_actor_pins, parse_roles_text
from pipeline.config import get_settings
from pipeline.orchestrator import Orchestrator, RunParams
from pipeline.providers import DEFAULT_MODEL, PROVIDER_NAMES, catalog, model_ids
from pipeline.providers.base import ProviderError
from pipeline.providers.catalog import gemini_voice
from pipeline.registry import RegistryLocked
from pipeline.schema import CharacterProfile, ProviderVoice, StoryInput, StoryOverview, StoryRole


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    mark_interrupted_runs()
    yield


app = FastAPI(title="Audio AI Pipeline", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("AI_AUDIO_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if o.strip()],
    allow_methods=["*"], allow_headers=["*"],
)
WEB_OUT = naming.REPO_ROOT / "web" / "out"  # Next.js static export (cd web && npm run export)

_runs: dict[str, Orchestrator] = {}
_lock = threading.Lock()


def _active() -> list[Orchestrator]:
    return [o for o in _runs.values() if o.run.status in ("pending", "running")]


def mark_interrupted_runs() -> list[str]:
    """A run lives in a thread of this process; if the server died mid-run its state file still says
    'running'. On startup, mark those as cancelled so the Library and the run board tell the truth
    (finished stages stay done; the Library's Continue picks up from the cached artifacts)."""
    fixed: list[str] = []
    if not naming.SERIES_DIR.exists():
        return fixed
    for p in naming.SERIES_DIR.glob("*/pipeline_run.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if data.get("status") not in ("pending", "running"):
            continue
        data["status"] = "cancelled"
        data["error"] = "interrupted: the server stopped while this run was in progress; use Continue in the Library"
        data["finished_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        for j in data.get("jobs", []):
            if j.get("status") in ("pending", "running"):
                j["status"] = "skipped"
                j["finished_at"] = j.get("finished_at") or data["finished_at"]
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        fixed.append(data.get("run_id", p.parent.name))
    return fixed




def _check_engine(provider: str, model: str | None) -> str | None:
    if provider not in PROVIDER_NAMES:
        raise HTTPException(422, f"tts_provider must be one of {PROVIDER_NAMES}")
    if model and model not in model_ids(provider):
        raise HTTPException(422, f"unknown {provider} model {model!r}; expected one of {model_ids(provider)}")
    s = get_settings()
    if provider == "elevenlabs" and not s.elevenlabs_api_key:
        raise HTTPException(422, "ELEVENLABS_API_KEY is not set in .env")
    if provider == "gemini" and not s.gemini_api_key:
        raise HTTPException(422, "GEMINI_API_KEY is not set in .env")
    return model or None


def _actor_summary(c: CharacterProfile) -> dict:
    return {"character_id": c.character_id, "display_name": c.display_name, "gender": c.gender, "age": c.age,
            "is_ip_asset": c.is_ip_asset, "persona": c.persona, "tags": c.tags,
            "voices": {p: v.voice_id for p, v in c.providers.items()},
            "previews": {p: previews.actor_preview(c, p, render=False) for p in c.providers}}


# --------------------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------------------


@app.get("/api/usage")
def usage_summary() -> dict:
    return usage.summary()




@app.get("/api/config")
def config() -> dict:
    s = get_settings()
    reg = registry_io.load()
    return {
        "llm_model": s.llm_model,
        "tts": {"provider": s.tts_provider, "model": s.tts_model or DEFAULT_MODEL.get(s.tts_provider), "batching": s.tts_batching},
        "keys": {"gemini": bool(s.gemini_api_key), "elevenlabs": bool(s.elevenlabs_api_key)},
        "catalog": catalog(),
        "defaults": {"episodes": 30, "produce": 5, "min_sec": 50, "max_sec": 70},
        "actors": [_actor_summary(c) for c in reg.characters],
        "active_run": _active()[0].run.run_id if _active() else None,
    }


# --------------------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------------------


class RoleIn(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    actor_id: str | None = None


class StartRun(BaseModel):
    series_id: str | None = None
    # sectioned story
    title: str = Field(min_length=1)
    total_minutes: int | None = Field(None, ge=1, le=600)
    genre: str = ""
    setting: str = ""
    roles: list[RoleIn] = Field(default_factory=list)
    roles_text: str = Field("", description="Alternative to roles[]: one 'Name: description' per line, '/actor' tags allowed.")
    script: str = Field(min_length=50)
    # production parameters
    episodes: int = Field(30, ge=1, le=99)
    produce: int | None = Field(None, ge=1, le=99)
    min_sec: int = Field(50, ge=20, le=600)
    max_sec: int = Field(70, ge=20, le=900)
    force: bool = False
    # engine
    tts_provider: str = "elevenlabs"
    tts_model: str | None = None
    tts_batching: str = "auto"


def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", s.lower()).strip("-")
    return s[:24] or "series"


@app.post("/api/runs")
def start_run(body: StartRun) -> dict:
    with _lock:
        active = _active()
        if active:
            raise HTTPException(409, f"a run is already in progress: {active[0].run.run_id}")
        sid = _slug(body.series_id) if body.series_id else _slug(body.title) + "-" + datetime.now(UTC).strftime("%m%d%H%M")
        if naming.series_bible_path(sid).exists() and not body.force:
            raise HTTPException(409, f"series '{sid}' already exists; open it in the Library to continue, or tick 'overwrite'")
        if body.max_sec < body.min_sec:
            raise HTTPException(422, "max_sec must be >= min_sec")
        model = _check_engine(body.tts_provider, body.tts_model)
        reg = registry_io.load()
        roles = [StoryRole(name=r.name, description=r.description, actor_id=r.actor_id or None) for r in body.roles]
        if body.roles_text.strip():
            roles += parse_roles_text(body.roles_text)
        try:
            roles = apply_role_tags(roles, reg)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        bad = [r.actor_id for r in roles if r.actor_id and r.actor_id not in reg.ids()]
        if bad:
            raise HTTPException(422, f"unknown actor id(s): {bad}")
        dup = duplicate_actor_pins(roles)
        if dup:
            raise HTTPException(422, "one Character IP can play only one role; pinned twice: "
                                + "; ".join(f"{a} -> {', '.join(n)}" for a, n in dup.items()))
        story = StoryInput(overview=StoryOverview(title=body.title, total_minutes=body.total_minutes, genre=body.genre, setting=body.setting),
                           roles=roles, script=body.script)
        try:
            params = RunParams(series_id=sid, episodes=body.episodes, produce=body.produce, min_sec=body.min_sec, max_sec=body.max_sec,
                               force=body.force, tts_provider=body.tts_provider, tts_model=model, tts_batching=body.tts_batching)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        orch = Orchestrator(params, story)
        run = orch.start()
        _runs[run.run_id] = orch
        return run.to_dict()


@app.get("/api/runs")
def list_runs() -> dict:
    live = {o.run.run_id: o.run.to_dict() for o in _runs.values()}
    persisted = []
    if naming.SERIES_DIR.exists():
        for d in sorted(naming.SERIES_DIR.iterdir()):
            p = d / "pipeline_run.json"
            if p.exists():
                try:
                    persisted.append(json.loads(p.read_text(encoding="utf-8")))
                except json.JSONDecodeError:
                    pass
    return {"active": list(live.values()), "persisted": [r for r in persisted if r["run_id"] not in live]}


def _get(run_id: str) -> dict:
    if run_id in _runs:
        return _runs[run_id].run.to_dict()
    sid = run_id.rsplit("-", 2)[0]
    d = naming.SERIES_DIR / sid / "pipeline_run.json"
    if d.exists():
        data = json.loads(d.read_text(encoding="utf-8"))
        if data.get("run_id") == run_id:
            return data
    raise HTTPException(404, "run not found")


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    return _get(run_id)


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict:
    o = _runs.get(run_id)
    if not o:
        raise HTTPException(404, "run not active")
    o.cancel()
    return {"ok": True}


@app.get("/api/runs/{run_id}/jobs/{job_id}/log", response_class=PlainTextResponse)
def job_log(run_id: str, job_id: str) -> str:
    run = _get(run_id)
    job = next((j for j in run["jobs"] if j["id"] == job_id), None)
    if not job:
        raise HTTPException(404, "job not found")
    if not job.get("log_path") or not Path(job["log_path"]).exists():
        return "(no log yet)"
    return Path(job["log_path"]).read_text(encoding="utf-8")[-20000:]


# --------------------------------------------------------------------------------------
# Story library
# --------------------------------------------------------------------------------------


@app.get("/api/library")
def library() -> dict:
    active = {o.run.params.series_id: o.run.run_id for o in _active()}
    items = stories.list_series()
    for s in items:
        s["active_run"] = active.get(s["series_id"])
    return {"series": items}


@app.get("/api/series/{sid}")
def series_detail(sid: str) -> dict:
    d = stories.series_detail(sid)
    if not d:
        raise HTTPException(404, "unknown series")
    o = next((o for o in _active() if o.run.params.series_id == sid), None)
    d["active_run"] = o.run.run_id if o else None
    if o:
        d["run_state"] = o.run.to_dict()
    return d


class ResumeIn(BaseModel):
    episodes: list[int] | None = Field(None, description="explicit episode numbers to produce")
    next: int | None = Field(None, ge=1, le=99, description="produce the next N episodes without a master")
    tts_provider: str | None = None
    tts_model: str | None = None
    tts_batching: str = "auto"
    force: bool = False


@app.post("/api/series/{sid}/resume")
def resume_series(sid: str, body: ResumeIn) -> dict:
    with _lock:
        if _active():
            raise HTTPException(409, f"a run is already in progress: {_active()[0].run.run_id}")
        s = stories.series_summary(sid)
        if not s or not naming.series_bible_path(sid).exists():
            raise HTTPException(404, "series has no outline yet; start it from the New story form")
        last = s.get("run") or {}
        provider = body.tts_provider or last.get("tts_provider") or get_settings().tts_provider
        model = _check_engine(provider, body.tts_model or (last.get("tts_model") if not body.tts_provider or body.tts_provider == last.get("tts_provider") else None))
        if body.episodes:
            only = sorted({n for n in body.episodes if 1 <= n <= s["planned"]})
        else:
            pool = s["remaining"] if not body.force else list(range(1, s["planned"] + 1))
            only = pool[: (body.next or 5)]
        if not only:
            raise HTTPException(409, "nothing left to produce: every planned episode already has a master (tick overwrite to re-render)")
        try:
            params = RunParams(series_id=sid, episodes=s["planned"], min_sec=last.get("min_sec") or 50, max_sec=last.get("max_sec") or 70,
                               force=body.force, tts_provider=provider, tts_model=model, tts_batching=body.tts_batching, only=only)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        orch = Orchestrator(params, None)
        run = orch.start()
        _runs[run.run_id] = orch
        return run.to_dict()


@app.delete("/api/series/{sid}")
def delete_series(sid: str) -> dict:
    if any(o.run.params.series_id == sid for o in _active()):
        raise HTTPException(409, "a run is in progress for this series")
    if not naming.series_root(sid).exists():
        raise HTTPException(404, "unknown series")
    stories.delete_series(sid)
    for rid in [r for r, o in _runs.items() if o.run.params.series_id == sid]:
        _runs.pop(rid, None)
    return {"ok": True}


@app.get("/api/series/{sid}/master/{ep}.mp3")
def master(sid: str, ep: int):
    p = naming.master_path(sid, ep, "mp3")
    if not p.exists():
        raise HTTPException(404, "master not rendered")
    return FileResponse(p, media_type="audio/mpeg", filename=p.name)


@app.get("/api/series/{sid}/episode/{ep}")
def episode(sid: str, ep: int) -> dict:
    out: dict = {}
    p = naming.parsed_script_path(sid, ep)
    if p.exists():
        out["script"] = json.loads(p.read_text(encoding="utf-8"))
    q = naming.qa_report_path(sid, ep)
    if q.exists():
        out["qa"] = json.loads(q.read_text(encoding="utf-8"))
    b = naming.series_bible_path(sid)
    if b.exists():
        bible = json.loads(b.read_text(encoding="utf-8"))
        out["plan"] = next((e for e in bible.get("episodes", []) if e["number"] == ep), None)
        out["roles"] = bible.get("roles", [])
    if not out:
        raise HTTPException(404, "nothing produced for this episode yet")
    return out


# --------------------------------------------------------------------------------------
# Character IPs
# --------------------------------------------------------------------------------------


class VoiceIn(BaseModel):
    voice_id: str = Field(min_length=1)
    model_id: str | None = None
    voice_url: str | None = None
    fallback_voice_id: str | None = None


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


def _profile(body: CharacterIn) -> CharacterProfile:
    provs: dict[str, ProviderVoice] = {}
    for k, v in body.providers.items():
        if k not in PROVIDER_NAMES:
            raise HTTPException(422, f"unknown provider {k!r}")
        vid = v.voice_id.strip()
        if not vid:
            continue
        model = (v.model_id or "").strip() or DEFAULT_MODEL[k]
        if model not in model_ids(k):
            raise HTTPException(422, f"unknown {k} model {model!r}")
        if k == "gemini":
            info = gemini_voice(vid)
            if not info:
                raise HTTPException(422, f"{vid!r} is not a Gemini prebuilt voice")
            vid = info["id"]
        provs[k] = ProviderVoice(voice_id=vid, model_id=model, voice_url=(v.voice_url or None) if k == "elevenlabs" else None,
                                 fallback_voice_id=(v.fallback_voice_id or None) if k == "elevenlabs" else None)
    return CharacterProfile(
        character_id=body.character_id, display_name=body.display_name, persona=body.persona, voice_description=body.voice_description,
        gender=body.gender or None, age=body.age or None, tags=[t.strip() for t in body.tags if t.strip()], is_ip_asset=body.is_ip_asset,
        providers=provs,
    )


def _with_previews(c: CharacterProfile) -> dict:
    d = c.model_dump()
    d["previews"] = {p: previews.actor_preview(c, p, render=False) for p in c.providers}
    return d


@app.get("/api/characters")
def list_characters() -> dict:
    reg = registry_io.load()
    return {"locked": reg.locked, "default_provider": reg.default_provider, "characters": [_with_previews(c) for c in reg.characters],
            "changelog": reg.changelog[-20:]}


@app.post("/api/characters")
def add_character(body: CharacterIn) -> dict:
    reg = registry_io.load()
    if body.character_id in reg.ids():
        raise HTTPException(409, f"{body.character_id} already exists; use PUT to edit")
    reg, entry = registry_io.upsert(_profile(body))
    return {"ok": True, "changelog": entry}


@app.put("/api/characters/{cid}")
def edit_character(cid: str, body: CharacterIn, unlock: bool = False) -> dict:
    if body.character_id != cid:
        raise HTTPException(422, "character_id cannot be changed")
    reg = registry_io.load()
    if cid not in reg.ids():
        raise HTTPException(404, "unknown character")
    profile = _profile(body)
    existing = reg.get(cid)
    # providers omitted from the form are removed (the registry merges by default), same lock rule as a change
    removed = [p for p in existing.providers if p not in profile.providers]
    if removed and reg.locked and existing.is_ip_asset and not unlock:
        raise HTTPException(423, f"{cid} is a locked IP asset; unlock to remove its {', '.join(removed)} voice")
    try:
        reg, entry = registry_io.upsert(profile, unlock=unlock)
    except RegistryLocked as e:
        raise HTTPException(423, str(e)) from e
    if removed:
        c = reg.get(cid)
        for p in removed:
            c.providers.pop(p, None)
        registry_io.save(reg, f"{cid}: removed {', '.join(removed)} voice")
        entry += f"; removed {', '.join(removed)}"
    return {"ok": True, "changelog": entry}


@app.delete("/api/characters/{cid}")
def delete_character(cid: str, unlock: bool = False) -> dict:
    try:
        registry_io.remove(cid, unlock=unlock)
    except KeyError as e:
        raise HTTPException(404, "unknown character") from e
    except RegistryLocked as e:
        raise HTTPException(423, str(e)) from e
    for p in naming.previews_dir().glob(f"{cid}_*"):
        p.unlink(missing_ok=True)
    return {"ok": True}


def _provider_error(e: ProviderError) -> HTTPException:
    return HTTPException(402 if e.status == 402 else (429 if e.status == 429 else 502), str(e))


@app.post("/api/characters/{cid}/preview")
def character_preview(cid: str, provider: str = "elevenlabs") -> dict:
    """Render the ~5 s preview once per (engine, model, voice) and cache it; later calls return the cached file."""
    reg = registry_io.load()
    if cid not in reg.ids():
        raise HTTPException(404, "unknown character")
    _check_engine(provider, None)
    c = reg.get(cid)
    if provider not in c.providers:
        raise HTTPException(422, f"{cid} has no {provider} voice")
    try:
        p = previews.actor_preview(c, provider)
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
        p = previews.voice_preview(body.provider, vid, model)
    except ProviderError as e:
        raise _provider_error(e) from e
    return {"ok": True, "preview": p}


@app.get("/api/previews/{name}")
def preview_file(name: str):
    p = naming.previews_dir() / Path(name).name
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="audio/wav")


class AuditionIn(BaseModel):
    text: str = Field("Xin chào, tôi là diễn viên của bạn. Hôm nay chúng ta kể một câu chuyện mới.", min_length=1, max_length=300)
    provider: str = "elevenlabs"


@app.post("/api/characters/{cid}/audition")
def audition(cid: str, body: AuditionIn) -> dict:
    from pipeline.providers import TtsRequest, get_provider
    from pipeline.text.vi_normalize import normalize_vi

    reg = registry_io.load()
    if cid not in reg.ids():
        raise HTTPException(404, "unknown character")
    _check_engine(body.provider, None)
    pv = reg.get(cid).providers.get(body.provider)
    if not pv:
        raise HTTPException(422, f"{cid} has no {body.provider} voice")
    out_dir = naming.auditions_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{cid}-{body.provider}-{int(time.time())}.wav"
    settings = dict(previews.EL_SETTINGS) if body.provider == "elevenlabs" else {"style": previews.GEMINI_STYLE}
    req = TtsRequest(provider=body.provider, model_id=pv.model_id, voice_id=pv.voice_id, text=normalize_vi(body.text), settings=settings)
    try:
        info = get_provider(body.provider).synthesize(req, out)
    except ProviderError as e:
        raise _provider_error(e) from e
    return {"ok": True, "url": f"/api/auditions/{out.name}", "duration_ms": info.get("duration_ms"), "characters_billed": info.get("characters_billed")}


@app.get("/api/auditions/{name}")
def audition_file(name: str):
    p = naming.auditions_dir() / Path(name).name
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="audio/wav")


# --------------------------------------------------------------------------------------
# Web app (Next.js static export). Mounted last so /api/* wins. Build: cd web && npm run export
# --------------------------------------------------------------------------------------

if WEB_OUT.exists():
    app.mount("/", StaticFiles(directory=str(WEB_OUT), html=True), name="web")
else:
    @app.get("/", response_class=HTMLResponse)
    def index_placeholder() -> str:
        return ("<!doctype html><meta charset=utf-8><title>Audio AI Studio</title>"
                "<body style='font:15px/1.5 system-ui;padding:40px;max-width:640px'><h1>Web app not built yet</h1>"
                "<p>Run <code>cd web && npm install && npm run export</code> once, then reload. "
                "For development use <code>npm run dev</code> in <code>web/</code> (http://localhost:3000). "
                "</p></body>")
