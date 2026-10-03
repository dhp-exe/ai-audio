"""The HTTP contract in web/lib/api.ts: config, runs, productions, the human gate, Voice IPs and costs."""

from __future__ import annotations

import json
import time

import pytest
from conftest import needs_ffmpeg, seed_registry
from fastapi.testclient import TestClient

from emvoox.api import app as webapp


@pytest.fixture
def client(sandbox):
    seed_registry(sandbox)
    webapp._engines.clear()
    return TestClient(webapp.app)


def wait_run(client, run_id: str, timeout: float = 120.0) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = client.get(f"/api/runs/{run_id}").json()
        if r["status"] not in ("pending", "running"):
            return r
        time.sleep(0.3)
    raise AssertionError("run did not finish")


def test_config_catalog_and_actors(client):
    c = client.get("/api/config").json()
    assert [p["id"] for p in c["catalog"]["providers"]] == ["gemini", "elevenlabs", "wavespeed", "mock"]  # mock shown because EMVOOX_ENABLE_MOCK
    assert c["keys"] == {"gemini": True, "elevenlabs": True, "wavespeed": False, "openai": False, "anthropic": False}
    ngan = next(a for a in c["actors"] if a["character_id"] == "ngan")
    assert ngan["voices"] == {"elevenlabs": "a3", "gemini": "Leda"} and ngan["sources"]["elevenlabs"] == "library" and ngan["previews"]["gemini"] is None
    assert {t["id"] for t in c["theme_categories"]} >= {"urban_ceo", "rebirth_butterfly_effect", "intellectual_slap_anti_trope"}
    assert len(client.get("/api/agents").json()["agents"]) == 7
    checks = {x["id"]: x["ok"] for x in client.get("/api/doctor").json()["checks"]}
    assert checks["registry"] is True and checks["key.wavespeed"] is None


def test_start_run_validation(client):
    base = {"source": "story", "title": "T", "script": "x" * 60, "episodes": 3, "produce": 1, "min_sec": 30, "max_sec": 60, "force": False,
            "tts_provider": "mock", "tts_model": None, "tts_batching": "auto", "tier": "test", "llm_provider": "mock", "max_retries": 1,
            "auto_approve": False, "halt_on_qa_fail": True}
    dup = {**base, "roles": [{"name": "A", "description": "", "actor_id": "ngan"}, {"name": "B", "description": "", "actor_id": "ngan"}]}
    r = client.post("/api/runs", json=dup)
    assert r.status_code == 422 and "only one role" in r.text
    assert client.post("/api/runs", json={**base, "tts_provider": "wavespeed"}).status_code == 422  # no key
    assert "no API key" in client.post("/api/runs", json={**base, "tts_provider": "wavespeed"}).json()["detail"]
    assert client.post("/api/runs", json={**base, "source": "brief", "brief_id": "nope"}).status_code == 404
    assert client.post("/api/runs", json={**base, "script": "short"}).status_code == 422


