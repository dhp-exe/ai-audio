"""Scene batching: chunk boundaries, transcripts, multi-speaker requests, manifest-aware assembly and QA."""

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline import naming
from pipeline.chunking import build_transcript, chunk_episode, speaker_label
from pipeline.providers import gemini_tts as gm
from pipeline.providers.base import TtsRequest
from pipeline.schema import CharacterProfile, EpisodeScript, ProviderVoice, VoiceRegistry

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / ".claude/skills"


def _load(name: str, script: str):
    import sys

    spec = importlib.util.spec_from_file_location(name, SKILLS / script)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses in the script look their module up here
    spec.loader.exec_module(mod)
    return mod


def _script(spec: list[tuple[str, list[tuple[str, str]]]]) -> EpisodeScript:
    """spec: [(scene_id, [(character_id|'pause', text), ...]), ...]"""
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


@pytest.fixture
def reg():
    return VoiceRegistry(characters=[
        CharacterProfile(character_id=c, display_name=c.title(), persona="p", voice_description="v", gender=g,
                         providers={"gemini": ProviderVoice(voice_id=v, model_id="gemini-3.1-flash-tts-preview")})
        for c, g, v in (("linh", "female", "Kore"), ("minh-khoi", "male", "Puck"), ("ong-trum", "male", "Algenib"))])


def test_chunk_boundaries():
    s = _script([
        ("sc01", [("linh", "a"), ("linh", "b")]),                                              # one actor
        ("sc02", [("linh", "c"), ("minh-khoi", "d"), ("pause", ""), ("minh-khoi", "e"), ("linh", "f")]),  # pause splits
        ("sc03", [("linh", "g"), ("minh-khoi", "h"), ("ong-trum", "i"), ("linh", "j")]),         # third actor splits
    ])
    chunks = chunk_episode(s)
    assert [(c.chunk_id, c.actors, len(c.lines)) for c in chunks] == [
        ("ep01_sc01_c01", ["linh"], 2),
        ("ep01_sc02_c01", ["linh", "minh-khoi"], 2), ("ep01_sc02_c02", ["minh-khoi", "linh"], 2),
        ("ep01_sc03_c01", ["linh", "minh-khoi"], 2), ("ep01_sc03_c02", ["ong-trum", "linh"], 2),
    ]
    assert chunks[1].pause_after_ms == 400 and chunks[0].line_ids == ["ep01_sc01_l001", "ep01_sc01_l002"]


def test_transcript_and_labels(reg):
    assert speaker_label("minh-khoi") == "MinhKhoi" and speaker_label("ngan") == "Ngan"
    s = _script([("sc01", [("linh", "Anh đi đi."), ("minh-khoi", "[sighs] Anh nợ em 200k.")])])
    chunk = chunk_episode(s)[0]
    header, text, speakers = build_transcript(chunk, reg, "gemini-3.1-flash-tts-preview")
    assert speakers == (("Linh", "Kore"), ("MinhKhoi", "Puck"))
    assert text == "Linh: Anh đi đi.\nMinhKhoi: Anh nợ em hai trăm nghìn."  # tags stripped, numbers normalized
    assert "KHÔNG đọc tên người nói" in header and "1. Linh:" in header and "2. MinhKhoi:" in header and "thở dài" in header
    # single actor: no labels
    solo = chunk_episode(_script([("sc01", [("linh", "Một."), ("linh", "Hai.")])]))[0]
    header, text, speakers = build_transcript(solo, reg, "m")
    assert text == "Một.\nHai." and speakers == (("Linh", "Kore"),) and "cùng một nhân vật" in header


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

    import sys
    from types import ModuleType
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
    # hash covers the speakers
    other = TtsRequest(provider="gemini", model_id="m", voice_id="ep01_sc01_c01", text="Linh: a\nMinhKhoi: b", settings={"style": "H"},
                       speakers=(("Linh", "Kore"), ("MinhKhoi", "Orus")))
    assert other.content_hash() != req.content_hash() and req.as_dict()["speakers"] == [["Linh", "Kore"], ["MinhKhoi", "Puck"]]


