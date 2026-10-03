"""Master rendering: timeline -> stereo master at the loudness target (D8).

Three FFmpeg stages:
  1. pad + concat the stems into one mono speech track (exactly the timeline)
  2. optional mix: a looped music bed ducked under the speech (sidechain compression) and
     sound-effect clips placed at their offsets
  3. two-pass loudnorm (measure, then apply with the measured values, linear) -> stereo WAV, then MP3

BGM and SFX only run when the caller passes them; with ENABLE_BGM / ENABLE_SFX off the result is
clean speech (D5/D6).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from emvoox.audio.ffmpeg import AudioToolError, measure_loudnorm, run
from emvoox.contracts.production import Timeline


@dataclass
class SfxPlacement:
    path: Path
    at_ms: int
    gain_db: float = -6.0


def _concat_speech(tl: Timeline, out: Path, filter_file: Path) -> None:
    stems = [c for c in tl.clips if c.kind == "stem"]
    if not stems:
        raise AudioToolError("timeline has no stems")
    # silence following each stem = next stem start - this stem end (covers pauses + scene gaps)
    pads: list[int] = []
    for i, c in enumerate(stems):
        end = c.start_ms + c.duration_ms
        nxt = stems[i + 1].start_ms if i + 1 < len(stems) else tl.total_duration_ms
        pads.append(max(0, nxt - end))
    lead = stems[0].start_ms
    parts: list[str] = []
    labels: list[str] = []
    for i, pad in enumerate(pads):
        f = f"[{i}:a]aformat=sample_fmts=s16:sample_rates=44100:channel_layouts=mono"
        if i == 0 and lead > 0:
            f += f",adelay={lead}|{lead}"
        f += f",apad=pad_dur={pad / 1000:.3f}[a{i}]"
        parts.append(f)
        labels.append(f"[a{i}]")
    parts.append("".join(labels) + f"concat=n={len(stems)}:v=0:a=1[out]")
    filter_file.write_text(";\n".join(parts) + "\n")
    cmd = ["ffmpeg", "-v", "error", "-y"]
    for c in stems:
        cmd += ["-i", str(c.path)]
    cmd += ["-filter_complex_script", str(filter_file), "-map", "[out]", "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", str(out)]
    run(cmd)


def _mix_bed(speech: Path, out: Path, *, bgm: Path | None, bgm_gain_db: float, sfx: list[SfxPlacement], total_ms: int) -> None:
    """Speech + ducked music bed + SFX -> mono mix of the same length as the speech."""
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(speech)]
    filters: list[str] = []
    mix_inputs = ["[sp]"]
    idx = 1
    total_s = total_ms / 1000
    if bgm is not None:
        cmd += ["-stream_loop", "-1", "-i", str(bgm)]
        fade_out = max(0.0, total_s - 1.5)
        filters.append("[0:a]asplit=2[sp][key]")
        filters.append(f"[{idx}:a]aformat=sample_rates=44100:channel_layouts=mono,atrim=0:{total_s:.3f},volume={bgm_gain_db}dB,"
                       f"afade=t=in:st=0:d=1.0,afade=t=out:st={fade_out:.3f}:d=1.5[bed]")
        # the bed drops whenever someone speaks and comes back up in the gaps
        filters.append("[bed][key]sidechaincompress=threshold=0.02:ratio=8:attack=15:release=350[duck]")
        mix_inputs.append("[duck]")
        idx += 1
    else:
        filters.append("[0:a]anull[sp]")
    for s in sfx:
        cmd += ["-i", str(s.path)]
        filters.append(f"[{idx}:a]aformat=sample_rates=44100:channel_layouts=mono,volume={s.gain_db}dB,adelay={max(0, s.at_ms)}|{max(0, s.at_ms)}[fx{idx}]")
        mix_inputs.append(f"[fx{idx}]")
        idx += 1
    filters.append("".join(mix_inputs) + f"amix=inputs={len(mix_inputs)}:duration=first:normalize=0[mix]")
    cmd += ["-filter_complex", ";".join(filters), "-map", "[mix]", "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", str(out)]
    run(cmd)


def render_master(tl: Timeline, out_wav: Path, out_mp3: Path, *, lufs: float, tp: float, mp3_bitrate: str,
                  bgm: Path | None = None, bgm_gain_db: float = -20.0, sfx: list[SfxPlacement] | None = None) -> dict:
    """Render the timeline to the stereo WAV master and its MP3. Returns the loudnorm measurement of the mix."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    stem = f"ep{tl.episode_number:02d}"
    filter_file = out_wav.parent / f"{stem}_filter.txt"
    speech = out_wav.parent / f"{stem}_speech.wav"
    mixed = out_wav.parent / f"{stem}_mix.wav"
    try:
        _concat_speech(tl, speech, filter_file)
        source = speech
        if bgm is not None or sfx:
            _mix_bed(speech, mixed, bgm=bgm, bgm_gain_db=bgm_gain_db, sfx=sfx or [], total_ms=tl.total_duration_ms)
            source = mixed
        m = measure_loudnorm(source, lufs, tp)
        ln = (f"loudnorm=I={lufs}:TP={tp}:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
              f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
        run(["ffmpeg", "-v", "error", "-y", "-i", str(source), "-af", f"{ln},aformat=channel_layouts=stereo",
             "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(out_wav)])
        run(["ffmpeg", "-v", "error", "-y", "-i", str(out_wav), "-c:a", "libmp3lame", "-b:a", mp3_bitrate, str(out_mp3)])
        return m
    finally:
        for p in (filter_file, speech, mixed):
            p.unlink(missing_ok=True)
