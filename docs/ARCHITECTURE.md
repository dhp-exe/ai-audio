# Emvoox Engine: architecture

| | |
|---|---|
| Status | Implemented through Phase 4 of `docs/MIGRATION_PLAN.md`. Offline end-to-end demo and 160 tests (159 pass, 1 skipped) |
| Date | 2026-10-03; rewritten 2026-10-13 for the workflow graph, durable runs, the agent runtime and the chat |
| Next | This document describes what runs today. Still planned: long-term memory and compaction (Phase 5), users, roles and metering (Phase 6); see `docs/TARGET_ARCHITECTURE.md` and `docs/MIGRATION_PLAN.md` |
| Replaces | the stage-script pipeline (`pipeline/`, `.claude/skills/*/scripts/`), `docs/ARCHITECTURE.md` v0, `docs/IMPLEMENTATION_PLAN.md`, `docs/System_Flow_Map.*`, `docs/Technical_Specification.md` (still in git history) |
| Sources | `emvox.docs/emvox technical map.png`, `emvox.docs/TỔNG HỢP DỰ ÁN EMVOOX VÀ KÊNH MẶC KHẢI.pdf`, `docs/Emvox_Technical_Map.md` |

Emvoox is an AI entertainment studio: fixed Virtual Actors (own voice, own look) perform Vietnamese micro-dramas, and
audio is the cheap funnel that decides which series earn a video budget. **Emvoox Engine** is the production system
for that funnel. It has two ways of working, each used where it fits:

- a **workflow graph** (LangGraph) for production, where order is fixed and money is spent under guarantees: seven agents
  with typed contracts, scenes produced in parallel with their own QA, retry and approval loops, and a human gate
  before anything is exported;
- an **agent runtime** for work whose path is not known in advance: a model calls tools from a registry, inside a
  permission gate, a step limit and a budget. The Market Research agent can run this way, and the **Producer** agent
  behind the chat does.

Runs are durable: a worker takes them from a queue, they pause wherever a person has to decide, and they continue from
a checkpoint in whichever process picks them up. Storage is tenant-scoped and can live in PostgreSQL.

---

## 1. System at a glance

```mermaid
flowchart TB
  subgraph Studio["Emvoox Studio (web/ Next.js 16 + Ant Design 6)"]
    UI["Producer chat · Dashboard · Productions · New production · Pipeline · Approvals · Voice IPs · Market research · Costs · Settings"]
  end
  UI -->|"JSON /api (web/lib/api.ts)"| API["FastAPI (emvoox/api/app.py)"]
  API -->|"saves the run / thread, enqueues a job"| Q[("Queue: memory | Redis")]
  Q --> W["Worker (emvoox/worker)"]

  subgraph RT["Agent runtime (emvoox/runtime)"]
    LOOP["loop: context → model → permission gate → tools → repeat"]
    PROD["Producer (chat)"] --- MRA["Market Research (loop mode)"]
  end
  subgraph TOOLS["Tool registry (emvoox/tools)"]
    T["core · research · library · production"]
  end
  W --> RT
  RT --> TOOLS

  subgraph WF["Workflow graph (emvoox/workflow, LangGraph)"]
    direction TB
    SER["series: [research] → script → casting"] --> EP["episode: draft → direct"]
    EP --> SC["scenes in parallel: render → QA → retry (≤3) → [approval]"]
    SC --> JOIN["join → master → episode QA → gate"]
  end
  W -->|"Engine (emvoox/engine)"| WF
  TOOLS -->|"production_start (needs approval)"| Q

  subgraph Fleet["Agents as plain functions (emvoox/agents)"]
    MR["Market Research"] --- SW["Script Writer"] --- CA["Casting"] --- DI["AI Director"] --- SE["Sound Engineer"] --- QA["QA Critic"] --- PU["Publisher"]
  end
  WF --> Fleet
  TOOLS --> Fleet

  subgraph Providers["Providers (emvoox/providers)"]
    LLM["LLM (structured output + tool calling): Gemini · WaveSpeed · OpenAI-compatible · Claude · mock"]
    TTS["TTS: Gemini TTS · ElevenLabs · WaveSpeed · mock"]
  end
  Fleet --> Providers
  RT --> Providers

  subgraph Data["Repositories, per tenant (emvoox/repositories)"]
    DS[("DocumentStore: JSON files | SQLite | PostgreSQL")]
    BS[("BlobStore: ./data → MinIO later")]
    CP[("Checkpoints: SQLite file | PostgreSQL")]
  end
  Fleet --> Data
  WF --> CP
  RT --> Data
```

One series flows through three series steps and six episode steps:

