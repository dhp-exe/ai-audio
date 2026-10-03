"""Productions library: every series, how far it got, and what each episode looks like.

Read-only views over the repositories for the Dashboard, Productions and Approvals pages. Older
artifacts from before the Emvoox refactor (QA reports without status, run files with ``jobs``)
are shown, not rejected.
"""

from __future__ import annotations

from datetime import UTC, datetime

from emvoox import paths
from emvoox.contracts.release import ReleasePackage
from emvoox.repositories import Repositories


def _iso(t: datetime | None) -> str | None:
    return t.isoformat(timespec="seconds") if t else None


def qa_brief(raw: dict | None) -> dict | None:
    if not raw:
        return None
    if "status" in raw:
        logs = raw.get("error_logs") or []
        return {"status": raw.get("status"), "score": raw.get("score"), "attempt": raw.get("attempt", 0), "issues": len(logs),
                "codes": sorted({i.get("code") for i in logs if i.get("code")})}
    checks = raw.get("checks") or {}
    failed = [k for k, v in checks.items() if isinstance(v, dict) and v.get("ok") is False]
    return {"status": None, "score": None, "attempt": 0, "issues": len(failed), "codes": failed, "legacy": True}


def run_brief(run: dict | None) -> dict | None:
    if not run:
        return None
    p = run.get("params") or {}
    return {"run_id": run.get("run_id"), "status": run.get("status"), "created_at": run.get("created_at"), "finished_at": run.get("finished_at"),
            "error": run.get("error"), "tts_provider": p.get("tts_provider", "elevenlabs"), "tts_model": p.get("tts_model"),
            "llm_provider": p.get("llm_provider") or (run.get("engine") or {}).get("llm"), "min_sec": p.get("min_sec"), "max_sec": p.get("max_sec")}


def run_summary(run: dict, title: str | None = None) -> dict:
    steps = run.get("steps") or run.get("jobs") or []
    done = sum(1 for s in steps if s.get("status") in ("done", "warn", "failed", "skipped", "waiting", "approved", "rejected"))
    current = next((s for s in steps if s.get("status") == "running"), None)
    return {"run_id": run.get("run_id"), "series_id": run.get("series_id"), "title": title or run.get("series_id"), "status": run.get("status"),
            "created_at": run.get("created_at"), "finished_at": run.get("finished_at"), "progress": {"done": done, "total": len(steps)},
            "current_step": current.get("id") if current else None, "current_agent": current.get("agent") if current else None,
            "cost_usd": round(((run.get("totals") or {}).get("cost_usd") or 0.0), 6),
            "episodes": sorted({s.get("episode") for s in steps if s.get("episode")})}


def episode_status(repos: Repositories, sid: str, n: int, plan: dict | None = None) -> dict:
    s = repos.series
    master = s.has_master(sid, n, "mp3")
    mastered = repos.docs.get(paths.mastered(sid, n)) or {}
    rel = s.load_release(sid, n)
    qa_raw = s.load_qa_raw(sid, n)
    dur = mastered.get("duration_ms")
    if dur is None and qa_raw and isinstance((qa_raw.get("checks") or {}).get("duration"), dict):
        sec = qa_raw["checks"]["duration"].get("seconds")
        dur = int(sec * 1000) if sec else None
    return {
        "number": n, "title": (plan or {}).get("title"), "logline": (plan or {}).get("logline"), "hook_score": (plan or {}).get("hook_score"),
        "draft": s.has_raw_script(sid, n), "direct": s.has_script(sid, n), "stems": s.count_stems(sid, n), "master": master,
        "master_url": f"/api/series/{sid}/master/{n}.mp3" if master else None, "duration_ms": dur,
        "qa": qa_brief(qa_raw),
        "release": {"state": rel.state, "reviewer": rel.decision.reviewer if rel.decision else None,
                    "at": rel.decision.at if rel.decision else rel.updated_at} if rel else None,
        "updated_at": s.mtime(paths.master(sid, n, "mp3")) or s.mtime(paths.parsed_script(sid, n)) or s.mtime(paths.raw_script(sid, n)),
    }


def _series_cost(repos: Repositories, sid: str) -> float:
    from emvoox.telemetry.usage import normalize  # prices pre-refactor ledger rows too

    rows = (normalize(sid, r) for r in repos.docs.read_log(paths.series_run_log(sid)))
    return round(sum(r["cost_usd"] for r in rows if r and r["kind"] != "agent"), 6)


