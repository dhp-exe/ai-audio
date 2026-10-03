"""Agent skills in isolation: casting and engine policy, trend ranking, cliffhanger rules, QA measurements, mastering with a music bed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import ROOT, needs_ffmpeg, seed_registry, tone

from emvoox.agents import AgentContext, AgentError, CastingAgent, MarketResearchAgent, QACriticAgent, SoundEngineerAgent
from emvoox.agents.qa_critic import wer
from emvoox.agents.script_writer import rule_check
from emvoox.config import get_settings
from emvoox.contracts import (
    EngineRef,
    EpisodeDraft,
    EpisodeScript,
    ProviderVoice,
    ResearchParams,
    RoleCast,
    RunParams,
    SeriesBible,
    TrendCandidate,
)
from emvoox.providers.llm import LlmClient
from emvoox.providers.llm.mock import MockLlm
from emvoox.telemetry.ledger import Ledger


def ctx_for(repos, **params) -> AgentContext:
    ledger = Ledger(repos.telemetry, series_id=params.get("series_id", "s1"))
    p = RunParams(**{"series_id": "s1", "tts_provider": "gemini", **params})
    return AgentContext(settings=get_settings(), repos=repos, llm=LlmClient(MockLlm(), ledger), ledger=ledger, params=p)


def bible_with(repos, roles: list[RoleCast]) -> SeriesBible:
    b = SeriesBible(series_id="s1", title="T", premise="p", tone="t", protagonist_role=roles[0].role_name, roles=roles)
    repos.series.save_bible(b)
    return b


# ---------------------------------------------------------------- casting & engine policy


def test_casting_pins_rules_and_placeholders(sandbox, repos):
    seed_registry(sandbox)
    bible_with(repos, [RoleCast(role_name="Tô Mạn", role_type="protagonist", description="nữ 24 tuổi", actor_id="ngan", assigned_by="user"),
                       RoleCast(role_name="Giang Thần", role_type="antagonist", description="nam 28 tuổi, tổng giám đốc"),
                       RoleCast(role_name="Bà Lý", role_type="minor", description="bà cụ bán nước")])
    ctx = ctx_for(repos)
    cast = CastingAgent().run(ctx)
    by = {m.role_name: m for m in cast.members}
    assert by["Tô Mạn"].actor_id == "ngan" and by["Tô Mạn"].assigned_by == "user" and by["Tô Mạn"].voice_id == "Leda"
    assert by["Giang Thần"].actor_id == "duong" and by["Giang Thần"].voice_source == "prebuilt"
    assert by["Bà Lý"].actor_id == "ba-ly" and by["Bà Lý"].voice_source == "placeholder" and by["Bà Lý"].voice_id not in ("Leda", "Orus")
    reg = repos.registry.load()
    assert reg.get("ba-ly").is_ip_asset is False and "gemini" in reg.get("ba-ly").providers
    bible = repos.series.load_bible("s1")
    assert bible.is_cast() and bible.protagonist_id == "ngan" and set(bible.cast) == {"ngan", "duong", "ba-ly"}


def test_cloned_voice_wins_when_its_engine_is_available(sandbox, repos, monkeypatch):
    seed_registry(sandbox)
    repos.registry.set_provider_voice("ngan", "wavespeed", ProviderVoice(voice_id="pvc-ngan", model_id="minimax/speech-2.6-hd", source="cloned"),
                                      make_preferred=True)
    bible_with(repos, [RoleCast(role_name="Tô Mạn", role_type="protagonist", actor_id="ngan"), RoleCast(role_name="Giang Thần", role_type="antagonist", actor_id="duong")])
    # no WaveSpeed key yet: the run's default engine is used and a note explains why
    cast = CastingAgent().run(ctx := ctx_for(repos))
    assert cast.member("ngan").provider == "gemini" and any("no API key" in n for n in ctx.notes)
    # the key is plugged in: the cloned voice is used right away, other actors stay on the default engine
    monkeypatch.setenv("WAVESPEED_API_KEY", "ws")
    from emvoox.config import reset_settings

    reset_settings()
    cast = CastingAgent().run(ctx_for(repos))
    m = cast.member("ngan")
    assert (m.provider, m.model_id, m.voice_id, m.voice_source) == ("wavespeed", "minimax/speech-2.6-hd", "pvc-ngan", "cloned")
    assert cast.member("duong").provider == "gemini"
    # an explicit per-role-type policy routes the antagonist through WaveSpeed's ElevenLabs endpoint with its own ElevenLabs voice
    cast = CastingAgent().run(ctx_for(repos, engine_by_role_type={"antagonist": EngineRef(provider="wavespeed")}))
    d = cast.member("duong")
    assert (d.provider, d.model_id, d.voice_id) == ("wavespeed", "elevenlabs/eleven-v3", "u5")
    assert repos.registry.load().get("duong").providers["wavespeed"].source == "library"


def test_final_tier_refuses_placeholders(sandbox, repos):
    seed_registry(sandbox)
    bible_with(repos, [RoleCast(role_name="A", role_type="protagonist", actor_id="ngan"), RoleCast(role_name="B", role_type="antagonist", actor_id="duong"),
                       RoleCast(role_name="C", role_type="minor", description="nam")])
    with pytest.raises(AgentError, match="placeholder"):
        CastingAgent().run(ctx_for(repos, tier="final"))


# ---------------------------------------------------------------- market research, script rules


def test_trend_ranking_weights_and_focus():
    def c(topic, theme, a, m, p):
        return TrendCandidate(topic=topic, theme_category=theme, target_audience="x", hook="h", premise="p", anti_trope_angle="a",
                              audience_fit=a, momentum=m, production_fit=p)

    ranked = MarketResearchAgent().trend_ranking([c("A", "urban_ceo", 8, 8, 8), c("B", "rebirth_butterfly_effect", 9, 9, 6)])
    assert [x.topic for x in ranked] == ["B", "A"] and ranked[0].score == round(9 * 0.45 + 9 * 0.30 + 6 * 0.25, 2)
    focused = MarketResearchAgent().trend_ranking([c("A", "urban_ceo", 8, 8, 8), c("B", "rebirth_butterfly_effect", 8, 8, 8)], focus="urban_ceo")
    assert focused[0].topic == "A"


def test_market_scan_reads_seeds_and_pasted_notes(repos):
    repos.blobs.write_text("inputs/trends/week40.md", "DramaBox top 10 ...")
    obs = MarketResearchAgent().market_scan(ctx_for(repos), ResearchParams(seeds="ghi chú dán vào"))
    assert [o.source for o in obs] == ["pasted notes", "week40.md"] and all(o.via == "local" for o in obs)


def test_cliffhanger_rules():
    draft = EpisodeDraft.model_validate({"episode_number": 1, "title": "t", "estimated_duration_sec": 60, "scenes": [{"heading": "h", "lines": [
        {"speaker": "Linh", "text": "Anh là ai?"}, {"speaker": "Khôi", "text": "Em sẽ biết sớm thôi."},
        {"speaker": "Linh", "internal": True, "text": "Nhưng người mở cửa lại là mẹ tôi..."}]}]})
    check = rule_check(draft, "người mở cửa lại là mẹ tôi", 6)
    assert check.passed and check.twist_within_30s and check.hook_score >= 8 and check.checked_by == "rules"
    flat = EpisodeDraft.model_validate({"episode_number": 2, "title": "t", "estimated_duration_sec": 60, "scenes": [{"heading": "h", "lines": [
        {"speaker": "Linh", "text": "Chào anh."}, {"speaker": "Khôi", "text": "Chào em."}]}]})
    assert not rule_check(flat, "x", 6).passed


# ---------------------------------------------------------------- QA measurements and mastering


def test_wer():
    assert wer("Anh đi đi.", "anh đi đi") == 0.0
    assert wer("một hai ba bốn", "một ba bốn") == 0.25
    assert wer("[sighs] Xin chào", "xin chào") == 0.0


@needs_ffmpeg
def test_qa_critic_finds_clipping_silence_wrong_voice_and_missing_stems(sandbox, repos):
    from tests_support import make_cast_and_script

    from emvoox.agents import DirectorAgent

    script, cast = make_cast_and_script()
    ctx = ctx_for(repos, series_id="t")
    repos.series.save_script(script)
    directed = DirectorAgent()._assemble(ctx, script, cast)
    stems = {r.id: r.stem for r in directed.render_plan}
    stem = lambda uid: repos.series.stem_path("t", 1, stems[uid])  # noqa: E731
    tone(stem("ep01_sc01_l001"), 2.6)
    tone(stem("ep01_sc01_l002"), 2.0, volume=20.0)                    # lavfi sine is -18 dBFS; x20 hard-clips
    tone(stem("ep01_sc01_l003"), 0.2)                                 # far too short for its words: a sentence is missing
    tone(stem("ep01_sc02_l001"), 1.6, volume=0.0)                     # silent
    repos.series.save_stem_meta("t", 1, stems["ep01_sc01_l001"], {"request": {"voice_id": "WRONG"}})  # rendered with another voice
    # ep01_sc02_l002 has no stem at all
    report = QACriticAgent().run(ctx, directed, cast, None)
    codes = {(i.code, i.unit_id) for i in report.error_logs}
    assert ("clipping", "ep01_sc01_l002") in codes and ("missing_sentence", "ep01_sc01_l003") in codes
    assert ("long_silence", "ep01_sc02_l001") in codes and ("speaker_mismatch", "ep01_sc01_l001") in codes
    assert ("missing_stem", "ep01_sc02_l002") in codes and ("master_missing", None) in codes
    assert report.status == "FLAGGED" and report.score < 50
    rr = {r.action: r.unit_ids for r in report.retry_instructions}
    assert set(rr["rerender"]) == {"ep01_sc01_l001", "ep01_sc01_l002", "ep01_sc01_l003", "ep01_sc02_l001", "ep01_sc02_l002"}


@needs_ffmpeg
def test_master_with_ducked_music_bed(sandbox, repos, monkeypatch):
    monkeypatch.setenv("ENABLE_BGM", "true")
    from tests_support import make_cast_and_script

    from emvoox.agents import DirectorAgent
    from emvoox.config import reset_settings

    reset_settings()
    script, cast = make_cast_and_script()
    ctx = ctx_for(repos, series_id="t")
    directed = DirectorAgent()._assemble(ctx, script, cast)
    assert directed.bgm_mood == "default"
    for r in directed.render_plan:
        tone(repos.series.stem_path("t", 1, r.stem), 1.0)
    tone(repos.blobs.path("assets/bgm/default/bed.wav"), 4.0, freq=220, volume=0.8)
    m = SoundEngineerAgent().assemble_audio(ctx, directed)
    tl = repos.series.load_timeline("t", 1)
    assert m.bgm is True and abs(m.loudness.integrated_lufs + 16) <= 1.0 and m.loudness.true_peak_dbtp <= -1.4
    assert m.duration_ms == tl.total_duration_ms and repos.blobs.exists(m.mp3_path)
    gaps = [c.duration_ms for c in tl.clips if c.kind == "silence"]
    assert gaps[-1] == 500 and 800 + 300 in [a + b for a, b in zip(gaps, gaps[1:], strict=False)] or 800 in gaps


def test_fixture_episode_still_validates():
    s = EpisodeScript.model_validate_json((ROOT / "tests/fixtures/episode.json").read_text(encoding="utf-8"))
    assert len(s.all_lines()) == 11 and json.loads(s.model_dump_json())["language"] == "vi-VN"
    assert Path(ROOT / "data/assets/voice_registry.json").exists()
