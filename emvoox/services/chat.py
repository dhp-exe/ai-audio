"""The chat: a thread is one conversation with the Producer agent, carried out turn by turn by workers.

    create_thread / post_message / answer   save what the person said and queue a chat job (the API calls these)
    run_chat_turn                           a worker advances the Producer's session until it answers or needs the person
    thread_view                             what the client shows: messages, tool activity, open questions and approvals,
                                            and the production runs this thread started, with their own open decisions

The Producer's session is an ``AgentSession`` with the thread's id. Every step of a turn is appended to the
thread's event log, which the client reads while the turn runs.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

from emvoox.config import get_settings
from emvoox.contracts.agentic import AgentSession, ChatMessage
from emvoox.contracts.chat import ChatThread
from emvoox.contracts.jobs import Job
from emvoox.providers.llm import LlmClient, LlmProvider, get_llm_provider
from emvoox.repositories import Repositories, now_iso
from emvoox.runtime import new_session, run_session
from emvoox.services import library
from emvoox.telemetry.ledger import Ledger

AGENT = "producer"


class ChatError(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def _job(repos: Repositories, thread_id: str, answers: dict | None = None) -> Job:
    return Job(kind="chat", tenant=repos.tenant, run_id=thread_id, payload={"thread_id": thread_id, "answers": answers or {}})


def _title(text: str) -> str:
    line = " ".join(text.split())
    return line[:60] + ("…" if len(line) > 60 else "")


def create_thread(repos: Repositories, text: str, submit: Callable[[Job], Any], *, user: str = "", mode: str = "auto") -> ChatThread:
    text = text.strip()
    if not text:
        raise ChatError("write a message to start a conversation", 422)
    thread_id = f"th-{uuid.uuid4().hex[:12]}"
    thread = ChatThread(id=thread_id, title=_title(text), user=user, status="running", session_id=thread_id, preview=_title(text), created_at=now_iso())
    session = new_session(AGENT, session_id=thread_id, mode=mode)
    session.messages.append(ChatMessage(role="user", content=text, at=now_iso()))
    repos.sessions.save(session)
    repos.chat.save(thread)
    repos.chat.append_event(thread_id, "user.message", {"text": text})
    submit(_job(repos, thread_id))
    return thread


def _load(repos: Repositories, thread_id: str) -> tuple[ChatThread, AgentSession]:
    thread = repos.chat.load(thread_id)
    session = repos.sessions.load(thread_id) if thread else None
    if thread is None or session is None:
        raise ChatError("no such conversation", 404)
    return thread, session


def post_message(repos: Repositories, thread_id: str, text: str, submit: Callable[[Job], Any]) -> ChatThread:
    """A new message from the person. If the agent was waiting for them, the message is their answer: it answers an
    open question, and it declines an approval it was asked for (they said something else instead of approving)."""
    thread, session = _load(repos, thread_id)
    text = text.strip()
    if not text:
        raise ChatError("the message is empty", 422)
    if thread.status == "running":
        raise ChatError("the Producer is still working on your last message")
    repos.chat.append_event(thread_id, "user.message", {"text": text})
    answers: dict = {}
    if session.pending:
        answers = {p.id: ({"answer": text} if p.kind == "question" else {"approved": False, "notes": text}) for p in session.pending}
    else:
        session.messages.append(ChatMessage(role="user", content=text, at=now_iso()))
        if session.status in ("done", "stopped", "failed"):
            session.status, session.steps, session.stop_reason, session.error = "idle", 0, "", None  # a new task: its own step budget
        repos.sessions.save(session)
    thread.status, thread.preview, thread.error = "running", _title(text), None
    repos.chat.save(thread)
    submit(_job(repos, thread_id, answers))
    return thread


def answer(repos: Repositories, thread_id: str, answers: dict[str, dict], submit: Callable[[Job], Any]) -> ChatThread:
    """Answers to the agent's open questions and approval requests: {pending id: {answer} | {approved, notes, reviewer}}."""
    thread, session = _load(repos, thread_id)
    open_ids = {p.id for p in session.pending}
    unknown = sorted(set(answers) - open_ids)
    if not answers or unknown:
        raise ChatError(f"not an open question or approval of this conversation: {unknown or 'nothing was answered'}", 422)
    if thread.status == "running":
        raise ChatError("the Producer is still working")
    thread.status = "running"
    repos.chat.save(thread)
    submit(_job(repos, thread_id, answers))
    return thread


