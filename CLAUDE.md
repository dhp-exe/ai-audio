# Emvoox Engine

Event-driven multi-agent pipeline that turns a trend or a Vietnamese story into a series of AI **audio** micro-drama
episodes voiced by fixed Virtual Actor IPs, so Emvoox can test audience retention cheaply before paying for video.
Full design: `docs/ARCHITECTURE.md`. Keys and first live run: `docs/SETUP.md`.

## Why this exists (business context)

- DataEye 2025: **95.37%** of standalone micro-dramas never break 50M heat; 7 of the 10 titles above 100M were series
  with recurring characters. Our bet: fixed AI actors (own voice, own face, own socials) accumulate fans across series.
- Audio is the funnel: **story → N audio episodes → retention data → only winners get video**.
- Market: Vietnam first (YouTube channel "Mặc Khải" by Emvoox; content lines Đô thị - Tổng tài, Vả mặt - Ngược tra,
  Tái sinh - Lội ngược dòng). Brand: "Emvoox" in UI text, "EMVOOX" in titles; navy `#284979`.

## Architectural decisions

| # | Decision |
|---|---|
| D1 | **Vietnamese-first** (`vi-VN`). Prompts and content in Vietnamese; JSON field names English. `emvoox/text/vi_normalize.py` runs before TTS. |
| D2 | Story comes from a human (`StoryInput`), a `TrendBrief` (Market Research Agent → Story Adapt), or a fresh research run. Segment mode keeps pasted dialogue verbatim; write mode expands a treatment. |
| D3 | **No third-person narrator.** Inner voice = `type: monologue` on the protagonist (alias `protagonist` resolved by the Director). |
| D4 | **No speech-to-speech.** TTS engines: Gemini TTS (default, free tier), ElevenLabs (Voice IPs), WaveSpeed (ElevenLabs v3 / MiniMax via one key), mock (offline). Engine per run, per role type or per actor (Engine Policy); a **cloned** IP voice wins whenever its engine has a key. |
| D5/D6 | BGM and SFX implemented but **off by default** (`ENABLE_BGM`, `ENABLE_SFX`). |
| D7 | **Local-first storage behind repositories** (`DocumentStore` + `BlobStore`, keys = relative paths under `./data`); V1RON (`v1ron_db` + MinIO) later via `EMVOOX_STORAGE=v1ron`. Voice IPs in `data/assets/voice_registry.json` (global, locked). |
| D8 | Stereo master **-16 LUFS / -1.5 dBTP**, WAV + **MP3 192 kbps**. |
| D9 | Sequential concat from measured stem durations; no overlap. |
| D10 | LLM via adapters: Gemini (`gemini-3.1-flash-lite` default), WaveSpeed LLM / OpenAI-compatible, Claude, mock. Every call validated against a Pydantic contract. |
| D11 | **Human approval gate**: nothing is exported without a reviewer; FLAGGED episodes halt the run by default. |
| D12 | One series at a time, episodes sequential (vendor rate limits). |
| E1-E10 | Refactor decisions (asyncio engine instead of LangGraph/CrewAI, FFmpeg not pydub, casting as its own agent, bounded QA retry loop, rule-based Director fallback, optional selector-free browser scan…): `docs/ARCHITECTURE.md` §11. |

## Repository layout

```
emvoox/
  config.py            Settings from .env (EMVOOX_*; legacy AI_AUDIO_* still read)
  paths.py             every storage key and stem name (never hand-build one)
  contracts/           Pydantic payloads: market, production (story/bible/script/registry/timeline), script, cast,
                       direction, audio, qa, release, run, telemetry
  agents/              market_research, script_writer, casting, director, sound_engineer, qa_critic, publisher (+ base)
  engine/              orchestrator.py (async state machine, retry loop, gate, CLI `run`), events.py (event bus)
  repositories/        base.py (protocols), local.py (JSON, SQLite, disk), repos.py (typed repositories, registry lock),
                       factory.py, v1ron.py (stubs)
  providers/llm/       gemini, openai_compat (WaveSpeed/OpenAI), anthropic_llm, mock; LlmClient in __init__
  providers/tts/       gemini, elevenlabs, wavespeed, mock, catalog, base
  delivery/            compile.py (Delivery Compile), plan.py (Render Plan), screenplay.py (rule-based reading)
  audio/               ffmpeg.py, timeline.py, mix.py (concat, ducked bed, SFX, two-pass loudnorm)
  telemetry/           ledger.py, pricing.py, usage.py (costs + quotas), events.py (vendor 429/402)
  services/            library.py (productions views), previews.py, doctor.py
  api/app.py           FastAPI; serves web/out at /
  cli.py               python -m emvoox serve | run | research | approve | reject | voices | plug-voice | doctor | agents
web/                   Next.js 16 + Ant Design 6; web/lib/api.ts is the API contract
data/                  assets/, inputs/, research/, series/<id>/, outputs/approved_masters/, telemetry/
scripts/demo_pipeline.py   offline end-to-end demo (mock LLM + mock voices, injected fault)
tests/                 pytest, offline: sockets blocked, .env not loaded (EMVOOX_SKIP_DOTENV)
.claude/skills/        emvoox-pipeline, voice-ip-registry, market-research
```

