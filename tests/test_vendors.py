"""Vendor adapters against fake HTTP transports (WaveSpeed TTS + LLM gateway), cost estimates and the ledger."""

from __future__ import annotations

import json
import socket
import wave
from io import BytesIO

import httpx
import pytest
from conftest import needs_ffmpeg
from pydantic import BaseModel

from emvoox.providers.llm.base import LlmSchemaError
from emvoox.providers.llm.openai_compat import OpenAICompatLlm
from emvoox.providers.tts.base import ProviderError, TtsRequest
from emvoox.providers.tts.wavespeed import WaveSpeedClient, WaveSpeedTtsProvider, build_body
from emvoox.telemetry import pricing
from emvoox.telemetry.usage import normalize


def _wav(seconds: float = 0.3) -> bytes:
    buf = BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x10" * int(24000 * seconds))
    return buf.getvalue()


def test_network_is_blocked_in_tests():
    with pytest.raises(RuntimeError, match="network"):
        socket.create_connection(("api.wavespeed.ai", 443), timeout=1)


def test_wavespeed_body_per_model_family():
    v3 = TtsRequest(provider="wavespeed", model_id="elevenlabs/eleven-v3", voice_id="pvc123", text="[sighs] Anh đi đi.",
                    settings={"stability": 0.0, "similarity_boost": 0.6, "style": "x"})
    assert build_body(v3) == {"text": "[sighs] Anh đi đi.", "voice_id": "pvc123", "stability": 0.0}
    mm = TtsRequest(provider="wavespeed", model_id="minimax/speech-2.6-hd", voice_id="clone-1", text="A.",
                    settings={"emotion": "tender", "speed": 0.9, "volume": 0.8, "pitch": 0})
    assert build_body(mm) == {"text": "A.", "voice_id": "clone-1", "speed": 0.9, "volume": 0.8, "pitch": 0}  # unsupported emotion dropped


@needs_ffmpeg
def test_wavespeed_submit_poll_download(tmp_path, monkeypatch):
    monkeypatch.setattr("emvoox.providers.tts.wavespeed.POLL_INTERVAL_S", 0.0)
    monkeypatch.setattr("time.sleep", lambda s: None)
    seen: list[str] = []
    polls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(f"{req.method} {req.url.path}")
        if req.url.host == "api.wavespeed.ai":
            assert req.headers["authorization"] == "Bearer ws-key"
        else:  # the audio URL on the CDN gets no API key
            assert "authorization" not in req.headers
        if req.method == "POST":
            body = json.loads(req.content)
            assert body["voice_id"] == "pvc123" and body["text"] == "Xin chào."
            return httpx.Response(200, json={"code": 200, "data": {"id": "task-1", "status": "created", "outputs": []}})
        if req.url.path.endswith("/result"):
            polls["n"] += 1
            if polls["n"] < 2:
                return httpx.Response(200, json={"data": {"id": "task-1", "status": "processing", "outputs": []}})
            return httpx.Response(200, json={"data": {"id": "task-1", "status": "completed", "outputs": ["https://cdn.example/out.wav"]}})
        return httpx.Response(200, content=_wav())

    client = WaveSpeedClient("ws-key", client=httpx.Client(transport=httpx.MockTransport(handler)))
    out = tmp_path / "stem.wav"
    info = WaveSpeedTtsProvider(client=client).synthesize(
        TtsRequest(provider="wavespeed", model_id="elevenlabs/eleven-v3", voice_id="pvc123", text="Xin chào."), out)
    assert seen[0] == "POST /api/v3/elevenlabs/eleven-v3" and seen.count("GET /api/v3/predictions/task-1/result") == 2
    assert info["task_id"] == "task-1" and 250 <= info["duration_ms"] <= 350 and info["characters_billed"] == len("Xin chào.")
    with wave.open(str(out)) as w:
        assert (w.getframerate(), w.getnchannels()) == (44100, 1)


def test_wavespeed_never_retries_a_submission_lost_in_transit():
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("dropped", request=req)

    client = WaveSpeedClient("k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderError, match="not retried"):
        client.submit("elevenlabs/eleven-v3", {"text": "a", "voice_id": "v"})
    assert calls["n"] == 1


def test_wavespeed_retries_rejected_submissions_and_reports_failures(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    answers = iter([httpx.Response(429, text="slow down"), httpx.Response(200, json={"data": {"id": "t2"}})])
    client = WaveSpeedClient("k", client=httpx.Client(transport=httpx.MockTransport(lambda r: next(answers))))
    assert client.submit("minimax/speech-2.6-hd", {"text": "a", "voice_id": "v"}) == "t2"
    failing = WaveSpeedClient("k", client=httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"data": {"status": "failed", "error": "voice not found"}}))))
    with pytest.raises(ProviderError, match="voice not found"):
        failing.wait("t3", interval_s=0)
    bal = WaveSpeedClient("k", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": {"balance": 50.25}}))))
    assert bal.balance() == 50.25


class Out(BaseModel):
    title: str
    score: int


def test_openai_compatible_json_mode_with_one_repair_round():
    bodies: list[dict] = []
    replies = iter(['{"title": "A"}', '```json\n{"title": "A", "score": 7}\n```'])

    def handler(req: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": next(replies)}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 100, "completion_tokens": 20}})

    llm = OpenAICompatLlm("wavespeed", api_key="k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    out, usage = llm.generate_structured(system="sys", user="u", schema=Out, model="google/gemini-3.1-flash-lite", temperature=0.2)
    assert out == Out(title="A", score=7) and usage.prompt_tokens == 200 and usage.output_tokens == 40 and usage.provider == "wavespeed"
    assert bodies[0]["response_format"] == {"type": "json_object"} and bodies[0]["model"] == "google/gemini-3.1-flash-lite"
    assert "JSON Schema" in bodies[0]["messages"][0]["content"] and "does not satisfy the schema" in bodies[1]["messages"][-1]["content"]
    bad = OpenAICompatLlm("wavespeed", api_key="k", client=httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"choices": [{"message": {"content": '{"nope": 1}'}, "finish_reason": "stop"}], "usage": {}}))))
    with pytest.raises(LlmSchemaError):
        bad.generate_structured(system="s", user="u", schema=Out, model="m")
    assert OpenAICompatLlm("wavespeed").base_url == "https://llm.wavespeed.ai/v1"


