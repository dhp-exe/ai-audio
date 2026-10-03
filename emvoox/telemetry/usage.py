"""Usage and quota monitoring for the two vendors.

Sources of truth, all local:
- series/<id>/run.log.jsonl        one line per LLM or TTS call (tokens / characters, model, time)
- library/previews/*.meta.json     the cached voice previews (one call each)
- library/usage-events.jsonl       429 / 402 responses recorded by the adapters, with the vendor's
                                   quota id, value and retry delay when it sends them

Plus, when the key allows it, ElevenLabs' own subscription endpoint (character_count /
character_limit / next reset). Gemini has no usage endpoint on the free tier, so its counters come
from the ledger and its limits from what the API reported in a 429 (or a documented default).

Gemini free-tier daily quotas reset at midnight Pacific time; ElevenLabs credits reset at the
subscription's `next_character_count_reset_unix`. `summary()` computes a status per model that
flips back to "ok" by itself once the reset time has passed, so a page that polls it stays right.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from pipeline import naming
from pipeline.config import get_settings
from pipeline.providers.catalog import GEMINI_MODELS, MODELS, PROVIDER_LABEL, PROVIDER_NAMES

PACIFIC = ZoneInfo("America/Los_Angeles")
_lock = threading.Lock()

# Documented free-tier defaults, used until the API reports a real value in a 429. Source: the
# quota id seen live on 2026-09-20 (GenerateRequestsPerDayPerProjectPerModel-FreeTier = 10 for TTS).
ASSUMED_LIMITS: dict[str, dict] = {
    **{m["id"]: {"requests_per_day": 10, "source": "assumed without billing (seen on gemini-2.5-flash-tts)"} for m in GEMINI_MODELS},
}


def events_path():
    return naming.LIBRARY_DIR / "usage-events.jsonl"


def record_event(provider: str, model: str, kind: str, *, status: int | None = None, quota_id: str | None = None,
                 quota_value: int | str | None = None, retry_after_s: float | None = None, message: str = "") -> None:
    """Append a vendor limit event. kind: rate_limit | quota_daily | quota_monthly | payment_required | error."""
    try:
        row = {"at": datetime.now(UTC).isoformat(timespec="seconds"), "provider": provider, "model": model, "kind": kind,
               "status": status, "quota_id": quota_id, "quota_value": quota_value, "retry_after_s": retry_after_s,
               "message": message[:300]}
        with _lock:
            p = events_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass  # monitoring must never break a render


def _read_jsonl(p) -> list[dict]:
    rows: list[dict] = []
    if not p.exists():
        return rows
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _parse_at(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except ValueError:
        return None


def calls() -> list[dict]:
    """Every paid call we know about, normalized: {at, provider, model, requests, tokens_in, tokens_out, characters, source}."""
    out: list[dict] = []
    if naming.SERIES_DIR.exists():
        for p in naming.SERIES_DIR.glob("*/run.log.jsonl"):
            for r in _read_jsonl(p):
                at = _parse_at(r.get("at"))
                if not at:
                    continue
                if r.get("stage") == "generate_voice":
                    out.append({"at": at, "provider": r.get("provider", "elevenlabs"), "model": r.get("model_id", "?"), "requests": 1,
                                "tokens_in": r.get("tokens_in") or 0, "tokens_out": r.get("tokens_out") or 0,
                                "characters": r.get("characters_billed") or 0, "source": p.parent.name, "stage": "voice"})
                elif r.get("model"):
                    out.append({"at": at, "provider": "gemini", "model": r["model"], "requests": 1,
                                "tokens_in": (r.get("prompt_tokens") or 0), "tokens_out": (r.get("output_tokens") or 0) + (r.get("thinking_tokens") or 0),
                                "characters": 0, "source": p.parent.name, "stage": r.get("stage", "llm")})
    pv = naming.previews_dir()
    if pv.exists():
        for m in pv.glob("*.meta.json"):
            try:
                d = json.loads(m.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            at = _parse_at(d.get("rendered_at"))
            req = d.get("request") or {}
            if at and req.get("provider"):
                out.append({"at": at, "provider": req["provider"], "model": req.get("model_id", "?"), "requests": 1,
                            "tokens_in": 0, "tokens_out": d.get("tokens_out") or 0, "characters": d.get("characters_billed") or 0,
                            "source": "previews", "stage": "preview"})
    return out


def _gemini_day_start(now: datetime) -> datetime:
    local = now.astimezone(PACIFIC)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


_el_cache: dict = {"at": 0.0, "data": None}


def elevenlabs_subscription() -> dict:
    """ElevenLabs' own counters, cached 60 s. Needs the key scope `user_read`; otherwise reports why."""
    if time.time() - _el_cache["at"] < 60 and _el_cache["data"] is not None:
        return _el_cache["data"]
    s = get_settings()
    data: dict
    if not s.elevenlabs_api_key:
        data = {"available": False, "reason": "ELEVENLABS_API_KEY is not set"}
    else:
        try:
            from elevenlabs.client import ElevenLabs

            sub = ElevenLabs(api_key=s.elevenlabs_api_key).user.subscription.get()
            data = {"available": True, "tier": sub.tier, "status": sub.status, "character_count": sub.character_count,
                    "character_limit": sub.character_limit, "resets_at": datetime.fromtimestamp(sub.next_character_count_reset_unix, UTC).isoformat(timespec="seconds")
                    if sub.next_character_count_reset_unix else None,
                    "voice_slots_used": sub.voice_slots_used, "voice_limit": sub.voice_limit,
                    "professional_voice_cloning": bool(sub.can_use_professional_voice_cloning)}
        except Exception as e:  # noqa: BLE001 - 401 missing scope, network, etc.
            msg = str(e)
            reason = ("the API key lacks the user_read permission; regenerate it with user_read to see the vendor's counters"
                      if "user_read" in msg else msg[:200])
            data = {"available": False, "reason": reason}
    _el_cache.update(at=time.time(), data=data)
    return data


