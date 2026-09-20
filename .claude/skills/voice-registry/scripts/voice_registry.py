#!/usr/bin/env python3
"""Global Voice IP registry manager for library/voice-ips.json (decision D7).

Subcommands
    init      create an empty, locked registry
    add       add a character (actor) or a provider voice anchor (IP assets need --unlock to change)
    list      print the roster
    validate  check a series cast (or a parsed episode) has voices on the active provider

The same registry is edited from the web client's Characters page; both go through pipeline.registry
so the lock rule lives in one place.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from pipeline import naming  # noqa: E402
from pipeline import registry as registry_io  # noqa: E402
from pipeline.providers.catalog import DEFAULT_MODEL, PROVIDER_NAMES, gemini_voice  # noqa: E402
from pipeline.registry import RegistryLocked  # noqa: E402
from pipeline.schema import CharacterProfile, EpisodeScript, ProviderVoice, SeriesBible, VoiceRegistry  # noqa: E402


def cmd_init(a: argparse.Namespace) -> int:
    p = naming.registry_path()
    if p.exists() and not a.force:
        raise SystemExit(f"exists: {p}")
    registry_io.save(VoiceRegistry(locked=True, default_provider=a.provider, characters=[]), "init")
    print(json.dumps({"ok": True, "path": str(p)}))
    return 0


def cmd_add(a: argparse.Namespace) -> int:
    reg = registry_io.load()
    if a.provider == "gemini" and not gemini_voice(a.voice_id):
        raise SystemExit(f"{a.voice_id!r} is not a Gemini prebuilt voice name (see pipeline/providers/catalog.py)")
    voice = ProviderVoice(voice_id=a.voice_id, model_id=a.model_id or DEFAULT_MODEL[a.provider], voice_url=a.voice_url,
                          fallback_voice_id=a.fallback_voice_id,
                          default_settings=json.loads(a.default_settings) if a.default_settings else {})
    existing = next((c for c in reg.characters if c.character_id == a.character_id), None)
    if existing:
        profile = existing.model_copy(update={k: v for k, v in {
            "display_name": a.display_name, "persona": a.persona, "voice_description": a.voice_description,
            "gender": a.gender, "age": a.age, "tags": a.tags.split(",") if a.tags else None}.items() if v})
        profile.providers = {a.provider: voice}
    else:
        if not (a.display_name and a.persona and a.voice_description):
            raise SystemExit("new character needs --display-name, --persona, --voice-description")
        profile = CharacterProfile(character_id=a.character_id, display_name=a.display_name, persona=a.persona,
                                   voice_description=a.voice_description, gender=a.gender, age=a.age,
                                   tags=[t.strip() for t in a.tags.split(",")] if a.tags else [], language=a.language,
                                   providers={a.provider: voice}, is_ip_asset=not a.one_off)
    try:
        _, entry = registry_io.upsert(profile, unlock=a.unlock)
    except RegistryLocked as e:
        raise SystemExit(str(e)) from e
    print(json.dumps({"ok": True, "character_id": a.character_id, "changelog": entry, "path": str(naming.registry_path())}))
    return 0


def cmd_list(_a: argparse.Namespace) -> int:
    reg = registry_io.load()
    for c in reg.characters:
        providers = ", ".join(f"{k}:{v.voice_id}@{v.model_id}" + (f"(fb {v.fallback_voice_id})" if v.fallback_voice_id else "") for k, v in c.providers.items())
        meta = "/".join(x for x in (c.gender or "", c.age or "") if x)
        print(f"{c.character_id:16} {c.display_name:20} {meta:14} ip={c.is_ip_asset!s:5} {providers or '(no voice)'}")
    print(json.dumps({"ok": True, "count": len(reg.characters), "locked": reg.locked}))
    return 0


def cmd_validate(a: argparse.Namespace) -> int:
    reg = registry_io.load()
    provider = a.provider or reg.default_provider
    if a.episode is not None:
        script = EpisodeScript.model_validate_json(naming.parsed_script_path(a.series, a.episode).read_text(encoding="utf-8"))
        used = {ln.character_id for _, ln in script.all_lines() if ln.type.value != "pause"}
    else:
        bible = SeriesBible.model_validate_json(naming.series_bible_path(a.series).read_text(encoding="utf-8"))
        used = set(bible.cast)
    problems = []
    for cid in sorted(used):
        if cid not in reg.ids():
            problems.append(f"{cid}: not in registry")
        elif provider not in reg.get(cid).providers:
            problems.append(f"{cid}: no voice on provider {provider}")
    for p in problems:
        print(p, file=sys.stderr)
    print(json.dumps({"ok": not problems, "provider": provider, "problems": len(problems)}))
    return 0 if not problems else 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init")
    s.add_argument("--provider", default="elevenlabs")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("add")
    s.add_argument("--character-id", required=True)
    s.add_argument("--display-name")
    s.add_argument("--persona")
    s.add_argument("--voice-description")
    s.add_argument("--gender", choices=["female", "male", "other"])
    s.add_argument("--age")
    s.add_argument("--tags", help="comma-separated casting tags")
    s.add_argument("--language", default="vi-VN")
    s.add_argument("--provider", default="elevenlabs", choices=PROVIDER_NAMES)
    s.add_argument("--voice-id", required=True, help="ElevenLabs voice_id, or a Gemini voice name such as Leda")
    s.add_argument("--model-id", default=None, help="default: eleven_v3 / gemini-3.1-flash-tts-preview")
    s.add_argument("--voice-url")
    s.add_argument("--fallback-voice-id", help="premade voice used when the plan rejects voice_id (402)")
    s.add_argument("--default-settings", help='JSON, e.g. \'{"stability": 0.5}\'')
    s.add_argument("--one-off", action="store_true")
    s.add_argument("--unlock", action="store_true")
    s.set_defaults(fn=cmd_add)

    s = sub.add_parser("list")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("validate")
    s.add_argument("--series", required=True)
    s.add_argument("--episode", type=int, default=None)
    s.add_argument("--provider", default=None)
    s.set_defaults(fn=cmd_validate)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
