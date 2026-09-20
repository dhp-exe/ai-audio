"""Unit tests for provider mapping and the two adapters (fake clients, no network)."""

import base64
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.providers import PROVIDER_NAMES, default_concurrency, get_provider
from pipeline.providers import elevenlabs as el
from pipeline.providers import gemini_tts as gm
from pipeline.providers.base import ProviderError, TtsRequest
from pipeline.providers.catalog import GEMINI_VOICES, catalog, gemini_voice, model_ids
from pipeline.providers.mapping import gemini_style, settings_for_line, text_for_provider
from pipeline.schema import Emotion, Line, LineType

ROOT = Path(__file__).resolve().parents[1]
HAS_FFMPEG = subprocess.run(["which", "ffmpeg"], capture_output=True).returncode == 0


def _line(**kw) -> Line:
    base = dict(line_id="ep01_sc01_l001", type=LineType.dialogue, character_id="linh", text="Anh đi đi.",
                tts_text="[sighs] Anh đi đi.", emotion=Emotion.sad, emotional_intensity=5,
                acoustic_direction="", pace="normal", volume="normal", pause_after_ms=400)
    base.update(kw)
    return Line(**base)


# ---- catalog ------------------------------------------------------------------------------


def test_catalog_two_engines_only():
    assert PROVIDER_NAMES == ("elevenlabs", "gemini")
    c = catalog()
    assert [p["id"] for p in c["providers"]] == ["elevenlabs", "gemini"]
    assert len(GEMINI_VOICES) == 30 and gemini_voice("leda")["gender"] == "female" and gemini_voice("nope") is None
    assert "eleven_v3" in model_ids("elevenlabs") and "gemini-2.5-flash-preview-tts" in model_ids("gemini")
    assert default_concurrency("gemini") == 1 and default_concurrency("elevenlabs") == 2
    with pytest.raises(ValueError):
        get_provider("minimax")


# ---- mapping ------------------------------------------------------------------------------


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


def test_gemini_style_direction():
    ln = _line(emotion=Emotion.desperate, emotional_intensity=9, pace="slow", volume="whisper", type=LineType.monologue,
               tts_text="[sighs] Tôi đã quên.", acoustic_direction="mic gần, run giọng")
    s = settings_for_line(ln, "gemini", "gemini-2.5-flash-preview-tts")
    style = s["style"]
    assert style == gemini_style(ln)
    for word in ("tuyệt vọng", "rất mạnh", "độc thoại nội tâm", "nói chậm", "thì thầm", "thở dài", "mic gần, run giọng"):
        assert word in style
    assert "[" not in text_for_provider(ln, "gemini", "gemini-2.5-flash-preview-tts")


def test_unknown_provider_rejected():
    with pytest.raises(ValueError):
        settings_for_line(_line(), "minimax", "speech-02-hd")


def test_text_tags_kept_on_v3_stripped_elsewhere():
    ln = _line(tts_text="[sighs] Anh nợ em 200k.")
    assert text_for_provider(ln, "elevenlabs", "eleven_v3").startswith("[sighs] Anh nợ em hai trăm nghìn")
    assert text_for_provider(ln, "elevenlabs", "eleven_multilingual_v2").startswith("Anh nợ em hai trăm nghìn")
    assert "[" not in text_for_provider(ln, "gemini", "gemini-2.5-flash-preview-tts")


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


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg")
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


# ---- Gemini TTS adapter with a fake client ----------------------------------------------


class FakeGenaiError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


