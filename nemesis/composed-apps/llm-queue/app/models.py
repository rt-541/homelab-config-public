"""Data models for the llm-queue job store.

Plain dataclasses (no ORM) plus the lightweight request/enum types shared by the
API, web UI, worker, and MCP server.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Statuses that are "settled" and eligible for retention pruning / deletion.
TERMINAL_STATUSES = (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED)


@dataclass
class Job:
    id: str
    owner: str
    prompt: str
    alias: str          # capability alias: fast | background | reasoning
    tier: str           # worker tier: gpu | cpu
    params: dict[str, Any]
    status: str
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: str = ""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    position: Optional[int] = None  # populated by queries, not stored
    enc_key: Optional[str] = None  # Fernet-encrypted caller key; scrubbed on terminal

    @staticmethod
    def from_row(row: Any) -> "Job":
        """Build a Job from an aiosqlite Row (sqlite3.Row-like)."""
        params = row["params"]
        return Job(
            id=row["id"],
            owner=row["owner"],
            prompt=row["prompt"],
            alias=row["alias"],
            tier=row["tier"],
            params=json.loads(params) if params else {},
            status=row["status"],
            result=row["result"],
            error=row["error"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            enc_key=(row["enc_key"] if "enc_key" in row.keys() else None),
        )

    def to_public(self) -> dict[str, Any]:
        """Serializable view returned by the API/MCP."""
        return {
            "id": self.id,
            "owner": self.owner,
            "alias": self.alias,
            "tier": self.tier,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "position": self.position,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "prompt": self.prompt,
            "params": self.params,
        }


@dataclass
class SubmitRequest:
    """Normalized submit payload (the API/MCP build this before hitting db)."""
    prompt: str
    alias: Optional[str] = None        # explicit capability alias
    task: Optional[str] = None         # free-text intent (for selection)
    latency: str = "interactive"
    est_context: int = 0
    params: dict[str, Any] = field(default_factory=dict)
