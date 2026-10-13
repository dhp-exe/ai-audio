# Emvoox Studio

**Emvoox** (Emotion + Voice) is an AI entertainment studio: fixed Virtual Actors with their own voices perform
Vietnamese micro-dramas for the Mặc Khải channel. Audio is the cheap test funnel: one story becomes a series of short
audio episodes, retention data decides which series earn a video budget.

**Emvoox Engine** is the production system behind it. You describe an idea to the **Producer** in a chat; it researches
trends, asks you which genre to make, and starts production once you approve the spend. Production runs on a workflow
graph: seven agents with typed contracts, scenes produced in parallel with their own QA and retry loops, and a human
approval gate before anything is published. Runs are durable: they pause for your decisions and continue after a restart.

```
Market Research → Script Writer → Casting & Voice IP Curator → AI Director → Sound Engineer → QA Critic → Approval Gate & Publisher
   TrendBrief      StoryInput+Bible    ResolvedCast+EnginePolicy   DirectedConversationUnits   MasteredEpisode   QAReport (PASS/FLAGGED)   approved masters + YouTube metadata
```

## Quick start with Docker (recommended for teammates)

Only Docker Desktop (or Docker Engine with Compose v2.24+) is needed: Python, Node, FFmpeg and the headless browser are in the image.

```bash
git clone <this repo> && cd ai-audio
cp .env.example .env                 # add WAVESPEED_API_KEY, set EMVOOX_LLM_PROVIDER / EMVOOX_TTS_PROVIDER to wavespeed
docker compose up --build            # first build takes a few minutes; then open http://localhost:8765
```

```bash
docker compose run --rm emvoox python scripts/demo_pipeline.py     # the whole fleet offline: no key, no cost
docker compose run --rm emvoox python -m emvoox doctor --live      # keys, balance, FFmpeg, registry
docker compose up -d && docker compose logs -f                     # run in the background, follow the log
docker compose down                                                # stop (your data stays in ./data)
```

Everything the engine writes (Voice IP registry, research, series, masters, cost log) is in `./data` on your machine, so it
survives rebuilds. After pulling new code: `docker compose up --build`. Details: [docs/SETUP.md](docs/SETUP.md) §1.

### Durable setup (optional)

By default everything is local: files under `./data`, and runs queued inside the server. To keep run state and
checkpoints in PostgreSQL and jobs in Redis, with a separate worker:

```bash
docker compose -f docker-compose.yml -f docker-compose.durable.yml up --build      # not yet tried on a real Docker host
```

or, without Docker: `pip install -e ".[durable]"`, `createdb emvoox`, set `EMVOOX_STORAGE=postgres`,
`EMVOOX_DATABASE_URL`, `EMVOOX_QUEUE=redis` in `.env`, then `python -m emvoox serve` and `python -m emvoox worker`.
Details: [docs/SETUP.md](docs/SETUP.md).

## Quick start without Docker

```bash
python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"   # Python 3.11+, FFmpeg on PATH
cd web && npm install && npm run export && cd ..                                # build the web app once
cp .env.example .env                                                            # keys: docs/SETUP.md

python scripts/demo_pipeline.py --keep ./demo-data      # the whole fleet offline: no key, no cost
python -m emvoox serve                                  # Emvoox Studio at http://127.0.0.1:8765 (the Producer chat is the home page)
python -m emvoox doctor --live                          # keys and vendors
python -m emvoox run --series s1 --story story.txt --episodes 30 --produce 3 --tts gemini
```

| Need | Where |
|---|---|
| How it works today (agents, contracts, engine, storage, providers, decisions) | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Where it is going (memory, users and roles, metering: not built yet) | [docs/TARGET_ARCHITECTURE.md](docs/TARGET_ARCHITECTURE.md) |
| What each migration phase built, with evidence and what it left out | [docs/MIGRATION_PLAN.md](docs/MIGRATION_PLAN.md) |
| Keys, accounts, and when to plug in the WaveSpeed key | [docs/SETUP.md](docs/SETUP.md) |
| Vendor pricing research | [docs/Cost_and_Pricing_Research.md](docs/Cost_and_Pricing_Research.md) ([tiếng Việt](docs/Cost_and_Pricing_Research.vi.md)) |
| Technical map (audio and video pipelines) | [docs/Emvox_Technical_Map.md](docs/Emvox_Technical_Map.md) |
| Working conventions for this repo | [CLAUDE.md](CLAUDE.md) |
| Web client | [web/README.md](web/README.md) |

## Repository

```
emvoox/            the engine (contracts, agents, workflow graph, engine, worker, runtime, tools, repositories, providers,
                   delivery, audio, telemetry, services, api, cli)
web/               Emvoox Studio: Next.js 16 + Ant Design 6 (static export served by the API)
data/              local storage: assets (Voice IP registry, previews), inputs, research, series, outputs, telemetry
scripts/           demo_pipeline.py
tests/             pytest, offline (network blocked)
docs/              architecture, setup, pricing research, technical map
emvox.docs/        brand and project source documents
.claude/skills/    emvoox-pipeline, voice-ip-registry, market-research
```
