"""Short voice previews (~5 s) for the Voice IPs page and the voice pickers.

Rendered once per (provider, model, voice, text) and cached under assets/previews/ with a sidecar,
so clicking play never spends credits twice. ElevenLabs voices the plan rejects (402) are rendered
with the actor's fallback premade voice and flagged ``placeholder: true``.
"""

from __future__ import annotations

import re
import time

from emvoox import paths
from emvoox.casting import guess_gender, placeholder_voice
from emvoox.contracts.production import CharacterProfile
from emvoox.providers.tts import DEFAULT_MODEL, ProviderError, TtsRequest, get_provider
from emvoox.providers.tts.catalog import voice_family
from emvoox.repositories import Repositories, now_iso
from emvoox.telemetry.ledger import Ledger
from emvoox.text.vi_normalize import normalize_vi

ACTOR_TEXT = "Xin chào, tôi là {name}. Có một chuyện tôi chưa từng kể với ai."  # ~13 words ≈ 5 s
VOICE_TEXT = "Xin chào, đây là giọng {name}. Có một chuyện tôi chưa từng kể với ai."
EL_SETTINGS = {"stability": 0.5, "similarity_boost": 0.75, "use_speaker_boost": True}
GEMINI_STYLE = "Nói tiếng Việt, giọng tự nhiên, ấm áp, tự giới thiệu mình, nhịp nhanh vừa phải, không ngắt nghỉ lâu"


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9-]+", "-", s).strip("-")[:40]


def actor_preview_name(character_id: str, provider: str) -> str:
    return f"{character_id}_{provider}.wav"


def voice_preview_name(provider: str, voice_id: str, model_id: str) -> str:
    return f"voice_{provider}_{_safe(voice_id)}_{_safe(model_id)}.wav"


def preview_settings(provider: str, model_id: str) -> dict:
    if provider == "elevenlabs":
        return dict(EL_SETTINGS)
    if voice_family(provider, model_id) == "gemini":
        return {"style": GEMINI_STYLE}
    if provider == "wavespeed" and model_id.startswith("elevenlabs/"):
        return {"stability": 0.5}
    return {}


def _request(provider: str, model_id: str, voice_id: str, text: str) -> TtsRequest:
    return TtsRequest(provider=provider, model_id=model_id, voice_id=voice_id, text=normalize_vi(text), settings=preview_settings(provider, model_id))


def _render(repos: Repositories, req: TtsRequest, name: str, *, fallback_voice: str | None) -> dict:
    """Render ``req`` to the preview ``name``; on an ElevenLabs 402 for the voice, render the fallback instead."""
    out = repos.assets.preview_path(name)
    engine = get_provider(req.provider)
    used, placeholder, reason = req, False, None
    t0 = time.time()
    try:
        info = engine.synthesize(req, out)
    except ProviderError as e:
        if req.provider == "elevenlabs" and e.status == 402 and fallback_voice and fallback_voice != req.voice_id:
            used = TtsRequest(provider=req.provider, model_id=req.model_id, voice_id=fallback_voice, text=req.text, settings=req.settings)
            info = engine.synthesize(used, out)
            placeholder, reason = True, str(e)[:200]
        else:
            raise
    data = {"hash": req.content_hash(), "request": used.as_dict(), "requested_voice": req.voice_id, "placeholder": placeholder,
            "reason": reason, "rendered_at": now_iso(), "duration_ms": info.get("duration_ms"), "characters_billed": info.get("characters_billed"),
            "tokens_out": info.get("tokens_out"), "ledgered": True}
    repos.assets.save_preview_meta(name, data)
    Ledger(repos.telemetry).tts(agent="studio", skill="voice_preview", provider=req.provider, model=req.model_id,
                                characters=int(info.get("characters_billed") or len(req.text)), audio_ms=int(info.get("duration_ms") or 0),
                                elapsed_s=round(time.time() - t0, 2), tokens_out=int(info.get("tokens_out") or 0))
    return data


def status(repos: Repositories, name: str, req_hash: str | None = None) -> dict | None:
    """Cached preview info for the UI, or None when nothing (valid) is cached."""
    if not repos.assets.preview_exists(name):
        return None
    m = repos.assets.preview_meta(name)
    if not m or (req_hash and m.get("hash") != req_hash):
        return None
    return {"url": f"/api/previews/{name}", "placeholder": bool(m.get("placeholder")), "voice": (m.get("request") or {}).get("voice_id"),
            "requested_voice": m.get("requested_voice"), "duration_ms": m.get("duration_ms"), "rendered_at": m.get("rendered_at")}


def actor_preview(repos: Repositories, profile: CharacterProfile, provider: str, *, force: bool = False, render: bool = True) -> dict | None:
    pv = profile.providers.get(provider)
    if not pv:
        return None
    req = _request(provider, pv.model_id, pv.voice_id, ACTOR_TEXT.format(name=profile.display_name))
    name = actor_preview_name(profile.character_id, provider)
    cached = status(repos, name, req.content_hash())
    if cached and not force:
        return cached
    if not render:
        return None
    fallback = pv.fallback_voice_id or placeholder_voice(profile.gender or guess_gender(profile.voice_description, profile.persona))
    _render(repos, req, name, fallback_voice=fallback)
    return status(repos, name, req.content_hash())


def voice_preview(repos: Repositories, provider: str, voice_id: str, model_id: str | None = None, *, force: bool = False) -> dict | None:
    """Preview for a voice picked in a form. Reuses an actor's cached clip of the same engine/voice/model."""
    model_id = model_id or DEFAULT_MODEL[provider]
    for c in repos.registry.load().characters:
        pv = c.providers.get(provider)
        if pv and pv.voice_id.lower() == voice_id.lower() and pv.model_id == model_id:
            cached = actor_preview(repos, c, provider, render=False)
            if cached:
                return cached
    req = _request(provider, model_id, voice_id, VOICE_TEXT.format(name=voice_id))
    name = voice_preview_name(provider, voice_id, model_id)
    cached = status(repos, name, req.content_hash())
    if cached and not force:
        return cached
    _render(repos, req, name, fallback_voice=None)
    return status(repos, name, req.content_hash())


def preview_key(name: str) -> str:
    return paths.preview(name)
