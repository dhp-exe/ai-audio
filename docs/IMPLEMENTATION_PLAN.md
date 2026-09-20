# End-to-End Implementation Plan

Status: **Phase 1 done on ep01-05; Phase 2 live-verified with placeholder voices; Phase 3 items 1 and 6 partly done.** All section-0 decisions were made by the Lead AI System
Architect on 2026-09-20 and are recorded below and in `CLAUDE.md`.

## 0. Decisions (final)

| # | Decision | Where it lives in code |
|---|---|---|
| D1 | Vietnamese-first `vi-VN`; lightweight normalizer (numbers, currency, time, dates, contractions, punctuation, NFC) before TTS | `pipeline/text/vi_normalize.py`, `AI_AUDIO_NORMALIZE_VI` |
| D2 | Hybrid: human `story_raw.txt` -> `episodize` (Gemini) -> `series.json` + 30 raw scripts of 90-120 s | `.claude/skills/episodize` |
| D3 | First-person POV; no house narrator. `type: monologue` on the protagonist, alias `protagonist`, tags `[internal monologue]`/`[introspective]` | `schema.py` (LineType, PROTAGONIST_ALIAS), `parse_script.py` |
| D4 | No STS. TTS: ElevenLabs `eleven_v3` primary (chosen over `multilingual_v2`/`flash_v2_5` for tag-driven acting; v2 kept as same-voice fallback), MiniMax `speech-02-hd` provider fallback | `generate_voice.py`, `voice-ips.json` `model_id` |
| D5/D6 | `ENABLE_BGM=false`, `ENABLE_SFX=false`; speech-only concat with 300-500 ms padding | `config.py`, `assemble_audio.py` |
| D7 | Local disk; sidecar JSON; global locked `library/voice-ips.json` | `naming.registry_path()`, `voice_registry.py --unlock` |
| D8 | Stereo -16 LUFS / -1.5 dBTP; WAV + MP3 192 kbps | `assemble_audio.render_voice_only` |
| D9 | Sequential from measured durations; no overlap | `assemble_audio.build_timeline` |
| D10 | Google Gemini via `google-genai` + Pydantic `response_schema`; **`gemini-3.1-flash-lite` default** (2.5 Flash is closed to new accounts), `gemini-3.6-flash` via env | `pipeline/llm/gemini_client.py` |
| D11 | Local FastAPI + HTML waveform review UI | Phase 4 |
| D12 | One series at a time, 30 episodes per batch | concurrency defaults |

Removed from the original design: `sts-override` skill, Anthropic SDK, pydub, per-series
`characters.json`, narrator character, BGM/SFX cue library work (moved to Phase 5).

## Progress log

**2026-09-20, first live run (episodes 1-5):**
- Outline: 30 episodes from `story_raw.txt` in one call (832 in / 4,290 out tokens). It invented one recurring role (`ong-trum`); episodize now carries such roles into `series.json.cast` + `pending_characters`, and a placeholder voice was registered.
- Drafts: switched from free-text screenplay to structured `EpisodeDraft` (scenes/lines) rendered deterministically; flash-lite under-writes, so a word floor (3.3 words/s x min duration) with up to two expansion passes was added. Episodes 4-5 land at 95-98 s; 1-3 were drafted before calibration and run 67-73 s.
- Director: all 5 episodes validate first try; ep01 lines verbatim 11/11; one to three intensity>=9 lines per episode.
- TTS: 51 stems on ElevenLabs v3, ~6,100 characters. Vendor rules learned and encoded: v3 rejects `previous_text`/`next_text`; `wav_44100` is Pro-only (fallback to mp3 + ffmpeg); Free tier cannot use library voices via API (402).
- Assembly: two-pass loudnorm replaces single-pass (-17.3 -> -16.0 LUFS). QA passes on ep01, 03, 04, 05; ep02 fails duration only (pre-calibration draft).
- Infra: Gemini client got a 180 s timeout, transport-error retries, and IPv4 pinning (this network's IPv6 path resets TLS on generativelanguage.googleapis.com).
- Tests: 44 passing, including mocked Gemini client and ElevenLabs adapter (format fallback, alignment).

**2026-09-20, later:** added `pipeline/orchestrator.py` (job graph over the CLIs, per-job logs, state file, placeholder casting for invented roles) and the browser client `pipeline/webui` (paste story, episodes, min/max seconds, produce-now count; CI-style board with live logs and inline players). `docs/ARCHITECTURE.md` written. 47 tests.

Next when resumed: human listen-through of ep01-05 masters; decide on ElevenLabs tier upgrade for Vietnamese voices; re-draft ep01-03 at the calibrated length if the review wants full-length episodes; then Phase 2 steps 2-4 (real Voice IPs, intensity calibration, pronunciation list).

## Current state (what already runs)

- `pytest`: 27 tests green (schema, naming, normalizer, timeline, real FFmpeg render).
- `episodize`, `parse-script`: complete, need `GEMINI_API_KEY` for a live run. Prompts in Vietnamese.
- `voice-registry`: complete, lock enforced.
- `generate-voice`: complete except the two vendor adapter bodies.
- `assemble-audio`: complete for voice-only; verified master at -16.0 LUFS stereo.
- `qa-audio`: stems / duration / loudness checks complete; verdict recording complete.

---

## Phase 1: Screenwriter + AI Director (Gemini)

Goal: `story_raw.txt` -> 30 validated `EpisodeScript` JSONs with no manual JSON edits.

1. Set `GEMINI_API_KEY` (docs/SETUP.md). `pip install -e .[dev]`.
2. Run `episodize --series demo --outline-only`; review `series.json` (cast onto Voice IPs,
   cliffhanger per episode). Iterate the outline prompt until a writer signs off on 2 outlines.
3. Run `episodize --series demo --only 1-3`; check the screenplay format is exactly what
   `parse-script` expects (`CHARACTER-ID:` / `(nội tâm)`). Tune `DRAFT_SYSTEM` for length
   (`estimated_duration_sec` vs measured later in Phase 2).
4. Run `parse-script --series demo --episodes 1-3`. Failure classes to hunt: invented characters,
   alias not used for monologue, intensity inflation (too many 9-10s), non-Vietnamese output, tags
   outside the approved list. Encode mechanical checks as validators, judgment as prompt rules.
5. Full batch: `episodize` all 30, `parse-script --episodes 1-30`. Record token cost per episode from
   `run.log.jsonl`; target < $0.05/episode on 2.5 Flash.
6. Tests: `tests/test_gemini_client.py` with a mocked `genai.Client` (schema errors, MAX_TOKENS,
   SAFETY, 429 retry); golden test on the demo episode; prompt snapshot test.
7. Optional: A/B `gemini-3.1-flash-lite` vs `gemini-2.5-flash` on 5 episodes for Director quality
   (intensity calibration, monologue placement); keep the cheaper one if a writer cannot tell.

Exit criteria: 30 consecutive episodes parse with zero validation failures; a writer approves the
raw scripts of episodes 1-5 with only line-level edits.

## Phase 2: TTS integration and Voice IP anchoring (ElevenLabs v3 + MiniMax)

Goal: every line renders to a correctly named, cached, normalized Vietnamese stem on the fixed voice.

1. `pipeline/providers/base.py` (`synthesize(TtsRequest, out) -> StemInfo`), `elevenlabs.py`
   (`eleven_v3` and `eleven_multilingual_v2`, `convert_with_timestamps`, `language_code="vi"`,
   PCM -> WAV mono), `minimax.py` (`speech-02-hd`, `language_boost: Vietnamese`). Move the stubs
   out of `generate_voice.py`; keep the CLI unchanged.
2. Voice IP creation: Professional Voice Clone per IP actor (Vietnamese source recordings, 30+ min
   clean audio each), audition with `generate-voice one` on a 6-line emotional ladder (intensity
   2/4/6/8/9/monologue), register with `voice-registry add`. Add a MiniMax clone for each too.
3. Calibrate the intensity table on real Vietnamese output: render the ladder at each band, listen,
   adjust `settings_for_line`. Watch v3's known failure modes on non-English (dropped syllables,
   wrong tone marks); pin a character to `eleven_multilingual_v2` in the registry if v3 is unstable.
