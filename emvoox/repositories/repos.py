"""Typed repositories: the data access layer agents and the API use.

Each one is plain Python over a ``DocumentStore`` and a ``BlobStore`` and knows nothing about where
those live. Keys come from ``emvoox.paths``.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path

from emvoox import paths
from emvoox.contracts.audio import MasteredEpisode
from emvoox.contracts.cast import ResolvedCast
from emvoox.contracts.direction import DirectedConversationUnits
from emvoox.contracts.market import TrendBrief
from emvoox.contracts.production import (
    CharacterProfile,
    EpisodeScript,
    ProviderVoice,
    SeriesBible,
    StoryInput,
    Timeline,
    VoiceRegistry,
)
from emvoox.contracts.qa import QAReport
from emvoox.contracts.release import ReleasePackage
from emvoox.contracts.run import PipelineEvent, RunState
from emvoox.contracts.script import CliffhangerCheck
from emvoox.contracts.telemetry import UsageRecord
from emvoox.repositories.base import BlobStore, DocumentStore


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class RegistryLocked(PermissionError):
    pass


class VoiceRegistryRepository:
    """The global, locked Voice IP registry (assets/voice_registry.json). The lock rule lives here
    and nowhere else: changing or removing an IP asset's voice needs ``unlock=True`` and lands in
    the changelog. Adding a voice on a new engine is an addition, so the lock is not involved; that
    is what lets a freshly cloned voice be plugged in without unlocking anything."""

    def __init__(self, docs: DocumentStore):
        self.docs = docs
        self._lock = threading.Lock()

    def load(self) -> VoiceRegistry:
        d = self.docs.get(paths.REGISTRY)
        if d is None:
            return VoiceRegistry(locked=True, default_provider="gemini", characters=[])
        return VoiceRegistry.model_validate(d)

    def save(self, reg: VoiceRegistry, changelog_entry: str | None = None) -> None:
        with self._lock:
            if changelog_entry:
                reg.changelog.append(f"{datetime.now(UTC).date()} {changelog_entry}")
            self.docs.put(paths.REGISTRY, reg.model_dump(mode="json"))

    def upsert(self, profile: CharacterProfile, *, unlock: bool = False) -> tuple[VoiceRegistry, str]:
        """Add or update a character. Returns (registry, changelog entry). Enforces the lock rule."""
        reg = self.load()
        existing = next((c for c in reg.characters if c.character_id == profile.character_id), None)
        if existing is None:
            reg.characters.append(profile)
            entry = f"added {profile.character_id} ({'IP asset' if profile.is_ip_asset else 'one-off'})"
            self.save(reg, entry)
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
        merged = {**existing.providers, **profile.providers}
        reg.characters[idx] = profile.model_copy(update={"providers": merged})
        entry = f"updated {profile.character_id}" + (f" ({'; '.join(changes)})" if changes else "")
        self.save(reg, entry)
        return reg, entry

    def set_provider_voice(self, character_id: str, provider: str, voice: ProviderVoice, *, unlock: bool = False,
                           make_preferred: bool = False) -> tuple[VoiceRegistry, str]:
        reg = self.load()
        c = reg.get(character_id)
        old = c.providers.get(provider)
        if old and (old.voice_id != voice.voice_id or old.model_id != voice.model_id) and reg.locked and c.is_ip_asset and not unlock:
            raise RegistryLocked(f"{character_id} is a locked IP asset; unlock to change its {provider} voice")
        c.providers[provider] = voice
        if make_preferred:
            c.preferred_provider = provider
        entry = (f"{character_id}/{provider}: {(old.voice_id + '@' + old.model_id + ' -> ') if old else '+'}{voice.voice_id}@{voice.model_id}"
                 + (f" [{voice.source}]" if voice.source == "cloned" else "") + (" (preferred engine)" if make_preferred else ""))
        self.save(reg, entry)
        return reg, entry

    def remove_provider_voice(self, character_id: str, provider: str, *, unlock: bool = False) -> VoiceRegistry:
        reg = self.load()
        c = reg.get(character_id)
        if provider not in c.providers:
            return reg
        if reg.locked and c.is_ip_asset and not unlock:
            raise RegistryLocked(f"{character_id} is a locked IP asset; unlock to remove its {provider} voice")
        c.providers.pop(provider)
        if c.preferred_provider == provider:
            c.preferred_provider = None
        self.save(reg, f"{character_id}: removed {provider} voice")
        return reg

    def remove(self, character_id: str, *, unlock: bool = False) -> VoiceRegistry:
        reg = self.load()
        c = reg.get(character_id)
        if reg.locked and c.is_ip_asset and not unlock:
            raise RegistryLocked(f"{character_id} is a locked IP asset; unlock to remove it")
        reg.characters.remove(c)
        self.save(reg, f"removed {character_id}")
        return reg


class SeriesRepository:
    """Everything under series/<id>/: story, bible, cast, scripts, directed units, stems, masters, QA, release."""

    def __init__(self, docs: DocumentStore, blobs: BlobStore):
        self.docs, self.blobs = docs, blobs

    # ---- listing / lifecycle
    def list_ids(self) -> list[str]:
        return self.blobs.list_dirs(paths.SERIES)

    def exists(self, sid: str) -> bool:
        return self.docs.exists(paths.bible(sid)) or self.docs.exists(paths.story(sid)) or self.docs.exists(paths.run_state(sid))

    def delete(self, sid: str) -> None:
        self.docs.delete_prefix(paths.series_root(sid))
        self.blobs.delete_prefix(paths.series_root(sid))

    # ---- story / bible / cast
    def save_story(self, sid: str, story: StoryInput) -> None:
        self.docs.put(paths.story(sid), story.model_dump(mode="json"))
        self.blobs.write_text(paths.story_raw(sid), story.to_text())

    def load_story(self, sid: str) -> StoryInput | None:
        d = self.docs.get(paths.story(sid))
        return StoryInput.model_validate(d) if d else None

    def load_story_raw(self, sid: str) -> str | None:
        return self.blobs.read_text(paths.story_raw(sid))

    def save_story_raw(self, sid: str, text: str) -> None:
        self.blobs.write_text(paths.story_raw(sid), text.strip() + "\n")

    def save_trend_brief(self, sid: str, brief: TrendBrief) -> None:
        self.docs.put(paths.trend_brief(sid), brief.model_dump(mode="json"))

    def load_trend_brief(self, sid: str) -> TrendBrief | None:
        d = self.docs.get(paths.trend_brief(sid))
        return TrendBrief.model_validate(d) if d else None

    def save_bible(self, bible: SeriesBible) -> None:
        self.docs.put(paths.bible(bible.series_id), bible.model_dump(mode="json"))

    def load_bible(self, sid: str) -> SeriesBible | None:
        d = self.docs.get(paths.bible(sid))
        return SeriesBible.model_validate(d) if d else None

    def save_cast(self, cast: ResolvedCast) -> None:
        self.docs.put(paths.cast(cast.series_id), cast.model_dump(mode="json"))

    def load_cast(self, sid: str) -> ResolvedCast | None:
        d = self.docs.get(paths.cast(sid))
        return ResolvedCast.model_validate(d) if d else None

    # ---- scripts
    def save_raw_script(self, sid: str, n: int, text: str) -> None:
        self.blobs.write_text(paths.raw_script(sid, n), text)

    def load_raw_script(self, sid: str, n: int) -> str | None:
        return self.blobs.read_text(paths.raw_script(sid, n))

    def has_raw_script(self, sid: str, n: int) -> bool:
        return self.blobs.exists(paths.raw_script(sid, n))

    def save_cliffhanger(self, sid: str, check: CliffhangerCheck) -> None:
        self.docs.put(paths.cliffhanger_check(sid, check.episode_number), check.model_dump(mode="json"))

    def load_cliffhanger(self, sid: str, n: int) -> CliffhangerCheck | None:
        d = self.docs.get(paths.cliffhanger_check(sid, n))
        return CliffhangerCheck.model_validate(d) if d else None

    def save_script(self, script: EpisodeScript) -> None:
        self.docs.put(paths.parsed_script(script.series_id, script.episode_number), script.model_dump(mode="json"))

    def load_script(self, sid: str, n: int) -> EpisodeScript | None:
        d = self.docs.get(paths.parsed_script(sid, n))
        return EpisodeScript.model_validate(d) if d else None

    def has_script(self, sid: str, n: int) -> bool:
        return self.docs.exists(paths.parsed_script(sid, n))

    def save_directed(self, d: DirectedConversationUnits) -> None:
        self.docs.put(paths.directed(d.series_id, d.episode_number), d.model_dump(mode="json"))

    def load_directed(self, sid: str, n: int) -> DirectedConversationUnits | None:
        d = self.docs.get(paths.directed(sid, n))
        return DirectedConversationUnits.model_validate(d) if d else None

    # ---- audio
    def stem_path(self, sid: str, n: int, name: str) -> Path:
        return self.blobs.path(paths.stem(sid, n, name))

    def stem_key(self, sid: str, n: int, name: str) -> str:
        return paths.stem(sid, n, name)

    def stem_exists(self, sid: str, n: int, name: str) -> bool:
        return self.blobs.exists(paths.stem(sid, n, name))

    def stem_meta(self, sid: str, n: int, name: str) -> dict | None:
        d = self.docs.get(paths.meta(paths.stem(sid, n, name)))
        return d if isinstance(d, dict) else None

    def save_stem_meta(self, sid: str, n: int, name: str, meta: dict) -> None:
        self.docs.put(paths.meta(paths.stem(sid, n, name)), meta)

    def count_stems(self, sid: str, n: int) -> int:
        return len(self.blobs.list(paths.stems_dir(sid, n), ".wav"))

    def save_manifest(self, sid: str, n: int, manifest: dict) -> None:
        self.docs.put(paths.render_manifest(sid, n), manifest)

    def load_manifest(self, sid: str, n: int) -> dict | None:
        d = self.docs.get(paths.render_manifest(sid, n))
        return d if isinstance(d, dict) else None

    def save_timeline(self, tl: Timeline) -> None:
        self.docs.put(paths.timeline(tl.series_id, tl.episode_number), tl.model_dump(mode="json"))

    def load_timeline(self, sid: str, n: int) -> Timeline | None:
        d = self.docs.get(paths.timeline(sid, n))
        return Timeline.model_validate(d) if d else None

    def master_path(self, sid: str, n: int, ext: str = "wav") -> Path:
        return self.blobs.path(paths.master(sid, n, ext))

    def has_master(self, sid: str, n: int, ext: str = "mp3") -> bool:
        return self.blobs.exists(paths.master(sid, n, ext))

    def save_mastered(self, m: MasteredEpisode) -> None:
        self.blobs.commit(m.wav_path)
        self.blobs.commit(m.mp3_path)
        self.docs.put(paths.mastered(m.series_id, m.episode_number), m.model_dump(mode="json"))

    def load_mastered(self, sid: str, n: int) -> MasteredEpisode | None:
        d = self.docs.get(paths.mastered(sid, n))
        return MasteredEpisode.model_validate(d) if d else None

    # ---- QA / release
    def save_qa(self, report: QAReport) -> None:
        self.docs.put(paths.qa_report(report.series_id, report.episode_number), report.model_dump(mode="json"))

    def load_qa(self, sid: str, n: int) -> QAReport | None:
        d = self.docs.get(paths.qa_report(sid, n))
        if not isinstance(d, dict) or "status" not in d:
            return None  # absent, or a pre-Emvoox report (see load_qa_raw)
        return QAReport.model_validate(d)

    def load_qa_raw(self, sid: str, n: int) -> dict | None:
        d = self.docs.get(paths.qa_report(sid, n))
        return d if isinstance(d, dict) else None

    def save_release(self, r: ReleasePackage) -> None:
        r.updated_at = now_iso()
        self.docs.put(paths.release(r.series_id, r.episode_number), r.model_dump(mode="json"))

    def load_release(self, sid: str, n: int) -> ReleasePackage | None:
        d = self.docs.get(paths.release(sid, n))
        return ReleasePackage.model_validate(d) if d else None

    def list_releases(self, sid: str) -> list[ReleasePackage]:
        out = []
        for key in self.docs.list(f"{paths.series_root(sid)}/release"):
            d = self.docs.get(key)
            if d:
                out.append(ReleasePackage.model_validate(d))
        return sorted(out, key=lambda r: r.episode_number)

    # ---- timestamps for the library view
    def mtime(self, key: str) -> str | None:
        t = self.docs.mtime(key) or self.blobs.mtime(key)
        return t.isoformat(timespec="seconds") if t else None


class RunRepository:
    """Run state (latest per series), its event log and per-step logs."""

    def __init__(self, docs: DocumentStore, blobs: BlobStore):
        self.docs, self.blobs = docs, blobs

    def save(self, state: RunState) -> None:
        self.docs.put(paths.run_state(state.series_id), state.model_dump(mode="json"))

    def load_raw(self, sid: str) -> dict | None:
        d = self.docs.get(paths.run_state(sid))
        return d if isinstance(d, dict) else None

    def load(self, sid: str) -> RunState | None:
        d = self.load_raw(sid)
        if not d or "steps" not in d:
            return None
        return RunState.model_validate(d)

    def save_raw(self, sid: str, d: dict) -> None:
        self.docs.put(paths.run_state(sid), d)

    def reset_events(self, sid: str) -> None:
        self.blobs.delete(paths.run_events(sid))

    def append_event(self, event: PipelineEvent) -> None:
        self.blobs.append_text(paths.run_events(event.series_id), event.model_dump_json() + "\n")

    def events(self, sid: str, after: int = 0) -> list[dict]:
        import json

        text = self.blobs.read_text(paths.run_events(sid)) or ""
        out = []
        for line in text.splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("seq", 0) > after:
                out.append(row)
        return out

    def log_key(self, sid: str, step_id: str) -> str:
        return paths.step_log(sid, step_id)

    def write_log(self, sid: str, step_id: str, text: str) -> None:
        self.blobs.write_text(paths.step_log(sid, step_id), text)

    def append_log(self, sid: str, step_id: str, text: str) -> None:
        self.blobs.append_text(paths.step_log(sid, step_id), text)

    def read_log(self, sid: str, step_id: str) -> str | None:
        return self.blobs.read_text(paths.step_log(sid, step_id))


class TelemetryRepository:
    """The audit ledger. Series calls go to series/<id>/run.log.jsonl, everything else (previews,
    market research, auditions) to telemetry/run_log.jsonl; vendor 429/402 events have their own log."""

    def __init__(self, docs: DocumentStore, blobs: BlobStore):
        self.docs, self.blobs = docs, blobs

    def record(self, rec: UsageRecord) -> None:
        try:
            key = paths.series_run_log(rec.series_id) if rec.series_id else paths.RUN_LOG
            self.docs.append(key, rec.model_dump(mode="json", exclude_none=True))
        except (OSError, ValueError):
            pass  # monitoring must never break a render

    def rows(self) -> list[tuple[str, dict]]:
        """Every ledger row as (source, row); source is the series id or 'studio'."""
        out: list[tuple[str, dict]] = [("studio", r) for r in self.docs.read_log(paths.RUN_LOG)]
        for sid in self.blobs.list_dirs(paths.SERIES):
            out.extend((sid, r) for r in self.docs.read_log(paths.series_run_log(sid)))
        return out

    def record_event(self, row: dict) -> None:
        try:
            self.docs.append(paths.VENDOR_EVENTS, row)
        except (OSError, ValueError):
            pass

    def events(self) -> list[dict]:
        return self.docs.read_log(paths.VENDOR_EVENTS)


class ResearchRepository:
    """Trend seeds in, TrendBriefs out."""

    def __init__(self, docs: DocumentStore, blobs: BlobStore):
        self.docs, self.blobs = docs, blobs

    def seed_files(self) -> list[tuple[str, str]]:
        """(file name, text) of every local trend seed under inputs/trends/."""
        out = []
        for key in self.blobs.list(paths.TREND_SEEDS):
            if key.endswith((".json", ".md", ".txt")):
                text = self.blobs.read_text(key)
                if text and text.strip():
                    out.append((key.rsplit("/", 1)[-1], text))
        return out

    def market_sources(self) -> list[dict]:
        d = self.docs.get(paths.MARKET_SOURCES)
        return d if isinstance(d, list) else []

    def save_brief(self, brief: TrendBrief) -> None:
        self.docs.put(paths.brief(brief.brief_id), brief.model_dump(mode="json"))

    def load_brief(self, brief_id: str) -> TrendBrief | None:
        d = self.docs.get(paths.brief(brief_id))
        return TrendBrief.model_validate(d) if d else None

    def list_briefs(self) -> list[TrendBrief]:
        out = []
        for key in self.docs.list(paths.BRIEFS):
            d = self.docs.get(key)
            if d:
                out.append(TrendBrief.model_validate(d))
        return sorted(out, key=lambda b: b.created_at, reverse=True)

    def delete_brief(self, brief_id: str) -> None:
        self.docs.delete(paths.brief(brief_id))


class AssetRepository:
    """Shared media: voice previews, auditions, BGM beds, SFX clips."""

    def __init__(self, docs: DocumentStore, blobs: BlobStore):
        self.docs, self.blobs = docs, blobs

    def preview_path(self, name: str) -> Path:
        return self.blobs.path(paths.preview(name))

    def preview_exists(self, name: str) -> bool:
        return self.blobs.exists(paths.preview(name))

    def preview_meta(self, name: str) -> dict | None:
        d = self.docs.get(paths.meta(paths.preview(name)))
        return d if isinstance(d, dict) else None

    def save_preview_meta(self, name: str, meta: dict) -> None:
        self.blobs.commit(paths.preview(name))
        self.docs.put(paths.meta(paths.preview(name)), meta)

    def preview_metas(self) -> list[dict]:
        out = []
        for key in self.docs.list(paths.PREVIEWS):
            if key.endswith(".meta.json"):
                d = self.docs.get(key)
                if isinstance(d, dict):
                    out.append(d)
        return out

    def delete_previews(self, prefix: str) -> None:
        for key in self.blobs.list(paths.PREVIEWS):
            if key.rsplit("/", 1)[-1].startswith(prefix):
                self.blobs.delete(key)

    def audition_path(self, name: str) -> Path:
        return self.blobs.path(paths.audition(name))

    def bgm_tracks(self, mood: str) -> list[Path]:
        keys = [k for k in self.blobs.list(paths.bgm_dir(mood)) if k.endswith((".wav", ".mp3", ".m4a", ".flac"))]
        return [self.blobs.local(k) for k in keys]

    def sfx_path(self, tag: str) -> Path | None:
        key = paths.sfx(tag)
        return self.blobs.local(key) if self.blobs.exists(key) else None

    def sfx_write_path(self, tag: str) -> Path:
        return self.blobs.path(paths.sfx(tag))


class OutputRepository:
    """Approved masters and their publishing metadata (outputs/approved_masters/<series>/)."""

    def __init__(self, docs: DocumentStore, blobs: BlobStore):
        self.docs, self.blobs = docs, blobs

    def export(self, src_key: str, sid: str, n: int, ext: str) -> str:
        dst = paths.approved_file(sid, n, ext)
        self.blobs.copy(src_key, dst)
        self.blobs.commit(dst)
        return dst

    def save_metadata(self, sid: str, n: int, doc: dict) -> str:
        key = paths.approved_file(sid, n, "youtube.json")
        self.docs.put(key, doc)
        return key

    def remove(self, sid: str, n: int) -> None:
        for ext in ("mp3", "wav"):
            self.blobs.delete(paths.approved_file(sid, n, ext))
        self.docs.delete(paths.approved_file(sid, n, "youtube.json"))

    def list(self) -> list[dict]:
        out = []
        for sid in self.blobs.list_dirs(paths.APPROVED):
            for key in self.blobs.list(paths.approved_dir(sid), ".mp3"):
                name = key.rsplit("/", 1)[-1]
                meta = self.docs.get(key[: -len(".mp3")] + ".youtube.json")
                out.append({"series_id": sid, "file": name, "key": key, "bytes": self.blobs.size(key),
                            "metadata": meta if isinstance(meta, dict) else None})
        return out

    def file(self, sid: str, name: str) -> Path | None:
        key = f"{paths.approved_dir(sid)}/{Path(name).name}"
        return self.blobs.local(key) if self.blobs.exists(key) else None
