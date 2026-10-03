#!/usr/bin/env python3
"""End-to-end demo of the Emvoox multi-agent pipeline.

Offline by default: the mock LLM writes a fixed Vietnamese story and the mock voice engine renders
tones instead of speech, so every agent, the contract validation, the QA retry loop, the human
gate, the export and the cost ledger run with no API key. A fault is injected on one line so you
can watch the QA Critic flag it and the engine re-render it.

    python scripts/demo_pipeline.py                          # offline, sandbox under /tmp, 2 episodes
    python scripts/demo_pipeline.py --keep ./demo-data       # keep the sandbox to inspect or open in the UI
    python scripts/demo_pipeline.py --live --llm wavespeed --tts wavespeed --episodes 1
                                                             # real vendors from .env, real data dir

``--live`` spends real credits (one short episode is a few cents) and writes to the configured
data directory (./data unless EMVOOX_DATA_DIR says otherwise).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SEED = """# Ghi chú xu hướng tuần này (DramaBox / ReelShort / TikTok)
- "Vợ cũ tổng tài phản công": 40 triệu lượt xem, bước ngoặt ở giây thứ 20, mỗi tập kết bằng một tin nhắn bí ẩn.
- Phim "Ngày tôi bị vu oan": nữ kế toán bị đổ lỗi thâm hụt, tự tìm bằng chứng; bình luận khen phản diện thông minh.
- Trend TikTok #tráisinh: sống lại để sửa sai, nhưng ký ức cũ không chính xác.
- Khán giả nữ 18-34 nghe truyện audio buổi tối, bỏ dở khi mở đầu dài trên 30 giây.
"""


def configure(args: argparse.Namespace) -> Path:
    if args.live:
        data = Path(os.environ.get("EMVOOX_DATA_DIR") or ROOT / "data")
    else:
        data = Path(args.keep).resolve() if args.keep else Path(tempfile.mkdtemp(prefix="emvoox-demo-"))
        data.mkdir(parents=True, exist_ok=True)
        os.environ["EMVOOX_DATA_DIR"] = str(data)
        os.environ["EMVOOX_LLM_PROVIDER"] = "mock"
        os.environ["EMVOOX_TTS_PROVIDER"] = "mock"
        reg = data / "assets" / "voice_registry.json"
        if not reg.exists():  # the studio's real Voice IPs, so casting picks real actors
            reg.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "data" / "assets" / "voice_registry.json", reg)
        seeds = data / "inputs" / "trends"
        seeds.mkdir(parents=True, exist_ok=True)
        (seeds / "weekly-notes.md").write_text(SEED, encoding="utf-8")
    from emvoox.config import reset_settings
    from emvoox.repositories import reset_repositories

    reset_settings()
    reset_repositories()
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="use the vendors configured in .env instead of the offline mocks")
    ap.add_argument("--llm", default=None, help="with --live: gemini | wavespeed | openai | anthropic")
    ap.add_argument("--tts", default=None, help="with --live: gemini | elevenlabs | wavespeed")
    ap.add_argument("--episodes", type=int, default=2, help="episodes to produce now (the plan has 10)")
    ap.add_argument("--series", default="demo-emvoox")
    ap.add_argument("--keep", default=None, help="offline: sandbox directory to keep (default: a temp dir, removed at the end)")
    ap.add_argument("--no-fault", action="store_true", help="offline: do not inject the clipped line")
    args = ap.parse_args()
    data = configure(args)

    from emvoox.agents.publisher import approve
    from emvoox.config import get_settings
    from emvoox.contracts import PipelineEvent, ResearchParams, RunParams
    from emvoox.engine.orchestrator import Engine
    from emvoox.providers.tts.mock import MockTtsProvider
    from emvoox.repositories import get_repositories

    s = get_settings()
    repos = get_repositories()
    if not args.live and not args.no_fault:
        MockTtsProvider.faults = {"ep01_sc01_l002": "clip"}  # QA must catch this and the engine must fix it

    params = RunParams(series_id=args.series, episodes=10, produce=args.episodes, min_sec=45, max_sec=70, source="research",
                       research=ResearchParams(seeds=SEED if args.live else "", focus="intellectual_slap"),
                       tts_provider=args.tts or s.tts_provider, llm_provider=args.llm or s.llm_provider, max_retries=3,
                       auto_approve=False, halt_on_qa_fail=True, force=True)

    def show(ev: PipelineEvent) -> None:
        if ev.type in ("step.finished", "step.failed", "contract.rejected", "qa.flagged", "gate.waiting", "gate.approved", "run.finished", "cast.resolved"):
            print(f"  {ev.type:<17} {ev.step_id or '':<11} {(ev.status or ''):<17} {ev.message[:90]}")

    print(f"Emvoox demo | data: {data} | LLM {params.llm_provider} | TTS {params.tts_provider}\n")
    engine = Engine(params, repos=repos, on_event=show)
    state = asyncio.run(engine.run())

    print(f"\nRun {state.run_id}: {state.status}" + (f" ({state.error})" if state.error else ""))
    for step in state.steps:
        extra = json.dumps(step.summary, ensure_ascii=False)[:100] if step.summary else (step.error or "")
        print(f"  {step.id:<12} {step.agent:<15} {step.status:<9} x{step.attempts} {step.elapsed_s:>6.2f}s ${step.cost_usd:.4f}  {extra}")
    for n in params.episode_numbers():
        r = repos.series.load_qa(args.series, n)
        if r:
            print(f"  QA ep{n:02d}: {r.status} score {r.score} after {r.attempt} retr{'y' if r.attempt == 1 else 'ies'}; "
                  f"issues: {[i.code for i in r.error_logs] or 'none'}")
    t = state.totals
    print(f"\nTelemetry: {t.llm_calls} LLM call(s), {t.tokens_in + t.tokens_out} tokens, {t.tts_requests} TTS request(s), "
          f"{t.tts_characters} characters, {t.audio_ms / 1000:.1f}s audio, {t.qa_retries} QA retr{'y' if t.qa_retries == 1 else 'ies'}, "
          f"estimated ${t.cost_usd:.4f}")

    waiting = [p for p in repos.series.list_releases(args.series) if p.state == "awaiting_approval"]
    if waiting:
        pkg = approve(repos, args.series, waiting[0].episode_number, reviewer="demo-script", notes="approved by the demo")
        print(f"\nHuman gate: approved ep{pkg.episode_number:02d} -> " + ", ".join(f.path for f in pkg.exported))
        print(f"  YouTube metadata: {pkg.metadata.title!r} ({len(pkg.metadata.tags)} tags)")
    ok = state.status in ("done", "awaiting_approval")
    if not args.live and not args.keep:
        shutil.rmtree(data, ignore_errors=True)
    elif args.keep:
        print(f"\nSandbox kept at {data}. Open it in the UI with: EMVOOX_DATA_DIR={data} python -m emvoox serve")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
