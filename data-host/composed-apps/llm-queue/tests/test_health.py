from fastapi.testclient import TestClient

from app.main import create_app


def test_health():
    with TestClient(create_app()) as c:
        r = c.get("/healthz")
    assert r.status_code == 200 and r.json()["status"] == "ok"
