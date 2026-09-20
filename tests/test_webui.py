"""Web API contract: config/catalog, library listing, resume, character CRUD and the one-actor-one-role rule.
Runs against a sandboxed series/ and library/ tree; the orchestrator is never started for real."""

import json

import pytest
from fastapi.testclient import TestClient

from pipeline import naming, stories
from pipeline.webui import app as webapp


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(naming, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(naming, "SERIES_DIR", tmp_path / "series")
    monkeypatch.setattr(naming, "LIBRARY_DIR", tmp_path / "library")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "e")
    from pipeline import config
    config.get_settings.cache_clear()
    (tmp_path / "library").mkdir()
    (tmp_path / "library" / "voice-ips.json").write_text(json.dumps({
        "locked": True, "default_provider": "elevenlabs", "characters": [
            {"character_id": "ngan", "display_name": "Ngân", "persona": "cute", "voice_description": "nữ", "gender": "female",
             "providers": {"elevenlabs": {"voice_id": "a3", "model_id": "eleven_v3"}, "gemini": {"voice_id": "Leda", "model_id": "gemini-2.5-flash-preview-tts"}}},
            {"character_id": "duong", "display_name": "Dương", "persona": "ceo", "voice_description": "nam", "gender": "male",
             "providers": {"elevenlabs": {"voice_id": "u5", "model_id": "eleven_v3"}}}]}))
    webapp._runs.clear()
    # a finished series with 3 planned episodes, 1 master
    sid = "s1"
    naming.story_json_path(sid).parent.mkdir(parents=True)
    naming.story_json_path(sid).write_text(json.dumps({"overview": {"title": "Story One", "genre": "drama"}, "roles": [{"name": "Tô Mạn", "actor_id": "ngan"}], "script": "x" * 60}))
    naming.series_bible_path(sid).write_text(json.dumps({
        "series_id": sid, "title": "Story One", "premise": "p", "tone": "t", "mode": "segment", "protagonist_id": "ngan", "cast": ["ngan", "duong"],
        "roles": [{"role_name": "Tô Mạn", "role_type": "protagonist", "actor_id": "ngan", "assigned_by": "user"},
                  {"role_name": "Giang Thần", "role_type": "antagonist", "actor_id": "duong"}],
        "episodes": [{"number": i, "title": f"t{i}", "logline": "l", "key_beats": ["b"], "cliffhanger": "c"} for i in range(1, 4)]}, ensure_ascii=False))
    naming.master_path(sid, 1, "mp3").parent.mkdir(parents=True)
    naming.master_path(sid, 1, "mp3").write_bytes(b"ID3")
    naming.qa_report_path(sid, 1).parent.mkdir(parents=True)
    naming.qa_report_path(sid, 1).write_text(json.dumps({"checks": {"duration": {"ok": True, "seconds": 61.2}, "loudness": {"ok": False}}, "review_lines": [], "human": None}))
    (naming.series_root(sid) / "pipeline_run.json").write_text(json.dumps({"run_id": "s1-20260920-000000", "status": "done", "created_at": "2026-09-20T00:00:00+00:00",
                                                                            "params": {"series_id": sid, "episodes": 3, "tts_provider": "gemini", "tts_model": None, "min_sec": 50, "max_sec": 70}}))
    return TestClient(webapp.app)


def test_config_catalog_and_actors(client):
    c = client.get("/api/config").json()
    assert [p["id"] for p in c["catalog"]["providers"]] == ["elevenlabs", "gemini"]
    assert c["keys"] == {"gemini": True, "elevenlabs": True}
    ngan = next(a for a in c["actors"] if a["character_id"] == "ngan")
    assert ngan["voices"] == {"elevenlabs": "a3", "gemini": "Leda"} and ngan["previews"]["gemini"] is None


def test_library_progress_and_detail(client):
    lib = client.get("/api/library").json()["series"]
    assert len(lib) == 1
    s = lib[0]
    assert s["series_id"] == "s1" and s["planned"] == 3 and s["produced"] == 1 and s["remaining"] == [2, 3] and s["next_episode"] == 2
    assert s["status"] == "in_progress" and s["run"]["tts_provider"] == "gemini" and s["qa_warn"] == 1
    assert s["roles"][0]["actor_name"] == "Ngân"
    d = client.get("/api/series/s1").json()
    assert d["episodes"][0]["master_url"] == "/api/series/s1/master/1.mp3" and d["episodes"][0]["qa"]["failed_checks"] == ["loudness"]
    assert d["episodes"][0]["duration_ms"] == 61200 and d["story"]["overview"]["title"] == "Story One"
    assert client.get("/api/series/nope").status_code == 404


