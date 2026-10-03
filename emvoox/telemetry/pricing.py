"""Cost estimates for the run log. These are list prices used to estimate spend, not invoices.

Sources: docs/Cost_and_Pricing_Research.md (ElevenLabs, Gemini TTS, MiniMax; checked 2026-09-21)
and the vendors' public price pages. Override or extend any entry without touching code by writing
``assets/pricing.json``:

    {"llm": {"google/gemini-3.1-flash-lite": [0.10, 0.40]},
     "tts_per_1k_chars": {"elevenlabs/eleven-v3": 0.20},
     "tts_audio_per_1m_tokens": {"gemini-3.1-flash-tts-preview": [1.0, 20.0]}}
"""

from __future__ import annotations

# USD per 1M tokens: (input, output). Matched by longest substring of the model id.
LLM_PRICES: dict[str, tuple[float, float]] = {
    "gemini-3.1-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-3.6-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "gpt-5-mini": (0.25, 2.00),
    "deepseek": (0.30, 1.20),
    "mock": (0.0, 0.0),
}
DEFAULT_LLM_PRICE = (0.30, 2.50)

# USD per 1,000 characters sent.
TTS_CHAR_PRICES: dict[str, float] = {
    "eleven_v3": 0.10,
    "eleven_multilingual_v2": 0.10,
    "eleven_flash_v2_5": 0.05,
    "eleven_turbo_v2_5": 0.05,
    "elevenlabs/eleven-v3": 0.20,  # WaveSpeed's documented rate for the hosted endpoint
    "minimax/speech-2.6-hd": 0.10,
    "minimax/speech-2.6-turbo": 0.06,
    "minimax/speech-02-hd": 0.05,
    "mock": 0.0,
}
# USD per request per started 1,000 billable characters (WaveSpeed's Gemini TTS: 100 characters cost the same as 1,000).
TTS_REQUEST_PRICES: dict[str, float] = {
    "google/gemini-3.8-flash/text-to-speech": 0.05,
    "google/gemini-3.8-flash-lite/text-to-speech": 0.04,
}
# Gemini TTS: USD per 1M tokens (text in, audio out); 25 audio tokens per second of audio.
TTS_TOKEN_PRICES: dict[str, tuple[float, float]] = {
    "gemini-3.1-flash-tts-preview": (1.00, 20.00),
    "gemini-2.5-flash-preview-tts": (0.50, 10.00),
    "gemini-2.5-pro-preview-tts": (1.00, 20.00),
}
AUDIO_TOKENS_PER_SECOND = 25

_overrides: dict | None = None


def _load_overrides() -> dict:
    global _overrides
    if _overrides is None:
        try:
            from emvoox.repositories import get_repositories

            d = get_repositories().docs.get("assets/pricing.json")
            _overrides = d if isinstance(d, dict) else {}
        except Exception:  # noqa: BLE001 - pricing must never break a run
            _overrides = {}
    return _overrides


def reset_overrides() -> None:
    global _overrides
    _overrides = None


def _match(table: dict, model: str):
    best = None
    for key, value in table.items():
        if key in model and (best is None or len(key) > len(best[0])):
            best = (key, value)
    return best[1] if best else None


def llm_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    table = {**LLM_PRICES, **{k: tuple(v) for k, v in (_load_overrides().get("llm") or {}).items()}}
    pin, pout = _match(table, model or "") or DEFAULT_LLM_PRICE
    return round((tokens_in * pin + tokens_out * pout) / 1_000_000, 6)


def tts_cost(provider: str, model: str, *, characters: int = 0, audio_ms: int = 0, tokens_in: int = 0, tokens_out: int = 0) -> float:
    ov = _load_overrides()
    if provider == "mock":
        return 0.0
    if provider == "gemini":
        table = {**TTS_TOKEN_PRICES, **{k: tuple(v) for k, v in (ov.get("tts_audio_per_1m_tokens") or {}).items()}}
        pin, pout = _match(table, model or "") or (1.00, 20.00)
        out_tokens = tokens_out or int(audio_ms / 1000 * AUDIO_TOKENS_PER_SECOND)
        in_tokens = tokens_in or int(characters / 4)
        return round((in_tokens * pin + out_tokens * pout) / 1_000_000, 6)
    per_request = _match({**TTS_REQUEST_PRICES, **(ov.get("tts_per_request_1k_chars") or {})}, model or "")
    if per_request is not None:
        return round(max(1, -(-characters // 1000)) * per_request, 6)
    table = {**TTS_CHAR_PRICES, **(ov.get("tts_per_1k_chars") or {})}
    per_1k = _match(table, model or "")
    if per_1k is None:
        per_1k = 0.10
    return round(characters * per_1k / 1000, 6)


def price_table() -> dict:
    """What the Costs page shows as the basis of its estimates."""
    ov = _load_overrides()
    return {
        "llm_per_1m_tokens": {**{k: list(v) for k, v in LLM_PRICES.items()}, **(ov.get("llm") or {})},
        "tts_per_1k_chars": {**TTS_CHAR_PRICES, **(ov.get("tts_per_1k_chars") or {})},
        "tts_per_request_1k_chars": {**TTS_REQUEST_PRICES, **(ov.get("tts_per_request_1k_chars") or {})},
        "tts_per_1m_tokens": {**{k: list(v) for k, v in TTS_TOKEN_PRICES.items()}, **(ov.get("tts_audio_per_1m_tokens") or {})},
        "note": "Estimates from list prices; the vendor invoice is the source of truth.",
    }
