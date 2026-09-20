---
name: generate-voice
description: Render one WAV stem per line of a parsed episode through one of the two TTS engines (ElevenLabs eleven_v3 for the Voice IPs, or Gemini TTS on the free tier). Maps character_id -> the actor's voice on the chosen engine from library/voice-ips.json, maps emotional_intensity -> ElevenLabs settings or a Vietnamese acting direction for Gemini, runs the Vietnamese text normalizer, and caches stems by content hash. Use after parse-script and before assemble-audio.
---

# generate-voice

Stage [3]. Input: `scripts/parsed/epNN.json` + `library/voice-ips.json`. Output: `stems/epNN/*.wav`
(44.1 kHz / 16-bit / mono) with a `.meta.json` sidecar per stem (provider, model, settings, hash,
cost, duration_ms, alignment when available).

```bash
python .claude/skills/generate-voice/scripts/generate_voice.py --series demo --episode 1                       # AI_AUDIO_TTS_PROVIDER (elevenlabs)
python .claude/skills/generate-voice/scripts/generate_voice.py --series demo --episode 1 --provider gemini     # free tier
python .claude/skills/generate-voice/scripts/generate_voice.py --series demo --episode 1 --provider gemini --model-override gemini-2.5-flash-preview-tts
python .claude/skills/generate-voice/scripts/generate_voice.py --series demo --episode 1 --lines ep01_sc02_l003 --force
python .claude/skills/generate-voice/scripts/generate_voice.py --series demo --episode 1 --dry-run   # payloads + character count
python .claude/skills/generate-voice/scripts/generate_voice.py one --provider elevenlabs --voice-id <id> --text "[sighs] Anh đi đi." --out /tmp/a.wav
python .claude/skills/generate-voice/scripts/generate_voice.py one --provider gemini --voice-id Leda --direction "giọng buồn, chậm" --text "Anh đi đi." --out /tmp/b.wav
```

## Engines (decision D4)

| engine / model | Vietnamese | expressiveness | control | cost | use |
|---|---|---|---|---|---|
| ElevenLabs `eleven_v3` | yes | highest, audio tags | stability 0.0/0.5/1.0 only | 1 credit/char | **Voice IPs** (paid plan needed for library voices) |
| ElevenLabs `eleven_multilingual_v2` | yes | good, no tags | continuous stability/style | 1 credit/char | same-voice fallback when v3 artifacts on a line |
| ElevenLabs `eleven_flash_v2_5` | yes | lowest | continuous | 0.5 credit/char | cheap drafts |
| Gemini `gemini-3.1-flash-tts-preview` | yes (multilingual voices) | good, natural-language direction | direction text | **free tier**, else per audio token | **default Gemini model**; pipeline and retention tests |
| Gemini `gemini-2.5-flash-preview-tts` | yes | good | direction text | free tier | older voices |
| Gemini `gemini-2.5-pro-preview-tts` | yes | best of the Gemini line | direction text | paid | optional |

The registry stores one voice per engine per actor (`providers.elevenlabs.voice_id`,
`providers.gemini.voice_id` = prebuilt name). `--provider` picks the engine; `--model-override` the
model. A character keeps one voice for the run: there is no cross-engine fallback. On ElevenLabs a
402 "paid plan required" for a voice is rendered with the actor's `fallback_voice_id` (premade) and
flagged in the sidecar (`voice_fallback`) and the summary (`placeholder_voices`).

## Text pipeline per line

`tts_text` -> Vietnamese normalizer (`pipeline.text.vi_normalize`) -> tag handling -> engine.
- ElevenLabs v3: tags kept; monologue lines without a monologue tag get `[introspective]`.
- ElevenLabs v2 / flash: tags stripped; monologue = lower stability, higher style.
- Gemini: tags stripped and folded into a Vietnamese direction built from emotion, intensity, pace,
  volume, monologue and `acoustic_direction` (`mapping.gemini_style`), sent as `"<direction>:\n<text>"`.
  Verified live: the direction is not spoken. Output is 24 kHz PCM resampled to the 44.1 kHz stem.

## Caching

Stem hash = sha256(provider | model_id | voice_id | final text | sorted(settings)). Sidecar hash
match + existing wav = skip unless `--force`. Switching engine or model changes the hash, so the
stems of the other engine are re-rendered (previous ones are overwritten in place).

## Concurrency and limits

`--concurrency` defaults to 2 for ElevenLabs and 1 for Gemini (free-tier requests per minute).
Gemini 429/5xx are retried with backoff (5, 10, 20, 40 s); a line that still fails is reported in
`failed` and the exit code is 2.

## Output

Last stdout line: `{"ok": true, "provider": "gemini", "model": "...", "planned": N, "rendered": R, "cached": C, "failed": [...], "fell_back": [...], "placeholder_voices": [...]}`.
Every rendered line is appended to `series/<id>/run.log.jsonl` with characters (both engines) and tokens (Gemini).
