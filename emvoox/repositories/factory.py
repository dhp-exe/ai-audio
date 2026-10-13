"""Builds the repository bundle for the configured backend. The single place storage is chosen."""

from __future__ import annotations

import atexit
import threading
from dataclasses import dataclass
from pathlib import Path

from emvoox.config import get_settings
from emvoox.repositories.base import BlobStore, DocumentStore
from emvoox.repositories.local import JsonDocumentStore, LocalBlobStore, SqliteDocumentStore
from emvoox.repositories.repos import (
    AssetRepository,
    ChatRepository,
    OutputRepository,
    ResearchRepository,
    RunRepository,
    SeriesRepository,
    SessionRepository,
    TelemetryRepository,
    VoiceRegistryRepository,
)
from emvoox.repositories.tenancy import DEFAULT_TENANT, TenantBlobStore, TenantDocumentStore, check_tenant


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
    sessions: SessionRepository
    chat: ChatRepository
    backend: str = "local"
    root: str = ""
    tenant: str = DEFAULT_TENANT
    database_url: str | None = None  # set when documents live in PostgreSQL: checkpoints go there too


def build(docs: DocumentStore, blobs: BlobStore, *, backend: str = "local", root: str = "", tenant: str = DEFAULT_TENANT,
          database_url: str | None = None) -> Repositories:
    return Repositories(
        docs=docs, blobs=blobs,
        registry=VoiceRegistryRepository(docs),
        series=SeriesRepository(docs, blobs),
        runs=RunRepository(docs, blobs),
        telemetry=TelemetryRepository(docs, blobs),
        research=ResearchRepository(docs, blobs),
        assets=AssetRepository(docs, blobs),
        outputs=OutputRepository(docs, blobs),
        sessions=SessionRepository(docs, blobs),
        chat=ChatRepository(docs, blobs),
        backend=backend, root=root, tenant=tenant, database_url=database_url,
    )


def local_repositories(root: Path, doc_store: str = "json", tenant: str = DEFAULT_TENANT) -> Repositories:
    """Local-first storage under ``root`` (./data): files for media, JSON files or SQLite for documents.
    The default tenant is ``root`` itself; any other tenant sees only ``root/tenants/<id>/``."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    blobs = TenantBlobStore(LocalBlobStore(root), tenant)
    if doc_store == "sqlite":
        docs: DocumentStore = TenantDocumentStore(_shared(("sqlite", str(root)), lambda: SqliteDocumentStore(root / "emvoox.sqlite3")), tenant)
    elif doc_store == "json":
        docs = TenantDocumentStore(JsonDocumentStore(root), tenant)
    else:
        raise ValueError(f"EMVOOX_DOC_STORE must be json or sqlite, got {doc_store!r}")
    return build(docs, blobs, backend=f"local/{doc_store}", root=str(root), tenant=tenant)


def postgres_repositories(dsn: str, root: Path, tenant: str = DEFAULT_TENANT) -> Repositories:
    """Documents, run state and logs in PostgreSQL (one row per tenant and key); media files on local disk."""
    from emvoox.repositories.postgres import PostgresDocumentStore, PostgresPool

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    pool = _shared(("postgres", dsn), lambda: PostgresPool(dsn))
    return build(PostgresDocumentStore(pool, check_tenant(tenant)), TenantBlobStore(LocalBlobStore(root), tenant), backend="postgres", root=str(root),
                 tenant=tenant, database_url=dsn)


_instances: dict[str, Repositories] = {}
_backends: dict[tuple, object] = {}  # one SQLite connection / PostgreSQL pool per database, shared by every tenant
_lock = threading.RLock()


def _shared(key: tuple, make):
    with _lock:
        if key not in _backends:
            _backends[key] = make()
        return _backends[key]


def get_repositories(tenant: str | None = None) -> Repositories:
    """Repositories of one tenant for the configured backend (EMVOOX_STORAGE, EMVOOX_DATA_DIR, EMVOOX_DOC_STORE,
    EMVOOX_DATABASE_URL). ``tenant`` defaults to EMVOOX_TENANT."""
    s = get_settings()
    tenant = check_tenant(tenant or s.tenant)
    with _lock:
        if tenant not in _instances:
            if s.storage_backend == "local":
                _instances[tenant] = local_repositories(s.data_dir, s.doc_store, tenant)
            elif s.storage_backend == "postgres":
                if not s.database_url:
                    raise ValueError("EMVOOX_STORAGE=postgres needs EMVOOX_DATABASE_URL (e.g. postgresql://localhost:5432/emvoox)")
                _instances[tenant] = postgres_repositories(s.database_url, s.data_dir, tenant)
            elif s.storage_backend == "v1ron":
                from emvoox.repositories.v1ron import v1ron_repositories

                _instances[tenant] = v1ron_repositories(s)
            else:
                raise ValueError(f"EMVOOX_STORAGE must be local, postgres or v1ron, got {s.storage_backend!r}")
        return _instances[tenant]


def _close_backends() -> None:
    """At interpreter exit: close pools while their threads can still be joined."""
    for b in list(_backends.values()):
        close = getattr(b, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001
                pass
    _backends.clear()


atexit.register(_close_backends)


def reset_repositories() -> None:
    """Forget the cached bundles (tests and the demo point the engine at a sandbox)."""
    with _lock:
        _instances.clear()
        for b in _backends.values():
            close = getattr(b, "close", None)
            if callable(close):
                close()
        _backends.clear()