| Step | Agent | Skills | Output contract | Stored at (`data/series/<id>/…`) |
|---|---|---|---|---|
| `research` (optional) | Market Research | Search Plan, Market Scan, Content Analyze, Trend Ranking | `TrendBrief` | `trend_brief.json` (+ `research/briefs/<id>.json`) |
| `script` | Script Writer | Story Adapt, Episodize (outline) | `ScriptPackage` = `StoryInput` + `SeriesBible` | `story.json`, `story_raw.txt`, `series.json` |
| `casting` | Casting & Voice IP Curator | Voice Registry, Casting Match, Engine Policy | `ResolvedCast` (+ `EnginePolicy`) | `cast.json`, `assets/voice_registry.json` |
| `epNN.draft` | Script Writer | Episodize (draft), Cliffhanger Check | `EpisodeDraftResult` (+ `CliffhangerCheck`) | `scripts/raw/epNN.txt`, `scripts/checks/epNN.json` |
| `epNN.direct` | AI Director | Parse Script, Delivery Compile, Render Plan | `DirectedConversationUnits` | `scripts/parsed/epNN.json`, `directed/epNN.json` |
| `epNN.voice` (all scenes) | Sound Engineer + QA Critic, per scene | Generate Voice, QA Audio, Review Audio | `VoiceRenderResult` (summed), one `SceneQAReport` per scene | `stems/epNN/*.wav` + `.meta.json`, `render.json`, `qa/epNN_scNN.json` |
| `epNN.master` | Sound Engineer | Generate SFX, Assemble Audio | `MasteredEpisode` | `timelines/`, `masters/epNN_master.{wav,mp3,json}` |
| `epNN.qa` | QA Critic | roll-up of the scene reports + master checks | `QAReport` | `qa/epNN_report.json` |
| `epNN.gate` | Approval Gate & Publisher | Approval Gate, Publish Metadata, Local Export | `ReleasePackage` | `release/epNN.json`, `outputs/approved_masters/<id>/` |

---

## 2. Agents

Every agent is a class in `emvoox/agents/` with a small set of skills (methods), one output contract, and nothing
else: no file paths, no vendor SDKs, no knowledge of the other agents. It receives an `AgentContext` (settings,
repositories, LLM client, telemetry ledger, run parameters, a log sink, a cancel flag) and returns a Pydantic model.

### 2.1 Market Research Agent (`market_research.py`)
- **Search Plan**: runs only when the editor gave a `guide` and the browser is on. One LLM call → `SearchPlan`: how the
  guide was understood (`intent`) and at most two searches each for TikTok, Google and YouTube. The model writes only
  search words; the agent builds the URL (`SEARCH_URL`) and drops URLs, duplicates and platforms the run did not ask
  for. The searches replace the fixed search pages of their platform; home pages (DramaBox, ReelShort) are still read.
  Without a guide, or when the call fails, the scan reads the fixed sources. Intent and queries are saved on the `ScanState`.
- **Market Scan**: observations from text pasted into the run, every `.md/.txt/.json` under `data/inputs/trends/`, and
  (when `use_browser` / `EMVOOX_RESEARCH_USE_BROWSER`) the visible text of public pages on DramaBox, ReelShort, TikTok,
  Google and YouTube through headless Chromium (Playwright, optional extra; sources in `DEFAULT_SOURCES` or
  `inputs/market_sources.json`). No per-site selectors: the page text goes to the model, so a redesign of a site does
  not break the scan. A robot check, login wall or error page is recorded as **blocked** and never worked around.
- **Scan record**: every source is a `ScanStep` (status, characters read, excerpt, screenshot) in a `ScanState`
  document saved after each step. `POST /api/research/scan` starts the agent in a background thread and returns the
  scan; the Market research page polls `GET /api/research/scans/{id}` once a second and shows the pages being read.
- **Content Analyze**: one LLM call → `MarketAnalysis`: insights per reference title, and the **three most trending
  genres**, each with its evidence from the data, the platforms it was seen on, a new story direction, three 1-10
  ratings (audience fit, momentum, production fit) and the nearest Mặc Khải content line (`urban_ceo`,
  `intellectual_slap_anti_trope`, `rebirth_butterfly_effect`, or `other`). The editor's free-text `guide` has priority:
  the prompt carries the guide, the plan's intent and its searches, and asks the model to say so when the data cannot answer it.
- **Trend Ranking**: deterministic score `0.45·audience_fit + 0.30·momentum + 0.25·production_fit`; genres on the
  editor's `focus` line rank first; the top three are kept in the `TrendBrief`.
- **Loop mode** (`agent: true` on a scan, `research --agent`): instead of the fixed order, the model drives the
  research with four tools (`research_read_notes`, `research_read_platform`, `research_search`,
  `research_write_brief`; §6). It never supplies a URL, sees only an excerpt of each page, and ends in the same
  Content Analyze + Trend Ranking, so the brief has the same shape. Every source it reads is a `ScanStep` like any other.
- **Human pick**: the editor chooses one of the three (`POST /api/research/briefs/{id}/select`); the brief's top-level
  fields (topic, hook, premise, genre…) mirror the pick and that is what the Script Writer's Story Adapt receives. A
  run started with `source = research` does not stop for the pick and uses the top-ranked genre.

### 2.2 Script Writer Agent (`script_writer.py`)
- **Story Adapt**: `TrendBrief` → `StoryInput` (title, 2-5 roles each with their own goal and motive, an act-by-act
  treatment). Skipped when a human supplies the story.
- **Episodize**: the outline call splits the story into N episodes (`SeriesBible`: premise, tone, role list with role
  types, episode plans that each end on a cliffhanger). Mode is picked from input length: *segment* keeps the author's
  dialogue verbatim (verbatim ratio checked, one retry), *write* expands a treatment (word floor enforced). Roles leave
  this agent **uncast**: casting belongs to the next agent. Then one draft call per episode renders the screenplay.
