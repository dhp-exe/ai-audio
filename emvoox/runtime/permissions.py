"""The permission gate: what happens to one tool call before anything runs.

    refuse     the call cannot run; the model is told why and may do something else
    ask        the call waits for a person (the session pauses)
    allow      the call runs

Rules, in order:
1. The tool must exist and be loaded for this agent (its area is one of the agent's, or was loaded on demand).
2. The arguments must satisfy the tool's Pydantic model.
3. ``external`` tools (money, publishing) always wait for a person. ``write`` tools wait in manual mode.
4. A session that has read text from outside (a web page), itself or through a specialist it handed work to,
   may not widen its own tools: ``load_tools`` is refused from then on. Whatever a page says, the agent keeps
   the tools it had, and the ones that spend money still wait for a person (rule 3).
5. A session that nobody is watching (a sub-agent, a background scan) cannot wait: a call that would need a
   person is refused instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ValidationError

from emvoox.contracts.agentic import AgentSession, AgentSpec, ToolCall
from emvoox.tools.base import Tool, ToolRegistry


@dataclass
class Verdict:
    action: Literal["allow", "ask", "refuse"]
    reason: str = ""
    tool: Tool | None = None
    args: BaseModel | None = None


def available(spec: AgentSpec, session: AgentSession, registry: ToolRegistry) -> list[Tool]:
    """The tools this session may call right now: its core tools plus every loaded area."""
    core = [t for t in (registry.get(name) for name in spec.core) if t is not None]
    areas = list(dict.fromkeys([*spec.areas, *session.loaded]))
    return core + [t for area in areas for t in registry.in_area(area)]


def check(call: ToolCall, spec: AgentSpec, session: AgentSession, registry: ToolRegistry, *, interactive: bool) -> Verdict:
    tools = {t.name: t for t in available(spec, session, registry)}
    tool = tools.get(call.name)
    if tool is None:
        known = registry.get(call.name)
        hint = f" It is in the '{known.area}' area; load it with load_tools first." if known and known.area in spec.loadable else ""
        return Verdict("refuse", f"'{call.name}' is not one of your tools.{hint} Your tools: {', '.join(sorted(tools))}.")
    if call.error:
        return Verdict("refuse", call.error, tool)
    try:
        args = tool.args.model_validate(call.args)
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(str(x) for x in err['loc']) or 'arguments'}: {err['msg']}" for err in e.errors()[:6])
        return Verdict("refuse", f"invalid arguments for {call.name}: {problems}", tool)
    if session.tainted and call.name == "load_tools":
        return Verdict("refuse", "load_tools is not available after reading outside content in this task; finish with the tools you have", tool, args)
    if call.name == "load_tools" and getattr(args, "area", None) not in spec.loadable:
        return Verdict("refuse", f"you may load: {', '.join(spec.loadable) or 'no further areas'}", tool, args)
    needs_person = call.name == "ask_user" or tool.kind == "external" or (tool.kind == "write" and session.mode == "manual")
    if needs_person and not interactive:
        return Verdict("refuse", f"{call.name} needs a person's decision and nobody is following this task; continue without it", tool, args)
    return Verdict("ask" if needs_person else "allow", "", tool, args)