def series_summary(repos: Repositories, sid: str, *, active_run: str | None = None) -> dict | None:
    s = repos.series
    story = repos.docs.get(paths.story(sid))
    bible = repos.docs.get(paths.bible(sid))
    run = repos.runs.load_raw(sid)
    if not (story or bible or run):
        return None
    reg = repos.registry.load()
    cast = repos.docs.get(paths.cast(sid)) or {}
    members = {m["actor_id"]: m for m in cast.get("members", [])}
    ov = (story or {}).get("overview", {}) if isinstance(story, dict) else {}
    bible = bible if isinstance(bible, dict) else {}
    planned = len(bible.get("episodes", [])) or ((run or {}).get("params") or {}).get("episodes", 0)
    eps = [episode_status(repos, sid, e["number"], e) for e in bible.get("episodes", [])]
    produced = [e["number"] for e in eps if e["master"]]
    remaining = [e["number"] for e in eps if not e["master"]]
    roles = []
    for r in bible.get("roles", []):
        actor = reg.get(r["actor_id"]) if r.get("actor_id") in reg.ids() else None
        m = members.get(r.get("actor_id")) or {}
        roles.append({"role": r["role_name"], "type": r.get("role_type"), "actor": r.get("actor_id"), "actor_name": actor.display_name if actor else None,
                      "assigned_by": r.get("assigned_by"), "provider": m.get("provider"), "voice": m.get("voice_id"), "voice_source": m.get("voice_source")})
    stamps = [x for x in (s.mtime(paths.run_state(sid)), s.mtime(paths.bible(sid)), s.mtime(paths.story(sid))) if x]
    releases = [e["release"]["state"] for e in eps if e["release"]]
    genre = ov.get("genre") or (", ".join(bible.get("genre", [])) if isinstance(bible.get("genre"), list) else "")
    return {
        "series_id": sid, "title": ov.get("title") or bible.get("title") or sid, "genre": genre, "setting": ov.get("setting", ""),
        "logline": bible.get("logline", ""), "mode": bible.get("mode"), "theme_category": bible.get("theme_category"), "media": "audio",
        "planned": planned, "drafted": sum(1 for e in eps if e["draft"]), "directed": sum(1 for e in eps if e["direct"]), "produced": len(produced),
        "approved": releases.count("approved"), "awaiting": releases.count("awaiting_approval"), "needs_review": releases.count("needs_review"),
        "qa_pass": sum(1 for e in eps if e["qa"] and (e["qa"]["status"] == "PASS" or (e["qa"].get("legacy") and not e["qa"]["issues"]))),
        "qa_flagged": sum(1 for e in eps if e["qa"] and (e["qa"]["status"] == "FLAGGED" or (e["qa"].get("legacy") and e["qa"]["issues"]))),
        "next_episode": remaining[0] if remaining else None, "remaining": remaining,
        "status": "complete" if planned and not remaining else ("in_progress" if produced else "new"),
        "run": run_brief(run), "roles": roles, "updated_at": max(stamps) if stamps else None, "active_run": active_run,
        "cost_usd": _series_cost(repos, sid), "duration_ms_total": sum(e["duration_ms"] or 0 for e in eps if e["master"]),
    }


def list_series(repos: Repositories, active: dict[str, str] | None = None) -> list[dict]:
    out = []
    for sid in repos.series.list_ids():
        s = series_summary(repos, sid, active_run=(active or {}).get(sid))
        if s:
            out.append(s)
    out.sort(key=lambda s: s.get("updated_at") or "", reverse=True)
    return out


def series_detail(repos: Repositories, sid: str, *, active_run: str | None = None) -> dict | None:
    s = series_summary(repos, sid, active_run=active_run)
    if not s:
        return None
    bible = repos.docs.get(paths.bible(sid)) or {}
    plans = {e["number"]: e for e in bible.get("episodes", [])}
    s["story"] = repos.docs.get(paths.story(sid))
    if s["story"] is None:
        raw = repos.series.load_story_raw(sid)
        if raw:
            s["story_raw"] = raw
    s["bible"] = {k: bible.get(k) for k in ("title", "logline", "premise", "tone", "mode", "protagonist_role", "episode_format", "trend_brief_id")}
    s["episodes"] = [episode_status(repos, sid, n, plans.get(n)) for n in sorted(plans)]
    run = repos.runs.load_raw(sid)
    s["run_state"] = run if run and "steps" in run else None
    tb = repos.series.load_trend_brief(sid)
    s["trend_brief"] = tb.model_dump(mode="json") if tb else None
    return s


def episode_detail(repos: Repositories, sid: str, n: int) -> dict | None:
    s = repos.series
    bible = repos.docs.get(paths.bible(sid)) or {}
    plan = next((e for e in bible.get("episodes", []) if e["number"] == n), None)
    directed = repos.docs.get(paths.directed(sid, n))
    qa = s.load_qa_raw(sid, n)
    rel = repos.docs.get(paths.release(sid, n))
    raw = s.load_raw_script(sid, n)
    if not (plan or directed or qa or raw):
        return None
    tl = repos.docs.get(paths.timeline(sid, n)) or {}
    cliff = repos.docs.get(paths.cliffhanger_check(sid, n))
    master = s.has_master(sid, n, "mp3")
    return {"number": n, "plan": plan, "raw_script": raw, "directed": directed, "qa": qa if qa and "status" in qa else None,
            "release": rel, "cliffhanger": cliff, "master_url": f"/api/series/{sid}/master/{n}.mp3" if master else None,
            "timeline_ms": tl.get("total_duration_ms"), "roles": bible.get("roles", [])}


def approvals(repos: Repositories) -> list[dict]:
    items = []
    for sid in repos.series.list_ids():
        title = None
        for pkg in repos.series.list_releases(sid):
            if title is None:
                b = repos.docs.get(paths.bible(sid)) or {}
                title = b.get("title") or sid
            qa = repos.series.load_qa(sid, pkg.episode_number)
            items.append(_approval_item(repos, sid, title, pkg, qa))
    order = {"needs_review": 0, "awaiting_approval": 1, "approved": 2, "rejected": 3}
    items.sort(key=lambda i: (order.get(i["state"], 9), i.get("updated_at") or ""), reverse=False)
    return items


def _approval_item(repos: Repositories, sid: str, title: str, pkg: ReleasePackage, qa) -> dict:
    d = pkg.model_dump(mode="json")
    bible = repos.docs.get(paths.bible(sid)) or {}
    plan = next((e for e in bible.get("episodes", []) if e["number"] == pkg.episode_number), None)
    d.update({"series_title": title, "episode_title": (plan or {}).get("title"),
              "master_url": f"/api/series/{sid}/master/{pkg.episode_number}.mp3" if repos.series.has_master(sid, pkg.episode_number) else None,
              "qa": qa.model_dump(mode="json") if qa else None})
    return d


def delete_series(repos: Repositories, sid: str) -> None:
    repos.series.delete(sid)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