def summary(now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    rows = calls()
    events = [e for e in _read_jsonl(events_path()) if _parse_at(e.get("at"))]
    g_day = _gemini_day_start(now)
    g_reset = (g_day + timedelta(days=1)).astimezone(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    el = elevenlabs_subscription()
    el_reset = _parse_at(el.get("resets_at")) if el.get("available") else None
    el_period_start = (el_reset - timedelta(days=30)) if el_reset else month_start
    s = get_settings()
    el_limit_env = os.getenv("ELEVENLABS_MONTHLY_CREDITS")

    models: list[dict] = []
    tts_ids = {m["id"] for p in PROVIDER_NAMES for m in MODELS[p]}
    llm_models = sorted({r["model"] for r in rows if r["provider"] == "gemini" and r["model"] not in tts_ids} | {s.llm_model})
    catalog_rows = [(p, m) for p in PROVIDER_NAMES for m in MODELS[p]] + [("gemini", {"id": mid, "label": f"{mid} (LLM)"}) for mid in llm_models]
    for provider, m in catalog_rows:
        if True:
            mid = m["id"]
            mine = [r for r in rows if r["provider"] == provider and r["model"] == mid]
            if provider == "gemini":
                period_start, resets_at, period = g_day.astimezone(UTC), g_reset, "day (resets midnight Pacific)"
            else:
                period_start, resets_at, period = el_period_start, el_reset, "billing month"
            in_period = [r for r in mine if r["at"] >= period_start]
            ev = [e for e in events if e.get("provider") == provider and e.get("model") in (mid, mid.replace("-preview", ""), mid.replace("-preview-tts", "-tts"))]
            last_ev = max(ev, key=lambda e: e["at"]) if ev else None
            limit = dict(ASSUMED_LIMITS.get(mid, {}))
            status, status_until, note = "ok", None, ""
            for e in sorted(ev, key=lambda e: e["at"], reverse=True):
                at = _parse_at(e["at"])
                if e.get("kind") == "quota_daily":
                    if e.get("quota_value"):
                        limit = {"requests_per_day": int(e["quota_value"]), "source": f"reported by the API ({e.get('quota_id')})"}
                    if _gemini_day_start(at) == g_day and now < g_reset:
                        status, status_until, note = "exhausted", g_reset.isoformat(timespec="seconds"), "daily request quota exhausted"
                    break
                if e.get("kind") == "rate_limit":
                    until = at + timedelta(seconds=float(e.get("retry_after_s") or 60))
                    if now < until:
                        status, status_until, note = "rate_limited", until.isoformat(timespec="seconds"), "per-minute rate limit"
                    break
                if e.get("kind") in ("payment_required", "quota_monthly"):
                    if provider == "elevenlabs" and (el_reset is None or now < el_reset) and at >= period_start:
                        status, status_until, note = "exhausted", (el_reset.isoformat(timespec="seconds") if el_reset else None), e.get("message") or "vendor refused: plan or credits"
                    break
            requests = sum(r["requests"] for r in in_period)
            characters = sum(r["characters"] for r in in_period)
            if provider == "gemini" and limit.get("requests_per_day") and requests >= limit["requests_per_day"] and status == "ok" and now < g_reset:
                status, status_until, note = "exhausted", g_reset.isoformat(timespec="seconds"), "reached the daily request limit (from our own ledger)"
            models.append({
                "provider": provider, "provider_label": ("Gemini LLM" if mid in llm_models else PROVIDER_LABEL[provider]), "model": mid, "label": m["label"],
                "kind": "llm" if mid in llm_models else "tts",
                "period": period, "period_start": period_start.isoformat(timespec="seconds"),
                "resets_at": resets_at.isoformat(timespec="seconds") if resets_at else None,
                "requests": requests, "tokens_in": sum(r["tokens_in"] for r in in_period), "tokens_out": sum(r["tokens_out"] for r in in_period),
                "characters": characters, "audio_seconds": None,
                "limit": limit or None, "status": status, "status_until": status_until, "note": note,
                "last_call_at": max((r["at"] for r in mine), default=None).isoformat(timespec="seconds") if mine else None,
                "last_event": {k: last_ev.get(k) for k in ("at", "kind", "status", "quota_id", "quota_value", "retry_after_s", "message")} if last_ev else None,
                "requests_month": sum(r["requests"] for r in mine if r["at"] >= month_start),
            })

    el_chars_period = sum(r["characters"] for r in rows if r["provider"] == "elevenlabs" and r["at"] >= el_period_start)
    el_limit = el.get("character_limit") if el.get("available") else (int(el_limit_env) if el_limit_env else 10_000)
    el_used = el.get("character_count") if el.get("available") else el_chars_period
    providers = {
        "gemini": {"label": "Gemini", "key": bool(s.gemini_api_key), "resets_at": g_reset.isoformat(timespec="seconds"),
                   "note": "Without billing on the Gemini project each model has a daily request quota; counters come from our ledger because Google exposes no usage endpoint."},
        "elevenlabs": {"label": "ElevenLabs", "key": bool(s.elevenlabs_api_key), "resets_at": el_reset.isoformat(timespec="seconds") if el_reset else None,
                       "credits_used": el_used, "credits_limit": el_limit,
                       "credits_source": "vendor" if el.get("available") else ("ledger + ELEVENLABS_MONTHLY_CREDITS" if el_limit_env else "ledger + assumed 10,000 credits"),
                       "subscription": el},
    }
    recent_events = sorted(events, key=lambda e: e["at"], reverse=True)[:30]
    return {"generated_at": now.isoformat(timespec="seconds"), "providers": providers, "models": models, "events": recent_events,
            "totals": {"calls_logged": len(rows), "gemini_requests_today": sum(m["requests"] for m in models if m["provider"] == "gemini"),
                       "elevenlabs_characters_period": el_chars_period}}
