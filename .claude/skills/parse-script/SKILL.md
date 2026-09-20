---
name: parse-script
description: AI Director. Turns a raw Vietnamese episode screenplay (scripts/raw/epNN.txt) into the validated EpisodeScript JSON contract (scenes, lines, character_id, tts_text with audio tags, emotion, emotional_intensity 1-10, acoustic_direction) using Gemini structured output. Use after episodize, or whenever a raw script is edited.
---

# parse-script (AI Director)

Stage [1]. Reads `scripts/raw/epNN.txt`, `series.json` (bible, cast, protagonist) and the Voice
IP registry, calls Gemini via `pipeline.llm.gemini_client.generate_structured` with the
`EpisodeScript` schema, resolves the `protagonist` alias, validates, and writes
`scripts/parsed/epNN.json`.

```bash
python .claude/skills/parse-script/scripts/parse_script.py --series demo --episode 1
python .claude/skills/parse-script/scripts/parse_script.py --series demo --episode 1 --dry-run        # prompt only
python .claude/skills/parse-script/scripts/parse_script.py --series demo --episode 1 --validate-only  # re-validate existing JSON
python .claude/skills/parse-script/scripts/parse_script.py --series demo --episodes 1-30 --force      # batch
```

Flags: `--model` (default `AI_AUDIO_LLM_MODEL`), `--provider elevenlabs|gemini` (whether audio
tags are emitted), `--force`.

## Rules the Director follows (system prompt)

1. Speaker labels are story ROLE names; the Director maps them to ACTOR ids via the casting table in
   `series.json.roles` (`character_id` = actor id, `role_name` = role). Anything left as a role name or slug is
   remapped after the call. Lines marked `(nội tâm)` become
   `type: monologue` with `character_id: "protagonist"` (resolved to the real id on save) and an
   `[internal monologue]` or `[introspective]` tag when the provider is ElevenLabs v3.
2. `text` is the author's Vietnamese line verbatim; `tts_text` may add approved tags and light
   punctuation only.
3. `emotional_intensity` is relative to the series; 9-10 reserved for 1-2 peaks per episode.
4. No narrator. No timing. `bgm` is null and `sfx` is empty while BGM/SFX are disabled.
5. The last spoken line is the cliffhanger.

## Output

`scripts/parsed/epNN.json` (validated) and a usage line in `run.log.jsonl`.
Last stdout line: `{"ok": true, "lines": N, "scenes": M, "peak_lines": [...], "path": "..."}`.

Exit codes: 2 validation failed, 3 blocked/truncated by the model.