- **Roster limit**: Story Adapt and the outline are told how many female and male Voice IPs exist
  (`casting.roster_capacity`) and may not write more *named* roles (protagonist, antagonist, supporting) of either
  gender; a version that exceeds it is sent back once. Whatever still does not fit (for example a pasted script with a
  large cast) is demoted to a background role (`minor`). Every role carries an explicit `gender`, which decides the
  voice. Drafts may not add speaking characters.
- **Cliffhanger Check**: an LLM editor scores the hook 1-10 and checks the Emvoox **Anti-Trope rules**
  (`contracts/script.py::ANTI_TROPE_RULES_VI`): independent motivations, a twist within ~30 s (≈100 words), a smart
  antagonist, prepared reveals, consequences, a resolved ending. Below `EMVOOX_CLIFFHANGER_MIN_SCORE` (6) a write-mode
  episode is rewritten once with the critique; segment mode keeps the author's text and flags it. A rule-based check
  stands in when the LLM check is off or fails.

### 2.3 Casting & Voice IP Curator Agent (`casting.py`)
- **Voice Registry**: reads the locked registry; adds a voice on an engine an actor does not have yet (an addition, so
  the lock is not involved). The agent **never adds a character**: Voice IPs are created by people (Voice IPs page, API).
  A Voice IP profile describes the voice and personality only, never a story: one IP plays many roles across series.
- **Casting Match**: named roles are always played by Voice IPs: director pins (`/ngan` in the story form, or the
  dropdown) → an LLM proposal over the free actors (gender, age, persona, timbre; a proposal whose gender does not match
  the role is rejected) → a rule-based gender match. Background roles (`minor`) take a Voice IP that is still free,
  otherwise a **temporary voice** that exists only in that production's `cast.json` and is kept across its later runs.
  One actor plays one role per series.
- **Engine Policy**: per actor, the first available of `by_actor` → the actor's **cloned / preferred voice** (when
  `prefer_cloned`) → `by_role_type` (e.g. protagonist on ElevenLabs, minor roles on Gemini) → the run's default engine.
  An engine whose key is missing is skipped with a run note. WaveSpeed reuses an actor's ElevenLabs voice id through its
  hosted ElevenLabs v3 endpoint. `tier: final` refuses temporary voices on named roles. Output: `ResolvedCast` with, per role, the
  actor, provider, model, voice id, voice source (`prebuilt | premade | library | cloned | placeholder`) and the voice's
  identity settings.

### 2.4 AI Director Agent (`director.py`)
- **Parse Script**: one structured LLM call → `EpisodeScript` (scenes, lines, actor id + role name, emotion enum,
  intensity 1-10, ≤2 approved audio tags, acoustic direction, pace, volume, pause after). Post-conditions the schema
  cannot express are enforced in code (every speaker is in the resolved cast, protagonist alias resolved). Two rejected
  answers fall back to a rule-based reading of the screenplay with neutral delivery and a run note, so production is
  never blocked by a malformed answer.
- **Delivery Compile** (`delivery/compile.py`): per line and engine, the normalized Vietnamese text (`text/vi_normalize.py`),
  tags kept where the engine reads them (ElevenLabs v3, WaveSpeed's ElevenLabs endpoint) or folded into a Vietnamese
  acting direction (Gemini), and the settings vector (v3 discrete stability, v2 continuous stability/style, MiniMax
  emotion/speed/volume). The voice's own `default_settings` (a cloned voice's identity anchor) are never overridden.
- **Render Plan** (`delivery/plan.py`): consecutive lines of one scene on a multi-speaker engine (Gemini) with ≤2 actors
  become one *conversation* request (1-3 requests per episode instead of 8-12); everything else is one request per line.
  Mixed engines in one scene are supported. The plan is part of the contract.
- **Output contract** `DirectedConversationUnits`: ordered units with `speaker_id`, `text`, `tts_text`, `emotion_tag`,
  `emotional_intensity`, `audio_tags`, `direction`, `pause_after_ms`, `speed`, `pitch`, `volume`, the resolved
  provider/model/voice and settings; plus the `render_plan` (validators: sequential order, ids belong to the episode,
  every spoken unit covered exactly once).

### 2.5 Sound Engineer Agent (`sound_engineer.py`)
- **Generate Voice**: executes the render plan through the TTS adapters; canonical stems (WAV 44.1 kHz / 16-bit / mono)
  with a sidecar per stem (content hash, request, cost, alignment, attempt). A stem is regenerated only when the hash of
  (provider, model, voice, final text, settings, speakers, retry attempt) changes. Bounded thread pool (Gemini serial for
  free-tier RPM). ElevenLabs "paid plan required" on a library/cloned voice → the actor's premade fallback, flagged.
- **Generate SFX**: cues from `assets/sfx/<tag>.wav`, or generated with ElevenLabs sound effects when `ENABLE_SFX` and the
  key are set (then cached in the library). Off by default (D6).
- **Assemble Audio** (`audio/`): timeline from measured stem durations (Director pauses clamped to 300-500 ms, `pause`
  units kept whole, 800 ms scene gaps, 500 ms tail), optional music bed from `assets/bgm/<mood>/` looped under the
  speech and ducked by sidechain compression (`ENABLE_BGM`, off by default per D5), SFX at their offsets, two-pass
  loudnorm to **-16 LUFS / -1.5 dBTP**, stereo WAV + MP3 192 kbps. Output `MasteredEpisode` with measured loudness.

### 2.6 QA Critic Agent (`qa_critic.py`)

