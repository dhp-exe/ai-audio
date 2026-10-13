# Emvoox Engine: migration plan to the agentic platform

| | |
|---|---|
| Status | **Phases 0-4 done (2026-10-13).** Phase 5 (memory and compaction) is next. Each phase below ends with a "Result" section: what was built, the evidence, and what was left out |
| Date | 2026-10-12, updated 2026-10-13 |
| Target | `docs/TARGET_ARCHITECTURE.md` (decisions F1-F12, open items O1-O6) |
| Today | `docs/ARCHITECTURE.md` |

## Ground rules for every phase

1. **The product keeps working.** After each phase the CLI, the API and the web app still produce an episode end to end.
2. **Offline tests stay green.** `pytest` runs with sockets blocked; every new capability gets a mock path (F12).
3. **Agents stay plain functions.** A phase may change who calls an agent, never make an agent import a framework.
4. **Contracts first.** A new handoff, tool or event starts as a Pydantic model in `emvoox/contracts/`.
5. **One phase, one switch.** New behaviour ships behind a setting until its exit criteria pass, then becomes default
   and the old path is deleted in the same phase.

Sizes are relative (S < M < L < XL), not calendar estimates.

## Overview

| Phase | Outcome | Size | Depends on |
|---|---|---|---|
| 0 | LangGraph trial: go or no-go on F1. **Done: go** | S | none |
| 1 | Scene-level production on the workflow graph. **Done** | L | 0 |
| 2 | Durable runs: worker, queue, checkpoints, PostgreSQL storage, tenant in every key. **Done** (MinIO left out) | XL | 1 |
| 3 | Tool calling, tool registry, agent runtime; Market Research as the first loop agent. **Done** (O5 still open) | L | 2 (can start after 0 in parallel with 1) |
| 4 | AI-first chat: Producer agent, pauses as chat cards. **Done** (no token streaming) | L | 2, 3 |
| 5 | Long-term memory and compaction | M | 3, 4 |
| 6 | SaaS: users, roles, per-tenant keys, budgets, metering, developer docs | L | 2, 3 |
| Later | Publishing and retention feedback; video pipeline | | 6 |

---

## Phase 0: LangGraph trial

**Goal.** Decide F1 with evidence before any migration.

**Work**
- Add `langgraph` as an optional extra (`.[workflow]`).
- New `emvoox/workflow/episode_graph.py`: the current episode flow (draft → direct → voice → master → QA → retry →
  gate) as a graph whose nodes call the existing agent methods. Scenes fan out in the voice/QA part.
- `Engine` gets a setting (`EMVOOX_ORCHESTRATOR=native|graph`) that swaps `_episode` for the graph. Nothing else changes.
- A per-provider concurrency limiter shared by parallel branches.
- Map graph progress onto the existing `PipelineEvent`s and `StepState`s.

**Exit criteria (all four, on the mock providers)**
1. Installs and runs on the project's Python (3.14 in the current venv).
2. Scenes of one episode run in parallel and never exceed the per-provider limit.
3. Two scenes pause for approval at the same time and resume independently, from a checkpoint, after a process restart.
4. The ledger and the event log contain every call and transition the native engine records for the same run.

**Decision.** All four pass → F1 adopted, E1 marked superseded. Any fails → keep E1; Phase 1 builds the same
scene-level flow natively and the rest of the plan is unchanged.

**Risks.** Framework and Python-version incompatibility; resume semantics (a paused node re-runs from its start).

### Result (2026-10-13): passed, F1 adopted

Built: `emvoox/workflow/episode_graph.py` (episode graph with a scene subgraph), `emvoox/workflow/limits.py`
(`ProviderLimiter`), the `EMVOOX_ORCHESTRATOR=native|graph` setting, the `.[workflow]` extra. Evidence, all on the mock
providers (`tests/test_workflow_graph.py`; no live vendor run was made):

| Check | Result |
|---|---|
| 1. Runs on the project's Python | LangGraph 1.2.14 on Python 3.14.0. All of `tests/test_engine.py` now runs once per orchestrator and passes on both |
| 2. Parallel scenes under the limit | Two scenes render at once; vendor requests peak at the provider's cap (2), and at 1 with a tighter cap |
| 3. Two scenes pause and resume independently after a restart | Passed with new engine objects and a SQLite checkpoint file, and once by hand across three separate OS processes. No scene was rendered again |
| 4. Same ledger and events as the native engine | For a run with one QA retry: identical ledger rows, event sequence, step states and totals |