def test_resume_builds_run_for_remaining(client, monkeypatch):
    started = {}

    class FakeOrch:
        def __init__(self, params, story):
            started["params"] = params
            # "done" so the next resume in the test is not blocked by an active run
            self.run = type("R", (), {"status": "done", "run_id": "s1-x", "params": params, "to_dict": lambda self: {"run_id": "s1-x", "params": params.__dict__}})()

        def start(self):
            return self.run

    monkeypatch.setattr(webapp, "Orchestrator", FakeOrch)
    r = client.post("/api/series/s1/resume", json={"next": 1, "tts_provider": "elevenlabs"})
    assert r.status_code == 200, r.text
    p = started["params"]
    assert p.only == [2] and p.episodes == 3 and p.tts_provider == "elevenlabs" and p.tts_model is None and p.min_sec == 50
    # engine kept from the last run when not given
    r = client.post("/api/series/s1/resume", json={"next": 5})
    assert r.status_code == 200, r.text
    assert started["params"].tts_provider == "gemini" and started["params"].only == [2, 3]
    assert client.post("/api/series/s1/resume", json={"tts_provider": "minimax"}).status_code == 422
    assert client.post("/api/series/s1/resume", json={"tts_model": "eleven_v3", "tts_provider": "gemini"}).status_code == 422


def test_start_run_rejects_duplicate_actor(client):
    body = {"title": "T", "script": "x" * 60, "roles": [{"name": "A", "actor_id": "ngan"}, {"name": "B", "description": "…", "actor_id": "ngan"}]}
    r = client.post("/api/runs", json=body)
    assert r.status_code == 422 and "one Character IP can play only one role" in r.text
    body = {"title": "T", "script": "x" * 60, "roles": [{"name": "A /ngan"}, {"name": "B", "description": "abc #ngan"}]}
    assert client.post("/api/runs", json=body).status_code == 422


def test_character_crud_and_lock(client):
    r = client.post("/api/characters", json={"character_id": "linh", "display_name": "Linh", "providers": {"gemini": {"voice_id": "kore"}}})
    assert r.status_code == 200, r.text
    chars = client.get("/api/characters").json()["characters"]
    linh = next(c for c in chars if c["character_id"] == "linh")
    assert linh["providers"]["gemini"] == {"voice_id": "Kore", "model_id": "gemini-2.5-flash-preview-tts", "voice_url": None, "fallback_voice_id": None, "default_settings": {}}
    # bad gemini voice / bad model / unknown provider
    assert client.post("/api/characters", json={"character_id": "x1", "display_name": "X", "providers": {"gemini": {"voice_id": "Nope"}}}).status_code == 422
    assert client.post("/api/characters", json={"character_id": "x2", "display_name": "X", "providers": {"elevenlabs": {"voice_id": "v", "model_id": "speech-02-hd"}}}).status_code == 422
    assert client.post("/api/characters", json={"character_id": "x3", "display_name": "X", "providers": {"minimax": {"voice_id": "v"}}}).status_code == 422
    # locked IP: changing or dropping a voice needs unlock
    ngan = {"character_id": "ngan", "display_name": "Ngân", "providers": {"elevenlabs": {"voice_id": "a3", "model_id": "eleven_v3"}}}
    assert client.put("/api/characters/ngan", json=ngan).status_code == 423  # drops gemini voice
    assert client.put("/api/characters/ngan?unlock=true", json=ngan).status_code == 200
    chars = client.get("/api/characters").json()["characters"]
    assert "gemini" not in next(c for c in chars if c["character_id"] == "ngan")["providers"]
    assert client.delete("/api/characters/ngan").status_code == 423
    assert client.delete("/api/characters/ngan?unlock=true").status_code == 200


def test_delete_series(client):
    assert client.delete("/api/series/s1").status_code == 200
    assert client.get("/api/library").json()["series"] == [] and stories.series_summary("s1") is None
