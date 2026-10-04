# Setup: install, keys, and the first real run

Prices and free tiers change; figures are from the vendors' public pages (September-October 2026). Re-check before
budgeting. Cost estimates in the app come from `emvoox/telemetry/pricing.py` and can be overridden in
`data/assets/pricing.json`.

## 1. Install

### Option A: Docker (no local toolchain)

```bash
cp .env.example .env                 # then fill in the keys you use (§4)
docker compose up --build            # http://localhost:8765
```

- The image contains Python 3.12, FFmpeg, the built web client and headless Chromium for the market research scan.
- `./data` is mounted into the container: the Voice IP registry from the repository is used, and everything produced
  stays on your machine. `EMVOOX_DATA_DIR` in `.env` is ignored inside the container.
- `.env` is read when the container starts and is never copied into the image. After changing it:
  `docker compose up -d` (recreates the container).
- The port is published on `127.0.0.1` only, because the app has no login. Another port: `EMVOOX_PORT=9000 docker compose up`.
- Any CLI command runs in the same image: `docker compose run --rm emvoox python -m emvoox <command>` (for example
  `doctor --live`, `voices`, `research --browser`, `run --series s1 --story /app/data/inputs/story.txt ...`; put input
  files under `./data/inputs/` so the container can read them).
- On Linux the container runs as uid 1000; if your user has another uid, `sudo chown -R 1000:1000 data` once.

### Option B: on the machine

```bash
python3.11+ -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"                      # + ".[research]" for the browser scan, ".[claude]" for Claude
python -m playwright install chromium        # only for the browser scan
brew install ffmpeg                          # FFmpeg and ffprobe on PATH
cd web && npm install && npm run export      # build the web app once (served by the API)
cp .env.example .env                         # then fill in the keys you use
```

## 2. Verify offline first (no key, no cost)

```bash
pytest                                       # 104 tests, no network
python scripts/demo_pipeline.py --keep ./demo-data
EMVOOX_DATA_DIR=./demo-data EMVOOX_ENABLE_MOCK=true python -m emvoox serve   # look at the demo in the UI
python -m emvoox doctor                      # Python, FFmpeg, registry, which keys are set
```

## 3. When to plug in the WaveSpeed key, and the first real test

Plug `WAVESPEED_API_KEY` into `.env` **after step 2 passes**: at that point every agent, the QA loop and the gate are
proven offline, so the first paid run only tests the vendors. Then:

1. Add the key to `.env` and restart the server. Optionally make WaveSpeed the default:
   `EMVOOX_LLM_PROVIDER=wavespeed` and `EMVOOX_TTS_PROVIDER=wavespeed`.
2. `python -m emvoox doctor --live` (cheap GETs, no generation). It shows the balance and the speech models the key can
   reach. The LLM gateway does not list its models; ids are `vendor/model`. Verified on our key (2026-10-03):
   `google/gemini-3.1-flash-lite` (the default when `EMVOOX_LLM_MODEL` is empty), `google/gemini-3.6-flash`,
   `anthropic/claude-sonnet-5`, `openai/gpt-5-mini`, `deepseek/deepseek-chat`.
3. Produce **one** short episode first:
   `python -m emvoox run --series test1 --story story.txt --episodes 10 --produce 1 --llm wavespeed --tts wavespeed`
   (or New production in the UI with WaveSpeed selected and "Produce now" = 1). Expect a few cents: ~6-8 LLM calls
   and ~1,000-1,500 characters of TTS at about $0.20 per 1,000 characters on WaveSpeed's ElevenLabs v3.
4. Listen on the Approvals page, check the run on Pipeline and the spend on Costs, then approve or reject.
5. Scale to `--produce 3`, then to the whole batch.

WaveSpeed's ElevenLabs endpoint accepts any ElevenLabs voice id, so the Voice IPs' existing ElevenLabs voices (and later
the team's cloned voices) are used through WaveSpeed automatically; actors with only a Gemini voice get a placeholder
on WaveSpeed until one is plugged in.

## 4. Keys

### `WAVESPEED_API_KEY` (LLM gateway + speech models, one key)
- Dashboard → API keys at https://wavespeed.ai. Prepaid balance in USD; `GET /api/v3/balance` is shown on the Costs page.
- LLM: `https://llm.wavespeed.ai/v1`, OpenAI Chat Completions protocol, 90+ models (Gemini, Claude, GPT, DeepSeek…),
  pay per token.
- Speech: `elevenlabs/eleven-v3` ($0.20 / 1k characters per the model page; voice = preset or any ElevenLabs voice id),
  `minimax/speech-2.6-hd` (emotion / speed / pitch / volume; voice cloning via `minimax/voice-clone`, 10-30 s sample),
  `google/gemini-3.8-flash/text-to-speech` and `google/gemini-3.8-flash-lite/text-to-speech` (Gemini prebuilt voices, so
  each actor's Gemini voice; no cloned voices). Gemini TTS is billed **per request per started 1,000 characters**
  ($0.05 / $0.04; 100 characters cost the same as 1,000), so the engine sends two-speaker runs of lines as one dialogue
  request. Select it per run in the UI or with `EMVOOX_TTS_MODEL=google/gemini-3.8-flash/text-to-speech`.

### `GEMINI_API_KEY` (LLM + Gemini TTS)
- https://aistudio.google.com/apikey. Free tier: Gemini TTS is **10 requests per day per model** and ~3 per minute
  without billing; scene batching makes an episode cost 1-3 requests. Paid: $0.50-1 per 1M text tokens in,
  $10-20 per 1M audio tokens out (25 tokens per second of audio).
- `gemini-2.5-flash` is closed to new accounts; `gemini-3.1-flash-lite` is the default LLM, `gemini-3.6-flash` the
  thinking alternative. The client pins IPv4 (`EMVOOX_FORCE_IPV4`) because this network's IPv6 path resets TLS.

### `ELEVENLABS_API_KEY`
- https://elevenlabs.io → API Keys (add scope `user_read` so the Costs page can read the credit counter).
- Free tier: premade voices only via API (library voices return 402), no `wav_44100`. Creator (~$22) unlocks library
  voices and Professional Voice Cloning; Pro (~$99) 44.1 kHz PCM. `eleven_v3` 1 credit per character.

### Optional: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`
- `EMVOOX_LLM_PROVIDER=openai` (any OpenAI-compatible endpoint) or `anthropic` (Claude via the official SDK; install `.[claude]`).

## 5. Findings from earlier live runs (2026-09-20)

- ElevenLabs Free tier: five episodes cost ~6,100 of the 10,000 monthly characters; library voices need Creator.
- Gemini TTS: the multi-speaker direction header is not read aloud in single-speaker mode (verified); multi-speaker
  chunks are covered by tests, and the QA Critic's duration check catches spoken direction.
- Measured pace: 3.6 words per second on ElevenLabs v3 (drafts aim at 3.3).
