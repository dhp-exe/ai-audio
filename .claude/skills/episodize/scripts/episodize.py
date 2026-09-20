#!/usr/bin/env python3
"""Screenwriter + casting: sectioned story -> series bible + N raw Vietnamese episode scripts (stage [0]).

Inputs (either):
    series/<id>/story.json        StoryInput {overview, roles[with optional actor_id], script}   (preferred)
    series/<id>/story_raw.txt     plain story text (legacy)

Two LLM tasks:
    outline  casting (respecting the director's /actor assignments) + split into N episodes.
             mode "segment": the script already has full dialogue -> keep the author's lines, cut at
             cliffhangers, record source_span per episode.  mode "write": input is a treatment -> plan beats.
    draft    one call per episode -> EpisodeDraft (scenes/lines, speaker = role name), rendered to
             scripts/raw/epNN.txt. In segment mode the full script is attached and lines stay verbatim.

CLI
    episodize.py --series <id> [--episodes 30] [--min-sec 50] [--max-sec 70] [--only 1-5] [--outline-only]
                 [--force] [--dry-run] [--model ...]

Exit codes: 0 ok, 1 usage/config error, 2 schema validation failed, 3 blocked/truncated.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from pipeline import naming  # noqa: E402
from pipeline import registry as registry_io  # noqa: E402
from pipeline.casting import apply_role_tags, guess_gender  # noqa: E402
from pipeline.config import get_settings  # noqa: E402
from pipeline.schema import (  # noqa: E402
    EpisodeDraft,
    EpisodeFormat,
    NewCharacter,
    RoleCast,
    SeriesBible,
    SeriesOutline,
    StoryInput,
    StoryOverview,
    VoiceRegistry,
    slugify_id,
)

WORDS_PER_SEC = 3.3  # measured 3.6 w/s on ElevenLabs v3; Vietnamese-native voices run a little slower
VERBATIM_MIN = 0.7   # segment mode: minimum share of lines copied word for word before we retry

OUTLINE_SYSTEM = """Bạn là biên kịch trưởng kiêm giám đốc casting của một studio phim ngắn (micro-drama) dạng AUDIO tiếng Việt.

Bạn nhận: (1) tổng quan câu chuyện, (2) danh sách vai và mô tả, một số vai đã được đạo diễn CHỈ ĐỊNH diễn viên, (3) danh sách Diễn viên AI (Voice IP) có sẵn, (4) kịch bản/câu chuyện.

Nhiệm vụ 1 - CASTING (roles[]): với mỗi vai trong câu chuyện, chọn actor_id phù hợp nhất từ danh sách diễn viên dựa trên giới tính, tuổi, tính cách và chất giọng.
- Vai đã chỉ định diễn viên: giữ nguyên actor_id đó, assigned_by="user".
- Mỗi diễn viên chỉ đóng MỘT vai trong series. Nếu không còn diễn viên phù hợp, để actor_id = null (hệ thống sẽ gán giọng tạm).
- Ghi lý do ngắn trong reason. Đặt role_type: protagonist | antagonist | supporting | minor. Xác định protagonist_role (nhân vật kể chuyện ngôi thứ nhất "tôi").

Nhiệm vụ 2 - CHIA TẬP (episodes[]): {count} tập, mỗi tập {min_sec}-{max_sec} giây khi đọc thành tiếng (khoảng {min_words}-{max_words} từ thoại), LUÔN kết thúc bằng cliffhanger.
{mode_rules}
- Tập 1 phải có hook trong 15 giây đầu. Mỗi tập có 1 xung đột rõ, 1 bước ngoặt, 1 cliffhanger.
- Đây là audio, không có hình: người nghe chỉ biết chuyện qua lời thoại và độc thoại nội tâm của nhân vật chính. KHÔNG có người dẫn chuyện ngôi thứ ba.
- Viết mọi nội dung bằng tiếng Việt tự nhiên. Chỉ các trường định danh (actor_id, role_type) dùng id/tiếng Anh.
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
    "write": "- Viết mới theo key_beats; giữ giọng điệu series; nhân vật chính có nhiều độc thoại nội tâm.",
}


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


