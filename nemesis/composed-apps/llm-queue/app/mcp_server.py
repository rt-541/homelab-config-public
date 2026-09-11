"""FastMCP server mounted at /mcp, exposing the 6 queue tools.

Shares the same store/selection/backends as the REST API (via app.state), so a
job submitted over MCP is visible to the web UI and vice versa.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers

from . import backends, crypto, selection, state
from .auth import OWNER_LOCAL, _extract_bearer, owner_hash
from .db import utcnow_iso
from .models import JobStatus

mcp = FastMCP(name="llm-queue")


def _mcp_caller() -> tuple[str, str | None]:
    """(owner, key) for the current MCP request from its Authorization header.
    Falls back to (OWNER_LOCAL, None) with no HTTP context (direct .fn() tests)."""
    headers = get_http_headers()
    key = _extract_bearer(headers.get("authorization"), headers.get("x-api-key"))
    return (owner_hash(key) if key else OWNER_LOCAL), key


@mcp.tool
def list_models() -> list[dict[str, Any]]:
    """List the available capability aliases / models in the fleet registry."""
    return backends.registry_for_prompt()


@mcp.tool
async def pick_best_backend(
    task: str, latency: str = "interactive", est_context: int = 0
) -> dict[str, Any]:
    """Pick the best alias for a task. Returns {alias, model, tier, rationale}."""
    alias, rationale = await selection.pick_best_backend(task, latency, est_context)
    b = backends.get_backend(alias)
    return {"alias": alias, "model": b.model, "tier": b.tier, "rationale": rationale}


@mcp.tool
async def submit_job(
    prompt: str,
    model_or_alias: Optional[str] = None,
    params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Submit a job to the queue. If no alias given, selection picks one.

    Returns {id, alias, tier, position, status}.
    """
    if not prompt.strip():
        raise ValueError("prompt is required")
    if model_or_alias and model_or_alias in backends.REGISTRY:
        alias, rationale = model_or_alias, "explicit alias"
    elif model_or_alias:
        # tolerate a raw model name -> map to its alias if known
        match = next((a for a, b in backends.REGISTRY.items() if b.model == model_or_alias), None)
        if match:
            alias, rationale = match, "matched model name"
        else:
            raise ValueError(f"unknown model_or_alias: {model_or_alias}")
    else:
        alias, rationale = await selection.pick_best_backend(prompt)
    tier = backends.tier_for(alias)
    owner, key = _mcp_caller()
    job = await state.get_store().add_job(
        id=uuid.uuid4().hex, owner=owner, prompt=prompt, alias=alias,
        tier=tier, params=params or {}, created_at=utcnow_iso(),
        enc_key=crypto.encrypt(key),
    )
    return {"id": job.id, "alias": alias, "tier": tier,
            "position": job.position, "status": job.status, "rationale": rationale}


@mcp.tool
async def get_status(job_id: str) -> dict[str, Any]:
    """Get a job's status and queue position."""
    owner, _ = _mcp_caller()
    job = await state.get_store().get_job(job_id)
    if not job or job.owner != owner:
        raise ValueError("job not found")
    return {"id": job.id, "status": job.status, "position": job.position,
            "alias": job.alias, "tier": job.tier}


@mcp.tool
async def get_result(job_id: str) -> dict[str, Any]:
    """Get a job's result (or error). Poll get_status until status is done."""
    owner, _ = _mcp_caller()
    job = await state.get_store().get_job(job_id)
    if not job or job.owner != owner:
        raise ValueError("job not found")
    return {"id": job.id, "status": job.status, "result": job.result, "error": job.error}


@mcp.tool
async def cancel_job(job_id: str) -> dict[str, Any]:
    """Cancel a queued job, or delete the row if it's already terminal."""
    owner, _ = _mcp_caller()
    store = state.get_store()
    job = await store.get_job(job_id)
    if not job or job.owner != owner:
        raise ValueError("job not found")
    if job.status == JobStatus.QUEUED.value:
        await store.cancel_job(job_id, owner, utcnow_iso())
        return {"id": job_id, "status": JobStatus.CANCELLED.value}
    await store.delete_job(job_id, owner)
    return {"id": job_id, "status": "deleted"}
