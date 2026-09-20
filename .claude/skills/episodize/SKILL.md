---
name: episodize
description: Screenwriter + casting. Turns the director's sectioned story (series/<id>/story.json: overview, roles with optional /actor assignments, full script) into a series bible (casting of story roles onto Voice IP actors, N-episode plan) and N raw Vietnamese episode screenplays. Segment mode keeps the author's dialogue verbatim; write mode expands a treatment. Use at the start of a new series, before parse-script.
---

# episodize (Screenwriter + casting)

Stage [0]. Input is `series/<id>/story.json` (`StoryInput`; the web form writes it) or, legacy,
`story_raw.txt`. Two Gemini call types via `pipeline.llm.gemini_client.generate_structured`:

1. **Outline** (one call) -> `SeriesOutline`: casting of every story role onto a registry actor
   (respecting the director's `/actor` tags, one actor per role, `null` when nothing fits) +
   `count` episode plans with cliffhangers. Saved as `series.json` (`SeriesBible`), where
   uncast roles get a slug id (`ly-minh`) listed in `pending_characters`; the orchestrator's cast
   job then registers them with placeholder voices.
2. **Draft** (one call per episode, resumable) -> `EpisodeDraft` (scenes/lines, speaker = role
   name) rendered to `scripts/raw/epNN.txt`.

```bash
python .claude/skills/episodize/scripts/episodize.py --series s1 --outline-only --episodes 30 --min-sec 50 --max-sec 70
python .claude/skills/episodize/scripts/episodize.py --series s1 --only 1-5            # draft (skips existing)
python .claude/skills/episodize/scripts/episodize.py --series s1 --only 3 --force      # overwrite one draft
python .claude/skills/episodize/scripts/episodize.py --series s1 --outline-only --redo-outline --episodes 20   # recompute plan
```

`--force` only overwrites drafts. `--redo-outline` is the only flag that recomputes `series.json`.

## Modes

| mode | when | draft behaviour |
|---|---|---|
| `segment` | script words >= 0.5 x episodes x min_sec x 3.3 (a full script was pasted) | temperature 0.15; lines copied verbatim (checked; retried once with the mismatched lines if < 70%); only splitting, directions and up to two short protagonist monologues allowed |
| `write` | a treatment/synopsis was pasted | writes new dialogue from `key_beats`; word floor with two expansion passes |

## Casting rule

The story adapts to the actors. `/ngan` in a role's name or description (or the dropdown in the
web form) pins that actor; the model casts the rest by gender, age, personality and voice
description from the registry's `casting_card()`. Each actor plays one role per series.

## Screenplay format (parse-script depends on it)

```
TẬP 01 - Ngày đầu tiên

CẢNH 1. Sảnh tập đoàn Hoàng Gia. Sáng.
(Tiếng giày trên sàn đá.)
TÔ MẠN (nội tâm): Ngày đầu tiên đi làm.
GIANG THẦN (lạnh lùng): Ngồi xuống.
```

Speaker labels are ROLE names in upper case; `(nội tâm)` marks the protagonist's inner voice.
