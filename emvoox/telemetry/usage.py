"""Cost and quota views over the run log.

Sources of truth, all local (through the repositories):
- series/<id>/run.log.jsonl and telemetry/run_log.jsonl   one ``UsageRecord`` per LLM call, TTS
                                                          request and agent step (older rows from
                                                          before the refactor are normalized here)
- assets/previews/*.meta.json                             previews rendered before the ledger existed
- telemetry/usage_events.jsonl                            429 / 402 / quota events from the adapters

Plus the vendors' own counters when a key allows it: the ElevenLabs subscription endpoint and the
WaveSpeed balance. Gemini free-tier daily quotas reset at midnight Pacific time; the per-model
status flips back to "ok" by itself once the reset time has passed.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from emvoox.config import get_settings
from emvoox.providers.tts.catalog import GEMINI_MODELS, MODELS, PROVIDER_LABEL, REAL_PROVIDERS
from emvoox.repositories import Repositories
from emvoox.telemetry import pricing

PACIFIC = ZoneInfo("America/Los_Angeles")
AGENT_TITLES = {
    "market_research": "Market Research", "script_writer": "Script Writer", "casting": "Casting & Voice IP Curator", "director": "AI Director",
    "sound_engineer": "Sound Engineer", "qa_critic": "QA Critic", "publisher": "Approval Gate & Publisher", "studio": "Studio (previews, auditions)",
}
LLM_LABEL = {"gemini": "Gemini", "wavespeed": "WaveSpeed", "openai": "OpenAI", "anthropic": "Claude", "mock": "Offline mock", "elevenlabs": "ElevenLabs"}

# Documented free-tier defaults, used until the API reports a real value in a 429. Source: the
# quota id seen live on 2026-09-20 (GenerateRequestsPerDayPerProjectPerModel-FreeTier = 10 for TTS).
ASSUMED_LIMITS: dict[str, dict] = {m["id"]: {"requests_per_day": 10, "source": "assumed without billing (seen on gemini-2.5-flash-tts)"} for m in GEMINI_MODELS}
LEGACY_AGENT = {"episodize": "script_writer", "parse_script": "director", "generate_voice": "sound_engineer"}


def _parse_at(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except ValueError:
        return None


def normalize(source: str, r: dict) -> dict | None:
    """One ledger row (new or pre-refactor) -> {at, kind, provider, model, agent, ...} with a cost estimate."""
    at = _parse_at(r.get("at"))
    if not at:
        return None
    if "kind" in r:
        return {**r, "at": at, "series_id": r.get("series_id") or (None if source == "studio" else source), "requests": int(r.get("requests", 1) or 0),
                "tokens_in": int(r.get("tokens_in") or 0), "tokens_out": int(r.get("tokens_out") or 0), "characters": int(r.get("characters") or 0),
                "audio_ms": int(r.get("audio_ms") or 0), "cost_usd": float(r.get("cost_usd") or 0.0), "elapsed_s": float(r.get("elapsed_s") or 0.0)}
    stage = str(r.get("stage") or "")
    agent = LEGACY_AGENT.get(stage.split(".")[0], "studio")
    if stage == "generate_voice":
        provider, model = r.get("provider", "elevenlabs"), r.get("model_id", "?")
        chars, audio = int(r.get("characters_billed") or 0), int(r.get("duration_ms") or 0)
        tin, tout = int(r.get("tokens_in") or 0), int(r.get("tokens_out") or 0)
        return {"at": at, "kind": "tts", "series_id": source, "episode": r.get("episode"), "agent": agent, "skill": "generate_voice", "provider": provider,
                "model": model, "requests": 1, "tokens_in": tin, "tokens_out": tout, "characters": chars, "audio_ms": audio, "elapsed_s": 0.0, "ok": True,
                "cost_usd": pricing.tts_cost(provider, model, characters=chars, audio_ms=audio, tokens_in=tin, tokens_out=tout), "note": "legacy"}
    if r.get("model"):
        tin, tout = int(r.get("prompt_tokens") or 0), int(r.get("output_tokens") or 0) + int(r.get("thinking_tokens") or 0)
        return {"at": at, "kind": "llm", "series_id": source, "episode": r.get("episode"), "agent": agent, "skill": stage, "provider": "gemini",
                "model": r["model"], "requests": 1, "tokens_in": tin, "tokens_out": tout, "characters": 0, "audio_ms": 0,
                "elapsed_s": float(r.get("elapsed_s") or 0.0), "ok": True, "cost_usd": pricing.llm_cost(r["model"], tin, tout), "note": "legacy"}
    return None


def records(repos: Repositories) -> list[dict]:
    out = [n for src, r in repos.telemetry.rows() if (n := normalize(src, r))]
    for d in repos.assets.preview_metas():  # previews rendered before the ledger existed
        if d.get("ledgered"):
            continue
        at = _parse_at(d.get("rendered_at"))
        req = d.get("request") or {}
        if at and req.get("provider"):
            chars, audio, tout = int(d.get("characters_billed") or 0), int(d.get("duration_ms") or 0), int(d.get("tokens_out") or 0)
            out.append({"at": at, "kind": "tts", "series_id": None, "agent": "studio", "skill": "voice_preview", "provider": req["provider"],
                        "model": req.get("model_id", "?"), "requests": 1, "tokens_in": 0, "tokens_out": tout, "characters": chars, "audio_ms": audio,
                        "elapsed_s": 0.0, "ok": True, "note": "legacy preview",
                        "cost_usd": pricing.tts_cost(req["provider"], req.get("model_id", ""), characters=chars, audio_ms=audio, tokens_out=tout)})
    out.sort(key=lambda r: r["at"])
    return out


# ---------------------------------------------------------------------- vendor counters

_el_cache: dict = {"at": 0.0, "data": None}
_ws_cache: dict = {"at": 0.0, "data": None}


def elevenlabs_subscription() -> dict:
    """ElevenLabs' own counters, cached 60 s. Needs the key scope ``user_read``; otherwise reports why."""
    if time.time() - _el_cache["at"] < 60 and _el_cache["data"] is not None:
        return _el_cache["data"]
    s = get_settings()
    if not s.elevenlabs_api_key:
        data: dict = {"available": False, "reason": "ELEVENLABS_API_KEY is not set"}
    else:
        try:
            from elevenlabs.client import ElevenLabs

            sub = ElevenLabs(api_key=s.elevenlabs_api_key).user.subscription.get()
            data = {"available": True, "tier": sub.tier, "status": sub.status, "character_count": sub.character_count,
                    "character_limit": sub.character_limit,
                    "resets_at": (datetime.fromtimestamp(sub.next_character_count_reset_unix, UTC).isoformat(timespec="seconds")
                                  if sub.next_character_count_reset_unix else None),
                    "voice_slots_used": sub.voice_slots_used, "voice_limit": sub.voice_limit,
                    "professional_voice_cloning": bool(sub.can_use_professional_voice_cloning)}
        except Exception as e:  # noqa: BLE001 - 401 missing scope, network, etc.
            msg = str(e)
            data = {"available": False, "reason": ("the API key lacks the user_read permission; regenerate it with user_read to see the vendor's counters"
                                                   if "user_read" in msg else msg[:200])}
    _el_cache.update(at=time.time(), data=data)
    return data