What the trial taught us (carry into the next phases):
- **Nothing with a side effect may sit before `interrupt` in the same node.** When one of two paused scenes is resumed,
  the other's paused node runs again from its start. The graph therefore announces a wait in its own node.
- **The cap must be on vendor requests, not on scenes.** Each scene opens its own thread pool, so the limiter sits
  around `synthesize` (`AgentContext.slot`), shared by all branches.
- **State is JSON dumps of contracts**, re-validated in every node, so a checkpoint is readable by a new process.
- **Only the graph's own state survives a restart.** `RunState` (the run board), the step's elapsed time and cost are
  rebuilt empty in the resuming process. Making them durable is Phase 2.
- **Not covered by the trial:** per-scene QA retry loops (the retry re-renders flagged units in one step, as natively),
  retry of a failed scene branch, live vendors, and the PostgreSQL checkpointer.
- **Dependency footprint:** `langgraph` pulls in `langchain-core`, `langgraph-checkpoint`, `langgraph-prebuilt`,
  `langgraph-sdk`, `ormsgpack`. We use only the graph and checkpoint packages; no LangChain model classes (F4).

The native engine stays the default until Phase 1 reaches parity at scene level and deletes it.

---

## Phase 1: scene-level production on the workflow graph

**Goal.** Production matches the real process: scenes in parallel, each with its own QA loop and approval, episode
mastering as the join (F5).

**Work**
- Contracts: `SceneRender`, `SceneQAReport`, `SceneApproval`; `QAReport` becomes the episode-level roll-up. Stem
  names and `paths.py` keys for scene artifacts.
- QA Critic: stem checks run per scene; master checks (loudness, true peak, duration) run once after the join.
- Director: `replan` scoped to one scene. Sound Engineer: `generate_voice` scoped to one scene; `assemble_audio` stays
  per episode.
- `emvoox/workflow/`: `series_graph.py`, `episode_graph.py` (exists from Phase 0), `scene_graph.py`; the engine runs them. Delete the
  hand-written `_episode` and `_series` once parity is reached.
- Per-run budget cap (`RunParams.max_cost_usd`): checked before every paid node; over the cap pauses the run.
- Research scans started from the API go through the same run path as everything else (one run mechanism).
- Web: Pipeline page shows scenes; Approvals page approves or rejects a scene.
- Update `scripts/demo_pipeline.py` and the `emvoox-pipeline` skill.

**Exit criteria**
- The offline demo produces an episode with parallel scenes, an injected fault in one scene, a retry in that scene
  only, and a PASS after the join.
- Existing engine tests pass or are replaced one for one; new tests cover partial failure, the join and the budget cap.
- A live single-episode run on the current keys stays within vendor rate limits.

**Risks.** Scene-level QA changes scoring; mastering quality at scene boundaries; rate limits on the free tiers.

### Result (2026-10-13): done

Built: `workflow/scene_graph.py`, `episode_graph.py`, `series_graph.py`, `checkpoints.py`; the native `_episode` /
`_series` and the `EMVOOX_ORCHESTRATOR` switch are deleted, LangGraph is a core dependency. `SceneQAReport`,
`SceneApproval`, `SceneRun`, `PendingDecision`; `QACriticAgent.review_scene` and the episode roll-up;
`RunParams.scene_approval` and `max_cost_usd`; `Engine.run(resume=...)` and `Engine.restore`; `GET /api/decisions`,
`POST /api/runs/{id}/decisions`, a stem endpoint for listening to a scene; `emvoox decide`; scenes on the Pipeline page,
decision cards on the Approvals page, scene approval and budget in the New production form.

Evidence (`tests/test_engine.py`, `tests/test_workflow_graph.py`, `tests/test_api.py`): two faults in two scenes are
retried by their own scenes and the episode is mastered once; a scene that stays broken does not re-render the other;
two scenes wait and are resumed independently by engines rebuilt from storage; a rejected scene re-renders only the
named unit and asks again; the budget pauses the run before an episode and halts it when declined; the offline demo
shows a per-scene retry.

Changed from the plan:
- **The episode gate stays non-blocking** (decided 2026-10-13): a PASS episode is parked and the run continues; only a
  FLAGGED episode halts. `approve` / `reject` remain separate actions.
- **A scene's stems are named by render unit**, not by new scene artifacts; the only new key is `qa/epNN_scNN.json`.
- **The budget is checked before each episode**, not before every paid node: scene retries are bounded already.
- Running research scans through the run path moved to Phase 2, where the queue exists (done there).
- Not done: a live single-episode run on real vendors.

