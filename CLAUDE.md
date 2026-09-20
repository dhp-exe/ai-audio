# Audio AI Production Pipeline

Automated pipeline that turns one Vietnamese story into a 30-episode AI **audio** micro-drama, voiced by
fixed Virtual Actor IPs, so we can test audience retention cheaply before paying for video rendering.

## Why this exists (business context)

- DataEye 2025: **95.37%** of standalone micro-dramas never break 50M heat. 7 of the 10 titles that broke
  100M were **series with recurring characters**. Generic one-off AI content loses.
- Our bet: fixed AI actors (own voice, own face, own socials) accumulate fans across many series.
- Audio is the cheap test funnel: **1 story -> 30 audio episodes -> retention data -> only winners get video.**
- Market: Vietnam first (VN users pay per 60-120 s episode via micro-transactions).

## Architectural decisions (locked, 2026-09-20)

| # | Decision |
|---|---|
| D1 | **Vietnamese-first** (`vi-VN`). All prompts and content in Vietnamese. `pipeline/text/vi_normalize.py` runs before TTS (NFC, numbers, currency, time, dates, chat contractions, punctuation). |
| D2 | **Hybrid upstream.** Director fills overview + characters + script (web form -> `story.json`); `episodize` casts roles onto Voice IP actors and produces `series.json` + N raw scripts (segment mode keeps the pasted dialogue verbatim; write mode expands a treatment). |
| D3 | **No third-person narrator.** Inner voice is first person on the protagonist: `type: monologue`, alias `character_id: "protagonist"` resolved to the real id; tag `[internal monologue]` / `[introspective]`. |
| D4 | **No speech-to-speech.** Two TTS engines, picked per run in the web client (`tts_provider`): **ElevenLabs** `eleven_v3` (the Voice IPs; paid; same-voice fallback `eleven_multilingual_v2`) and **Gemini TTS** `gemini-3.1-flash-tts-preview` (free tier; 30 prebuilt voices addressed by name; style by Vietnamese direction). No other provider (MiniMax removed 2026-09-20). |
| D5/D6 | **BGM and SFX disabled** (`ENABLE_BGM=false`, `ENABLE_SFX=false`). Assembly = clean speech concat with 300-500 ms padding. |
| D7 | **Local disk + sidecar JSON.** Voice IPs locked in `library/voice-ips.json` (global across series). |
| D8 | Stereo master **-16 LUFS / -1.5 dBTP**, WAV + **MP3 192 kbps**. |
| D9 | Sequential concat from measured stem durations. No overlap. |
| D10 | LLM = **Google Gemini** via `google-genai` with Pydantic `response_schema`. Model from `AI_AUDIO_LLM_MODEL` (default `gemini-3.1-flash-lite`; `gemini-2.5-flash` is closed to new accounts; `gemini-3.6-flash` is the thinking alternative). |
| D11 | Human QA = local **FastAPI + HTML waveform** review page (Phase 4). |
| D12 | Single series at a time, 30 episodes per batch. |

## Pipeline

```
story_raw.txt (human)
   |
   v
[0] episodize      Gemini x(1 + 30) -> series.json + scripts/raw/epNN.txt
   |
   v
[1] parse-script   Gemini structured output -> scripts/parsed/epNN.json  (AI Director)
   |
   v
[2] voice-registry library/voice-ips.json: character_id -> voice_id per provider (locked)
   |
   v
[3] generate-voice vi_normalize -> ElevenLabs v3 | Gemini TTS (per run) -> stems/epNN/*.wav + .meta.json
   |
   v
[5] assemble-audio timeline (measured durations + padding) -> FFmpeg concat + loudnorm -> masters/epNN_master.wav|mp3
   |
   v
[6] qa-audio       auto checks + human verdict -> qa/epNN_report.json   (FastAPI review UI in Phase 4)
   |
   v
[7] publish + retention analytics (plan only)
```

Every stage reads and writes files with deterministic names, so any stage re-runs in isolation and the
pipeline is idempotent: a stem is regenerated only when the hash of (provider, model, voice_id, final
text, settings) changes.

