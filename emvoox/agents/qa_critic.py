"""QA Critic Agent: measures the mastered episode against the technical standard and says what to redo.

Skills
    QA Audio      deterministic FFmpeg checks per stem and on the master:
                    missing stems / missing sentences (stem far shorter than its text), clipping,
                    long silences inside a stem, speaker mismatch (stem rendered with another voice),
                    placeholder voices, master loudness and true peak, master duration vs target
    Review Audio  optional (EMVOOX_QA_TRANSCRIBE=true, LLM with audio input): transcript of each
                  stem vs its text (word error rate) to catch mispronounced, skipped or added words
                  and spoken direction in multi-speaker chunks; plus the list of lines a human
                  should listen to (peaks, intense monologues)

Output: ``QAReport`` with PASS / FLAGGED, a 0-100 score, timestamped issues and retry instructions
the orchestrator executes (re-render units with more stable settings, split a chunk into lines,
re-master).
"""

from __future__ import annotations

import re
import unicodedata

from emvoox import paths
from emvoox.agents.base import Agent, AgentContext, Skill
from emvoox.audio.ffmpeg import detect_silences, measure_ebur128, peak_stats
from emvoox.audio.timeline import unit_offsets
from emvoox.contracts.audio import MasteredEpisode
from emvoox.contracts.cast import ResolvedCast
from emvoox.contracts.direction import DirectedConversationUnits, RenderUnit
from emvoox.contracts.qa import QAIssue, QAReport, RetryInstruction
from emvoox.repositories import now_iso

WORDS_PER_SEC = 3.6
SHORT_RATIO = 0.45  # stem shorter than 45 % of what its words need: a sentence is missing
LONG_RATIO = 2.4  # stem longer than 240 %: runaway audio or spoken direction
CLIP_DB = -0.1
SILENCE_DB, SILENCE_S = -50.0, 1.5
WER_FAIL = 0.25
PENALTY = {"blocker": 25, "major": 12, "minor": 3}
LEAK_WORDS = ("nhân vật", "chỉ dẫn", "diễn xuất", "hội thoại", "lời thoại")


def _norm_words(text: str) -> list[str]:
    t = unicodedata.normalize("NFC", text.lower())
    t = re.sub(r"\[[^\]]*\]", " ", t)
    return re.findall(r"\w+", t)


