"""MCP tools share the same store as the REST API."""
import pytest
from fastapi.testclient import TestClient

import app.backends as backends
from app.main import create_app
from app import mcp_server, state


async def _fake_run(alias, prompt, params=None, **kw):
    return f"echo[{alias}]: {prompt}"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(backends, "run", _fake_run)
    with TestClient(create_app()) as c:
        if state.pool is not None:
            state.pool.run_fn = _fake_run
        yield c


def test_mcp_mounted(client):
    # The streamable-HTTP endpoint should exist (405/406/400 for a bare GET,
    # not 404). A 404 would mean it isn't mounted. Authed so we test mounting,
    # not the bearer gate (covered separately below).
    r = client.get("/mcp/", headers={"Authorization": "Bearer test-pw"})
    assert r.status_code != 404


def test_mcp_requires_bearer(client):
    # The /mcp mount must reject unauthenticated calls on its own, not just rely
    # on the edge LAN allowlist (Phase B opens this up beyond the LAN).
    assert client.get("/mcp/").status_code == 401
    assert client.post("/mcp/", json={}).status_code == 401
    assert client.get(
        "/mcp/", headers={"Authorization": "Bearer wrong"}
    ).status_code == 401


def test_mcp_accepts_valid_bearer(client):
    # A valid token passes the gate; whatever the MCP layer then returns for a
    # bare GET (405/406/400), it must not be the 401 from our guard.
    assert client.get(
        "/mcp/", headers={"Authorization": "Bearer test-pw"}
    ).status_code != 401
    # x-api-key header is accepted too (mirrors require_api_auth).
    assert client.get(
        "/mcp/", headers={"x-api-key": "test-pw"}
    ).status_code != 401


def test_list_models_tool():
    out = mcp_server.list_models.fn()
    assert {m["alias"] for m in out} == {"fast", "background", "reasoning"}


@pytest.mark.asyncio
async def test_pick_best_backend_tool(client):
    out = await mcp_server.pick_best_backend.fn("write and debug python", "interactive", 0)
    assert out["alias"] == "fast"
    out2 = await mcp_server.pick_best_backend.fn("summarize this log", "batch", 0)
    assert out2["alias"] == "background"


@pytest.mark.asyncio
async def test_submit_and_result_share_store(client):
    """A job submitted via MCP must be visible via the REST API (same store)."""
    sub = await mcp_server.submit_job.fn("hi from mcp", "fast")
    jid = sub["id"]
    assert sub["tier"] == "gpu"
    # worker (fake) completes it
    import asyncio
    for _ in range(50):
        res = await mcp_server.get_result.fn(jid)
        if res["status"] == "done":
            break
        await asyncio.sleep(0.1)
    assert res["status"] == "done"
    assert res["result"] == "echo[fast]: hi from mcp"


@pytest.mark.asyncio
async def test_get_status_tool(client):
    sub = await mcp_server.submit_job.fn("status test", "reasoning")
    st = await mcp_server.get_status.fn(sub["id"])
    assert st["tier"] == "cpu"
    assert st["status"] in ("queued", "running", "done")


@pytest.mark.asyncio
async def test_mcp_owner_scoping(client, monkeypatch):
    # caller A submits
    monkeypatch.setattr(mcp_server, "_mcp_caller", lambda: ("k:ownerA", "sk-good-A"))
    sub = await mcp_server.submit_job.fn("a job", "background")
    jid = sub["id"]
    # caller B cannot read it
    monkeypatch.setattr(mcp_server, "_mcp_caller", lambda: ("k:ownerB", "sk-good-B"))
    with pytest.raises(Exception):
        await mcp_server.get_result.fn(jid)
    # caller A can
    monkeypatch.setattr(mcp_server, "_mcp_caller", lambda: ("k:ownerA", "sk-good-A"))
    res = await mcp_server.get_result.fn(jid)
    assert res["id"] == jid