## Running

```bash
python -m emvoox serve                                       # API + web app at http://127.0.0.1:8765 (build web once: cd web && npm run export)
cd web && npm run dev                                        # UI dev server :3000, proxies /api
python scripts/demo_pipeline.py                              # offline demo
python -m emvoox run --series s1 --story story.txt --episodes 30 --produce 3 --tts gemini
python -m emvoox run --series s2 --research --seeds "..." --llm wavespeed --tts wavespeed
python -m emvoox run --series s1 --only 4-6                  # continue
python -m emvoox approve --series s1 --episode 1 --reviewer <name>
```

## Conventions

### Code
- Python 3.11+, type hints, **Pydantic v2 for anything crossing an agent or file boundary**. Agents return contracts;
  the engine re-validates every handoff.
- Agents never touch paths or vendor SDKs: storage only through `ctx.repos`, LLM only through `ctx.llm.structured(...)`,
  TTS only through `providers.tts.get_provider(...)`. Keys only via `emvoox.paths`, settings only via `get_settings()`.
- Every LLM call, TTS request and agent step goes to the ledger (`ctx.ledger`) with tokens/characters/time/cost.
- Stems cached by content hash (`TtsRequest.content_hash`, includes the retry attempt); skip on match unless `force`.
- Prompts in Vietnamese; Emvoox Anti-Trope rules in `contracts/script.py`.
- Tests under `tests/`, no network (sockets blocked), `ruff` line length 160 (prompt-heavy modules exempt from E501).
- Every CLI command ends with a one-line JSON summary and exits non-zero on failure.

### Stem names (underscore separates fields; ids are `[a-z0-9-]`)
```
ep{NN}_sc{NN}_l{NNN}_{actor_id}_{dialogue|monologue}.wav    one line
ep{NN}_sc{NN}_c{NN}_chunk.wav                               one multi-speaker conversation request
ep{NN}_master.wav | .mp3 | .json,  ep{NN}_timeline.json
```

### Audio format
Stems WAV 44.1 kHz / 16-bit / mono. Masters stereo WAV + MP3 192 kbps at -16 LUFS / -1.5 dBTP. Director pauses
clamped to 300-500 ms; `pause` units uncapped; scene gap 800 ms; 500 ms tail.

### Emotional intensity → engine settings (`delivery/compile.py`)

| intensity | v3 `stability` / `similarity_boost` | v2 `stability` / `style` | Gemini direction | WaveSpeed |
|---|---|---|---|---|
| 1-3 | 0.5 / 0.80 | 0.70 / 0.15 | `giọng <emotion> (nhẹ)` | ElevenLabs v3: stability as v3; MiniMax: emotion, speed from pace, volume from volume |
| 4-6 | 0.5 / 0.75 | 0.50 / 0.30 | `(vừa phải)` | |
| 7-8 | 0.0 / 0.65 | 0.40 / 0.40 | `(mạnh)` | |
| 9-10 | 0.0 / 0.55 | 0.30 / 0.50 | `(rất mạnh, cao trào)` | |

A voice's `default_settings` (identity anchor of a cloned voice) always win. QA retries move toward stable delivery:
v3 stability 0.5 then 1.0; v2 stability +0.15, style -0.15 per attempt; Gemini adds "đọc thật rõ ràng, đầy đủ từng chữ".

## Current account constraints (2026-10-03)

- ElevenLabs key is **Free tier**: library voices return 402 (premade fallback, flagged by QA), no `wav_44100`.
- Gemini TTS without billing: **10 requests/day per model, 3/min**; scene batching makes an episode 1-3 requests.
- WaveSpeed key: provided by the organization, not yet in `.env`; plug it in after the offline demo passes (SETUP §3).
- Test fixture for the episode contract: `tests/fixtures/episode.json` (never `data/series/demo`, which is live data).
