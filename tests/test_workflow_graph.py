"""The workflow graph: scenes in parallel under a provider cap, per-scene approval and rejection, pausing and
resuming a run from its checkpoint in another engine object, and the budget pause."""

from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest
from conftest import needs_ffmpeg, seed_registry

from emvoox.agents import AgentError
from emvoox.agents.sound_engineer import SoundEngineerAgent
from emvoox.contracts import RunParams, StoryInput, StoryOverview, StoryRole
from emvoox.engine.orchestrator import Engine
from emvoox.providers.llm.mock import MockLlm
from emvoox.providers.tts.mock import MockTtsProvider
from emvoox.telemetry import pricing
from emvoox.workflow.limits import ProviderLimiter

pytestmark = needs_ffmpeg

STORY = StoryInput(
    overview=StoryOverview(title="Bản hợp đồng", genre="Đô thị, tổng tài", setting="Hiện đại"),
    roles=[StoryRole(name="Linh", description="Nữ 26 tuổi, kế toán, bình tĩnh, sắc sảo", actor_id="ngan"),
           StoryRole(name="Khôi", description="Nam 31 tuổi, giám đốc tài chính, toan tính")],
    script="Linh bị đổ lỗi cho một khoản thâm hụt và mất việc. Cô giữ lại một bản sao lưu, lần theo dòng tiền và phát hiện Khôi không phải kẻ chủ mưu duy nhất.",
)


def params(series_id: str = "s1", **kw) -> RunParams:
    return RunParams(**{"series_id": series_id, "episodes": 4, "produce": 1, "min_sec": 30, "max_sec": 70, "tts_provider": "mock", "llm_provider": "mock",
                        "max_retries": 3, **kw})


def run(engine: Engine, resume: dict | None = None):
    return asyncio.run(engine.run(resume))


@pytest.fixture
def studio(sandbox, repos):
    seed_registry(sandbox)
    return repos


class Concurrency:
    """Counts how many calls of a wrapped function overlap."""

    def __init__(self):
        self.lock, self.active, self.peak, self.calls = threading.Lock(), 0, 0, 0

    def wrap(self, fn, delay: float = 0.0):
        def inner(*a, **kw):
            with self.lock:
                self.active += 1
                self.calls += 1
                self.peak = max(self.peak, self.active)
            try:
                time.sleep(delay)
                return fn(*a, **kw)
            finally:
                with self.lock:
                    self.active -= 1
        return inner


def test_scenes_render_in_parallel_under_the_provider_limit(studio, monkeypatch):
    requests, scenes = Concurrency(), Concurrency()
    monkeypatch.setattr(MockTtsProvider, "synthesize", requests.wrap(MockTtsProvider.synthesize, delay=0.05))
    monkeypatch.setattr(SoundEngineerAgent, "generate_voice", scenes.wrap(SoundEngineerAgent.generate_voice))
    eng = Engine(params(), story=STORY, repos=studio, llm=MockLlm())
    st = run(eng)
    assert st.status == "awaiting_approval", st.error
    plan = studio.series.load_directed("s1", 1).render_plan
    assert scenes.calls == 2 and scenes.peak == 2  # one branch per scene, both rendering at once
    # each scene opens its own pool of 2; the shared limiter holds the whole episode to the provider's 2
    assert requests.calls == len(plan) and requests.peak == 2 and eng.limiter.peak == {"mock": 2}
    assert st.step("ep01.voice").summary["rendered"] == len(plan) and studio.series.load_manifest("s1", 1)["units"][0]["id"] == plan[0].id


def test_a_tighter_limit_is_honoured_across_scenes(studio, monkeypatch):
    requests = Concurrency()
    monkeypatch.setattr(MockTtsProvider, "synthesize", requests.wrap(MockTtsProvider.synthesize, delay=0.02))
    eng = Engine(params(), story=STORY, repos=studio, llm=MockLlm())
    eng.limiter = ProviderLimiter(lambda _provider: 1)  # e.g. Gemini TTS on the free tier
    assert run(eng).status == "awaiting_approval"
    assert requests.peak == 1 and eng.limiter.peak == {"mock": 1}


