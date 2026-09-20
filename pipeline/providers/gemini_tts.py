"""Gemini TTS adapter (second engine next to ElevenLabs).

Models: gemini-2.5-flash-preview-tts, gemini-3.1-flash-tts-preview (free tier), gemini-2.5-pro-preview-tts.
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

PCM_RATE = 24_000
RETRY_STATUSES = {429, 500, 502, 503, 504}


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
        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=req.voice_id))
            ),
        )
        attempt = 0
        t0 = time.time()
        while True:
            try:
                resp = client.models.generate_content(model=req.model_id, contents=prompt, config=config)
                break
            except errors.APIError as e:
                status = int(getattr(e, "code", 0) or 0)
                if status in RETRY_STATUSES and attempt < retries:
                    attempt += 1
                    time.sleep(min(60, 5 * (2 ** (attempt - 1))))
                    continue
                msg = str(getattr(e, "message", None) or e)
                raise ProviderError(f"gemini {status}: {msg[:300]}", retryable=status in RETRY_STATUSES, status=status) from e
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
