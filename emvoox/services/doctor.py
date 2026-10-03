"""Health checks for the Settings page and ``python -m emvoox doctor``.

Offline checks (always): Python, FFmpeg, data directory, Voice IP registry, which keys are set and
which engines they unlock. Live checks (``live=True``, a few cheap GETs, no generation): Gemini
model listing, ElevenLabs user, WaveSpeed balance and model catalogue, WaveSpeed LLM model list.
"""

from __future__ import annotations

import platform
import sys

from emvoox.audio.ffmpeg import have_ffmpeg
from emvoox.config import get_settings
from emvoox.repositories import Repositories


def _check(cid: str, label: str, ok: bool | None, detail: str) -> dict:
    return {"id": cid, "label": label, "ok": ok, "detail": detail}


def run_checks(repos: Repositories, *, live: bool = False) -> list[dict]:
    s = get_settings()
    out = [
        _check("python", "Python 3.11+", sys.version_info >= (3, 11), f"{platform.python_version()} at {sys.executable}"),
        _check("ffmpeg", "FFmpeg and ffprobe on PATH", have_ffmpeg(), "needed for stems, mastering and QA"),
        _check("storage", "Storage backend", True, f"{repos.backend} at {repos.root}"),
    ]
    reg = repos.registry.load()
    ips = reg.actors()
    out.append(_check("registry", "Voice IP registry", bool(ips), f"{len(ips)} IP actor(s), {len(reg.characters) - len(ips)} one-off; "
                      f"cloned voices: {sum(len(c.cloned_providers()) for c in reg.characters)}"))
    keys = s.keys_present()
    out.append(_check("llm", "LLM provider", s.llm_provider == "mock" or keys.get(s.llm_provider, False),
                      f"{s.llm_provider} / {s.llm_model}" + ("" if s.llm_provider == "mock" or keys.get(s.llm_provider) else " (key missing)")))
    out.append(_check("tts", "Default TTS engine", s.tts_provider == "mock" or keys.get(s.tts_provider, False),
                      f"{s.tts_provider}" + ("" if s.tts_provider == "mock" or keys.get(s.tts_provider) else " (key missing)")))
    for name, env in (("gemini", "GEMINI_API_KEY"), ("elevenlabs", "ELEVENLABS_API_KEY"), ("wavespeed", "WAVESPEED_API_KEY"),
                      ("openai", "OPENAI_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY")):
        out.append(_check(f"key.{name}", env, keys[name] or None, "set" if keys[name] else "not set (optional)"))
    try:
        import playwright  # noqa: F401

        out.append(_check("playwright", "Browser scan (Playwright)", True, "installed; run `playwright install chromium` once"))
    except ImportError:
        out.append(_check("playwright", "Browser scan (Playwright)", None, "not installed (optional): pip install -e '.[research]'"))
    if live:
        out.extend(live_checks())
    return out


def live_checks() -> list[dict]:
    s = get_settings()
    out: list[dict] = []
    if s.gemini_api_key:
        try:
            from emvoox.providers.llm.gemini import make_client

            n = sum(1 for _ in make_client().models.list())
            out.append(_check("live.gemini", "Gemini API reachable", True, f"{n} model(s) visible"))
        except Exception as e:  # noqa: BLE001
            out.append(_check("live.gemini", "Gemini API reachable", False, f"{type(e).__name__}: {str(e)[:160]}"))
    if s.elevenlabs_api_key:
        try:
            from elevenlabs.client import ElevenLabs

            v = ElevenLabs(api_key=s.elevenlabs_api_key).voices.search(page_size=1)
            out.append(_check("live.elevenlabs", "ElevenLabs API reachable", True, f"voices visible: {getattr(v, 'total_count', '?')}"))
        except Exception as e:  # noqa: BLE001
            out.append(_check("live.elevenlabs", "ElevenLabs API reachable", False, f"{type(e).__name__}: {str(e)[:160]}"))
    if s.wavespeed_api_key:
        from emvoox.providers.tts.wavespeed import WaveSpeedClient

        ws = WaveSpeedClient(s.wavespeed_api_key)
        try:
            out.append(_check("live.wavespeed.balance", "WaveSpeed balance", True, f"${ws.balance():.2f}"))
        except Exception as e:  # noqa: BLE001
            out.append(_check("live.wavespeed.balance", "WaveSpeed balance", False, f"{type(e).__name__}: {str(e)[:160]}"))
        try:
            models = ws.models()
            speech = sorted(m.get("model_id", "") for m in models
                            if any(w in str(m.get("type", "")) + m.get("model_id", "") for w in ("speech", "audio", "tts", "voice")))
            out.append(_check("live.wavespeed.tts", "WaveSpeed speech models", bool(speech), ", ".join(speech[:12]) or "none visible"))
        except Exception as e:  # noqa: BLE001
            out.append(_check("live.wavespeed.tts", "WaveSpeed speech models", False, f"{type(e).__name__}: {str(e)[:160]}"))
        try:
            from emvoox.providers.llm.openai_compat import OpenAICompatLlm

            ids = OpenAICompatLlm("wavespeed").list_models()
            pick = [m for m in ids if any(k in m for k in ("gemini", "claude", "gpt"))][:12]
            out.append(_check("live.wavespeed.llm", "WaveSpeed LLM models", bool(ids), f"{len(ids)} model(s); e.g. {', '.join(pick) or ', '.join(ids[:8])}"))
        except Exception as e:  # noqa: BLE001
            out.append(_check("live.wavespeed.llm", "WaveSpeed LLM models", False, f"{type(e).__name__}: {str(e)[:160]}"))
    if not out:
        out.append(_check("live.none", "Live checks", None, "no vendor key is set"))
    return out