def test_plan_chunks_and_manifest(reg, tmp_path, monkeypatch):
    monkeypatch.setattr(naming, "SERIES_DIR", tmp_path / "series")
    gv = _load("generate_voice", "generate-voice/scripts/generate_voice.py")
    s = _script([("sc01", [("linh", "a"), ("minh-khoi", "b"), ("ong-trum", "c")])])
    units = gv.plan_chunks(s, reg, None, None, True)
    assert [u.id for u in units] == ["ep01_sc01_c01", "ep01_sc01_c02"]
    assert units[0].out.name == "ep01_sc01_c01_chunk.wav" and units[0].req.speakers == (("Linh", "Kore"), ("MinhKhoi", "Puck"))
    assert units[1].req.speakers == (("OngTrum", "Algenib"),) and units[1].req.voice_id == "Algenib"
    only = gv.plan_chunks(s, reg, {"ep01_sc01_l003"}, None, True)
    assert [u.id for u in only] == ["ep01_sc01_c02"]
    m = json.loads(gv.write_manifest(s, "scene", units).read_text())
    assert m["batching"] == "scene" and m["units"][0]["line_ids"] == ["ep01_sc01_l001", "ep01_sc01_l002"]
    assert gv.resolve_batching("auto", "gemini") == "scene" and gv.resolve_batching("auto", "elevenlabs") == "line"
    with pytest.raises(SystemExit):
        gv.resolve_batching("scene", "elevenlabs")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
def test_timeline_and_qa_from_manifest(tmp_path):
    asm = _load("assemble_audio", "assemble-audio/scripts/assemble_audio.py")
    qa = _load("qa_audio", "qa-audio/scripts/qa_audio.py")
    s = _script([("sc01", [("linh", "a"), ("minh-khoi", "b")]), ("sc02", [("linh", "c"), ("pause", ""), ("linh", "d")])])
    stems = tmp_path / "stems"
    stems.mkdir()
    units = [{"id": "ep01_sc01_c01", "path": "ep01_sc01_c01_chunk.wav", "scene_id": "sc01", "line_ids": ["ep01_sc01_l001", "ep01_sc01_l002"], "actors": ["linh", "minh-khoi"], "pause_after_ms": 450},
             {"id": "ep01_sc02_c01", "path": "ep01_sc02_c01_chunk.wav", "scene_id": "sc02", "line_ids": ["ep01_sc02_l001"], "actors": ["linh"], "pause_after_ms": 400},
             {"id": "ep01_sc02_c02", "path": "ep01_sc02_c02_chunk.wav", "scene_id": "sc02", "line_ids": ["ep01_sc02_l003"], "actors": ["linh"], "pause_after_ms": 400}]
    (stems / "render.json").write_text(json.dumps({"batching": "scene", "units": units}))
    for u in units:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "1", "-ac", "1", str(stems / u["path"])], check=True)
    tl = asm.build_timeline(s, stems, padding_ms=400, padding_min=300, padding_max=500, use_director_pauses=True, scene_gap_ms=800)
    clips = [(c.kind, c.line_id, c.duration_ms) for c in tl.clips]
    assert [c for c in clips if c[0] == "stem"] == [("stem", "ep01_sc01_c01", 1000), ("stem", "ep01_sc02_c01", 1000), ("stem", "ep01_sc02_c02", 1000)]
    # chunk gap 450 (clamped director pause), scene gap 800, the pause line's 1200 ms, then the 500 ms tail
    assert [c[2] for c in clips if c[0] == "silence"] == [450, 800, 400, 1200, 500]
    assert qa.check_stems_complete(s, stems) == {"ok": True, "missing": [], "batching": "scene", "units": 3}
    (stems / "ep01_sc02_c02_chunk.wav").unlink()
    assert qa.check_stems_complete(s, stems)["missing"] == ["ep01_sc02_c02"]
    # naming helpers
    assert naming.chunk_stem_name_from_id("ep01_sc02_c03") == "ep01_sc02_c03_chunk.wav"
    with pytest.raises(ValueError):
        naming.chunk_stem_name_from_id("ep01_sc02_l003")
