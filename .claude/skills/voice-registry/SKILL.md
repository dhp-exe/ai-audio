---
name: voice-registry
description: Manage the global, locked Voice IP registry (library/voice-ips.json) of actors: display name, personality, voice description, gender/age/tags for casting, and per-provider voice ids (ElevenLabs voice_id, model, voice link, fallback premade voice). The web client's Characters page edits the same file through pipeline.registry. Use to add/list/validate actors or to change a locked voice with --unlock.
---

# voice-registry (Voice IP anchoring)

Stage [2]. One registry for the whole studio. Series cast story roles onto these actors
(`series.json.roles`). This CLI and the web page both go through `pipeline/registry.py`.

```bash
python .claude/skills/voice-registry/scripts/voice_registry.py list
python .claude/skills/voice-registry/scripts/voice_registry.py add --character-id ngan --display-name "Ngân" \
    --gender female --age 23 --tags cute,innocent --persona "..." --voice-description "..." \
    --provider elevenlabs --voice-id a3AkyqGG4v8Pg7SWQ0Y3 --model-id eleven_v3 \
    --voice-url https://elevenlabs.io/voices/a3AkyqGG4v8Pg7SWQ0Y3 --fallback-voice-id cgSgspJ2msm6clMCkdW9
python .claude/skills/voice-registry/scripts/voice_registry.py add --character-id ngan --provider elevenlabs --voice-id NEW --unlock
python .claude/skills/voice-registry/scripts/voice_registry.py validate --series s1 [--episode 1]
```

## Lock rule

`locked: true`. Changing `voice_id`/`model_id` of an `is_ip_asset` actor fails without `--unlock`
(HTTP 423 in the web API) and every change is appended to `changelog`. Personality and metadata
edits never need unlock. One-off roles (`--one-off`, created by the orchestrator for uncast roles)
are not locked.

## Fallback voice

`fallback_voice_id` is a premade ElevenLabs voice used automatically when the account plan
rejects the real voice (HTTP 402, e.g. library voices on the Free tier). Stems rendered that way
carry `voice_fallback` in their sidecar and the run notes tell you to upgrade and re-render.