def test_a_scene_that_stays_broken_does_not_hold_back_or_rerender_the_others(studio):
    MockTtsProvider.faults = {"ep01_sc02_l003": "silence*"}
    st = run(Engine(params(max_retries=2), story=STORY, repos=studio, llm=MockLlm()))
    assert st.status == "halted"
    assert [(s.scene_id, s.status, s.attempt) for s in st.scenes] == [("sc01", "passed", 0), ("sc02", "flagged", 2)]
    assert all(MockTtsProvider.calls.count(c) == 1 for c in MockTtsProvider.calls if "_sc01_" in c)  # scene 1 rendered once
    assert MockTtsProvider.calls.count("ep01_sc02_l003") == 3 and st.totals.qa_retries == 2
    report = studio.series.load_qa("s1", 1)
    assert report.status == "FLAGGED" and report.attempt == 2 and report.checks["loudness"]["ok"]  # the episode is still mastered for the reviewer
    assert [(s["scene_id"], s["status"]) for s in report.scenes] == [("sc01", "PASS"), ("sc02", "FLAGGED")]
    assert st.step("ep01.voice").status == "warn" and st.step("ep01.voice").summary["flagged_scenes"] == ["sc02"]


def test_two_scenes_wait_for_approval_and_resume_independently_in_new_engines(studio, monkeypatch):
    """A paused run is continued by engines rebuilt from storage: nothing in memory is shared with the run that paused."""
    renders = Concurrency()
    monkeypatch.setattr(SoundEngineerAgent, "generate_voice", renders.wrap(SoundEngineerAgent.generate_voice))
    st = run(Engine(params(scene_approval=True), story=STORY, repos=studio, llm=MockLlm()))
    assert st.status == "waiting" and st.finished_at is None
    assert sorted((d.kind, d.scene_id, d.data["qa_status"]) for d in st.pending) == [("scene_approval", "sc01", "PASS"), ("scene_approval", "sc02", "PASS")]
    assert [s.status for s in st.scenes] == ["waiting", "waiting"] and st.step("ep01.voice").status == "running"
    assert renders.calls == 2 and studio.series.load_mastered("s1", 1) is None  # both scenes rendered, nothing mastered while they wait
    ids = {d.scene_id: d.id for d in st.pending}

    # approve scene 2 only: scene 1 keeps waiting, no scene is rendered again
    eng = Engine.restore(studio, "s1", llm=MockLlm())
    assert eng.run_id == st.run_id and eng.state.status == "waiting"
    st2 = run(eng, {ids["sc02"]: {"approved": True, "reviewer": "an"}})
    assert st2.status == "waiting" and [(d.scene_id, d.id) for d in st2.pending] == [("sc01", ids["sc01"])]
    assert {s.scene_id: s.status for s in st2.scenes} == {"sc01": "waiting", "sc02": "approved"} and renders.calls == 2

    # approve scene 1 from yet another engine: the join runs, the episode is mastered, checked and parked at the gate
    st3 = run(Engine.restore(studio, "s1", llm=MockLlm()), {ids["sc01"]: {"approved": True, "reviewer": "lead"}})
    assert st3.status == "awaiting_approval" and st3.pending == [] and renders.calls == 2
    assert studio.series.load_mastered("s1", 1) and studio.series.load_release("s1", 1).state == "awaiting_approval"
    assert [(s["scene_id"], s["approved_by"]) for s in studio.series.load_qa("s1", 1).scenes] == [("sc01", "lead"), ("sc02", "an")]
    assert studio.series.load_scene_qa("s1", 1, "sc02").approval.reviewer == "an"
    # one event log across the three engines, numbered without gaps, each wait and approval exactly once
    events = studio.runs.events("s1")
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    scene_events = sorted((e["type"], e["data"]["scene"]) for e in events if e["type"] in ("scene.waiting", "scene.approved"))
    assert scene_events == [("scene.approved", "sc01"), ("scene.approved", "sc02"), ("scene.waiting", "sc01"), ("scene.waiting", "sc02")]
    assert [e["type"] for e in events].count("run.resumed") == 2 and events[-1]["type"] == "run.finished"
    # totals carry over from the engines that did the earlier work
    assert st3.totals.tts_requests == st.totals.tts_requests > 0 and st3.totals.llm_calls > st.totals.llm_calls


