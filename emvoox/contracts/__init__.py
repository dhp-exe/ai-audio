"""Pydantic v2 payloads exchanged between agents. One import point for the whole fleet.

    Market Research  -> TrendBrief
    Script Writer    -> ScriptPackage (StoryInput + SeriesBible), EpisodeDraftResult (+ CliffhangerCheck)
    Casting          -> ResolvedCast (+ EnginePolicy)
    AI Director      -> DirectedConversationUnits
    Sound Engineer   -> MasteredEpisode
    QA Critic        -> QAReport
    Publisher / gate -> ReleasePackage
"""

from emvoox.contracts.audio import LoudnessMetrics, MasteredEpisode, StemRecord, VoiceRenderResult
from emvoox.contracts.cast import CastingAssignment, CastingProposal, CastMember, EnginePolicy, EngineRef, ResolvedCast
from emvoox.contracts.direction import ConversationUnit, DirectedConversationUnits, RenderUnit
from emvoox.contracts.market import (
    ContentInsight,
    FormatSpec,
    MarketAnalysis,
    MarketObservation,
    ThemeCategory,
    TrendBrief,
    TrendCandidate,
)
from emvoox.contracts.production import (
    APPROVED_AUDIO_TAGS,
    PROTAGONIST_ALIAS,
    CharacterProfile,
    Emotion,
    EpisodeDraft,
    EpisodeFormat,
    EpisodePlan,
    EpisodeScript,
    Line,
    LineType,
    NewCharacter,
    ProviderVoice,
    RoleCast,
    Scene,
    SeriesBible,
    SeriesOutline,
    StoryInput,
    StoryOverview,
    StoryRole,
    Timeline,
    TimelineClip,
    VoiceRegistry,
    slugify_id,
)
from emvoox.contracts.qa import HumanVerdict, QAIssue, QAReport, RetryInstruction
from emvoox.contracts.release import ApprovalDecision, ExportedFile, PublishMetadata, ReleasePackage
from emvoox.contracts.run import PipelineEvent, ResearchParams, RunParams, RunState, RunTotals, StepState
from emvoox.contracts.script import CliffhangerCheck, EpisodeDraftResult, ScriptPackage, StoryAdaptation
from emvoox.contracts.telemetry import UsageRecord

__all__ = [
    "APPROVED_AUDIO_TAGS", "PROTAGONIST_ALIAS", "ApprovalDecision", "CastMember", "CastingAssignment", "CastingProposal",
    "CharacterProfile", "CliffhangerCheck", "ContentInsight", "ConversationUnit", "DirectedConversationUnits", "Emotion",
    "EnginePolicy", "EngineRef", "EpisodeDraft", "EpisodeDraftResult", "EpisodeFormat", "EpisodePlan", "EpisodeScript",
    "ExportedFile", "FormatSpec", "HumanVerdict", "Line", "LineType", "LoudnessMetrics", "MarketAnalysis", "MarketObservation",
    "MasteredEpisode", "NewCharacter", "PipelineEvent", "ProviderVoice", "PublishMetadata", "QAIssue", "QAReport",
    "ReleasePackage", "RenderUnit", "ResearchParams", "ResolvedCast", "RetryInstruction", "RoleCast", "RunParams", "RunState",
    "RunTotals", "Scene", "ScriptPackage", "SeriesBible", "SeriesOutline", "StemRecord", "StepState", "StoryAdaptation",
    "StoryInput", "StoryOverview", "StoryRole", "ThemeCategory", "Timeline", "TimelineClip", "TrendBrief", "TrendCandidate",
    "UsageRecord", "VoiceRegistry", "VoiceRenderResult", "slugify_id",
]