@needs_ffmpeg
def test_run_gate_approve_and_costs(client):
    body = {"source": "story", "series_id": "s1", "title": "Bản hợp đồng", "genre": "đô thị", "setting": "", "script": "Một câu chuyện về bản hợp đồng. " * 4,
            "roles": [{"name": "Linh", "description": "nữ 26 tuổi", "actor_id": "ngan"}, {"name": "Khôi", "description": "nam 31 tuổi", "actor_id": None}],
            "episodes": 3, "produce": 1, "min_sec": 30, "max_sec": 60, "force": False, "tts_provider": "mock", "tts_model": None, "tts_batching": "auto",
            "tier": "test", "llm_provider": "mock", "max_retries": 2, "auto_approve": False, "halt_on_qa_fail": True}
    r = client.post("/api/runs", json=body)
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["series_id"] == "s1" and [s["id"] for s in run["steps"]][:3] == ["script", "casting", "ep01.draft"]
    run = wait_run(client, run["run_id"])
    assert run["status"] == "awaiting_approval", run["error"]
    assert run["casting"][0]["actor"] == "ngan" and run["totals"]["llm_calls"] > 0
    assert client.post("/api/runs", json=body).status_code == 409  # the series exists now
    events = client.get(f"/api/runs/{run['run_id']}/events?after=0").json()["events"]
    assert events[0]["type"] == "run.started" and events[-1]["type"] == "run.finished"
    after = events[3]["seq"]
    assert all(e["seq"] > after for e in client.get(f"/api/runs/{run['run_id']}/events?after={after}").json()["events"])
    assert "qa:" in client.get(f"/api/runs/{run['run_id']}/steps/ep01.qa/log").text
    # productions
    lib = client.get("/api/library").json()["series"][0]
    assert (lib["series_id"], lib["planned"], lib["produced"], lib["awaiting"], lib["remaining"]) == ("s1", 3, 1, 1, [2, 3])
    ep = client.get("/api/series/s1/episodes/1").json()
    assert ep["directed"]["units"] and ep["qa"]["status"] == "PASS" and ep["release"]["state"] == "awaiting_approval" and ep["master_url"]
    assert client.get(ep["master_url"]).status_code == 200
    # the gate
    items = client.get("/api/approvals").json()["items"]
    assert len(items) == 1 and items[0]["state"] == "awaiting_approval" and items[0]["qa"]["status"] == "PASS"
    meta = {**items[0]["metadata"], "title": "Bản hợp đồng | Tập 1"}
    assert client.put("/api/series/s1/episodes/1/metadata", json=meta).json()["metadata"]["title"] == "Bản hợp đồng | Tập 1"
    assert client.post("/api/series/s1/episodes/1/approve", json={"reviewer": ""}).status_code == 422
    pkg = client.post("/api/series/s1/episodes/1/approve", json={"reviewer": "an", "notes": "ok"}).json()
    assert pkg["state"] == "approved" and {f["kind"] for f in pkg["exported"]} == {"mp3", "wav", "metadata"}
    out = client.get("/api/outputs").json()["items"]
    assert [o["file"] for o in out] == ["ep01.mp3"] and out[0]["metadata"]["title"] == "Bản hợp đồng | Tập 1"
    assert client.get(out[0]["url"]).status_code == 200
    # dashboard and costs
    d = client.get("/api/dashboard").json()
    assert d["kpis"]["approved"] == 1 and d["kpis"]["episodes_mastered"] == 1 and len(d["cost_by_day"]) == 14
    costs = client.get("/api/costs").json()
    assert costs["totals"]["llm_calls"] > 0 and costs["totals"]["tts_requests"] > 0 and costs["wavespeed"]["available"] is False
    assert {a["agent"] for a in costs["by_agent"]} >= {"script_writer", "director", "sound_engineer", "qa_critic"}
    # continue the series: next episode
    r = client.post("/api/series/s1/resume", json={"next": 1, "tts_provider": "mock", "llm_provider": "mock"})
    assert r.status_code == 200, r.text
    assert wait_run(client, r.json()["run_id"])["params"]["only"] == [2]
    assert client.post("/api/series/s1/resume", json={"tts_provider": "minimax"}).status_code == 422


def test_voice_ips_crud_lock_and_plugging_a_cloned_voice(client):
    r = client.post("/api/characters", json={"character_id": "linh", "display_name": "Linh", "providers": {"gemini": {"voice_id": "kore"}}})
    assert r.status_code == 200, r.text
    linh = next(c for c in client.get("/api/characters").json()["characters"] if c["character_id"] == "linh")
    assert linh["providers"]["gemini"]["voice_id"] == "Kore" and linh["providers"]["gemini"]["source"] == "prebuilt"
    assert client.post("/api/characters", json={"character_id": "x1", "display_name": "X", "providers": {"gemini": {"voice_id": "Nope"}}}).status_code == 422
    assert client.post("/api/characters", json={"character_id": "x3", "display_name": "X", "providers": {"minimax": {"voice_id": "v"}}}).status_code == 422
    # plug the cloning track's voice in: no unlock needed for a new engine, it becomes the preferred engine
    r = client.post("/api/characters/ngan/voices", json={"provider": "wavespeed", "voice_id": "clone-ngan", "model_id": "minimax/speech-2.6-hd",
                                                        "source": "cloned", "label": "Ngân clone v1", "make_preferred": True, "unlock": False})
    assert r.status_code == 200, r.text
    ngan = next(c for c in client.get("/api/characters").json()["characters"] if c["character_id"] == "ngan")
    assert ngan["preferred_provider"] == "wavespeed" and ngan["providers"]["wavespeed"]["source"] == "cloned"
    assert client.post("/api/characters/ngan/voices", json={"provider": "wavespeed", "voice_id": "x", "model_id": "eleven_v3", "source": "cloned",
                                                           "make_preferred": True, "unlock": True}).status_code == 422  # not a WaveSpeed model path
    # replacing a locked voice needs unlock
    r = client.post("/api/characters/ngan/voices", json={"provider": "elevenlabs", "voice_id": "pvc-1", "source": "cloned", "make_preferred": False, "unlock": False})
    assert r.status_code == 423
    assert client.post("/api/characters/ngan/voices", json={"provider": "elevenlabs", "voice_id": "pvc-1", "source": "cloned",
                                                           "make_preferred": False, "unlock": True}).status_code == 200
    assert client.delete("/api/characters/ngan/voices/gemini").status_code == 423
    assert client.delete("/api/characters/ngan/voices/gemini?unlock=true").status_code == 200
    assert client.delete("/api/characters/ngan").status_code == 423
    assert client.delete("/api/characters/ngan?unlock=true").status_code == 200