def wavespeed_balance() -> dict:
    """Prepaid WaveSpeed balance in USD, cached 60 s."""
    if time.time() - _ws_cache["at"] < 60 and _ws_cache["data"] is not None:
        return _ws_cache["data"]
    s = get_settings()
    if not s.wavespeed_api_key:
        data: dict = {"available": False, "reason": "WAVESPEED_API_KEY is not set"}
    else:
        try:
            from emvoox.providers.tts.wavespeed import WaveSpeedClient

            data = {"available": True, "balance": round(WaveSpeedClient(s.wavespeed_api_key).balance(), 4)}
        except Exception as e:  # noqa: BLE001
            data = {"available": False, "reason": f"{type(e).__name__}: {str(e)[:160]}"}
    _ws_cache.update(at=time.time(), data=data)
    return data


# ---------------------------------------------------------------------- costs page


def cost_summary(repos: Repositories, now: datetime | None = None, *, vendor_counters: bool = True) -> dict:
    now = now or datetime.now(UTC)
    rows = records(repos)
    paid = [r for r in rows if r["kind"] in ("llm", "tts", "sfx")]
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    def agg(key) -> dict:
        d: dict = defaultdict(lambda: {"cost_usd": 0.0, "requests": 0, "tokens_in": 0, "tokens_out": 0, "characters": 0, "audio_ms": 0,
                                       "elapsed_s": 0.0, "steps": 0})
        for r in rows:
            k = key(r)
            if k is None:
                continue
            a = d[k]
            if r["kind"] == "agent":
                a["elapsed_s"] += r["elapsed_s"]
                a["steps"] += 1
                continue
            a["cost_usd"] += r["cost_usd"]
            a["requests"] += r["requests"]
            a["tokens_in"] += r["tokens_in"]
            a["tokens_out"] += r["tokens_out"]
            a["characters"] += r["characters"]
            a["audio_ms"] += r["audio_ms"]
        return d

    by_provider = [{"provider": k, "label": LLM_LABEL.get(k, PROVIDER_LABEL.get(k, k)), **{x: round(v[x], 6) if x == "cost_usd" else v[x]
                    for x in ("cost_usd", "requests", "tokens_in", "tokens_out", "characters")}}
                   for k, v in agg(lambda r: r.get("provider") if r["kind"] != "agent" else None).items()]
    by_model = [{"provider": k[0], "model": k[1], "kind": k[2], **{x: round(v[x], 6) if x == "cost_usd" else v[x]
                 for x in ("cost_usd", "requests", "tokens_in", "tokens_out", "characters", "audio_ms")}}
                for k, v in agg(lambda r: (r.get("provider"), r.get("model"), r["kind"]) if r["kind"] != "agent" else None).items()]
    by_agent = [{"agent": k, "title": AGENT_TITLES.get(k, k), "cost_usd": round(v["cost_usd"], 6), "requests": v["requests"],
                 "elapsed_s": round(v["elapsed_s"], 2), "steps": v["steps"]} for k, v in agg(lambda r: r.get("agent") or "studio").items()]
    series_rows = []
    for sid, v in agg(lambda r: r.get("series_id")).items():
        bible = repos.series.load_bible(sid) if sid in repos.series.list_ids() else None
        mastered = [m for n in range(1, (len(bible.episodes) if bible else 0) + 1) if (m := repos.series.load_mastered(sid, n))]
        minutes = sum(m.duration_ms for m in mastered) / 60000
        series_rows.append({"series_id": sid, "title": bible.title if bible else sid, "cost_usd": round(v["cost_usd"], 6), "episodes_mastered": len(mastered),
                            "audio_minutes": round(minutes, 2), "cost_per_minute": round(v["cost_usd"] / minutes, 4) if minutes else None})
    days: dict = defaultdict(lambda: {"llm_usd": 0.0, "tts_usd": 0.0})
    for r in paid:
        if r["at"] >= now - timedelta(days=30):
            days[r["at"].date().isoformat()]["llm_usd" if r["kind"] == "llm" else "tts_usd"] += r["cost_usd"]
    by_day = [{"date": (now - timedelta(days=i)).date().isoformat(), **{k: round(v, 6) for k, v in days[(now - timedelta(days=i)).date().isoformat()].items()}}
              for i in range(13, -1, -1)]
    recent = [{**r, "at": r["at"].isoformat(timespec="seconds")} for r in rows[-60:]][::-1]
    totals = {
        "cost_usd": round(sum(r["cost_usd"] for r in paid), 6), "cost_month_usd": round(sum(r["cost_usd"] for r in paid if r["at"] >= month_start), 6),
        "cost_today_usd": round(sum(r["cost_usd"] for r in paid if r["at"] >= day_start), 6),
        "llm_calls": sum(r["requests"] for r in paid if r["kind"] == "llm"), "tts_requests": sum(r["requests"] for r in paid if r["kind"] != "llm"),
        "tokens_in": sum(r["tokens_in"] for r in paid), "tokens_out": sum(r["tokens_out"] for r in paid),
        "characters": sum(r["characters"] for r in paid), "audio_minutes": round(sum(r["audio_ms"] for r in paid) / 60000, 2),
    }
    return {"generated_at": now.isoformat(timespec="seconds"), "currency": "USD", "totals": totals,
            "by_provider": sorted(by_provider, key=lambda x: -x["cost_usd"]), "by_model": sorted(by_model, key=lambda x: -x["cost_usd"]),
            "by_agent": sorted(by_agent, key=lambda x: -x["cost_usd"]), "by_series": sorted(series_rows, key=lambda x: -x["cost_usd"]),
            "by_day": by_day, "recent": recent, "pricing": pricing.price_table(),
            "wavespeed": wavespeed_balance() if vendor_counters else {"available": False, "reason": "not checked"}}