def run_chat_turn(repos: Repositories, payload: dict, llm: LlmProvider | None = None, queue=None) -> AgentSession | None:
    """One job: advance the Producer until it has answered, or needs the person. Never raises; a failure is the thread's state."""
    thread = repos.chat.load(payload.get("thread_id") or "")
    session = repos.sessions.load(thread.id) if thread else None
    if thread is None or session is None:
        return None
    s = get_settings()
    ledger = Ledger(repos.telemetry)
    client = LlmClient(llm or get_llm_provider(s.llm_provider), ledger)

    def emit(event: str, **data) -> None:
        repos.chat.append_event(thread.id, event, data)
        if event in ("tool.result", "agent.text", "agent.asked"):
            repos.sessions.save(session)  # the view shows the conversation as it grows

    def submit(job: Job) -> Any:
        if queue is None:
            raise RuntimeError("no queue to start a production run on")
        return queue.enqueue(job)

    try:
        from emvoox.runtime.context import before_model, memory_context

        run_session(session, repos, client, ledger, answers=payload.get("answers") or None, interactive=True, user=thread.user, submit=submit, emit=emit,
                    context=lambda ses: memory_context(repos, ses), before_model=lambda ses: before_model(repos, client, ses))
    except Exception as e:  # noqa: BLE001
        session.status, session.error = "failed", f"{type(e).__name__}: {str(e)[:300]}"
        repos.chat.append_event(thread.id, "turn.failed", {"error": session.error})
    repos.sessions.save(session)
    thread.status = "waiting" if session.status == "waiting" else "failed" if session.status == "failed" else "idle"
    thread.error = session.error or (session.stop_reason if session.status == "stopped" else None)
    last = next((m.content for m in reversed(session.messages) if m.role == "assistant" and m.content), "")
    thread.preview = _title(last) if last else thread.preview
    repos.chat.save(thread)
    return session


# ---------------------------------------------------------------------- what the client shows


def _parse(content: str) -> Any:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return content


def thread_view(repos: Repositories, thread_id: str) -> dict:
    thread, session = _load(repos, thread_id)
    results = {m.tool_call_id: m for m in session.messages if m.role == "tool"}
    pending = {p.id: p for p in session.pending}
    items: list[dict] = []
    for m in session.messages:
        if m.role == "user":
            items.append({"kind": "user", "text": m.content, "at": m.at})
        elif m.role == "assistant":
            if m.content:
                items.append({"kind": "assistant", "text": m.content, "at": m.at})
            for c in m.tool_calls:
                r = results.get(c.id)
                out = _parse(r.content) if r else None
                failed = isinstance(out, dict) and "error" in out
                item = {"kind": "tool", "id": c.id, "tool": c.name, "args": c.args, "at": m.at,
                        "status": "waiting" if c.id in pending else "failed" if failed else "done" if r else "running",
                        "result": out if not isinstance(out, dict) or len(json.dumps(out, ensure_ascii=False)) < 2000 else {"summary": str(out)[:600] + "…"}}
                if c.id in pending:
                    p = pending[c.id]
                    item["pending"] = {"id": p.id, "kind": p.kind, "message": p.message, "options": p.options, "asked_at": p.asked_at}
                items.append(item)
    runs = []
    for ref in session.data.get("runs") or []:
        raw = repos.runs.load_raw(ref["series_id"])
        if not raw:
            continue
        mine = raw.get("run_id") == ref["run_id"]
        title = (repos.docs.get(f"series/{ref['series_id']}/series.json") or {}).get("title") or ref["series_id"]
        decisions = []
        for d in (raw.get("pending") or []) if mine and raw.get("status") == "waiting" else []:
            item = {**d, "run_id": raw["run_id"], "series_id": ref["series_id"], "series_title": title}
            if d.get("kind") == "scene_approval":
                item["scene"] = library.scene_detail(repos, ref["series_id"], d["episode"], d["scene_id"])
            decisions.append(item)
        steps = raw.get("steps") or []
        runs.append({"series_id": ref["series_id"], "run_id": raw.get("run_id"), "title": title, "status": raw.get("status"), "error": raw.get("error"),
                     "cost_usd": (raw.get("totals") or {}).get("cost_usd", 0), "budget_usd": raw.get("budget_usd"),
                     "progress": {"done": sum(1 for s in steps if s.get("status") in ("done", "warn", "approved", "waiting", "skipped")), "total": len(steps)},
                     "current": next((s.get("label") for s in steps if s.get("status") == "running"), None), "decisions": decisions,
                     "episodes": [i for i in library.approvals(repos) if i["series_id"] == ref["series_id"]]})
    return {"thread": thread.model_dump(mode="json"), "items": items, "runs": runs,
            "usage": {"steps": session.steps, "cost_usd": session.cost_usd, "tokens_in": session.tokens_in, "tokens_out": session.tokens_out},
            "summary": session.summary}
