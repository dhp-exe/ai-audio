"""The data access layer: both document stores honour one contract; typed repositories enforce the registry lock."""

from __future__ import annotations

import uuid

import pytest

from emvoox.contracts import CharacterProfile, ProviderVoice, VoiceRegistry
from emvoox.repositories import RegistryLocked, local_repositories
from emvoox.repositories.base import BlobStore, DocumentStore
from emvoox.repositories.local import JsonDocumentStore, LocalBlobStore, SqliteDocumentStore


@pytest.fixture(params=["json", "sqlite", "postgres"])
def docs(request, tmp_path) -> DocumentStore:
    if request.param == "postgres":
        from emvoox.repositories.postgres import PostgresDocumentStore, PostgresPool

        pool = PostgresPool(request.getfixturevalue("postgres_dsn"))
        store = PostgresDocumentStore(pool, f"t-{uuid.uuid4().hex[:12]}")  # a tenant of its own: nothing left over from other tests
        yield store
        store.delete_prefix("")
        pool.close()
        return
    yield JsonDocumentStore(tmp_path) if request.param == "json" else SqliteDocumentStore(tmp_path / "db.sqlite3")


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


# ---------------------------------------------------------------- tenants


def _tenant_pair(kind: str, tmp_path, request):
    if kind == "postgres":
        from emvoox.repositories.factory import postgres_repositories, reset_repositories

        dsn = request.getfixturevalue("postgres_dsn")
        a, b = f"a-{uuid.uuid4().hex[:10]}", f"b-{uuid.uuid4().hex[:10]}"
        ra, rb = postgres_repositories(dsn, tmp_path, a), postgres_repositories(dsn, tmp_path, b)
        request.addfinalizer(lambda: (ra.docs.delete_prefix(""), rb.docs.delete_prefix(""), reset_repositories()))
        return ra, rb
    return local_repositories(tmp_path, kind, "studio-a"), local_repositories(tmp_path, kind, "studio-b")


@pytest.mark.parametrize("kind", ["json", "sqlite", "postgres"])
def test_two_tenants_cannot_see_each_others_series_registry_or_runs(kind, tmp_path, request):
    from emvoox.contracts import RunParams, RunState

    a, b = _tenant_pair(kind, tmp_path, request)
    assert a.tenant != b.tenant
    for repos, name in ((a, "Ngân A"), (b, "Ngân B")):
        repos.registry.save(VoiceRegistry(characters=[CharacterProfile(character_id="ngan", display_name=name, persona="p", voice_description="nữ",
                                                                      providers={"gemini": ProviderVoice(voice_id="Leda", model_id="m")})]))
    a.docs.put("series/s1/series.json", {"title": "only A"})
    a.blobs.write_text("series/s1/story_raw.txt", "A's story")
    a.runs.save(RunState(run_id="s1-1", series_id="s1", created_at="2026-10-13T00:00:00+00:00", params=RunParams(series_id="s1", tts_provider="mock")))
    a.docs.append("series/s1/run.log.jsonl", {"cost": 1})
    # the same keys, two tenants, two worlds
    assert a.registry.load().get("ngan").display_name == "Ngân A" and b.registry.load().get("ngan").display_name == "Ngân B"
    assert a.series.list_ids() == ["s1"] and b.series.list_ids() == []
    assert b.docs.get("series/s1/series.json") is None and b.runs.load("s1") is None and b.docs.read_log("series/s1/run.log.jsonl") == []
    assert b.blobs.read_text("series/s1/story_raw.txt") is None and not b.series.exists("s1")
    assert a.docs.list("series/s1") == ["series/s1/pipeline_run.json", "series/s1/series.json"] and b.docs.list("series") == []
    # deleting in one tenant leaves the other alone, and a key cannot climb out of its tenant
    b.docs.delete_prefix("series")
    b.blobs.delete_prefix("series")
    assert a.docs.get("series/s1/series.json") == {"title": "only A"} and a.blobs.read_text("series/s1/story_raw.txt") == "A's story"
    for bad in ("../studio-a/series/s1/series.json", "/etc/passwd", "series/../../x"):
        with pytest.raises(ValueError):
            b.blobs.read_text(bad)


@pytest.mark.parametrize("doc_store", ["json", "sqlite"])
def test_the_default_tenant_is_the_data_root_and_cannot_reach_other_tenants(tmp_path, doc_store):
    default, other = local_repositories(tmp_path, doc_store), local_repositories(tmp_path, doc_store, "studio-a")
    default.docs.put("series/s1/series.json", {"title": "root"})
    default.blobs.write_text("series/s1/story_raw.txt", "root")
    other.docs.put("series/s9/series.json", {"title": "tenant"})
    other.blobs.write_text("series/s9/story_raw.txt", "x")
    if doc_store == "json":  # an existing single-studio data directory is the default tenant as it is: nothing moves
        assert (tmp_path / "series" / "s1" / "series.json").exists() and (tmp_path / "tenants" / "studio-a" / "series" / "s9" / "series.json").exists()
    assert default.series.list_ids() == ["s1"] and other.series.list_ids() == ["s9"]
    assert default.docs.list("series") == ["series/s1/series.json"]
    for store, call in ((default.docs, "get"), (default.blobs, "read_text"), (default.docs, "list")):
        with pytest.raises(ValueError, match="another tenant"):
            getattr(store, call)("tenants/studio-a/series/s9/series.json")
    with pytest.raises(ValueError):
        local_repositories(tmp_path, doc_store, "Not_A_Tenant")