## Repository layout

```
ai-audio/
  CLAUDE.md
  pyproject.toml, .env.example, .gitignore
  pipeline/                      <- shared package
    schema.py                    <- Pydantic contracts: StoryInput, SeriesOutline, EpisodeDraft, SeriesBible, EpisodeScript, VoiceRegistry, Timeline
    casting.py                   <- /actor tag parsing, gender guess, placeholder premade voices
    chunking.py                  <- scene batching for Gemini TTS: <=2-speaker chunks, transcript + direction header
    registry.py                  <- the only writer of library/voice-ips.json (lock rule)
    naming.py                    <- all paths and stem names (never hand-build)
    config.py                    <- .env-backed Settings
    llm/gemini_client.py         <- generate_structured(system, user, schema) -> (instance, usage)
    providers/                   <- base.py (TtsRequest, wav helpers), catalog.py (engines/models/Gemini voices), elevenlabs.py, gemini_tts.py, mapping.py (intensity -> settings | Gemini direction)
    previews.py                  <- cached ~5 s voice previews per actor and engine (library/previews/)
    stories.py                   <- story library index: progress per series, remaining episodes, delete
    text/vi_normalize.py         <- Vietnamese TTS text normalizer
    orchestrator.py              <- CI-style job graph over the skill CLIs; state in series/<id>/pipeline_run.json
    usage.py                     <- usage + quota monitor: ledger aggregation, 429/402 events, ElevenLabs subscription, per-model status/reset
    webui/                       <- FastAPI JSON API; serves web/out (Next.js static export) at / (python -m pipeline.webui)
  web/                           <- Next.js 16 + Tailwind 4 client: Library, New/Edit story, Run board, Characters, Usage (npm run dev | npm run export)
  .claude/skills/<skill>/        <- SKILL.md + scripts/<skill>.py (anthropics/skills layout)
  library/
    voice-ips.json               <- LOCKED global Voice IP registry (per actor: elevenlabs voice_id + gemini voice name)
    previews/                    <- <actor>_<engine>.wav previews (+ .meta.json cache)
  series/<series_id>/
    story.json                   <- sectioned input: overview, roles (+ actor assignment), script
    story_raw.txt                <- same, rendered as text
    series.json                  <- bible: premise, tone, protagonist_id, cast, 30 episode plans
    scripts/raw/epNN.txt         <- episodize output / human-edited
    scripts/parsed/epNN.json     <- AI Director output (validated)
    stems/epNN/*.wav(+.meta.json)
    timelines/epNN_timeline.json
    masters/epNN_master.wav|mp3
    qa/epNN_report.json
    run.log.jsonl                <- one line per LLM/TTS call with tokens/credits
    pipeline_run.json            <- orchestrator state (jobs, statuses, summaries)
    logs/<job>.log               <- stdout/stderr of each orchestrated job
  docs/ARCHITECTURE.md, docs/IMPLEMENTATION_PLAN.md, docs/SETUP.md
  tests/
```

## Tech stack

