#!/usr/bin/env python3
"""AI Director: raw Vietnamese screenplay -> validated EpisodeScript JSON (pipeline stage [1]).

Speaker labels in the screenplay are ROLE names ("TÔ MẠN"); the Director outputs the ACTOR id
("ngan") in `character_id` using the role->actor map from series.json, plus `role_name`.
Anything the model leaves as a role name/slug is remapped after the call.

CLI
    parse_script.py --series <id> (--episode <n> | --episodes 1-30) [--model ...]
                    [--provider elevenlabs|minimax] [--dry-run] [--validate-only] [--force]

Exit codes: 0 ok, 1 usage/config error, 2 schema validation failed, 3 blocked/truncated.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from pipeline import naming  # noqa: E402
from pipeline import registry as registry_io  # noqa: E402
from pipeline.config import get_settings  # noqa: E402
from pipeline.schema import (  # noqa: E402
    APPROVED_AUDIO_TAGS,
    PROTAGONIST_ALIAS,
    EpisodeScript,
    SeriesBible,
    VoiceRegistry,
)

SYSTEM_PROMPT = """Bạn là Đạo diễn AI cho một series phim ngắn dạng audio bằng tiếng Việt. Bạn chuyển kịch bản thô của một tập thành JSON sản xuất để hệ thống TTS + dựng âm thanh render tự động.

