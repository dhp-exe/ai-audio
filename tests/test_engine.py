"""The engine end to end with the offline mock LLM and voice engine: every agent, the handoff validation,
the QA retry loop, the human gate, halting, telemetry and resuming. Needs FFmpeg (mastering and QA)."""

from __future__ import annotations

import asyncio

import pytest
from conftest import needs_ffmpeg, seed_registry

from emvoox.agents import AgentError, DirectorAgent
from emvoox.agents.publisher import approve, reject
from emvoox.contracts import ResearchParams, RunParams, StoryInput, StoryOverview, StoryRole
from emvoox.engine.orchestrator import Engine
from emvoox.providers.llm.mock import MockLlm
from emvoox.providers.tts.mock import MockTtsProvider

pytestmark = needs_ffmpeg

STORY = StoryInput(
    overview=StoryOverview(title="Bản hợp đồng", genre="Đô thị, tổng tài", setting="Hiện đại"),
    roles=[StoryRole(name="Linh", description="Nữ 26 tuổi, kế toán, bình tĩnh, sắc sảo", actor_id="ngan"),
           StoryRole(name="Khôi", description="Nam 31 tuổi, giám đốc tài chính, toan tính")],
    script="Linh bị đổ lỗi cho một khoản thâm hụt và mất việc. Cô giữ lại một bản sao lưu, lần theo dòng tiền và phát hiện Khôi không phải kẻ chủ mưu duy nhất.",
)


def params(**kw) -> RunParams:
    base = dict(series_id="s1", episodes=4, produce=2, min_sec=30, max_sec=70, tts_provider="mock", llm_provider="mock", max_retries=3)
    base.update(kw)
    return RunParams(**base)


def run(engine: Engine):
    return asyncio.run(engine.run())


@pytest.fixture
def studio(sandbox, repos):
    seed_registry(sandbox)
    return repos


def test_full_run_reaches_the_gate_and_exports_on_approval(studio):
    eng = Engine(params(), story=STORY, repos=studio, llm=MockLlm())
    st = run(eng)
    assert st.status == "awaiting_approval", st.error
    by = {s.id: s for s in st.steps}
    assert [s.status for s in st.steps if s.episode is None] == ["done", "done"]
    for n in (1, 2):
        assert [by[f"ep0{n}.{x}"].status for x in ("draft", "direct", "voice", "master", "qa", "gate")] == ["done"] * 5 + ["waiting"]
    # casting: the pin survives, the open role gets the remaining IP actor; both get a mock voice added to the registry
    cast = studio.series.load_cast("s1")
    assert {m.role_name: m.actor_id for m in cast.members} == {"Linh": "ngan", "Khôi": "duong"}
    assert {m.provider for m in cast.members} == {"mock"} and cast.protagonist_id == "ngan"
    assert all("mock" in studio.registry.load().get(a).providers for a in ("ngan", "duong"))
    # every handoff artifact exists and validates
    for n in (1, 2):
        assert studio.series.load_directed("s1", n) and studio.series.load_mastered("s1", n) and studio.series.load_qa("s1", n).status == "PASS"
        assert studio.series.load_release("s1", n).state == "awaiting_approval"
        assert studio.series.load_cliffhanger("s1", n).hook_score == 8
    m = studio.series.load_mastered("s1", 1)
    assert abs(m.loudness.integrated_lufs + 16) <= 1.0 and m.loudness.true_peak_dbtp <= -1.4
    # telemetry: LLM calls and TTS requests are in the ledger, the run totals add up
    assert st.totals.llm_calls >= 6 and st.totals.tts_requests >= 20 and st.totals.tts_characters > 0 and st.totals.cost_usd == 0
    kinds = {r["kind"] for r in studio.docs.read_log("series/s1/run.log.jsonl")}
    assert kinds == {"llm", "tts", "agent"}
    # the event log tells the story in order
    types = [e["type"] for e in studio.runs.events("s1")]
    assert types[0] == "run.started" and types[-1] == "run.finished" and "cast.resolved" in types and types.count("gate.waiting") == 2
    # nothing is exported before a human approves
    assert studio.outputs.list() == []
    pkg = approve(studio, "s1", 1, reviewer="an", notes="ok")
    assert pkg.state == "approved" and {f.kind for f in pkg.exported} == {"mp3", "wav", "metadata"}
    meta = studio.docs.get("outputs/approved_masters/s1/ep01.youtube.json")
    assert meta["contains_synthetic_media"] is True and meta["approved_by"] == "an" and meta["platform"] == "youtube"
    assert studio.series.load_qa("s1", 1).human.verdict == "approved"
    pkg = reject(studio, "s1", 1, reviewer="an", notes="line 2 is flat", lines=["ep01_sc01_l002"])
    assert pkg.state == "rejected" and studio.outputs.list() == []


