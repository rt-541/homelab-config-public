"""REST API routes. Owner is resolved by the bearer auth dependency."""
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import backends, crypto, selection, state
from .auth import Caller, require_api_auth, require_caller
from .db import utcnow_iso
from .models import JobStatus

router = APIRouter(prefix="/api", tags=["api"])


class SubmitBody(BaseModel):
    prompt: str
    alias: Optional[str] = None          # explicit capability alias
    task: Optional[str] = None           # intent for selection (if no alias)
    latency: str = "interactive"
    est_context: int = 0
    params: dict[str, Any] = Field(default_factory=dict)


class SelectBody(BaseModel):
    task: str
    latency: str = "interactive"
    est_context: int = 0


async def resolve_alias(body: SubmitBody) -> tuple[str, str]:
    """Return (alias, rationale). Explicit alias wins; else selection."""
    if body.alias:
        if body.alias not in backends.REGISTRY:
            raise HTTPException(status_code=400, detail=f"unknown alias: {body.alias}")
        return body.alias, "explicit alias"
    task = body.task or body.prompt
    return await selection.pick_best_backend(task, body.latency, body.est_context)


@router.post("/jobs")
async def submit_job(body: SubmitBody, caller: Caller = Depends(require_caller)):
    if not body.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is required")
    alias, rationale = await resolve_alias(body)
    tier = backends.tier_for(alias)
    job = await state.get_store().add_job(
        id=uuid.uuid4().hex, owner=caller.owner, prompt=body.prompt, alias=alias,
        tier=tier, params=body.params, created_at=utcnow_iso(),
        enc_key=crypto.encrypt(caller.key),
    )
    return {"id": job.id, "alias": alias, "tier": tier,
            "position": job.position, "rationale": rationale, "status": job.status}


@router.get("/jobs")
async def list_jobs(owner: str = Depends(require_api_auth)):
    jobs = await state.get_store().list_jobs(owner)
    return {"jobs": [j.to_public() for j in jobs]}


@router.get("/jobs/{job_id}")
async def get_status(job_id: str, owner: str = Depends(require_api_auth)):
    job = await state.get_store().get_job(job_id)
    if not job or job.owner != owner:
        raise HTTPException(status_code=404, detail="job not found")
    return job.to_public()


@router.get("/jobs/{job_id}/result")
async def get_result(job_id: str, owner: str = Depends(require_api_auth)):
    job = await state.get_store().get_job(job_id)
    if not job or job.owner != owner:
        raise HTTPException(status_code=404, detail="job not found")
    return {"id": job.id, "status": job.status, "result": job.result, "error": job.error}


@router.delete("/jobs/{job_id}")
async def cancel_or_delete(job_id: str, owner: str = Depends(require_api_auth)):
    store = state.get_store()
    job = await store.get_job(job_id)
    if not job or job.owner != owner:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status == JobStatus.QUEUED.value:
        await store.cancel_job(job_id, owner, utcnow_iso())
        return {"id": job_id, "status": JobStatus.CANCELLED.value}
    # terminal (or running): self-delete the row
    await store.delete_job(job_id, owner)
    return {"id": job_id, "status": "deleted"}


@router.get("/models")
async def list_models(owner: str = Depends(require_api_auth)):
    return {"models": backends.registry_for_prompt()}


@router.post("/select")
async def select(body: SelectBody, owner: str = Depends(require_api_auth)):
    alias, rationale = await selection.pick_best_backend(
        body.task, body.latency, body.est_context)
    b = backends.get_backend(alias)
    return {"alias": alias, "model": b.model, "tier": b.tier, "rationale": rationale}