| Concern | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ | `.venv` + `pip install -e .[dev]`; FFmpeg/ffprobe on PATH |
| LLM | `google-genai`, `gemini-3.1-flash-lite` | `pipeline.llm.gemini_client.generate_structured`; `response_mime_type=application/json` + Pydantic `response_schema`; response text re-validated with Pydantic (regex/cross-field rules are client-side). Retries on 429/500/503 and transport errors; 180 s timeout; IPv4 pinned (`AI_AUDIO_FORCE_IPV4`) because this network's IPv6 path resets TLS. |
| TTS engine 1 (Voice IPs) | `elevenlabs` SDK, `eleven_v3` via `pipeline/providers/elevenlabs.py` | tags `[sighs] [whispers] [internal monologue]`; **stability discrete 0.0/0.5/1.0**; v3 rejects `language_code` and `previous_text`/`next_text`; `wav_44100` is Pro-tier only, adapter falls back to `mp3_44100_128` + ffmpeg; `convert_with_timestamps` alignment stored in sidecar |
| TTS same-voice fallback | `eleven_multilingual_v2` | continuous stability/style; no tags |
| TTS engine 2 | Gemini TTS via `pipeline/providers/gemini_tts.py` (`google-genai`, same client as the LLM); **scene batching** by default: one multi-speaker request per chunk of a scene with up to 2 actors (1-3 requests per episode instead of 8-12), `--batching line` for per-line stems | models `gemini-3.1-flash-tts-preview` (default), `gemini-2.5-flash-preview-tts`, `gemini-2.5-pro-preview-tts`; voice = one of 30 prebuilt names; direction prefixed as `"<style>:\n<text>"` (verified: direction is not spoken); 24 kHz PCM resampled to 44.1 k; serial (free-tier RPM) |
| Normalization | `pipeline.text.vi_normalize` | on by default (`AI_AUDIO_NORMALIZE_VI`) |
| Mixing | FFmpeg `filter_complex` (apad + concat) then **two-pass** `loudnorm` | pydub dropped; single-pass landed 1.3 LU off, two-pass hits -16.0 exactly |
| State | sidecar JSON + `run.log.jsonl` | no database |
| Web client | Next.js 16 (App Router, TypeScript, Tailwind 4, lucide) in `web/`; backend FastAPI + uvicorn `python -m pipeline.webui` (port 8765) serves the static export and the JSON API | Pages: **Library** (progress, listen, continue N more episodes, edit & re-run, delete), **New story / Edit story** (collapsible, resizable side panel; one IP per role), **Run** (CI-style board, logs, players), **Characters** (cards with a ▶ preview per engine rendered once and cached; `+ New character` opens the panel; edit is a separate panel title), **Usage** (per-model requests/tokens/characters, limits, exhausted/rate-limited status with live countdown to reset, vendor events). Light/dark themes. Deploy the `web/` app on Vercel with `API_BASE` pointing at a hosted backend. |
| Keys | `.env`: `GEMINI_API_KEY` (LLM + Gemini TTS), `ELEVENLABS_API_KEY` (scope `user_read` lets the Usage page read the vendor's credit counter) | see docs/SETUP.md |

## Conventions

### Naming standard for audio stems

Underscore separates fields, so **no underscores inside a field**. Character IDs are lowercase
`[a-z0-9-]`, e.g. `linh`, `minh-khoi`.

```
ep{NN}_sc{NN}_l{NNN}_{character_id}_{type}.wav      type = dialogue | monologue
  ep01_sc02_l003_linh_dialogue.wav
  ep01_sc01_l001_linh_monologue.wav
ep{NN}_sc{NN}_c{NN}_chunk.wav                        scene-batched unit (Gemini), lines listed in stems/epNN/render.json
ep{NN}_master.wav / ep{NN}_master.mp3
ep{NN}_timeline.json
```

Line numbers restart at 001 per scene; episodes/scenes 2 digits, lines 3. Helpers: `pipeline/naming.py`.

### Audio format

- Stems: WAV 44.1 kHz / 16-bit / **mono** (`pcm_44100` from providers).
- Masters: WAV 44.1 kHz **stereo** + MP3 **192 kbps**, **-16 LUFS integrated, -1.5 dBTP**.
- Padding: Director `pause_after_ms` clamped to [300, 500] ms; `pause` lines uncapped; scene gap 800 ms;
  500 ms tail. Fixed padding via `--fixed-padding`.

### Coding conventions

- Type hints everywhere; `pydantic` v2 for anything crossing a file boundary.
- Every skill script is an `argparse` CLI with `--dry-run`, non-zero exit on failure, and a one-line JSON
  summary as the last stdout line. Exit codes: 1 usage/config, 2 validation, 3 LLM blocked/truncated.
- Paths only via `pipeline/naming.py`. Config only via `pipeline/config.get_settings()`.
- All LLM calls through `pipeline/llm/gemini_client.py`; all TTS through provider adapters
  (`pipeline/providers/` in Phase 2). Skills never call vendor SDKs directly.
- Cache stems by content hash in `<stem>.meta.json`; skip on match unless `--force`.
- Log every paid call to `series/<id>/run.log.jsonl` (tokens or characters).
- Prompts are written in Vietnamese; JSON field names stay English.
- Tests under `tests/`, `pytest`, no live API calls. `ruff` line length 120.

### Emotional intensity -> TTS settings

| intensity | v3 `stability` | v3 `similarity_boost` | multilingual_v2 `stability` / `style` | Gemini direction |
|---|---|---|---|---|
| 1-3 | 0.5 | 0.80 | 0.70 / 0.15 | `giọng <emotion> (nhẹ)` |
| 4-6 | 0.5 | 0.75 | 0.50 / 0.30 | `giọng <emotion> (vừa phải)` |
| 7-8 | 0.0 | 0.65 | 0.40 / 0.40 | `giọng <emotion> (mạnh)` |
| 9-10 | 0.0 | 0.55 | 0.30 / 0.50 | `giọng <emotion> (rất mạnh, cao trào)` |

Monologue lines: v3 gets `[introspective]` if the Director left no monologue tag; v2 gets stability
-0.1 / style +0.1; Gemini gets "độc thoại nội tâm, mic gần" in the direction. Gemini's direction (`mapping.gemini_style`) is
`"Nói tiếng Việt, giọng <emotion> (<intensity word>), [monologue], <pace>, <volume>, <tag hints>, <acoustic_direction>"`;
tags are stripped from the text and folded into it. Implemented in `pipeline/providers/mapping.py`.

## AI Director output contract

Canonical definition: `pipeline/schema.py::EpisodeScript` (`python -m pipeline.schema` prints the JSON Schema).

```json
{
  "schema_version": "1.0",
  "language": "vi-VN",
  "series_id": "demo",
  "episode_number": 1,
  "title": "Bản hợp đồng",
  "logline": "Khôi gọi sau ba năm im lặng, chỉ để thuê Linh.",
  "target_duration_sec": 120,
  "characters_used": ["linh", "minh-khoi"],
  "scenes": [
    {
      "scene_id": "sc01",
      "title": "Cuộc gọi trên sân thượng",
      "location": "Sân thượng chung cư, Quận 1",
      "time_of_day": "night",
      "ambience_tag": null,
      "ambience_level": 0.2,
      "bgm": null,
      "lines": [
        {
          "line_id": "ep01_sc01_l001",
          "type": "monologue",
          "character_id": "protagonist",
          "text": "Ba năm. Tôi đã xóa số, đổi số, chuyển nhà.",
          "tts_text": "[internal monologue] Ba năm. Tôi đã xóa số, đổi số, chuyển nhà...",
          "emotion": "sad",
          "emotional_intensity": 5,
          "acoustic_direction": "nội tâm, mic gần, đều giọng",
          "pace": "slow",
          "volume": "soft",
          "pause_after_ms": 500,
          "sfx": []
        },
        {
          "line_id": "ep01_sc01_l002",
          "type": "dialogue",
          "character_id": "linh",
          "text": "Anh đã nói sẽ không bao giờ gọi cho em nữa.",
          "tts_text": "[sighs] Anh đã nói sẽ không bao giờ gọi cho em nữa.",
          "emotion": "sad",
          "emotional_intensity": 6,
          "acoustic_direction": "khẽ, kìm nén, mic gần",
          "pace": "slow",
          "volume": "soft",
          "pause_after_ms": 400,
          "sfx": []
        }
      ]
    }
  ],
  "cliffhanger": "Văn phòng là nhà thờ cũ, nơi họ từng định làm lễ cưới.",
  "director_notes": ""
}
```

Field rules (enforced by validators):

- `line.type` in `dialogue | monologue | pause`. `pause` lines have empty text.
- `character_id` lowercase; `protagonist` alias allowed and rewritten to `series.json.protagonist_id` by
  parse-script; every other id must be in the series cast and in `library/voice-ips.json`.
- `tts_text` tags only from `APPROVED_AUDIO_TAGS` in `schema.py`.
- `emotion` enum: `neutral happy sad angry fearful surprised disgusted tender sarcastic desperate`.
- `emotional_intensity` 1-10; `pause_after_ms` 0-5000; `bgm` null and `sfx` empty while disabled.
- `scene_id` sequential `scNN`; `line_id` = `ep{NN}_sc{NN}_l{NNN}` restarting per scene, unique.
- No timing in the Director output; assembly computes it from real stem durations.

## Skills

| Skill | Script | Stage | Status |
|---|---|---|---|
| `episodize` | `scripts/episodize.py` | [0] story -> bible + 30 raw scripts | live-verified; structured `EpisodeDraft` rendered to screenplay; word floor = 3.3 words/s x min duration with 2 expansion passes |
| `parse-script` | `scripts/parse_script.py` | [1] raw -> EpisodeScript | live-verified on ep01-05; lines kept verbatim 11/11 on ep01 |
| `voice-registry` | `scripts/voice_registry.py` | [2] locked Voice IP registry | implemented |
| `generate-voice` | `scripts/generate_voice.py` | [3] stems | live-verified (ElevenLabs v3, thread pool, hash cache, provider fallback hook) |
| `assemble-audio` | `scripts/assemble_audio.py` | [5] timeline + master | live-verified, two-pass loudnorm |
| `qa-audio` | `scripts/qa_audio.py` | [6] checks + verdict | stems/duration/loudness done; rest Phase 4 |

Removed: `sts-override` (D4). Run any script with `--help`.

### Running the whole pipeline

```bash
python -m pipeline.webui                                   # API + web app at http://127.0.0.1:8765 (build once: cd web && npm install && npm run export)
cd web && npm run dev                                      # UI dev server at http://localhost:3000 proxying /api to the backend
python -m pipeline.orchestrator --series s1 --story story.txt --episodes 30 --produce 5 --min-sec 50 --max-sec 70 --tts gemini
python -m pipeline.orchestrator --series s1 --only 6-10 --tts elevenlabs                   # continue an existing series
```

The orchestrator runs the skill CLIs as jobs (outline -> cast -> per-episode draft -> direct -> voice -> assemble -> qa),
one episode at a time, in order. The engine is a run parameter; the cast job gives
every actor a voice on that engine (one voice per role, never shared): roles the outline invents get placeholder voices
(one-off, flagged in the run notes) and IP actors missing a voice on the engine get one auto-assigned. `--only` / the
Library's "Continue" produce the remaining episodes of an existing series. Full walkthrough: `docs/ARCHITECTURE.md`.

## Roles vs actors

A **role** is a character in a story ("Tô Mạn"); an **actor** is a Voice IP in `library/voice-ips.json` ("ngan").
`series.json.roles` is the casting table. The director pins an actor with `/ngan` in the role name/description (or the
web dropdown); the outline call casts the rest. `character_id` in scripts, stems and sidecars is always the actor id;
`role_name` carries the story name. Each actor plays one role per series.

## Current account constraints (2026-09-20)

- ElevenLabs key is **Free tier** and scoped (no `user_read`/`models_read`): library voices (e.g. Thuy Duong, vi) return 402 via API, `wav_44100` returns 403. Placeholders in `library/voice-ips.json` are English premade voices driven in Vietnamese by v3; the target Vietnamese voices are noted in each `voice_description`. Upgrade to Creator+ for library voices and Professional Voice Cloning.
- Measured pace on v3 with these voices: **3.6 words/s**; drafter uses 3.3.
- Gemini TTS without billing: **10 requests/day per model, 3/min**. Scene batching (default on Gemini) makes an episode cost 1-3 requests; per-line rendering costs one per line. The adapter fails fast on the daily quota.
- Test fixture for the episode contract lives in `tests/fixtures/episode.json`, never in `series/demo` (that folder is regenerated live).
