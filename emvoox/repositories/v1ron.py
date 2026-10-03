"""V1RON OS backends: ``v1ron_db`` (PostgreSQL) for documents and V1RON Media (MinIO) for blobs.

Not available yet: the studio has no V1RON OS access during Prototype V1, so these classes only
pin down the work that remains. When access arrives, implement the two classes below against the
protocols in ``base.py`` and set ``EMVOOX_STORAGE=v1ron``. Nothing else changes: agents, the
engine and the API only ever see ``Repositories``.

    PostgresDocumentStore   table documents(key text primary key, body jsonb, updated_at timestamptz)
                            table logs(id bigserial, key text, body jsonb)
                            -> the same shape as ``SqliteDocumentStore`` in local.py
    MinioBlobStore          object name = key; ``path()`` returns a file in a local cache directory,
                            ``commit()`` uploads it, ``local()`` downloads on a cache miss
"""

from __future__ import annotations

from emvoox.config import Settings


class PostgresDocumentStore:  # pragma: no cover - placeholder until V1RON OS access exists
    def __init__(self, dsn: str):
        raise NotImplementedError("v1ron_db is not connected yet; keep EMVOOX_STORAGE=local")


class MinioBlobStore:  # pragma: no cover - placeholder until V1RON OS access exists
    def __init__(self, endpoint: str, bucket: str, cache_dir: str):
        raise NotImplementedError("V1RON Media (MinIO) is not connected yet; keep EMVOOX_STORAGE=local")


def v1ron_repositories(settings: Settings):  # pragma: no cover
    raise NotImplementedError(
        "EMVOOX_STORAGE=v1ron needs PostgresDocumentStore and MinioBlobStore (emvoox/repositories/v1ron.py). "
        "Use EMVOOX_STORAGE=local until V1RON OS access is available."
    )
