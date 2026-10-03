"""Short voice previews (~5 s) for the Characters page and the voice pickers.

Rendered once per (provider, model, voice, text) and cached under library/previews/ with a sidecar,
so clicking play never spends credits twice. ElevenLabs voices the plan rejects (402) are rendered
with the actor's fallback premade voice and flagged `placeholder: true`.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from pipeline import naming
from pipeline.casting import guess_gender, placeholder_voice
from pipeline.providers import DEFAULT_MODEL, TtsRequest, get_provider
from pipeline.providers.base import ProviderError
from pipeline.schema import CharacterProfile
from pipeline.text.vi_normalize import normalize_vi

ACTOR_TEXT = "Xin chào, tôi là {name}. Có một chuyện tôi chưa từng kể với ai."  # ~13 words ≈ 5 s
VOICE_TEXT = "Xin chào, đây là giọng {name}. Có một chuyện tôi chưa từng kể với ai."
EL_SETTINGS = {"stability": 0.5, "similarity_boost": 0.75, "use_speaker_boost": True}
GEMINI_STYLE = "Nói tiếng Việt, giọng tự nhiên, ấm áp, tự giới thiệu mình, nhịp nhanh vừa phải, không ngắt nghỉ lâu"


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9-]+", "-", s).strip("-")[:40]


def actor_preview_path(character_id: str, provider: str) -> Path:
    return naming.previews_dir() / f"{character_id}_{provider}.wav"


def voice_preview_path(provider: str, voice_id: str, model_id: str) -> Path:
    return naming.previews_dir() / f"voice_{provider}_{_safe(voice_id)}_{_safe(model_id)}.wav"


def _meta(p: Path) -> dict | None:
    m = naming.meta_path(p)
    if p.exists() and m.exists():
        try:
            return json.loads(m.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
    return None


def _request(provider: str, model_id: str, voice_id: str, text: str) -> TtsRequest:
    settings = dict(EL_SETTINGS) if provider == "elevenlabs" else {"style": GEMINI_STYLE}
    return TtsRequest(provider=provider, model_id=model_id, voice_id=voice_id, text=normalize_vi(text), settings=settings)


def _render(req: TtsRequest, out: Path, *, fallback_voice: str | None) -> dict:
    """Render `req` to `out`; on an ElevenLabs 402 for the voice, render the fallback instead. Returns sidecar data."""
    out.parent.mkdir(parents=True, exist_ok=True)
    engine = get_provider(req.provider)
    used, placeholder, reason = req, False, None
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
            "reason": reason, "rendered_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "duration_ms": info.get("duration_ms"), "characters_billed": info.get("characters_billed"),
            "tokens_out": info.get("tokens_out")}
    naming.meta_path(out).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def status(p: Path, req_hash: str | None = None) -> dict | None:
    """Cached preview info for the UI, or None when nothing (valid) is cached."""
    m = _meta(p)
    if not m or (req_hash and m.get("hash") != req_hash):
        return None
    return {"url": f"/api/previews/{p.name}", "placeholder": bool(m.get("placeholder")), "voice": m["request"]["voice_id"],
            "requested_voice": m.get("requested_voice"), "duration_ms": m.get("duration_ms"), "rendered_at": m.get("rendered_at")}


def actor_preview(profile: CharacterProfile, provider: str, *, force: bool = False, render: bool = True) -> dict | None:
    pv = profile.providers.get(provider)
    if not pv:
        return None
    req = _request(provider, pv.model_id, pv.voice_id, ACTOR_TEXT.format(name=profile.display_name))
    out = actor_preview_path(profile.character_id, provider)
    cached = status(out, req.content_hash())
    if cached and not force:
        return cached
    if not render:
        return None
    fallback = pv.fallback_voice_id or placeholder_voice(profile.gender or guess_gender(profile.voice_description, profile.persona))
    _render(req, out, fallback_voice=fallback)
    return status(out, req.content_hash())


def voice_preview(provider: str, voice_id: str, model_id: str | None = None, *, force: bool = False) -> dict:
    """Preview for a voice picked in a form. Reuses an actor's cached clip of the same engine/voice/model
    when one exists, so a voice is never rendered twice."""
    from pipeline import registry as registry_io

    model_id = model_id or DEFAULT_MODEL[provider]
    for c in registry_io.load().characters:
        pv = c.providers.get(provider)
        if pv and pv.voice_id.lower() == voice_id.lower() and pv.model_id == model_id:
            cached = actor_preview(c, provider, render=False)
            if cached:
                return cached
    req = _request(provider, model_id, voice_id, VOICE_TEXT.format(name=voice_id))
    out = voice_preview_path(provider, voice_id, model_id)
    cached = status(out, req.content_hash())
    if cached and not force:
        return cached
    _render(req, out, fallback_voice=None)
    return status(out, req.content_hash())  # type: ignore[return-value]


def hashed(provider: str, model_id: str, voice_id: str, text: str) -> str:
    return hashlib.sha256(f"{provider}|{model_id}|{voice_id}|{text}".encode()).hexdigest()
