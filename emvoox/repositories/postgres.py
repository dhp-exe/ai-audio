"""PostgreSQL ``DocumentStore``: documents, run state and logs in one database, one row per tenant and key.

    documents(tenant, key, body jsonb, updated_at)   primary key (tenant, key)
    logs(id bigserial, tenant, key, body jsonb)      append-only

The same contract test as the JSON and SQLite stores (tests/test_repositories.py). Media files are not stored
here: with ``EMVOOX_STORAGE=postgres`` blobs stay on local disk; MinIO is the remaining piece of ``v1ron``.
Needs ``pip install -e '.[durable]'``.
"""

from __future__ import annotations

from datetime import datetime

from emvoox.repositories.base import JsonDoc

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS documents (tenant text NOT NULL, key text NOT NULL, body jsonb NOT NULL, "
    "updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (tenant, key))",
    "CREATE TABLE IF NOT EXISTS logs (id bigserial PRIMARY KEY, tenant text NOT NULL, key text NOT NULL, body jsonb NOT NULL)",
    "CREATE INDEX IF NOT EXISTS logs_tenant_key ON logs (tenant, key, id)",
)


def _like(prefix: str) -> str:
    """LIKE pattern for 'everything under prefix/'. '' = everything."""
    p = prefix.rstrip("/")
    escaped = p.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}/%" if p else "%"


class PostgresPool:
    """One connection pool per database, shared by every tenant's store."""

    def __init__(self, dsn: str):
        try:
            from psycopg_pool import ConnectionPool
        except ImportError as e:  # pragma: no cover - depends on the install
            raise RuntimeError("EMVOOX_STORAGE=postgres needs: pip install -e '.[durable]'") from e
        self.dsn = dsn
        self.pool = ConnectionPool(dsn, min_size=1, max_size=8, kwargs={"autocommit": True}, open=True)
        with self.pool.connection() as conn:
            for stmt in SCHEMA:
                conn.execute(stmt)

    def close(self) -> None:
        self.pool.close()


class PostgresDocumentStore:
    """Every statement carries the tenant: a store cannot read or write another tenant's rows."""

    def __init__(self, pool: PostgresPool, tenant: str):
        self._pool, self.tenant = pool, tenant

    def _run(self, sql: str, params: tuple, fetch: bool = False):
        from psycopg.types.json import Jsonb  # noqa: F401 - imported so a missing driver fails here, clearly

        with self._pool.pool.connection() as conn:
            cur = conn.execute(sql, params)
            return cur.fetchall() if fetch else None

    def get(self, key: str) -> JsonDoc | None:
        rows = self._run("SELECT body FROM documents WHERE tenant = %s AND key = %s", (self.tenant, key), fetch=True)
        return rows[0][0] if rows else None

    def put(self, key: str, doc: JsonDoc) -> None:
        from psycopg.types.json import Jsonb

        self._run("INSERT INTO documents(tenant, key, body) VALUES(%s, %s, %s) "
                  "ON CONFLICT (tenant, key) DO UPDATE SET body = excluded.body, updated_at = now()", (self.tenant, key, Jsonb(doc)))

    def delete(self, key: str) -> None:
        self._run("DELETE FROM documents WHERE tenant = %s AND key = %s", (self.tenant, key))

    def exists(self, key: str) -> bool:
        return bool(self._run("SELECT 1 FROM documents WHERE tenant = %s AND key = %s", (self.tenant, key), fetch=True))

    def list(self, prefix: str) -> list[str]:
        rows = self._run("SELECT key FROM documents WHERE tenant = %s AND key LIKE %s ORDER BY key", (self.tenant, _like(prefix)), fetch=True)
        return [r[0] for r in rows]

    def append(self, key: str, row: dict) -> None:
        from psycopg.types.json import Jsonb

        self._run("INSERT INTO logs(tenant, key, body) VALUES(%s, %s, %s)", (self.tenant, key, Jsonb(row)))

    def read_log(self, key: str) -> list[dict]:
        rows = self._run("SELECT body FROM logs WHERE tenant = %s AND key = %s ORDER BY id", (self.tenant, key), fetch=True)
        return [r[0] for r in rows]

    def mtime(self, key: str) -> datetime | None:
        rows = self._run("SELECT updated_at FROM documents WHERE tenant = %s AND key = %s", (self.tenant, key), fetch=True)
        return rows[0][0] if rows else None

    def delete_prefix(self, prefix: str) -> None:
        like = _like(prefix)
        self._run("DELETE FROM documents WHERE tenant = %s AND key LIKE %s", (self.tenant, like))
        self._run("DELETE FROM logs WHERE tenant = %s AND key LIKE %s", (self.tenant, like))
