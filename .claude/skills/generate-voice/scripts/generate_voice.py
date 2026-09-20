#!/usr/bin/env python3
"""TTS stem generation for a parsed episode (pipeline stage [3]).

Modes
    episode (default)
        generate_voice.py --series <id> --episode <n> [--provider elevenlabs|gemini] [--model-override <model_id>]
                          [--batching auto|line|scene] [--lines id,...] [--force] [--dry-run] [--no-normalize] [--concurrency N]
    one
        generate_voice.py one --provider elevenlabs --voice-id <id> --text "<text>" --out <path.wav> [--model-id eleven_v3]
                          [--stability 0.5] [--similarity-boost 0.75] [--style 0.0] [--speaker-boost]
        generate_voice.py one --provider gemini --voice-id Leda --text "<text>" --out <path.wav> [--direction "giọng buồn, chậm"]

Batching (how many requests an episode costs)
    line   one request per spoken line -> stems/epNN/ep01_sc01_l001_<actor>_<type>.wav (ElevenLabs always; Gemini optional)
    scene  Gemini only: one request per chunk (a run of lines in a scene with <= 2 actors, multi-speaker mode)
           -> stems/epNN/ep01_sc01_c01_chunk.wav. Typical episodes need 1-3 requests instead of 8-12.
    auto   scene on Gemini, line on ElevenLabs (default; AI_AUDIO_TTS_BATCHING)
    Either way stems/epNN/render.json lists the render units so assemble-audio and qa-audio know what to expect.

Behaviour
    * character_id -> voice profile from library/voice-ips.json (Voice IP anchoring, D7); the voice used is the one
      stored for the chosen provider (ElevenLabs voice_id or Gemini voice name).
    * tts_text -> Vietnamese normalizer -> provider-specific tag handling (D1), via pipeline.providers.mapping.
    * Sidecar .meta.json per unit with hash, settings, cost, alignment (ElevenLabs) or covered line ids (chunks).
    * Skips units whose sidecar hash matches unless --force. Bounded thread pool (Gemini: serial, per-minute limits).
    * ElevenLabs 402 "paid plan required" on a voice -> re-rendered with the actor's fallback premade voice and
      flagged (voice_fallback in the sidecar, placeholder_voices in the summary). No cross-engine fallback.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from pipeline import naming  # noqa: E402
from pipeline import registry as registry_io  # noqa: E402
from pipeline.casting import guess_gender, placeholder_voice  # noqa: E402
from pipeline.chunking import Chunk, build_transcript, chunk_episode  # noqa: E402
from pipeline.config import get_settings  # noqa: E402
from pipeline.providers import (  # noqa: E402
    DEFAULT_MODEL,
    PROVIDER_NAMES,
    TtsRequest,
    default_concurrency,
    get_provider,
)
from pipeline.providers.base import ProviderError  # noqa: E402
from pipeline.providers.mapping import settings_for_line, text_for_provider  # noqa: E402
from pipeline.schema import EpisodeScript, LineType, VoiceRegistry  # noqa: E402
from pipeline.text.vi_normalize import normalize_vi  # noqa: E402

BATCHING = ("auto", "line", "scene")


@dataclass
class Unit:
    """One render unit: a line (line mode) or a chunk of lines (scene mode)."""

    id: str
    req: TtsRequest
    out: Path
    line_ids: list[str]
    scene_id: str
    actors: list[str]
    pause_after_ms: int


def resolve_batching(requested: str, provider: str) -> str:
    if requested == "auto":
        return "scene" if provider == "gemini" else "line"
    if requested == "scene" and provider != "gemini":
        raise SystemExit("--batching scene needs the Gemini engine (multi-speaker requests); ElevenLabs renders per line")
    return requested


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


def plan_lines(script: EpisodeScript, registry: VoiceRegistry, provider: str, only: set[str] | None,
               model_override: str | None, normalize: bool) -> list[Unit]:
    lines = [(sc, ln) for sc, ln in script.all_lines() if ln.type != LineType.pause]
    units: list[Unit] = []
    for idx, (scene, line) in enumerate(lines):
        if only and line.line_id not in only:
            continue
        prev_text = lines[idx - 1][1].text if idx > 0 and lines[idx - 1][1].character_id == line.character_id else None
        next_text = lines[idx + 1][1].text if idx + 1 < len(lines) and lines[idx + 1][1].character_id == line.character_id else None
        try:
            req = build_request(line, registry, provider, model_override, normalize, prev_text, next_text)
        except KeyError as e:
            raise SystemExit(f"{e} (assign one in the Characters page or voice-registry add)") from e
        out = naming.stems_dir(script.series_id, script.episode_number) / naming.stem_name_from_line_id(
            line.line_id, line.character_id, line.type.value)
        units.append(Unit(line.line_id, req, out, [line.line_id], scene.scene_id, [line.character_id], line.pause_after_ms))
    return units


def chunk_request(chunk: Chunk, registry: VoiceRegistry, model_id: str, normalize: bool) -> TtsRequest:
    for a in chunk.actors:
        if a not in registry.ids() or "gemini" not in registry.get(a).providers:
            raise SystemExit(f"{a} has no Gemini voice (assign one in the Characters page or voice-registry add)")
    header, transcript, speakers = build_transcript(chunk, registry, model_id, normalize=normalize)
    return TtsRequest(provider="gemini", model_id=model_id, voice_id=chunk.chunk_id if len(speakers) > 1 else speakers[0][1],
                      text=transcript, settings={"style": header}, line_id=chunk.chunk_id, speakers=speakers)


def plan_chunks(script: EpisodeScript, registry: VoiceRegistry, only: set[str] | None, model_override: str | None,
                normalize: bool) -> list[Unit]:
    units: list[Unit] = []
    for chunk in chunk_episode(script):
        if only and not (set(chunk.line_ids) & only):
            continue
        model_id = model_override or registry.get(chunk.actors[0]).providers["gemini"].model_id
        req = chunk_request(chunk, registry, model_id, normalize)
        out = naming.stems_dir(script.series_id, script.episode_number) / naming.chunk_stem_name_from_id(chunk.chunk_id)
        units.append(Unit(chunk.chunk_id, req, out, chunk.line_ids, chunk.scene_id, list(chunk.actors), chunk.pause_after_ms))
    return units


def write_manifest(script: EpisodeScript, batching: str, units: list[Unit]) -> Path:
    p = naming.render_manifest_path(script.series_id, script.episode_number)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "batching": batching, "episode": script.episode_number, "written_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "units": [{"id": u.id, "path": u.out.name, "scene_id": u.scene_id, "line_ids": u.line_ids, "actors": u.actors,
                   "pause_after_ms": u.pause_after_ms, "provider": u.req.provider, "model_id": u.req.model_id} for u in units],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def is_cached(req: TtsRequest, out: Path) -> bool:
    meta = naming.meta_path(out)
    if not (out.exists() and meta.exists()):
        return False
    try:
        return json.loads(meta.read_text())["hash"] == req.content_hash()
    except (json.JSONDecodeError, KeyError):
        return False


def write_meta(out: Path, req: TtsRequest, info: dict, elapsed: float, unit: Unit | None = None) -> None:
    extra = {"line_ids": unit.line_ids, "actors": unit.actors, "scene_id": unit.scene_id} if unit else {}
    naming.meta_path(out).write_text(json.dumps(
        {"hash": req.content_hash(), "request": req.as_dict(), "rendered_at": datetime.now(UTC).isoformat(timespec="seconds"),
         "elapsed_s": round(elapsed, 2), **extra, **info}, ensure_ascii=False, indent=2))


def log_run(series: str, episode: int, req: TtsRequest, info: dict, unit: Unit | None = None) -> None:
    p = naming.run_log_path(series)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": datetime.now(UTC).isoformat(timespec="seconds"), "stage": "generate_voice", "episode": episode,
                            "line_id": req.line_id, "lines": len(unit.line_ids) if unit else 1, "provider": req.provider,
                            "model_id": req.model_id, "voice_id": req.voice_id, "characters_billed": info.get("characters_billed"),
                            "tokens_in": info.get("tokens_in"), "tokens_out": info.get("tokens_out"),
                            "duration_ms": info.get("duration_ms")}) + "\n")


def run_episode(a: argparse.Namespace) -> int:
    settings = get_settings()
    provider = a.provider or settings.tts_provider
    if provider not in PROVIDER_NAMES:
        raise SystemExit(f"unknown provider {provider!r}; expected one of {PROVIDER_NAMES}")
    batching = resolve_batching(a.batching or settings.tts_batching, provider)
    model_override = a.model_override or (settings.tts_model if not a.provider or a.provider == settings.tts_provider else None)
    normalize = settings.normalize_vi and not a.no_normalize
    script = EpisodeScript.model_validate_json(naming.parsed_script_path(a.series, a.episode).read_text(encoding="utf-8"))
    registry = registry_io.load()
    only = set(a.lines.split(",")) if a.lines else None
    all_units = (plan_chunks(script, registry, None, model_override, normalize) if batching == "scene"
                 else plan_lines(script, registry, provider, None, model_override, normalize))
    plan = [u for u in all_units if not only or (set(u.line_ids) & only)]
    lines_by_id = {ln.line_id: ln for _, ln in script.all_lines()}

    todo = [u for u in plan if a.force or not is_cached(u.req, u.out)]
    chars = sum(len(u.req.text) for u in todo)
    if a.dry_run:
        for u in todo:
            print(json.dumps({"out": u.out.name, "lines": u.line_ids, **u.req.as_dict()}, ensure_ascii=False))
        print(json.dumps({"ok": True, "dry_run": True, "provider": provider, "batching": batching, "planned": len(plan),
                          "to_render": len(todo), "characters": chars, "lines": sum(len(u.line_ids) for u in plan)}))
        return 0

    engine = get_provider(provider)

    def render(u: Unit) -> tuple[str, dict, str]:
        req, out = u.req, u.out
        out.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        try:
            info = engine.synthesize(req, out)
        except ProviderError as e:
            if provider == "elevenlabs" and e.status == 402 and "voice" in str(e).lower():
                # Account tier rejects this voice (library/PVC voice on Free tier). Degrade to a
                # premade placeholder of the same gender so the run completes; QA flags the stem.
                line = lines_by_id[req.line_id]
                profile = registry.get(line.character_id)
                pv = profile.providers[provider]
                alt = pv.fallback_voice_id or placeholder_voice(profile.gender or guess_gender(profile.voice_description, profile.persona))
                alt_req = TtsRequest(provider=req.provider, model_id=req.model_id, voice_id=alt, text=req.text,
                                     settings=req.settings, line_id=req.line_id)
                info = engine.synthesize(alt_req, out)
                info["voice_fallback"] = {"requested": req.voice_id, "used": alt, "reason": str(e)[:160]}
                write_meta(out, alt_req, info, time.time() - t0, u)
                log_run(a.series, a.episode, alt_req, info, u)
                return u.id, info, f"{provider} (placeholder voice)"
            raise
        write_meta(out, req, info, time.time() - t0, u)
        log_run(a.series, a.episode, req, info, u)
        return u.id, info, provider

    workers = a.concurrency if a.concurrency else default_concurrency(provider)
    rendered, failed, fell_back = 0, [], []
    placeholder_hits: set[str] = set()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(render, u): u.id for u in todo}
        for fut in as_completed(futures):
            uid = futures[fut]
            try:
                _, info, used_provider = fut.result()
            except Exception as e:  # noqa: BLE001 - record and continue; QA catches gaps
                print(f"{uid}: {type(e).__name__}: {e}", file=sys.stderr)
                failed.append(uid)
                continue
            rendered += 1
            if used_provider != provider:
                fell_back.append(uid)
                if "voice_fallback" in info:
                    placeholder_hits.add(info["voice_fallback"]["requested"])
            print(f"{uid}: {info.get('duration_ms')} ms, {info.get('characters_billed')} chars, {used_provider}", file=sys.stderr)

    write_manifest(script, batching, all_units)
    if placeholder_hits:
        print(f"WARNING: account tier rejected voice(s) {sorted(placeholder_hits)}; rendered with placeholder premade voices. "
              f"Upgrade the ElevenLabs plan and re-run with --force to use the real Voice IPs.", file=sys.stderr)
    print(json.dumps({"ok": not failed, "provider": provider, "batching": batching, "model": model_override or "registry",
                      "planned": len(plan), "lines": sum(len(u.line_ids) for u in plan), "rendered": rendered,
                      "cached": len(plan) - len(todo), "failed": sorted(failed), "fell_back": sorted(fell_back),
                      "placeholder_voices": sorted(placeholder_hits)}))
    return 0 if not failed else 2


def run_one(a: argparse.Namespace) -> int:
    model_id = a.model_id or DEFAULT_MODEL[a.provider]
    if a.provider == "gemini":
        s = {"style": a.direction} if a.direction else {}
    else:
        s = {"stability": a.stability, "similarity_boost": a.similarity_boost, "use_speaker_boost": a.speaker_boost}
        if a.style is not None:
            s["style"] = a.style
    text = normalize_vi(a.text) if not a.no_normalize else a.text
    req = TtsRequest(provider=a.provider, model_id=model_id, voice_id=a.voice_id, text=text, settings=s)
    if a.dry_run:
        print(json.dumps(req.as_dict(), ensure_ascii=False, indent=2))
        return 0
    out = Path(a.out)
    t0 = time.time()
    info = get_provider(a.provider).synthesize(req, out)
    write_meta(out, req, info, time.time() - t0)
    print(json.dumps({"ok": True, "out": a.out, **{k: v for k, v in info.items() if k not in ("alignment", "prompt")}}))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode")

    ep = sub.add_parser("episode", help="render all stems for an episode (default)")
    ep.add_argument("--series", required=True)
    ep.add_argument("--episode", type=int, required=True)
    ep.add_argument("--provider", choices=PROVIDER_NAMES)
    ep.add_argument("--model-override", help="force a model_id for this run, e.g. eleven_multilingual_v2 or gemini-2.5-flash-preview-tts")
    ep.add_argument("--batching", choices=BATCHING, default=None, help="auto (default): scene on Gemini, line on ElevenLabs")
    ep.add_argument("--lines", help="comma-separated line_ids to (re)render (scene mode: their chunks)")
    ep.add_argument("--force", action="store_true")
    ep.add_argument("--dry-run", action="store_true")
    ep.add_argument("--no-normalize", action="store_true")
    ep.add_argument("--concurrency", type=int, default=None, help="default: 2 for ElevenLabs, 1 for Gemini")
    ep.set_defaults(fn=run_episode)

    one = sub.add_parser("one", help="synthesize a single text (voice audition)")
    one.add_argument("--provider", choices=PROVIDER_NAMES, default="elevenlabs")
    one.add_argument("--voice-id", required=True, help="ElevenLabs voice_id or Gemini voice name")
    one.add_argument("--text", required=True)
    one.add_argument("--out", required=True)
    one.add_argument("--model-id", default=None)
    one.add_argument("--stability", type=float, default=0.5)
    one.add_argument("--similarity-boost", type=float, default=0.75)
    one.add_argument("--style", type=float, default=None)
    one.add_argument("--speaker-boost", action="store_true")
    one.add_argument("--direction", help="Gemini: natural-language acting direction (Vietnamese)")
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