Quy tắc bắt buộc:
- Mỗi VAI trong kịch bản do một DIỄN VIÊN AI (actor_id) thể hiện theo bảng phân vai bên dưới. `character_id` PHẢI là actor_id; `role_name` là tên vai. Không bịa vai mới; nếu gặp người nói lạ, gán cho vai gần nhất và ghi vào director_notes.
- Dòng có nhãn "(nội tâm)" là độc thoại nội tâm ngôi thứ nhất của nhân vật chính: type="monologue", character_id="{alias}". KHÔNG có người dẫn chuyện ngôi thứ ba.
- `text` là lời thoại nguyên văn (tiếng Việt, không tag). `tts_text` là cùng câu đó chuẩn bị cho máy đọc: có thể thêm tag và dấu câu để diễn, viết số bằng chữ.
- emotional_intensity 1-10 tính tương đối trên toàn series; chỉ dành 9-10 cho tối đa hai khoảnh khắc đỉnh của tập.
- acoustic_direction: ghi chú ngắn về cách diễn và không gian. pause_after_ms: 300-500 giữa các câu, tới 1500 sau khoảnh khắc quan trọng.
- Nhạc nền và hiệu ứng đang TẮT: bgm = null, sfx = [], ambience_tag = null.
- Không xuất thông tin thời gian tuyệt đối. Không thêm lời thoại không có trong kịch bản; được phép tách câu dài thành nhiều dòng.
- scene_id tuần tự sc01, sc02...; line_id dạng ep{{NN}}_sc{{NN}}_l{{NNN}}, đánh số lại từ l001 ở mỗi cảnh.
- Dòng thoại cuối cùng phải là cliffhanger; ghi lại vào trường cliffhanger.
"""

TAG_RULES_ELEVENLABS = (
    "Máy đọc là ElevenLabs v3. Trong tts_text CHỈ được dùng các tag sau, đặt trước phần lời bị ảnh hưởng: "
    + ", ".join(f"[{t}]" for t in sorted(APPROVED_AUDIO_TAGS))
    + ". Tối đa hai tag mỗi dòng. Dòng monologue nên bắt đầu bằng [internal monologue] hoặc [introspective]."
)
TAG_RULES_MINIMAX = "Máy đọc là MiniMax. KHÔNG dùng tag trong ngoặc vuông; thể hiện cách diễn qua emotion, pace, volume, dấu câu và acoustic_direction."


def build_prompt(raw: str, bible: SeriesBible, registry: VoiceRegistry, episode: int, provider: str) -> tuple[str, str]:
    tag_rules = TAG_RULES_ELEVENLABS if provider == "elevenlabs" else TAG_RULES_MINIMAX
    rows = []
    for r in bible.roles:
        actor = registry.get(r.actor_id) if r.actor_id in registry.ids() else None
        rows.append(f"- VAI \"{r.role_name}\" ({r.role_type}) -> actor_id: {r.actor_id}"
                    + (f" | {actor.display_name}, giọng: {actor.voice_description}" if actor else "")
                    + (" [NHÂN VẬT CHÍNH, kể chuyện ngôi thứ nhất]" if r.role_name == bible.protagonist_role else ""))
    if not rows:  # legacy bible without roles
        rows = [f"- actor_id: {cid} | {registry.get(cid).display_name}" + (" [NHÂN VẬT CHÍNH]" if cid == bible.protagonist_id else "")
                for cid in bible.cast if cid in registry.ids()]
    plan = bible.episodes[episode - 1] if len(bible.episodes) >= episode else None
    system = (SYSTEM_PROMPT.format(alias=PROTAGONIST_ALIAS) + "\n" + tag_rules
              + f"\n\nSeries: {bible.title}\nTiền đề: {bible.premise}\nGiọng điệu: {bible.tone}\n\nBẢNG PHÂN VAI:\n" + "\n".join(rows) + "\n")
    user = (f"series_id: {bible.series_id}\nepisode_number: {episode}\ntarget_duration_sec: {bible.episode_format.max_duration_sec}\n"
            + (f"Cliffhanger dự kiến: {plan.cliffhanger}\n" if plan else "")
            + f"\nKịch bản thô:\n<script>\n{raw}\n</script>\n\nHãy trả về EpisodeScript.")
    return system, user


def parse_episode(a: argparse.Namespace, episode: int, bible: SeriesBible, registry: VoiceRegistry, provider: str) -> dict:
    out_path = naming.parsed_script_path(a.series, episode)
    raw_path = naming.raw_script_path(a.series, episode)
    if not raw_path.exists():
        raise SystemExit(f"raw script not found: {raw_path}")
    if out_path.exists() and not a.force and not a.dry_run:
        raise SystemExit(f"parsed file exists, use --force: {out_path}")

    system, user = build_prompt(raw_path.read_text(encoding="utf-8"), bible, registry, episode, provider)
    if a.dry_run:
        print("=== SYSTEM ===\n" + system + "\n=== USER ===\n" + user)
        return {"episode": episode, "dry_run": True}

    from pipeline.llm.gemini_client import generate_structured

    script, usage = generate_structured(system=system, user=user, schema=EpisodeScript, model=a.model)

    script.resolve_protagonist(bible.protagonist_id)
    mapping = bible.role_to_actor()
    remapped = script.remap_characters(mapping)
    actor_to_role = bible.actor_to_role()
    for _, ln in script.all_lines():
        if not ln.role_name and ln.character_id in actor_to_role:
            ln.role_name = actor_to_role[ln.character_id]
    used = {ln.character_id for _, ln in script.all_lines() if ln.type.value != "pause"}
    unknown = sorted(used - registry.ids())
    if unknown:
        raise SystemExit(f"episode {episode}: unknown character_ids in output: {unknown} (cast: {bible.cast})")
    off_cast = sorted(used - set(bible.cast))
    if off_cast:
        raise SystemExit(f"episode {episode}: characters not in series cast: {off_cast}")
    if script.series_id != a.series or script.episode_number != episode:
        raise SystemExit(f"episode {episode}: series_id/episode_number in output do not match")
    script.characters_used = sorted(used)
    script = EpisodeScript.model_validate(script.model_dump())

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(script.model_dump_json(indent=2), encoding="utf-8")
    log = naming.run_log_path(a.series)
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": datetime.now(UTC).isoformat(timespec="seconds"), "stage": "parse_script", "episode": episode, **usage.as_dict()}) + "\n")
    peaks = [ln.line_id for _, ln in script.all_lines() if ln.emotional_intensity >= 9]
    return {"episode": episode, "lines": len(script.all_lines()), "scenes": len(script.scenes), "peak_lines": peaks,
            "remapped": remapped, "path": str(out_path)}


def parse_range(spec: str) -> list[int]:
    out: set[int] = set()
    for part in spec.split(","):
        if "-" in part:
            x, y = part.split("-", 1)
            out.update(range(int(x), int(y) + 1))
        else:
            out.add(int(part))
    return sorted(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--series", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--episode", type=int)
    g.add_argument("--episodes", help="range, e.g. 1-30 or 2,5")
    ap.add_argument("--model", default=None)
    ap.add_argument("--provider", choices=["elevenlabs", "minimax"], default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--validate-only", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)

    settings = get_settings()
    provider = a.provider or settings.tts_provider
    episodes = [a.episode] if a.episode else parse_range(a.episodes)

    if a.validate_only:
        results = [{"episode": n, "lines": len(EpisodeScript.model_validate_json(naming.parsed_script_path(a.series, n).read_text(encoding="utf-8")).all_lines())} for n in episodes]
        print(json.dumps({"ok": True, "episodes": results}))
        return 0

    bible = SeriesBible.model_validate_json(naming.series_bible_path(a.series).read_text(encoding="utf-8"))
    registry = registry_io.load()

    from pipeline.llm.gemini_client import LlmBlocked, LlmSchemaError, LlmTruncated

    results = []
    try:
        for n in episodes:
            results.append(parse_episode(a, n, bible, registry, provider))
    except LlmSchemaError as e:
        print(f"schema validation failed:\n{e}", file=sys.stderr)
        return 2
    except (LlmBlocked, LlmTruncated) as e:
        print(str(e), file=sys.stderr)
        return 3

    print(json.dumps({"ok": True, **(results[0] if len(results) == 1 else {"episodes": results})}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
