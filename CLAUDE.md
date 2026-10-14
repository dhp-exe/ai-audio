# Emvoox Engine

Agentic production system that turns a trend or a Vietnamese story into a series of AI **audio** micro-drama episodes
voiced by fixed Virtual Actor IPs, so Emvoox can test audience retention cheaply before paying for video. Two ways of
working: a **workflow graph** (LangGraph) for production, and an **agent runtime** (tool-calling loop) for open-ended
work, reached through a chat with the Producer agent. Runs are durable and pause for human decisions.
What runs: `docs/ARCHITECTURE.md`. Keys and first live run: `docs/SETUP.md`.

**Migration status (2026-10-13):** Phases 0-4 of `docs/MIGRATION_PLAN.md` are built (workflow graph with parallel
scenes, durable runs, PostgreSQL / Redis, tenant-scoped storage, tool registry, agent runtime, chat). **Not built:**
Phase 5 (long-term memory, compaction) and Phase 6 (users, roles, per-tenant keys and budgets, metering). Target:
`docs/TARGET_ARCHITECTURE.md`.

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
| D4 | **No speech-to-speech.** TTS engines: Gemini TTS (default, free tier), ElevenLabs (Voice IPs), WaveSpeed (ElevenLabs v3 / MiniMax / Gemini 3.8 TTS via one key; the model path's vendor decides which of the actor's voices is used), mock (offline). Engine per run, per role type or per actor (Engine Policy); a **cloned** IP voice wins whenever its engine has a key. |
| D5/D6 | BGM and SFX implemented but **off by default** (`ENABLE_BGM`, `ENABLE_SFX`). |
| D7 | **Local-first storage behind repositories** (`DocumentStore` + `BlobStore`, keys = relative paths under `./data`); V1RON (`v1ron_db` + MinIO) later via `EMVOOX_STORAGE=v1ron`. Voice IPs in `data/assets/voice_registry.json` (global, locked). |
| D8 | Stereo master **-16 LUFS / -1.5 dBTP**, WAV + **MP3 192 kbps**. |
| D9 | Sequential concat from measured stem durations; no overlap. |
| D10 | LLM via adapters: Gemini (`gemini-3.1-flash-lite` default), WaveSpeed LLM / OpenAI-compatible, Claude, mock. Every call validated against a Pydantic contract. |
| D11 | **Human approval gate**: nothing is exported without a reviewer; FLAGGED episodes halt the run by default. |
| D12 | **Replaced (F5).** Episodes of a run are still produced in order, but the scenes of an episode run in parallel under a per-provider cap, and runs queue instead of being refused. Per-tenant limits come with Phase 6. |
| E1-E10 | Refactor decisions (asyncio engine instead of LangGraph/CrewAI, FFmpeg not pydub, casting as its own agent, bounded QA retry loop, rule-based Director fallback, optional selector-free browser scan…): `docs/ARCHITECTURE.md` §12. E1 is superseded by F1: the native engine is deleted, production runs on the workflow graph. |

## Agentic platform decisions (F1-F6, F9 built; F7, F8, F10 partly or not)

Full text and open items: `docs/TARGET_ARCHITECTURE.md`. Phase results and what each phase left out: `docs/MIGRATION_PLAN.md`.

| # | Decision | Status |
|---|---|---|
| F1 | Workflow graph on **LangGraph**; agents, contracts, providers, ledger and storage stay our own code. | Built |
| F2 | Agent loop where the path is unknown (research, the Producer chat); deterministic graph for production. The model cannot skip QA, mastering or the gate. | Built |
| F3 | Model-callable tool registry: Pydantic argument models, `area`, `kind` (`core`, `read`, `write`, `external`), loaded on demand. Existing skills are wrapped, not rewritten. | Built (14 tools) |
| F4 | LLM adapters have tool calling (`LlmClient.chat`). No LangChain model classes, no LiteLLM. | Built |
| F5 | The scene is the unit of QA and approval; scenes run in parallel under per-provider limits; episode mastering is the join. | Built |
| F6 | Durable runs: worker, queue (memory or Redis), checkpoints (SQLite or PostgreSQL), pause and resume. | Built |
| F7/F8 | Memory in three stores; compaction clear → summarise → drop. Agents save memory automatically; a person reads, edits and deletes. | **Not built** (Phase 5); conversation history exists as `AgentSession` |
| F9 | AI-first chat; one Producer agent owns the conversation and delegates to the specialist agents. | Built (replies arrive per model turn, not per token) |
| F10 | Multi-tenant: tenant in every storage key, users and roles, per-tenant keys, budgets and limits. | Storage scoping built; the rest is Phase 6 |
| F11 | Safety: D11 stays; `external` tools always need approval; scraped text is data, never instructions; a blocked page is never worked around; budgets are hard caps. | Built |
| F12 | Offline tests stay: the mock LLM plays scripted tool calls; outside sockets remain blocked. | Built |

