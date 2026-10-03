"""Script Writer Agent: TrendBrief or a human story -> StoryInput + SeriesBible, then one screenplay per episode.

Skills
    Story Adapt        TrendBrief -> a writable story (title, roles with their own goals, act-by-act
                       treatment) under the Emvoox Anti-Trope rules. Skipped when a human supplies the story.
    Episodize          outline: split the story into N episodes that each end on a cliffhanger;
                       draft: one screenplay per episode. Two modes, picked from the input length:
                       "segment" keeps the author's dialogue word for word, "write" expands a treatment.
    Cliffhanger Check  score the hook of each drafted episode (1-10) and verify the Anti-Trope rules;
                       a weak episode written in "write" mode is rewritten once with the critique.

Casting is not done here: roles leave this agent without actors and the Casting Agent resolves them.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from emvoox.agents.base import Agent, AgentContext, AgentError, Skill
from emvoox.casting import apply_role_tags
from emvoox.contracts.market import THEME_LABEL_VI, TrendBrief
from emvoox.contracts.production import (
    EpisodeDraft,
    EpisodeFormat,
    RoleCast,
    SeriesBible,
    SeriesOutline,
    StoryInput,
    StoryOverview,
)
from emvoox.contracts.script import ANTI_TROPE_RULES_VI, CliffhangerCheck, EpisodeDraftResult, ScriptPackage, StoryAdaptation
from emvoox.providers.llm import LlmBlocked, LlmError, LlmSchemaError, LlmTruncated

WORDS_PER_SEC = 3.3  # measured 3.6 w/s on ElevenLabs v3; Vietnamese-native voices run a little slower
VERBATIM_MIN = 0.7   # segment mode: minimum share of lines copied word for word before we retry
TWIST_WINDOW_WORDS = 100  # about 30 seconds of dialogue

_RULES = "\n".join(f"{i}. {r}" for i, r in enumerate(ANTI_TROPE_RULES_VI, start=1))

ADAPT_SYSTEM = f"""Bạn là biên kịch trưởng của Emvoox (kênh Mặc Khải), viết micro-drama dạng AUDIO tiếng Việt.
Bạn nhận một Trend Brief từ bộ phận nghiên cứu thị trường và phát triển nó thành một câu chuyện hoàn chỉnh để chia tập.

Trả về StoryAdaptation:
- title, genre, setting.
- roles[]: 2-5 vai. Mỗi vai có name (tên Việt) và description: tuổi, giới tính, tính cách, MỤC TIÊU và ĐỘNG CƠ riêng. Để actor_id = null.
- treatment: toàn bộ câu chuyện theo từng hồi, đủ chi tiết để chia thành nhiều tập, nêu rõ các bước ngoặt và kết thúc.

Quy tắc Anti-Trope của Emvoox (bắt buộc):
{_RULES}

Đây là audio: không có hình, không có người dẫn chuyện ngôi thứ ba; mọi thứ đi qua lời thoại và độc thoại nội tâm của nhân vật chính.
Không sao chép tựa tham khảo; chỉ học cách chúng tạo hook. Viết bằng tiếng Việt tự nhiên.
"""

OUTLINE_SYSTEM = """Bạn là biên kịch trưởng của một studio phim ngắn (micro-drama) dạng AUDIO tiếng Việt.

Bạn nhận: (1) tổng quan câu chuyện, (2) danh sách vai và mô tả, (3) kịch bản/câu chuyện.

Nhiệm vụ 1 - DANH SÁCH VAI (roles[]): liệt kê mọi vai có lời thoại. Đặt role_type: protagonist | antagonist | supporting | minor, và description (tuổi, giới tính, tính cách, mục tiêu). Để actor_id = null: việc phân vai do bộ phận casting làm sau. Xác định protagonist_role (nhân vật kể chuyện ngôi thứ nhất "tôi").

