"""The Phase-1 audio agent fleet, in pipeline order."""

from emvoox.agents.base import Agent, AgentContext, AgentError, Skill
from emvoox.agents.casting import CastingAgent
from emvoox.agents.director import DirectorAgent
from emvoox.agents.market_research import MarketResearchAgent
from emvoox.agents.publisher import PublisherAgent
from emvoox.agents.qa_critic import QACriticAgent
from emvoox.agents.script_writer import ScriptWriterAgent
from emvoox.agents.sound_engineer import SoundEngineerAgent

FLEET: tuple[Agent, ...] = (
    MarketResearchAgent(), ScriptWriterAgent(), CastingAgent(), DirectorAgent(), SoundEngineerAgent(), QACriticAgent(), PublisherAgent(),
)


def fleet() -> list[dict]:
    return [a.describe() for a in FLEET]


__all__ = ["FLEET", "Agent", "AgentContext", "AgentError", "CastingAgent", "DirectorAgent", "MarketResearchAgent", "PublisherAgent",
           "QACriticAgent", "ScriptWriterAgent", "Skill", "SoundEngineerAgent", "fleet"]
