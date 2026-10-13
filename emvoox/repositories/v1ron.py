"""V1RON OS backends: ``v1ron_db`` (PostgreSQL) for documents and V1RON Media (MinIO) for blobs.

The PostgreSQL half exists: ``emvoox/repositories/postgres.py`` (``EMVOOX_STORAGE=postgres``, media on local
disk). What remains for ``EMVOOX_STORAGE=v1ron`` is ``MinioBlobStore`` against the ``BlobStore`` protocol in
``base.py``: object name = tenant prefix + key; ``path()`` returns a file in a local cache directory,
``commit()`` uploads it, ``local()`` downloads on a cache miss. Agents, the engine and the API do not change.
"""

from __future__ import annotations

from emvoox.config import Settings


class MinioBlobStore:  # pragma: no cover - placeholder until V1RON OS access exists
    def __init__(self, endpoint: str, bucket: str, cache_dir: str):
        raise NotImplementedError("V1RON Media (MinIO) is not connected yet; keep EMVOOX_STORAGE=local")


def v1ron_repositories(settings: Settings):  # pragma: no cover
    raise NotImplementedError(
        "EMVOOX_STORAGE=v1ron needs MinioBlobStore (emvoox/repositories/v1ron.py). Until V1RON Media is available use "
        "EMVOOX_STORAGE=postgres (documents in PostgreSQL, media on local disk) or EMVOOX_STORAGE=local."
    )