Decided along the way: the **episode gate does not block the run** (a PASS episode is parked and the run continues; a
FLAGGED one halts it); PostgreSQL and Redis locally, media on local disk; the live `./data` is the `default` tenant as
it stands; the queue is our own (`JobQueue` protocol), not RQ.

Rules for this codebase:
- **Do not assume a planned component exists.** There is no `emvoox/memory` and no user or role model. Check the tree
  and `docs/MIGRATION_PLAN.md` before importing or documenting one.
- **Agents stay plain functions** that return contracts. A graph node or a tool calls an agent; an agent never
  imports LangGraph, the runtime or the tools.
- **The API never runs an engine.** It saves state and enqueues a `Job`; a worker does the work
  (`Engine.create` / `Engine.restore`).
- **In a graph node, nothing with a side effect comes before `interrupt`:** the node re-runs from its start on
  resume, and a paused sibling re-runs whenever another branch is resumed. Announce a wait in its own node.
- **Every graph node must be safe to repeat** (a recovered run re-runs the node that was in progress). Graph state
  holds small JSON values and ids; artifacts are read back from the repositories and re-validated.
- **A vendor request made from code that can run in parallel is wrapped in `ctx.slot(provider)`.**
- **A new tool** is one `@tool` function with a Pydantic arguments model in `emvoox/tools/`. Pick its `kind` honestly:
  anything that spends money or publishes is `external`. A tool whose result contains outside text is `untrusted=True`
  and returns an excerpt, never a whole page. The model never supplies a URL.
- **An agent never answers a decision that is a person's** (scene approval, budget, the episode gate, `external`
  tool approval).
- A new handoff, tool or event starts as a Pydantic model in `emvoox/contracts/`.
- New storage keys go through `emvoox.paths`; storage is reached through a tenant's `Repositories`, never a raw path.
- When a phase lands, update `docs/ARCHITECTURE.md` (what runs), its Result in `docs/MIGRATION_PLAN.md`, this file and
  the affected skill in the same change.
- **Never run Claude on the DreamHost server** (emvoox.com, `iad1-shared-e1-32.dreamhost.com`, SSH alias `emvoox`).
  It is shared hosting with severe resource limits. Do not install or start Claude Code, VS Code Server (Remote-SSH),
  builds, Python, Node or any long-running process there, and do not edit files on the server. Claude works only on the
  local machine. The server is touched by `scripts/deploy_landing.sh` (rsync) and by short read-only checks
  (`ls`, `tail` of `~/logs/emvoox.com/https/error.log`).

## Repository layout

