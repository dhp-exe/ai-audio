# Setup: API keys and accounts

Copy `.env.example` to `.env` and fill in the keys below. Prices and free tiers change often; the
figures here are from the vendors' public pages as of September 2026 and should be re-checked on the
linked pages before budgeting.

## Phase 1 (episodize + AI Director)

### `GEMINI_API_KEY`
- **Get it:** Google AI Studio -> https://aistudio.google.com/apikey -> "Create API key". The SDK also
  accepts `GOOGLE_API_KEY`. No credit card needed for the free tier.
- **Free tier:** available for `gemini-2.5-flash` and the Flash-Lite models with per-minute and
  per-day request caps (on the order of 10 requests/min and a few hundred requests/day). Free-tier
  prompts may be used by Google to improve products; do not send confidential story material on the
  free tier. Enough for prompt iteration on 1-3 episodes, not for a 30-episode batch in one sitting.
- **Paid:** enable billing on the Google Cloud project linked to the key (AI Studio -> "Set up
  billing"). Pay-as-you-go per token. Reference: https://ai.google.dev/gemini-api/docs/pricing
  - `gemini-2.5-flash`: about $0.30 / 1M input tokens, $2.50 / 1M output tokens (thinking tokens bill
    as output).
  - `gemini-2.5-flash-lite`: about $0.10 / 1M input, $0.40 / 1M output.
  - `gemini-3.1-flash-lite`: check the pricing page; set `AI_AUDIO_LLM_MODEL` to switch.
  - Rough series cost: 31 episodize calls + 30 Director calls, each ~3-6k input and ~2-4k output
    tokens, lands well under $1 per 30-episode series on 2.5 Flash.

## Phase 2 (TTS)

### `ELEVENLABS_API_KEY`
- **Get it:** https://elevenlabs.io -> sign in -> profile menu (bottom left) -> "API Keys" ->
  "Create API key". Scope it to Text to Speech + Voices.
- **Free tier:** 10,000 credits/month, non-commercial license, no voice cloning. Fine for auditioning
  the stock library, useless for our IP voices.
- **Paid (monthly, credits reset monthly):** https://elevenlabs.io/pricing
  - Starter ~$5: 30k credits, commercial license, Instant Voice Cloning.
  - Creator ~$22 (~$11 first month): 100k credits, **Professional Voice Cloning** (what our Voice
    IPs need), 192 kbps output.
  - Pro ~$99: 500k credits, higher concurrency.
  - Scale ~$330: 2M credits. Business ~$1,320: 11M credits.
  - Billing: `eleven_v3` and `eleven_multilingual_v2` cost 1 credit per character;
    `eleven_flash_v2_5` 0.5. A 30-episode Vietnamese series is roughly 35-45k characters of dialogue,
    so **Creator** covers one series per month including ~2x re-rolls; Pro if you iterate heavily.
  - PVC requires ~30 min of clean recordings per voice and a verification step; plan a few days.

### `MINIMAX_API_KEY` and `MINIMAX_GROUP_ID` (fallback provider, optional until Phase 2 step 2)
- **Get it:** https://platform.minimax.io (international platform; the `.chat` domain is the China
  region) -> sign up -> "API Keys" -> create. The **GroupId** is shown in the account/organization
  settings page and is required in the request URL.
- **Free tier:** new accounts typically receive a small trial credit; no permanent free tier.
- **Paid:** pay-as-you-go per character, see https://platform.minimax.io/docs (pricing page).
  `speech-02-hd` is priced higher than `speech-02-turbo`; both are on the order of tens of dollars
  per 1M characters, so a 30-episode series costs a few dollars. Voice cloning is a separate,
  per-voice fee.

## Findings from the first live run (2026-09-20)

- **Gemini:** `gemini-2.5-flash` is listed by the Models API but returns 404 "no longer available to new users". `gemini-3.1-flash-lite` (no thinking, ~4 s/call) and `gemini-3.6-flash` (thinking, ~5-16 s/call) both work. Default is now 3.1-flash-lite.
- **Network:** on this machine IPv6 to `generativelanguage.googleapis.com` fails (TLS EOF). The client pins IPv4; set `AI_AUDIO_FORCE_IPV4=false` to disable elsewhere.
- **ElevenLabs Free tier:** API key scopes omit `user_read`/`models_read` (fine). Library voices such as *Thuy Duong - Vietnamese* return 402 via API on Free; only premade voices work. `wav_44100` output needs Pro; the adapter falls back to `mp3_44100_128`. Five episodes cost ~6,100 characters of the 10,000/month free quota.
- **Upgrade path:** Creator (~$22/mo) unlocks library voices and Professional Voice Cloning; that is the minimum for real Vietnamese Voice IPs.

## Not needed

- No Anthropic/OpenAI key (D10). No Suno/Soundraw (D5). No STS-related access (D4).

## Local tools

- Python 3.11+ (`python3 -m venv .venv && .venv/bin/pip install -e .[dev]`).
- FFmpeg + ffprobe on PATH (`brew install ffmpeg`), already present on this machine.

## Smoke test without any key

```bash
.venv/bin/python -m pytest -q
.venv/bin/python .claude/skills/parse-script/scripts/parse_script.py --series demo --episode 1 --dry-run
.venv/bin/python .claude/skills/generate-voice/scripts/generate_voice.py --series demo --episode 1 --dry-run
```