| Check | Method | Issue code | Severity | Retry action |
|---|---|---|---|---|
| Stem present for every render unit | storage | `missing_stem` | blocker | `rerender` |
| Missing sentence | stem duration < 45 % of what its words need at 3.6 w/s | `missing_sentence` | major | `rerender`; a conversation chunk → `rerender_line_mode` |
| Extra speech / spoken direction | duration > 240 %, or transcript has header words | `duration_off`, `direction_leak` | major | same |
| Clipping | `astats` peak ≥ -0.1 dBFS | `clipping` | major | `rerender` (more stable settings) |
| Silence inside a stem | `silencedetect` -50 dB ≥ 1.5 s, or a silent stem | `long_silence` | major | `rerender` |
| Speaker mismatch | sidecar voice ≠ resolved cast voice | `speaker_mismatch` | major | `rerender` |
| Placeholder voice | ElevenLabs plan fallback used | `placeholder_voice` | minor | none (human decides) |
| Master loudness / true peak | `ebur128` vs target ±1 LU, TP ≤ target + 0.1 | `loudness_off`, `true_peak_over` | major | `reassemble` |
| Master duration | 50-160 % of the target | `master_duration_off` | minor | none (script length) |
| Mispronunciation (optional) | `EMVOOX_QA_TRANSCRIBE`: LLM transcript of each stem, word error rate > 25 % | `mispronunciation` | major | `rerender` |

**Two levels.** Scenes are produced in parallel, so the stem checks run per scene (`review_scene` → `SceneQAReport`,
with the retries that scene can do). The episode report (`run`) rolls the scene reports up, places each issue on the
master's timeline, and adds the checks only a master can answer (loudness, true peak, duration).

Score = 100 - 25·blocker - 12·major - 3·minor. **FLAGGED** when any blocker/major remains or the score is below
`EMVOOX_QA_PASS_SCORE` (80). Every issue carries the render unit, the line and its **timestamp in the master**
(`at_ms`). Lines a human should hear anyway (intensity ≥ 9, intense monologues) are listed in `review_lines`.

### 2.7 Human Approval Gate & Publisher (`publisher.py`)
- **Approval Gate**: nothing is exported without a human. PASS → `awaiting_approval`; still FLAGGED after the retries →
  `needs_review` with the reason. `auto_approve` exports PASS episodes only. Approving a FLAGGED episode is allowed and
  recorded as an override. A reviewer name is required.
- **Publish Metadata**: YouTube title, description (with the AI-voice disclosure), tags, hashtags, playlist, thumbnail
  text; LLM with a rule-based fallback; editable at the gate.
- **Local Export**: approved WAV + MP3 + `<ep>.youtube.json` to `data/outputs/approved_masters/<series>/`, and a
  publishing mock-up receipt (`ready_for_upload`). The upload itself is not wired in Prototype V1.

---

## 3. Engine and workflow graph (`emvoox/engine/`, `emvoox/workflow/`)

```mermaid
stateDiagram-v2
  [*] --> research: source = research
  [*] --> script: source = story | brief | existing
  research --> script: TrendBrief
  script --> casting: ScriptPackage
  casting --> pick: ResolvedCast
  pick --> budget: spent ≥ cap (pause)
  budget --> pick: raised
  budget --> [*]: declined (halted)
  pick --> draft: next episode
  state "episode" as EP {
    draft --> direct
    direct --> scenes: DirectedConversationUnits (validated)
    state "scenes, in parallel" as scenes {
      render --> check
      check --> retry: FLAGGED and attempt < max_retries
      retry --> render: only the flagged units
      check --> approve: scene_approval (pause)
      approve --> redo: rejected
      redo --> render
    }
    scenes --> join: every scene done
    join --> master: plan saved once, manifest written
    master --> qa
    qa --> master: loudness off, re-master (bounded)
    qa --> gate
  }
  gate --> pick: parked for approval
  gate --> [*]: FLAGGED and halt_on_qa_fail (halted)
```

- **Who does what.** The graphs in `emvoox/workflow` (`series_graph`, `episode_graph`, `scene_graph`) decide order,
  fan-out, pauses and checkpoints. `Engine` is what their nodes run with: the run's state and events, the ledger, the
  agents, and `_step`, which runs one agent call in a worker thread, re-validates its output against the declared
  contract, retries a rejected handoff once when the agent says it is retryable, and records time and cost.
- **Scenes in parallel.** Each scene renders, is checked (`SceneQAReport`), and retries only its own flagged units up
  to `max_retries`, with the Director's retry parameters. Vendor requests of all scenes share one cap per provider
  (`ProviderLimiter`, held around every `synthesize` call). A scene works from an unsaved view of the plan; the join
  saves the plan once with every scene's retry parameters, writes the render manifest, and only then is the episode
  mastered.
- **Pauses.** A run stops for a person in three places: a scene waiting for approval (`RunParams.scene_approval`; a
  rejection re-renders the scene or the units the reviewer names, and asks again), the budget (`max_cost_usd`, checked
  before each episode: raise it or the run halts), and a FLAGGED episode (halts the run, as before). A paused run has
  status `waiting` and its open decisions in `RunState.pending`; answering them continues it.
- **The episode gate is not a pause.** An episode that passes QA is parked for approval and the run goes on to the next
  one. Nothing is exported without a human (D11); `approve` / `reject` are separate actions.
