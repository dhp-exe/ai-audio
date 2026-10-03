"""Builds the repository bundle for the configured backend. The single place storage is chosen."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from emvoox.config import get_settings
from emvoox.repositories.base import BlobStore, DocumentStore
from emvoox.repositories.local import JsonDocumentStore, LocalBlobStore, SqliteDocumentStore
from emvoox.repositories.repos import (
    AssetRepository,
    OutputRepository,
    ResearchRepository,
    RunRepository,
    SeriesRepository,
    TelemetryRepository,
    VoiceRegistryRepository,
)


@dataclass
class Repositories:
    docs: DocumentStore
    blobs: BlobStore
    registry: VoiceRegistryRepository
    series: SeriesRepository
    runs: RunRepository
    telemetry: TelemetryRepository
    research: ResearchRepository
    assets: AssetRepository
    outputs: OutputRepository
    backend: str = "local"
    root: str = ""


def build(docs: DocumentStore, blobs: BlobStore, *, backend: str = "local", root: str = "") -> Repositories:
    return Repositories(
        docs=docs, blobs=blobs,
        registry=VoiceRegistryRepository(docs),
        series=SeriesRepository(docs, blobs),
        runs=RunRepository(docs, blobs),
        telemetry=TelemetryRepository(docs, blobs),
        research=ResearchRepository(docs, blobs),
        assets=AssetRepository(docs, blobs),
        outputs=OutputRepository(docs, blobs),
        backend=backend, root=root,
    )


def local_repositories(root: Path, doc_store: str = "json") -> Repositories:
    """Local-first storage under ``root`` (./data): files for media, JSON files or SQLite for documents."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    blobs = LocalBlobStore(root)
    if doc_store == "sqlite":
        docs: DocumentStore = SqliteDocumentStore(root / "emvoox.sqlite3")
    elif doc_store == "json":
        docs = JsonDocumentStore(root)
    else:
        raise ValueError(f"EMVOOX_DOC_STORE must be json or sqlite, got {doc_store!r}")
    return build(docs, blobs, backend=f"local/{doc_store}", root=str(root))


_instance: Repositories | None = None
_lock = threading.Lock()


def get_repositories() -> Repositories:
    """Process-wide repositories for the configured backend (EMVOOX_STORAGE, EMVOOX_DATA_DIR, EMVOOX_DOC_STORE)."""
    global _instance
    with _lock:
        if _instance is None:
            s = get_settings()
            if s.storage_backend == "local":
                _instance = local_repositories(s.data_dir, s.doc_store)
            elif s.storage_backend == "v1ron":
                from emvoox.repositories.v1ron import v1ron_repositories

                _instance = v1ron_repositories(s)
            else:
                raise ValueError(f"EMVOOX_STORAGE must be local or v1ron, got {s.storage_backend!r}")
        return _instance


def reset_repositories() -> None:
    """Forget the cached bundle (tests and the demo point the engine at a sandbox)."""
    global _instance
    with _lock:
        _instance = None