```
emvoox/
  config.py            Settings from .env (EMVOOX_*; legacy AI_AUDIO_* still read)
  paths.py             every storage key and stem name (never hand-build one)
  contracts/           Pydantic payloads: market, production (story/bible/script/registry/timeline), script, cast,
                       direction, audio, qa (episode + scene reports), release, run (state, scenes, pending decisions),
                       jobs, agentic (tools, sessions), chat, telemetry
  agents/              market_research, script_writer, casting, director, sound_engineer, qa_critic, publisher (+ base)
  workflow/            LangGraph: series_graph.py (run), episode_graph.py, scene_graph.py, checkpoints.py, limits.py
  engine/              orchestrator.py (Engine: run state, events, _step, start / resume / recover, CLI `run`), events.py
  worker/              queue.py (JobQueue: MemoryQueue, RedisQueue), worker.py (Worker, embedded worker, CLI `worker`)
  runtime/             loop.py (agent loop on an AgentSession), permissions.py (the gate), agents.py (AgentSpec configs),
                       context.py (memory and compaction hooks: empty until Phase 5)
  tools/               base.py (@tool, registry, ToolContext), core.py, research.py, library.py, production.py
  repositories/        base.py (protocols), local.py (JSON, SQLite, disk), postgres.py, tenancy.py (tenant scoping),
                       repos.py (typed repositories, registry lock), factory.py, v1ron.py (MinIO stub)
  providers/llm/       gemini, openai_compat (WaveSpeed/OpenAI), anthropic_llm, mock; LlmClient (structured + chat)
  providers/tts/       gemini, elevenlabs, wavespeed, mock, catalog, base
  delivery/            compile.py (Delivery Compile), plan.py (Render Plan), screenplay.py (rule-based reading)
  audio/               ffmpeg.py, timeline.py, mix.py (concat, ducked bed, SFX, two-pass loudnorm)
  telemetry/           ledger.py, pricing.py, usage.py (costs + quotas), events.py (vendor 429/402)
  services/            library.py (productions views), runs.py (start a run), research.py (scans as jobs, loop mode),
                       chat.py (threads, turns, the client view), previews.py, doctor.py
  api/app.py           FastAPI; serves web/out at /
  cli.py               python -m emvoox serve | worker | run | decide | research | approve | reject | voices | plug-voice | doctor | agents
web/                   Next.js 16 + Ant Design 6; web/lib/api.ts is the API contract; app/page.tsx is the Producer chat
data/                  assets/, inputs/, research/, series/<id>/, agents/sessions/, chat/threads/, runs/, outputs/, telemetry/,
                       tenants/<id>/ (the same layout for any tenant other than "default")
landing/               emvoox.com landing page: static HTML/CSS/JS + contact.php for DreamHost (landing/README.md)
scripts/demo_pipeline.py   offline end-to-end demo (mock LLM + mock voices, injected fault)
tests/                 pytest, offline: outside sockets blocked, .env not loaded (EMVOOX_SKIP_DOTENV); PostgreSQL and
                       Redis tests run against localhost and are skipped when absent
docker-compose.durable.yml   adds PostgreSQL, Redis and a worker (written, not yet run)
.claude/skills/        emvoox-pipeline, voice-ip-registry, market-research
```

## Running

```bash
docker compose up --build                                    # everything in one container at http://localhost:8765 (teammates)
python -m emvoox serve                                       # API + web app + an embedded worker (build web once: cd web && npm run export)
python -m emvoox worker                                      # extra workers, with EMVOOX_QUEUE=redis
cd web && npm run dev                                        # UI dev server :3000, proxies /api
python scripts/demo_pipeline.py                              # offline demo
python -m emvoox run --series s1 --story story.txt --episodes 30 --produce 3 --tts gemini   # runs in this process, no queue
python -m emvoox run --series s1 --story story.txt --scene-approval --max-cost 2             # pauses for decisions
python -m emvoox decide --series s1                          # list what a paused run waits for; --scene sc01 --approve --reviewer <name> to answer
python -m emvoox research --agent --browser --guide "..."    # market research as a tool loop
python -m emvoox run --series s1 --only 4-6                  # continue
python -m emvoox approve --series s1 --episode 1 --reviewer <name>
```

Durable setup: `EMVOOX_STORAGE=postgres` + `EMVOOX_DATABASE_URL`, `EMVOOX_QUEUE=redis` + `EMVOOX_REDIS_URL`, extra
`pip install -e '.[durable]'`. Default is local files, SQLite checkpoints and the in-process queue.

## Conventions

### Code
- Python 3.11+, type hints, **Pydantic v2 for anything crossing an agent or file boundary**. Agents return contracts;
  the engine re-validates every handoff.
- Agents never touch paths or vendor SDKs: storage only through `ctx.repos`, LLM only through `ctx.llm.structured(...)`
  (the agent loop uses `ctx.llm.chat(...)`), TTS only through `providers.tts.get_provider(...)`. Keys only via `emvoox.paths`, settings only via `get_settings()`.
- Every LLM call, TTS request, agent step and tool call goes to the ledger (`ctx.ledger`) with tokens/characters/time/cost.
- Stems cached by content hash (`TtsRequest.content_hash`, includes the retry attempt); skip on match unless `force`.
- Prompts in Vietnamese; Emvoox Anti-Trope rules in `contracts/script.py`.
- Voice IPs are reusable actors: `persona` and `voice_description` describe the voice and personality, never one story.
  Agents never add characters to the registry. The Script Writer may not write more named roles per gender than there
  are Voice IPs; only background roles (`minor`) may get a temporary voice, stored in that production's `cast.json` only.
- Tests under `tests/`, no outside network (sockets blocked except localhost), `ruff` line length 160 (prompt-heavy
  modules exempt from E501). The test default LLM provider is `gemini`: a test that drives the chat sets it to `mock`.
