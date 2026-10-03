---
name: voice-ip-registry
description: Inspect and curate the locked Voice IP registry (data/assets/voice_registry.json) of Emvoox's Virtual Actors, and plug in a voice produced by the voice-cloning track so the next run uses it. Use to list actors and their voices per engine, add a cloned ElevenLabs / WaveSpeed (MiniMax) voice, or replace a locked voice.
---

# voice-ip-registry

The registry is written only through `emvoox.repositories.repos.VoiceRegistryRepository` (the lock rule lives there):
adding a voice on a new engine needs no unlock; changing or removing an IP asset's existing voice needs `--unlock`
and is recorded in the changelog. The web app's Voice IPs page edits the same file.

```bash
python -m emvoox voices                                                       # every actor, every engine, source tags
python -m emvoox plug-voice --actor ngan --provider elevenlabs --voice-id <PVC voice id> --label "Ngân PVC v1"
python -m emvoox plug-voice --actor duong --provider wavespeed --voice-id <clone id> --model minimax/speech-2.6-hd
python -m emvoox plug-voice --actor ngan --provider elevenlabs --voice-id <new id> --unlock   # replace a locked voice
```

`plug-voice` stores the voice with `source: cloned` and makes that engine the actor's preferred one (pass
`--not-preferred` to only add it). The Casting Agent's Engine Policy then renders the actor on that voice in every new
run, as long as the engine's API key is in `.env`; without the key it falls back to the run's engine and says so in
the run notes. Previews for the actor on that engine are invalidated so the Voice IPs page renders the new voice once.

Engines: `elevenlabs` (any ElevenLabs voice id, cloned included), `wavespeed` (model path decides the vendor:
`elevenlabs/eleven-v3` takes any ElevenLabs voice id, `minimax/speech-2.6-hd` takes MiniMax system or cloned ids),
`gemini` (30 prebuilt names only, no cloning).