def wer(reference: str, hypothesis: str) -> float:
    ref, hyp = _norm_words(reference), _norm_words(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, start=1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, start=1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / len(ref)


class QACriticAgent(Agent):
    id = "qa_critic"
    title = "QA Critic Agent"
    description = "Checks every stem and the master for missing sentences, clipping, silences, wrong voices and loudness; emits retry instructions."
    skills = (
        Skill("qa_audio", "QA Audio", "FFmpeg measurements per stem and on the master against the technical standard."),
        Skill("review_audio", "Review Audio", "Transcript vs script (word error rate) when enabled, and the lines a human should hear."),
    )
    consumes = "MasteredEpisode + DirectedConversationUnits"
    produces = QAReport

    def _expected_ms(self, directed: DirectedConversationUnits, r: RenderUnit) -> int:
        words = sum(len(directed.unit(uid).text.split()) for uid in r.unit_ids)
        return int(words / WORDS_PER_SEC * 1000)

    # ---- skill: QA Audio
    def qa_audio(self, ctx: AgentContext, directed: DirectedConversationUnits, cast: ResolvedCast, mastered: MasteredEpisode | None) -> tuple[dict, list[QAIssue]]:
        sid, n = directed.series_id, directed.episode_number
        repo = ctx.repos.series
        tl = repo.load_timeline(sid, n)
        offsets = unit_offsets(tl) if tl else {}
        issues: list[QAIssue] = []
        checks: dict[str, dict] = {}
        missing, short, long_, clipped, silent, mismatch, placeholder = [], [], [], [], [], [], []
        for r in directed.render_plan:
            at = offsets.get(r.id)
            first_line = r.unit_ids[0]
            if not repo.stem_exists(sid, n, r.stem):
                missing.append(r.id)
                issues.append(QAIssue(code="missing_stem", severity="blocker", message=f"no audio for {r.id}", unit_id=r.id, line_id=first_line, at_ms=at))
                continue
            path = ctx.repos.blobs.local(paths.stem(sid, n, r.stem))
            meta = repo.stem_meta(sid, n, r.stem) or {}
            dur = int(meta.get("duration_ms") or 0)
            if not dur:
                from emvoox.audio.ffmpeg import duration_ms

                dur = duration_ms(path)
            expected = self._expected_ms(directed, r)
            ratio = dur / expected if expected else 1.0
            if ratio < SHORT_RATIO:
                short.append(r.id)
                issues.append(QAIssue(code="missing_sentence", severity="major", unit_id=r.id, line_id=first_line, at_ms=at, value=round(ratio, 2),
                                      message=f"{r.id}: {dur} ms of audio for ~{expected} ms of text ({ratio:.0%}); words are missing"))
            elif ratio > LONG_RATIO:
                long_.append(r.id)
                code = "direction_leak" if r.kind == "conversation" else "duration_off"
                issues.append(QAIssue(code=code, severity="major", unit_id=r.id, line_id=first_line, at_ms=at, value=round(ratio, 2),
                                      message=f"{r.id}: {dur} ms of audio for ~{expected} ms of text ({ratio:.0%}); extra speech"))
            ps = peak_stats(path)
            if ps["peak_db"] == ps["peak_db"] and ps["peak_db"] >= CLIP_DB:  # nan-safe
                clipped.append(r.id)
                issues.append(QAIssue(code="clipping", severity="major", unit_id=r.id, line_id=first_line, at_ms=at, value=round(ps["peak_db"], 2),
                                      message=f"{r.id}: peak {ps['peak_db']:.2f} dBFS (clipping)"))
            gaps = detect_silences(path, noise_db=SILENCE_DB, min_s=SILENCE_S)
            if ps["rms_db"] == float("-inf") or gaps:
                silent.append(r.id)
                where = f" at {gaps[0][0]:.1f}s for {gaps[0][1]:.1f}s" if gaps else ""
                issues.append(QAIssue(code="long_silence", severity="major", unit_id=r.id, line_id=first_line,
                                      at_ms=(at or 0) + int(gaps[0][0] * 1000) if gaps else at,
                                      message=f"{r.id}: silence inside the stem{where}"))
            req = meta.get("request") or {}
            if meta.get("voice_fallback"):
                placeholder.append(r.id)
                issues.append(QAIssue(code="placeholder_voice", severity="minor", unit_id=r.id, line_id=first_line, at_ms=at,
                                      message=f"{r.id}: rendered with fallback voice {meta['voice_fallback'].get('used')} instead of {r.voice_id}"))
            elif r.kind == "line":
                want = cast.member(r.speakers[0]).voice_id
                if req.get("voice_id") and req.get("voice_id") != want:
                    mismatch.append(r.id)
                    issues.append(QAIssue(code="speaker_mismatch", severity="major", unit_id=r.id, line_id=first_line, at_ms=at,
                                          message=f"{r.id}: rendered with voice {req.get('voice_id')}, cast voice is {want}"))
            else:
                want_pairs = sorted(cast.member(a).voice_id for a in r.speakers)
                got = sorted(v for _, v in (req.get("speakers") or [])) or [req.get("voice_id")]
                if req and got != want_pairs and len(r.speakers) > 1:
                    mismatch.append(r.id)
                    issues.append(QAIssue(code="speaker_mismatch", severity="major", unit_id=r.id, line_id=first_line, at_ms=at,
                                          message=f"{r.id}: speakers {got} do not match the cast {want_pairs}"))
        checks["stems_complete"] = {"ok": not missing, "missing": missing, "units": len(directed.render_plan)}
        checks["sentences"] = {"ok": not short and not long_, "short": short, "long": long_}
        checks["clipping"] = {"ok": not clipped, "units": clipped, "threshold_dbfs": CLIP_DB}
        checks["silence"] = {"ok": not silent, "units": silent, "min_silence_s": SILENCE_S}
        checks["speakers"] = {"ok": not mismatch, "mismatch": mismatch, "placeholder": placeholder}

        if mastered is None or not ctx.repos.blobs.exists(paths.master(sid, n, "wav")):
            checks["loudness"] = {"ok": False, "error": "master not found"}
            issues.append(QAIssue(code="master_missing", severity="blocker", message="the episode has no master"))
            return checks, issues
        m = measure_ebur128(ctx.repos.blobs.local(paths.master(sid, n, "wav")))
        target, tp = ctx.settings.loudness_lufs, ctx.settings.true_peak_dbtp
        if m is None:
            checks["loudness"] = {"ok": False, "error": "could not measure the master"}
            issues.append(QAIssue(code="loudness_off", severity="major", message="could not measure the master's loudness"))
        else:
            loud_ok = abs(m["integrated_lufs"] - target) <= 1.0
            peak_ok = m["true_peak_dbtp"] <= tp + 0.1
            checks["loudness"] = {"ok": loud_ok and peak_ok, "integrated_lufs": m["integrated_lufs"], "true_peak_dbtp": m["true_peak_dbtp"],
                                  "target_lufs": target, "target_tp": tp}
            if not loud_ok:
                issues.append(QAIssue(code="loudness_off", severity="major", value=m["integrated_lufs"],
                                      message=f"master at {m['integrated_lufs']:.1f} LUFS, target {target} ±1"))
            if not peak_ok:
                issues.append(QAIssue(code="true_peak_over", severity="major", value=m["true_peak_dbtp"],
                                      message=f"true peak {m['true_peak_dbtp']:.1f} dBTP over the {tp} limit"))
        sec = mastered.duration_ms / 1000
        tgt = directed.target_duration_sec
        dur_ok = 0.5 * tgt <= sec <= 1.6 * tgt
        checks["duration"] = {"ok": dur_ok, "seconds": round(sec, 1), "target": tgt}
        if not dur_ok:
            issues.append(QAIssue(code="master_duration_off", severity="minor", value=round(sec, 1),
                                  message=f"master is {sec:.0f}s for a {tgt}s target; the script length needs a look"))
        return checks, issues

    # ---- skill: Review Audio
    def review_audio(self, ctx: AgentContext, directed: DirectedConversationUnits, offsets: dict[str, int]) -> tuple[dict, list[QAIssue], list[str]]:
        review = [u.unit_id for u in directed.spoken() if u.emotional_intensity >= 9 or (u.type.value == "monologue" and u.emotional_intensity >= 7)]
        if not ctx.settings.qa_transcribe:
            return {"ok": None, "skipped": "EMVOOX_QA_TRANSCRIBE is off"}, [], review
        if not ctx.llm.can_transcribe():
            return {"ok": None, "skipped": f"{ctx.llm.name} cannot transcribe audio"}, [], review
        sid, n = directed.series_id, directed.episode_number
        issues: list[QAIssue] = []
        rows = []
        for r in directed.render_plan:
            if not ctx.repos.series.stem_exists(sid, n, r.stem):
                continue
            ref = " ".join(directed.unit(uid).text for uid in r.unit_ids)
            try:
                hyp = ctx.llm.transcribe(ctx.repos.blobs.local(paths.stem(sid, n, r.stem)), agent=self.id, skill="review_audio", episode=n)
            except Exception as e:  # noqa: BLE001 - a judge failure never fails the episode
                rows.append({"unit": r.id, "error": f"{type(e).__name__}: {str(e)[:100]}"})
                continue
            score = wer(ref, hyp)
            rows.append({"unit": r.id, "wer": round(score, 3)})
            leak = r.kind == "conversation" and any(w in hyp.lower() and w not in ref.lower() for w in LEAK_WORDS)
            if leak:
                issues.append(QAIssue(code="direction_leak", severity="major", unit_id=r.id, line_id=r.unit_ids[0], at_ms=offsets.get(r.id),
                                      message=f"{r.id}: the acting direction was read aloud"))
            elif score > WER_FAIL:
                issues.append(QAIssue(code="mispronunciation", severity="major", unit_id=r.id, line_id=r.unit_ids[0], at_ms=offsets.get(r.id),
                                      value=round(score, 3), message=f"{r.id}: transcript differs from the script (WER {score:.0%})"))
        return {"ok": not issues, "units": rows, "wer_fail": WER_FAIL}, issues, review

    # ---- retry instructions
    def retry_plan(self, directed: DirectedConversationUnits, issues: list[QAIssue], attempt: int) -> list[RetryInstruction]:
        kinds = {r.id: r.kind for r in directed.render_plan}
        rerender, split, remaster = set(), set(), False
        reasons: dict[str, list[str]] = {}
        for i in issues:
            if i.severity == "minor":
                continue
            if i.code in ("loudness_off", "true_peak_over"):
                remaster = True
                continue
            if not i.unit_id:
                continue
            reasons.setdefault(i.unit_id, []).append(i.code)
            if kinds.get(i.unit_id) == "conversation" and i.code in ("missing_sentence", "direction_leak", "mispronunciation", "duration_off"):
                split.add(i.unit_id)
            else:
                rerender.add(i.unit_id)
        rerender -= split
        out: list[RetryInstruction] = []
        nxt = attempt + 1
        if rerender:
            out.append(RetryInstruction(action="rerender", step="voice", unit_ids=sorted(rerender), params={"attempt": nxt},
                                        reason="; ".join(f"{u}: {','.join(reasons[u])}" for u in sorted(rerender))))
        if split:
            out.append(RetryInstruction(action="rerender_line_mode", step="voice", unit_ids=sorted(split), params={"attempt": nxt},
                                        reason="multi-speaker chunk lost or added speech; render its lines one by one"))
        if remaster and not (rerender or split):
            out.append(RetryInstruction(action="reassemble", step="master", params={"attempt": nxt}, reason="master loudness outside the target"))
        return out

    # ---- agent entry point
    def run(self, ctx: AgentContext, directed: DirectedConversationUnits, cast: ResolvedCast, mastered: MasteredEpisode | None, *, attempt: int = 0) -> QAReport:
        checks, issues = self.qa_audio(ctx, directed, cast, mastered)
        tl = ctx.repos.series.load_timeline(directed.series_id, directed.episode_number)
        transcript, review_issues, review_lines = self.review_audio(ctx, directed, unit_offsets(tl) if tl else {})
        checks["transcript"] = transcript
        issues += review_issues
        score = max(0, 100 - sum(PENALTY[i.severity] for i in issues))
        # A score under the bar from minor issues alone is FLAGGED with no retry: nothing to re-render, a human decides.
        flagged = any(i.severity in ("blocker", "major") for i in issues) or score < ctx.settings.qa_pass_score
        report = QAReport(series_id=directed.series_id, episode_number=directed.episode_number, attempt=attempt,
                          status="FLAGGED" if flagged else "PASS", score=score, checks=checks, error_logs=issues,
                          retry_instructions=self.retry_plan(directed, issues, attempt) if flagged else [],
                          review_lines=review_lines, generated_at=now_iso())
        ctx.repos.series.save_qa(report)
        ctx.log(f"qa: {report.status} score {score} ({len(issues)} issue(s)); retry: "
                + (", ".join(f"{r.action}[{','.join(r.unit_ids) or 'master'}]" for r in report.retry_instructions) or "none"))
        return report
