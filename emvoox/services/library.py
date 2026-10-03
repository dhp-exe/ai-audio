"""Story library: what exists under series/<id>/ and how far each series got.

Read-only scans of the deterministic file layout (naming.py) so the Library page can list every
story, show progress (planned / drafted / directed / mastered / QA) and offer "continue" with the
episodes that still lack a master. Deleting a series removes its folder.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from pipeline import naming
from pipeline import registry as registry_io


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except json.JSONDecodeError:
        return None


def _mtime(p: Path) -> str | None:
    return datetime.fromtimestamp(p.stat().st_mtime, UTC).isoformat(timespec="seconds") if p.exists() else None


def episode_status(sid: str, n: int, plan: dict | None = None) -> dict:
    stems = naming.stems_dir(sid, n)
    qa = _read_json(naming.qa_report_path(sid, n))
    master = naming.master_path(sid, n, "mp3")
    checks = (qa or {}).get("checks", {})
    failed = [k for k, v in checks.items() if isinstance(v, dict) and v.get("ok") is False]
    return {
        "number": n,
        "title": (plan or {}).get("title"),
        "logline": (plan or {}).get("logline"),
        "draft": naming.raw_script_path(sid, n).exists(),
        "direct": naming.parsed_script_path(sid, n).exists(),
        "stems": len(list(stems.glob("*.wav"))) if stems.exists() else 0,
        "master": master.exists(),
        "master_url": f"/api/series/{sid}/master/{n}.mp3" if master.exists() else None,
        "duration_ms": int(checks["duration"]["seconds"] * 1000) if isinstance(checks.get("duration"), dict) and checks["duration"].get("seconds") else None,
        "qa": {"ok": not failed, "failed_checks": failed, "verdict": ((qa or {}).get("human") or {}).get("verdict")} if qa else None,
        "updated_at": _mtime(master) or _mtime(naming.parsed_script_path(sid, n)) or _mtime(naming.raw_script_path(sid, n)),
    }


def series_summary(sid: str) -> dict | None:
    root = naming.series_root(sid)
    story = _read_json(naming.story_json_path(sid))
    bible = _read_json(naming.series_bible_path(sid))
    run = _read_json(root / "pipeline_run.json")
    if not (story or bible or run):
        return None
    reg = registry_io.load()
    ov = (story or {}).get("overview", {})
    planned = len((bible or {}).get("episodes", [])) or (run or {}).get("params", {}).get("episodes", 0)
    eps = [episode_status(sid, n, p) for n, p in ((e["number"], e) for e in (bible or {}).get("episodes", []))] if bible else []
    produced = [e["number"] for e in eps if e["master"]]
    remaining = [e["number"] for e in eps if not e["master"]]
    params = (run or {}).get("params", {})
    roles = []
    for r in (bible or {}).get("roles", []):
        actor = reg.get(r["actor_id"]) if r.get("actor_id") in reg.ids() else None
        roles.append({"role": r["role_name"], "type": r.get("role_type"), "actor": r.get("actor_id"),
                      "actor_name": actor.display_name if actor else None, "assigned_by": r.get("assigned_by")})
    updated = max([x for x in (_mtime(root / "pipeline_run.json"), _mtime(naming.series_bible_path(sid)), _mtime(naming.story_json_path(sid))) if x] or [""])
    return {
        "series_id": sid,
        "title": ov.get("title") or (bible or {}).get("title") or sid,
        "genre": ov.get("genre") or ", ".join((bible or {}).get("genre", []) if isinstance((bible or {}).get("genre"), list) else []),
        "setting": ov.get("setting", ""),
        "total_minutes": ov.get("total_minutes"),
        "logline": (bible or {}).get("logline", ""),
        "mode": (bible or {}).get("mode"),
        "planned": planned,
        "drafted": sum(1 for e in eps if e["draft"]),
        "directed": sum(1 for e in eps if e["direct"]),
        "produced": len(produced),
        "qa_pass": sum(1 for e in eps if e["qa"] and e["qa"]["ok"]),
        "qa_warn": sum(1 for e in eps if e["qa"] and not e["qa"]["ok"]),
        "next_episode": remaining[0] if remaining else None,
        "remaining": remaining,
        "status": "complete" if planned and not remaining else ("in_progress" if produced else "new"),
        "run": {"run_id": run.get("run_id"), "status": run.get("status"), "created_at": run.get("created_at"),
                "finished_at": run.get("finished_at"), "error": run.get("error"), "tts_provider": params.get("tts_provider", "elevenlabs"),
                "tts_model": params.get("tts_model"), "min_sec": params.get("min_sec"), "max_sec": params.get("max_sec")} if run else None,
        "roles": roles,
        "updated_at": updated or None,
    }


def list_series() -> list[dict]:
    out: list[dict] = []
    if naming.SERIES_DIR.exists():
        for d in naming.SERIES_DIR.iterdir():
            if d.is_dir() and not d.name.startswith("."):
                s = series_summary(d.name)
                if s:
                    out.append(s)
    out.sort(key=lambda s: s.get("updated_at") or "", reverse=True)
    return out


def series_detail(sid: str) -> dict | None:
    s = series_summary(sid)
    if not s:
        return None
    bible = _read_json(naming.series_bible_path(sid)) or {}
    plans = {e["number"]: e for e in bible.get("episodes", [])}
    s["story"] = _read_json(naming.story_json_path(sid))
    if s["story"] is None and naming.story_raw_path(sid).exists():
        s["story_raw"] = naming.story_raw_path(sid).read_text(encoding="utf-8")
    s["bible"] = {k: bible.get(k) for k in ("title", "logline", "premise", "tone", "mode", "protagonist_role", "episode_format")}
    s["episodes"] = [episode_status(sid, n, plans.get(n)) for n in sorted(plans)]
    s["run_state"] = _read_json(naming.series_root(sid) / "pipeline_run.json")
    return s


def delete_series(sid: str) -> None:
    root = naming.series_root(sid)
    if root.exists():
        shutil.rmtree(root)
