"""ElevenLabs adapter (primary provider, decision D4).

Models: eleven_v3 (audio tags, discrete stability), eleven_multilingual_v2 (continuous stability/style).
Uses `convert_with_timestamps` so the character alignment is stored in the sidecar for later
subtitle / lip-sync work.

Vendor rules encoded here (from the ElevenLabs API docs, verified against SDK 2.68):
- `language_code` is only accepted by Turbo v2.5 / Flash v2.5; sending it to v3 or multilingual_v2
  returns 400, so it is only added for those models.
- Output formats above mp3_44100_128 / pcm_44100 / wav_44100 are tier-gated; we try the canonical
  WAV first and fall back to mp3_44100_128 + ffmpeg conversion when the account tier rejects it.
"""

from __future__ import annotations

import base64
import threading
import time
from pathlib import Path

from pipeline.config import get_settings
from pipeline.providers.base import ProviderError, StemInfo, TtsRequest, duration_ms, to_stem_wav
from pipeline.usage import record_event

LANGUAGE_ENFORCING_MODELS = {"eleven_turbo_v2_5", "eleven_flash_v2_5"}
NO_CONTEXT_MODELS = {"eleven_v3"}  # "previous_text or next_text is not yet supported with the 'eleven_v3' model"
OUTPUT_FORMATS = (("wav_44100", ".wav"), ("mp3_44100_128", ".mp3"))
RETRY_STATUSES = {429, 500, 502, 503, 504}


class ElevenLabsProvider:
    name = "elevenlabs"

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key
        self._client = None
        self._format_index = 0  # sticks to the fallback format once the tier rejects the first
        self._lock = threading.Lock()

    def _get_client(self):
        if self._client is None:
            from elevenlabs.client import ElevenLabs

            self._client = ElevenLabs(api_key=self._api_key or get_settings().require("elevenlabs_api_key"))
        return self._client

    def synthesize(self, req: TtsRequest, out: Path, *, retries: int = 3) -> StemInfo:
        from elevenlabs import VoiceSettings
        from elevenlabs.core.api_error import ApiError

        client = self._get_client()
        vs_kwargs = {k: v for k, v in req.settings.items() if k in ("stability", "similarity_boost", "style", "use_speaker_boost", "speed")}
        kwargs: dict = dict(text=req.text, model_id=req.model_id, voice_settings=VoiceSettings(**vs_kwargs))
        if req.model_id in LANGUAGE_ENFORCING_MODELS:
            kwargs["language_code"] = "vi"
        if req.model_id not in NO_CONTEXT_MODELS:  # v3 returns 400 for previous_text/next_text
            if req.previous_text:
                kwargs["previous_text"] = req.previous_text
            if req.next_text:
                kwargs["next_text"] = req.next_text

        attempt = 0
        while True:
            used_index = self._format_index
            fmt, suffix = OUTPUT_FORMATS[used_index]
            try:
                t0 = time.time()
                res = client.text_to_speech.convert_with_timestamps(req.voice_id, output_format=fmt, **kwargs)
                elapsed = time.time() - t0
                break
            except ApiError as e:
                detail = (e.body or {}).get("detail", {}) if isinstance(e.body, dict) else {}
                msg = detail.get("message", str(e.body)) if isinstance(detail, dict) else str(detail)
                status = e.status_code or 0
                body_l = str(e.body).lower()
                if status == 429 or "quota_exceeded" in body_l:
                    record_event("elevenlabs", req.model_id, "quota_monthly" if "quota_exceeded" in body_l else "rate_limit", status=status, message=msg)
                elif status == 402:
                    record_event("elevenlabs", req.model_id, "payment_required", status=402, message=msg)
                # Tier-gated output format: switch to the fallback format and retry immediately.
                # Thread-safe: another worker may already have advanced the index; then just retry.
                if status in (400, 402, 403) and ("output_format" in body_l or "output format" in body_l):
                    with self._lock:
                        if self._format_index == used_index and used_index + 1 < len(OUTPUT_FORMATS):
                            self._format_index = used_index + 1
                    if self._format_index != used_index:
                        continue
                if status in RETRY_STATUSES and attempt < retries:
                    attempt += 1
                    time.sleep(2 * (2 ** attempt))
                    continue
                raise ProviderError(f"elevenlabs {status}: {msg}", retryable=status in RETRY_STATUSES, status=status) from e

        audio = base64.b64decode(res.audio_base_64)
        to_stem_wav(audio, out, src_suffix=suffix)
        info: StemInfo = {
            "duration_ms": duration_ms(out),
            "characters_billed": len(req.text),
            "output_format": fmt,
            "elapsed_s": round(elapsed, 2),
        }
        al = res.alignment
        if al is not None:
            info["alignment"] = {
                "characters": al.characters,
                "start_s": al.character_start_times_seconds,
                "end_s": al.character_end_times_seconds,
            }
        return info