def test_a_rejected_scene_is_rendered_again_and_asks_again(studio):
    st = run(Engine(params(scene_approval=True), story=STORY, repos=studio, llm=MockLlm()))
    ids = {d.scene_id: d for d in st.pending}
    unit = ids["sc02"].data["units"][0]
    MockTtsProvider.calls.clear()
    eng = Engine.restore(studio, "s1", llm=MockLlm())
    st = run(eng, {ids["sc01"].id: {"approved": True, "reviewer": "an"},
                   ids["sc02"].id: {"approved": False, "reviewer": "an", "notes": "flat delivery", "unit_ids": [unit]}})
    assert st.status == "waiting" and [(d.scene_id, d.data["attempt"]) for d in st.pending] == [("sc02", 1)]
    assert MockTtsProvider.calls == [unit]  # only the named unit, one attempt further
    assert st.pending[0].id != ids["sc02"].id and any(e["type"] == "scene.rejected" for e in studio.runs.events("s1"))
    st = run(eng, {st.pending[0].id: {"approved": True, "reviewer": "an"}})
    assert st.status == "awaiting_approval"
    plan = {r.id: r.attempt for r in studio.series.load_directed("s1", 1).render_plan}
    assert plan[unit] == 1 and sum(plan.values()) == 1  # the saved plan is the one the stems were rendered from


def test_a_decision_must_belong_to_the_waiting_run(studio):
    eng = Engine(params(scene_approval=True), story=STORY, repos=studio, llm=MockLlm())
    run(eng)
    with pytest.raises(AgentError, match="unknown decision"):
        run(eng, {"nope": {"approved": True}})
    done = Engine(params("s2"), story=STORY, repos=studio, llm=MockLlm())
    run(done)
    with pytest.raises(AgentError, match="not waiting"):
        run(done, {"x": {"approved": True}})


def test_reaching_the_budget_pauses_the_run_until_someone_raises_it(studio, sandbox):
    (sandbox / "assets" / "pricing.json").write_text(json.dumps({"llm": {"mock": [1000.0, 1000.0]}}))  # make the mock LLM cost money
    pricing.reset_overrides()
    st = run(Engine(params(produce=2, max_cost_usd=0.5), story=STORY, repos=studio, llm=MockLlm()))
    assert st.status == "waiting" and [d.kind for d in st.pending] == ["budget"]  # the outline and casting already cost more than the cap
    d = st.pending[0]
    assert d.episode == 1 and d.data["spent_usd"] >= 0.5 and d.data["budget_usd"] == 0.5 and st.step("ep01.draft").status == "pending"
    eng = Engine.restore(studio, "s1", llm=MockLlm())
    spent = eng.spent()
    st = run(eng, {d.id: {"approved": True, "reviewer": "lead", "max_cost_usd": spent + 0.01}})
    # episode 1 is produced under the raised cap, then the run asks again before episode 2
    assert st.status == "waiting" and st.pending[0].kind == "budget" and st.pending[0].episode == 2 and st.budget_usd == round(spent + 0.01, 6)
    assert studio.series.load_release("s1", 1).state == "awaiting_approval"
    st = run(Engine.restore(studio, "s1", llm=MockLlm()), {st.pending[0].id: {"approved": False, "reviewer": "lead"}})
    assert st.status == "halted" and "budget" in st.error and all(s.status == "skipped" for s in st.steps if s.episode == 2)
    types = [e["type"] for e in studio.runs.events("s1")]
    assert types.count("budget.waiting") == 2 and types.count("budget.raised") == 1
