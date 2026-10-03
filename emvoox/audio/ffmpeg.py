"""FFmpeg/ffprobe helpers shared by the Sound Engineer and the QA Critic. Requires both on PATH."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path


class AudioToolError(RuntimeError):
    pass


def have_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def duration_ms(path: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return int(round(float(out) * 1000))


def measure_loudnorm(path: Path, lufs: float, tp: float) -> dict:
    """First loudnorm pass: the measured_* values a second pass needs to land exactly on target."""
    res = subprocess.run(
        ["ffmpeg", "-v", "info", "-nostats", "-i", str(path), "-af",
         f"loudnorm=I={lufs}:TP={tp}:LRA=11:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", res.stderr)
    if not m:
        raise AudioToolError("loudnorm measurement failed:\n" + res.stderr[-800:])
    return json.loads(m.group(0))


def measure_ebur128(path: Path) -> dict | None:
    """Integrated loudness (LUFS), true peak (dBTP) and loudness range of a file; None if unparseable."""
    res = subprocess.run(["ffmpeg", "-v", "info", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
                         capture_output=True, text=True)
    log = res.stderr
    m_i = re.search(r"Integrated loudness:\s*I:\s*(-?[\d.]+) LUFS", log)
    m_tp = re.search(r"True peak:\s*Peak:\s*(-?[\d.]+|-?inf) dBFS", log)
    m_lra = re.search(r"Loudness range:\s*LRA:\s*(-?[\d.]+) LU", log)
    if not (m_i and m_tp):
        return None
    peak = float("-inf") if "inf" in m_tp.group(1) else float(m_tp.group(1))
    return {"integrated_lufs": float(m_i.group(1)), "true_peak_dbtp": peak, "lra": float(m_lra.group(1)) if m_lra else None}


def peak_stats(path: Path) -> dict:
    """Sample peak and RMS level of a stem in dBFS (ffmpeg astats). A silent file reports -inf."""
    res = subprocess.run(["ffmpeg", "-v", "info", "-nostats", "-i", str(path), "-af", "astats=metadata=0:measure_perchannel=none", "-f", "null", "-"],
                         capture_output=True, text=True)

    def grab(label: str) -> float:
        m = re.search(label + r":\s*(-?[\d.]+|-?inf)", res.stderr)
        if not m:
            return float("nan")
        return float("-inf") if "inf" in m.group(1) else float(m.group(1))

    flat = re.search(r"Flat factor:\s*(-?[\d.]+|-?inf|nan)", res.stderr)
    return {"peak_db": grab("Peak level dB"), "rms_db": grab("RMS level dB"),
            "flat_factor": float(flat.group(1)) if flat and flat.group(1) not in ("nan", "inf", "-inf") else 0.0}


def detect_silences(path: Path, *, noise_db: float = -50.0, min_s: float = 1.5) -> list[tuple[float, float]]:
    """(start_s, duration_s) of every silent stretch at least ``min_s`` long."""
    res = subprocess.run(["ffmpeg", "-v", "info", "-nostats", "-i", str(path), "-af", f"silencedetect=n={noise_db}dB:d={min_s}", "-f", "null", "-"],
                         capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start:\s*(-?[\d.]+)", res.stderr)]
    durs = [float(x) for x in re.findall(r"silence_duration:\s*([\d.]+)", res.stderr)]
    return list(zip(starts, durs, strict=False))


def run(cmd: list[str]) -> None:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise AudioToolError(f"{cmd[0]} failed ({res.returncode}): {res.stderr[-600:]}")
