"""Human Approval Gate & Publisher.

Skills
    Approval Gate      park every QA'd episode for a human: PASS episodes wait for sign-off
                       (``awaiting_approval``), episodes still FLAGGED after the automatic retries wait
                       for a decision (``needs_review``). With ``auto_approve`` a PASS episode is
                       exported without waiting; a FLAGGED one never is.
    Publish Metadata   YouTube title, description, tags, playlist and thumbnail text (LLM, with a
                       rule-based fallback); editable at the gate before approval
    Local Export       on approval: copy the WAV and MP3 masters to outputs/approved_masters/<series>/,
                       write <ep>.youtube.json, and record a publishing mock-up receipt
                       (``ready_for_upload``; the YouTube upload itself is not wired in Prototype V1)
"""

from __future__ import annotations

from emvoox import paths
from emvoox.agents.base import Agent, AgentContext, AgentError, Skill
from emvoox.contracts.audio import MasteredEpisode
from emvoox.contracts.production import SeriesBible
from emvoox.contracts.qa import QAReport
from emvoox.contracts.release import ApprovalDecision, ExportedFile, PublishMetadata, ReleasePackage
from emvoox.providers.llm import LlmError
from emvoox.repositories import Repositories, now_iso

METADATA_SYSTEM = """Bạn viết metadata đăng YouTube cho kênh truyện audio Mặc Khải (by Emvoox).
Trả về PublishMetadata:
- title tối đa 90 ký tự: tên series | Tập N: tình huống chính. Không giật tít sai sự thật.
- description: 2-4 câu giới thiệu tập (không tiết lộ cliffhanger), một dòng "Nghe tập tiếp theo trong danh sách phát", và dòng công bố: "Giọng đọc trong video được tạo bằng AI."
- tags: 8-15 từ khoá tiếng Việt (thể loại, tuyến nội dung, "truyện audio", tên kênh). hashtags: 3-5, bắt đầu bằng #.
- playlist_title: tên series. thumbnail_text: tối đa 5 chữ, một tình huống rõ ràng.
- contains_synthetic_media = true. language = "vi". generated_by = "llm".
"""


def rule_metadata(bible: SeriesBible | None, n: int, title: str, logline: str) -> PublishMetadata:
    series = bible.title if bible else "Mặc Khải"
    genre = list(bible.genre) if bible else []
    full = f"{series} | Tập {n}: {title}" if title else f"{series} | Tập {n}"
    return PublishMetadata(
        title=full[:100], description=(f"{logline}\n\nNghe tập tiếp theo trong danh sách phát {series}.\n"
                                       "Giọng đọc trong video được tạo bằng AI. Truyện audio by Emvoox."),
        tags=[*genre[:5], "truyện audio", "truyện ngắn", "Mặc Khải", "Emvoox"], hashtags=["#truyenaudio", "#MacKhai", "#Emvoox"],
        playlist_title=series, thumbnail_text=(title or series)[:40], generated_by="rules")


class PublisherAgent(Agent):
    id = "publisher"
    title = "Human Approval Gate & Publisher"
    description = "Holds every episode for human sign-off, prepares YouTube metadata and exports approved masters."
    skills = (
        Skill("approval_gate", "Approval Gate", "PASS -> awaiting approval; FLAGGED after retries -> needs review. Nothing exports without a human."),
        Skill("publish_metadata", "Publish Metadata", "YouTube title, description, tags, playlist and thumbnail text; editable at the gate."),
        Skill("local_export", "Local Export", "Approved WAV/MP3 + metadata JSON to outputs/approved_masters/; publishing mock-up receipt."),
    )
    consumes = "QAReport + MasteredEpisode"
    produces = ReleasePackage

    # ---- skill: Publish Metadata
    def publish_metadata(self, ctx: AgentContext, n: int, title: str) -> PublishMetadata:
        bible = ctx.repos.series.load_bible(ctx.series_id)
        plan = bible.episodes[n - 1] if bible and len(bible.episodes) >= n else None
        logline = plan.logline if plan else ""
        user = (f"Series: {bible.title if bible else ctx.series_id}\nThể loại: {', '.join(bible.genre) if bible else ''}\n"
                f"Tiền đề: {bible.premise if bible else ''}\nTập {n}: {title}\nLogline: {logline}\n\nHãy trả về PublishMetadata.")
        try:
            return ctx.llm.structured(agent=self.id, skill="publish_metadata", system=METADATA_SYSTEM, user=user, schema=PublishMetadata, episode=n,
                                      temperature=0.5, context={"series_title": bible.title if bible else ctx.series_id, "episode": n, "title": title,
                                                                "logline": logline})
        except LlmError as e:
            ctx.log(f"ep{n:02d}: metadata by rules ({type(e).__name__})")
            return rule_metadata(bible, n, title, logline)

    # ---- skill: Approval Gate
    def approval_gate(self, ctx: AgentContext, mastered: MasteredEpisode | None, report: QAReport, *, exhausted: bool) -> ReleasePackage:
        n = report.episode_number
        title = mastered.title if mastered else f"Tập {n}"
        meta = self.publish_metadata(ctx, n, title)
        if report.status == "PASS":
            state, reason = "awaiting_approval", "QA passed; waiting for a human to listen and approve."
        else:
            codes = sorted({i.code for i in report.error_logs if i.severity != "minor"}) or ["score below the bar"]
            reason = (f"QA still FLAGGED after {report.attempt} automatic retr{'y' if report.attempt == 1 else 'ies'}: {', '.join(codes)}."
                      if exhausted else f"QA FLAGGED: {', '.join(codes)}.")
            state = "needs_review"
        pkg = ReleasePackage(series_id=ctx.series_id, episode_number=n, title=title, state=state, qa_status=report.status, qa_score=report.score,
                             qa_attempts=report.attempt, reason=reason, duration_ms=mastered.duration_ms if mastered else 0,
                             master_mp3=mastered.mp3_path if mastered else "", master_wav=mastered.wav_path if mastered else "",
                             metadata=meta, created_at=now_iso())
        existing = ctx.repos.series.load_release(ctx.series_id, n)
        if existing and existing.state == "approved":
            ctx.repos.outputs.remove(ctx.series_id, n)  # a re-render supersedes the earlier approval
        ctx.repos.series.save_release(pkg)
        if state == "awaiting_approval" and ctx.params.auto_approve:
            pkg = approve(ctx.repos, ctx.series_id, n, reviewer="auto-approve", notes="EMVOOX_AUTO_APPROVE / run parameter")
        ctx.log(f"gate: ep{n:02d} -> {pkg.state} ({reason})")
        return pkg


