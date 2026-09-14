import os

# Ensure env is set before app modules import (backends builds registry at import).
os.environ.setdefault("APP_PASSWORD", "test-pw")
os.environ.setdefault("SESSION_SECRET", "test-secret-key-please-change")
os.environ.setdefault("DB_PATH", ":memory:")
os.environ.setdefault("SELECTION_LLM_ENABLED", "false")

from cryptography.fernet import Fernet  # noqa: E402
os.environ.setdefault("JOB_KEY_SECRET", Fernet.generate_key().decode())

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _fake_gateway(monkeypatch):
    async def fake_validate(key):
        return bool(key) and (key == "test-pw" or key.startswith("sk-good"))
    import app.auth as _auth
    monkeypatch.setattr(_auth, "_validate_key_remote", fake_validate)
