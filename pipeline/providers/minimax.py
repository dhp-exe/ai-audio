"""MiniMax T2A v2 adapter (fallback provider, decision D4).

HTTP only (no SDK). Endpoint and payload follow the public MiniMax "T2A v2" docs; this adapter has
not been exercised live yet because no MiniMax key is configured. First live run should be
`generate_voice.py one --provider minimax ...` and any payload mismatch fixed here.

Request:  POST https://api.minimax.io/v1/t2a_v2?GroupId=<MINIMAX_GROUP_ID>
Response: {"data": {"audio": "<hex>"}, "extra_info": {"usage_characters": N, "audio_length": ms},
           "base_resp": {"status_code": 0, "status_msg": "success"}}
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from pipeline.config import get_settings
from pipeline.providers.base import ProviderError, StemInfo, TtsRequest, duration_ms, to_stem_wav

ENDPOINT = "https://api.minimax.io/v1/t2a_v2"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class MiniMaxProvider:
    name = "minimax"

    def __init__(self, api_key: str | None = None, group_id: str | None = None):
        s = get_settings()
        self._api_key = api_key or s.require("minimax_api_key")
        self._group_id = group_id or s.require("minimax_group_id")

    def synthesize(self, req: TtsRequest, out: Path, *, retries: int = 3) -> StemInfo:
        voice_setting = {"voice_id": req.voice_id}
        for k in ("speed", "vol", "pitch", "emotion"):
            if k in req.settings:
                voice_setting[k] = req.settings[k]
        body = {
            "model": req.model_id,
            "text": req.text,
            "stream": False,
            "language_boost": "Vietnamese",
            "voice_setting": voice_setting,
            "audio_setting": {"sample_rate": 44100, "bitrate": 128000, "format": "mp3", "channel": 1},
        }
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

        attempt = 0
        while True:
            t0 = time.time()
            try:
                r = httpx.post(ENDPOINT, params={"GroupId": self._group_id}, json=body, headers=headers, timeout=120)
            except httpx.HTTPError as e:
                if attempt < retries:
                    attempt += 1
                    time.sleep(2 * (2 ** attempt))
                    continue
                raise ProviderError(f"minimax network error: {e}", retryable=True) from e
            if r.status_code in RETRY_STATUSES and attempt < retries:
                attempt += 1
                time.sleep(2 * (2 ** attempt))
                continue
            if r.status_code != 200:
                raise ProviderError(f"minimax HTTP {r.status_code}: {r.text[:200]}", retryable=r.status_code in RETRY_STATUSES, status=r.status_code)
            payload = r.json()
            base = payload.get("base_resp", {})
            if base.get("status_code", 0) != 0:
                raise ProviderError(f"minimax {base.get('status_code')}: {base.get('status_msg')}", status=r.status_code)
            break
        elapsed = time.time() - t0

        audio_hex = payload.get("data", {}).get("audio")
        if not audio_hex:
            raise ProviderError("minimax returned no audio")
        to_stem_wav(bytes.fromhex(audio_hex), out, src_suffix=".mp3")
        extra = payload.get("extra_info", {})
        return {
            "duration_ms": duration_ms(out),
            "characters_billed": int(extra.get("usage_characters", len(req.text))),
            "vendor_audio_length_ms": extra.get("audio_length"),
            "elapsed_s": round(elapsed, 2),
        }
