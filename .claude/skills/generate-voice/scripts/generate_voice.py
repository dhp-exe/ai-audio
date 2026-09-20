#!/usr/bin/env python3
"""TTS stem generation for a parsed episode (pipeline stage [3]).

Modes
    episode (default)
        generate_voice.py --series <id> --episode <n> [--provider elevenlabs|minimax]
                          [--model-override <model_id>] [--lines id,...] [--force] [--dry-run]
                          [--no-normalize] [--concurrency 3] [--no-fallback]
    one
        generate_voice.py one --voice-id <id> --text "<text>" --out <path.wav> [--model-id eleven_v3]
                          [--stability 0.5] [--similarity-boost 0.75] [--style 0.0] [--speaker-boost]

Behaviour
    * character_id -> voice profile from library/voice-ips.json (Voice IP anchoring, D7).
    * tts_text -> Vietnamese normalizer -> provider-specific tag handling (D1), via pipeline.providers.mapping.
    * One WAV per line named by pipeline.naming; sidecar .meta.json with hash, settings, cost, alignment.
    * Skips lines whose sidecar hash matches unless --force. Bounded thread pool.
    * On a retryable provider error, retries the line on the fallback provider if the character has a
      voice there (unless --no-fallback).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from pipeline import naming  # noqa: E402
from pipeline import registry as registry_io  # noqa: E402
from pipeline.casting import guess_gender, placeholder_voice  # noqa: E402
from pipeline.config import get_settings  # noqa: E402
from pipeline.providers import PROVIDER_NAMES, TtsRequest, get_provider  # noqa: E402
from pipeline.providers.base import ProviderError  # noqa: E402
from pipeline.providers.mapping import settings_for_line, text_for_provider  # noqa: E402
from pipeline.schema import EpisodeScript, LineType, VoiceRegistry  # noqa: E402
from pipeline.text.vi_normalize import normalize_vi  # noqa: E402


def build_request(line, registry: VoiceRegistry, provider: str, model_override: str | None, normalize: bool,
                  prev_text: str | None = None, next_text: str | None = None) -> TtsRequest:
    profile = registry.get(line.character_id)
    if provider not in profile.providers:
        raise KeyError(f"{line.character_id} has no voice on provider {provider}")
    pv = profile.providers[provider]
    model_id = model_override or pv.model_id
    return TtsRequest(
        provider=provider, model_id=model_id, voice_id=pv.voice_id,
        text=text_for_provider(line, provider, model_id, normalize=normalize),
        settings=settings_for_line(line, provider, model_id, pv.default_settings),
        line_id=line.line_id, previous_text=prev_text, next_text=next_text,
    )


def plan_episode(script: EpisodeScript, registry: VoiceRegistry, provider: str, only: set[str] | None,
                 model_override: str | None, normalize: bool) -> list[tuple[TtsRequest, Path]]:
    lines = [ln for _, ln in script.all_lines() if ln.type != LineType.pause]
    plan = []
    for idx, line in enumerate(lines):
        if only and line.line_id not in only:
            continue
        # prosody context: neighbouring lines by the same speaker
        prev_text = lines[idx - 1].text if idx > 0 and lines[idx - 1].character_id == line.character_id else None
        next_text = lines[idx + 1].text if idx + 1 < len(lines) and lines[idx + 1].character_id == line.character_id else None
        try:
            req = build_request(line, registry, provider, model_override, normalize, prev_text, next_text)
        except KeyError as e:
            raise SystemExit(f"{e} (voice-registry add)") from e
        out = naming.stems_dir(script.series_id, script.episode_number) / naming.stem_name_from_line_id(
            line.line_id, line.character_id, line.type.value)
        plan.append((req, out))
    return plan


def is_cached(req: TtsRequest, out: Path) -> bool:
    meta = naming.meta_path(out)
    if not (out.exists() and meta.exists()):
        return False
    try:
        return json.loads(meta.read_text())["hash"] == req.content_hash()
    except (json.JSONDecodeError, KeyError):
        return False


def write_meta(out: Path, req: TtsRequest, info: dict, elapsed: float) -> None:
    naming.meta_path(out).write_text(json.dumps(
        {"hash": req.content_hash(), "request": req.as_dict(), "rendered_at": datetime.now(UTC).isoformat(timespec="seconds"),
         "elapsed_s": round(elapsed, 2), **info}, ensure_ascii=False, indent=2))


def log_run(series: str, episode: int, req: TtsRequest, info: dict) -> None:
    p = naming.run_log_path(series)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": datetime.now(UTC).isoformat(timespec="seconds"), "stage": "generate_voice", "episode": episode,
                            "line_id": req.line_id, "provider": req.provider, "model_id": req.model_id,
                            "characters_billed": info.get("characters_billed"), "duration_ms": info.get("duration_ms")}) + "\n")


def run_episode(a: argparse.Namespace) -> int:
    settings = get_settings()
    provider = a.provider or settings.tts_provider
    normalize = settings.normalize_vi and not a.no_normalize
    script = EpisodeScript.model_validate_json(naming.parsed_script_path(a.series, a.episode).read_text(encoding="utf-8"))
    registry = registry_io.load()
    only = set(a.lines.split(",")) if a.lines else None
    plan = plan_episode(script, registry, provider, only, a.model_override, normalize)
    lines_by_id = {ln.line_id: ln for _, ln in script.all_lines()}

    todo = [(r, o) for r, o in plan if a.force or not is_cached(r, o)]
    chars = sum(len(r.text) for r, _ in todo)
    if a.dry_run:
        for r, o in todo:
            print(json.dumps({"out": o.name, **r.as_dict()}, ensure_ascii=False))
        print(json.dumps({"ok": True, "dry_run": True, "provider": provider, "planned": len(plan), "to_render": len(todo), "characters": chars}))
        return 0

    primary = get_provider(provider)
    fallback_name = settings.tts_fallback_provider if (not a.no_fallback and settings.tts_fallback_provider != provider) else None
    fallback = None

    def render(req: TtsRequest, out: Path) -> tuple[str, dict, str]:
        nonlocal fallback
        out.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        try:
            info = primary.synthesize(req, out)
            used = req
        except ProviderError as e:
            if e.status == 402 and "voice" in str(e).lower():
                # Account tier rejects this voice (library/PVC voice on Free tier). Degrade to a
                # premade placeholder of the same gender so the run completes; QA flags the stem.
                line = lines_by_id[req.line_id]
                profile = registry.get(line.character_id)
                pv = profile.providers[provider]
                alt = pv.fallback_voice_id or placeholder_voice(profile.gender or guess_gender(profile.voice_description, profile.persona))
                alt_req = TtsRequest(provider=req.provider, model_id=req.model_id, voice_id=alt, text=req.text,
                                     settings=req.settings, line_id=req.line_id)
                info = primary.synthesize(alt_req, out)
                info["voice_fallback"] = {"requested": req.voice_id, "used": alt, "reason": str(e)[:160]}
                used = alt_req
                write_meta(out, used, info, time.time() - t0)
                log_run(a.series, a.episode, used, info)
                return req.line_id, info, f"{provider} (placeholder voice)"
            if not (e.retryable and fallback_name):
                raise
            line = lines_by_id[req.line_id]
            try:
                fb_req = build_request(line, registry, fallback_name, None, normalize)
            except KeyError:
                raise e from None
            if fallback is None:
                fallback = get_provider(fallback_name)
            info = fallback.synthesize(fb_req, out)
            info["fallback_from"] = f"{req.provider}:{e}"
            used = fb_req
        write_meta(out, used, info, time.time() - t0)
        log_run(a.series, a.episode, used, info)
        return req.line_id, info, used.provider

    rendered, failed, fell_back = 0, [], []
    placeholder_hits: set[str] = set()
    with ThreadPoolExecutor(max_workers=max(1, a.concurrency)) as pool:
        futures = {pool.submit(render, r, o): r.line_id for r, o in todo}
        for fut in as_completed(futures):
            lid = futures[fut]
            try:
                _, info, used_provider = fut.result()
            except Exception as e:  # noqa: BLE001 - record and continue; QA catches gaps
                print(f"{lid}: {type(e).__name__}: {e}", file=sys.stderr)
                failed.append(lid)
                continue
            rendered += 1
            if used_provider != provider:
                fell_back.append(lid)
                if "placeholder voice" in used_provider and "voice_fallback" in info:
                    placeholder_hits.add(info["voice_fallback"]["requested"])
            print(f"{lid}: {info.get('duration_ms')} ms, {info.get('characters_billed')} chars, {used_provider}", file=sys.stderr)

    if placeholder_hits:
        print(f"WARNING: account tier rejected voice(s) {sorted(placeholder_hits)}; rendered with placeholder premade voices. "
              f"Upgrade the ElevenLabs plan and re-run with --force to use the real Voice IPs.", file=sys.stderr)
    print(json.dumps({"ok": not failed, "provider": provider, "planned": len(plan), "rendered": rendered,
                      "cached": len(plan) - len(todo), "failed": sorted(failed), "fell_back": sorted(fell_back),
                      "placeholder_voices": sorted(placeholder_hits)}))
    return 0 if not failed else 2


def run_one(a: argparse.Namespace) -> int:
    s = {"stability": a.stability, "similarity_boost": a.similarity_boost, "use_speaker_boost": a.speaker_boost}
    if a.style is not None:
        s["style"] = a.style
    text = normalize_vi(a.text) if not a.no_normalize else a.text
    req = TtsRequest(provider=a.provider, model_id=a.model_id, voice_id=a.voice_id, text=text, settings=s)
    if a.dry_run:
        print(json.dumps(req.as_dict(), ensure_ascii=False, indent=2))
        return 0
    out = Path(a.out)
    t0 = time.time()
    info = get_provider(a.provider).synthesize(req, out)
    write_meta(out, req, info, time.time() - t0)
    print(json.dumps({"ok": True, "out": a.out, **{k: v for k, v in info.items() if k != "alignment"}}))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode")

    ep = sub.add_parser("episode", help="render all stems for an episode (default)")
    ep.add_argument("--series", required=True)
    ep.add_argument("--episode", type=int, required=True)
    ep.add_argument("--provider", choices=PROVIDER_NAMES)
    ep.add_argument("--model-override", help="force a model_id for this run, e.g. eleven_multilingual_v2")
    ep.add_argument("--lines", help="comma-separated line_ids to (re)render")
    ep.add_argument("--force", action="store_true")
    ep.add_argument("--dry-run", action="store_true")
    ep.add_argument("--no-normalize", action="store_true")
    ep.add_argument("--no-fallback", action="store_true")
    ep.add_argument("--concurrency", type=int, default=3)
    ep.set_defaults(fn=run_episode)

    one = sub.add_parser("one", help="synthesize a single text (voice audition)")
    one.add_argument("--provider", choices=PROVIDER_NAMES, default="elevenlabs")
    one.add_argument("--voice-id", required=True)
    one.add_argument("--text", required=True)
    one.add_argument("--out", required=True)
    one.add_argument("--model-id", default="eleven_v3")
    one.add_argument("--stability", type=float, default=0.5)
    one.add_argument("--similarity-boost", type=float, default=0.75)
    one.add_argument("--style", type=float, default=None)
    one.add_argument("--speaker-boost", action="store_true")
    one.add_argument("--no-normalize", action="store_true")
    one.add_argument("--dry-run", action="store_true")
    one.set_defaults(fn=run_one)

    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] not in ("episode", "one", "-h", "--help"):
        argv = ["episode", *argv]
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
