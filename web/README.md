# Audio AI Studio (web client)

Next.js app for the pipeline. Pages: Library, New/Edit story, Run board, Characters, Usage.

```bash
npm install
npm run dev        # http://localhost:3000, proxies /api/* to API_BASE (default http://127.0.0.1:8765)
npm run export     # static build in out/, served by `python -m pipeline.webui` at http://127.0.0.1:8765
```

Deploying on Vercel: import the `web/` folder, set `API_BASE` to the public URL of the FastAPI backend.
The backend needs FFmpeg and a disk, so it runs on a container host (Fly.io, Railway, Render), not on Vercel.

## Hosting the whole thing

| piece | needs | fits |
|---|---|---|
| `web/` (this app) | static or Node hosting | **Vercel** (import the `web/` folder, set `API_BASE`) |
| `pipeline/` backend (FastAPI, FFmpeg, subprocesses, disk) | a long-running container with FFmpeg and a persistent volume | **Fly.io** or **Railway** (Dockerfile with `ffmpeg`), or a small VPS |
| series files, stems, masters, previews | object storage once the backend is not on one machine | **Cloudflare R2** (no egress fees for audio) or S3 |
| runs, stories, registry, usage ledger | a database once several people share one studio | **Postgres on Supabase** (also gives auth and a storage bucket if you prefer one vendor) |

Today everything is files under `series/` and `library/` and the API reads them directly, which is right for one
operator. Move to Supabase Postgres + R2 when you add logins or a second machine; the FastAPI routes stay the same,
only `pipeline/stories.py`, `pipeline/registry.py` and `pipeline/usage.py` change their storage.
