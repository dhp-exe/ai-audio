"""The agent loop: build context -> call the model -> permission gate -> run tools -> repeat.

It runs on an ``AgentSession``, a document that is saved by the caller after every call of ``run_session``, so
the loop can stop wherever a person is needed and continue in another process:

    run_session(session, ...)                      work until done, stopped, or waiting
    run_session(session, ..., answers={id: ...})   continue a waiting session with the person's answers

A turn's tool calls are carried out in order. One that must wait for a person (``ask_user``, an ``external``
tool, a ``write`` tool in manual mode) is put in ``session.pending``; the model is not called again until every
call of that turn has a result, which is also what the vendors' APIs require.

Limits are checked before every model call: the step limit, the agent's budget (model calls plus what its tools
spent), and a cancel request. A session that hits one ends as ``stopped`` with the reason, never silently.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from emvoox.config import get_settings
from emvoox.contracts.agentic import AgentSession, AgentSpec, ChatMessage, PendingAction, ToolCall
from emvoox.contracts.jobs import Job
from emvoox.providers.llm import LlmClient, LlmError
from emvoox.repositories import Repositories, now_iso
from emvoox.runtime import permissions
from emvoox.runtime.agents import finish_session, get_agent
from emvoox.telemetry.ledger import Ledger
from emvoox.tools.base import Tool, ToolContext, ToolError, ToolRegistry, load_builtin_tools

MAX_RESULT_CHARS = 6000  # a tool result longer than this is cut in the conversation (tools keep large text elsewhere)
Emit = Callable[..., None]


def new_session(agent_id: str, *, session_id: str | None = None, mode: str = "auto", data: dict | None = None, parent_id: str | None = None) -> AgentSession:
    return AgentSession(id=session_id or f"ses-{uuid.uuid4().hex[:12]}", agent_id=agent_id, mode=mode, data=data or {}, parent_id=parent_id,  # type: ignore[arg-type]
                        created_at=now_iso(), updated_at=now_iso())


def system_prompt(spec: AgentSpec, session: AgentSession, registry: ToolRegistry, extra: str = "") -> str:
    parts = [spec.prompt.strip()]
    loadable = [a for a in spec.loadable if a not in session.loaded and a not in spec.areas]
    if loadable and "load_tools" in spec.core:
        lines = [f"- {area}: " + ", ".join(t.name for t in registry.in_area(area)) for area in loadable]
        parts.append("Nhóm tool có thể nạp thêm bằng load_tools(area):\n" + "\n".join(lines))
    if session.summary:
        parts.append("Tóm tắt phần hội thoại trước đó (đã được rút gọn):\n" + session.summary)
    if extra:
        parts.append(extra)
    return "\n\n".join(parts)


def _dump(result: Any) -> str:
    if isinstance(result, BaseModel):
        result = result.model_dump(mode="json")
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + f'... [cut: {len(text) - MAX_RESULT_CHARS} more characters]'
    return text


def _result(call: ToolCall, content: Any) -> ChatMessage:
    return ChatMessage(role="tool", tool_call_id=call.id, name=call.name, content=_dump(content), at=now_iso())


def run_session(session: AgentSession, repos: Repositories, llm: LlmClient, ledger: Ledger, *, answers: dict[str, dict] | None = None,
                spec: AgentSpec | None = None, registry: ToolRegistry | None = None, interactive: bool = True, user: str = "",
                submit: Callable[[Job], Any] | None = None, emit: Emit | None = None, cancel: threading.Event | None = None,
                log: Callable[[str], None] | None = None, context: Callable[[AgentSession], str] | None = None,
                before_model: Callable[[AgentSession], None] | None = None, depth: int = 0) -> AgentSession:
    """Advance ``session`` as far as it can go. The caller saves it afterwards (and may save it from ``emit``)."""
    spec = spec or get_agent(session.agent_id)
    registry = registry or load_builtin_tools()
    emit = emit or (lambda *_a, **_kw: None)
    cancel = cancel or threading.Event()
    log = log or (lambda _msg: None)
    mark = ledger.mark()
    ctx = ToolContext(settings=get_settings(), repos=repos, llm=llm, ledger=ledger, session=session, spec=spec, user=user, submit=submit, log=log,
                      emit=emit, cancel=cancel)

    def spent() -> float:
        return round(session.cost_usd + ledger.cost_since(mark), 6)

    def finish(status: str, reason: str = "", error: str | None = None) -> AgentSession:
        session.status, session.stop_reason, session.error = status, reason, error  # type: ignore[assignment]
        session.cost_usd = spent()
        session.updated_at = now_iso()
        emit("agent.finished" if status != "waiting" else "agent.waiting", agent=spec.id, status=status, reason=reason, pending=len(session.pending))
        return session

    def execute(call: ToolCall, tool: Tool, args: BaseModel) -> ChatMessage:
        """Run one allowed call. Core tools are carried out here; everything else is the tool's own function."""
        emit("tool.called", agent=spec.id, tool=call.name, args=call.args, call_id=call.id)
        t0 = time.time()
        try:
            if call.name == "load_tools":
                area = args.area  # type: ignore[attr-defined]
                if area not in session.loaded:
                    session.loaded.append(area)
                out: Any = {"loaded": area, "tools": [t.name for t in registry.in_area(area)]}
            elif call.name == "spawn_subagent":
                out = _spawn(args.agent, args.task)  # type: ignore[attr-defined]
            else:
                out = tool.fn(ctx, args)
                if tool.untrusted:
                    session.tainted = True
            ok = True
        except ToolError as e:
            out, ok = {"error": str(e)}, False
        except Exception as e:  # noqa: BLE001 - a broken tool is reported to the model, it does not end the task
            out, ok = {"error": f"{call.name} failed: {type(e).__name__}: {str(e)[:300]}"}, False
        msg = _result(call, out)
        # every tool call is in the audit ledger, next to the model calls that asked for it
        ledger.agent(agent=spec.id, skill=f"tool:{call.name}", elapsed_s=round(time.time() - t0, 2), ok=ok,
                     note=(str(out.get("error"))[:160] if not ok and isinstance(out, dict) else user))
        emit("tool.result", agent=spec.id, tool=call.name, ok=ok, call_id=call.id, result=msg.content[:600])
        return msg

    def _spawn(agent_id: str, task: str) -> dict:
        try:
            child_spec = get_agent(agent_id)
        except KeyError as e:
            raise ToolError(str(e)) from e
        if depth >= 1:
            raise ToolError("a specialist agent cannot hand work on to another agent")
        child = new_session(agent_id, mode="auto", parent_id=session.id, data={"task": task})
        child.messages.append(ChatMessage(role="user", content=task, at=now_iso()))
        emit("agent.spawned", agent=agent_id, parent=spec.id, session=child.id)
        run_session(child, repos, llm, ledger, spec=child_spec, registry=registry, interactive=False, user=user, submit=submit, emit=emit, cancel=cancel,
                    log=log, depth=depth + 1)
        finish_session(repos, child)
        repos.sessions.save(child)
        session.data.setdefault("children", []).append(child.id)
        session.tainted = session.tainted or child.tainted  # what the specialist read reaches this agent through its answer
        if child.status == "failed":
            raise ToolError(f"{agent_id} did not complete the task: {child.error or child.stop_reason or child.result}")
        return {"agent": agent_id, "status": child.status, "result": child.result or child.stop_reason or child.error or "",
                **{k: v for k, v in child.data.items() if k in ("brief_id", "scan_id")}}

    # ---- a person answered: give every answered call its result
    if session.pending:
        calls = {c.id: c for m in session.messages if m.role == "assistant" for c in m.tool_calls}
        for p in list(session.pending):
            answer = (answers or {}).get(p.id)
            if answer is None:
                continue
            call = calls[p.id]
            session.pending.remove(p)
            if p.kind == "question":
                session.messages.append(_result(call, {"answer": str(answer.get("answer") or answer.get("notes") or "")}))
            elif answer.get("approved"):
                verdict = permissions.check(call, spec, session, registry, interactive=True)
                runnable = verdict.action != "refuse" and verdict.tool is not None and verdict.args is not None
                session.messages.append(execute(call, verdict.tool, verdict.args) if runnable else _result(call, {"error": verdict.reason}))  # type: ignore[arg-type]
            else:
                why = str(answer.get("notes") or "").strip()
                session.messages.append(_result(call, {"error": f"the person did not approve this call{': ' + why if why else ''}. "
                                                                "Do not repeat it; ask what they want instead."}))
            emit("agent.answered", agent=spec.id, call_id=p.id, approved=bool(answer.get("approved", True)))
        if session.pending:
            return finish("waiting")
    elif answers:
        return finish(session.status if session.status in ("done", "stopped", "failed") else "idle")

    session.status = "running"
    while True:
        if cancel.is_set():
            return finish("stopped", "cancelled")
        if session.steps >= spec.max_steps:
            return finish("stopped", f"step limit reached ({spec.max_steps} model turns)")
        if spec.max_cost_usd is not None and spent() >= spec.max_cost_usd:
            return finish("stopped", f"budget reached (${spent():.4f} of ${spec.max_cost_usd:.2f})")
        if before_model:
            before_model(session)
        tools = permissions.available(spec, session, registry)
        try:
            reply = llm.chat(agent=spec.id, system=system_prompt(spec, session, registry, context(session) if context else ""),
                             messages=session.messages, tools=[t.spec() for t in tools], model=spec.model,
                             context={"agent": spec.id, "session": session.data, "tools": [t.name for t in tools]})
        except LlmError as e:
            return finish("failed", error=f"{type(e).__name__}: {str(e)[:300]}")
        session.steps += 1
        usage = llm.last_usage
        if usage:
            session.tokens_in += usage.prompt_tokens
            session.tokens_out += usage.output_tokens + usage.thinking_tokens
        session.messages.append(ChatMessage(role="assistant", content=reply.text, tool_calls=reply.tool_calls, provider_data=reply.provider_data, at=now_iso()))
        if reply.text:
            emit("agent.text", agent=spec.id, text=reply.text)
        if not reply.tool_calls:
            session.result = reply.text
            return finish("done")
        for call in reply.tool_calls:
            verdict = permissions.check(call, spec, session, registry, interactive=interactive)
            if verdict.action == "refuse":
                session.messages.append(_result(call, {"error": verdict.reason}))
                emit("tool.refused", agent=spec.id, tool=call.name, reason=verdict.reason, call_id=call.id)
            elif verdict.action == "ask":
                question = call.name == "ask_user"
                session.pending.append(PendingAction(
                    id=call.id, kind="question" if question else "tool_approval", tool=call.name, args=call.args, asked_at=now_iso(),
                    message=str(call.args.get("question") or "") if question else f"{spec.title} wants to run {call.name}.",
                    options=[str(o) for o in (call.args.get("options") or [])][:5] if question else []))
                emit("agent.asked", agent=spec.id, tool=call.name, call_id=call.id)
            else:
                session.messages.append(execute(call, verdict.tool, verdict.args))  # type: ignore[arg-type]
        if session.pending:
            return finish("waiting")
