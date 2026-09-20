---
name: generate-voice
description: Render one WAV stem per line of a parsed episode via the TTS provider adapter (ElevenLabs eleven_v3 primary, MiniMax speech-02 fallback). Maps character_id -> voice_id from library/voice-ips.json, maps emotional_intensity -> provider settings, runs the Vietnamese text normalizer, keeps audio tags, and caches stems by content hash. Use after parse-script and before assemble-audio.
---

# generate-voice

Stage [3]. Input: `scripts/parsed/epNN.json` + `library/voice-ips.json`. Output: `stems/epNN/*.wav`
(44.1 kHz / 16-bit / mono) with a `.meta.json` sidecar per stem (provider, model, settings, hash,
cost, duration_ms, alignment when available).

```bash
python .claude/skills/generate-voice/scripts/generate_voice.py --series demo --episode 1
python .claude/skills/generate-voice/scripts/generate_voice.py --series demo --episode 1 --lines ep01_sc02_l003 --force
python .claude/skills/generate-voice/scripts/generate_voice.py --series demo --episode 1 --provider minimax
python .claude/skills/generate-voice/scripts/generate_voice.py --series demo --episode 1 --dry-run   # payloads + character count
python .claude/skills/generate-voice/scripts/generate_voice.py one --voice-id <id> --text "[sighs] Anh đi đi." --out /tmp/a.wav
```

## Model choice (decision D4)

| model | Vietnamese | expressiveness | control | cost (credits/char) | use |
|---|---|---|---|---|---|
| `eleven_v3` | yes (70+ langs) | highest, audio tags | stability 0.0/0.5/1.0 only | 1 | **default** for drama lines |
| `eleven_multilingual_v2` | yes | good, no tags | continuous stability/style | 1 | same-voice fallback when v3 artifacts on a line |
| `eleven_flash_v2_5` | yes | lowest | continuous | 0.5 | not used: latency is irrelevant for batch, quality is not |
| MiniMax `speech-02-hd` | yes | good, `emotion` enum | speed/vol/pitch | vendor pricing | provider fallback (quota/outage) |

The registry stores `model_id` per character, so a character can be pinned to v2 if v3 mangles
their voice. QA can request `--model-override eleven_multilingual_v2 --lines ...` for one line.

## Text pipeline per line

`tts_text` -> Vietnamese normalizer (`pipeline.text.vi_normalize`, NFC + numbers + contractions +
punctuation; tags preserved) -> tag handling (kept for v3, stripped for v2/MiniMax) -> provider.
Monologue lines without a monologue tag get `[introspective]` prepended on v3, and lower
stability/higher style on v2.

## Caching

Stem hash = sha256(provider | model_id | voice_id | final text | sorted(settings)). Sidecar hash
match + existing wav = skip unless `--force`.
