#!/usr/bin/env python3
"""Episode assembly, voice-only: stems -> timeline -> stereo master (pipeline stage [5]).

CLI
    assemble_audio.py --series <id> --episode <n> [--timeline-only | --render-only]
                      [--padding-ms 400] [--fixed-padding] [--scene-gap-ms 800]
                      [--lufs -16] [--true-peak -1.5] [--mp3-bitrate 192k] [--dry-run]

Decisions: D5/D6 BGM+SFX disabled, D8 stereo -16 LUFS WAV + MP3 192k, D9 sequential, no overlap.
Requires ffmpeg/ffprobe on PATH.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from pipeline import naming  # noqa: E402
from pipeline.config import get_settings  # noqa: E402
from pipeline.schema import EpisodeScript, LineType, Timeline, TimelineClip  # noqa: E402

TAIL_MS = 500  # silence after the last line so players don't clip the final word


def duration_ms(path: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return int(round(float(out) * 1000))


def load_units(stems: Path) -> dict[str, dict]:
    """line_id -> render unit from stems/epNN/render.json (scene batching). Empty when the episode was
    rendered per line (or before manifests existed)."""
    p = stems / "render.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if data.get("batching") != "scene":
        return {}
    return {lid: u for u in data.get("units", []) for lid in u.get("line_ids", [])}


def build_timeline(script: EpisodeScript, stems: Path, *, padding_ms: int, padding_min: int, padding_max: int,
                   use_director_pauses: bool, scene_gap_ms: int) -> Timeline:
    clips: list[TimelineClip] = []
    missing: list[str] = []
    cursor = 0
    units = load_units(stems)  # scene batching: several lines share one stem
    placed: set[str] = set()

    def add_silence(ms: int, scene_id: str, line_id: str | None = None) -> None:
        nonlocal cursor
        if ms <= 0:
            return
        clips.append(TimelineClip(kind="silence", start_ms=cursor, duration_ms=ms, line_id=line_id, scene_id=scene_id))
        cursor += ms

    for si, scene in enumerate(script.scenes):
        if si > 0:
            add_silence(scene_gap_ms, scene.scene_id)
        for line in scene.lines:
            if line.type == LineType.pause:
                add_silence(line.pause_after_ms, scene.scene_id, line.line_id)
                continue
            unit = units.get(line.line_id)
            if unit:
                if unit["id"] in placed:
                    continue  # already covered by its chunk
                stem = stems / unit["path"]
                unit_id, pause = unit["id"], unit.get("pause_after_ms", line.pause_after_ms)
                placed.add(unit_id)
            else:
                stem = stems / naming.stem_name_from_line_id(line.line_id, line.character_id, line.type.value)
                unit_id, pause = line.line_id, line.pause_after_ms
            if not stem.exists():
                missing.append(unit_id)
                continue
            d = duration_ms(stem)
            clips.append(TimelineClip(kind="stem", path=str(stem), start_ms=cursor, duration_ms=d,
                                      line_id=unit_id, scene_id=scene.scene_id))
            cursor += d
            gap = max(padding_min, min(padding_max, pause)) if use_director_pauses else padding_ms
            add_silence(gap, scene.scene_id, unit_id)

    if missing:
        raise SystemExit(f"missing stems for {len(missing)} lines (run generate-voice): {missing[:5]}{'...' if len(missing) > 5 else ''}")
    # replace the trailing gap with a fixed tail
    if clips and clips[-1].kind == "silence":
        cursor -= clips[-1].duration_ms
        clips.pop()
    add_silence(TAIL_MS, script.scenes[-1].scene_id)
    return Timeline(series_id=script.series_id, episode_number=script.episode_number, total_duration_ms=cursor, clips=clips)


def measure_loudness(path: Path, lufs: float, tp: float) -> dict:
    """First loudnorm pass: returns the measured_* values needed for an accurate second pass."""
    res = subprocess.run(
        ["ffmpeg", "-v", "info", "-nostats", "-i", str(path), "-af",
         f"loudnorm=I={lufs}:TP={tp}:LRA=11:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", res.stderr)
    if not m:
        raise SystemExit("loudnorm measurement failed:\n" + res.stderr[-800:])
    return json.loads(m.group(0))


def render_voice_only(tl: Timeline, out_wav: Path, out_mp3: Path, *, lufs: float, tp: float, mp3_bitrate: str) -> None:
    """Two ffmpeg passes: (1) pad + concat to a temp WAV, (2) two-pass loudnorm (measure, then apply
    with measured_* values and linear=true) to the stereo master; then MP3."""
    stems = [c for c in tl.clips if c.kind == "stem"]
    if not stems:
        raise SystemExit("timeline has no stems")
    # silence following each stem = next stem start - this stem end (covers pauses + scene gaps)
    pads: list[int] = []
    for i, c in enumerate(stems):
        end = c.start_ms + c.duration_ms
        nxt = stems[i + 1].start_ms if i + 1 < len(stems) else tl.total_duration_ms
        pads.append(max(0, nxt - end))
    lead = stems[0].start_ms

    parts: list[str] = []
    labels: list[str] = []
    for i, (c, pad) in enumerate(zip(stems, pads, strict=True)):
        f = f"[{i}:a]aformat=sample_fmts=s16:sample_rates=44100:channel_layouts=mono"
        if i == 0 and lead > 0:
            f += f",adelay={lead}|{lead}"
        f += f",apad=pad_dur={pad / 1000:.3f}[a{i}]"
        parts.append(f)
        labels.append(f"[a{i}]")
    parts.append("".join(labels) + f"concat=n={len(stems)}:v=0:a=1[out]")

    filter_path = out_wav.parent / f"ep{tl.episode_number:02d}_filter.txt"
    concat_path = out_wav.parent / f"ep{tl.episode_number:02d}_concat.wav"
    filter_path.write_text(";\n".join(parts) + "\n")
    try:
        cmd = ["ffmpeg", "-v", "error", "-y"]
        for c in stems:
            cmd += ["-i", c.path]
        cmd += ["-filter_complex_script", str(filter_path), "-map", "[out]", "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", str(concat_path)]
        subprocess.run(cmd, check=True)

        m = measure_loudness(concat_path, lufs, tp)
        ln = (f"loudnorm=I={lufs}:TP={tp}:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
              f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(concat_path), "-af",
                        f"{ln},aformat=channel_layouts=stereo", "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(out_wav)], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(out_wav), "-c:a", "libmp3lame", "-b:a", mp3_bitrate, str(out_mp3)], check=True)
    finally:
        filter_path.unlink(missing_ok=True)
        concat_path.unlink(missing_ok=True)


def render_mixed(tl: Timeline, *_a, **_k) -> None:
    """Mixing renderer (BGM beds, ambience, SFX, sidechain ducking). Deferred: see plan Phase 5."""
    raise SystemExit("ENABLE_BGM/ENABLE_SFX are true but the mixing renderer is not implemented in this phase; set both to false")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--series", required=True)
    ap.add_argument("--episode", type=int, required=True)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--timeline-only", action="store_true")
    g.add_argument("--render-only", action="store_true")
    ap.add_argument("--padding-ms", type=int, default=None)
    ap.add_argument("--fixed-padding", action="store_true", help="ignore Director pauses, use --padding-ms everywhere")
    ap.add_argument("--scene-gap-ms", type=int, default=None)
    ap.add_argument("--lufs", type=float, default=None)
    ap.add_argument("--true-peak", type=float, default=None)
    ap.add_argument("--mp3-bitrate", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    s = get_settings()
    if s.enable_bgm or s.enable_sfx:
        render_mixed(None)
    lufs = a.lufs if a.lufs is not None else s.loudness_lufs
    tp = a.true_peak if a.true_peak is not None else s.true_peak_dbtp
    tl_path = naming.timeline_path(a.series, a.episode)

    if not a.render_only:
        script = EpisodeScript.model_validate_json(naming.parsed_script_path(a.series, a.episode).read_text(encoding="utf-8"))
        tl = build_timeline(
            script, naming.stems_dir(a.series, a.episode),
            padding_ms=a.padding_ms if a.padding_ms is not None else s.padding_ms,
            padding_min=s.padding_min_ms, padding_max=s.padding_max_ms,
            use_director_pauses=s.use_director_pauses and not a.fixed_padding,
            scene_gap_ms=a.scene_gap_ms if a.scene_gap_ms is not None else s.scene_gap_ms,
        )
        if a.dry_run:
            print(tl.model_dump_json(indent=2))
        else:
            tl_path.parent.mkdir(parents=True, exist_ok=True)
            tl_path.write_text(tl.model_dump_json(indent=2))
    else:
        tl = Timeline.model_validate_json(tl_path.read_text())

    summary = {"ok": True, "total_ms": tl.total_duration_ms,
               "stems": sum(1 for c in tl.clips if c.kind == "stem"),
               "silence_ms": sum(c.duration_ms for c in tl.clips if c.kind == "silence")}
    if a.timeline_only or a.dry_run:
        print(json.dumps({**summary, "timeline": str(tl_path)}))
        return 0

    out_wav = naming.master_path(a.series, a.episode)
    out_mp3 = naming.master_path(a.series, a.episode, "mp3")
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    render_voice_only(tl, out_wav, out_mp3, lufs=lufs, tp=tp, mp3_bitrate=a.mp3_bitrate or s.mp3_bitrate)
    print(json.dumps({**summary, "master_wav": str(out_wav), "master_mp3": str(out_mp3)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
