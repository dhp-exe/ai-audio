"""Command line for Emvoox Engine.

    python -m emvoox serve [--host 127.0.0.1] [--port 8765]     API + web app
    python -m emvoox worker                                      run queued jobs (EMVOOX_QUEUE=redis); start as many as needed
    python -m emvoox run --series s1 --story story.txt --episodes 30 --produce 3 --tts gemini
    python -m emvoox run --series s2 --research --seeds "ghi chú xu hướng..." --llm wavespeed --tts wavespeed
    python -m emvoox run --series s1 --only 4-6                  continue an existing series
    python -m emvoox research [--seeds "..."] [--browser] [--platforms dramabox,youtube] [--guide "..."] [--focus urban_ceo]
    python -m emvoox run --series s1 --story story.txt --scene-approval --max-cost 2     pause for scene approvals and at a budget
    python -m emvoox decide --series s1                           list what a paused run is waiting for
    python -m emvoox decide --series s1 --scene sc01 --approve --reviewer an           answer; the run continues
    python -m emvoox decide --series s1 --scene sc02 --reject --reviewer an --units ep01_sc02_l003 --notes "flat"
    python -m emvoox decide --series s1 --budget --approve --max-cost 5 --reviewer an
    python -m emvoox approve --series s1 --episode 1 --reviewer an [--notes "..."]
    python -m emvoox reject  --series s1 --episode 1 --reviewer an --notes "line 3 sounds flat"
    python -m emvoox voices                                       list Voice IPs and their voices
    python -m emvoox plug-voice --actor ngan --provider elevenlabs --voice-id <id> [--model eleven_v3] [--label "Ngân PVC v1"]
    python -m emvoox doctor [--live]                              environment and key checks
    python -m emvoox agents                                       the agent fleet and its skills

Every command prints a one-line JSON summary last and exits non-zero on failure.
"""

from __future__ import annotations

import argparse
import json
import sys


def _out(d: dict, ok: bool = True) -> int:
    print(json.dumps(d, ensure_ascii=False))
    return 0 if ok else 1