def test_qa_flags_a_broken_line_and_the_engine_rerenders_only_that_line(studio):
    MockTtsProvider.faults = {"ep01_sc01_l002": "clip", "ep01_sc02_l003": "truncate"}
    st = run(Engine(params(produce=1), story=STORY, repos=studio, llm=MockLlm()))
    assert st.status == "awaiting_approval", st.error
    report = studio.series.load_qa("s1", 1)
    assert report.status == "PASS" and report.attempt == 1 and st.totals.qa_retries == 1
    assert st.step("ep01.voice").attempts == 2 and st.step("ep01.qa").attempts == 2
    # only the two flagged units were rendered again
    assert sorted(c for c in MockTtsProvider.calls if MockTtsProvider.calls.count(c) > 1) == ["ep01_sc01_l002", "ep01_sc01_l002", "ep01_sc02_l003", "ep01_sc02_l003"]
    flagged = [e for e in studio.runs.events("s1") if e["type"] == "qa.flagged"]
    assert len(flagged) == 1 and set(flagged[0]["data"]["codes"]) == {"clipping", "missing_sentence"}
    meta = studio.series.stem_meta("s1", 1, "ep01_sc01_l002_duong_dialogue.wav") or studio.series.stem_meta("s1", 1, "ep01_sc01_l002_ngan_dialogue.wav")
    assert meta["attempt"] == 1 and meta["request"]["attempt"] == 1


def test_persistent_failure_goes_to_human_review_and_halts_the_run(studio):
    MockTtsProvider.faults = {"ep01_sc01_l003": "silence*"}
    st = run(Engine(params(produce=2, max_retries=2), story=STORY, repos=studio, llm=MockLlm()))
    assert st.status == "halted" and "needs human review" not in (st.error or "") and "FLAGGED" in st.error
    report = studio.series.load_qa("s1", 1)
    assert report.status == "FLAGGED" and report.attempt == 2 and report.retry_instructions
    assert any(i.code == "long_silence" and i.at_ms is not None for i in report.error_logs)
    pkg = studio.series.load_release("s1", 1)
    assert pkg.state == "needs_review" and "after 2 automatic retries" in pkg.reason
    assert st.step("ep01.gate").status == "waiting" and st.step("ep01.qa").status == "warn"
    assert all(s.status == "skipped" for s in st.steps if s.episode == 2)
    # a human may still approve: recorded as an override
    assert approve(studio, "s1", 1, reviewer="lead").decision.override_flagged is True


def test_no_halt_keeps_producing(studio):
    MockTtsProvider.faults = {"ep01_sc01_l003": "silence*"}
    st = run(Engine(params(produce=2, max_retries=1, halt_on_qa_fail=False), story=STORY, repos=studio, llm=MockLlm()))
    assert st.status == "awaiting_approval" and st.step("ep02.gate").status == "waiting"
    assert studio.series.load_release("s1", 1).state == "needs_review" and studio.series.load_release("s1", 2).state == "awaiting_approval"


def test_auto_approve_exports_pass_episodes(studio):
    st = run(Engine(params(produce=1, auto_approve=True), story=STORY, repos=studio, llm=MockLlm()))
    assert st.status == "done" and st.step("ep01.gate").status == "approved"
    assert [i["file"] for i in studio.outputs.list()] == ["ep01.mp3"]


