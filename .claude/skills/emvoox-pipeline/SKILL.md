---
name: emvoox-pipeline
description: Run, continue and inspect the Emvoox multi-agent audio pipeline (Market Research -> Script Writer -> Casting -> AI Director -> Sound Engineer -> QA Critic -> Approval Gate). Use to produce episodes of a series from a story, a trend brief or a fresh market scan, to resume a series, to approve or reject episodes at the human gate, or to run the offline demo.
---

# emvoox-pipeline

The engine lives in `emvoox/engine/orchestrator.py`; agents in `emvoox/agents/`. Every command prints a one-line JSON
summary last and exits non-zero on failure. Data lives under `./data` (`EMVOOX_DATA_DIR`).

```bash
python -m emvoox doctor [--live]                                     # keys, FFmpeg, registry; --live pings the vendors (no generation)
python scripts/demo_pipeline.py [--keep ./demo-data]                  # offline end to end, mock LLM + mock voices, no API key
python -m emvoox run --series s1 --story story.txt --episodes 30 --produce 3 --tts gemini
python -m emvoox run --series s2 --research --seeds "ghi chú xu hướng..." --llm wavespeed --tts wavespeed --episodes 10 --produce 1
python -m emvoox run --series s3 --brief <brief_id> --episodes 20 --produce 2
python -m emvoox run --series s1 --only 4-6                           # continue: keeps the outline and drafts, stems cached by hash
python -m emvoox approve --series s1 --episode 1 --reviewer an        # exports to data/outputs/approved_masters/s1/
python -m emvoox reject  --series s1 --episode 2 --reviewer an --notes "line 3 flat" --lines ep02_sc01_l003
python -m emvoox serve                                                # web app + API at http://127.0.0.1:8765
```

Useful flags on `run`: `--llm gemini|wavespeed|openai|anthropic|mock`, `--llm-model`, `--tts gemini|elevenlabs|wavespeed|mock`,
`--tts-model`, `--batching auto|line|scene`, `--max-retries N` (QA retry loop, default 3), `--auto-approve`, `--no-halt`,
`--tier test|final` (final refuses placeholder voices), `--force` (redo outline and drafts).

What a run does per episode: draft (+ Cliffhanger Check) -> direct (EpisodeScript, then DirectedConversationUnits,
validated) -> voice (render plan, cached by content hash) -> master (-16 LUFS / -1.5 dBTP) -> QA (PASS/FLAGGED with
timestamped issues) -> up to N automatic re-renders of the flagged units -> the human gate. A run ends
`awaiting_approval`; with `halt_on_qa_fail` an episode still FLAGGED after the retries halts the run.

Artifacts per episode: `data/series/<id>/scripts/{raw,parsed,checks}/epNN.*`, `directed/epNN.json`,
`stems/epNN/` (+ `.meta.json`, `render.json`), `timelines/`, `masters/epNN_master.{wav,mp3,json}`,
`qa/epNN_report.json`, `release/epNN.json`; run state `pipeline_run.json`, events `logs/events.jsonl`,
step logs `logs/<step>.log`, ledger `run.log.jsonl`.
