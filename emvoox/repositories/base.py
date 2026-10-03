"""Storage interfaces. Agents never touch a path or a database; they call typed repositories, and
those are written against two small backends:

    DocumentStore   JSON documents and append-only logs, addressed by key
                    (local: JSON files or SQLite; later: v1ron_db / PostgreSQL JSONB)
    BlobStore       binary and text files, addressed by the same kind of key
                    (local: ./data on disk; later: V1RON Media / MinIO)

Moving to V1RON OS means implementing these two protocols once (see ``v1ron.py``) and setting
``EMVOOX_STORAGE=v1ron``. Agent and engine code does not change.

FFmpeg and the vendor SDKs need real files, so a ``BlobStore`` always hands out a local path:
``path()`` for a file that will be written (followed by ``commit()``), ``local()`` for one that
must be read (a remote store downloads it into its cache first).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

JsonDoc = dict | list


@runtime_checkable
class DocumentStore(Protocol):
    def get(self, key: str) -> JsonDoc | None: ...

    def put(self, key: str, doc: JsonDoc) -> None: ...

    def delete(self, key: str) -> None: ...

    def exists(self, key: str) -> bool: ...

    def list(self, prefix: str) -> list[str]:
        """Keys of documents under ``prefix`` (recursive), sorted."""
        ...

    def append(self, key: str, row: dict) -> None:
        """Append one row to the log at ``key`` (JSONL locally, an insert remotely)."""
        ...

    def read_log(self, key: str) -> list[dict]: ...

    def mtime(self, key: str) -> datetime | None: ...

    def delete_prefix(self, prefix: str) -> None: ...


@runtime_checkable
class BlobStore(Protocol):
    def path(self, key: str) -> Path:
        """Local path to write ``key`` to (parent directories exist). Call ``commit`` when done."""
        ...

    def commit(self, key: str) -> None:
        """Publish a file written at ``path(key)`` to the backing store. No-op on local disk."""
        ...

    def local(self, key: str) -> Path:
        """Local path of an existing blob for reading (downloads it first on a remote store)."""
        ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...

    def delete_prefix(self, prefix: str) -> None: ...

    def list(self, prefix: str, suffix: str = "") -> list[str]:
        """Keys directly under ``prefix`` (one level), sorted."""
        ...

    def list_dirs(self, prefix: str) -> list[str]:
        """Names of the 'directories' directly under ``prefix``."""
        ...

    def read_text(self, key: str) -> str | None: ...

    def write_text(self, key: str, text: str) -> None: ...

    def append_text(self, key: str, text: str) -> None: ...

    def copy(self, src: str, dst: str) -> None: ...

    def mtime(self, key: str) -> datetime | None: ...

    def size(self, key: str) -> int: ...
