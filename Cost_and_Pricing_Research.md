# TTS Cost and Pricing Research: ElevenLabs vs MiniMax vs Gemini

| | |
|---|---|
| Purpose | Choose the TTS vendor and plan for producing one 30-minute audio story per day with our pipeline |
| Date | 2026-09-22 (prices and limits checked 2026-09-21 on the vendors' pages; see Sources) |
| Owner | Product / pipeline team |
| Status | Recommendation ready for decision (section 8) |

---

## 1. Summary

- **Gemini TTS is the cheapest by far**: about $0.50 to $0.95 per 30-minute day ($14 to $28 a month) once billing is enabled. Its free tier cannot sustain the daily target (10 requests per day per model).
- **ElevenLabs is the most expressive and the only one with our Character IP voices**, at about $3.20 per day. A daily cadence needs the **Pro plan ($99/month)**; depending on how the plan allowance is counted (see 3.1) the real monthly cost is $99 to about $165.
- **MiniMax sits in the middle** ($1.90 to $3.20 per day, $58 to $96 a month pay as you go) with the best explicit pause control and the cheapest voice cloning, but it is **not integrated in the pipeline today** (adapter removed 2026-09-20).
- **Optimal setup**: produce the daily episodes on **Gemini 2.5 Flash TTS (paid tier)**, about $14 a month. Each series is rendered exactly once, on one engine chosen before production starts; ElevenLabs Pro is reserved for a series that must launch on the Character IP voices from its first episode. Details in section 8.

---

## 2. What we are sizing

The numbers below come from the pipeline's own ledger on the two series produced so far.

| Quantity | Value | Basis |
|---|---|---|
| Finished audio per day | 1,800 s (30 min) | target |
| Words per second of master | 3.3 to 3.8 | measured |
| TTS characters per second of master (incl. tags) | 15 to 18 | measured |
| **Characters per day** | **≈ 32,000** (28k to 35k with retries) | derived |
| Characters per month (30 days) | ≈ 1,000,000 | derived |
| Audio per month | 15 hours | derived |
| Lines per day | ≈ 500 | 8 to 12 per 60 s episode |
| Requests per day, Gemini scene batching | 60 to 90 | 1 to 3 per episode |
| Requests per day, ElevenLabs per line | ≈ 500 (≈ 80 to 100 with Text to Dialogue, planned) | |
| LLM cost (outline, draft, direct on gemini-3.1-flash-lite) | ≈ $5 per month | ledger |

Stems are cached by content hash, so re-running an unchanged episode costs nothing; only edited text or changed voices re-spend.

---

## 3. How each vendor charges

### 3.1 ElevenLabs

- **Unit**: characters sent, billed as credits. On Eleven v3 and Multilingual v2, 1 character = 1 credit ($0.10 per 1,000). Flash v2.5 and Turbo v2.5 cost 0.5 credit per character ($0.05 per 1,000). Audio tags such as `[sighs]` count as characters (about 8 percent of our text).
- **Model**: a monthly subscription with an included credit allowance, plus usage-based overage on paid plans (about $0.17 to $0.20 per 1,000 credits depending on tier). Annual billing is about 17 percent cheaper.
- **Gates by plan**: library voices and cloned voices through the API require a paid plan (our Free key gets `402 paid_plan_required`, observed live). Professional Voice Cloning starts at Creator. 44.1 kHz PCM/WAV output and 192 kbps MP3 need Pro or above (our adapter falls back to 128 kbps MP3 on lower tiers).
- **Discrepancy to confirm at checkout**: the API pricing page lists included *characters* (Starter 60,000; Creator 220,000; Pro 990,000) while the general plans page lists *credits* (Starter 30,000; Creator about 100,000 to 121,000; Pro 600,000; Scale 1,800,000). The figures in this document give both where it changes the conclusion. The subscription endpoint our Usage page reads is the source of truth once subscribed.

| Plan | Monthly | Included (API page, characters) | Included (plans page, credits) | Notable features |
|---|---|---|---|---|
| Free | $0 | 10,000 | 10,000 | Premade voices only via API; no commercial license |
| Starter | $6 | 60,000 | 30,000 | Commercial license, Instant Voice Cloning |
| Creator | $22 ($11 first month) | 220,000 | ~100,000 | Professional Voice Cloning (1 slot), 192 kbps MP3 |
| Pro | $99 | 990,000 | 600,000 | 44.1 kHz PCM via API, PVC (1) |
| Scale | $299 | 2,990,000 | 1,800,000 | PVC (3), 3 seats |
| Business | $990 | 9,900,000 | 6,000,000 | PVC (10), 10 seats |

### 3.2 Gemini TTS (Gemini API)

- **Unit**: tokens. Input text at $0.50 to $1.00 per million tokens; output audio at $10 to $20 per million *audio tokens*, where 1 second of audio = 25 tokens. So 30 minutes of audio = 45,000 output tokens.
- **Model**: pay as you go with no subscription; billing must be enabled on the Google Cloud project. A Batch API tier (asynchronous) is 50 percent cheaper but our pipeline renders synchronously.
- **Free tier**: both Flash TTS models are free without billing but limited to about 3 requests per minute and **10 requests per day per model** (observed live as `GenerateRequestsPerDayPerProjectPerModel-FreeTier`). With scene batching that is 3 to 10 episodes per day, not 30. Rate limits for paid tiers are shown per project in AI Studio; Tier 1 unlocks as soon as billing is linked.
- **Status**: all three TTS models are "preview" models.

| Model | Free tier | Paid: text in / audio out per 1M tokens | Notes |
|---|---|---|---|
| gemini-2.5-flash-preview-tts | yes (10 req/day) | $0.50 / $10 | previous-generation voices, cheapest |
| gemini-3.1-flash-tts-preview | yes (10 req/day) | $1.00 / $20 | current default in the pipeline, newest voices, inline tags |
| gemini-2.5-pro-preview-tts | no | $1.00 / $20 | highest quality of the line |

### 3.3 MiniMax (Speech API)

- **Unit**: characters, pay as you go: **speech-2.8-turbo $60 per million characters, speech-2.8-hd $100 per million** (older 2.6 and 02 generations at the same prices). Voice cloning is a one-time fee per voice: Rapid Voice Cloning $1.50, Voice Design $3.00.
- **Subscriptions ("audio points")**: monthly plans with points quotas and rate limits (RPM). MiniMax does not publish the points-to-character rate for HD versus Turbo; the free tier's "10,000 points ≈ 12 minutes of HD audio" implies roughly 1 point per character on HD. Purchased credits now expire after two months.

| Plan | Monthly | Audio points | RPM | Voice slots |
|---|---|---|---|---|
| Free | $0 | 10,000 | | 3 |
| Starter | $5 | 100,000 | 10 | 10 |
| Standard | $30 | 300,000 | 50 | 100 |
| Pro | $99 | 1,100,000 | 200 | 250 |
| Scale | $249 | 3,300,000 | 500 | 500 |
| Business | $999 | 20,000,000 | 800 | 800 |

Third-party summaries quote slightly different tier prices ($17 Standard, $38 Pro); the table uses MiniMax's own documentation.

---

## 4. Output quality and how much emotion we can control

What matters for our micro-dramas: Vietnamese support, how delivery is directed (tags, prompts, numeric knobs), multi-voice conversation rendering, and whether the voice can be *ours* (cloning). The pipeline's Director already produces emotion, intensity 1 to 10, pace, volume, tags and a free-text acting note for every line; the question is how much of that each engine can act on.

| Capability | ElevenLabs Eleven v3 | ElevenLabs Flash v2.5 | Gemini 3.1 / 2.5 Flash TTS | MiniMax speech-2.8 |
|---|---|---|---|---|
| Vietnamese | yes (70+ languages) | yes (32 languages) | yes (80+ languages) | yes (~40 languages, `language_boost: Vietnamese`) |
| Emotion direction | inline audio tags (`[sighs]`, `[whispers]`, `[crying]`, `[shouting]`…); the delivery follows the text's punctuation and context | none beyond text | natural-language director's notes (style, scene, pacing) plus inline tags (`[whispers]`, `[laughs]`, `[sighs]`, `[gasp]`) | `emotion` parameter with 9 values (happy, sad, angry, fearful, disgusted, surprised, calm, fluent, whisper) plus interjection tags (`(laughs)`, `(sighs)`) on 2.8 |
| Numeric knobs | stability (Creative / Natural / Robust), similarity | stability, similarity, style, speed | none (prompt only) | speed 0.5 to 2, volume, pitch −12 to +12 |
| Precise pauses | no (tags only; pipeline inserts silence at assembly) | no | no (pipeline inserts silence) | **yes**: `<#1.5#>` inline pause markers |
| Multi-voice in one request | Text to Dialogue: up to 10 voices, 2,000 characters, per-line timestamps | no | up to 2 speakers per request | no (one voice per request) |
| Voices | thousands (library needs a paid plan), instant and professional cloning | same | 30 prebuilt, no cloning | system voices, cloning $1.50 per voice, voice design $3 |
| Max text per request | 5,000 characters | 40,000 | 32k-token session | 10,000 characters |
| Expressiveness (our assessment) | highest: verified emotional range in Vietnamese on our IP placeholders | low, flat | high in prompt-driven style, reactive timing inside a chunk; verified the direction is not read aloud | medium to high; emotion enum is coarse but reliable, pauses are exact |
| Pipeline status | integrated, live-verified | integrated (same adapter) | integrated, scene batching, live-verified single speaker | not integrated (removed 2026-09-20; adapter is 1 to 2 days of work) |

Two facts that change model choices:

- **ElevenLabs Multilingual v2 does not list Vietnamese.** It is currently our same-voice fallback model. Flash v2.5 does support Vietnamese and costs half; it should be the fallback.
- **Voice identity is the product.** Only ElevenLabs (now) and MiniMax (cheaply) can carry a cloned Character IP voice. Gemini's 30 fixed voices are fine for daily production but cannot become an IP asset. This is why the engine is chosen per series before production starts: a series is rendered once, on one engine, and never rendered again on another.

---

## 5. Cost per day and per month at 30 minutes per day

All figures for ≈ 32,000 characters and 1,800 seconds of audio per day; LLM cost (≈ $5 per month) is the same for every option and excluded.

| Vendor and model | Per day | Per month (30 days) | Plan or billing required | Fits the daily cadence? |
|---|---|---|---|---|
| Gemini 2.5 Flash TTS (paid) | $0.47 | **$14** | billing enabled, pay as you go | yes |
| Gemini 3.1 Flash TTS (paid) | $0.93 | **$28** | same | yes |
| Gemini 2.5 Pro TTS (paid) | $0.93 | $28 | same | yes |
| Gemini Flash TTS (free tier) | $0 | $0 | none | **no**: 3 to 10 episodes per day |
| Gemini, Batch API tier | $0.24 to $0.47 | $7 to $14 | billing; asynchronous rendering (not implemented) | future option |
| MiniMax speech-2.8-turbo (PAYG) | $1.92 | **$58** | pay as you go | yes (adapter needed) |
| MiniMax speech-2.8-hd (PAYG) | $3.20 | **$96** | pay as you go | yes (adapter needed) |
| MiniMax Pro subscription | | $99 | 1.1M points; assumes ≈ 1 point per character | yes, unverified conversion |
| ElevenLabs Flash v2.5 | $1.60 | $48 | Creator (220k characters) is short; Pro | quality too flat for drama |
| ElevenLabs Eleven v3 | $3.20 | **$96 of usage** | Pro $99 (fits if 990k characters; if 600k credits, Pro + ≈ $65 overage ≈ $165, or Scale $299) | yes |
| ElevenLabs Eleven v3 on Free | | | 10,000 credits ≈ 8 minutes per month; library voices blocked | no |

How the Gemini figures are computed: 1,800 s × 25 tokens = 45,000 audio tokens per day; at $10 per million that is $0.45 (2.5 Flash) or $0.90 at $20 per million (3.1 Flash, 2.5 Pro). Text input is about 30,000 tokens per day including the per-chunk direction headers, $0.015 to $0.03.

### Monthly scenarios

| Scenario | What runs where | Monthly TTS cost |
|---|---|---|
Every series is rendered once; the scenarios differ only in which engine is chosen before production.

| Scenario | What runs where | Monthly TTS cost |
|---|---|---|
| A. All Gemini | every episode on 2.5 Flash TTS (or 3.1) | $14 to $28 |
| B. All ElevenLabs v3 | every episode on the IP voices | $99 to $165 |
| C. All MiniMax turbo | every episode, cloned voices | $58 (+ one-time $1.50 per voice) |
| D. Mixed roles | leads on ElevenLabs v3, supporting roles on Gemini, in the same series | ≈ $55 to $70 |
| E. Per-series choice | most series on Gemini; a series that must launch on IP voices produced on ElevenLabs from episode 1 | $14 to $28 in Gemini-only months; $99 to $165 in a month with an ElevenLabs series |

---

## 6. Vendor-by-vendor verdict

**ElevenLabs.** Best acting range and the only engine that already hosts our IP voices and the professional cloning the voice track needs. Costs about 3.5 to 7 times Gemini. Buy Pro only for a month in which a series is produced on its IP voices from the first episode; Creator ($22, 220k characters) covers about 7 daily episodes per month plus PVC and is the right plan for the cloning experiments themselves.

**Gemini TTS.** Cheapest production path by an order of magnitude and already the pipeline's default with scene batching. Limits: preview models, 30 fixed voices, two speakers per request, no cloning, quotas that require billing to be useful. Right choice for the daily production where volume matters more than voice identity. Prefer 2.5 Flash TTS at half the price unless listening tests show 3.1's voices win.

**MiniMax.** Worth keeping on the list for two features nobody else offers at this price: exact inline pauses and $1.50 voice cloning. It would suit the cloning track as a low-cost home for custom voices if ElevenLabs PVC proves too expensive per slot. Cost of adoption is one adapter and re-validation of the emotion mapping; not needed for the current plan.

---

## 7. Risks and things to verify before committing money

1. ElevenLabs plan allowance: confirm whether Pro includes 990k characters or 600k credits at checkout; it decides between $99 and about $165 a month.
2. Gemini paid-tier request limits are only visible in AI Studio after billing is enabled; confirm they allow 60 to 90 TTS requests per day before scheduling.
3. Gemini multi-speaker chunks have not been live-verified (free quota was exhausted); one paid day of testing settles it.
4. MiniMax points-to-character conversion is unpublished; if a subscription is ever considered, run a 1,000-character probe and read the balance.
5. Preview models can change voice quality without notice; keep the probe clips under `library/previews/` as a reference.

---

## 8. Recommendation

1. **Enable billing on the Gemini project now** and run the daily 30-minute cadence on **gemini-2.5-flash-preview-tts** with scene batching. Budget: about $14 a month (about $28 if 3.1 Flash is preferred after a listening test). This unblocks the daily target immediately with no code change.
2. **Take ElevenLabs Creator ($22) for the voice-cloning track** (Professional Voice Cloning, library voices, 220k characters for auditions) and **upgrade to Pro ($99) only for a month in which a series is produced on the IP voices from its first episode**. Switch the same-voice fallback from Multilingual v2 to Flash v2.5.
3. **Do not reinstate MiniMax now.** Revisit if the cloning track needs many cheap custom voices or if exact inline pauses become a quality requirement; the adapter cost is small.
4. **Decide the engine per series before production and never render a series twice.** Re-voicing a finished series on another engine would double its TTS spend; the pipeline's hash cache already guarantees that an unchanged episode is never re-rendered on the same engine.

Expected steady-state spend under this plan: **about $14 to $28 a month** for daily production on Gemini, rising to $99 to $165 only in a month with an ElevenLabs series, versus $100 to $165 every month for producing everything on ElevenLabs.

---

## Sources

- ElevenLabs API pricing: https://elevenlabs.io/pricing/api
- ElevenLabs plans: https://elevenlabs.io/pricing
- ElevenLabs models and language support: https://elevenlabs.io/docs/overview/models
- ElevenLabs text to speech capabilities: https://elevenlabs.io/docs/overview/capabilities/text-to-speech
- Gemini API pricing: https://ai.google.dev/gemini-api/docs/pricing
- Gemini API rate limits: https://ai.google.dev/gemini-api/docs/rate-limits
- Gemini speech generation guide: https://ai.google.dev/gemini-api/docs/speech-generation
- Gemini 3.1 Flash TTS pricing explainer (audio tokens per second): https://www.nemovideo.com/blog/gemini-3-1-flash-tts-pricing
- MiniMax pay-as-you-go pricing: https://platform.minimax.io/docs/guides/pricing-paygo.md
- MiniMax audio subscription: https://platform.minimax.io/docs/guides/pricing-speech.md
- MiniMax text-to-speech API reference: https://platform.minimax.io/docs/api-reference/speech-t2a-http
- MiniMax Speech review (third-party plan summary): https://knowara.com/ai-tools/voice/minimax-speech-review/
- Pipeline measurements: `series/*/run.log.jsonl`, `series/*/scripts/parsed/*.json`, master durations via ffprobe (2026-09-21)
