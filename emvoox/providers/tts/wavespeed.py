"""WaveSpeed.ai adapter: one API key in front of many speech models.

API (https://wavespeed.ai/docs):
    POST https://api.wavespeed.ai/api/v3/<model path>      -> {"data": {"id": ..., "status": ...}}
    GET  https://api.wavespeed.ai/api/v3/predictions/<id>/result
         -> {"data": {"status": "completed" | "failed" | ..., "outputs": ["https://...mp3"], "error": ...}}
    GET  https://api.wavespeed.ai/api/v3/balance            -> {"data": {"balance": 50.25}}
    GET  https://api.wavespeed.ai/api/v3/models             -> every model the key can reach
    Authorization: Bearer $WAVESPEED_API_KEY

``model_id`` in a request is the model path. Request bodies differ by vendor family:

    elevenlabs/*   text, voice_id (preset name or ANY ElevenLabs voice id, cloned ones included), stability
    minimax/*      text, voice_id (system or cloned), emotion, speed, pitch, volume
    google/*       Gemini 3.8 TTS: text, voice (prebuilt name), style_instructions; or, for a
                   two-speaker chunk, speakers [{speaker_id, voice}] + turns [{speaker_id, text,
                   style_instructions}] and no text. Unknown fields are rejected. Billed per
                   request per started 1,000 characters of text + style (verified live 2026-10-03)
    anything else  text, voice_id plus the request's scalar settings as given

A submission is never retried after a transport error: WaveSpeed documents that a dropped
response can still belong to a prediction that was accepted and billed. HTTP 429/5xx answers are
retried (the task was not accepted); polling the result is idempotent and retried freely.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from emvoox.config import get_settings
from emvoox.providers.tts.base import ProviderError, StemInfo, TtsRequest, duration_ms, to_stem_wav
from emvoox.providers.tts.catalog import voice_family
from emvoox.telemetry.events import record_event

BASE_URL = "https://api.wavespeed.ai/api/v3"
RETRY_STATUSES = {429, 500, 502, 503, 504}
POLL_INTERVAL_S = 1.5
POLL_TIMEOUT_S = 240.0
MINIMAX_EMOTIONS = {"happy", "sad", "angry", "fearful", "disgusted", "surprised", "neutral"}
MINIMAX_KEYS = ("emotion", "speed", "pitch", "volume")
STYLE_MAX = 2000  # style_instructions limit of the Gemini TTS endpoints


def _gemini_body(req: TtsRequest) -> dict:
    s = req.settings
    style = str(s.get("style") or "").strip()
    if len(req.speakers) > 1:  # dialogue: the transcript's "Label: text" lines become turns, each with its own direction
        labels = {label for label, _ in req.speakers}
        styles = list(s.get("turn_styles") or [])
        turns = []
        for i, raw in enumerate(ln for ln in req.text.split("\n") if ln.strip()):
            label, sep, said = raw.partition(": ")
            if not sep or label not in labels:
                raise ProviderError(f"wavespeed: dialogue line {i + 1} of {req.line_id or req.voice_id} has no known speaker label")
            turn = {"speaker_id": label, "text": said.strip()}
            if i < len(styles) and styles[i]:
                turn["style_instructions"] = str(styles[i])[:STYLE_MAX]
            turns.append(turn)
        body: dict = {"speakers": [{"speaker_id": label, "voice": voice} for label, voice in req.speakers], "turns": turns}
    else:
        body = {"text": req.text, "voice": req.speakers[0][1] if req.speakers else req.voice_id}
    if style:
        body["style_instructions"] = style[:STYLE_MAX]
    return body


def billable_characters(req: TtsRequest, body: dict) -> int:
    """Characters the vendor bills for this request (Gemini TTS also bills the style text)."""
    if voice_family("wavespeed", req.model_id) != "gemini":
        return len(req.text)
    n = len(body.get("text", "")) + len(body.get("style_instructions", ""))
    return n + sum(len(t["text"]) + len(t.get("style_instructions", "")) for t in body.get("turns", []))


def build_body(req: TtsRequest) -> dict:
    """Request body for the model family named by ``req.model_id``."""
    if voice_family("wavespeed", req.model_id) == "gemini":
        return _gemini_body(req)
    body: dict = {"text": req.text, "voice_id": req.voice_id}
    s = req.settings
    if req.model_id.startswith("elevenlabs/"):
        if "stability" in s:  # the only tuning parameter the hosted endpoint documents
            body["stability"] = s["stability"]
    elif req.model_id.startswith("minimax/"):
        for k in MINIMAX_KEYS:
            if k in s and s[k] is not None:
                body[k] = s[k]
        if body.get("emotion") not in MINIMAX_EMOTIONS:
            body.pop("emotion", None)
    else:
        body.update({k: v for k, v in s.items() if isinstance(v, (int, float, str, bool)) and k not in ("style", "retry_attempt")})
    return body


class WaveSpeedClient:
    """Thin HTTP client shared by the TTS adapter and the doctor/costs checks."""

    def __init__(self, api_key: str | None = None, *, client: httpx.Client | None = None, base_url: str = BASE_URL):
        self._api_key = api_key
        self._client = client
        self.base_url = base_url.rstrip("/")

    def _key(self) -> str:
        return self._api_key or get_settings().require("wavespeed_api_key")

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=60.0, follow_redirects=True)
        return self._client

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._key()}", "Content-Type": "application/json"}

    def balance(self) -> float:
        r = self._http().get(f"{self.base_url}/balance", headers=self._headers())
        r.raise_for_status()
        return float((r.json().get("data") or {}).get("balance") or 0.0)

    def models(self) -> list[dict]:
        r = self._http().get(f"{self.base_url}/models", headers=self._headers())
        r.raise_for_status()
        return list(r.json().get("data") or [])

    def submit(self, model_path: str, body: dict, *, retries: int = 3) -> str:
        attempt = 0
        while True:
            try:
                r = self._http().post(f"{self.base_url}/{model_path}", json=body, headers=self._headers())
            except httpx.HTTPError as e:
                # not retried: the task may have been accepted and billed
                raise ProviderError(f"wavespeed network error on submit (not retried, the task may have been accepted): {e}", retryable=False) from e
            if r.status_code == 200:
                data = (r.json() or {}).get("data") or {}
                if not data.get("id"):
                    raise ProviderError(f"wavespeed: no task id in the response: {r.text[:300]}", status=502)
                return str(data["id"])
            if r.status_code == 429:
                record_event("wavespeed", model_path, "rate_limit", status=429, message=r.text[:200])
            elif r.status_code == 402:
                record_event("wavespeed", model_path, "payment_required", status=402, message=r.text[:200])
            if r.status_code in RETRY_STATUSES and attempt < retries:
                attempt += 1
                time.sleep(2 * (2 ** attempt))
                continue
            raise ProviderError(f"wavespeed {r.status_code}: {r.text[:400]}", retryable=r.status_code in RETRY_STATUSES, status=r.status_code)

    def wait(self, task_id: str, *, timeout_s: float = POLL_TIMEOUT_S, interval_s: float = POLL_INTERVAL_S) -> dict:
        deadline = time.time() + timeout_s
        errors = 0
        while time.time() < deadline:
            try:
                r = self._http().get(f"{self.base_url}/predictions/{task_id}/result", headers=self._headers())
            except httpx.HTTPError as e:
                errors += 1
                if errors > 5:
                    raise ProviderError(f"wavespeed network error while polling {task_id}: {e}", retryable=True) from e
                time.sleep(interval_s)
                continue
            if r.status_code == 200:
                data = (r.json() or {}).get("data") or {}
                status = str(data.get("status") or "")
                if status == "completed":
                    return data
                if status in ("failed", "cancelled", "timeout", "deleted"):
                    raise ProviderError(f"wavespeed task {task_id} {status}: {str(data.get('error') or '')[:300]}", retryable=status == "timeout")
            elif r.status_code not in RETRY_STATUSES:
                raise ProviderError(f"wavespeed {r.status_code} while polling: {r.text[:300]}", status=r.status_code)
            time.sleep(interval_s)
        raise ProviderError(f"wavespeed task {task_id} did not finish within {timeout_s:.0f}s", retryable=True)

    def download(self, url: str) -> bytes:
        r = self._http().get(url)
        r.raise_for_status()
        return r.content


class WaveSpeedTtsProvider:
    name = "wavespeed"

    def __init__(self, api_key: str | None = None, *, client: WaveSpeedClient | None = None):
        self._ws = client or WaveSpeedClient(api_key)

    def synthesize(self, req: TtsRequest, out: Path, *, retries: int = 3) -> StemInfo:
        t0 = time.time()
        body = build_body(req)
        task_id = self._ws.submit(req.model_id, body, retries=retries)
        data = self._ws.wait(task_id)
        outputs = data.get("outputs") or []
        if not outputs:
            raise ProviderError(f"wavespeed task {task_id} completed without outputs", retryable=True)
        url = str(outputs[0])
        suffix = ".wav" if url.lower().split("?")[0].endswith(".wav") else ".mp3"
        try:
            audio = self._ws.download(url)
        except httpx.HTTPError as e:
            raise ProviderError(f"wavespeed: could not download the audio for task {task_id}: {e}", retryable=True) from e
        to_stem_wav(audio, out, src_suffix=suffix)
        return {
            "duration_ms": duration_ms(out),
            "characters_billed": billable_characters(req, body),
            "elapsed_s": round(time.time() - t0, 2),
            "task_id": task_id,
            "output_url": url,
        }
