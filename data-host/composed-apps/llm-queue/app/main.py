"""FastAPI app: lifespan starts the store + per-tier workers + retention sweep,
mounts the REST API, the web UI, and the FastMCP server at /mcp.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import FastAPI

from . import api, state, web
from .mcp_server import mcp
from .middleware import MCPBearerAuth
from .retention import retention_loop

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("llm-queue")


def create_app() -> FastAPI:
    """Build a fully wired FastAPI app.

    A factory (not a module singleton) so the test suite can spin up an
    independent app per TestClient — the FastMCP streamable-HTTP session manager
    may only have its lifespan entered once per instance, so each test needs its
    own mcp_app/app pair. In production ``app`` (below) is created exactly once.
    """
    # FastMCP 2.x streamable-HTTP ASGI app (mounted at /mcp). Its own lifespan
    # must run for the session manager to start, so we chain it into ours.
    mcp_app = mcp.http_app(path="/")

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        await state.init()
        stop = asyncio.Event()
        retention_task = asyncio.create_task(retention_loop(stop))
        log.info("llm-queue started")
        async with mcp_app.lifespan(_app):
            try:
                yield
            finally:
                stop.set()
                retention_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await retention_task
                await state.shutdown()
                log.info("llm-queue stopped")

    fastapi_app = FastAPI(title="llm-queue", lifespan=lifespan)
    fastapi_app.include_router(api.router)
    fastapi_app.include_router(web.router)
    fastapi_app.mount("/mcp", mcp_app)
    # Gate the /mcp mount with the same bearer token as the REST API (raw ASGI so
    # MCP's SSE streams aren't buffered).
    fastapi_app.add_middleware(MCPBearerAuth)

    @fastapi_app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return fastapi_app


# Production singleton (uvicorn target: app.main:app).
app = create_app()
