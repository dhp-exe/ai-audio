"""Local backends: JSON files, SQLite, and plain files under the data root."""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from emvoox.repositories.base import JsonDoc


def _safe(root: Path, key: str) -> Path:
    if not key or key.startswith("/") or ".." in Path(key).parts:
        raise ValueError(f"illegal storage key {key!r}")
    return root / key


def _mtime(p: Path) -> datetime | None:
    return datetime.fromtimestamp(p.stat().st_mtime, UTC) if p.exists() else None


class LocalBlobStore:
    """Files on disk under ``root``. ``commit`` is a no-op: the path is the store."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._lock = threading.Lock()

    def path(self, key: str) -> Path:
        p = _safe(self.root, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def commit(self, key: str) -> None:
        return None

    def local(self, key: str) -> Path:
        return _safe(self.root, key)

    def exists(self, key: str) -> bool:
        return _safe(self.root, key).exists()

    def delete(self, key: str) -> None:
        _safe(self.root, key).unlink(missing_ok=True)

    def delete_prefix(self, prefix: str) -> None:
        p = _safe(self.root, prefix)
        if p.is_dir():
            shutil.rmtree(p)

    def list(self, prefix: str, suffix: str = "") -> list[str]:
        d = _safe(self.root, prefix)
        if not d.is_dir():
            return []
        return sorted(f"{prefix.rstrip('/')}/{f.name}" for f in d.iterdir() if f.is_file() and f.name.endswith(suffix) and not f.name.startswith("."))

    def list_dirs(self, prefix: str) -> list[str]:
        d = _safe(self.root, prefix)
        if not d.is_dir():
            return []
        return sorted(f.name for f in d.iterdir() if f.is_dir() and not f.name.startswith("."))

    def read_text(self, key: str) -> str | None:
        p = _safe(self.root, key)
        return p.read_text(encoding="utf-8") if p.exists() else None

    def write_text(self, key: str, text: str) -> None:
        p = self.path(key)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(p)

    def append_text(self, key: str, text: str) -> None:
        with self._lock, self.path(key).open("a", encoding="utf-8") as f:
            f.write(text)

    def copy(self, src: str, dst: str) -> None:
        shutil.copyfile(_safe(self.root, src), self.path(dst))

    def mtime(self, key: str) -> datetime | None:
        return _mtime(_safe(self.root, key))

    def size(self, key: str) -> int:
        p = _safe(self.root, key)
        return p.stat().st_size if p.exists() else 0


class JsonDocumentStore:
    """One JSON file per document, one JSONL file per log, under ``root``. Human-readable and diffable."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._lock = threading.Lock()

    def get(self, key: str) -> JsonDoc | None:
        p = _safe(self.root, key)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def put(self, key: str, doc: JsonDoc) -> None:
        p = _safe(self.root, key)
        with self._lock:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(p)

    def delete(self, key: str) -> None:
        _safe(self.root, key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return _safe(self.root, key).exists()

    def list(self, prefix: str) -> list[str]:
        d = _safe(self.root, prefix)
        if not d.is_dir():
            return []
        return sorted(str(f.relative_to(self.root).as_posix()) for f in d.rglob("*.json") if f.is_file())

    def append(self, key: str, row: dict) -> None:
        p = _safe(self.root, key)
        with self._lock:
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def read_log(self, key: str) -> list[dict]:
        p = _safe(self.root, key)
        rows: list[dict] = []
        if not p.exists():
            return rows
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def mtime(self, key: str) -> datetime | None:
        return _mtime(_safe(self.root, key))

    def delete_prefix(self, prefix: str) -> None:
        p = _safe(self.root, prefix)
        if p.is_dir():
            shutil.rmtree(p)


class SqliteDocumentStore:
    """The same contract on one SQLite file: the shape a PostgreSQL JSONB table takes later.

        documents(key PRIMARY KEY, body JSON, updated_at)
        logs(id AUTOINCREMENT, key, body JSON)
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        with self._lock, self._conn:
            self._conn.execute("CREATE TABLE IF NOT EXISTS documents (key TEXT PRIMARY KEY, body TEXT NOT NULL, updated_at TEXT NOT NULL)")
            self._conn.execute("CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL, body TEXT NOT NULL)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS logs_key ON logs(key)")

    def get(self, key: str) -> JsonDoc | None:
        with self._lock:
            row = self._conn.execute("SELECT body FROM documents WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, doc: JsonDoc) -> None:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._lock, self._conn:
            self._conn.execute("INSERT INTO documents(key, body, updated_at) VALUES(?, ?, ?) "
                               "ON CONFLICT(key) DO UPDATE SET body = excluded.body, updated_at = excluded.updated_at",
                               (key, json.dumps(doc, ensure_ascii=False), now))

    def delete(self, key: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM documents WHERE key = ?", (key,))

    def exists(self, key: str) -> bool:
        with self._lock:
            return self._conn.execute("SELECT 1 FROM documents WHERE key = ?", (key,)).fetchone() is not None

    def list(self, prefix: str) -> list[str]:
        with self._lock:
            rows = self._conn.execute("SELECT key FROM documents WHERE key LIKE ? ORDER BY key", (prefix.rstrip("/") + "/%",)).fetchall()
        return [r[0] for r in rows]

    def append(self, key: str, row: dict) -> None:
        with self._lock, self._conn:
            self._conn.execute("INSERT INTO logs(key, body) VALUES(?, ?)", (key, json.dumps(row, ensure_ascii=False)))

    def read_log(self, key: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT body FROM logs WHERE key = ? ORDER BY id", (key,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def mtime(self, key: str) -> datetime | None:
        with self._lock:
            row = self._conn.execute("SELECT updated_at FROM documents WHERE key = ?", (key,)).fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def delete_prefix(self, prefix: str) -> None:
        like = prefix.rstrip("/") + "/%"
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM documents WHERE key LIKE ?", (like,))
            self._conn.execute("DELETE FROM logs WHERE key LIKE ?", (like,))
