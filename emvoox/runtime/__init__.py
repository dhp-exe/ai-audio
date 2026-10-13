"""The agent runtime: one loop for every agent (docs/TARGET_ARCHITECTURE.md §4.2).

    agents.py        the agents as configuration (prompt, tool areas, model, budget)
    permissions.py   the gate every tool call passes: is it loaded, are the arguments valid, does it need a person
    loop.py          build context -> call the model -> gate -> run tools -> repeat, on a session that can pause

The workflow graph (``emvoox/workflow``) is where order is fixed and money is spent under guarantees. The runtime
is for work whose path is not known in advance; it reaches production only by calling a tool.
"""

from emvoox.runtime.agents import AGENTS, get_agent
from emvoox.runtime.loop import new_session, run_session

__all__ = ["AGENTS", "get_agent", "new_session", "run_session"]