Nhiệm vụ 2 - CHIA TẬP (episodes[]): {count} tập, mỗi tập {min_sec}-{max_sec} giây khi đọc thành tiếng (khoảng {min_words}-{max_words} từ thoại), LUÔN kết thúc bằng cliffhanger.
{mode_rules}
- Tập 1 phải có hook trong 15 giây đầu. Mỗi tập có 1 xung đột rõ, 1 bước ngoặt trong 30 giây đầu, 1 cliffhanger.
- Đây là audio, không có hình: người nghe chỉ biết chuyện qua lời thoại và độc thoại nội tâm của nhân vật chính. KHÔNG có người dẫn chuyện ngôi thứ ba.
- Viết mọi nội dung bằng tiếng Việt tự nhiên. Chỉ các trường định danh (role_type) dùng tiếng Anh.

Quy tắc Anti-Trope của Emvoox:
{rules}
"""

MODE_RULES = {
    "segment": (
        "- Kịch bản đã có đầy đủ lời thoại: KHÔNG viết lại câu chuyện. Hãy CHIA kịch bản theo đúng thứ tự thành {count} tập có độ dài tương đương, "
        "cắt tại những điểm căng thẳng nhất để làm cliffhanger. Ghi source_span cho mỗi tập (ví dụ 'Cảnh 3 - giữa Cảnh 4', hoặc câu đầu và câu cuối của đoạn). "
        "Không được bỏ sót hay đảo thứ tự nội dung."
    ),
    "write": (
        "- Đầu vào là tóm tắt/treatment: hãy phát triển thành {count} tập với key_beats cụ thể cho từng tập. source_span để trống."
    ),
}

DRAFT_SYSTEM = """Bạn là biên kịch viết kịch bản audio micro-drama tiếng Việt cho tập {nn}.
Kịch bản dài {min_sec}-{max_sec} giây khi đọc thành tiếng: tổng cộng {min_words}-{max_words} từ thoại (đếm mọi từ trong text), chia 2-4 cảnh, mỗi cảnh 4-8 lời thoại.

Trả về EpisodeDraft có cấu trúc:
- scenes[]: heading ("Địa điểm. Thời gian."), atmosphere (một dòng không khí/âm thanh, có thể rỗng), lines[].
- lines[]: speaker = TÊN VAI đúng như trong danh sách vai (ví dụ "{example_role}"), internal (true = độc thoại nội tâm ngôi thứ nhất, CHỈ dành cho {protagonist_role}), direction (ghi chú diễn xuất ngắn hoặc rỗng), text (lời nói).
- Mỗi phần tử lines là MỘT lời thoại của MỘT người. Không đưa nhãn tên hay dấu ngoặc vào text.

Quy tắc:
{mode_rules}
- Chỉ dùng các vai trong danh sách. Không có người dẫn chuyện: mọi bối cảnh phải đi qua thoại hoặc nội tâm của {protagonist_role}.
- Lời thoại ngắn, đời, nói được. Viết số bằng chữ ("hai mươi mốt giờ" thay vì "21h").
- Dòng cuối cùng của tập phải là cliffhanger đã định (có thể diễn đạt lại cho tự nhiên).
- estimated_duration_sec ≈ tổng số từ thoại / 3.3.
"""

DRAFT_MODE_RULES = {
    "segment": (
        "- Tập này là ĐOẠN kịch bản gốc được chỉ định (source_span). Bạn là người CHÉP LẠI, không phải người viết lại: "
        "mỗi lời thoại trong text phải là NGUYÊN VĂN từng chữ của tác giả (kể cả dấu câu), theo đúng thứ tự, không thêm, không bớt, không diễn đạt lại. "
        "Chỉ được: (a) tách một lời thoại dài thành nhiều dòng của cùng người nói, (b) thêm direction, (c) thêm tối đa 2 độc thoại nội tâm NGẮN của nhân vật chính "
        "nếu đoạn gốc không có nội tâm nào. Không bịa tình tiết, không thêm nhân vật."
    ),
    "write": ("- Viết mới theo key_beats; giữ giọng điệu series; nhân vật chính có nhiều độc thoại nội tâm.\n"
              "- Anti-Trope: bước ngoặt đầu tiên trong 30 giây đầu (khoảng 100 từ đầu); phản diện thông minh, có lý do; mỗi vai nói và hành động theo động cơ riêng."),
}

CLIFFHANGER_SYSTEM = f"""Bạn là biên tập viên của Emvoox. Bạn chấm một tập kịch bản audio micro-drama tiếng Việt.

