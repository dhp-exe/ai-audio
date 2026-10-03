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
    # a temporary voice belongs to this production's cast only: the Voice IP registry is untouched
    assert by["Bà Lý"].is_ip_asset is False and repos.registry.load().ids() == {"ngan", "duong"}
    assert any("Temporary voice" in n and "this production only" in n for n in ctx.notes)
    # a later run of the same series keeps the background role's voice
    again = CastingAgent().run(ctx_for(repos))
    assert again.member("ba-ly").voice_id == by["Bà Lý"].voice_id and repos.registry.load().ids() == {"ngan", "duong"}
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
                       RoleCast(role_name="C", role_type="supporting", description="nam")])
    with pytest.raises(AgentError, match="temporary voices on named roles"):
        CastingAgent().run(ctx_for(repos, tier="final"))
    # a background role may keep a temporary voice in a final render
    bible_with(repos, [RoleCast(role_name="A", role_type="protagonist", actor_id="ngan"), RoleCast(role_name="B", role_type="antagonist", actor_id="duong"),
                       RoleCast(role_name="C", role_type="minor", description="nam")])
    assert CastingAgent().run(ctx_for(repos, tier="final")).member("c").voice_source == "placeholder"


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


def test_browser_scan_records_each_page_and_reports_blocks(repos, monkeypatch):
    """The browser scan publishes one step per source (status, excerpt, screenshot); a robot check is 'blocked', never bypassed."""
    import sys
    from types import ModuleType, SimpleNamespace

    pages = {"https://a.example/": (200, "A", "Tổng tài lạnh lùng\n" * 60), "https://www.google.com/search?q=x": (429, "sorry", "Our systems have detected unusual traffic")}

    class Page:
        def goto(self, url, **_):
            self.url = url
            self.status, self._title, self._text = pages[url]
            return SimpleNamespace(status=self.status)

        mouse = SimpleNamespace(wheel=lambda *_: None)

        def wait_for_timeout(self, _ms): ...
        def title(self): return self._title
        def inner_text(self, _sel): return self._text
        def screenshot(self, path, **_): open(path, "wb").write(b"jpg")
        def close(self): ...

    class Ctx:
        def __enter__(self): return SimpleNamespace(chromium=SimpleNamespace(launch=lambda **_: SimpleNamespace(
            new_context=lambda **_: SimpleNamespace(new_page=Page), close=lambda: None)))
        def __exit__(self, *_): return False

    mod = ModuleType("playwright.sync_api")
    mod.sync_playwright = Ctx  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "playwright", ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", mod)
    repos.docs.put("inputs/market_sources.json", [{"platform": "dramabox", "url": "https://a.example/"}, {"platform": "google", "url": "https://www.google.com/search?q=x"},
                                                  {"platform": "tiktok", "url": "https://t.example/"}])
    agent = MarketResearchAgent()
    brief = agent.run(ctx_for(repos), ResearchParams(use_browser=True, platforms=["dramabox", "google"], guide="3 thể loại hot nhất"), scan_id="scan-20261003-000000")
    scan = repos.research.load_scan("scan-20261003-000000")
    assert [(s.platform, s.status) for s in scan.steps] == [("dramabox", "ok"), ("google", "blocked")]  # tiktok was not asked for
    assert scan.steps[0].screenshot == "dramabox-1.jpg" and repos.blobs.exists("research/scans/scan-20261003-000000/dramabox-1.jpg") and scan.steps[0].chars > 400
    assert scan.status == "done" and scan.brief_id == brief.brief_id and brief.sources == ["https://a.example/"] and len(brief.candidates) == 3
    assert brief.with_selected(1).topic == brief.candidates[1].topic
    # nothing readable at all: the run fails with a clear message and the scan is closed as failed
    with pytest.raises(AgentError, match="blocked or failed"):
        agent.run(ctx_for(repos), ResearchParams(use_browser=True, platforms=["google"]), scan_id="scan-20261003-000001")
    assert repos.research.load_scan("scan-20261003-000001").status == "failed"


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


def test_wavespeed_model_family_picks_the_matching_voice(sandbox, repos, monkeypatch):
    """On WaveSpeed the model path decides whose voices are valid: Gemini TTS takes the actor's Gemini voice name,
    the ElevenLabs endpoint its ElevenLabs id; a plugged-in voice of another family is never used or overwritten."""
    from emvoox.config import reset_settings

    g38 = "google/gemini-3.8-flash/text-to-speech"
    monkeypatch.setenv("WAVESPEED_API_KEY", "ws")
    reset_settings()
    seed_registry(sandbox)
    bible_with(repos, [RoleCast(role_name="Tô Mạn", role_type="protagonist", actor_id="ngan"), RoleCast(role_name="Giang Thần", role_type="antagonist", actor_id="duong"),
                       RoleCast(role_name="Bà Lý", role_type="minor", description="nữ, lớn tuổi")])
    cast = CastingAgent().run(ctx_for(repos, tts_provider="wavespeed", tts_model=g38))
    by = {m.role_name: m for m in cast.members}
    assert (by["Tô Mạn"].model_id, by["Tô Mạn"].voice_id, by["Tô Mạn"].voice_source) == (g38, "Leda", "prebuilt")
    assert by["Giang Thần"].voice_id == "Orus"
    from emvoox.providers.tts.catalog import gemini_voice

    assert gemini_voice(by["Bà Lý"].voice_id) is not None and by["Bà Lý"].voice_id not in ("Leda", "Orus")  # placeholder from the Gemini pool
    # switching the run back to the ElevenLabs endpoint uses the ElevenLabs ids, although a Gemini-family WaveSpeed voice is stored
    assert repos.registry.load().get("ngan").providers["wavespeed"].voice_id == "Leda"
    cast = CastingAgent().run(ctx_for(repos, tts_provider="wavespeed", tts_model="elevenlabs/eleven-v3"))
    assert (cast.member("ngan").voice_id, cast.member("duong").voice_id) == ("a3", "u5")
    assert repos.registry.load().get("ngan").providers["wavespeed"].voice_id == "Leda"  # not overwritten
    # EMVOOX_TTS_MODEL is the default for runs that name no model
    monkeypatch.setenv("EMVOOX_TTS_PROVIDER", "wavespeed")
    monkeypatch.setenv("EMVOOX_TTS_MODEL", g38)
    reset_settings()
    assert CastingAgent().run(ctx_for(repos, tts_provider="wavespeed")).member("duong").model_id == g38