def test_research_scan_and_briefs(client, repos):
    assert client.post("/api/research/scan", json={"seeds": "", "platforms": [], "use_browser": False, "focus": "", "llm_provider": "mock"}).status_code == 422
    r = client.post("/api/research/scan", json={"seeds": "Top DramaBox tuần này: phim vả mặt, phản diện thông minh", "platforms": [], "use_browser": False,
                                                "focus": "urban_ceo", "guide": "Tìm 3 thể loại hot nhất", "llm_provider": "mock", "wait": True})
    assert r.status_code == 200, r.text
    scan = r.json()
    assert scan["status"] == "done" and scan["phase"] == "done" and scan["brief_id"] and scan["guide"] == "Tìm 3 thể loại hot nhất"
    assert [(s["platform"], s["status"]) for s in scan["steps"]] == [("local", "ok")] and any("trend ranking" in line for line in scan["log"])
    assert client.get(f"/api/research/scans/{scan['scan_id']}").json() == scan and client.get("/api/research/scans").json()["scans"][0]["scan_id"] == scan["scan_id"]
    assert client.get("/api/research/scans/nope").status_code == 404 and client.get(f"/api/research/scans/{scan['scan_id']}/shots/x.jpg").status_code == 404
    brief = client.get(f"/api/research/briefs/{scan['brief_id']}").json()
    assert brief["theme_category"] == "urban_ceo" and len(brief["candidates"]) == 3  # the focus boosts its line to the top; three genres documented
    assert brief["selected"] == 0 and brief["genre"] == brief["candidates"][0]["genre"] and brief["scan_id"] == scan["scan_id"]
    # the editor picks another of the three genres: that one is what the Script Writer receives
    picked = client.post(f"/api/research/briefs/{brief['brief_id']}/select", json={"index": 2}).json()
    assert picked["selected"] == 2 and picked["topic"] == brief["candidates"][2]["topic"] and picked["theme_category"] == brief["candidates"][2]["theme_category"]
    assert client.post(f"/api/research/briefs/{brief['brief_id']}/select", json={"index": 7}).status_code == 422
    assert client.post("/api/research/briefs/nope/select", json={"index": 0}).status_code == 404
    assert client.get("/api/research/briefs").json()["briefs"][0]["brief_id"] == brief["brief_id"]
    assert client.delete(f"/api/research/briefs/{brief['brief_id']}").json() == {"ok": True}


def test_interrupted_runs_and_legacy_runs(client, repos):
    legacy = {"run_id": "old-20260920-000000", "series_id": "old", "status": "running", "created_at": "2026-09-20T00:00:00+00:00",
              "params": {"series_id": "old", "episodes": 3, "tts_provider": "gemini"},
              "jobs": [{"id": "outline", "stage": "outline", "episode": None, "status": "done"}, {"id": "ep01.voice", "stage": "voice", "episode": 1, "status": "running"}]}
    repos.docs.put("series/old/pipeline_run.json", legacy)
    assert webapp.mark_interrupted_runs() == ["old-20260920-000000"]
    data = repos.runs.load_raw("old")
    assert data["status"] == "cancelled" and [j["status"] for j in data["jobs"]] == ["done", "skipped"]
    run = client.get("/api/runs/old-20260920-000000").json()
    assert [s["id"] for s in run["steps"]] == ["outline", "ep01.voice"] and run["totals"]["cost_usd"] == 0
    assert webapp.mark_interrupted_runs() == []


def test_usage_quota_status(client, repos):
    from datetime import UTC, datetime, timedelta

    from emvoox.telemetry import usage
    from emvoox.telemetry.events import record_event

    record_event("gemini", "gemini-3.1-flash-tts-preview", "quota_daily", status=429, quota_id="GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                 quota_value="10", message="quota")
    record_event("gemini", "gemini-2.5-flash-preview-tts", "rate_limit", status=429, retry_after_s=30, message="slow down")
    u = usage.quota_summary(repos, vendor_counters=False)
    by = {m["model"]: m for m in u["models"]}
    tts = by["gemini-3.1-flash-tts-preview"]
    assert tts["status"] == "exhausted" and tts["limit"]["requests_per_day"] == 10
    assert by["gemini-2.5-flash-preview-tts"]["status"] == "rate_limited" and by["eleven_v3"]["status"] == "ok" and len(u["events"]) == 2
    later = datetime.fromisoformat(tts["resets_at"]).astimezone(UTC) + timedelta(hours=1)
    assert {m["model"]: m["status"] for m in usage.quota_summary(repos, now=later, vendor_counters=False)["models"]}["gemini-3.1-flash-tts-preview"] == "ok"
    assert json.dumps(client.get("/api/usage").json())  # serializable end to end
