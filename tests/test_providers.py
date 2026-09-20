"""Unit tests for provider mapping and the ElevenLabs adapter (fake client, no network)."""

import base64
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.providers import elevenlabs as el
from pipeline.providers.base import ProviderError, TtsRequest
from pipeline.providers.mapping import settings_for_line, text_for_provider
from pipeline.schema import Emotion, Line, LineType

ROOT = Path(__file__).resolve().parents[1]


def _line(**kw) -> Line:
    base = dict(line_id="ep01_sc01_l001", type=LineType.dialogue, character_id="linh", text="Anh đi đi.",
                tts_text="[sighs] Anh đi đi.", emotion=Emotion.sad, emotional_intensity=5,
                acoustic_direction="", pace="normal", volume="normal", pause_after_ms=400)
    base.update(kw)
    return Line(**base)


@pytest.mark.parametrize("intensity,stability", [(2, 0.5), (5, 0.5), (7, 0.0), (10, 0.0)])
def test_v3_stability_is_discrete(intensity, stability):
    s = settings_for_line(_line(emotional_intensity=intensity), "elevenlabs", "eleven_v3")
    assert s["stability"] == stability and s["stability"] in (0.0, 0.5, 1.0)


def test_v2_stability_continuous_and_monologue_bias():
    d = settings_for_line(_line(emotional_intensity=9), "elevenlabs", "eleven_multilingual_v2")
    m = settings_for_line(_line(emotional_intensity=9, type=LineType.monologue), "elevenlabs", "eleven_multilingual_v2")
    assert 0.3 <= d["stability"] <= 0.8 and m["stability"] <= d["stability"] and m["style"] > d["style"]


def test_registry_defaults_win():
    s = settings_for_line(_line(), "elevenlabs", "eleven_v3", {"stability": 1.0})
    assert s["stability"] == 1.0


def test_minimax_settings():
    s = settings_for_line(_line(emotion=Emotion.desperate, pace="slow", volume="shout"), "minimax", "speech-02-hd")
    assert s == {"emotion": "sad", "speed": 0.85, "vol": 1.6}


def test_text_tags_kept_on_v3_stripped_elsewhere():
    ln = _line(tts_text="[sighs] Anh nợ em 200k.")
    assert text_for_provider(ln, "elevenlabs", "eleven_v3").startswith("[sighs] Anh nợ em hai trăm nghìn")
    assert text_for_provider(ln, "elevenlabs", "eleven_multilingual_v2").startswith("Anh nợ em hai trăm nghìn")
    assert "[" not in text_for_provider(ln, "minimax", "speech-02-hd")


def test_monologue_gets_introspective_tag_on_v3():
    ln = _line(type=LineType.monologue, tts_text="Tôi đã quên.")
    assert text_for_provider(ln, "elevenlabs", "eleven_v3").startswith("[introspective]")


# ---- ElevenLabs adapter with a fake client ----------------------------------------------


def _wav_bytes(tmp_path: Path) -> bytes:
    p = tmp_path / "src.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=22050",
                    "-t", "0.3", "-ac", "1", str(p)], check=True)
    return p.read_bytes()


class FakeApiError(Exception):
    def __init__(self, status_code, body):
        self.status_code, self.body = status_code, body


@pytest.fixture
def fake_el(monkeypatch, tmp_path):
    """Patch the SDK imports used inside synthesize()."""
    import sys
    from types import ModuleType

    audio = _wav_bytes(tmp_path)
    calls = []

    def convert_with_timestamps(voice_id, *, output_format, **kw):
        calls.append(output_format)
        if output_format == "wav_44100":
            raise FakeApiError(400, {"detail": {"status": "invalid_output_format", "message": "output_format not allowed on this tier"}})
        al = SimpleNamespace(characters=list(kw["text"]), character_start_times_seconds=[0.0] * len(kw["text"]),
                             character_end_times_seconds=[0.1] * len(kw["text"]))
        return SimpleNamespace(audio_base_64=base64.b64encode(audio).decode(), alignment=al)

    client = SimpleNamespace(text_to_speech=SimpleNamespace(convert_with_timestamps=convert_with_timestamps))
    vs_mod = ModuleType("elevenlabs")
    vs_mod.VoiceSettings = lambda **kw: kw
    err_mod = ModuleType("elevenlabs.core.api_error")
    err_mod.ApiError = FakeApiError
    core_mod = ModuleType("elevenlabs.core")
    monkeypatch.setitem(sys.modules, "elevenlabs", vs_mod)
    monkeypatch.setitem(sys.modules, "elevenlabs.core", core_mod)
    monkeypatch.setitem(sys.modules, "elevenlabs.core.api_error", err_mod)
    prov = el.ElevenLabsProvider(api_key="x")
    prov._client = client
    return prov, calls


@pytest.mark.skipif(subprocess.run(["which", "ffmpeg"], capture_output=True).returncode != 0, reason="ffmpeg")
def test_format_fallback_and_alignment(fake_el, tmp_path):
    prov, calls = fake_el
    req = TtsRequest(provider="elevenlabs", model_id="eleven_v3", voice_id="v", text="Xin chào", settings={"stability": 0.5})
    out = tmp_path / "ep01_sc01_l001_linh_dialogue.wav"
    info = prov.synthesize(req, out)
    assert calls == ["wav_44100", "mp3_44100_128"]
    assert info["output_format"] == "mp3_44100_128" and info["duration_ms"] > 0
    assert len(info["alignment"]["characters"]) == len("Xin chào")
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=sample_rate,channels", "-of", "csv=p=0", str(out)],
                           capture_output=True, text=True).stdout.strip()
    assert probe == "44100,1"
    # second call sticks to the fallback format
    prov.synthesize(req, out)
    assert calls[-1] == "mp3_44100_128"


def test_language_code_only_for_enforcing_models():
    assert "eleven_v3" not in el.LANGUAGE_ENFORCING_MODELS and "eleven_flash_v2_5" in el.LANGUAGE_ENFORCING_MODELS


def test_content_hash_ignores_prosody_context():
    a = TtsRequest(provider="elevenlabs", model_id="m", voice_id="v", text="t", settings={"a": 1}, previous_text="x")
    b = TtsRequest(provider="elevenlabs", model_id="m", voice_id="v", text="t", settings={"a": 1}, next_text="y")
    assert a.content_hash() == b.content_hash()
    assert a.content_hash() != TtsRequest(provider="elevenlabs", model_id="m", voice_id="v", text="t2", settings={"a": 1}).content_hash()