# ---------------------------------------------------------------------- quotas page


def _gemini_day_start(now: datetime) -> datetime:
    local = now.astimezone(PACIFIC)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def quota_summary(repos: Repositories, now: datetime | None = None, *, vendor_counters: bool = True) -> dict:
    now = now or datetime.now(UTC)
    rows = [r for r in records(repos) if r["kind"] != "agent"]
    events = [e for e in repos.telemetry.events() if _parse_at(e.get("at"))]
    g_day = _gemini_day_start(now)
    g_reset = (g_day + timedelta(days=1)).astimezone(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    el = elevenlabs_subscription() if vendor_counters else {"available": False, "reason": "not checked"}
    el_reset = _parse_at(el.get("resets_at")) if el.get("available") else None
    el_period_start = (el_reset - timedelta(days=30)) if el_reset else month_start
    s = get_settings()

    llm_models = sorted({(r["provider"], r["model"]) for r in rows if r["kind"] == "llm" and r["provider"] != "mock"} | {(s.llm_provider, s.llm_model)})
    catalog_rows = [(p, m, "tts") for p in REAL_PROVIDERS for m in MODELS[p]] + [(p, {"id": mid, "label": f"{mid} (LLM)"}, "llm")
                                                                                  for p, mid in llm_models if p != "mock"]
    models: list[dict] = []
    for provider, m, kind in catalog_rows:
        mid = m["id"]
        mine = [r for r in rows if r["provider"] == provider and r["model"] == mid]
        if provider == "gemini":
            period_start, resets_at, period = g_day.astimezone(UTC), g_reset, "day (resets midnight Pacific)"
        elif provider == "elevenlabs":
            period_start, resets_at, period = el_period_start, el_reset, "billing month"
        else:
            period_start, resets_at, period = month_start, None, "calendar month (prepaid balance)"
        in_period = [r for r in mine if r["at"] >= period_start]
        ev = [e for e in events if e.get("provider") == provider and e.get("model") in (mid, mid.replace("-preview", ""), mid.replace("-preview-tts", "-tts"))]
        last_ev = max(ev, key=lambda e: e["at"]) if ev else None
        limit = dict(ASSUMED_LIMITS.get(mid, {})) if kind == "tts" else {}
        status, status_until, note = "ok", None, ""
        for e in sorted(ev, key=lambda e: e["at"], reverse=True):
            at = _parse_at(e["at"])
            if e.get("kind") == "quota_daily":
                if e.get("quota_value"):
                    limit = {"requests_per_day": int(e["quota_value"]), "source": f"reported by the API ({e.get('quota_id')})"}
                if at and _gemini_day_start(at) == g_day and now < g_reset:
                    status, status_until, note = "exhausted", g_reset.isoformat(timespec="seconds"), "daily request quota exhausted"
                break
            if e.get("kind") == "rate_limit":
                until = (at or now) + timedelta(seconds=float(e.get("retry_after_s") or 60))
                if now < until:
                    status, status_until, note = "rate_limited", until.isoformat(timespec="seconds"), "per-minute rate limit"
                break
            if e.get("kind") in ("payment_required", "quota_monthly"):
                if (el_reset is None or now < el_reset) and at and at >= period_start:
                    status, note = "exhausted", e.get("message") or "vendor refused: plan or credits"
                    status_until = el_reset.isoformat(timespec="seconds") if el_reset else None
                break
        requests = sum(r["requests"] for r in in_period)
        over = bool(limit.get("requests_per_day")) and requests >= limit["requests_per_day"]
        if provider == "gemini" and kind == "tts" and over and status == "ok" and now < g_reset:
            status, status_until, note = "exhausted", g_reset.isoformat(timespec="seconds"), "reached the daily request limit (from our own ledger)"
        models.append({
            "provider": provider, "provider_label": f"{LLM_LABEL.get(provider, provider)} LLM" if kind == "llm" else PROVIDER_LABEL.get(provider, provider),
            "model": mid, "label": m["label"], "kind": kind, "period": period, "period_start": period_start.isoformat(timespec="seconds"),
            "resets_at": resets_at.isoformat(timespec="seconds") if resets_at else None, "requests": requests,
            "tokens_in": sum(r["tokens_in"] for r in in_period), "tokens_out": sum(r["tokens_out"] for r in in_period),
            "characters": sum(r["characters"] for r in in_period), "limit": limit or None, "status": status, "status_until": status_until, "note": note,
            "last_call_at": max(r["at"] for r in mine).isoformat(timespec="seconds") if mine else None,
            "last_event": {k: last_ev.get(k) for k in ("at", "kind", "status", "quota_id", "quota_value", "retry_after_s", "message")} if last_ev else None,
            "requests_month": sum(r["requests"] for r in mine if r["at"] >= month_start),
        })
    el_chars = sum(r["characters"] for r in rows if r["provider"] == "elevenlabs" and r["at"] >= el_period_start)
    el_limit_env = os.getenv("ELEVENLABS_MONTHLY_CREDITS")
    ws = wavespeed_balance() if vendor_counters else {"available": False}
    providers = {
        "gemini": {"label": "Gemini", "key": bool(s.gemini_api_key), "resets_at": g_reset.isoformat(timespec="seconds"),
                   "note": "Without billing each Gemini TTS model has a daily request quota; "
                           "counters come from our ledger (Google exposes no usage endpoint)."},
        "elevenlabs": {"label": "ElevenLabs", "key": bool(s.elevenlabs_api_key), "resets_at": el_reset.isoformat(timespec="seconds") if el_reset else None,
                       "credits_used": el.get("character_count") if el.get("available") else el_chars,
                       "credits_limit": el.get("character_limit") if el.get("available") else (int(el_limit_env) if el_limit_env else 10_000),
                       "credits_source": "vendor" if el.get("available")
                       else ("ledger + ELEVENLABS_MONTHLY_CREDITS" if el_limit_env else "ledger + assumed 10,000 credits"),
                       "note": el.get("reason", "")},
        "wavespeed": {"label": "WaveSpeed", "key": bool(s.wavespeed_api_key), "resets_at": None, "balance_usd": ws.get("balance"),
                      "note": ws.get("reason", "prepaid balance in USD")},
    }
    recent_events = sorted(events, key=lambda e: e["at"], reverse=True)[:30]
    return {"generated_at": now.isoformat(timespec="seconds"), "providers": providers, "models": models, "events": recent_events}
