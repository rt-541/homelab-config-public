import httpx
import pytest
from fastapi.testclient import TestClient

import app.backends as backends
from app.main import create_app

AUTH = {"Authorization": "Bearer test-pw"}


async def _fake_run(alias, prompt, params=None, **kw):
    return f"echo[{alias}]: {prompt}"


@pytest.fixture
def client(monkeypatch):
    # Patch the network backend BEFORE the app's lifespan constructs the worker
    # pool (the pool captures backends.run at construction).
    monkeypatch.setattr(backends, "run", _fake_run)
    with TestClient(create_app()) as c:
        import app.state as state
        # belt-and-suspenders: make the live pool use the fake even if it was
        # already constructed.
        if state.pool is not None:
            state.pool.run_fn = _fake_run
        yield c


def test_requires_auth(client):
    r = client.post("/api/jobs", json={"prompt": "hi"})
    assert r.status_code == 401


def test_submit_with_explicit_alias(client):
    r = client.post("/api/jobs", json={"prompt": "hi", "alias": "background"}, headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["alias"] == "background" and body["tier"] == "cpu"
    assert body["status"] == "queued"


def test_submit_auto_selection(client):
    r = client.post("/api/jobs",
                    json={"prompt": "summarize this log", "latency": "batch"},
                    headers=AUTH)
    assert r.json()["alias"] == "background"

    r2 = client.post("/api/jobs",
                     json={"prompt": "write and debug python", "latency": "interactive"},
                     headers=AUTH)
    assert r2.json()["alias"] == "fast"


def test_select_endpoint(client):
    r = client.post("/api/select",
                    json={"task": "write and debug a python function", "latency": "interactive"},
                    headers=AUTH)
    assert r.status_code == 200
    assert r.json()["alias"] == "fast"

    r2 = client.post("/api/select",
                     json={"task": "summarize this log", "latency": "batch"},
                     headers=AUTH)
    assert r2.json()["alias"] == "background"


def test_models_endpoint(client):
    r = client.get("/api/models", headers=AUTH)
    aliases = {m["alias"] for m in r.json()["models"]}
    assert aliases == {"fast", "background", "reasoning"}


def test_status_and_result_lifecycle(client):
    r = client.post("/api/jobs", json={"prompt": "hi", "alias": "fast"}, headers=AUTH)
    jid = r.json()["id"]
    # poll until the worker completes it (fake backend, fast)
    import time
    for _ in range(50):
        st = client.get(f"/api/jobs/{jid}", headers=AUTH).json()
        if st["status"] == "done":
            break
        time.sleep(0.1)
    assert st["status"] == "done"
    res = client.get(f"/api/jobs/{jid}/result", headers=AUTH).json()
    assert res["result"] == "echo[fast]: hi"


def test_cancel_queued_job(client):
    # use a cpu job and pause its worker so it stays queued
    import app.state as state
    # submit many to keep position; just submit and cancel quickly
    r = client.post("/api/jobs", json={"prompt": "x", "alias": "reasoning"}, headers=AUTH)
    jid = r.json()["id"]
    d = client.delete(f"/api/jobs/{jid}", headers=AUTH)
    assert d.status_code == 200
    assert d.json()["status"] in ("cancelled", "deleted")


def test_list_jobs(client):
    client.post("/api/jobs", json={"prompt": "a", "alias": "fast"}, headers=AUTH)
    r = client.get("/api/jobs", headers=AUTH)
    assert r.status_code == 200
    assert isinstance(r.json()["jobs"], list)


def test_submit_persists_encrypted_caller_key(client):
    r = client.post("/api/jobs", headers={"Authorization": "Bearer sk-good-7"},
                    json={"prompt": "hello", "alias": "fast"})
    assert r.status_code == 200
    jid = r.json()["id"]
    got = client.get(f"/api/jobs/{jid}", headers={"Authorization": "Bearer sk-good-7"})
    assert "enc_key" not in got.json()
    import asyncio
    from app import state, crypto
    job = asyncio.get_event_loop().run_until_complete(state.get_store().get_job(jid))
    assert job.enc_key is not None
    assert crypto.decrypt(job.enc_key) == "sk-good-7"
