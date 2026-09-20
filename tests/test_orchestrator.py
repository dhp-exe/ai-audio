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
    assert run.notes and "ong-trum" in run.notes[0]
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