- **Durable.** The run graph is checkpointed after every step (thread = tenant + run id; a SQLite file under the data
  directory, or PostgreSQL). What the engine does follows from the saved state: `pending` → start, `waiting` → continue
  with the answers, `running` → the process that had it died, so recover from the last checkpoint. The node that was
  running then runs again, so nodes are repeat-safe: stems are reused by content hash, and a forced render skips what
  this very run already rendered. A recovered LLM step is paid for again.
- **In a graph node, nothing with a side effect comes before `interrupt`.** A paused node re-runs from its start when
  it is resumed, and a paused sibling re-runs whenever another branch is resumed; a wait is announced in its own node.
- **Events.** Every transition is a `PipelineEvent` (`run.started | waiting | resumed | recovered | finished`,
  `step.*`, `contract.rejected`, `scene.qa | waiting | approved | rejected | failed`, `qa.flagged`,
  `budget.waiting | raised`, `gate.*`, `episode.stopped`). The subscriber persists `RunState` after each one; sequence
  numbers continue across the processes of one run.
- **Run state** (`RunState`): steps with status / attempts / timing / cost / summary, the scenes (`SceneRun`: status,
  attempt, score, issues, reviewer), open decisions, the current budget, notes, the casting table, totals and the
  engines used. Totals carry over from the processes that did the earlier work.

### 3.1 Queue and workers (`emvoox/worker/`)

- The API never runs an engine. It saves a run as `pending` (`Engine.create`) and enqueues a `Job`; answering a
  decision or sending a chat message enqueues one too. A job names its run, it does not carry it: the worker rebuilds
  the engine from storage (`Engine.restore`).
- **Queues.** `memory` (default): jobs live in the API process, which also runs the worker thread; at startup the API
  re-enqueues runs that were queued or in progress. `redis`: jobs are shared and survive restarts; start
  `python -m emvoox worker` processes. A claimed job has a lease the worker renews; when the worker dies the lease
  expires and any worker puts the job back, marked `recover`.
- A per-run lock keeps two jobs of one run from executing at once. Cancel is a signal on the queue: a worker stops the
  run after the current step; a queued run is closed when it is claimed.
- Job kinds: `run` (start, resume, recover), `scan` (market research), `chat` (one turn of a conversation).

---

## 4. Data layer (`emvoox/repositories/`)

```mermaid
flowchart LR
  A["Agents · Engine · API"] --> R["Typed repositories<br/>VoiceRegistry · Series · Runs · Telemetry · Research · Assets · Outputs"]
  R --> D{{"DocumentStore protocol"}}
  R --> B{{"BlobStore protocol"}}
  D --> J["JsonDocumentStore (default)"]
  D --> S["SqliteDocumentStore"]
  D --> P["PostgresDocumentStore (EMVOOX_STORAGE=postgres)"]
  B --> L["LocalBlobStore (./data)"]
  B -.-> M["MinioBlobStore → V1RON Media (stub)"]
```

- Every artifact has one **key**: a POSIX path relative to the storage root, built only by `emvoox/paths.py`
  (`series/<id>/directed/ep01.json`, `assets/voice_registry.json`, …). Locally the key is a file under `./data`; on V1RON
  it is the document id in `v1ron_db` and the object name in MinIO.
- `DocumentStore`: `get/put/delete/exists/list/append/read_log/mtime/delete_prefix`. Two local implementations honour the
  same contract test (`tests/test_repositories.py`): one JSON file per document (default, human-readable, diffable) and
  SQLite (`EMVOOX_DOC_STORE=sqlite`, the shape a PostgreSQL JSONB table takes).
- `BlobStore`: `path/commit/local/exists/list/...`. FFmpeg and the SDKs need real files, so a remote store hands out a
  local cache path; `commit()` uploads after writing, `local()` downloads on a miss. Locally both are no-ops.
- **Tenants.** `get_repositories(tenant)` returns one tenant's bundle. The `default` tenant is the storage root itself
  (an existing single-studio `./data` is the default tenant as it is); any other tenant lives under `tenants/<id>/`.
  Scoping is done once around the two backends (`repositories/tenancy.py`): a key that tries to leave its tenant is
  refused, and the default tenant cannot address `tenants/`. PostgreSQL rows carry the tenant in their primary key.
  Nothing chooses a tenant per request yet (`EMVOOX_TENANT` per process); that arrives with users and roles (Phase 6).
- **PostgreSQL** (`EMVOOX_STORAGE=postgres`, `repositories/postgres.py`): documents, run state, logs and the graph's
  checkpoints in one database; media files stay on local disk. The same contract test runs against JSON, SQLite and
  PostgreSQL.
- **Still to do for `EMVOOX_STORAGE=v1ron`**: `MinioBlobStore` in `repositories/v1ron.py`. Agents, engine and API do not change.

Local layout (`./data`, `EMVOOX_DATA_DIR`):

