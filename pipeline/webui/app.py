"""FastAPI app for the pipeline web client. Single-page UI in static/index.html; JSON API below.

Pipeline
    GET  /api/config                          defaults, keys present, actor summary
    POST /api/runs                            start a run with a sectioned story (see StartRun)
    GET  /api/runs                            active + persisted runs
    GET  /api/runs/{run_id}                   run state
    POST /api/runs/{run_id}/cancel
    GET  /api/runs/{run_id}/jobs/{job_id}/log
    GET  /api/series/{sid}/master/{ep}.mp3
    GET  /api/series/{sid}/episode/{ep}

Character IPs (library/voice-ips.json)
    GET    /api/characters
    POST   /api/characters                    add
    PUT    /api/characters/{id}?unlock=1      edit (unlock needed to change an IP asset's voice)
    DELETE /api/characters/{id}?unlock=1
    POST   /api/characters/{id}/audition      {text} -> renders one line, returns an audio URL (spends credits)
    GET    /api/auditions/{file}
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from pipeline import naming
from pipeline import registry as registry_io
from pipeline.casting import apply_role_tags, parse_roles_text
from pipeline.config import get_settings
from pipeline.orchestrator import Orchestrator, RunParams
from pipeline.registry import RegistryLocked
from pipeline.schema import CharacterProfile, ProviderVoice, StoryInput, StoryOverview, StoryRole

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Audio AI Pipeline")

_runs: dict[str, Orchestrator] = {}
_lock = threading.Lock()


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
    parallel: int = Field(2, ge=1, le=4)
    force: bool = False


def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", s.lower()).strip("-")
    return s[:24] or "series"


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/api/config")
def config() -> dict:
    s = get_settings()
    reg = registry_io.load()
    return {
        "llm_model": s.llm_model, "tts_provider": s.tts_provider, "tts_model": s.tts_model,
        "keys": {"gemini": bool(s.gemini_api_key), "elevenlabs": bool(s.elevenlabs_api_key), "minimax": bool(s.minimax_api_key)},
        "defaults": {"episodes": 30, "produce": 5, "min_sec": 50, "max_sec": 70},
        "actors": [{"character_id": c.character_id, "display_name": c.display_name, "gender": c.gender, "age": c.age,
                    "is_ip_asset": c.is_ip_asset, "persona": c.persona} for c in reg.characters],
    }


@app.post("/api/runs")
def start_run(body: StartRun) -> dict:
    with _lock:
        active = [o for o in _runs.values() if o.run.status in ("pending", "running")]
        if active:
            raise HTTPException(409, f"a run is already in progress: {active[0].run.run_id}")
        sid = _slug(body.series_id) if body.series_id else _slug(body.title) + "-" + datetime.now(UTC).strftime("%m%d%H%M")
        if naming.series_bible_path(sid).exists() and not body.force:
            raise HTTPException(409, f"series '{sid}' already exists; choose another id or tick 'overwrite'")
        if body.max_sec < body.min_sec:
            raise HTTPException(422, "max_sec must be >= min_sec")
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
        story = StoryInput(overview=StoryOverview(title=body.title, total_minutes=body.total_minutes, genre=body.genre, setting=body.setting),
                           roles=roles, script=body.script)
        params = RunParams(series_id=sid, episodes=body.episodes, produce=body.produce, min_sec=body.min_sec, max_sec=body.max_sec,
                           max_parallel_episodes=body.parallel, force=body.force)
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
    model_id: str = "eleven_v3"
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
    return CharacterProfile(
        character_id=body.character_id, display_name=body.display_name, persona=body.persona, voice_description=body.voice_description,
        gender=body.gender or None, age=body.age or None, tags=[t.strip() for t in body.tags if t.strip()], is_ip_asset=body.is_ip_asset,
        providers={k: ProviderVoice(voice_id=v.voice_id.strip(), model_id=v.model_id.strip() or "eleven_v3", voice_url=v.voice_url or None,
                                    fallback_voice_id=v.fallback_voice_id or None) for k, v in body.providers.items() if v.voice_id.strip()},
    )


@app.get("/api/characters")
def list_characters() -> dict:
    reg = registry_io.load()
    return {"locked": reg.locked, "default_provider": reg.default_provider, "characters": [c.model_dump() for c in reg.characters],
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
    try:
        reg, entry = registry_io.upsert(_profile(body), unlock=unlock)
    except RegistryLocked as e:
        raise HTTPException(423, str(e)) from e
    return {"ok": True, "changelog": entry}


@app.delete("/api/characters/{cid}")
def delete_character(cid: str, unlock: bool = False) -> dict:
    try:
        registry_io.remove(cid, unlock=unlock)
    except KeyError as e:
        raise HTTPException(404, "unknown character") from e
    except RegistryLocked as e:
        raise HTTPException(423, str(e)) from e
    return {"ok": True}


class AuditionIn(BaseModel):
    text: str = Field("Xin chào, tôi là diễn viên của bạn. Hôm nay chúng ta kể một câu chuyện mới.", min_length=1, max_length=300)
    provider: str = "elevenlabs"


@app.post("/api/characters/{cid}/audition")
def audition(cid: str, body: AuditionIn) -> dict:
    from pipeline.providers import TtsRequest, get_provider
    from pipeline.providers.base import ProviderError
    from pipeline.text.vi_normalize import normalize_vi

    reg = registry_io.load()
    if cid not in reg.ids():
        raise HTTPException(404, "unknown character")
    pv = reg.get(cid).providers.get(body.provider)
    if not pv:
        raise HTTPException(422, f"{cid} has no {body.provider} voice")
    out_dir = naming.auditions_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{cid}-{int(time.time())}.wav"
    req = TtsRequest(provider=body.provider, model_id=pv.model_id, voice_id=pv.voice_id, text=normalize_vi(body.text),
                     settings={"stability": 0.5, "similarity_boost": 0.75, "use_speaker_boost": True} if body.provider == "elevenlabs" else {})
    try:
        info = get_provider(body.provider).synthesize(req, out)
    except ProviderError as e:
        raise HTTPException(402 if e.status == 402 else 502, str(e)) from e
    return {"ok": True, "url": f"/api/auditions/{out.name}", "duration_ms": info.get("duration_ms"), "characters_billed": info.get("characters_billed")}


@app.get("/api/auditions/{name}")
def audition_file(name: str):
    p = naming.auditions_dir() / Path(name).name
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="audio/wav")
