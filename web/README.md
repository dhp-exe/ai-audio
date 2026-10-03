# Emvoox Studio (web client)

Next.js 16 (App Router, static export) + Ant Design 6 client for the Emvoox engine API (`emvoox/api/app.py`).
Pages: Dashboard, Productions (+ detail), New production, Pipeline, Approvals, Voice IPs, Market research, Costs, Settings.
`lib/api.ts` is the contract with the backend; light/dark/system theme via antd ConfigProvider.

```bash
npm install
npm run dev        # http://localhost:3000, proxies /api/* to API_BASE (default http://127.0.0.1:8765)
                   # the Network URL (this Mac's LAN IP) works too; add other hosts with DEV_ORIGINS=host1,host2
npm run typecheck
npm run export     # static build in out/, served by the engine at /
```

Deploying on Vercel: import the `web/` folder, set `API_BASE` to the public URL of the FastAPI backend.
The backend needs FFmpeg and a disk, so it runs on a container host (Fly.io, Railway, Render), not on Vercel.

## Hosting the whole thing

| piece | needs | fits |
|---|---|---|
| `web/` (this app) | static or Node hosting | **Vercel** (import the `web/` folder, set `API_BASE`), or served by the engine at `/` |
| `emvoox/` engine + API (FastAPI, FFmpeg, disk) | a long-running container with FFmpeg and a persistent volume | V1RON OS agent runtime when available; until then a container host or one studio machine |
| documents (story, bible, cast, runs, QA, ledger) | `DocumentStore` | JSON files or SQLite today; **v1ron_db** (PostgreSQL) via `EMVOOX_STORAGE=v1ron` |
| audio (stems, masters, previews, approved exports) | `BlobStore` | `./data` today; **V1RON Media (MinIO)** via `EMVOOX_STORAGE=v1ron` |

Everything lives under `./data` behind the repository layer (`emvoox/repositories/`); moving to V1RON OS means
implementing the two storage adapters in `emvoox/repositories/v1ron.py`. The API routes and this app do not change.
See `docs/ARCHITECTURE.md` §4.
