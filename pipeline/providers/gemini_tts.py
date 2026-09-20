"""Gemini TTS adapter (second engine next to ElevenLabs).

Models: gemini-3.1-flash-tts-preview (default), gemini-2.5-flash-preview-tts (both free tier), gemini-2.5-pro-preview-tts.
Voices: 30 prebuilt names (see catalog.GEMINI_VOICES); `voice_id` in the registry is the name.

Style is not a settings vector but a natural-language direction. `mapping.settings_for_line`
builds it as `settings["style"]` (Vietnamese); this adapter prefixes it to the text as
"<direction>:\n<text>" which is the pattern Google documents ("Say cheerfully: ..."). The model
returns 24 kHz 16-bit mono PCM; we resample to the canonical 44.1 kHz stem with FFmpeg.

Rate limits on the free tier are low, so 429 is retried with a long backoff; the skill runs the
voice stage with concurrency 1 for this provider.
"""

from __future__ import annotations

import time
from pathlib import Path

from pipeline.providers.base import ProviderError, StemInfo, TtsRequest, duration_ms, to_stem_wav
from pipeline.usage import record_event

PCM_RATE = 24_000
RETRY_STATUSES = {429, 500, 502, 503, 504}


def _error_details(e: Exception) -> list:
    d = getattr(e, "details", None)
    if isinstance(d, dict):
        d = d.get("error", d)
        return d.get("details", []) if isinstance(d, dict) else []
    return d if isinstance(d, list) else []


def quota_violation(e: Exception) -> dict | None:
    """First QuotaFailure violation of a google-genai APIError: {quotaId, quotaValue, model}."""
    for item in _error_details(e):
        if isinstance(item, dict) and str(item.get("@type", "")).endswith("QuotaFailure"):
            for v in item.get("violations", []):
                return {"quotaId": v.get("quotaId", ""), "quotaValue": v.get("quotaValue"),
                        "model": (v.get("quotaDimensions") or {}).get("model")}
    return None


def retry_delay(e: Exception) -> float:
    for item in _error_details(e):
        if isinstance(item, dict) and str(item.get("@type", "")).endswith("RetryInfo"):
            try:
                return float(str(item.get("retryDelay", "0")).rstrip("s"))
            except ValueError:
                return 0.0
    return 0.0


def build_prompt(style: str | None, text: str) -> str:
    style = (style or "").strip().rstrip(":;,. ")
    return f"{style}:\n{text}" if style else text


class GeminiTtsProvider:
    name = "gemini"

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key
        self._client = None

    def _get_client(self):
        if self._client is None:
            from pipeline.llm.gemini_client import make_client

            self._client = make_client(self._api_key)
        return self._client

    def synthesize(self, req: TtsRequest, out: Path, *, retries: int = 4) -> StemInfo:
        from google.genai import errors, types

        client = self._get_client()
        prompt = build_prompt(req.settings.get("style"), req.text)
        if len(req.speakers) > 1:  # scene chunk: up to two speakers in one request
            speech = types.SpeechConfig(multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(speaker_voice_configs=[
                types.SpeakerVoiceConfig(speaker=label, voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))) for label, voice in req.speakers]))
        else:
            voice = req.speakers[0][1] if req.speakers else req.voice_id
            speech = types.SpeechConfig(voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)))
        config = types.GenerateContentConfig(response_modalities=["AUDIO"], speech_config=speech)
        attempt = 0
        t0 = time.time()
        while True:
            try:
                resp = client.models.generate_content(model=req.model_id, contents=prompt, config=config)
                break
            except errors.APIError as e:
                status = int(getattr(e, "code", 0) or 0)
                quota = quota_violation(e)
                if status == 429:
                    record_event("gemini", req.model_id, "quota_daily" if quota and "PerDay" in quota.get("quotaId", "") else "rate_limit",
                                 status=429, quota_id=(quota or {}).get("quotaId"), quota_value=(quota or {}).get("quotaValue"),
                                 retry_after_s=retry_delay(e) or None, message=str(getattr(e, "message", None) or e))
                if quota and "PerDay" in quota.get("quotaId", ""):
                    # Free tier: 10 requests per day per model. Waiting does not help; say so at once.
                    raise ProviderError(
                        f"gemini 429: daily free-tier quota exhausted for {quota.get('model', req.model_id)} "
                        f"({quota.get('quotaValue', '?')} requests/day). Enable billing on the Gemini project, switch the Gemini "
                        f"model, or retry tomorrow.", retryable=False, status=429) from e
                if status in RETRY_STATUSES and attempt < retries:
                    attempt += 1
                    time.sleep(min(60, max(retry_delay(e), 5 * (2 ** (attempt - 1)))))
                    continue
                msg = str(getattr(e, "message", None) or e)
                if quota:
                    msg += f" [quota {quota.get('quotaId')} = {quota.get('quotaValue')} for {quota.get('model')}]"
                raise ProviderError(f"gemini {status}: {msg[:400]}", retryable=status in RETRY_STATUSES, status=status) from e
            except (ConnectionError, TimeoutError, OSError) as e:
                if attempt < retries:
                    attempt += 1
                    time.sleep(min(60, 5 * (2 ** (attempt - 1))))
                    continue
                raise ProviderError(f"gemini network error: {e}", retryable=True) from e
        elapsed = time.time() - t0

        pf = getattr(resp, "prompt_feedback", None)
        if pf is not None and getattr(pf, "block_reason", None):
            raise ProviderError(f"gemini blocked the prompt: {pf.block_reason}", status=400)
        cand = resp.candidates[0] if resp.candidates else None
        parts = getattr(getattr(cand, "content", None), "parts", None) or []
        pcm = next((p.inline_data.data for p in parts if getattr(p, "inline_data", None) and p.inline_data.data), None)
        if not pcm:
            finish = str(getattr(cand, "finish_reason", "") or "")
            raise ProviderError(f"gemini returned no audio (finish_reason={finish or 'unknown'})", retryable=True)

        to_stem_wav(pcm, out, src_suffix=".pcm", pcm_rate=PCM_RATE)
        um = getattr(resp, "usage_metadata", None)
        return {
            "duration_ms": duration_ms(out),
            "characters_billed": len(req.text),
            "tokens_in": int(getattr(um, "prompt_token_count", 0) or 0),
            "tokens_out": int(getattr(um, "candidates_token_count", 0) or 0),
            "elapsed_s": round(elapsed, 2),
            "prompt": prompt,
        }
