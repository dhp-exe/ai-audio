"""Core tools: always available, and carried out by the runtime itself rather than by a function here.

They are registered like any other tool so the model sees one consistent list, and so their arguments are
validated the same way. The functions below are never called: ``emvoox/runtime/loop.py`` intercepts these names.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from emvoox.tools.base import ToolContext, ToolError, tool


class LoadToolsArgs(BaseModel):
    area: str = Field(description="The tool area to load, as listed in your instructions.")


class AskUserArgs(BaseModel):
    question: str = Field(description="One clear question for the person you are working for.")
    options: list[str] = Field(default_factory=list, description="Up to five short answers to choose from; leave empty for a free answer.")


class SpawnSubagentArgs(BaseModel):
    agent: str = Field(description="Id of the specialist agent to hand the task to.")
    task: str = Field(description="What the specialist must do, with everything it needs to know; it does not see this conversation.")


def _runtime_only(_ctx: ToolContext, _args: BaseModel):  # pragma: no cover - the loop intercepts core tools
    raise ToolError("this tool is carried out by the runtime")


@tool("load_tools", area="core", kind="core", description="Load one more area of tools so you can call them in your next turn. "
      "Only areas named in your instructions can be loaded.")
def load_tools(ctx: ToolContext, args: LoadToolsArgs):
    return _runtime_only(ctx, args)


@tool("ask_user", area="core", kind="core", description="Ask the person a question and wait for the answer. Use it only when a decision is "
      "theirs to make or you are missing something only they know.")
def ask_user(ctx: ToolContext, args: AskUserArgs):
    return _runtime_only(ctx, args)


@tool("spawn_subagent", area="core", kind="core", description="Hand a self-contained task to a specialist agent and get its result back.")
def spawn_subagent(ctx: ToolContext, args: SpawnSubagentArgs):
    return _runtime_only(ctx, args)