def approve(repos: Repositories, sid: str, n: int, *, reviewer: str, notes: str = "", metadata: PublishMetadata | None = None) -> ReleasePackage:
    """Human sign-off: export the masters and the metadata. Works for FLAGGED episodes too (recorded as an override)."""
    pkg = repos.series.load_release(sid, n)
    if pkg is None:
        raise AgentError(f"ep{n:02d} has not reached the approval gate")
    if not reviewer.strip():
        raise AgentError("a reviewer name is required")
    if metadata is not None:
        pkg.metadata = metadata
    mastered = repos.series.load_mastered(sid, n)
    if mastered is None or not repos.blobs.exists(mastered.mp3_path):
        raise AgentError(f"ep{n:02d} has no master to export")
    exported = []
    for kind, key in (("mp3", mastered.mp3_path), ("wav", mastered.wav_path)):
        dst = repos.outputs.export(key, sid, n, kind)
        exported.append(ExportedFile(kind=kind, path=dst, bytes=repos.blobs.size(dst)))
    bible = repos.series.load_bible(sid)
    doc = {"platform": "youtube", "series_id": sid, "episode_number": n, "series_title": bible.title if bible else sid,
           "duration_seconds": round(mastered.duration_ms / 1000, 1), "audio_file": f"{paths.ep(n)}.mp3",
           **pkg.metadata.model_dump(mode="json"), "qa": {"status": pkg.qa_status, "score": pkg.qa_score, "attempts": pkg.qa_attempts},
           "approved_by": reviewer, "approved_at": now_iso()}
    key = repos.outputs.save_metadata(sid, n, doc)
    exported.append(ExportedFile(kind="metadata", path=key))
    pkg.decision = ApprovalDecision(decision="approved", reviewer=reviewer, notes=notes, override_flagged=pkg.qa_status == "FLAGGED", at=now_iso())
    pkg.state = "approved"
    pkg.exported = exported
    pkg.publish = {"platform": "youtube", "status": "ready_for_upload", "at": now_iso(),
                   "note": "Publishing mock-up: files and metadata are staged locally; the upload is not wired in Prototype V1."}
    repos.series.save_release(pkg)
    qa = repos.series.load_qa(sid, n)
    if qa is not None:
        from emvoox.contracts.qa import HumanVerdict

        qa.human = HumanVerdict(verdict="approved", reviewer=reviewer, notes=notes, at=now_iso())
        repos.series.save_qa(qa)
    return pkg


def reject(repos: Repositories, sid: str, n: int, *, reviewer: str, notes: str = "", lines: list[str] | None = None) -> ReleasePackage:
    pkg = repos.series.load_release(sid, n)
    if pkg is None:
        raise AgentError(f"ep{n:02d} has not reached the approval gate")
    if pkg.state == "approved":
        repos.outputs.remove(sid, n)
    pkg.decision = ApprovalDecision(decision="rejected", reviewer=reviewer or "unknown", notes=notes, lines=lines or [], at=now_iso())
    pkg.state = "rejected"
    pkg.exported = []
    pkg.publish = {}
    repos.series.save_release(pkg)
    qa = repos.series.load_qa(sid, n)
    if qa is not None:
        from emvoox.contracts.qa import HumanVerdict

        qa.human = HumanVerdict(verdict="rejected", reviewer=reviewer, lines=lines or [], notes=notes, at=now_iso())
        repos.series.save_qa(qa)
    return pkg


def update_metadata(repos: Repositories, sid: str, n: int, metadata: PublishMetadata) -> ReleasePackage:
    pkg = repos.series.load_release(sid, n)
    if pkg is None:
        raise AgentError(f"ep{n:02d} has not reached the approval gate")
    pkg.metadata = metadata
    repos.series.save_release(pkg)
    if pkg.state == "approved":
        doc = repos.docs.get(paths.approved_file(sid, n, "youtube.json")) or {}
        repos.outputs.save_metadata(sid, n, {**doc, **metadata.model_dump(mode="json")})
    return pkg
