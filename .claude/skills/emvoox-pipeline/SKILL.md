---
name: emvoox-pipeline
description: Run, continue and inspect the Emvoox multi-agent audio pipeline (Market Research -> Script Writer -> Casting -> AI Director -> Sound Engineer -> QA Critic -> Approval Gate). Use to produce episodes of a series from a story, a trend brief or a fresh market scan, to resume a series, to answer what a paused run is waiting for (scene approvals, budget), to approve or reject episodes at the human gate, to start workers, or to run the offline demo.
---

# emvoox-pipeline

Production runs on a workflow graph (`emvoox/workflow`, LangGraph) driven by `Engine` (`emvoox/engine/orchestrator.py`);
agents are in `emvoox/agents/`. Every command prints a one-line JSON summary last and exits non-zero on failure. Data
lives under `./data` (`EMVOOX_DATA_DIR`).

```bash
python -m emvoox doctor [--live]                                     # keys, FFmpeg, registry, storage, queue; --live pings the vendors (no generation)
python scripts/demo_pipeline.py [--keep ./demo-data]                  # offline end to end, mock LLM + mock voices, no API key
python -m emvoox run --series s1 --story story.txt --episodes 30 --produce 3 --tts gemini
python -m emvoox run --series s2 --research --seeds "ghi chú xu hướng..." --llm wavespeed --tts wavespeed --episodes 10 --produce 1
python -m emvoox run --series s3 --brief <brief_id> --episodes 20 --produce 2
python -m emvoox run --series s1 --only 4-6                           # continue: keeps the outline and drafts, stems cached by hash
python -m emvoox run --series s4 --story story.txt --scene-approval --max-cost 2    # pauses: every scene, and at the budget
python -m emvoox decide --series s4                                   # what the paused run is waiting for
python -m emvoox decide --series s4 --scene sc01 --approve --reviewer an            # answer; the run continues in this process
python -m emvoox decide --series s4 --scene sc02 --reject --reviewer an --units ep01_sc02_l003 --notes "flat"
python -m emvoox decide --series s4 --budget --approve --max-cost 5 --reviewer an   # or --reject to stop the run
python -m emvoox approve --series s1 --episode 1 --reviewer an        # the episode gate: exports to data/outputs/approved_masters/s1/
python -m emvoox reject  --series s1 --episode 2 --reviewer an --notes "line 3 flat" --lines ep02_sc01_l003
python -m emvoox serve                                                # web app + API + an embedded worker at http://127.0.0.1:8765
python -m emvoox worker                                               # more workers (EMVOOX_QUEUE=redis)
```

Useful flags on `run`: `--llm gemini|wavespeed|openai|anthropic|mock`, `--llm-model`, `--tts gemini|elevenlabs|wavespeed|mock`,
`--tts-model`, `--batching auto|line|scene`, `--max-retries N` (per scene, default 3), `--auto-approve`, `--no-halt`,
`--tier test|final` (final refuses placeholder voices), `--force` (redo outline and drafts), `--scene-approval`, `--max-cost USD`.

What a run does per episode: draft (+ Cliffhanger Check) -> direct (EpisodeScript, then DirectedConversationUnits,
validated) -> **every scene in parallel**: render (cached by content hash, under a per-provider cap) -> scene QA ->
up to N re-renders of that scene's flagged units -> [scene approval] -> join -> master (-16 LUFS / -1.5 dBTP) ->
episode QA (the scene reports rolled up + loudness, true peak, duration) -> the human gate.

How a run ends:
- `awaiting_approval`: episodes are parked at the gate; approve or reject them. The gate does not block the run.
- `waiting`: the run is paused for a decision (`pending` in the JSON summary: a scene approval or the budget). Answer
  with `decide`, the Approvals page, the Pipeline page or the chat. Its checkpoint survives a restart.
- `halted`: an episode stayed FLAGGED after its retries (`halt_on_qa_fail`), or the budget was declined.
- A run that was in progress when the process died is recovered from its checkpoint when the server starts (memory
  queue) or when a worker takes its job again (Redis). Audio already rendered is not paid for twice.

`run` from the CLI executes in this process, with no queue. Runs started from the web app, the API or the chat are
queued and executed by a worker.

Artifacts per episode: `data/series/<id>/scripts/{raw,parsed,checks}/epNN.*`, `directed/epNN.json`,
`stems/epNN/` (+ `.meta.json`, `render.json`), `timelines/`, `masters/epNN_master.{wav,mp3,json}`,
`qa/epNN_report.json`, `qa/epNN_scNN.json` (one scene), `release/epNN.json`; run state `pipeline_run.json`
(steps, scenes, pending decisions), events `logs/events.jsonl`, step logs `logs/<step>.log`, ledger `run.log.jsonl`;
checkpoints `data/runs/checkpoints.sqlite` (or PostgreSQL).