def test_casting_follows_the_stated_gender_and_rejects_a_mismatched_proposal(sandbox, repos):
    """RoleCast.gender (set by the Script Writer) decides the voice: a female role never gets a male actor or a male placeholder,
    even when its description says nothing and the LLM proposes the wrong actor."""
    from emvoox.contracts import CastingProposal

    seed_registry(sandbox)  # ngan (female), duong (male)
    bible_with(repos, [RoleCast(role_name="Quý", role_type="protagonist", gender="female", description="27 tuổi, sắc sảo"),
                       RoleCast(role_name="Bảo Trân", role_type="supporting", gender="nữ", description="bạn thân"),  # 'nữ' is normalised
                       RoleCast(role_name="Sếp", role_type="antagonist", gender="male", description="45 tuổi")])
    ctx = ctx_for(repos)
    wrong = CastingProposal.model_validate({"assignments": [{"role_name": "Quý", "actor_id": "duong", "reason": "x"}, {"role_name": "Sếp", "actor_id": "duong", "reason": "y"}]})
    ctx.llm.structured = lambda **_: wrong  # type: ignore[method-assign]
    cast = CastingAgent().run(ctx)
    by = {m.role_name: m for m in cast.members}
    assert by["Quý"].actor_id == "ngan" and by["Sếp"].actor_id == "duong"
    from emvoox.providers.tts.catalog import gemini_voice

    assert by["Bảo Trân"].voice_source == "placeholder" and gemini_voice(by["Bảo Trân"].voice_id)["gender"] == "female"
    assert by["Bảo Trân"].actor_id not in repos.registry.load().ids()


def test_named_roles_never_outnumber_the_voice_ips(sandbox, repos):
    """The Script Writer is told the roster size; whatever still exceeds it becomes a background role, and casting gives
    named roles the Voice IPs first."""
    from emvoox.agents.script_writer import ScriptWriterAgent
    from emvoox.casting import over_capacity, roster_capacity, roster_rule_vi
    from emvoox.contracts.production import EpisodeFormat, StoryInput, StoryOverview, StoryRole

    seed_registry(sandbox)  # ngan (female), duong (male)
    cap = roster_capacity(repos.registry.load())
    assert cap == {"female": 1, "male": 1} and "1 diễn viên nữ và 1 diễn viên nam" in roster_rule_vi(cap)
    roles = [RoleCast(role_name="Vy", role_type="supporting", gender="female"), RoleCast(role_name="Mạn", role_type="protagonist", gender="female"),
             RoleCast(role_name="Thần", role_type="antagonist", gender="male"), RoleCast(role_name="Bảo vệ", role_type="minor", gender="male")]
    assert [r.role_name for r in over_capacity(roles, cap)] == ["Vy"]  # the protagonist keeps the only female IP
    assert over_capacity(roles, {"female": 0, "male": 0}) == []  # no roster at all: nothing to enforce
    # through the Script Writer: three named roles written, two Voice IPs available
    ctx = ctx_for(repos)
    story = StoryInput(overview=StoryOverview(title="T"), script="x " * 50, roles=[
        StoryRole(name="Hạ Vy", gender="female", description="Nữ 26 tuổi"), StoryRole(name="Khang", gender="male", description="Nam 31 tuổi"),
        StoryRole(name="Mai", gender="female", description="Nữ 24 tuổi, đồng nghiệp")])
    bible = ScriptWriterAgent().outline(ctx, story, EpisodeFormat(count=3, min_duration_sec=30, max_duration_sec=60))
    assert {r.role_name: r.role_type for r in bible.roles}["Mai"] == "minor" and any("more named" in n for n in ctx.notes)
    assert sum(r.role_type != "minor" for r in bible.roles) == 2
    repos.series.save_bible(bible)
    cast = CastingAgent().run(ctx)
    by = {m.role_name: m for m in cast.members}
    assert by["Hạ Vy"].actor_id == "ngan" and by["Khang"].actor_id == "duong" and by["Mai"].voice_source == "placeholder"
    assert repos.registry.load().ids() == {"ngan", "duong"}
