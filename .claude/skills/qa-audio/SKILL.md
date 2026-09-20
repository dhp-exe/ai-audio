---
name: qa-audio
description: QA gate for an assembled episode. Runs automatic checks (missing stems, master duration vs target, integrated loudness and true peak vs target, plus stubs for clipping, silence gaps and STT transcript diff), lists lines that need human listening (intensity >= 9, monologues at high intensity), and records the human verdict. The human review UI is a local FastAPI page (Phase 4). Use before publishing an episode.
---

# qa-audio

Stage [6]. Produces `series/<id>/qa/epNN_report.json`. Nothing ships without `human.verdict == "approved"`.

```bash
python .claude/skills/qa-audio/scripts/qa_audio.py --series demo --episode 1                 # auto checks
python .claude/skills/qa-audio/scripts/qa_audio.py --series demo --episode 1 --transcribe    # + STT diff (Phase 4)
python .claude/skills/qa-audio/scripts/qa_audio.py --series demo --episode 1 --verdict approved --reviewer phuoc
python .claude/skills/qa-audio/scripts/qa_audio.py --series demo --episode 1 --verdict rejected --lines ep01_sc02_l003 --notes "sai tông"
```

## Automatic checks

| check | source | fail condition | status |
|---|---|---|---|
| stems_complete | stems dir vs parsed script | any non-pause line without a stem | done |
| duration | ffprobe on master vs `target_duration_sec` | outside 60-150% of target | done |
| loudness | ffmpeg `ebur128` on master | integrated off target by > 1 LU, or true peak above limit | done |
| clipping | per-stem peak | any stem above -0.1 dBFS | Phase 4 |
| silence | ffmpeg `silencedetect` | any gap > 3 s | Phase 4 |
| transcript_diff | STT per stem vs `line.text` | WER > 15% | Phase 4 |

## Human review

`review_lines` lists intensity >= 9 lines and monologues with intensity >= 7. The reviewer UI
(D11) is a local FastAPI app with a per-line waveform player and approve / reject / re-render
buttons that write to this same report; see docs/IMPLEMENTATION_PLAN.md Phase 4.
