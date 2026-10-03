"""The data access layer: both document stores honour one contract; typed repositories enforce the registry lock."""

from __future__ import annotations

import pytest

from emvoox.contracts import CharacterProfile, ProviderVoice, VoiceRegistry
from emvoox.repositories import RegistryLocked, local_repositories
from emvoox.repositories.base import BlobStore, DocumentStore
from emvoox.repositories.local import JsonDocumentStore, LocalBlobStore, SqliteDocumentStore


@pytest.fixture(params=["json", "sqlite"])
def docs(request, tmp_path) -> DocumentStore:
    return JsonDocumentStore(tmp_path) if request.param == "json" else SqliteDocumentStore(tmp_path / "db.sqlite3")


def test_document_store_contract(docs):
    assert isinstance(docs, DocumentStore)
    assert docs.get("series/a/series.json") is None and not docs.exists("series/a/series.json")
    docs.put("series/a/series.json", {"title": "Bản hợp đồng"})
    docs.put("series/a/qa/ep01_report.json", {"score": 90})
    docs.put("series/b/series.json", {"title": "B"})
    assert docs.get("series/a/series.json") == {"title": "Bản hợp đồng"} and docs.exists("series/a/series.json")
    assert docs.list("series/a") == ["series/a/qa/ep01_report.json", "series/a/series.json"]
    assert docs.mtime("series/a/series.json") is not None
    docs.append("series/a/run.log.jsonl", {"n": 1})
    docs.append("series/a/run.log.jsonl", {"n": 2})
    assert [r["n"] for r in docs.read_log("series/a/run.log.jsonl")] == [1, 2]
    docs.delete_prefix("series/a")
    assert docs.list("series/a") == [] and docs.read_log("series/a/run.log.jsonl") == [] and docs.get("series/b/series.json") == {"title": "B"}
    docs.delete("series/b/series.json")
    assert docs.get("series/b/series.json") is None


def test_blob_store_contract(tmp_path):
    blobs = LocalBlobStore(tmp_path)
    assert isinstance(blobs, BlobStore)
    p = blobs.path("series/a/stems/ep01/x.wav")
    p.write_bytes(b"RIFF")
    blobs.commit("series/a/stems/ep01/x.wav")
    assert blobs.exists("series/a/stems/ep01/x.wav") and blobs.size("series/a/stems/ep01/x.wav") == 4
    assert blobs.list("series/a/stems/ep01", ".wav") == ["series/a/stems/ep01/x.wav"] and blobs.list_dirs("series") == ["a"]
    blobs.write_text("series/a/story_raw.txt", "Xin chào")
    blobs.append_text("series/a/logs/x.log", "a\n")
    blobs.append_text("series/a/logs/x.log", "b\n")
    assert blobs.read_text("series/a/story_raw.txt") == "Xin chào" and blobs.read_text("series/a/logs/x.log") == "a\nb\n"
    blobs.copy("series/a/stems/ep01/x.wav", "outputs/approved_masters/a/ep01.mp3")
    assert blobs.exists("outputs/approved_masters/a/ep01.mp3")
    with pytest.raises(ValueError):
        blobs.path("../escape.txt")
    blobs.delete_prefix("series/a")
    assert not blobs.exists("series/a/story_raw.txt")


@pytest.mark.parametrize("doc_store", ["json", "sqlite"])
def test_registry_lock_and_plugging_a_cloned_voice(tmp_path, doc_store):
    repos = local_repositories(tmp_path, doc_store)
    reg = repos.registry
    reg.save(VoiceRegistry(characters=[CharacterProfile(character_id="ngan", display_name="Ngân", persona="p", voice_description="nữ",
                                                        providers={"gemini": ProviderVoice(voice_id="Leda", model_id="gemini-3.1-flash-tts-preview", source="prebuilt")})]))
    # a voice on a new engine is an addition: no unlock, usable at once, and it can become the preferred engine
    cloned = ProviderVoice(voice_id="pvc123", model_id="eleven_v3", source="cloned", label="Ngân PVC v1")
    r, entry = reg.set_provider_voice("ngan", "elevenlabs", cloned, make_preferred=True)
    c = r.get("ngan")
    assert c.providers["elevenlabs"].source == "cloned" and c.preferred_provider == "elevenlabs" and c.cloned_providers() == ["elevenlabs"]
    assert "[cloned]" in entry and "(preferred engine)" in entry
    # replacing a locked voice needs unlock and is written to the changelog
    with pytest.raises(RegistryLocked):
        reg.set_provider_voice("ngan", "elevenlabs", ProviderVoice(voice_id="other", model_id="eleven_v3"))
    reg.set_provider_voice("ngan", "elevenlabs", ProviderVoice(voice_id="pvc124", model_id="eleven_v3", source="cloned"), unlock=True)
    assert "pvc123@eleven_v3 -> pvc124@eleven_v3" in reg.load().changelog[-1]
    with pytest.raises(RegistryLocked):
        reg.remove_provider_voice("ngan", "gemini")
    assert "gemini" not in reg.remove_provider_voice("ngan", "gemini", unlock=True).get("ngan").providers
    with pytest.raises(RegistryLocked):
        reg.remove("ngan")


def test_series_repository_roundtrip(repos):
    from emvoox.contracts import SeriesBible, StoryInput, StoryOverview

    s = repos.series
    s.save_story("s1", StoryInput(overview=StoryOverview(title="T"), script="x" * 60))
    assert s.load_story("s1").overview.title == "T" and s.load_story_raw("s1").startswith("TÊN: T")
    s.save_bible(SeriesBible(series_id="s1", title="T", premise="p", tone="t"))  # uncast bibles are valid until the Casting Agent runs
    assert s.load_bible("s1").is_cast() is False and s.list_ids() == ["s1"] and s.exists("s1")
    s.save_raw_script("s1", 1, "TẬP 01 - A\n")
    assert s.has_raw_script("s1", 1) and not s.has_script("s1", 1)
    s.delete("s1")
    assert s.list_ids() == [] and not s.exists("s1")
