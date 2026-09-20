---
name: assemble-audio
description: Build the episode master. Voice-only in this phase (ENABLE_BGM=false, ENABLE_SFX=false): concatenates speech stems in script order with configurable inter-line silence (300-500 ms), scene gaps, stereo -16 LUFS loudness normalization, and exports WAV + MP3 192 kbps. Writes a timeline JSON first so layout is diffable. Use after generate-voice and before qa-audio.
---

# assemble-audio

Stage [5]. Two sub-steps:

1. `timeline`: stems + parsed script -> `timelines/epNN_timeline.json`. Sequential placement from
   **measured** stem durations (ffprobe); silence clips between lines; no overlap (D9).
2. `render`: timeline -> `masters/epNN_master.wav` (44.1 kHz stereo) + `masters/epNN_master.mp3`
   (192 kbps) through one FFmpeg `filter_complex` (apad + concat + loudnorm).

```bash
python .claude/skills/assemble-audio/scripts/assemble_audio.py --series demo --episode 1
python .claude/skills/assemble-audio/scripts/assemble_audio.py --series demo --episode 1 --timeline-only
python .claude/skills/assemble-audio/scripts/assemble_audio.py --series demo --episode 1 --render-only
python .claude/skills/assemble-audio/scripts/assemble_audio.py --series demo --episode 1 --padding-ms 350 --fixed-padding
```

## Padding policy (D5/D9)

- Default: honour the Director's `pause_after_ms`, clamped to `[AI_AUDIO_PADDING_MIN_MS,
  AI_AUDIO_PADDING_MAX_MS]` = [300, 500].
- `--fixed-padding` (or `AI_AUDIO_USE_DIRECTOR_PAUSES=false`): every gap = `--padding-ms`
  (`AI_AUDIO_PADDING_MS`, default 400).
- `pause` lines add their own `pause_after_ms` (uncapped) so the Director can hold a beat.
- Scene boundary adds `AI_AUDIO_SCENE_GAP_MS` (800).

## BGM / SFX

Disabled by config. If `ENABLE_BGM` or `ENABLE_SFX` is true the script exits with a clear
message: the mixing renderer (ducking, ambience beds) is scheduled for a later phase.
