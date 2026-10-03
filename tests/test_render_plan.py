"""Delivery Compile + Render Plan: chunk boundaries, transcripts, mixed engines, retries, and the Gemini multi-speaker request."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from emvoox import paths
from emvoox.agents import AgentContext, DirectorAgent
from emvoox.config import get_settings
from emvoox.contracts import CastMember, DirectedConversationUnits, EnginePolicy, EngineRef, EpisodeScript, ResolvedCast, RunParams
from emvoox.delivery.plan import build_transcript, chunk_episode, speaker_label
from emvoox.providers.llm import LlmClient
from emvoox.providers.llm.mock import MockLlm
from emvoox.providers.tts import gemini as gm
from emvoox.providers.tts.base import TtsRequest
from emvoox.telemetry.ledger import Ledger


def make_script(spec: list[tuple[str, list[tuple[str, str]]]]) -> EpisodeScript:
    """spec: [(scene_id, [(character_id | 'pause', text), ...]), ...]"""
    scenes = []
    for sc, lines in spec:
        out = []
        for i, (cid, text) in enumerate(lines, start=1):
            base = {"line_id": f"ep01_{sc}_l{i:03d}", "emotion": "neutral", "emotional_intensity": 3, "acoustic_direction": "",
                    "pace": "normal", "volume": "normal", "pause_after_ms": 400}
            if cid == "pause":
                out.append({**base, "type": "pause", "character_id": "linh", "text": "", "tts_text": "", "pause_after_ms": 1200})
            else:
                out.append({**base, "type": "dialogue", "character_id": cid, "role_name": cid.title(), "text": text, "tts_text": text})
        scenes.append({"scene_id": sc, "title": sc, "location": "x", "time_of_day": "night", "lines": out})
    return EpisodeScript.model_validate({"series_id": "t", "episode_number": 1, "title": "t", "logline": "l", "cliffhanger": "c", "target_duration_sec": 60,
                                         "characters_used": sorted({c for _, ls in spec for c, _ in ls if c != "pause"}), "scenes": scenes})


def make_cast(engines: dict[str, tuple[str, str, str]], batching: str = "auto") -> ResolvedCast:
    """engines: actor -> (provider, model, voice)"""
    members = [CastMember(role_name=a.title(), role_type="protagonist" if i == 0 else "supporting", actor_id=a, display_name=a.title(),
                          provider=p, model_id=m, voice_id=v) for i, (a, (p, m, v)) in enumerate(engines.items())]
    return ResolvedCast(series_id="t", engine_policy=EnginePolicy(default=EngineRef(provider="gemini"), batching=batching),  # type: ignore[arg-type]
                        protagonist_id=members[0].actor_id, members=members)


GEMINI = "gemini-3.1-flash-tts-preview"
ALL_GEMINI = {"linh": ("gemini", GEMINI, "Kore"), "minh-khoi": ("gemini", GEMINI, "Puck"), "ong-trum": ("gemini", GEMINI, "Algenib")}


@pytest.fixture
def ctx(repos):
    return AgentContext(settings=get_settings(), repos=repos, llm=LlmClient(MockLlm(), Ledger(repos.telemetry)), ledger=Ledger(repos.telemetry),
                        params=RunParams(series_id="t", tts_provider="gemini"))


def test_chunk_boundaries():
    s = make_script([
        ("sc01", [("linh", "a"), ("linh", "b")]),                                                         # one actor
        ("sc02", [("linh", "c"), ("minh-khoi", "d"), ("pause", ""), ("minh-khoi", "e"), ("linh", "f")]),  # pause splits
        ("sc03", [("linh", "g"), ("minh-khoi", "h"), ("ong-trum", "i"), ("linh", "j")]),                  # third actor splits
    ])
    chunks = chunk_episode(s)
    assert [(c.chunk_id, c.actors, len(c.lines)) for c in chunks] == [
        ("ep01_sc01_c01", ["linh"], 2),
        ("ep01_sc02_c01", ["linh", "minh-khoi"], 2), ("ep01_sc02_c02", ["minh-khoi", "linh"], 2),
        ("ep01_sc03_c01", ["linh", "minh-khoi"], 2), ("ep01_sc03_c02", ["ong-trum", "linh"], 2),
    ]
    assert chunks[1].pause_after_ms == 400 and chunks[0].line_ids == ["ep01_sc01_l001", "ep01_sc01_l002"]
    # a line that cannot be batched closes the chunk and is left out
    only_linh = chunk_episode(s, can_batch=lambda ln: ln.character_id == "linh")
    assert [c.line_ids for c in only_linh][:2] == [["ep01_sc01_l001", "ep01_sc01_l002"], ["ep01_sc02_l001"]]


def test_transcript_and_labels():
    cast = make_cast(ALL_GEMINI)
    assert speaker_label("minh-khoi") == "MinhKhoi" and speaker_label("ngan") == "Ngan"
    s = make_script([("sc01", [("linh", "Anh đi đi."), ("minh-khoi", "[sighs] Anh nợ em 200k.")])])
    header, text, speakers = build_transcript(chunk_episode(s)[0], cast, GEMINI, descriptions={"linh": "nữ, khàn"})
    assert speakers == (("Linh", "Kore"), ("MinhKhoi", "Puck"))
    assert text == "Linh: Anh đi đi.\nMinhKhoi: Anh nợ em hai trăm nghìn."  # tags stripped, numbers normalized
    assert "KHÔNG đọc tên người nói" in header and "1. Linh:" in header and "2. MinhKhoi:" in header and "thở dài" in header and "nữ, khàn" in header
    header, text, speakers = build_transcript(chunk_episode(make_script([("sc01", [("linh", "Một."), ("linh", "Hai.")])]))[0], cast, "m")
    assert text == "Một.\nHai." and speakers == (("Linh", "Kore"),) and "cùng một nhân vật" in header


def test_render_plan_mixed_engines_line_mode_and_attempts(ctx):
    d = DirectorAgent()
    s = make_script([("sc01", [("linh", "a b c"), ("minh-khoi", "d e"), ("ong-trum", "f g"), ("linh", "h")])])
    cast = make_cast({"linh": ("gemini", GEMINI, "Kore"), "minh-khoi": ("gemini", GEMINI, "Puck"), "ong-trum": ("elevenlabs", "eleven_v3", "u5")})
    units = d.delivery_compile(ctx, s, cast)
    plan, batching = d.render_plan(ctx, s, cast, units)
    assert batching == "mixed"
    assert [(r.id, r.kind, r.provider) for r in plan] == [("ep01_sc01_c01", "conversation", "gemini"), ("ep01_sc01_l003", "line", "elevenlabs"),
                                                          ("ep01_sc01_c02", "conversation", "gemini")]
    assert plan[0].speaker_voices == [("Linh", "Kore"), ("MinhKhoi", "Puck")] and plan[1].stem == "ep01_sc01_l003_ong-trum_dialogue.wav"
    assert plan[1].settings["stability"] == 0.5 and plan[1].text == "f g."  # normalized: terminal punctuation added
    # retry: the first chunk is split into lines with attempt 1, the v3 line gets more stable settings
    plan2, _ = d.render_plan(ctx, s, cast, units, line_mode={"ep01_sc01_c01"}, attempts={"ep01_sc01_c01": 1, "ep01_sc01_l003": 2})
    ids = [(r.id, r.kind, r.attempt) for r in plan2]
    assert ids[:3] == [("ep01_sc01_l001", "line", 1), ("ep01_sc01_l002", "line", 1), ("ep01_sc01_l003", "line", 2)]
    assert "không bỏ sót" in plan2[0].settings["style"] and plan2[2].settings["stability"] == 1.0
    # line batching renders everything per line; the whole thing validates as the Director's contract
    line_cast = make_cast(ALL_GEMINI, batching="line")
    plan3, b3 = d.render_plan(ctx, s, line_cast, d.delivery_compile(ctx, s, line_cast))
    assert b3 == "line" and len(plan3) == 4
    DirectedConversationUnits(series_id="t", episode_number=1, title="t", target_duration_sec=60, units=units, render_plan=plan)


def test_directed_contract_rejects_gaps():
    units = [{"unit_id": "ep01_sc01_l001", "scene_id": "sc01", "order": 1, "type": "dialogue", "speaker_id": "linh", "text": "a", "tts_text": "a",
              "provider": "gemini", "model_id": GEMINI, "voice_id": "Kore"},
             {"unit_id": "ep01_sc01_l002", "scene_id": "sc01", "order": 2, "type": "dialogue", "speaker_id": "linh", "text": "b", "tts_text": "b",
              "provider": "gemini", "model_id": GEMINI, "voice_id": "Kore"}]
    plan = [{"id": "ep01_sc01_l001", "kind": "line", "scene_id": "sc01", "unit_ids": ["ep01_sc01_l001"], "speakers": ["linh"], "provider": "gemini",
             "model_id": GEMINI, "voice_id": "Kore", "text": "a", "stem": "x.wav"}]
    with pytest.raises(ValueError, match="cover every spoken unit"):
        DirectedConversationUnits.model_validate({"series_id": "t", "episode_number": 1, "title": "t", "target_duration_sec": 60, "units": units,
                                                  "render_plan": plan})
    units[1]["voice_id"] = ""
    with pytest.raises(ValueError, match="voice_id must be resolved"):
        DirectedConversationUnits.model_validate({"series_id": "t", "episode_number": 1, "title": "t", "target_duration_sec": 60, "units": units,
                                                  "render_plan": plan})


def test_gemini_multi_speaker_request(monkeypatch, tmp_path):
    captured = {}

    class Cfg:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    def generate_content(*, model, contents, config):
        captured.update(model=model, contents=contents, config=config)
        part = SimpleNamespace(inline_data=SimpleNamespace(data=b"\x00\x00" * 2400))
        return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]), finish_reason="STOP")],
                               prompt_feedback=None, usage_metadata=SimpleNamespace(prompt_token_count=1, candidates_token_count=2))

    types_mod = ModuleType("google.genai.types")
    for n in ("GenerateContentConfig", "SpeechConfig", "VoiceConfig", "PrebuiltVoiceConfig", "MultiSpeakerVoiceConfig", "SpeakerVoiceConfig"):
        setattr(types_mod, n, Cfg)
    err_mod = ModuleType("google.genai.errors")
    err_mod.APIError = type("APIError", (Exception,), {})
    genai_mod = ModuleType("google.genai")
    genai_mod.types, genai_mod.errors = types_mod, err_mod
    google_mod = ModuleType("google")
    google_mod.genai = genai_mod
    for n, m in (("google", google_mod), ("google.genai", genai_mod), ("google.genai.types", types_mod), ("google.genai.errors", err_mod)):
        monkeypatch.setitem(sys.modules, n, m)
    monkeypatch.setattr(gm, "to_stem_wav", lambda *a, **k: Path(a[1]).write_bytes(b"RIFF"))
    monkeypatch.setattr(gm, "duration_ms", lambda p: 100)
    prov = gm.GeminiTtsProvider(api_key="x")
    prov._client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    req = TtsRequest(provider="gemini", model_id="m", voice_id="ep01_sc01_c01", text="Linh: a\nMinhKhoi: b", settings={"style": "H"},
                     speakers=(("Linh", "Kore"), ("MinhKhoi", "Puck")))
    prov.synthesize(req, tmp_path / "c.wav")
    cfgs = captured["config"].speech_config.multi_speaker_voice_config.speaker_voice_configs
    assert [(c.speaker, c.voice_config.prebuilt_voice_config.voice_name) for c in cfgs] == [("Linh", "Kore"), ("MinhKhoi", "Puck")]
    assert captured["contents"] == "H:\nLinh: a\nMinhKhoi: b"
    other = TtsRequest(provider="gemini", model_id="m", voice_id="ep01_sc01_c01", text="Linh: a\nMinhKhoi: b", settings={"style": "H"},
                       speakers=(("Linh", "Kore"), ("MinhKhoi", "Orus")))
    assert other.content_hash() != req.content_hash() and req.as_dict()["speakers"] == [["Linh", "Kore"], ["MinhKhoi", "Puck"]]
    # the retry attempt is part of the cache key, so a QA retry really re-renders
    assert TtsRequest(**{**req.__dict__, "attempt": 1}).content_hash() != req.content_hash()


def test_stem_naming():
    assert paths.chunk_stem_name_from_id("ep01_sc02_c03") == "ep01_sc02_c03_chunk.wav"
    with pytest.raises(ValueError):
        paths.chunk_stem_name_from_id("ep01_sc02_l003")
    with pytest.raises(ValueError):
        paths.series_root("bad/id")


def test_wavespeed_gemini_tts_batches_dialogue_as_turns(ctx):
    """WaveSpeed's Gemini TTS is billed per request, so two-speaker runs go out as one dialogue request with per-turn direction."""
    g38 = "google/gemini-3.8-flash/text-to-speech"
    d = DirectorAgent()
    s = make_script([("sc01", [("linh", "a b c"), ("minh-khoi", "d e"), ("linh", "h")])])
    cast = make_cast({"linh": ("wavespeed", g38, "Kore"), "minh-khoi": ("wavespeed", g38, "Puck")})
    units = d.delivery_compile(ctx, s, cast)
    assert "giọng" in units[0].settings["style"] and "[" not in units[0].tts_text
    plan, batching = d.render_plan(ctx, s, cast, units)
    assert batching == "scene" and [(r.id, r.kind, r.provider, r.model_id) for r in plan] == [("ep01_sc01_c01", "conversation", "wavespeed", g38)]
    assert plan[0].speaker_voices == [("Linh", "Kore"), ("MinhKhoi", "Puck")] and len(plan[0].settings["turn_styles"]) == 3
    assert len(plan[0].settings["style"]) < 200  # the long per-line header is not sent (billed, capped at 2,000 characters)
    # the same cast on WaveSpeed's ElevenLabs endpoint is rendered line by line
    el = make_cast({"linh": ("wavespeed", "elevenlabs/eleven-v3", "x"), "minh-khoi": ("wavespeed", "elevenlabs/eleven-v3", "y")})
    plan2, b2 = d.render_plan(ctx, s, el, d.delivery_compile(ctx, s, el))
    assert b2 == "line" and len(plan2) == 3
    # a QA retry splits the chunk into lines that carry the retry direction
    plan3, _ = d.render_plan(ctx, s, cast, units, line_mode={"ep01_sc01_c01"}, attempts={"ep01_sc01_c01": 1})
    assert [r.kind for r in plan3] == ["line"] * 3 and "không bỏ sót" in plan3[0].settings["style"]
