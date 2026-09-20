"""Orchestrator job graph and status transitions with a fake runner (no subprocesses, no network)."""

import json

import pytest

from pipeline import naming
from pipeline.orchestrator import STAGES, Orchestrator, RunParams


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(naming, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(naming, "SERIES_DIR", tmp_path / "series")
    monkeypatch.setattr(naming, "LIBRARY_DIR", tmp_path / "library")
    (tmp_path / "library").mkdir()
    (tmp_path / "library" / "voice-ips.json").write_text(json.dumps({
        "locked": True, "default_provider": "elevenlabs", "characters": [
            {"character_id": "linh", "display_name": "Linh", "persona": "p", "voice_description": "nữ",
             "providers": {"elevenlabs": {"voice_id": "v1", "model_id": "eleven_v3"}}, "is_ip_asset": True}]}))
    return tmp_path


def _bible(sid: str, cast, pending=()):
    p = naming.series_bible_path(sid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "series_id": sid, "title": "t", "premise": "p", "tone": "t", "protagonist_id": "linh", "cast": cast,
        "pending_characters": [{"character_id": c, "display_name": c, "persona": "", "voice_description": "nam, trầm"} for c in pending],
        "episodes": [{"number": i, "title": "x", "logline": "l", "key_beats": ["b"], "cliffhanger": "c"} for i in range(1, 4)],
    }, ensure_ascii=False))


def test_job_graph_shape(sandbox):
    o = Orchestrator(RunParams(series_id="s", episodes=30, produce=3), story="x" * 60)
    jobs = o.build_jobs()
    assert list(jobs)[:2] == ["outline", "cast"]
    assert sum(1 for j in jobs.values() if j.episode) == 3 * len(STAGES)
    assert "--episodes" in jobs["outline"].cmd and "30" in jobs["outline"].cmd
    assert jobs["ep02.draft"].cmd[-2:] == ["--only", "2"]
    assert jobs["ep01.voice"].cmd[-4:] == ["--provider", "elevenlabs", "--batching", "auto"] and "--model-override" not in jobs["ep01.voice"].cmd
    assert jobs["ep01.direct"].cmd[-2:] == ["--provider", "elevenlabs"]


def test_engine_and_resume_params(sandbox):
    p = RunParams(series_id="s", episodes=10, tts_provider="gemini", tts_model="gemini-3.1-flash-tts-preview", only=[4, 9, 42])
    assert p.episode_numbers() == [4, 9]
    jobs = Orchestrator(p, None).build_jobs()
    assert sorted({j.episode for j in jobs.values() if j.episode}) == [4, 9]
    assert jobs["ep04.voice"].cmd[-6:] == ["--provider", "gemini", "--model-override", "gemini-3.1-flash-tts-preview", "--batching", "auto"]
    assert RunParams(series_id="s", tts_provider="gemini", tts_batching="scene").tts_batching == "scene"
    with pytest.raises(ValueError):  # scene batching is a Gemini feature
        RunParams(series_id="s", tts_provider="elevenlabs", tts_batching="scene")
    with pytest.raises(ValueError):
        RunParams(series_id="s", tts_provider="minimax")
    with pytest.raises(ValueError):  # model from the other engine
        RunParams(series_id="s", tts_provider="gemini", tts_model="eleven_v3")
    assert RunParams(series_id="s", tts_provider="gemini", tts_model="").tts_model is None


def test_run_success_and_placeholder_cast(sandbox):
    sid = "s"

    def runner(job):
        if job.stage == "outline":
            _bible(sid, ["linh", "ong-trum"], pending=["ong-trum"])
            return 0, '{"ok": true, "outline": true, "new_characters": ["ong-trum"]}'
        if job.stage == "qa":
            return 2, '{"ok": false, "failed_checks": ["duration"], "review_lines": 1}'
        return 0, json.dumps({"ok": True, "stage": job.stage})

    o = Orchestrator(RunParams(series_id=sid, episodes=3, produce=2), story="x" * 60, runner=runner)
    run = o.start()
    o.wait(30)
    assert run.status == "done", run.error
    assert naming.story_raw_path(sid).exists()
    statuses = {j.id: j.status for j in run.jobs.values()}
    assert statuses["outline"] == "done" and statuses["cast"] == "done"
    assert statuses["ep01.qa"] == "warn" and statuses["ep02.voice"] == "done"
    reg = json.loads((sandbox / "library" / "voice-ips.json").read_text())
    added = next(c for c in reg["characters"] if c["character_id"] == "ong-trum")
    assert added["is_ip_asset"] is False and "elevenlabs" in added["providers"]
    assert added["providers"]["elevenlabs"]["voice_id"] != "v1"  # never shares a voice with the cast
    assert run.notes and "ong-trum" in run.notes[0]
    assert run.casting[0]["voice"] == "v1" if run.casting else True
    state = json.loads(run.state_path().read_text())
    assert state["status"] == "done" and len(state["jobs"]) == 2 + 2 * len(STAGES)


def test_failure_skips_downstream(sandbox):
    sid = "f"

    def runner(job):
        if job.stage == "outline":
            _bible(sid, ["linh"])
            return 0, '{"ok": true}'
        if job.id == "ep01.voice":
            return 2, "ep01_sc01_l001: ProviderError: elevenlabs 402: quota\n{\"ok\": false, \"failed\": [\"ep01_sc01_l001\"]}"
        return 0, '{"ok": true}'

    o = Orchestrator(RunParams(series_id=sid, episodes=2, produce=2), story="x" * 60, runner=runner)
    run = o.start()
    o.wait(30)
    s = {j.id: j.status for j in run.jobs.values()}
    assert run.status == "failed"
    assert s["ep01.voice"] == "failed" and s["ep01.assemble"] == "skipped" and s["ep01.qa"] == "skipped"
    assert s["ep02.qa"] == "done"
    assert "402" in run.jobs["ep01.voice"].error


def test_cast_on_gemini_auto_assigns_ip_actor(sandbox):
    """linh has no Gemini voice: the cast job adds one (an addition, no unlock) and notes it; the
    pending role gets a different Gemini voice."""
    sid = "g"

    def runner(job):
        if job.stage == "outline":
            _bible(sid, ["linh", "ong-trum"], pending=["ong-trum"])
            return 0, '{"ok": true}'
        return 0, '{"ok": true}'

    o = Orchestrator(RunParams(series_id=sid, episodes=2, produce=1, tts_provider="gemini"), story="x" * 60, runner=runner)
    run = o.start()
    o.wait(30)
    assert run.status == "done", run.error
    reg = {c["character_id"]: c for c in json.loads((sandbox / "library" / "voice-ips.json").read_text())["characters"]}
    linh_v, trum_v = reg["linh"]["providers"]["gemini"]["voice_id"], reg["ong-trum"]["providers"]["gemini"]["voice_id"]
    assert linh_v and trum_v and linh_v != trum_v
    assert reg["linh"]["providers"]["gemini"]["model_id"] == "gemini-3.1-flash-tts-preview"
    assert reg["linh"]["providers"]["elevenlabs"]["voice_id"] == "v1"  # untouched
    assert any("auto-assigned" in n for n in run.notes)
    assert run.jobs["cast"].summary["auto_voiced"] == ["linh"] and run.jobs["cast"].summary["placeholders"] == ["ong-trum"]