```
data/
  assets/voice_registry.json      locked Voice IP registry (global)
  assets/previews/, auditions/    cached voice previews, ad-hoc auditions
  assets/bgm/<mood>/, assets/sfx/ music beds and effect clips (optional)
  inputs/trends/*.md|txt|json     trend notes for the Market Research Agent; inputs/market_sources.json (browser targets)
  research/briefs/<id>.json       TrendBriefs
  research/scans/<id>.json        scan records (progress, sources, log); research/scans/<id>/*.jpg page screenshots
  research/observations/<id>.json full text an agent-driven scan has read (the conversation keeps excerpts)
  agents/sessions/<id>.json       AgentSession: one agent working on one task (a chat thread, a research loop)
  chat/threads/<id>/              thread.json and events.jsonl of one conversation with the Producer
  runs/checkpoints.sqlite         workflow graph checkpoints (local storage)
  tenants/<tenant>/…              the same layout for every tenant other than "default"
  series/<id>/                    story, bible, cast, scripts, directed units, stems, timelines, masters, qa, release,
                                  run.log.jsonl (ledger), pipeline_run.json (run state), logs/ (step logs, events.jsonl)
  outputs/approved_masters/<id>/  epNN.mp3, epNN.wav, epNN.youtube.json (approved only)
  telemetry/run_log.jsonl         ledger rows not tied to a series (previews, research, auditions)
  telemetry/usage_events.jsonl    vendor 429 / 402 / quota events
```

---

## 5. Providers (`emvoox/providers/`)

| Kind | Provider | Adapter | Notes |
|---|---|---|---|
| LLM | Gemini (`gemini-3.1-flash-lite` default) | `llm/gemini.py` | Pydantic `response_schema`, retries on 429/5xx, IPv4 pin, audio transcription for Review Audio |
| LLM | **WaveSpeed LLM** (`https://llm.wavespeed.ai/v1`) | `llm/openai_compat.py` | OpenAI Chat Completions protocol, `vendor/model` ids (Gemini, Claude, GPT, DeepSeek…), JSON mode + schema in the prompt + one repair round |
| LLM | OpenAI or any compatible gateway | `llm/openai_compat.py` | same adapter, `OPENAI_API_KEY` |
| LLM | Claude | `llm/anthropic_llm.py` | official SDK, `messages.parse(output_format=…)`, optional extra `.[claude]` |
| LLM | mock | `llm/mock.py` | deterministic, schema-valid Vietnamese template story; offline demo and tests |
| TTS | Gemini TTS | `tts/gemini.py` | 30 prebuilt voices, multi-speaker conversation requests, direction prefix, free-tier quota fail-fast |
| TTS | ElevenLabs | `tts/elevenlabs.py` | `eleven_v3` + v2/flash, any account voice (cloned included), alignment, tier-gated format fallback |
| TTS | **WaveSpeed** | `tts/wavespeed.py` | `POST /api/v3/<model path>` → poll `/predictions/{id}/result` → download; `elevenlabs/eleven-v3` (any ElevenLabs voice id), `minimax/speech-2.6-hd` (system or cloned ids, emotion/speed/pitch/volume). Submissions are never blindly retried (a lost response may still be billed); `google/gemini-3.8-flash[-lite]/text-to-speech` (the actor's Gemini voice name, `style_instructions`, two-speaker dialogue as `speakers` + `turns`; billed per request per started 1,000 characters, hence scene batching) |
| TTS | mock | `tts/mock.py` | tones at the canonical stem format; fault injection (`clip`, `truncate`, `silence`, `error`) for the QA loop |

`LlmClient.chat(...)` is the second entry point: one model turn of a tool loop (text, tool calls, or both), on Gemini
function calling, Chat Completions function calling (WaveSpeed / OpenAI) and the Claude Messages API. A Gemini model
turn is sent back exactly as received, because Gemini checks the thought signatures of its own function calls. The mock
plays a scripted list of turns, or a small fixed policy per agent, so the loop and the chat run offline.

Every call goes through `LlmClient.structured(...)`, `LlmClient.chat(...)` or a `TtsProvider.synthesize(...)`, which is where validation,
retries and telemetry live. A new engine (for example a self-hosted model serving the team's cloned voices) is one class
with `synthesize(req, out)` plus `register_provider("name", factory)` and a catalog entry; the Director needs no change
because delivery is compiled per engine.

---

## 6. Agent runtime and tools (`emvoox/runtime/`, `emvoox/tools/`)

- **One loop for every agent** (`runtime/loop.py`): build context → call the model → permission gate → run tools →
  repeat until the model answers without a tool call. It runs on an `AgentSession`, a document saved after every turn,
  so it can stop wherever a person is needed and continue in another process.
- **An agent is configuration** (`runtime/agents.py`, `AgentSpec`): prompt, tool areas, core tools, model, step limit,
  budget. Today: `market_research` (loop mode) and `producer` (the chat). `register_agent` adds one.
- **A tool is a function** with a Pydantic arguments model, an `area` and a `kind`, registered with `@tool`
  (`tools/base.py`). 14 tools ship: core (`load_tools`, `ask_user`, `spawn_subagent`), research (4), library (5, read
  only), production (`production_start`, `production_continue`). `GET /api/agents` lists them with their schemas.
- **The permission gate** (`runtime/permissions.py`), per call, in order: the tool must be loaded for this agent; the
  arguments must validate (the error goes back to the model); `external` tools always wait for a person and `write`
  tools wait in manual mode; a session that has read outside text (itself or through a specialist) may no longer load
  tool areas; a session nobody is following cannot wait, so a call that needs a person is refused.
- **Limits**, checked before every model call: the step limit, the agent's budget (model calls plus what its tools
  spent), a cancel request. A session that hits one ends as `stopped` with the reason.
- **Outside text is data.** A page's text reaches the model only inside a tool result, as an excerpt with a note; the
  full text stays in the scan's observations. In the live check (four runs, two models) neither model followed an
  instruction planted in a page; the structural rules above hold even if one does.
- **Production from an agent.** `production_start` saves a run and enqueues it; it does not wait. The run pauses for
  its own decisions, which only a person answers.
- Tool calls are in the ledger (`skill: tool:<name>`) next to the model calls that asked for them.

### 6.1 Chat (`emvoox/services/chat.py`)

A thread is one conversation with the Producer. A message or an answer enqueues a `chat` job; a worker advances the
Producer's session until it has answered or needs the person. The Producer hands research to the Market Research agent
(`spawn_subagent`), asks which of the three genres to produce (`ask_user`), and starts production
(`production_start`, which needs approval). The thread view carries the conversation, the open questions and
approvals, and the runs the thread started with their own open decisions and parked episodes, so every decision can be
taken in the chat. Typing a reply while the agent waits answers its question, and declines an approval. The reply
arrives per model turn, not per token.

---

## 7. Voice IPs and cloned voices

- The registry (`data/assets/voice_registry.json`, model `VoiceRegistry`) holds actors (`CharacterProfile`: persona,
  voice description, gender, age, tags) and one `ProviderVoice` per engine (`voice_id`, `model_id`, `source`, `label`,
  `fallback_voice_id`, `default_settings`, `added_at`) plus `preferred_provider`.
- **Lock rule** (only in `VoiceRegistryRepository`): changing or removing an IP asset's existing voice needs `unlock`
  and is written to the changelog; adding a voice on a new engine does not.
- **Plugging in a cloned voice** (web: Voice IPs → "Plug in cloned voice"; CLI: `python -m emvoox plug-voice`; API:
  `POST /api/characters/{id}/voices`): stores it with `source: cloned` and, by default, makes that engine the actor's
  preferred one. The next run's Engine Policy renders the actor on that voice whenever the engine's key is configured.
  ElevenLabs PVC/IVC voice ids work directly and through WaveSpeed's ElevenLabs endpoint; MiniMax clones (WaveSpeed
  `minimax/voice-clone`) work through `minimax/speech-2.6-hd`.

