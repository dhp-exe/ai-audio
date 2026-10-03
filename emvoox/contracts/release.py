"""Human Approval Gate & Publisher contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

GateState = Literal["awaiting_approval", "needs_review", "approved", "rejected"]


class PublishMetadata(BaseModel):
    """Metadata for a YouTube upload (title, tags, description). Editable at the gate."""

    title: str = Field(min_length=1, max_length=100)
    description: str = Field(max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=30)
    hashtags: list[str] = Field(default_factory=list, max_length=10)
    playlist_title: str = ""
    thumbnail_text: str = Field("", description="Short text for the thumbnail (one situation, clear character, few words).")
    language: str = "vi"
    category: str = "Entertainment"
    made_for_kids: bool = False
    contains_synthetic_media: bool = Field(True, description="Platform AI-content disclosure: the voices are AI-generated.")
    generated_by: str = Field("rules", description="'llm' or 'rules'.")


class ApprovalDecision(BaseModel):
    decision: Literal["approved", "rejected"]
    reviewer: str
    notes: str = ""
    lines: list[str] = Field(default_factory=list, description="Lines the reviewer wants re-rendered (on reject).")
    override_flagged: bool = Field(False, description="True when a FLAGGED episode was approved anyway.")
    at: str


class ExportedFile(BaseModel):
    kind: Literal["mp3", "wav", "metadata"]
    path: str = Field(description="Storage key under outputs/approved_masters/.")
    bytes: int = 0


class ReleasePackage(BaseModel):
    """Gate state of one episode: what QA said, the metadata draft, the human decision, the export."""

    series_id: str
    episode_number: int = Field(ge=1, le=99)
    title: str = ""
    state: GateState
    qa_status: Literal["PASS", "FLAGGED"]
    qa_score: int = Field(ge=0, le=100)
    qa_attempts: int = 0
    reason: str = Field("", description="Why the episode is waiting for a human.")
    duration_ms: int = 0
    master_mp3: str = ""
    master_wav: str = ""
    metadata: PublishMetadata
    decision: ApprovalDecision | None = None
    exported: list[ExportedFile] = Field(default_factory=list)
    publish: dict = Field(default_factory=dict, description="Publishing mock-up receipt (platform, status, at).")
    created_at: str = ""
    updated_at: str = ""