- Every CLI command ends with a one-line JSON summary and exits non-zero on failure.

### Stem names (underscore separates fields; ids are `[a-z0-9-]`)
```
ep{NN}_sc{NN}_l{NNN}_{actor_id}_{dialogue|monologue}.wav    one line
ep{NN}_sc{NN}_c{NN}_chunk.wav                               one multi-speaker conversation request
ep{NN}_master.wav | .mp3 | .json,  ep{NN}_timeline.json
qa/ep{NN}_report.json (episode)   qa/ep{NN}_sc{NN}.json (one scene)
```

### Audio format
Stems WAV 44.1 kHz / 16-bit / mono. Masters stereo WAV + MP3 192 kbps at -16 LUFS / -1.5 dBTP. Director pauses
clamped to 300-500 ms; `pause` units uncapped; scene gap 800 ms; 500 ms tail.

### Emotional intensity → engine settings (`delivery/compile.py`)

| intensity | v3 `stability` / `similarity_boost` | v2 `stability` / `style` | Gemini direction | WaveSpeed |
|---|---|---|---|---|
| 1-3 | 0.5 / 0.80 | 0.70 / 0.15 | `giọng <emotion> (nhẹ)` | ElevenLabs v3: stability as v3; MiniMax: emotion, speed from pace, volume from volume; Gemini 3.8 TTS: the Gemini direction as `style_instructions`, dialogue chunks as turns |
| 4-6 | 0.5 / 0.75 | 0.50 / 0.30 | `(vừa phải)` | |
| 7-8 | 0.0 / 0.65 | 0.40 / 0.40 | `(mạnh)` | |
| 9-10 | 0.0 / 0.55 | 0.30 / 0.50 | `(rất mạnh, cao trào)` | |

A voice's `default_settings` (identity anchor of a cloned voice) always win. QA retries move toward stable delivery:
v3 stability 0.5 then 1.0; v2 stability +0.15, style -0.15 per attempt; Gemini adds "đọc thật rõ ràng, đầy đủ từng chữ".

## Landing page (emvoox.com)

Static site in `landing/` (no build step), hosted on DreamHost shared hosting; details in `landing/README.md`.
1. Edit locally in `landing/`. English copy is in `index.html`; every `data-i18n` key also needs its Vietnamese text in
   `assets/js/i18n.js`. When CSS or JS changes, bump its `?v=` in `index.html`.
2. Preview locally: `cd landing && python3 -m http.server 8811` → `http://127.0.0.1:8811` (and `?lang=vi`). Check
   both languages, light and dark, and a phone width. The contact form only works on the server.
3. Commit the change in git.
4. Deploy: `scripts/deploy_landing.sh` (dry run, uploads nothing), check the list, then `scripts/deploy_landing.sh --live`.
   It never deletes server files.
5. Check https://emvoox.com (Cmd+Shift+R). The live site is public: a deploy needs the user's go-ahead.

Facts not to lose: the form sends from and to `dhp@emvoox.com`; public copy must not claim what the team flagged as
hypotheses (see `landing/README.md`); KnitOS is not mentioned on the page.

## Current account constraints (2026-10-13)

- `.env` holds only `WAVESPEED_API_KEY` (checked 2026-10-13); the two lines below apply when those keys are added back.
- ElevenLabs key is **Free tier**: library voices return 402 (premade fallback, flagged by QA), no `wav_44100`.
- Gemini TTS without billing: **10 requests/day per model, 3/min**; scene batching makes an episode 1-3 requests.
- WaveSpeed key: in `.env` (prepaid balance). LLM gateway and `elevenlabs/eleven-v3` TTS verified live 2026-10-03 with one call each; the gateway does not list its models (verified ids in SETUP §3).
- Live checks on 2026-10-13 (WaveSpeed LLM only, about 6 cents): `google/gemini-3.1-flash-lite` and
  `google/gemini-3.6-flash` each drove the research tool loop to a brief 2 of 2 times. The gateway has **no web search**
  (it accepts the parameter and returns unsourced answers). The chat and scene-level production have not run on real vendors.
- Local PostgreSQL 18 and Redis 8 are used by the tests: databases `emvoox` and `emvoox_test`, Redis db 15 (tests) and 14.
- Test fixture for the episode contract: `tests/fixtures/episode.json` and the series bible `tests/fixtures/series.json` (tests never read `data/series/`, which is live data).