---

## 8. Cost and audit telemetry (`emvoox/telemetry/`)

- `UsageRecord` per LLM call (tokens in/out), TTS request (characters, audio ms, tokens for Gemini), SFX, and agent step
  (execution time), stamped with run, series, episode, agent and skill, plus an **estimated cost** from
  `telemetry/pricing.py` (list prices from `docs/Cost_and_Pricing_Research.md`; override in `data/assets/pricing.json`).
- Written to `series/<id>/run.log.jsonl` (or `telemetry/run_log.jsonl`); pre-refactor rows are normalized and priced.
- `GET /api/costs`: totals (all time, month, today), by provider, model, agent, series (cost per audio minute), by day,
  recent records, the pricing basis, and the WaveSpeed balance. `GET /api/usage`: per-model quota status (Gemini daily
  free-tier quota with reset countdown, ElevenLabs subscription counters, vendor 429/402 events).

---

## 9. Web app and API

`web/` is a Next.js 16 static export with Ant Design 6 (navy `#284979`, light and dark themes), served by the API at
`/` (`python -m emvoox serve`, port 8765) or run with `npm run dev`. Pages: **Producer chat** (the home screen: one
message starts the work; question, approval, scene, budget and episode cards appear in the conversation),
**Dashboard** (`/dashboard/`: KPIs, productions in
progress, attention queue, cost trend), **Productions** (library, episode players, episode drawer with script, directed
units, QA report and release), **New production** (wizard: source = trend brief / own story / research now → story and
roles → engines and QA policy → review), **Pipeline** (agent flow, episode × step matrix, the scenes of each episode, a paused run's decisions, live
logs, casting, event timeline), **Approvals** (paused runs: scene and budget decisions; and the human gate: listen,
timestamped QA issues, edit metadata, approve / reject, exported files), **Voice IPs** (actors, previews per engine, cloned-voice plug-in), **Market research**
(scan, briefs, ranked candidates), **Costs** (spend and quotas), **Settings** (health checks, keys, agent fleet).

The full route list is at the top of `emvoox/api/app.py`; `web/lib/api.ts` is the typed contract both sides follow.

---

## 10. Configuration

All settings come from `emvoox/config.py::get_settings()` (`.env`, `EMVOOX_*`, legacy `AI_AUDIO_*` still read). The
important ones: `EMVOOX_LLM_PROVIDER/MODEL`, `EMVOOX_TTS_PROVIDER/MODEL/BATCHING`, `EMVOOX_PREFER_CLONED_VOICES`,
`EMVOOX_STORAGE` (`local | postgres`), `EMVOOX_DATA_DIR`, `EMVOOX_DOC_STORE`, `EMVOOX_DATABASE_URL`, `EMVOOX_TENANT`,
`EMVOOX_QUEUE` (`memory | redis`), `EMVOOX_REDIS_URL`, `EMVOOX_EMBEDDED_WORKER`, `ENABLE_BGM`, `ENABLE_SFX`, loudness and padding,
`EMVOOX_QA_MAX_RETRIES`, `EMVOOX_QA_PASS_SCORE`, `EMVOOX_QA_TRANSCRIBE`, `EMVOOX_CLIFFHANGER_*`, `EMVOOX_AUTO_APPROVE`,
`EMVOOX_HALT_ON_QA_FAIL`, `EMVOOX_RESEARCH_USE_BROWSER`. See `.env.example`; keys and accounts in `docs/SETUP.md`.

