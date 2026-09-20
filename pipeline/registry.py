"""Read/write access to the locked Voice IP registry (library/voice-ips.json).

Used by the voice-registry skill, the orchestrator's cast job and the web dashboard so the lock
rule lives in exactly one place: changing voice_id/model_id of an IP asset requires `unlock=True`
and is written to the changelog.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime

from pipeline import naming
from pipeline.schema import CharacterProfile, ProviderVoice, VoiceRegistry

_lock = threading.Lock()


class RegistryLocked(PermissionError):
    pass


def load() -> VoiceRegistry:
    p = naming.registry_path()
    if not p.exists():
        return VoiceRegistry(locked=True, default_provider="elevenlabs", characters=[])
    return VoiceRegistry.model_validate_json(p.read_text(encoding="utf-8"))


def save(reg: VoiceRegistry, changelog_entry: str | None = None) -> None:
    with _lock:
        if changelog_entry:
            reg.changelog.append(f"{datetime.now(UTC).date()} {changelog_entry}")
        p = naming.registry_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(reg.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)


def upsert(profile: CharacterProfile, *, unlock: bool = False, reg: VoiceRegistry | None = None) -> tuple[VoiceRegistry, str]:
    """Add or update a character. Returns (registry, changelog entry). Enforces the lock rule."""
    reg = reg or load()
    existing = next((c for c in reg.characters if c.character_id == profile.character_id), None)
    if existing is None:
        reg.characters.append(profile)
        entry = f"added {profile.character_id} ({'IP asset' if profile.is_ip_asset else 'one-off'})"
        save(reg, entry)
        return reg, entry
    changes = []
    for prov, new in profile.providers.items():
        old = existing.providers.get(prov)
        if old and (old.voice_id != new.voice_id or old.model_id != new.model_id):
            if reg.locked and existing.is_ip_asset and not unlock:
                raise RegistryLocked(f"{profile.character_id} is a locked IP asset; unlock to change its {prov} voice")
            changes.append(f"{prov}: {old.voice_id}@{old.model_id} -> {new.voice_id}@{new.model_id}")
        elif old is None:
            changes.append(f"{prov}: +{new.voice_id}@{new.model_id}")
    idx = reg.characters.index(existing)
    merged_providers = {**existing.providers, **profile.providers}
    reg.characters[idx] = profile.model_copy(update={"providers": merged_providers})
    entry = f"updated {profile.character_id}" + (f" ({'; '.join(changes)})" if changes else "")
    save(reg, entry)
    return reg, entry


def set_provider_voice(character_id: str, provider: str, voice: ProviderVoice, *, unlock: bool = False) -> VoiceRegistry:
    reg = load()
    c = reg.get(character_id)
    old = c.providers.get(provider)
    if old and (old.voice_id != voice.voice_id or old.model_id != voice.model_id) and reg.locked and c.is_ip_asset and not unlock:
        raise RegistryLocked(f"{character_id} is a locked IP asset; unlock to change its {provider} voice")
    c.providers[provider] = voice
    save(reg, f"{character_id}/{provider}: {(old.voice_id + '@' + old.model_id + ' -> ') if old else '+'}{voice.voice_id}@{voice.model_id}")
    return reg


def remove(character_id: str, *, unlock: bool = False) -> VoiceRegistry:
    reg = load()
    c = reg.get(character_id)
    if reg.locked and c.is_ip_asset and not unlock:
        raise RegistryLocked(f"{character_id} is a locked IP asset; unlock to remove it")
    reg.characters.remove(c)
    save(reg, f"removed {character_id}")
    return reg
