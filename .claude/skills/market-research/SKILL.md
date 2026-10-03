---
name: market-research
description: Run the Emvoox Market Research Agent alone to turn trend notes (and optionally a headless-browser scan of public DramaBox / ReelShort / TikTok pages) into a ranked TrendBrief the Script Writer can produce. Use when looking for the next story direction or before starting a series from a brief.
---

# market-research

```bash
python -m emvoox research --seeds "Top DramaBox tuần này: ..." [--focus urban_ceo|rebirth_butterfly_effect|intellectual_slap_anti_trope]
python -m emvoox research --browser --platforms dramabox,reelshort,tiktok,google,youtube --guide "Document the 3 most trending genres"
python -m emvoox run --series s2 --brief <brief_id> --episodes 20 --produce 2
```

Inputs: text passed with `--seeds`, every `.md/.txt/.json` under `data/inputs/trends/`, and with `--browser` the pages in
`data/inputs/market_sources.json` (default: DramaBox, ReelShort, TikTok, Google and YouTube pages). The browser scan needs
`pip install -e '.[research]' && playwright install chromium`. A page that shows a robot check or a login wall is
recorded as blocked and skipped; never try to get around it (on 2026-10-03 Google and TikTok were blocked from this network).

Skills: Market Scan (collect observations; each source is a step with status, excerpt and screenshot in
`data/research/scans/<id>.json`) -> Content Analyze (one LLM call: insights + the three most trending genres, each with
evidence, a story direction and ratings for audience fit, momentum, production fit) -> Trend Ranking (weighted score; the
editor's `--focus` line ranks first). The brief is saved to `data/research/briefs/<id>.json`. On the Market research page the
scan is shown live and the editor picks one of the three genres (`POST /api/research/briefs/{id}/select`); that pick is
what the Script Writer receives.
