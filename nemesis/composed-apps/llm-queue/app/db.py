"""SQLite job store (async via aiosqlite).

All timestamps are passed in by the caller (ISO-8601 UTC strings) so the pure
store helpers stay deterministic and unit-testable. Use ``utcnow_iso()`` in the
route/worker layer to produce them.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

import aiosqlite

from .models import Job, JobStatus, TERMINAL_STATUSES

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  owner TEXT NOT NULL,
  prompt TEXT NOT NULL,
  alias TEXT NOT NULL,
  tier  TEXT NOT NULL,
  params TEXT,
  status TEXT NOT NULL,
  result TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  enc_key TEXT
);
CREATE INDEX IF NOT EXISTS jobs_status_tier ON jobs(status, tier, created_at);
"""


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    """Thin async wrapper around a single aiosqlite connection."""

    def __init__(self, path: str):
        self.path = path
        self._db: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        # WAL improves concurrent read while a worker holds a write txn.
        await self._db.execute("PRAGMA journal_mode=WAL;")
        await self._db.executescript(SCHEMA)
        # Phase B: add enc_key to pre-existing tables (idempotent).
        cur = await self._db.execute("PRAGMA table_info(jobs)")
        cols = {r["name"] for r in await cur.fetchall()}
        if "enc_key" not in cols:
            await self._db.execute("ALTER TABLE jobs ADD COLUMN enc_key TEXT")
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Store not connected; call connect() first")
        return self._db

    # --- writes ---

    async def add_job(
        self,
        *,
        id: str,
        owner: str,
        prompt: str,
        alias: str,
        tier: str,
        params: dict[str, Any],
        created_at: str,
        enc_key: Optional[str] = None,
    ) -> Job:
        await self.db.execute(
            """INSERT INTO jobs (id, owner, prompt, alias, tier, params, status, created_at, enc_key)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (id, owner, prompt, alias, tier, json.dumps(params or {}),
             JobStatus.QUEUED.value, created_at, enc_key),
        )
        await self.db.commit()
        job = await self.get_job(id)
        assert job is not None
        return job

    async def claim_next(self, tier: str, started_at: str) -> Optional[Job]:
        """Atomically claim the oldest queued job for a tier -> running.

        Returns the claimed Job, or None if the tier queue is empty.
        """
        cur = await self.db.execute(
            """UPDATE jobs SET status=?, started_at=?
               WHERE id = (
                 SELECT id FROM jobs
                 WHERE status=? AND tier=?
                 ORDER BY created_at ASC LIMIT 1
               )
               RETURNING *""",
            (JobStatus.RUNNING.value, started_at, JobStatus.QUEUED.value, tier),
        )
        row = await cur.fetchone()
        await self.db.commit()
        return Job.from_row(row) if row else None

    async def complete_job(self, id: str, result: str, finished_at: str) -> None:
        await self.db.execute(
            "UPDATE jobs SET status=?, result=?, finished_at=? WHERE id=?",
            (JobStatus.DONE.value, result, finished_at, id),
        )
        await self.db.commit()

    async def scrub_key(self, id: str) -> None:
        """Drop the stored per-job key once it is no longer needed."""
        await self.db.execute("UPDATE jobs SET enc_key=NULL WHERE id=?", (id,))
        await self.db.commit()

    async def fail_job(self, id: str, error: str, finished_at: str) -> None:
        await self.db.execute(
            "UPDATE jobs SET status=?, error=?, finished_at=? WHERE id=?",
            (JobStatus.FAILED.value, error, finished_at, id),
        )
        await self.db.commit()

    async def cancel_job(self, id: str, owner: str, finished_at: str) -> bool:
        """Cancel a queued job owned by ``owner``. Returns True if cancelled.

        Only QUEUED jobs can be cancelled (a running job is left to finish).
        """
        cur = await self.db.execute(
            """UPDATE jobs SET status=?, finished_at=?, enc_key=NULL
               WHERE id=? AND owner=? AND status=?""",
            (JobStatus.CANCELLED.value, finished_at, id, owner, JobStatus.QUEUED.value),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def delete_job(self, id: str, owner: str) -> bool:
        """Delete an owner's own job row (self-delete). Returns True if removed."""
        cur = await self.db.execute(
            "DELETE FROM jobs WHERE id=? AND owner=?", (id, owner)
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def prune(self, older_than: str) -> int:
        """Delete terminal jobs whose finished_at is older than ``older_than``."""
        placeholders = ",".join("?" for _ in TERMINAL_STATUSES)
        cur = await self.db.execute(
            f"""DELETE FROM jobs
                WHERE status IN ({placeholders})
                  AND finished_at IS NOT NULL
                  AND finished_at < ?""",
            tuple(s.value for s in TERMINAL_STATUSES) + (older_than,),
        )
        await self.db.commit()
        return cur.rowcount

    # --- reads ---

    async def get_job(self, id: str) -> Optional[Job]:
        cur = await self.db.execute("SELECT * FROM jobs WHERE id=?", (id,))
        row = await cur.fetchone()
        if not row:
            return None
        job = Job.from_row(row)
        if job.status == JobStatus.QUEUED.value:
            job.position = await self.queue_position(id)
        return job

    async def list_jobs(self, owner: str, limit: int = 200) -> list[Job]:
        cur = await self.db.execute(
            "SELECT * FROM jobs WHERE owner=? ORDER BY created_at DESC LIMIT ?",
            (owner, limit),
        )
        rows = await cur.fetchall()
        jobs = [Job.from_row(r) for r in rows]
        for j in jobs:
            if j.status == JobStatus.QUEUED.value:
                j.position = await self.queue_position(j.id)
        return jobs

    async def queue_position(self, id: str) -> Optional[int]:
        """1-based position among queued jobs in the same tier (FIFO).

        Returns None if the job is not currently queued.
        """
        cur = await self.db.execute(
            "SELECT tier, created_at, status FROM jobs WHERE id=?", (id,)
        )
        row = await cur.fetchone()
        if not row or row["status"] != JobStatus.QUEUED.value:
            return None
        cur = await self.db.execute(
            """SELECT COUNT(*) AS n FROM jobs
               WHERE status=? AND tier=? AND created_at < ?""",
            (JobStatus.QUEUED.value, row["tier"], row["created_at"]),
        )
        c = await cur.fetchone()
        return int(c["n"]) + 1