4. Normalizer hardening: collect mispronunciations from QA, extend `CONTRACTIONS` and number rules;
   add a per-series `pronunciation.json` (name -> phonetic spelling) applied after normalization.
5. Bounded concurrency (ElevenLabs tier limit) + backoff; per-episode cost logged from sidecars;
   `--dry-run` estimate before every full-episode render.
6. Tests: mocked adapters, cache-skip contract test, normalizer regression corpus.

Exit criteria: 30 episodes render end-to-end with < 2% failed lines; changing one line re-renders
only that stem; a native speaker rates 90% of lines "natural" on a 3-episode sample.

## Phase 3: Voice-only assembly hardening

Goal: masters that sound intentional without music.

1. Two-pass `loudnorm` (measure, then apply) for tighter -16 LUFS; keep single-pass as fallback.
2. Room tone instead of digital silence: generate a 1 s low-level noise bed per series and use it for
   padding (configurable, off by default) so gaps do not sound "dead".
3. Head/tail trim per stem (strip provider-added silence > 150 ms) before timeline placement, so
   padding is what we set, not provider silence plus ours.
4. Per-episode duration check against `series.json.episode_format` at assembly time; warn early.
5. ID3 tags on MP3 (series, episode, title). Optional per-platform export table.
6. ~~Orchestrator~~ done as `python -m pipeline.orchestrator` (per-episode job graph; failed job skips the rest of that episode).

Exit criteria: full 30-episode batch assembles in < 2 min; loudness within 0.5 LU; no audible
clicks at joins.

## Phase 4: Human QA UI and remaining checks

Goal: a non-engineer approves an episode in under 5 minutes.

1. Implement `check_clipping`, `check_silence`, `check_transcript_diff` (ElevenLabs Scribe or
   Gemini audio transcription, Vietnamese; WER per line).
2. Extend the existing web client (`pipeline/webui`, already shows runs, logs and masters) with the review view:
   per-line waveform player (wavesurfer.js from CDN), approve / reject / re-render buttons that call
   `generate-voice --lines` and `assemble-audio` and write `qa/epNN_report.json`. Same file the CLI
   writes; no database.
3. Series dashboard: status per episode, cost to date, review backlog (reads sidecars + run log).
4. `publish` and `metrics` skill placeholders so the funnel closes (platform TBD by the business side).
5. `docs/RUNBOOK.md`: new-series checklist, Voice IP creation, costs, failure recovery.

Exit criteria: one full 30-episode series reviewed and approved through the UI by a non-engineer.

## Phase 5 (later): BGM, SFX, mixing

Deferred by D5/D6. When enabled: mood-tagged BGM library, SFX cues from the Director (schema
already has the fields), FFmpeg mixing renderer with sidechain ducking. Flip `ENABLE_BGM` /
`ENABLE_SFX` and implement `assemble_audio.render_mixed`.

## Cross-cutting

- `git init` before Phase 1 work; `.gitignore` already excludes audio and `.env`.
- CI: ruff + pytest, all vendor calls mocked.
- `run.log.jsonl` per series is the cost ledger; a `cost` subcommand can sum it later.
