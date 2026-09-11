"""Daily retention sweep: prune terminal jobs older than RETENTION_DAYS."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from . import state

log = logging.getLogger("llm-queue.retention")
SWEEP_INTERVAL = 24 * 3600  # daily


def retention_days() -> int:
    try:
        return int(os.environ.get("RETENTION_DAYS", "30"))
    except ValueError:
        return 30


async def sweep_once() -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days())).isoformat()
    removed = await state.get_store().prune(cutoff)
    if removed:
        log.info("retention: pruned %d job(s) older than %s", removed, cutoff)
    return removed


async def retention_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await sweep_once()
        except Exception:
            log.exception("retention sweep failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=SWEEP_INTERVAL)
        except asyncio.TimeoutError:
            pass
