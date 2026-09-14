"""Server-rendered web UI (Jinja2 + HTMX). Password gate -> signed cookie."""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import backends, crypto, selection, state
from . import auth
from .db import utcnow_iso
from .models import JobStatus

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _session(request: Request) -> dict | None:
    token = request.cookies.get(auth.COOKIE_NAME)
    return auth.read_session_cookie(token) if token else None


def _owner(request: Request) -> str | None:
    s = _session(request)
    return s["owner"] if s else None


def _redirect_login() -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if not _session(request):
        return _redirect_login()
    return RedirectResponse("/queue", status_code=303)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "authed": False})


@router.post("/login")
async def login_submit(request: Request, key: str = Form("")):
    owner = await auth.owner_for_token(key)
    if owner is None:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "authed": False, "error": "Invalid API key."},
            status_code=401,
        )
    resp = RedirectResponse("/queue", status_code=303)
    resp.set_cookie(
        auth.COOKIE_NAME, auth.make_session_cookie(owner, key),
        max_age=auth.COOKIE_MAX_AGE, httponly=True, samesite="lax",
    )
    return resp


@router.get("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(auth.COOKIE_NAME)
    return resp


@router.get("/submit", response_class=HTMLResponse)
async def submit_page(request: Request):
    if not _session(request):
        return _redirect_login()
    return templates.TemplateResponse("submit.html", {
        "request": request, "authed": True,
        "aliases": backends.registry_for_prompt(),
    })


@router.post("/submit")
async def submit_create(request: Request, prompt: str = Form(...),
                        alias: str = Form(""), latency: str = Form("interactive")):
    s = _session(request)
    if not s:
        return _redirect_login()
    if alias and alias in backends.REGISTRY:
        chosen = alias
    else:
        chosen, _ = await selection.pick_best_backend(prompt, latency)
    tier = backends.tier_for(chosen)
    job = await state.get_store().add_job(
        id=uuid.uuid4().hex, owner=s["owner"], prompt=prompt, alias=chosen,
        tier=tier, params={}, created_at=utcnow_iso(),
        enc_key=crypto.encrypt(s["key"]),
    )
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


@router.get("/queue", response_class=HTMLResponse)
async def queue_page(request: Request):
    if not _session(request):
        return _redirect_login()
    jobs = await state.get_store().list_jobs(_owner(request), limit=50)
    return templates.TemplateResponse("queue.html", {
        "request": request, "authed": True, "jobs": jobs})


@router.get("/partials/queue", response_class=HTMLResponse)
async def queue_partial(request: Request):
    if not _session(request):
        return HTMLResponse("", status_code=401)
    jobs = await state.get_store().list_jobs(_owner(request), limit=50)
    return templates.TemplateResponse("_queue_table.html", {
        "request": request, "authed": True, "jobs": jobs})


@router.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    if not _session(request):
        return _redirect_login()
    jobs = await state.get_store().list_jobs(_owner(request), limit=200)
    return templates.TemplateResponse("history.html", {
        "request": request, "authed": True, "jobs": jobs})


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_page(request: Request, job_id: str):
    if not _session(request):
        return _redirect_login()
    job = await state.get_store().get_job(job_id)
    if not job or job.owner != _owner(request):
        return HTMLResponse("<main><p>Job not found.</p></main>", status_code=404)
    return templates.TemplateResponse("job.html", {
        "request": request, "authed": True, "job": job})


@router.post("/jobs/{job_id}/cancel")
async def job_cancel(request: Request, job_id: str):
    if not _session(request):
        return _redirect_login()
    owner = _owner(request)
    job = await state.get_store().get_job(job_id)
    if not job or job.owner != owner:
        return HTMLResponse("<main><p>Job not found.</p></main>", status_code=404)
    await state.get_store().cancel_job(job_id, owner, utcnow_iso())
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)
