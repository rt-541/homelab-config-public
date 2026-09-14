"""Web UI: key-as-login and per-user session cookie."""
import pytest
from fastapi.testclient import TestClient

import app.backends as backends
from app.main import create_app
from app import state


async def _fake_run(alias, prompt, params=None, **kw):
    return f"echo[{alias}]: {prompt}"


@pytest.fixture
def web_client(monkeypatch):
    monkeypatch.setattr(backends, "run", _fake_run)
    with TestClient(create_app()) as c:
        if state.pool is not None:
            state.pool.run_fn = _fake_run
        yield c


def test_login_requires_valid_key(web_client):
    r = web_client.post("/login", data={"key": "sk-bad"}, follow_redirects=False)
    assert r.status_code == 401
    r2 = web_client.post("/login", data={"key": "test-pw"}, follow_redirects=False)
    assert r2.status_code == 303