def test_cost_estimates_and_legacy_ledger_rows():
    assert pricing.llm_cost("gemini-3.1-flash-lite", 1_000_000, 0) == 0.10
    assert pricing.llm_cost("google/gemini-3.1-flash-lite", 0, 1_000_000) == 0.40  # gateway ids match by substring
    assert pricing.tts_cost("elevenlabs", "eleven_v3", characters=1000) == 0.10
    assert pricing.tts_cost("wavespeed", "elevenlabs/eleven-v3", characters=1000) == 0.20
    assert pricing.tts_cost("gemini", "gemini-3.1-flash-tts-preview", audio_ms=60_000, tokens_in=0) == round(1500 * 20 / 1e6, 6)
    assert pricing.tts_cost("mock", "mock-tone", characters=9999) == 0.0
    legacy_voice = {"at": "2026-09-20T15:29:22+00:00", "stage": "generate_voice", "provider": "elevenlabs", "model_id": "eleven_v3", "characters_billed": 500}
    legacy_llm = {"at": "2026-09-20T15:28:56+00:00", "stage": "parse_script", "model": "gemini-3.1-flash-lite", "prompt_tokens": 1000, "output_tokens": 500}
    v, m = normalize("demo", legacy_voice), normalize("demo", legacy_llm)
    assert (v["kind"], v["agent"], v["cost_usd"]) == ("tts", "sound_engineer", 0.05)
    assert (m["kind"], m["agent"], m["tokens_out"]) == ("llm", "director", 500) and m["cost_usd"] > 0
    assert normalize("demo", {"at": "bad"}) is None


G38 = "google/gemini-3.8-flash/text-to-speech"


def test_wavespeed_gemini_tts_bodies_and_billing():
    """Gemini 3.8 TTS through WaveSpeed: voice by Gemini name, style as style_instructions, dialogue as turns; no unknown fields."""
    from emvoox.providers.tts.wavespeed import billable_characters

    one = TtsRequest(provider="wavespeed", model_id=G38, voice_id="Kore", text="Anh đi đi.", settings={"style": "giọng lạnh lùng (mạnh)"})
    assert build_body(one) == {"text": "Anh đi đi.", "voice": "Kore", "style_instructions": "giọng lạnh lùng (mạnh)"}
    assert billable_characters(one, build_body(one)) == len("Anh đi đi.") + len("giọng lạnh lùng (mạnh)")
    duo = TtsRequest(provider="wavespeed", model_id=G38, voice_id="ep01_sc01_c01", text="Linh: Anh đi đi.\nMinhKhoi: Không: tôi ở lại.",
                     settings={"style": "Hội thoại.", "turn_styles": ["giọng buồn", ""]}, speakers=(("Linh", "Kore"), ("MinhKhoi", "Puck")))
    assert build_body(duo) == {
        "speakers": [{"speaker_id": "Linh", "voice": "Kore"}, {"speaker_id": "MinhKhoi", "voice": "Puck"}],
        "turns": [{"speaker_id": "Linh", "text": "Anh đi đi.", "style_instructions": "giọng buồn"}, {"speaker_id": "MinhKhoi", "text": "Không: tôi ở lại."}],
        "style_instructions": "Hội thoại."}
    with pytest.raises(ProviderError):
        build_body(TtsRequest(provider="wavespeed", model_id=G38, voice_id="c", text="Ai đó: xin chào", speakers=(("Linh", "Kore"), ("MinhKhoi", "Puck"))))
    # billed per request per started 1,000 characters: a 100-character line costs as much as a 1,000-character chunk
    assert pricing.tts_cost("wavespeed", G38, characters=100) == pricing.tts_cost("wavespeed", G38, characters=1000) == 0.05
    assert pricing.tts_cost("wavespeed", G38, characters=1001) == 0.10
    assert pricing.tts_cost("wavespeed", "google/gemini-3.8-flash-lite/text-to-speech", characters=10) == 0.04