def parse_range(spec: str | None, count: int) -> list[int]:
    if not spec:
        return list(range(1, count + 1))
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return sorted(n for n in out if 1 <= n <= count)


def load_story(series: str, registry: VoiceRegistry) -> StoryInput:
    sj = naming.story_json_path(series)
    if sj.exists():
        story = StoryInput.model_validate_json(sj.read_text(encoding="utf-8"))
        story.roles = apply_role_tags(story.roles, registry)
        return story
    raw = naming.story_raw_path(series)
    if not raw.exists():
        raise SystemExit(f"no story found: {sj} or {raw}")
    text = raw.read_text(encoding="utf-8")
    return StoryInput(overview=StoryOverview(title=series), roles=[], script=text)


def detect_mode(story: StoryInput, fmt: EpisodeFormat) -> str:
    need = fmt.count * fmt.min_duration_sec * WORDS_PER_SEC
    return "segment" if story.script_words() >= 0.5 * need else "write"


def log_usage(series: str, stage: str, usage: dict, **extra) -> None:
    p = naming.run_log_path(series)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": datetime.now(UTC).isoformat(timespec="seconds"), "stage": stage, **usage, **extra}, ensure_ascii=False) + "\n")


def roster_text(registry: VoiceRegistry, exclude: set[str]) -> str:
    rows = [c.casting_card() for c in registry.actors() if c.character_id not in exclude]
    return "\n".join(rows) if rows else "(không còn diễn viên trống)"


def run_outline(a: argparse.Namespace, story: StoryInput, registry: VoiceRegistry, fmt: EpisodeFormat) -> SeriesBible:
    from pipeline.llm.gemini_client import generate_structured

    mode = detect_mode(story, fmt)
    min_words = int(fmt.min_duration_sec * WORDS_PER_SEC)
    max_words = int(fmt.max_duration_sec * WORDS_PER_SEC * 1.15)
    pre = {r.name: r.actor_id for r in story.roles if r.actor_id}
    system = OUTLINE_SYSTEM.format(count=fmt.count, min_sec=fmt.min_duration_sec, max_sec=fmt.max_duration_sec,
                                   min_words=min_words, max_words=max_words, mode_rules=MODE_RULES[mode].format(count=fmt.count))
    roles_txt = "\n".join(f"- {r.name}: {r.description}" + (f"  => ĐÃ CHỈ ĐỊNH actor_id={r.actor_id}" if r.actor_id else "") for r in story.roles) or "(chưa liệt kê; hãy suy ra từ kịch bản)"
    o = story.overview
    user = (
        f"series_id: {a.series}\nSố tập: {fmt.count} | Thời lượng mỗi tập: {fmt.min_duration_sec}-{fmt.max_duration_sec} giây | Chế độ: {mode}\n\n"
        f"TỔNG QUAN\nTên: {o.title}\nThời lượng dự kiến: {o.total_minutes or '?'} phút\nThể loại: {o.genre}\nBối cảnh: {o.setting}\n\n"
        f"VAI TRONG CÂU CHUYỆN\n{roles_txt}\n\n"
        f"DIỄN VIÊN AI CÓ SẴN (chưa chỉ định)\n{roster_text(registry, set(pre.values()))}\n\n"
        f"KỊCH BẢN\n<script>\n{story.script.strip()}\n</script>\n\nHãy trả về SeriesOutline."
    )
    if a.dry_run:
        print("=== OUTLINE SYSTEM ===\n" + system + "\n=== OUTLINE USER ===\n" + user)
        raise SystemExit(0)
    outline, usage = generate_structured(system=system, user=user, schema=SeriesOutline, model=a.model)
    log_usage(a.series, "episodize.outline", usage.as_dict(), mode=mode)
    if len(outline.episodes) != fmt.count:
        raise SystemExit(f"outline returned {len(outline.episodes)} episodes, expected {fmt.count}")

    # Enforce the director's assignments and registry membership; unassigned roles get a slug id + placeholder later.
    roles: list[RoleCast] = []
    used: set[str] = set()
    pending: list[NewCharacter] = []
    desc_by_name = {r.name: r.description for r in story.roles}
    for rc in outline.roles:
        actor = pre.get(rc.role_name) or rc.actor_id
        by = "user" if rc.role_name in pre else rc.assigned_by
        if actor and (actor not in registry.ids() or actor in used):
            actor, by = None, "placeholder"
        if actor is None:
            actor, by = slugify_id(rc.role_name), "placeholder"
            if actor in registry.ids() or actor in used:
                actor = f"{actor}-2"
            desc = desc_by_name.get(rc.role_name, rc.reason)
            pending.append(NewCharacter(character_id=actor, display_name=rc.role_name, persona=desc,
                                        voice_description=f"{guess_gender(rc.role_name, desc)}; {desc[:120]}"))
        used.add(actor)
        roles.append(RoleCast(role_name=rc.role_name, role_type=rc.role_type, actor_id=actor, assigned_by=by, reason=rc.reason))
    prot = next((r for r in roles if r.role_name == outline.protagonist_role), roles[0])

    bible = SeriesBible(
        series_id=a.series, title=outline.title, logline=outline.logline, premise=outline.premise, tone=outline.tone,
        genre=outline.genre, overview=story.overview, mode=mode, protagonist_id=prot.actor_id or "", protagonist_role=prot.role_name,
        roles=roles, cast=[r.actor_id for r in roles if r.actor_id], pending_characters=pending, episode_format=fmt,
        episodes=outline.episodes, changelog=[f"{datetime.now(UTC).date()} episodize outline ({usage.model}, mode={mode})"],
    )
    p = naming.series_bible_path(a.series)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(bible.model_dump_json(indent=2), encoding="utf-8")
    for r in roles:
        print(f"cast: {r.role_name} -> {r.actor_id} ({r.assigned_by}; {r.reason[:60]})", file=sys.stderr)
    for nc in pending:
        print(f"WARNING role needs a voice: {nc.display_name} -> placeholder id {nc.character_id}", file=sys.stderr)
    a._new_characters = [nc.character_id for nc in pending]
    return bible


