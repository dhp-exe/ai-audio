"""Where the workflow graph keeps its checkpoints, so a paused run survives the process that started it."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from emvoox import paths
from emvoox.repositories import Repositories

_ready: set[str] = set()  # databases whose checkpoint tables this process has already created


@asynccontextmanager
async def open_checkpointer(repos: Repositories) -> AsyncIterator:
    """PostgreSQL when the documents live there (``EMVOOX_STORAGE=postgres``); otherwise one SQLite file under the
    tenant's data directory. Either way a checkpoint outlives the process that wrote it."""
    if repos.database_url:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        async with AsyncPostgresSaver.from_conn_string(repos.database_url) as saver:
            if repos.database_url not in _ready:
                await saver.setup()
                _ready.add(repos.database_url)
            yield saver
        return
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    path = repos.blobs.path(paths.CHECKPOINTS)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        yield saver
