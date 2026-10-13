"""Running the Market Research Agent on its own, as a job (the Market research page, the chat)."""

from __future__ import annotations

from emvoox.agents import AgentContext, MarketResearchAgent
from emvoox.agents.market_research import ScanRecorder
from emvoox.config import get_settings
from emvoox.contracts.agentic import AgentSession, ChatMessage
from emvoox.contracts.run import ResearchParams, RunParams
from emvoox.providers.llm import LlmClient, LlmProvider, get_llm_provider
from emvoox.repositories import Repositories, now_iso
from emvoox.runtime import new_session, run_session
from emvoox.runtime.agents import finish_session
from emvoox.telemetry.ledger import Ledger

DEFAULT_GUIDE_VI = "Tìm 3 thể loại phim ngắn đang thịnh hành nhất với khán giả Việt và hướng truyện mới cho từng thể loại."


def run_scan(repos: Repositories, payload: dict, llm: LlmProvider | None = None) -> None:
    """``payload`` = {scan_id, llm_provider, seeds, platforms, use_browser, focus, guide, agent}. The agent records its
    progress, and a failure, in the scan document the client polls; nothing is raised. ``agent: true`` runs the
    tool loop (the model decides what to read and search); otherwise the four skills run in their fixed order."""
    if payload.get("agent"):
        run_agent_scan(repos, payload, llm=llm)
        return
    s = get_settings()
    ledger = Ledger(repos.telemetry)
    provider = llm or get_llm_provider(payload.get("llm_provider") or s.llm_provider)
    ctx = AgentContext(settings=s, repos=repos, llm=LlmClient(provider, ledger), ledger=ledger,
                       params=RunParams(series_id="research", tts_provider="mock"))  # research renders no audio
    params = ResearchParams(**{k: payload[k] for k in ("seeds", "platforms", "use_browser", "focus", "guide") if k in payload})
    try:
        MarketResearchAgent().run(ctx, params, scan_id=payload.get("scan_id"))
    except Exception:  # noqa: BLE001 - recorded in the scan document
        pass


def run_agent_scan(repos: Repositories, payload: dict, llm: LlmProvider | None = None) -> AgentSession:
    """Market research as a tool loop. The session is saved next to the scan (same id), so what the agent called
    and why can be read afterwards."""
    s = get_settings()
    ledger = Ledger(repos.telemetry)
    provider = llm or get_llm_provider(payload.get("llm_provider") or s.llm_provider)
    client = LlmClient(provider, ledger, model=payload.get("llm_model"))
    params = ResearchParams(**{k: payload[k] for k in ("seeds", "platforms", "use_browser", "focus", "guide") if k in payload})
    use_browser = s.research_use_browser if params.use_browser is None else params.use_browser
    ctx = AgentContext(settings=s, repos=repos, llm=client, ledger=ledger, params=RunParams(series_id="research", tts_provider="mock"))
    rec = ScanRecorder(ctx, params, use_browser, payload.get("scan_id"))
    rec.state.mode = "agent"
    rec.phase("plan", f"agent loop: {client.model} decides what to read")
    session = new_session("market_research", session_id=rec.state.scan_id,
                          data={"scan_id": rec.state.scan_id, "research": {**params.model_dump(), "use_browser": use_browser}})
    session.messages.append(ChatMessage(role="user", at=now_iso(), content=(
        f"Hướng dẫn nghiên cứu: {params.guide.strip() or DEFAULT_GUIDE_VI}\nTrọng tâm biên tập: {params.focus or '(không có)'}\n"
        f"Nền tảng được chọn: {', '.join(params.platforms) or 'tất cả'}\nTrình duyệt: {'bật' if use_browser else 'tắt (chỉ dùng ghi chú)'}")))

    def emit(event: str, **data) -> None:
        if event not in ("tool.called", "tool.refused", "agent.finished"):
            return
        state = repos.research.load_scan(rec.state.scan_id) or rec.state  # the tools write to the scan too: append to what is there
        if event == "tool.called":
            line = f"agent: {data['tool']}({', '.join(f'{k}={v!r}' for k, v in (data.get('args') or {}).items())})"
        elif event == "tool.refused":
            line = f"agent: {data['tool']} refused: {data['reason'][:160]}"
        else:
            line = f"agent: {data['status']}" + (f" ({data['reason']})" if data.get("reason") else "")
        ScanRecorder.attach(ctx, state).log(line)

    try:
        run_session(session, repos, client, ledger, interactive=False, emit=emit)
    except Exception as e:  # noqa: BLE001 - recorded in the scan document
        session.status, session.error = "failed", f"{type(e).__name__}: {str(e)[:300]}"
    finish_session(repos, session)
    repos.sessions.save(session)
    return session
