"""Script Writer Agent contracts on top of the story/bible models in ``production``."""

from __future__ import annotations

from pydantic import BaseModel, Field

from emvoox.contracts.production import SeriesBible, StoryInput, StoryRole

# Emvoox Anti-Trope rules. Sent to the Script Writer in Vietnamese and checked by Cliffhanger Check.
ANTI_TROPE_RULES_VI: tuple[str, ...] = (
    "Mỗi nhân vật có mục tiêu và động cơ RIÊNG, độc lập với nhân vật chính; không ai tồn tại chỉ để làm nền.",
    "Bước ngoặt đầu tiên phải xuất hiện trong 30 giây đầu của mỗi tập (khoảng 100 từ thoại đầu).",
    "Phản diện thông minh: có lý do hành động hợp lý, đi trước nhân vật chính ít nhất một bước, không tự để lộ sơ hở ngớ ngẩn.",
    "Kết quả đến từ lựa chọn và hành động có cơ sở; bằng chứng và bước ngoặt được cài cắm trước, không dùng trùng hợp ngẫu nhiên.",
    "Quyết định quan trọng phải tạo ra hậu quả; phần kết giải quyết xung đột chính đã đặt ra.",
    "Làm mới mô-típ quen thuộc bằng động cơ, lựa chọn và hậu quả hợp lý thay vì lặp lại khuôn mẫu.",
)


class StoryAdaptation(BaseModel):
    """Structured output of the Story Adapt skill: a TrendBrief turned into a writable story."""

    title: str
    genre: str
    setting: str
    roles: list[StoryRole] = Field(min_length=2, max_length=6)
    treatment: str = Field(min_length=200, description="The whole story as a detailed treatment, act by act, with the turning points.")


class CliffhangerCheck(BaseModel):
    """Cliffhanger Check skill output for one drafted episode."""

    episode_number: int = Field(ge=1, le=99)
    hook_score: int = Field(ge=1, le=10, description="How strongly the last line makes a listener start the next episode.")
    twist_within_30s: bool = Field(description="A turn or reveal lands within the first ~30 seconds.")
    antagonist_is_smart: bool = True
    independent_motivations: bool = True
    issues: list[str] = Field(default_factory=list)
    suggestion: str = Field("", description="Concrete rewrite note when the score is low; empty otherwise.")
    checked_by: str = Field("llm", description="'llm' or 'rules' (deterministic fallback).")
    passed: bool = True


class ScriptPackage(BaseModel):
    """Script Writer Agent output for the series step: ``StoryInput`` + ``SeriesBible``."""

    story: StoryInput
    bible: SeriesBible
    outline_reused: bool = False
    adapted_from_brief: str | None = None


class EpisodeDraftResult(BaseModel):
    """Script Writer Agent output for one episode: the raw screenplay and its hook score."""

    series_id: str
    episode_number: int = Field(ge=1, le=99)
    raw_script: str = Field(min_length=20)
    words: int = Field(ge=1)
    scenes: int = Field(ge=1)
    estimated_duration_sec: int = Field(ge=1)
    cliffhanger: CliffhangerCheck | None = None
    reused: bool = False
    rewrites: int = 0