@pytest.fixture
def fake_gemini(monkeypatch):
    import sys
    from types import ModuleType

    calls: list[dict] = []
    state = {"fail_first": 0}

    def generate_content(*, model, contents, config):
        calls.append({"model": model, "contents": contents, "voice": config.speech_config.voice_config.prebuilt_voice_config.voice_name})
        if state["fail_first"] > 0:
            state["fail_first"] -= 1
            raise FakeGenaiError(429, "rate limited")
        pcm = b"\x00\x00" * 2400  # 0.1 s of silence at 24 kHz
        part = SimpleNamespace(inline_data=SimpleNamespace(data=pcm))
        cand = SimpleNamespace(content=SimpleNamespace(parts=[part]), finish_reason="STOP")
        return SimpleNamespace(candidates=[cand], prompt_feedback=None, usage_metadata=SimpleNamespace(prompt_token_count=12, candidates_token_count=40))

    class Cfg:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    types_mod = ModuleType("google.genai.types")
    types_mod.GenerateContentConfig = Cfg
    types_mod.SpeechConfig = Cfg
    types_mod.VoiceConfig = Cfg
    types_mod.PrebuiltVoiceConfig = Cfg
    err_mod = ModuleType("google.genai.errors")
    err_mod.APIError = FakeGenaiError
    genai_mod = ModuleType("google.genai")
    genai_mod.types, genai_mod.errors = types_mod, err_mod
    google_mod = ModuleType("google")
    google_mod.genai = genai_mod
    for name, mod in (("google", google_mod), ("google.genai", genai_mod), ("google.genai.types", types_mod), ("google.genai.errors", err_mod)):
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setattr(gm.time, "sleep", lambda s: None)
    prov = gm.GeminiTtsProvider(api_key="x")
    prov._client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    return prov, calls, state


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg")
def test_gemini_prompt_voice_and_pcm(fake_gemini, tmp_path):
    prov, calls, state = fake_gemini
    state["fail_first"] = 1  # one 429, then success
    req = TtsRequest(provider="gemini", model_id="gemini-2.5-flash-preview-tts", voice_id="Leda", text="Xin chào.",
                     settings={"style": "Nói tiếng Việt, giọng buồn"})
    out = tmp_path / "ep01_sc01_l001_ngan_dialogue.wav"
    info = prov.synthesize(req, out)
    assert len(calls) == 2 and calls[-1]["voice"] == "Leda" and calls[-1]["model"] == "gemini-2.5-flash-preview-tts"
    assert calls[-1]["contents"] == "Nói tiếng Việt, giọng buồn:\nXin chào."
    assert info["tokens_out"] == 40 and info["characters_billed"] == len("Xin chào.") and 80 <= info["duration_ms"] <= 120
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=sample_rate,channels", "-of", "csv=p=0", str(out)],
                           capture_output=True, text=True).stdout.strip()
    assert probe == "44100,1"


def test_gemini_non_retryable_error(fake_gemini, tmp_path):
    prov, calls, state = fake_gemini

    def boom(**kw):
        raise FakeGenaiError(400, "bad voice")

    prov._client = SimpleNamespace(models=SimpleNamespace(generate_content=boom))
    with pytest.raises(ProviderError) as e:
        prov.synthesize(TtsRequest(provider="gemini", model_id="m", voice_id="Nope", text="x"), tmp_path / "x.wav")
    assert e.value.status == 400 and not e.value.retryable


def test_gemini_prompt_without_style():
    assert gm.build_prompt(None, "Xin chào") == "Xin chào" and gm.build_prompt("giọng vui.", "A") == "giọng vui:\nA"


def test_gemini_daily_quota_fails_fast(fake_gemini, tmp_path):
    prov, calls, state = fake_gemini
    details = {"error": {"code": 429, "details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
            {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier", "quotaValue": "10", "quotaDimensions": {"model": "gemini-2.5-flash-tts"}}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "26s"}]}}

    def boom(**kw):
        err = FakeGenaiError(429, "You exceeded your current quota")
        err.details = details
        raise err

    prov._client = SimpleNamespace(models=SimpleNamespace(generate_content=boom))
    with pytest.raises(ProviderError) as e:
        prov.synthesize(TtsRequest(provider="gemini", model_id="gemini-2.5-flash-preview-tts", voice_id="Leda", text="x"), tmp_path / "x.wav")
    assert e.value.status == 429 and not e.value.retryable and "10 requests/day" in str(e.value) and "gemini-2.5-flash-tts" in str(e.value)
    assert gm.quota_violation(boom.__closure__ and FakeGenaiError(429, "x")) is None
    assert gm.retry_delay(SimpleNamespace(details=details)) == 26.0
