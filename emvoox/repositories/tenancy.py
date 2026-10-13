"""Tenant scoping for storage. A tenant's repositories can only address that tenant's keys.

The ``default`` tenant is the storage root itself (the layout a single-studio install already has); every other
tenant lives under ``tenants/<id>/``. Scoping is done once, here, around the two backends, so no repository,
agent or engine code builds a tenant path, and none can address another tenant's data: a key that tries to
leave its scope is refused.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from emvoox.repositories.base import BlobStore, DocumentStore, JsonDoc

DEFAULT_TENANT = "default"
TENANTS = "tenants"
_TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


def check_tenant(tenant: str) -> str:
    if not _TENANT_RE.match(tenant or ""):
        raise ValueError(f"tenant id must be lowercase letters, digits and hyphens (at most 40): {tenant!r}")
    return tenant


def tenant_prefix(tenant: str) -> str:
    """'' for the default tenant, 'tenants/<id>/' for any other."""
    return "" if check_tenant(tenant) == DEFAULT_TENANT else f"{TENANTS}/{tenant}/"


class _Scope:
    def __init__(self, tenant: str):
        self.tenant = check_tenant(tenant)
        self._prefix = tenant_prefix(tenant)

    def _in(self, key: str) -> str:
        if not key or key.startswith("/") or ".." in key.split("/"):
            raise ValueError(f"illegal storage key {key!r}")
        if not self._prefix and (key == TENANTS or key.startswith(TENANTS + "/")):
            raise ValueError(f"the default tenant may not address another tenant's data: {key!r}")
        return self._prefix + key

    def _out(self, key: str) -> str:
        return key[len(self._prefix):] if self._prefix and key.startswith(self._prefix) else key

    def _visible(self, key: str) -> bool:
        return bool(self._prefix) or not key.startswith(TENANTS + "/")


class TenantDocumentStore(_Scope):
    """A ``DocumentStore`` seen from one tenant."""

    def __init__(self, inner: DocumentStore, tenant: str):
        super().__init__(tenant)
        self.inner = inner

    def get(self, key: str) -> JsonDoc | None:
        return self.inner.get(self._in(key))

    def put(self, key: str, doc: JsonDoc) -> None:
        self.inner.put(self._in(key), doc)

    def delete(self, key: str) -> None:
        self.inner.delete(self._in(key))

    def exists(self, key: str) -> bool:
        return self.inner.exists(self._in(key))

    def list(self, prefix: str) -> list[str]:
        return [self._out(k) for k in self.inner.list(self._in(prefix)) if self._visible(k)]

    def append(self, key: str, row: dict) -> None:
        self.inner.append(self._in(key), row)

    def read_log(self, key: str) -> list[dict]:
        return self.inner.read_log(self._in(key))

    def mtime(self, key: str) -> datetime | None:
        return self.inner.mtime(self._in(key))

    def delete_prefix(self, prefix: str) -> None:
        self.inner.delete_prefix(self._in(prefix))


class TenantBlobStore(_Scope):
    """A ``BlobStore`` seen from one tenant."""

    def __init__(self, inner: BlobStore, tenant: str):
        super().__init__(tenant)
        self.inner = inner

    def path(self, key: str) -> Path:
        return self.inner.path(self._in(key))

    def commit(self, key: str) -> None:
        self.inner.commit(self._in(key))

    def local(self, key: str) -> Path:
        return self.inner.local(self._in(key))

    def exists(self, key: str) -> bool:
        return self.inner.exists(self._in(key))

    def delete(self, key: str) -> None:
        self.inner.delete(self._in(key))

    def delete_prefix(self, prefix: str) -> None:
        self.inner.delete_prefix(self._in(prefix))

    def list(self, prefix: str, suffix: str = "") -> list[str]:
        return [self._out(k) for k in self.inner.list(self._in(prefix), suffix)]

    def list_dirs(self, prefix: str) -> list[str]:
        return self.inner.list_dirs(self._in(prefix))

    def read_text(self, key: str) -> str | None:
        return self.inner.read_text(self._in(key))

    def write_text(self, key: str, text: str) -> None:
        self.inner.write_text(self._in(key), text)

    def append_text(self, key: str, text: str) -> None:
        self.inner.append_text(self._in(key), text)

    def copy(self, src: str, dst: str) -> None:
        self.inner.copy(self._in(src), self._in(dst))

    def mtime(self, key: str) -> datetime | None:
        return self.inner.mtime(self._in(key))

    def size(self, key: str) -> int:
        return self.inner.size(self._in(key))
