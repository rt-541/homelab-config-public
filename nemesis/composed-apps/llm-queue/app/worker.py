"""Per-tier async worker pool.

One asyncio task per tier (gpu, cpu). Each loops: claim the oldest queued job for
its tier, run it against the backend, write the result/error back. Because each
tier has its own task, a slow CPU job never blocks a GPU job and vice versa.

Started/stopped from the FastAPI lifespan. The run function is injected so tests
can substitute a fake backend.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from . import backends, crypto
from .db import Store, utcnow_iso

log = logging.getLogger("llm-queue.worker")

TIERS = ("gpu", "cpu")
IDLE_SLEEP = 1.0  # seconds to wait when a tier queue is empty

RunFn = Callable[..., Awaitable[str]]


class WorkerPool:
    def __init__(self, store: Store, run_fn: Optional[RunFn] = None):
        self.store = store
        self.run_fn = run_fn or backends.run
        self._tasks: list[asyncio.Task] = []
        self._stop = asyncio.Event()

    def start(self) -> None:
        self._stop.clear()
        self._tasks = [
            asyncio.create_task(self._tier_loop(tier), name=f"worker-{tier}")
            for tier in TIERS
        ]
        log.info("worker pool started: tiers=%s", TIERS)

    async def stop(self) -> None:
        self._stop.set()
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._tasks = []
        log.info("worker pool stopped")

    async def _tier_loop(self, tier: str) -> None:
        while not self._stop.is_set():
            try:
                processed = await self.process_one(tier)
                if not processed:
                    await asyncio.sleep(IDLE_SLEEP)
            except asyncio.CancelledError:
                raise
            except Exception:  # never let the loop die on an unexpected error
                log.exception("tier %s loop error", tier)
                await asyncio.sleep(IDLE_SLEEP)

    async def process_one(self, tier: str) -> bool:
        """Claim and run a single job for ``tier``. Returns True if one ran."""
        job = await self.store.claim_next(tier, utcnow_iso())
        if job is None:
            return False
        log.info("tier=%s claimed job=%s alias=%s", tier, job.id, job.alias)
        try:
            api_key = crypto.decrypt(job.enc_key)
            result = await self.run_fn(job.alias, job.prompt, job.params, api_key=api_key)
            await self.store.complete_job(job.id, result, utcnow_iso())
            log.info("job=%s done (%d chars)", job.id, len(result))
        except asyncio.CancelledError:
            raise
        except Exception as e:  # record a real failure, don't swallow it
            await self.store.fail_job(job.id, f"{type(e).__name__}: {e}", utcnow_iso())
            log.warning("job=%s failed: %s", job.id, e)
        finally:
            await self.store.scrub_key(job.id)  # never keep the key past one run
        return True