Trả về CliffhangerCheck:
- hook_score 1-10: câu kết khiến người nghe muốn mở tập sau đến mức nào (10 = không thể dừng; 5 = kết bình thường; dưới 5 = kết khép, không còn câu hỏi).
- twist_within_30s: có bước ngoặt/tiết lộ trong khoảng 100 từ thoại đầu không.
- antagonist_is_smart: phản diện hành động có lý do và không ngớ ngẩn (true nếu tập không có phản diện).
- independent_motivations: các vai có động cơ riêng, không chỉ phản ứng theo nhân vật chính.
- issues[]: vấn đề cụ thể (tối đa 4). suggestion: một ghi chú sửa cụ thể nếu hook_score < 7, nếu không để rỗng.
- checked_by = "llm". passed = true nếu hook_score đạt ngưỡng {{min_score}} và twist_within_30s đúng.

Quy tắc Anti-Trope của Emvoox:
{_RULES}
"""


def _norm_line(s: str) -> str:
    return re.sub(r"[\s\.,!?…;:\"'“”‘’\-–—]+", " ", s.lower()).strip()


def verbatim_ratio(draft: EpisodeDraft, script: str) -> tuple[float, list[str]]:
    """Share of draft lines (excluding new monologues) that appear word for word in the source script."""
    src = _norm_line(script)
    total, kept, missing = 0, 0, []
    for sc in draft.scenes:
        for ln in sc.lines:
            if ln.internal:
                continue
            total += 1
            if _norm_line(ln.text) in src:
                kept += 1
            else:
                missing.append(ln.text)
    return (kept / total if total else 1.0), missing


def detect_mode(story: StoryInput, fmt: EpisodeFormat) -> str:
    need = fmt.count * fmt.min_duration_sec * WORDS_PER_SEC
    return "segment" if story.script_words() >= 0.5 * need else "write"


def rule_check(draft: EpisodeDraft, planned_cliffhanger: str, min_score: int) -> CliffhangerCheck:
    """Deterministic Cliffhanger Check, used when the LLM check is off or fails: does the episode
    end on an open question, and does anything turn inside the first ~30 seconds?"""
    lines = [ln for sc in draft.scenes for ln in sc.lines]
    last = lines[-1].text.strip()
    score = 5
    if last.endswith(("?", "...", "…", "!", "\"", "”")):
        score += 2
    if any(w in last.lower() for w in ("nhưng", "không ngờ", "lại là", "đã chết", "là ai", "chạy", "bí mật", "sự thật")):
        score += 1
    if planned_cliffhanger and _norm_line(planned_cliffhanger)[:24] in _norm_line(last):
        score += 1
    words, early = 0, False
    for ln in lines:
        words += len(ln.text.split())
        if words > TWIST_WINDOW_WORDS:
            break
        if "?" in ln.text or "!" in ln.text or ln.internal:
            early = True
    issues = []
    if score < min_score:
        issues.append("Câu kết chưa để lại câu hỏi mở cho tập sau.")
    if not early:
        issues.append("Chưa thấy bước ngoặt trong 30 giây đầu.")
    score = max(1, min(10, score))
    return CliffhangerCheck(episode_number=draft.episode_number, hook_score=score, twist_within_30s=early, issues=issues,
                            suggestion="Kết tập bằng một tiết lộ hoặc câu hỏi chưa có lời đáp." if score < min_score else "",
                            checked_by="rules", passed=score >= min_score and early)


class ScriptWriterAgent(Agent):
    id = "script_writer"
    title = "Script Writer Agent"
    description = "Adapts a trend brief or a human story into a series bible and episode screenplays under the Anti-Trope rules."
    skills = (
        Skill("story_adapt", "Story Adapt", "TrendBrief -> story with roles, motives and an act-by-act treatment."),
        Skill("episodize", "Episodize", "Outline N episodes ending on cliffhangers, then draft each screenplay (segment or write mode)."),
        Skill("cliffhanger_check", "Cliffhanger Check", "Hook score 1-10 and Anti-Trope checks per episode; weak drafts are rewritten once."),
    )
    consumes = "TrendBrief | StoryInput"
    produces = ScriptPackage

    # ---- skill: Story Adapt
    def story_adapt(self, ctx: AgentContext, brief: TrendBrief) -> StoryInput:
        f = brief.format_spec
        user = (
            f"TREND BRIEF\nChủ đề: {brief.topic}\nTuyến nội dung: {THEME_LABEL_VI[brief.theme_category]}\nKhán giả: {brief.target_audience}\n"
            f"Hook: {brief.hook}\nTiền đề: {brief.premise}\nGóc làm mới: {brief.anti_trope_angle}\n"
            f"Tựa tham khảo (không sao chép): {', '.join(brief.reference_titles) or '(không có)'}\n"
            f"Định dạng: {ctx.params.episodes} tập, mỗi tập {ctx.params.min_sec}-{ctx.params.max_sec} giây "
            f"(brief đề xuất {f.episodes} tập, {f.episode_seconds_min}-{f.episode_seconds_max} giây).\n\nHãy trả về StoryAdaptation."
        )
        try:
            a = ctx.llm.structured(agent=self.id, skill="story_adapt", system=ADAPT_SYSTEM, user=user, schema=StoryAdaptation,
                                   context={"brief": brief.model_dump(mode="json")})
        except LlmError as e:
            raise AgentError(f"Story Adapt failed: {e}", retryable=not isinstance(e, LlmBlocked)) from e
        total_min = max(1, round(ctx.params.episodes * (ctx.params.min_sec + ctx.params.max_sec) / 2 / 60))
        story = StoryInput(overview=StoryOverview(title=a.title, total_minutes=total_min, genre=a.genre, setting=a.setting),
                           roles=a.roles, script=a.treatment)
        ctx.log(f"story adapt: {a.title!r}, {len(a.roles)} role(s), treatment {len(a.treatment.split())} words")
        return story

    # ---- skill: Episodize (outline)
    def outline(self, ctx: AgentContext, story: StoryInput, fmt: EpisodeFormat, *, brief: TrendBrief | None = None) -> SeriesBible:
        mode = detect_mode(story, fmt)
        min_words = int(fmt.min_duration_sec * WORDS_PER_SEC)
        max_words = int(fmt.max_duration_sec * WORDS_PER_SEC * 1.15)
        system = OUTLINE_SYSTEM.format(count=fmt.count, min_sec=fmt.min_duration_sec, max_sec=fmt.max_duration_sec, min_words=min_words,
                                       max_words=max_words, mode_rules=MODE_RULES[mode].format(count=fmt.count), rules=_RULES)
        roles_txt = "\n".join(f"- {r.name}: {r.description}" for r in story.roles) or "(chưa liệt kê; hãy suy ra từ kịch bản)"
        o = story.overview
        user = (
            f"series_id: {ctx.series_id}\nSố tập: {fmt.count} | Thời lượng mỗi tập: {fmt.min_duration_sec}-{fmt.max_duration_sec} giây | Chế độ: {mode}\n\n"
            f"TỔNG QUAN\nTên: {o.title}\nThời lượng dự kiến: {o.total_minutes or '?'} phút\nThể loại: {o.genre}\nBối cảnh: {o.setting}\n\n"
            f"VAI TRONG CÂU CHUYỆN\n{roles_txt}\n\n"
            f"KỊCH BẢN\n<script>\n{story.script.strip()}\n</script>\n\nHãy trả về SeriesOutline."
        )
        try:
            outline = ctx.llm.structured(
                agent=self.id, skill="episodize.outline", system=system, user=user, schema=SeriesOutline,
                context={"title": o.title, "genre": o.genre, "count": fmt.count, "mode": mode,
                         "roles": [{"name": r.name, "description": r.description} for r in story.roles]})
        except LlmError as e:
            raise AgentError(f"outline failed: {e}", retryable=not isinstance(e, LlmBlocked)) from e
        if len(outline.episodes) != fmt.count:
            raise AgentError(f"outline returned {len(outline.episodes)} episodes, expected {fmt.count}", retryable=True)

        # The director's pins survive the outline; every other role leaves uncast for the Casting Agent.
        pins = {r.name: r.actor_id for r in story.roles if r.actor_id}
        desc = {r.name: r.description for r in story.roles}
        roles = [RoleCast(role_name=rc.role_name, role_type=rc.role_type, description=desc.get(rc.role_name) or rc.description or rc.reason,
                          actor_id=pins.get(rc.role_name), assigned_by="user" if rc.role_name in pins else "ai", reason="") for rc in outline.roles]
        bible = SeriesBible(
            series_id=ctx.series_id, title=outline.title, logline=outline.logline, premise=outline.premise, tone=outline.tone,
            genre=outline.genre, overview=story.overview, mode=mode, protagonist_role=outline.protagonist_role, roles=roles,
            episode_format=fmt, episodes=outline.episodes, trend_brief_id=brief.brief_id if brief else None,
            theme_category=brief.theme_category.value if brief else None,
            changelog=[f"{datetime.now(UTC).date()} outline ({ctx.llm.model}, mode={mode})"],
        )
        ctx.log(f"outline: {len(bible.episodes)} episode(s), mode={mode}, {len(roles)} role(s), protagonist {bible.protagonist_role!r}")
        return bible

    # ---- skill: Episodize (draft)
    def draft(self, ctx: AgentContext, bible: SeriesBible, story: StoryInput, n: int, *, feedback: str = "") -> EpisodeDraft:
        fmt = bible.episode_format
        plan = bible.episodes[n - 1]
        prev = bible.episodes[n - 2] if n > 1 else None
        nxt = bible.episodes[n] if n < len(bible.episodes) else None
        min_words = int(fmt.min_duration_sec * WORDS_PER_SEC)
        max_words = int(fmt.max_duration_sec * WORDS_PER_SEC * 1.15)
        cast_lines = "\n".join(f"- {r.role_name} ({r.role_type}): {r.description}" for r in bible.roles)
        system = DRAFT_SYSTEM.format(nn=f"{n:02d}", min_sec=fmt.min_duration_sec, max_sec=fmt.max_duration_sec, min_words=min_words,
                                     max_words=max_words, protagonist_role=bible.protagonist_role, example_role=bible.roles[0].role_name,
                                     mode_rules=DRAFT_MODE_RULES[bible.mode])
        user = (
            f"Series: {bible.title}\nTiền đề: {bible.premise}\nGiọng điệu: {bible.tone}\n\nVAI:\n{cast_lines}\n\n"
            f"Tập trước: {prev.logline + ' | Cliffhanger: ' + prev.cliffhanger if prev else '(không có, đây là tập 1)'}\n"
            f"TẬP NÀY ({n:02d}) - {plan.title}\nLogline: {plan.logline}\nCác beat: " + "; ".join(plan.key_beats)
            + (f"\nĐoạn kịch bản gốc cần dùng (source_span): {plan.source_span}" if plan.source_span else "")
            + f"\nCliffhanger phải đạt: {plan.cliffhanger}\nTập sau: {nxt.logline if nxt else '(kết series)'}\n"
        )
        if bible.mode == "segment":
            user += f"\nKỊCH BẢN GỐC ĐẦY ĐỦ (chỉ dùng phần thuộc tập này):\n<script>\n{story.script.strip()}\n</script>\n"
        if feedback:
            user += f"\nGHI CHÚ BIÊN TẬP CẦN SỬA:\n{feedback}\n"
        user += "\nHãy trả về EpisodeDraft."
        mock_ctx = {"episode": n, "title": plan.title, "roles": [r.role_name for r in bible.roles], "protagonist_role": bible.protagonist_role,
                    "cliffhanger": plan.cliffhanger, "pad": max(0, (min_words - 60) // 14 + 1)}

        def call(extra: str = "", temperature: float | None = None) -> EpisodeDraft:
            return ctx.llm.structured(agent=self.id, skill="episodize.draft", system=system, user=user + extra, schema=EpisodeDraft,
                                      episode=n, temperature=temperature, context=mock_ctx)

        draft = call(temperature=0.15 if bible.mode == "segment" else None)
        if bible.mode == "segment":
            ratio, missing = verbatim_ratio(draft, story.script)
            if ratio < VERBATIM_MIN:
                fb = ("\n\nBạn đã DIỄN ĐẠT LẠI lời thoại. Các dòng sau không có nguyên văn trong kịch bản gốc:\n- "
                      + "\n- ".join(m[:120] for m in missing[:12])
                      + "\n\nViết lại toàn bộ tập: chép NGUYÊN VĂN từng lời thoại của tác giả trong đoạn này (chỉ tách dòng, thêm direction, thêm nội tâm ngắn).")
                draft = call(fb, temperature=0.1)
                ratio, _ = verbatim_ratio(draft, story.script)
            ctx.log(f"ep{n:02d}: verbatim {ratio:.0%}")
        for _ in range(2 if bible.mode == "write" else 0):  # small models under-write; enforce the word floor (write mode only)
            if draft.word_count() >= min_words:
                break
            draft = call(f"\n\nBản nháp trước chỉ có {draft.word_count()} từ thoại, quá ngắn. Viết lại TOÀN BỘ tập với ít nhất {min_words} và tối đa "
                         f"{max_words} từ thoại. Giữ nguyên các beat và cliffhanger.")
        if draft.episode_number != n:
            raise AgentError(f"draft returned episode {draft.episode_number}, expected {n}", retryable=True)
        known = {r.role_name.lower() for r in bible.roles}
        bad = sorted(s for s in draft.speakers() if s.lower() not in known)
        if bad:
            raise AgentError(f"episode {n}: draft uses speakers not in the role list: {bad}", retryable=True)
        return draft

    # ---- skill: Cliffhanger Check
    def cliffhanger_check(self, ctx: AgentContext, bible: SeriesBible, draft: EpisodeDraft) -> CliffhangerCheck:
        n = draft.episode_number
        plan = bible.episodes[n - 1]
        min_score = ctx.settings.cliffhanger_min_score
        if not ctx.settings.cliffhanger_check:
            return rule_check(draft, plan.cliffhanger, min_score)
        user = (f"Series: {bible.title}\nTiền đề: {bible.premise}\nTập {n:02d}: {plan.title}\nCliffhanger dự kiến: {plan.cliffhanger}\n"
                f"Ngưỡng đạt: {min_score}\n\nKỊCH BẢN TẬP:\n<script>\n{draft.render()}</script>\n\nHãy trả về CliffhangerCheck với episode_number = {n}.")
        try:
            check = ctx.llm.structured(agent=self.id, skill="cliffhanger_check", system=CLIFFHANGER_SYSTEM.replace("{min_score}", str(min_score)),
                                       user=user, schema=CliffhangerCheck, episode=n, temperature=0.1, context={"episode": n})
        except LlmError as e:
            ctx.log(f"ep{n:02d}: cliffhanger check fell back to rules ({type(e).__name__})")
            return rule_check(draft, plan.cliffhanger, min_score)
        check.episode_number = n
        check.passed = check.hook_score >= min_score and check.twist_within_30s
        return check

    # ---- agent entry points
    def write_series(self, ctx: AgentContext, *, story: StoryInput | None = None, brief: TrendBrief | None = None) -> ScriptPackage:
        """Series step: (TrendBrief | StoryInput) -> StoryInput + SeriesBible. An existing bible is kept unless ``force``."""
        repo = ctx.repos.series
        sid = ctx.series_id
        registry = ctx.repos.registry.load()
        adapted = None
        if story is None:
            story = repo.load_story(sid)
        if story is None and brief is not None:
            story = self.story_adapt(ctx, brief)
            adapted = brief.brief_id
        if story is None:
            raw = repo.load_story_raw(sid)
            if not raw:
                raise AgentError("no story to write from: give a StoryInput, a TrendBrief, or run Market Research first")
            story = StoryInput(overview=StoryOverview(title=sid), roles=[], script=raw)
        story.roles = apply_role_tags(story.roles, registry)
        for r in story.roles:
            if r.actor_id and r.actor_id not in registry.ids():
                raise AgentError(f"assigned actor {r.actor_id!r} for role {r.name!r} is not in the Voice IP registry")
        repo.save_story(sid, story)
        if brief is not None:
            repo.save_trend_brief(sid, brief)

        existing = repo.load_bible(sid)
        if existing and existing.episodes and not ctx.params.force:
            ctx.log(f"outline kept: {len(existing.episodes)} episode(s) already planned")
            return ScriptPackage(story=story, bible=existing, outline_reused=True, adapted_from_brief=adapted)
        fmt = EpisodeFormat(count=ctx.params.episodes, min_duration_sec=ctx.params.min_sec, max_duration_sec=ctx.params.max_sec)
        bible = self.outline(ctx, story, fmt, brief=brief or repo.load_trend_brief(sid))
        repo.save_bible(bible)
        return ScriptPackage(story=story, bible=bible, outline_reused=False, adapted_from_brief=adapted)

    def write_episode(self, ctx: AgentContext, n: int) -> EpisodeDraftResult:
        """Episode step: draft the screenplay, check its hook, rewrite once if it is weak (write mode)."""
        repo = ctx.repos.series
        sid = ctx.series_id
        bible = repo.load_bible(sid)
        story = repo.load_story(sid)
        if bible is None or story is None:
            raise AgentError("series has no bible yet; the Script Writer's series step must run first")
        if not 1 <= n <= len(bible.episodes):
            raise AgentError(f"episode {n} is not in the plan (1-{len(bible.episodes)})")
        existing = repo.load_raw_script(sid, n)
        if existing and not ctx.params.force:
            check = repo.load_cliffhanger(sid, n)
            words = len(re.findall(r"\S+", existing))
            ctx.log(f"ep{n:02d}: draft kept ({words} words on disk)")
            return EpisodeDraftResult(series_id=sid, episode_number=n, raw_script=existing, words=max(1, words),
                                      scenes=max(1, existing.count("CẢNH ")), estimated_duration_sec=max(1, round(words / WORDS_PER_SEC)),
                                      cliffhanger=check, reused=True)
        rewrites = 0
        try:
            draft = self.draft(ctx, bible, story, n)
            check = self.cliffhanger_check(ctx, bible, draft)
            if not check.passed and bible.mode == "write":
                fb = (f"Điểm hook hiện tại {check.hook_score}/10. " + " ".join(check.issues) + (" Gợi ý: " + check.suggestion if check.suggestion else "")
                      + " Viết lại toàn bộ tập: bước ngoặt trong 30 giây đầu và câu kết để lại câu hỏi mở.")
                redraft = self.draft(ctx, bible, story, n, feedback=fb)
                recheck = self.cliffhanger_check(ctx, bible, redraft)
                rewrites = 1
                if recheck.hook_score >= check.hook_score:
                    draft, check = redraft, recheck
        except LlmSchemaError as e:
            raise AgentError(f"episode {n}: draft did not satisfy the contract: {str(e)[:300]}", retryable=True) from e
        except (LlmBlocked, LlmTruncated) as e:
            raise AgentError(f"episode {n}: {e}") from e
        except LlmError as e:
            raise AgentError(f"episode {n}: {e}", retryable=True) from e

        raw = draft.render()
        repo.save_raw_script(sid, n, raw)
        repo.save_cliffhanger(sid, check)
        bible.episodes[n - 1].hook_score = check.hook_score
        repo.save_bible(bible)
        words = draft.word_count()
        ctx.log(f"ep{n:02d}: {len(draft.scenes)} scene(s), {words} words, est {draft.estimated_duration_sec}s, hook {check.hook_score}/10"
                f"{' (rewritten once)' if rewrites else ''}{'' if check.passed else ' - below the bar, flagged for the editor'}")
        if not check.passed:
            ctx.note(f"ep{n:02d}: cliffhanger hook {check.hook_score}/10 is below the bar ({ctx.settings.cliffhanger_min_score}); review the script before publishing.")
        return EpisodeDraftResult(series_id=sid, episode_number=n, raw_script=raw, words=words, scenes=len(draft.scenes),
                                  estimated_duration_sec=draft.estimated_duration_sec, cliffhanger=check, rewrites=rewrites)
