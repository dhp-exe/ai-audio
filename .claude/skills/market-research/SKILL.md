---
name: market-research
description: Run the Emvoox Market Research Agent alone to turn trend notes (and optionally a headless-browser scan of public DramaBox / ReelShort / TikTok pages) into a ranked TrendBrief the Script Writer can produce. Use when looking for the next story direction or before starting a series from a brief.
---

# market-research

```bash
python -m emvoox research --seeds "Top DramaBox tuần này: ..." [--focus urban_ceo|rebirth_butterfly_effect|intellectual_slap_anti_trope]
python -m emvoox research --seeds notes.md --browser          # + visible text of public listing pages (needs Playwright)
python -m emvoox run --series s2 --brief <brief_id> --episodes 20 --produce 2
```

Inputs: text passed with `--seeds`, every `.md/.txt/.json` under `data/inputs/trends/`, and with `--browser` the pages in
`data/inputs/market_sources.json` (default: DramaBox, ReelShort, TikTok listing pages). The browser scan is optional:
`pip install -e '.[research]' && playwright install chromium`; blocked or login-walled pages are skipped and logged.

Skills: Market Scan (collect observations) -> Content Analyze (one LLM call: insights + 3-5 story directions rated on
audience fit, momentum, production fit) -> Trend Ranking (weighted score; the editor's `--focus` line ranks first).
The brief is saved to `data/research/briefs/<id>.json` and listed on the Market research page.