def run_draft(a: argparse.Namespace, bible: SeriesBible, story: StoryInput, registry: VoiceRegistry, n: int) -> Path:
    from pipeline.llm.gemini_client import generate_structured

    fmt = bible.episode_format
    plan = bible.episodes[n - 1]
    prev = bible.episodes[n - 2] if n > 1 else None
    nxt = bible.episodes[n] if n < len(bible.episodes) else None
    min_words = int(fmt.min_duration_sec * WORDS_PER_SEC)
    max_words = int(fmt.max_duration_sec * WORDS_PER_SEC * 1.15)
    desc_by_name = {r.name: r.description for r in story.roles}
    cast_lines = "\n".join(
        f"- {r.role_name} ({r.role_type}; diễn viên {r.actor_id}): {desc_by_name.get(r.role_name) or (registry.get(r.actor_id).persona if r.actor_id in registry.ids() else '')}"
        for r in bible.roles
    )
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
    user += "\nHãy trả về EpisodeDraft."
    if a.dry_run:
        print(f"=== DRAFT ep{n:02d} USER ===\n" + user[:3000])
        return naming.raw_script_path(a.series, n)

    temperature = 0.15 if bible.mode == "segment" else None
    draft, usage = generate_structured(system=system, user=user, schema=EpisodeDraft, model=a.model, temperature=temperature)
    if bible.mode == "segment":
        ratio, missing = verbatim_ratio(draft, story.script)
        if ratio < VERBATIM_MIN:
            log_usage(a.series, "episodize.draft.paraphrased", usage.as_dict(), episode=n, verbatim=round(ratio, 2))
            feedback = ("\n\nBạn đã DIỄN ĐẠT LẠI lời thoại. Các dòng sau không có nguyên văn trong kịch bản gốc:\n- "
                        + "\n- ".join(m[:120] for m in missing[:12])
                        + "\n\nViết lại toàn bộ tập: chép NGUYÊN VĂN từng lời thoại của tác giả trong đoạn này (chỉ tách dòng, thêm direction, thêm nội tâm ngắn).")
            draft, usage = generate_structured(system=system, user=user + feedback, schema=EpisodeDraft, model=a.model, temperature=0.1)
            ratio, _ = verbatim_ratio(draft, story.script)
        print(f"ep{n:02d}: verbatim {ratio:.0%}", file=sys.stderr)
    for _ in range(2 if bible.mode == "write" else 0):  # flash-lite under-writes; enforce the word floor (write mode only)
        if draft.word_count() >= min_words:
            break
        log_usage(a.series, "episodize.draft.short", usage.as_dict(), episode=n, words=draft.word_count())
        feedback = (f"\n\nBản nháp trước chỉ có {draft.word_count()} từ thoại, quá ngắn. Viết lại TOÀN BỘ tập với ít nhất {min_words} và tối đa "
                    f"{max_words} từ thoại. Giữ nguyên các beat và cliffhanger.")
        draft, usage = generate_structured(system=system, user=user + feedback, schema=EpisodeDraft, model=a.model)
    if draft.episode_number != n:
        raise SystemExit(f"draft returned episode {draft.episode_number}, expected {n}")
    known = {r.role_name for r in bible.roles} | {r.role_name.lower() for r in bible.roles}
    bad = sorted(s for s in draft.speakers() if s not in known and s.lower() not in known)
    if bad:
        raise SystemExit(f"episode {n}: draft uses speakers not in cast: {bad}")
    words = draft.word_count()
    log_usage(a.series, "episodize.draft", usage.as_dict(), episode=n, estimated_duration_sec=draft.estimated_duration_sec, words=words, scenes=len(draft.scenes))
    p = naming.raw_script_path(a.series, n)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(draft.render(), encoding="utf-8")
    print(f"ep{n:02d}: {len(draft.scenes)} scenes, {words} words, est {draft.estimated_duration_sec}s", file=sys.stderr)
    return p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--series", required=True)
    ap.add_argument("--episodes", type=int, default=30)
    ap.add_argument("--min-sec", type=int, default=50)
    ap.add_argument("--max-sec", type=int, default=70)
    ap.add_argument("--only", help="episode range to draft, e.g. 1-5 or 3,7")
    ap.add_argument("--outline-only", action="store_true")
    ap.add_argument("--force", action="store_true", help="overwrite existing drafts (never touches an existing outline)")
    ap.add_argument("--redo-outline", action="store_true", help="recompute series.json even if it exists (uses --episodes/--min-sec/--max-sec)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--model", default=None)
    a = ap.parse_args(argv)
    a._new_characters = []
    get_settings()

    registry = registry_io.load()
    story = load_story(a.series, registry)
    for r in story.roles:
        if r.actor_id and r.actor_id not in registry.ids():
            print(f"assigned actor {r.actor_id!r} for role {r.name!r} is not in the registry", file=sys.stderr)
            return 1
    fmt = EpisodeFormat(count=a.episodes, min_duration_sec=a.min_sec, max_duration_sec=a.max_sec)

    from pipeline.llm.gemini_client import LlmBlocked, LlmSchemaError, LlmTruncated

    bible_path = naming.series_bible_path(a.series)
    did_outline = False
    try:
        if bible_path.exists() and not a.redo_outline:
            bible = SeriesBible.model_validate_json(bible_path.read_text(encoding="utf-8"))
            if not bible.episodes:
                bible = run_outline(a, story, registry, fmt)
                did_outline = True
        else:
            bible = run_outline(a, story, registry, fmt)
            did_outline = True

        drafted, skipped = [], []
        if not a.outline_only:
            for n in parse_range(a.only, bible.episode_format.count):
                p = naming.raw_script_path(a.series, n)
                if p.exists() and not a.force:
                    skipped.append(n)
                    continue
                run_draft(a, bible, story, registry, n)
                drafted.append(n)
    except LlmSchemaError as e:
        print(f"schema validation failed:\n{e}", file=sys.stderr)
        return 2
    except (LlmBlocked, LlmTruncated) as e:
        print(str(e), file=sys.stderr)
        return 3

    print(json.dumps({"ok": True, "outline": did_outline, "mode": bible.mode, "drafted": drafted, "skipped": skipped,
                      "new_characters": a._new_characters, "dry_run": a.dry_run}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
