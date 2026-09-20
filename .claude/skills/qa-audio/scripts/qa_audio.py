#!/usr/bin/env python3
"""QA gate for an assembled episode (pipeline stage [6]).

CLI
    qa_audio.py --series <id> --episode <n> [--transcribe] [--dry-run]
    qa_audio.py --series <id> --episode <n> --verdict approved|rejected [--reviewer <name>]
                [--lines <ids>] [--notes "..."]

Report: series/<id>/qa/epNN_report.json
    {"checks": {...}, "review_lines": [...], "human": {"verdict", "reviewer", "lines", "notes", "at"}}
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from pipeline import naming  # noqa: E402
from pipeline.config import get_settings  # noqa: E402
from pipeline.schema import EpisodeScript, LineType  # noqa: E402


def check_stems_complete(script: EpisodeScript, stems: Path) -> dict:
    manifest = stems / "render.json"
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        if data.get("batching") == "scene":
            covered = {lid for u in data.get("units", []) for lid in u.get("line_ids", [])}
            missing = [u["id"] for u in data.get("units", []) if not (stems / u["path"]).exists()]
            uncovered = [ln.line_id for _, ln in script.all_lines() if ln.type != LineType.pause and ln.line_id not in covered]
            return {"ok": not missing and not uncovered, "missing": missing + uncovered, "batching": "scene", "units": len(data.get("units", []))}
    missing = [ln.line_id for _, ln in script.all_lines() if ln.type != LineType.pause
               and not (stems / naming.stem_name_from_line_id(ln.line_id, ln.character_id, ln.type.value)).exists()]
    return {"ok": not missing, "missing": missing, "batching": "line"}


def check_duration(script: EpisodeScript, master: Path) -> dict:
    if not master.exists():
        return {"ok": False, "error": "master not found"}
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(master)],
                         capture_output=True, text=True, check=True).stdout.strip()
    sec = float(out)
    target = script.target_duration_sec
    return {"ok": 0.6 * target <= sec <= 1.5 * target, "seconds": round(sec, 1), "target": target}


def check_loudness(master: Path, lufs: float, tp: float) -> dict:
    if not master.exists():
        return {"ok": False, "error": "master not found"}
    res = subprocess.run(["ffmpeg", "-v", "info", "-nostats", "-i", str(master), "-af", "ebur128=peak=true", "-f", "null", "-"],
                         capture_output=True, text=True)
    log = res.stderr
    m_i = re.search(r"Integrated loudness:\s*I:\s*(-?[\d.]+) LUFS", log)
    m_tp = re.search(r"True peak:\s*Peak:\s*(-?[\d.]+) dBFS", log)
    if not (m_i and m_tp):
        return {"ok": False, "error": "could not parse ebur128 output"}
    i, peak = float(m_i.group(1)), float(m_tp.group(1))
    return {"ok": abs(i - lufs) <= 1.0 and peak <= tp + 0.1, "integrated_lufs": i, "true_peak_dbtp": peak, "target_lufs": lufs, "target_tp": tp}


def check_clipping(stems: Path) -> dict:
    """TODO(Phase 4): per-stem peak via ffmpeg astats; fail > -0.1 dBFS."""
    return {"ok": None, "todo": True}


def check_silence(master: Path) -> dict:
    """TODO(Phase 4): ffmpeg silencedetect=n=-50dB:d=3."""
    return {"ok": None, "todo": True}


def check_transcript_diff(script: EpisodeScript, stems: Path) -> dict:
    """TODO(Phase 4): STT each stem (ElevenLabs Scribe, Vietnamese), WER vs line.text, flag > 15%."""
    return {"ok": None, "todo": True}


def review_lines(script: EpisodeScript) -> list[str]:
    return [ln.line_id for _, ln in script.all_lines() if ln.type != LineType.pause
            and (ln.emotional_intensity >= 9 or (ln.is_monologue() and ln.emotional_intensity >= 7))]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--series", required=True)
    ap.add_argument("--episode", type=int, required=True)
    ap.add_argument("--transcribe", action="store_true")
    ap.add_argument("--verdict", choices=["approved", "rejected"])
    ap.add_argument("--reviewer", default=None)
    ap.add_argument("--lines", default=None)
    ap.add_argument("--notes", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    s = get_settings()
    report_path = naming.qa_report_path(a.series, a.episode)
    report = json.loads(report_path.read_text()) if report_path.exists() else {"checks": {}, "review_lines": [], "human": None}

    if a.verdict:
        report["human"] = {"verdict": a.verdict, "reviewer": a.reviewer, "lines": a.lines.split(",") if a.lines else [],
                           "notes": a.notes, "at": datetime.now(UTC).isoformat(timespec="seconds")}
    else:
        script = EpisodeScript.model_validate_json(naming.parsed_script_path(a.series, a.episode).read_text(encoding="utf-8"))
        stems = naming.stems_dir(a.series, a.episode)
        master = naming.master_path(a.series, a.episode)
        report["checks"] = {
            "stems_complete": check_stems_complete(script, stems),
            "duration": check_duration(script, master),
            "loudness": check_loudness(master, s.loudness_lufs, s.true_peak_dbtp),
            "clipping": check_clipping(stems),
            "silence": check_silence(master),
        }
        if a.transcribe:
            report["checks"]["transcript_diff"] = check_transcript_diff(script, stems)
        report["review_lines"] = review_lines(script)
        report["generated_at"] = datetime.now(UTC).isoformat(timespec="seconds")

    if not a.dry_run:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    failed = [k for k, v in report["checks"].items() if v.get("ok") is False]
    print(json.dumps({"ok": not failed, "failed_checks": failed, "review_lines": len(report["review_lines"]),
                      "human": (report["human"] or {}).get("verdict"), "path": str(report_path)}))
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