---

## 11. Testing and the demo

- `python scripts/demo_pipeline.py` runs research → master → gate → approval offline with an injected fault, prints
  every step, the QA retry and the telemetry. `--live --llm wavespeed --tts wavespeed --episodes 1` runs the same on real vendors.
- `pytest` (160 tests, no outside network: sockets are blocked except localhost and `.env` is not loaded under test).
  Tests that need PostgreSQL (`createdb emvoox_test`) or Redis (database 15) are skipped when the server is not
  there. Covered: the workflow graph (parallel scenes under the provider cap, per-scene retries, scene approval and
  rejection, the budget pause, pausing and resuming in new engines), durability (a run whose process was killed with
  SIGKILL is recovered without paying twice, Redis re-delivery, checkpoints in PostgreSQL, tenant isolation), the
  runtime (gate, limits, tool loading, the taint rule, adapters' tool calling), the research loop, and the chat from one
  message to a mastered episode. Also: contracts, normalizer,
  delivery compile and render plan, provider adapters on fake transports (Gemini, ElevenLabs, WaveSpeed TTS + LLM),
  repositories (JSON and SQLite against one contract), agents (casting policy with cloned voices, QA measurements on
  synthetic audio, mastering with a ducked bed), the engine end to end (retry loop, halting, auto-approve, contract
  rejection, rule-based fallback, research-to-master, resume), and the HTTP API.

---

## 12. Decisions

Decisions F1-F12 of the agentic platform are in `docs/TARGET_ARCHITECTURE.md`; F1-F6 and F9 are built. Locked decisions
D1-D11 (CLAUDE.md) hold; D12 (one series at a time, episodes sequential) is replaced: scenes run in parallel under a
per-provider cap and runs queue. The refactor decisions below hold except E1. New decisions taken in this
refactor, each with the reason; numbered so the Lead Architect can confirm or override them one by one:

| # | Decision | Why |
|---|---|---|
| E1 | Orchestration is a native asyncio state machine with Pydantic contracts, not LangGraph or CrewAI | the flow is a fixed graph with one loop; a framework adds dependencies (and Python 3.14 risk) without adding control; every step stays a plain, testable function. **Superseded by F1 (2026-10-13):** production runs scenes in parallel with their own QA and approval loops, on LangGraph; the native engine was deleted in Phase 1. Agents are still plain, testable functions |
| E2 | Storage behind `DocumentStore` + `BlobStore` with keys = relative paths; JSON files by default, SQLite optional | local-first now, one adapter pair to reach v1ron_db + MinIO later |
| E3 | Audio processing stays FFmpeg via subprocess (`audio/`), no pydub | two-pass loudnorm hits -16.0 LUFS exactly; pydub was dropped earlier for that reason |
| E4 | LLM abstraction is a thin adapter layer (Gemini SDK, OpenAI-compatible HTTP for WaveSpeed/OpenAI, Anthropic SDK), not LiteLLM/LangChain | structured output per vendor is the hard part and each adapter does it natively; WaveSpeed already aggregates models behind one protocol |
| E5 | Casting moves out of the outline call into its own agent; roles leave the Script Writer uncast | matches the technical map; lets cloned-voice preference and engine policy decide per actor |
| E6 | The QA loop re-plans and re-renders only flagged units, at most `max_retries` (3), with progressively more stable engine settings; then a human decides | bounded cost, deterministic, auditable (each attempt is in the stem sidecar and the cache key) |
| E7 | Nothing is published without a human; FLAGGED episodes halt the run by default | capital efficiency: stop spending before someone listens |
| E8 | The Director falls back to rule-based direction after two rejected LLM answers | a malformed answer should cost a note, not a stalled batch |
| E9 | Gemini remains the default engine; ElevenLabs and WaveSpeed are per-run or per-actor choices; a cloned voice wins whenever its engine has a key | testing stays cheap; IP voices are used as soon as they exist |
| E10 | The Market Research browser scan is optional and selector-free | public pages change and block bots; local trend notes are the supported path until V1RON's automation fleet |

## 13. Not built yet (roadmap)

Phases 0-4 of `docs/MIGRATION_PLAN.md` are done. Next: (5) long-term memory and compaction, (6) users, roles,
per-tenant keys and budgets, metering. Open from the phases done: token streaming in the chat, `MinioBlobStore`, a
real search source for Google (O5), per-request tenants.

1. **V1RON OS**: still unplanned: the V1RON API provider for LLM/TTS (register as a provider) and the V1RON browser
   automation fleet behind Market Scan.
2. **Publishing** (after Phase 6): the YouTube upload (OAuth) behind the existing `ReleasePackage`; retention analytics feeding the
   Market Research Agent.
3. **Director v2** (from the former Technical Specification): engine-neutral delivery cues, ElevenLabs Text-to-Dialogue
   conversation units with per-line segments, an identity-anchored modulation model per cloned voice, an LLM delivery
   judge for peak lines.
4. **Video pipeline** (Visual Development, Storyboard, Video Director, Editor, QA Video; see the video map in
   `docs/Emvox_Technical_Map.md`) for series that prove themselves in audio. The Dashboard already reserves a Video view.