def test_rejected_director_output_falls_back_to_rule_based_direction(studio, monkeypatch):
    class BadDirector(MockLlm):
        def generate_structured(self, *, schema, **kw):
            if schema.__name__ == "EpisodeScript":
                from emvoox.providers.llm import LlmSchemaError

                raise LlmSchemaError("line_id must match epNN_scNN_lNNN")
            return super().generate_structured(schema=schema, **kw)

    st = run(Engine(params(produce=1), story=STORY, repos=studio, llm=BadDirector()))
    assert st.status == "awaiting_approval", st.error
    assert any("directed by rules" in n for n in st.notes)
    assert studio.series.load_script("s1", 1).director_notes == "rule-based direction (no LLM)"


def test_handoff_validation_rejects_a_bad_director_payload(studio, monkeypatch):
    real = DirectorAgent.run

    def wrong_episode(self, ctx, episode, cast):
        d = real(self, ctx, episode, cast)
        return d.model_copy(update={"episode_number": episode + 1})

    monkeypatch.setattr(DirectorAgent, "run", wrong_episode)
    st = run(Engine(params(produce=1), story=STORY, repos=studio, llm=MockLlm()))
    direct = st.step("ep01.direct")
    assert direct.status == "failed" and direct.attempts == 2 and st.status == "failed"
    assert st.step("ep01.voice").status == "skipped"
    assert any(e["type"] == "contract.rejected" for e in studio.runs.events("s1"))


def test_market_research_to_master(studio):
    studio.blobs.write_text("inputs/trends/notes.md", "Phim 'Ngày tôi bị vu oan' đang hot trên DramaBox; khán giả khen phản diện thông minh.")
    p = params(produce=1, source="research", research=ResearchParams(focus="intellectual_slap"))
    st = run(Engine(p, repos=studio, llm=MockLlm()))
    assert st.status == "awaiting_approval", st.error
    assert st.step("research").summary["theme"] == "intellectual_slap_anti_trope"
    bible = studio.series.load_bible("s1")
    assert bible.trend_brief_id and bible.theme_category == "intellectual_slap_anti_trope" and len(bible.roles) == 3
    assert studio.series.load_trend_brief("s1").topic.startswith("Ngày tôi phản công")
    # three named roles but two Voice IPs: the third becomes a background role with a temporary voice, and no character is added to the registry
    cast = studio.series.load_cast("s1")
    assert [m.voice_source for m in cast.members].count("placeholder") == 1 and any("Temporary voice" in n for n in st.notes)
    assert [r.role_type for r in bible.roles].count("minor") == 1 and studio.registry.load().ids() == {"ngan", "duong"}


def test_research_without_inputs_fails_clearly(studio):
    st = run(Engine(params(source="research"), repos=studio, llm=MockLlm()))
    assert st.status == "failed" and "found nothing to analyse" in (st.step("research").error or "")


def test_resume_keeps_outline_and_drafts(studio):
    run(Engine(params(produce=1), story=STORY, repos=studio, llm=MockLlm()))
    llm = MockLlm()
    st = run(Engine(params(only=[2], source="existing"), repos=studio, llm=llm))
    assert st.status == "awaiting_approval" and st.episodes() == [2]
    assert "SeriesOutline" not in llm.calls and llm.calls.count("EpisodeDraft") == 1
    assert st.step("script").summary["reused"] is True


def test_missing_key_fails_before_spending(studio, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    from emvoox.config import reset_settings

    reset_settings()
    with pytest.raises(ValueError):
        RunParams(series_id="s1", tts_provider="minimax")
    st = run(Engine(params(tts_provider="gemini"), story=STORY, repos=studio, llm=MockLlm()))
    assert st.status == "failed" and "has no API key" in (st.step("casting").error or "")


def test_agent_error_is_typed():
    assert AgentError("x", retryable=True).retryable