def cmd_serve(a: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("emvoox.api.app:app", host=a.host, port=a.port, log_level="info")
    return 0


def cmd_worker(_a: argparse.Namespace) -> int:
    from emvoox.worker.worker import main as worker_main

    return worker_main()


def cmd_run(argv: list[str]) -> int:
    from emvoox.engine.orchestrator import main as run_main

    return run_main(argv)


def cmd_research(a: argparse.Namespace) -> int:
    from emvoox.agents import AgentContext, MarketResearchAgent
    from emvoox.config import get_settings
    from emvoox.contracts.run import ResearchParams, RunParams
    from emvoox.providers.llm import LlmClient, get_llm_provider
    from emvoox.repositories import get_repositories
    from emvoox.telemetry.ledger import Ledger

    s = get_settings()
    repos = get_repositories()
    ledger = Ledger(repos.telemetry)
    ctx = AgentContext(settings=s, repos=repos, llm=LlmClient(get_llm_provider(a.llm), ledger), ledger=ledger,
                       params=RunParams(series_id="research", tts_provider="mock"), log=lambda m: print(m, file=sys.stderr))
    seeds = a.seeds
    if seeds and seeds.endswith((".md", ".txt", ".json")):
        from pathlib import Path

        seeds = Path(seeds).read_text(encoding="utf-8")
    if a.agent:
        from emvoox.services.research import run_agent_scan

        session = run_agent_scan(repos, {"llm_provider": a.llm or s.llm_provider, "llm_model": a.llm_model, "seeds": seeds or "", "focus": a.focus or "",
                                         "guide": a.guide or "", "use_browser": a.browser or None,
                                         "platforms": [p.strip() for p in (a.platforms or "").split(",") if p.strip()]})
        scan = repos.research.load_scan(session.data["scan_id"])
        for line in scan.log:
            print(line, file=sys.stderr)
        print(session.result, file=sys.stderr)
        return _out({"ok": bool(scan.brief_id), "brief_id": scan.brief_id, "scan_id": scan.scan_id, "status": session.status, "steps": session.steps,
                     "tool_calls": sum(len(m.tool_calls) for m in session.messages), "cost_usd": session.cost_usd, "error": scan.error},
                    ok=bool(scan.brief_id))
    brief = MarketResearchAgent().run(ctx, ResearchParams(seeds=seeds or "", use_browser=a.browser or None, focus=a.focus or "", guide=a.guide or "",
                                                         platforms=[p.strip() for p in (a.platforms or "").split(",") if p.strip()]))
    for c in brief.candidates:
        print(f"{c.score:5.2f}  {c.theme_category.value:<30} {c.topic}", file=sys.stderr)
    return _out({"ok": True, "brief_id": brief.brief_id, "topic": brief.topic, "theme": brief.theme_category.value, "score": brief.score})


def cmd_gate(a: argparse.Namespace, decision: str) -> int:
    from emvoox.agents import AgentError
    from emvoox.agents import publisher as gate
    from emvoox.repositories import get_repositories

    try:
        if decision == "approve":
            pkg = gate.approve(get_repositories(), a.series, a.episode, reviewer=a.reviewer, notes=a.notes)
        else:
            pkg = gate.reject(get_repositories(), a.series, a.episode, reviewer=a.reviewer, notes=a.notes, lines=a.lines.split(",") if a.lines else [])
    except AgentError as e:
        return _out({"ok": False, "error": str(e)}, ok=False)
    return _out({"ok": True, "state": pkg.state, "exported": [f.path for f in pkg.exported]})


def cmd_voices(_a: argparse.Namespace) -> int:
    from emvoox.repositories import get_repositories

    reg = get_repositories().registry.load()
    for c in reg.characters:
        print(f"{c.character_id:<12} {c.display_name:<14} {'IP' if c.is_ip_asset else 'one-off':<8} preferred={c.preferred_provider or '-'}", file=sys.stderr)
        for p, v in c.providers.items():
            print(f"    {p:<11} {v.voice_id:<28} @ {v.model_id:<30} [{v.source}]{' ' + v.label if v.label else ''}", file=sys.stderr)
    return _out({"ok": True, "actors": len(reg.characters), "locked": reg.locked})


def cmd_plug(a: argparse.Namespace) -> int:
    from emvoox.contracts.production import ProviderVoice
    from emvoox.providers.tts.catalog import DEFAULT_MODEL
    from emvoox.repositories import RegistryLocked, get_repositories, now_iso

    repos = get_repositories()
    voice = ProviderVoice(voice_id=a.voice_id, model_id=a.model or DEFAULT_MODEL[a.provider], source=a.source, label=a.label, voice_url=a.url,
                          added_at=now_iso())
    try:
        _, entry = repos.registry.set_provider_voice(a.actor, a.provider, voice, unlock=a.unlock, make_preferred=not a.not_preferred)
    except KeyError:
        return _out({"ok": False, "error": f"unknown actor {a.actor!r}"}, ok=False)
    except RegistryLocked as e:
        return _out({"ok": False, "error": f"{e} (pass --unlock)"}, ok=False)
    repos.assets.delete_previews(f"{a.actor}_{a.provider}")
    return _out({"ok": True, "changelog": entry})


def cmd_doctor(a: argparse.Namespace) -> int:
    from emvoox.repositories import get_repositories
    from emvoox.services.doctor import run_checks

    checks = run_checks(get_repositories(), live=a.live)
    for c in checks:
        mark = {True: "ok ", False: "FAIL", None: " -  "}[c["ok"]]
        print(f"[{mark}] {c['label']:<34} {c['detail']}", file=sys.stderr)
    failed = [c["id"] for c in checks if c["ok"] is False]
    return _out({"ok": not failed, "failed": failed}, ok=not failed)


def cmd_agents(_a: argparse.Namespace) -> int:
    from emvoox.agents import fleet

    for a in fleet():
        print(f"{a['title']}  ({a['consumes']} -> {a['produces']})", file=sys.stderr)
        for s in a["skills"]:
            print(f"    - {s['name']}: {s['description']}", file=sys.stderr)
    return _out({"ok": True, "agents": len(fleet())})


def cmd_decide(a: argparse.Namespace) -> int:
    """List a waiting run's open decisions, or answer some of them and continue the run in this process."""
    import asyncio

    from emvoox.agents import AgentError
    from emvoox.engine.orchestrator import Engine, report
    from emvoox.repositories import get_repositories

    try:
        engine = Engine.restore(get_repositories(), a.series)
    except AgentError as e:
        return _out({"ok": False, "error": str(e)}, ok=False)
    st = engine.state
    if st.status != "waiting":
        return _out({"ok": False, "error": f"run {st.run_id} is not waiting for a decision (status: {st.status})"}, ok=False)
    if not (a.approve or a.reject):
        for d in st.pending:
            print(f"{d.id}  {d.kind:<15} {d.message}", file=sys.stderr)
        return _out({"ok": True, "run_id": st.run_id, "status": st.status, "pending": [d.model_dump(mode="json") for d in st.pending]})
    if not a.reviewer:
        return _out({"ok": False, "error": "--reviewer is required to answer a decision"}, ok=False)
    chosen = [d for d in st.pending if (a.all or d.id == a.id or (a.budget and d.kind == "budget")
                                        or (a.scene and d.scene_id == a.scene and (a.episode is None or d.episode == a.episode)))]
    if not chosen:
        return _out({"ok": False, "error": "no open decision matches; run 'decide --series ...' to list them"}, ok=False)
    answer = {"approved": bool(a.approve), "reviewer": a.reviewer, "notes": a.notes, "unit_ids": [u for u in a.units.split(",") if u]}
    if a.max_cost:
        answer["max_cost_usd"] = a.max_cost
    return report(asyncio.run(engine.run({d.id: answer for d in chosen})))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "run":
        return cmd_run(argv[1:])
    ap = argparse.ArgumentParser(prog="python -m emvoox", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sv = sub.add_parser("serve", help="API + web app")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8765)
    sub.add_parser("worker", help="run queued jobs until interrupted (needs EMVOOX_QUEUE=redis)")
    sub.add_parser("run", help="run the pipeline (see: python -m emvoox run --help)")
    rs = sub.add_parser("research", help="Market Research Agent only: produce a TrendBrief")
    rs.add_argument("--seeds", default="", help="trend notes (text, or a .md/.txt file)")
    rs.add_argument("--browser", action="store_true")
    rs.add_argument("--focus", default="")
    rs.add_argument("--guide", default="", help="what the agent should look for")
    rs.add_argument("--platforms", default="", help="comma-separated: dramabox,reelshort,tiktok,google,youtube (default: all)")
    rs.add_argument("--llm", default=None)
    rs.add_argument("--llm-model", default=None)
    rs.add_argument("--agent", action="store_true", help="tool loop: the model decides what to read and search, then writes the brief")
    for name in ("approve", "reject"):
        g = sub.add_parser(name, help=f"{name} an episode at the human gate")
        g.add_argument("--series", required=True)
        g.add_argument("--episode", type=int, required=True)
        g.add_argument("--reviewer", required=True)
        g.add_argument("--notes", default="")
        if name == "reject":
            g.add_argument("--lines", default="")
    dd = sub.add_parser("decide", help="list or answer what a paused run is waiting for (scene approvals, budget)")
    dd.add_argument("--series", required=True)
    dd.add_argument("--id", default=None, help="one decision by id")
    dd.add_argument("--scene", default=None, help="a scene approval, e.g. sc01")
    dd.add_argument("--episode", type=int, default=None)
    dd.add_argument("--budget", action="store_true", help="the budget decision")
    dd.add_argument("--all", action="store_true", help="every open decision")
    verdict = dd.add_mutually_exclusive_group()
    verdict.add_argument("--approve", action="store_true")
    verdict.add_argument("--reject", action="store_true")
    dd.add_argument("--reviewer", default="")
    dd.add_argument("--notes", default="")
    dd.add_argument("--units", default="", help="rejecting a scene: render units to redo, comma-separated (default: the whole scene)")
    dd.add_argument("--max-cost", type=float, default=None, help="approving the budget decision: the new cap in USD")
    sub.add_parser("voices", help="list Voice IPs")
    pv = sub.add_parser("plug-voice", help="plug a (cloned) voice into a Voice IP; the next run uses it")
    pv.add_argument("--actor", required=True)
    pv.add_argument("--provider", required=True, choices=["elevenlabs", "wavespeed", "gemini"])
    pv.add_argument("--voice-id", required=True)
    pv.add_argument("--model", default=None)
    pv.add_argument("--label", default=None)
    pv.add_argument("--url", default=None)
    pv.add_argument("--source", default="cloned", choices=["cloned", "library", "premade", "prebuilt"])
    pv.add_argument("--not-preferred", action="store_true", help="add the voice without making this engine the actor's preferred one")
    pv.add_argument("--unlock", action="store_true", help="allow replacing a locked voice on the same engine")
    dc = sub.add_parser("doctor", help="environment and key checks")
    dc.add_argument("--live", action="store_true", help="also call the vendors (cheap GETs, no generation)")
    sub.add_parser("agents", help="list the agent fleet")
    a = ap.parse_args(argv)
    return {
        "serve": cmd_serve, "worker": cmd_worker, "research": cmd_research, "decide": cmd_decide,
        "approve": lambda x: cmd_gate(x, "approve"), "reject": lambda x: cmd_gate(x, "reject"),
        "voices": cmd_voices, "plug-voice": cmd_plug, "doctor": cmd_doctor, "agents": cmd_agents,
    }[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
