"""The tool registry: what the agents' models may call (docs/TARGET_ARCHITECTURE.md §4.3).

    base.py         Tool, ToolContext, ToolError, the ``@tool`` decorator and the registry
    core.py         load_tools, ask_user, spawn_subagent (the runtime carries them out)
    research.py     reading trend notes and platform pages, searching, writing the TrendBrief
    library.py      reading what the studio already has: series, briefs, Voice IPs, runs
    production.py   starting and following a production run (spends money: always needs approval)
"""

from emvoox.tools.base import REGISTRY, Tool, ToolContext, ToolError, ToolRegistry, load_builtin_tools, tool

__all__ = ["REGISTRY", "Tool", "ToolContext", "ToolError", "ToolRegistry", "load_builtin_tools", "tool"]
