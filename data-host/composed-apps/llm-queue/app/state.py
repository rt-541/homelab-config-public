"""Shared singletons (the store + worker pool) used by api/web/mcp.

main.py initializes these in the FastAPI lifespan. Keeping them in one module
avoids import cycles and gives the MCP server, API, and web routes the *same*
store instance (a hard requirement: MCP submits must be visible to the API and
vice versa).
"""
from __future__ import annotations

import os
from typing import Optional

from .db import Store
from .worker import WorkerPool

store: Optional[Store] = None
pool: Optional[WorkerPool] = None


def db_path() -> str:
    return os.environ.get("DB_PATH", "/data/queue.db")


async def init() -> None:
    global store, pool
    store = Store(db_path())
    await store.connect()
    pool = WorkerPool(store)
    pool.start()


async def shutdown() -> None:
    global store, pool
    if pool is not None:
        await pool.stop()
        pool = None
    if store is not None:
        await store.close()
        store = None


def get_store() -> Store:
    if store is None:
        raise RuntimeError("store not initialized")
    return store