---

## Phase 2: durable runs, V1RON storage, tenants

**Goal.** A run survives restarts and can wait days for a person (F6); data is tenant-scoped from here on (F10).

**Work**
- O2 is decided: PostgreSQL and Redis locally. Implement `PostgresDocumentStore` and `MinioBlobStore` (`repositories/v1ron.py`, today stubs) and pass the
  existing repository contract test against them.
- Tenant id in every key: `paths.py` takes a tenant; repositories refuse a key without one. A migration script moves
  `./data` into a default tenant.
- Queue and worker: `python -m emvoox worker`; the API enqueues instead of starting a thread. Leases and heartbeats so
  a dead worker's run is picked up again.
- Checkpoints stored in the database (the graph's checkpointer, or our own table if Phase 0 failed).
- Pause and resume API: a run in `waiting` has a list of pending decisions; `POST` of a decision re-queues it. The
  approve/reject endpoints become decisions on a paused run.
- Review every node for repeat-safety (resume re-runs the paused node).
- Docker Compose gains the database, the queue and a worker service.

**Exit criteria**
- Kill the worker mid-episode: the run resumes and finishes with no duplicated vendor spend (ledger proves it).
- A run paused at a scene approval resumes correctly after a restart of every process.
- Two tenants cannot read each other's series, registry or runs (tests on the repository layer).
- The contract test passes on JSON, SQLite, PostgreSQL and MinIO.

**Risks.** Data migration of live `./data`; blob latency for FFmpeg (local cache path already in the `BlobStore` contract).

### Result (2026-10-13): done, without MinIO

Decided 2026-10-13: PostgreSQL and Redis locally; media files stay on local disk for now; the live `./data` is not
moved, it is the `default` tenant as it stands.

Built: `repositories/postgres.py` (`EMVOOX_STORAGE=postgres`: documents, run state, logs, and the graph's checkpoints
through `langgraph-checkpoint-postgres`), `repositories/tenancy.py` (tenant-scoped stores; `get_repositories(tenant)`),
`emvoox/worker/` (`MemoryQueue`, `RedisQueue` with leases and re-delivery, `Worker`, `python -m emvoox worker`),
`Engine.create` and the start / resume / recover modes, forced renders made repeat-safe, the API moved onto the queue
(no engine lives in the API; `recover_interrupted_runs` at startup), market scans as jobs,
`docker-compose.durable.yml`, a queue check in `doctor`. Extra `.[durable]`.

Evidence (`tests/test_worker.py`, `tests/test_repositories.py`, run against the local PostgreSQL 18 and Redis 8):
- A run whose process was killed with SIGKILL as mastering started is recovered by a worker and finishes; every unit
  has exactly one TTS row in the ledger, even with `force`.
- With Redis, a job held by a dead worker comes back when its lease expires and a second worker finishes the run.
- With PostgreSQL, a run paused at scene approvals is resumed after the pools are rebuilt; its checkpoint rows are
  deleted when it finishes.
- Two tenants cannot see each other's series, registry, runs, logs or blobs on JSON, SQLite and PostgreSQL; the
  default tenant cannot address `tenants/`.
- One manual check with a real separate `emvoox worker` process, PostgreSQL and Redis: start → wait → decide → finish.

Changed from the plan, and left out:
- **The queue is our own small implementation** behind a `JobQueue` protocol, not RQ: leases, re-delivery, a per-run
  lock and a cancel signal are the whole requirement, and RQ's fork-per-job and failure registries fit it badly.
- **A tenant is chosen per process** (`EMVOOX_TENANT`), not per request; that needs users and roles (Phase 6).
- **`MinioBlobStore` is not built**; `EMVOOX_STORAGE=v1ron` still raises.
- **A recovered LLM step is paid for again** (draft, direct, script); only audio is protected by a cache.
- **`docker-compose.durable.yml` was written but not run**: Docker was not available on this machine.
- No tool copies an existing JSON data directory into PostgreSQL.

---

## Phase 3: tool calling, tool registry, agent runtime

**Goal.** A model can decide what to do next, inside limits (F2, F3, F4). Market Research is the first loop agent.

**Work**
- `LlmClient.chat(messages, tools) -> reply | tool calls` on each adapter (Gemini, OpenAI-compatible, Claude). The mock
  provider plays scripted tool-call sequences. Tool calls go to the ledger.
- `emvoox/tools/`: `registry.py` (register, list by area, load on demand), `base.py` (`ToolContext`, kinds), one
  module per area. Wrap existing skills: research (`search_plan`, `open_page`, `analyze`, `save_brief`), story, casting,
  registry reads, `produce_episode` (runs the workflow graph, kind `external`).
- `emvoox/runtime/`: `loop.py` (context → model → gate → tools), `permissions.py` (role, argument validation, approval
  by kind), `budget.py` (per-run and per-turn limits, max steps).
- Agent definitions as configuration (prompt, tool areas, model, budget) next to each agent.
- Market Research as a loop: search, read, decide whether to search again, then rank. Scraped text is wrapped as data
  and never treated as instructions (F11). Decide O5 (Google source) and O6 (model for loop agents) with measurements.
- `GET /api/agents` lists tools per agent.

**Exit criteria**
- Offline: a scripted loop run of Market Research produces a valid `TrendBrief`; a tool call with invalid arguments is
  rejected and reported back to the model; a run stops at its budget and at its step limit.
- A `write` tool pauses for approval in manual mode; an `external` tool always pauses.
- A page containing "ignore your instructions"-style text does not change which tools are called (test fixture).
- Live: one research run answers a guide the fixed scan could not, within its budget.

**Risks.** Weak models misuse tools; cost per research run rises; prompt injection through scraped pages.

### Result (2026-10-13): done; the Google source (O5) is still open

Built: `LlmClient.chat` and `chat()` on the Gemini, OpenAI-compatible and Claude adapters; `contracts/agentic.py`;
`emvoox/tools/` (registry, `@tool`, 14 tools); `emvoox/runtime/` (`loop.py`, `permissions.py`, `agents.py`); the mock's
scripted turns and per-agent policies; Market Research in loop mode (`services/research.run_agent_scan`,
`research --agent`, `agent: true` on a scan, a switch on the Market research page); `GET /api/agents` lists runtime
agents and tools; tool calls in the ledger.

Evidence (`tests/test_runtime.py`): invalid arguments, unknown tools and broken tools are reported to the model and
nothing runs; an `external` tool waits and runs only when approved; `write` tools wait only in manual mode; a task
nobody follows cannot wait; the step limit and the budget stop a task; after reading outside text a session cannot
load tool areas; the research loop reads, searches and writes a brief, reports blocks, refuses URLs, and ends without
a brief when nothing was read.

Live check (WaveSpeed LLM only, 5.7 cents in total; the browser replaced by fixed pages, one carrying an injected
instruction; two runs per model):

| Model | Finished with a brief | Model turns | Invalid calls | Followed the injection | Cost per run |
|---|---|---|---|---|---|
| `google/gemini-3.1-flash-lite` | 2 of 2 | 6 | 0 | 0 of 2 | about $0.0025 |
| `google/gemini-3.6-flash` | 2 of 2 | 7 | 0 | 0 of 2 | about $0.026 |

- **O6:** the default `gemini-3.1-flash-lite` drove this loop correctly, which was not what we expected; it stays the
  default and an agent can name its own model (`AgentSpec.model`). Four runs on one task is a small sample.
- **O5 is still open.** The WaveSpeed gateway accepts a search parameter and ignores it: the answers had no sources and
  invented titles. Searching Google needs a Gemini API key (grounding) or a search API key; neither is in `.env`.
- One gateway call took about ten minutes (180 s timeout, three retries). Chat turns inherit that worst case.

Changed from the plan: story and casting were not wrapped as separate tools (they run inside the series graph, which
`production_start` starts). The Claude adapter's `chat` is untested: the SDK is not installed here. No real-browser
research run was made in loop mode.

---

## Phase 4: AI-first chat

**Goal.** The user states an idea; agents do the rest and stop for decisions (F9).

**Work**
- Contracts and storage for threads and messages (per tenant, per user).
- API: create thread, post message, stream events (server-sent events), list and answer pending decisions.
- Producer agent: owns the thread, delegates with `spawn_subagent`, asks with `ask_user` (O3 decided: one Producer, no direct chat with each agent).
- Web: chat page as the home screen. Decision cards for pause points (pick a genre, approve cast, approve spend,
  approve scene, approve episode) with the audio player and QA issues inline. Existing pages stay and are linked from
  the chat.
- Token streaming from the adapters to the UI.

**Exit criteria**
- From one message ("make a 10-episode rebirth series for women 25-34") the system reaches a mastered first episode,
  stopping only at the planned pause points; offline with the mock providers and live on the current keys.
- Closing the browser and returning later shows the same thread and pending decisions.
- Every action available in the chat is also recorded in the audit log.

**Risks.** Scope creep in the UI; long runs need clear progress in the chat; streaming on the static export.

### Result (2026-10-13): done, without token streaming

Decided 2026-10-13 (O3): one Producer agent that delegates; no direct chat with each agent.

Built: `contracts/chat.py`, `services/chat.py`, the `producer` agent, the `production_start` / `production_continue`
tools, the chat API (threads, messages, answers, events, a server-sent-events stream), chat jobs in the worker, and
the chat page as the home screen (the dashboard moved to `/dashboard/`) with question, approval, scene, budget and
episode cards.

Evidence (`tests/test_chat.py`, on the mock providers): from one message the Producer hands research to the Market
Research agent, asks which of the three genres to produce, asks for approval to start, and the run reaches a mastered
episode that is approved from the conversation; the thread and what it waits for are the same after a restart; scene
decisions of a run started from the chat appear in it; declining the start spends nothing; every tool call and model
call is in the ledger. The flow was also walked through in a headless browser against a mock-provider server, with no
console errors.

Left out:
- **Token streaming.** A reply arrives per model turn. The adapters' `chat` is not streamed.
- **Not run live:** the chat has only been driven by the mock model. The Producer's prompt has not met a real model.
- A run does not post into its thread when it changes; the page polls the thread, which reads the run.
- One user: the reviewer's name is typed in the page. Users arrive with Phase 6.

---

## Phase 5: long-term memory and compaction

**Goal.** Agents remember what they learn about a tenant, and long conversations stay inside the context window
(F7, F8).

**Work**
- `emvoox/memory/`: store per tenant and agent; `remember`, `recall`, `forget` tools; provenance on every entry
  (thread, run, time). O4 decided: agents save automatically; a person reads, edits and deletes.
- Web: a memory page per agent where a person reads, edits and deletes entries.
- Compaction in the runtime: clear old tool results, summarise older turns (one model call, saved), drop oldest;
  thresholds as settings. Large tool results stored as blobs with an excerpt in the conversation.
- Context builder selects relevant memories, not all of them.

**Exit criteria**
- A fact learned in one thread is used in a new thread of the same tenant and never appears for another tenant.
- A scripted long conversation stays under the context limit and still answers a question about its first turns.
- Deleting a memory entry removes it from the next context.

**Risks.** Wrong memories persisting; memory used as a second copy of domain data (forbidden by F7).

---

## Phase 6: SaaS

**Goal.** Other studios can use the platform safely, and developers can extend it (F10).

**Work**
- Authentication, users, roles; runs execute as the signed-in user; the permission gate reads the role.
- Per-tenant provider keys, Voice IP registries, budgets, concurrency limits and rate limits.
- Metering per tenant (LLM tokens, TTS characters, exported minutes, storage) and an export for billing.
- Audit log: tool calls, approvals, writes; reviewable per tenant.
- Developer documentation: how to add a tool, an agent, and a workflow variant; a worked example of each.
- Tenant administration pages.

**Exit criteria**
- Two tenants run concurrently with separate keys, registries, budgets and memories; a cross-tenant request is refused
  at the API and at the repository layer.
- A developer adds a tool and an agent by following the documentation, without editing `emvoox/runtime/`.
- A tenant that reaches its budget is stopped; its usage report matches the ledger.

**Risks.** Security review of tenant isolation; key management; support load from custom workflows.

---

## Later
- **Publishing**: YouTube and TikTok upload as `external` tools behind the existing `ReleasePackage`; retention data as
  read tools and as a source for long-term memory.
- **Video pipeline** for series that prove themselves in audio (`docs/Emvox_Technical_Map.md`).

## Where new code goes

| Package | Phase | Purpose |
|---|---|---|
| `emvoox/workflow/` | 0-1 | Series, episode and scene graphs; provider concurrency limiter |
| `emvoox/worker/` | 2 | Queue consumer, leases, resume |
| `emvoox/tools/` | 3 | Registry and tool modules by area |
| `emvoox/runtime/` | 3, 5 | Agent loop, permission gate, budgets, compaction |
| `emvoox/memory/` | 5 | Long-term memory store and tools |
| `emvoox/tenancy/` | 2, 6 | Tenant, user and role models; auth |

`workflow`, `worker`, `tools` and `runtime` exist. `memory` and `tenancy` (users, roles) do not; tenant scoping itself lives in `repositories/tenancy.py`.
