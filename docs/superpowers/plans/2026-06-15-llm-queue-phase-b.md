# llm-queue Phase B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `llm-queue` a multi-user, internet-exposed service gated by per-user LiteLLM API keys with real quotas, by standing up a LAN-only LiteLLM gateway, rewiring the queue to validate/pass-through each key, then exposing only `queue.rt-541.io`.

**Architecture:** A new LAN-only `llm-gateway` (LiteLLM) container owns authN + per-key quotas and fronts the B70 vLLM + CPU Ollama backends. The queue validates a caller's virtual key against the gateway's `/key/info`, sets `owner = sha256(key)`, persists the key (Fernet-encrypted) with each job so the async worker can spend that user's budget, and calls the gateway instead of the backends directly. `queue.rt-541.io` is the only public surface (drop `lan-only`); the gateway never leaves the LAN.

**Tech Stack:** FastAPI, httpx, aiosqlite, `cryptography` (Fernet), LiteLLM proxy, Traefik, Docker Compose. Tests run in a `python:3.12-slim` throwaway container (the host has no fastapi); LiteLLM checks are curl-based against the live LAN container.

**Design doc:** `docs/superpowers/specs/2026-06-15-llm-queue-phase-b-design.md`

**How to run the test suite (every "run tests" step assumes this):**
```bash
cd /docker/homelab-config/nemesis/composed-apps/llm-queue
sudo docker run --rm -v "$PWD":/app -w /app python:3.12-slim \
  sh -c "pip install -q -r requirements.txt && python -m pytest -q"
```
Add `cryptography>=43,<45` to `requirements.txt` in Task 3 so it is present for all later runs.

---

## Part B1 — LiteLLM gateway (new app, LAN-only). Config, not unit-tested code.

### Task 1: Scaffold the `llm-gateway` composed-app

**Files:**
- Create: `nemesis/composed-apps/llm-gateway/docker-compose.yml`
- Create: `nemesis/composed-apps/llm-gateway/config.yaml`
- Create: `nemesis/composed-apps/llm-gateway/.env.example`
- Create: `nemesis/composed-apps/llm-gateway/.gitignore`
- Create: `nemesis/composed-apps/llm-gateway/README.md`

- [ ] **Step 1: Write `.gitignore`**

```
.env
```

- [ ] **Step 2: Write `.env.example`**

```sh
# LiteLLM master key (admin). Generate: openssl rand -hex 24, prefix with sk-.
LITELLM_MASTER_KEY=sk-REPLACE_ME
# Salt the key store / signing. Generate: openssl rand -hex 32.
LITELLM_SALT_KEY=REPLACE_ME
# Postgres password (LiteLLM REQUIRES Postgres for virtual-key/quota persistence;
# its bundled Prisma schema rejects sqlite). Generate: openssl rand -hex 24.
POSTGRES_PASSWORD=REPLACE_ME
```

- [ ] **Step 3: Write `config.yaml`** (model groups map the queue's aliases; only these are allowlisted)

```yaml
model_list:
  - model_name: fast
    litellm_params:
      model: openai/qwen2.5-7b-instruct
      api_base: http://192.168.1.216:8000/v1
      api_key: "none"
  - model_name: background
    litellm_params:
      model: openai/qwen2.5:7b
      api_base: http://host.docker.internal:11434/v1
      api_key: "none"
  - model_name: reasoning
    litellm_params:
      model: openai/deepseek-r1:7b
      api_base: http://host.docker.internal:11434/v1
      api_key: "none"

litellm_settings:
  drop_params: true
  request_timeout: 900

router_settings:
  routing_strategy: simple-shuffle
  num_retries: 1

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
  # Global concurrency cap protecting the single GPU.
  global_max_parallel_requests: 8
```

- [ ] **Step 4: Write `docker-compose.yml`** (LAN-only; bound to the proxy network; reachable by the queue at `http://llm-gateway:4000`)

```yaml
services:
  llm-gateway:
    image: ghcr.io/berriai/litellm:main-stable
    container_name: llm-gateway
    restart: unless-stopped
    env_file: .env
    command: ["--config", "/app/config.yaml", "--port", "4000"]
    environment:
      # LiteLLM reads DATABASE_URL; build it from the Postgres password.
      DATABASE_URL: "postgresql://litellm:${POSTGRES_PASSWORD}@llm-gateway-db:5432/litellm"
    volumes:
      - ./config.yaml:/app/config.yaml:ro
    extra_hosts:
      - "host.docker.internal:host-gateway"
    depends_on:
      llm-gateway-db:
        condition: service_healthy
    networks:
      - proxy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:4000/health/liveliness', timeout=4).status==200 else 1)"]
      interval: 30s
      timeout: 6s
      retries: 3
      start_period: 40s
    labels:
      - "autoheal=true"
      - "traefik.enable=true"
      - "traefik.docker.network=proxy"
      - "traefik.http.routers.llm-gateway.rule=Host(`llm-gateway.rt-541.io`)"
      - "traefik.http.routers.llm-gateway.entrypoints=secure"
      - "traefik.http.routers.llm-gateway.tls.certresolver=default"
      - "traefik.http.routers.llm-gateway.middlewares=lan-only@docker"
      - "traefik.http.services.llm-gateway.loadbalancer.server.port=4000"
      - "traefik.http.middlewares.lan-only.ipallowlist.sourcerange=192.168.1.0/24,127.0.0.1/32"

  llm-gateway-db:
    image: postgres:16-alpine
    container_name: llm-gateway-db
    restart: unless-stopped
    environment:
      POSTGRES_DB: litellm
      POSTGRES_USER: litellm
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - /docker/llm-gateway/data/postgres:/var/lib/postgresql/data
    networks:
      - proxy
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U litellm -d litellm"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s

  llm-gateway-autoheal:
    image: willfarrell/autoheal:latest
    container_name: llm-gateway-autoheal
    restart: unless-stopped
    environment:
      AUTOHEAL_CONTAINER_LABEL: autoheal
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock

networks:
  proxy:
    external: true
```

- [ ] **Step 5: Write `README.md`** (short; how to run + that it is LAN-only and fronts the backends)

```markdown
# llm-gateway

LAN-only LiteLLM proxy that owns per-user API keys and quotas for the LLM fleet.
Fronts the B70 vLLM (GPU) and nemesis CPU Ollama. The `llm-queue` app validates
caller keys against this gateway and routes jobs through it; this gateway is
never exposed to the internet.

- Aliases (model groups): `fast` (vLLM), `background` / `reasoning` (Ollama).
- Reachable on the LAN at `http://llm-gateway:4000` (proxy network) and
  `https://llm-gateway.rt-541.io` (lan-only).
- Keys/quotas live in the Postgres sidecar (`llm-gateway-db`), data at
  `/docker/llm-gateway/data/postgres`. LiteLLM requires Postgres for virtual-key
  persistence (its Prisma schema rejects sqlite).

## Run
    cd /docker/homelab-config/nemesis/composed-apps/llm-gateway
    sudo docker compose down && sudo docker compose up -d   # restart = down+up

## Issue / revoke a key
    source .env
    # issue (returns {"key":"sk-..."}):
    curl -s http://llm-gateway:4000/key/generate \
      -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H 'Content-Type: application/json' \
      -d '{"models":["fast","background","reasoning"],"max_budget":5,"rpm_limit":20,"tpm_limit":40000,"max_parallel_requests":2,"duration":"30d"}'
    # revoke:
    curl -s http://llm-gateway:4000/key/delete \
      -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H 'Content-Type: application/json' \
      -d '{"keys":["sk-..."]}'
```

- [ ] **Step 6: Create the data dir and bring it up**

```bash
sudo mkdir -p /docker/llm-gateway/data
cp .env.example .env
# edit .env: set LITELLM_MASTER_KEY and LITELLM_SALT_KEY to real random values
cd /docker/homelab-config/nemesis/composed-apps/llm-gateway
sudo docker compose up -d
```

- [ ] **Step 7: Verify it is healthy and serving the allowlisted models**

```bash
sleep 30; source .env
curl -s http://llm-gateway:4000/health/liveliness          # expect: "I'm alive!"
curl -s http://llm-gateway:4000/v1/models -H "Authorization: Bearer $LITELLM_MASTER_KEY"
# expect a list containing exactly fast, background, reasoning
```
Expected: liveliness OK; models list shows only the three aliases.

- [ ] **Step 8: Commit**

```bash
cd /docker/homelab-config
sudo git add nemesis/composed-apps/llm-gateway
sudo git commit -m "feat(llm-gateway): LAN-only LiteLLM proxy fronting vLLM + Ollama"
```

---

### Task 2: Issue a test key and verify key gating + quotas (integration)

**Files:** none (operational verification of the running gateway).

- [ ] **Step 1: Unauthenticated request is rejected**

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://llm-gateway:4000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"fast","messages":[{"role":"user","content":"hi"}]}'
```
Expected: `401`.

- [ ] **Step 2: Issue a tiny-budget test key**

```bash
source .env
curl -s http://llm-gateway:4000/key/generate \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H 'Content-Type: application/json' \
  -d '{"models":["fast","background","reasoning"],"max_budget":0.01,"rpm_limit":2,"duration":"1d"}'
```
Expected: JSON containing `"key":"sk-..."`. Save it as `$TESTKEY`.

- [ ] **Step 3: Valid key gets a completion**

```bash
curl -s http://llm-gateway:4000/v1/chat/completions \
  -H "Authorization: Bearer $TESTKEY" -H 'Content-Type: application/json' \
  -d '{"model":"background","messages":[{"role":"user","content":"say hi in one word"}]}'
```
Expected: a normal OpenAI-shaped completion JSON.

- [ ] **Step 4: `/key/info` returns the key's metadata (the queue will use this)**

```bash
curl -s "http://llm-gateway:4000/key/info?key=$TESTKEY" -H "Authorization: Bearer $TESTKEY"
```
Expected: JSON with `info.models` and budget fields. (Note: a key may query its own info with itself as the bearer — confirm this returns 200; if your LiteLLM build requires the master key here, record that and the queue will use the master key for validation instead — see Task 5 Step 1.)

- [ ] **Step 5: A non-allowlisted model is refused**

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://llm-gateway:4000/v1/chat/completions \
  -H "Authorization: Bearer $TESTKEY" -H 'Content-Type: application/json' \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"hi"}]}'
```
Expected: `400` or `401` (not a completion).

- [ ] **Step 6: Revoke the test key, confirm it now 401s**

```bash
curl -s http://llm-gateway:4000/key/delete \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H 'Content-Type: application/json' \
  -d "{\"keys\":[\"$TESTKEY\"]}"
curl -s -o /dev/null -w "%{http_code}\n" "http://llm-gateway:4000/key/info?key=$TESTKEY" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY"
```
Expected: after delete, the key is unknown (404/400) — revocation is immediate.

No commit (verification only). Record the working `/key/info` auth mode for Task 5.

---

## Part B2 — queue rewire (TDD). Each task keeps the existing 45 tests green.

### Task 3: Fernet crypto helper for per-job key storage

**Files:**
- Modify: `nemesis/composed-apps/llm-queue/requirements.txt`
- Create: `nemesis/composed-apps/llm-queue/app/crypto.py`
- Create: `nemesis/composed-apps/llm-queue/tests/test_crypto.py`

- [ ] **Step 1: Add the dependency**

Add to `requirements.txt`:
```
cryptography>=43,<45
```

- [ ] **Step 2: Make the test env provide a Fernet key** — append to `tests/conftest.py`:

```python
from cryptography.fernet import Fernet  # noqa: E402
os.environ.setdefault("JOB_KEY_SECRET", Fernet.generate_key().decode())
```

- [ ] **Step 3: Write the failing test** — `tests/test_crypto.py`:

```python
import pytest
from app import crypto


def test_round_trip():
    token = crypto.encrypt("sk-secret-123")
    assert token != "sk-secret-123"
    assert crypto.decrypt(token) == "sk-secret-123"


def test_encrypt_none_is_none():
    assert crypto.encrypt(None) is None
    assert crypto.decrypt(None) is None


def test_tampered_token_raises():
    token = crypto.encrypt("sk-secret-123")
    with pytest.raises(Exception):
        crypto.decrypt(token + "x")
```

- [ ] **Step 4: Run it, expect failure**

Run the suite (see header). Expected: `test_crypto.py` fails with `ModuleNotFoundError: No module named 'app.crypto'`.

- [ ] **Step 5: Implement `app/crypto.py`**

```python
"""Symmetric encryption for secrets persisted at rest (per-job LiteLLM keys).

A job is submitted now but run later by a worker, so the submitter's virtual key
must be stored between the two. Store it Fernet-encrypted, keyed by JOB_KEY_SECRET
(a urlsafe-base64 32-byte key, generated with `Fernet.generate_key()`), and scrub
it once the job reaches a terminal state.
"""
from __future__ import annotations

import os
from typing import Optional

from cryptography.fernet import Fernet


def _fernet() -> Fernet:
    secret = os.environ.get("JOB_KEY_SECRET")
    if not secret:
        raise RuntimeError("JOB_KEY_SECRET is not set; cannot encrypt per-job keys")
    return Fernet(secret.encode())


def encrypt(plaintext: Optional[str]) -> Optional[str]:
    if plaintext is None:
        return None
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: Optional[str]) -> Optional[str]:
    if token is None:
        return None
    return _fernet().decrypt(token.encode()).decode()
```

- [ ] **Step 6: Run tests, expect pass**

Expected: `test_crypto.py` passes; full suite still green.

- [ ] **Step 7: Commit**

```bash
cd /docker/homelab-config
sudo git add nemesis/composed-apps/llm-queue/app/crypto.py \
  nemesis/composed-apps/llm-queue/tests/test_crypto.py \
  nemesis/composed-apps/llm-queue/tests/conftest.py \
  nemesis/composed-apps/llm-queue/requirements.txt
sudo git commit -m "feat(llm-queue): Fernet crypto helper for per-job key storage"
```

---

### Task 4: Persist + scrub the encrypted key on the job row

**Files:**
- Modify: `nemesis/composed-apps/llm-queue/app/db.py` (SCHEMA, `add_job`, new `scrub_key`)
- Modify: `nemesis/composed-apps/llm-queue/app/models.py` (`Job.enc_key`, `from_row`)
- Modify: `nemesis/composed-apps/llm-queue/tests/test_db.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_db.py`:

```python
@pytest.mark.asyncio
async def test_add_job_stores_and_scrubs_enc_key(tmp_store):
    job = await tmp_store.add_job(
        id="k1", owner="ownerhash", prompt="p", alias="fast", tier="gpu",
        params={}, created_at="2026-01-01T00:00:00+00:00", enc_key="ENC",
    )
    assert job.enc_key == "ENC"
    again = await tmp_store.get_job("k1")
    assert again.enc_key == "ENC"
    await tmp_store.scrub_key("k1")
    assert (await tmp_store.get_job("k1")).enc_key is None
```

(Use whatever store fixture `test_db.py` already defines; if it constructs `Store(":memory:")` inline, mirror that and name it `tmp_store` or reuse the existing fixture name.)

- [ ] **Step 2: Run it, expect failure**

Expected: fails — `add_job() got an unexpected keyword argument 'enc_key'`.

- [ ] **Step 3: Add the column to `SCHEMA`** in `db.py` (inside the `CREATE TABLE`, after `finished_at TEXT`):

```python
  finished_at TEXT,
  enc_key TEXT
```

Because `CREATE TABLE IF NOT EXISTS` will not alter an existing table, also add a forward-compatible migration in `Store.connect`, right after `await self._db.executescript(SCHEMA)`:

```python
        # Phase B: add enc_key to pre-existing tables (idempotent).
        cur = await self._db.execute("PRAGMA table_info(jobs)")
        cols = {r["name"] for r in await cur.fetchall()}
        if "enc_key" not in cols:
            await self._db.execute("ALTER TABLE jobs ADD COLUMN enc_key TEXT")
```

- [ ] **Step 4: Thread `enc_key` through `add_job`** — change the signature and INSERT:

```python
    async def add_job(
        self,
        *,
        id: str,
        owner: str,
        prompt: str,
        alias: str,
        tier: str,
        params: dict[str, Any],
        created_at: str,
        enc_key: Optional[str] = None,
    ) -> Job:
        await self.db.execute(
            """INSERT INTO jobs (id, owner, prompt, alias, tier, params, status, created_at, enc_key)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (id, owner, prompt, alias, tier, json.dumps(params or {}),
             JobStatus.QUEUED.value, created_at, enc_key),
        )
        await self.db.commit()
        job = await self.get_job(id)
        assert job is not None
        return job
```

- [ ] **Step 5: Add `scrub_key`** to `Store` (next to `complete_job`):

```python
    async def scrub_key(self, id: str) -> None:
        """Drop the stored per-job key once it is no longer needed."""
        await self.db.execute("UPDATE jobs SET enc_key=NULL WHERE id=?", (id,))
        await self.db.commit()
```

- [ ] **Step 6: Carry `enc_key` on the model** — in `models.py`, add the field to `Job` (after `position`):

```python
    enc_key: Optional[str] = None  # Fernet-encrypted caller key; scrubbed on terminal
```

and in `Job.from_row`, add (guard for older rows / tests without the column):

```python
            enc_key=(row["enc_key"] if "enc_key" in row.keys() else None),
```

`to_public()` must NOT include `enc_key` (leave it out — it is a secret).

- [ ] **Step 7: Run tests, expect pass**

Expected: new test passes; existing `test_db.py` + full suite green.

- [ ] **Step 8: Commit**

```bash
cd /docker/homelab-config
sudo git add nemesis/composed-apps/llm-queue/app/db.py \
  nemesis/composed-apps/llm-queue/app/models.py \
  nemesis/composed-apps/llm-queue/tests/test_db.py
sudo git commit -m "feat(llm-queue): persist + scrub per-job encrypted key"
```

---

### Task 5: Validate a LiteLLM key in `auth.py`; owner = key hash

**Files:**
- Modify: `nemesis/composed-apps/llm-queue/app/auth.py`
- Modify: `nemesis/composed-apps/llm-queue/tests/test_api.py` (or a new `tests/test_auth.py`)

- [ ] **Step 1: Write the failing test** — create `tests/test_auth.py`:

```python
import hashlib
import pytest
from app import auth


@pytest.fixture
def gateway_ok(monkeypatch):
    async def fake_info(key):
        return key.startswith("sk-good")
    monkeypatch.setattr(auth, "_validate_key_remote", fake_info)


@pytest.mark.asyncio
async def test_valid_key_yields_hash_owner(gateway_ok):
    owner = await auth.owner_for_token("sk-good-123")
    assert owner == "k:" + hashlib.sha256(b"sk-good-123").hexdigest()[:32]


@pytest.mark.asyncio
async def test_invalid_key_returns_none(gateway_ok):
    assert await auth.owner_for_token("sk-bad") is None


@pytest.mark.asyncio
async def test_missing_token_returns_none(gateway_ok):
    assert await auth.owner_for_token(None) is None
```

- [ ] **Step 2: Run it, expect failure**

Expected: fails — `module 'app.auth' has no attribute 'owner_for_token'`.

- [ ] **Step 3: Implement key validation in `auth.py`** — add imports and functions; keep existing names. Add near the top:

```python
import hashlib
import os
import httpx
```

Add the gateway-backed validator and the owner helper (replacing the Phase A password path for API/MCP; the password helpers may stay for now but are unused by callers):

```python
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://llm-gateway:4000")
# How to authenticate the /key/info probe. "self" = the key validates itself;
# "master" = use GATEWAY_MASTER_KEY (set if Task 2 Step 4 required the master key).
GATEWAY_KEYINFO_AUTH = os.environ.get("GATEWAY_KEYINFO_AUTH", "self")
GATEWAY_MASTER_KEY = os.environ.get("GATEWAY_MASTER_KEY", "")


def owner_hash(key: str) -> str:
    return "k:" + hashlib.sha256(key.encode()).hexdigest()[:32]


async def _validate_key_remote(key: str) -> bool:
    """Return True if the gateway recognizes this virtual key. Fails closed."""
    bearer = GATEWAY_MASTER_KEY if GATEWAY_KEYINFO_AUTH == "master" else key
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"{GATEWAY_URL}/key/info",
                params={"key": key},
                headers={"Authorization": f"Bearer {bearer}"},
            )
        return r.status_code == 200
    except httpx.HTTPError:
        return False


async def owner_for_token(token: str | None) -> str | None:
    """Validate a bearer/login token against the gateway; return its owner hash."""
    if not token:
        return None
    if not await _validate_key_remote(token):
        return None
    return owner_hash(token)
```

Now make the FastAPI dependencies async and gateway-backed:

```python
async def require_api_auth(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> str:
    """Validate the API/MCP virtual key against the gateway; return owner hash."""
    token = _extract_bearer(authorization, x_api_key)
    owner = await owner_for_token(token)
    if owner is None:
        raise HTTPException(status_code=401, detail="invalid or missing API token")
    return owner
```

Keep `token_is_valid` working for the MCP ASGI guard, but route it through the gateway. Replace its body:

```python
async def token_is_valid(authorization: str | None, x_api_key: str | None) -> bool:
    token = _extract_bearer(authorization, x_api_key)
    return await owner_for_token(token) is not None
```

> NOTE: `token_is_valid` becomes **async**. Task 6b updates the one caller (`middleware.MCPBearerAuth`) to await it. Keep this in the same commit so the suite stays green.

- [ ] **Step 4: Update the MCP guard to await the now-async check** — in `app/middleware.py`, change:

```python
            if not await token_is_valid(headers.get("authorization"), headers.get("x-api-key")):
```

- [ ] **Step 5: Make the test suite able to reach a fake gateway** — the existing `client` fixtures send `Authorization: Bearer test-pw`. Add a global autouse fixture so all tests treat `test-pw` and `sk-good*` as valid without a real gateway. Append to `tests/conftest.py`:

```python
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _fake_gateway(monkeypatch):
    async def fake_validate(key):
        return bool(key) and (key == "test-pw" or key.startswith("sk-good"))
    import app.auth as _auth
    monkeypatch.setattr(_auth, "_validate_key_remote", fake_validate)
```

This keeps `Bearer test-pw` valid (existing tests unchanged) while owner becomes a hash. Existing API tests that assert `owner == "local"` must change to assert the hash; update them: any `assert ... owner == "local"` becomes `assert resp.json()["owner"].startswith("k:")`.

- [ ] **Step 6: Run tests, expect pass**

Expected: `test_auth.py` passes; full suite green after the owner-assertion updates.

- [ ] **Step 7: Commit**

```bash
cd /docker/homelab-config
sudo git add nemesis/composed-apps/llm-queue/app/auth.py \
  nemesis/composed-apps/llm-queue/app/middleware.py \
  nemesis/composed-apps/llm-queue/tests/test_auth.py \
  nemesis/composed-apps/llm-queue/tests/conftest.py \
  nemesis/composed-apps/llm-queue/tests/test_api.py
sudo git commit -m "feat(llm-queue): validate LiteLLM keys via gateway; owner = key hash"
```

---

### Task 6: Route `backends.run` through the gateway with the caller's key

**Files:**
- Modify: `nemesis/composed-apps/llm-queue/app/backends.py`
- Modify: `nemesis/composed-apps/llm-queue/tests/test_backends.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_backends.py`:

```python
import pytest
import httpx
from app import backends


@pytest.mark.asyncio
async def test_run_calls_gateway_with_caller_key(monkeypatch):
    captured = {}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {"choices": [{"message": {"content": "hi"}}]}

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["model"] = json["model"]
            return FakeResp()

    monkeypatch.setattr(backends, "GATEWAY_URL", "http://gw:4000")
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    out = await backends.run("fast", "hello", api_key="sk-good-1")
    assert out == "hi"
    assert captured["url"] == "http://gw:4000/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-good-1"
    assert captured["model"] == "fast"  # alias IS the LiteLLM model group name
```

- [ ] **Step 2: Run it, expect failure**

Expected: fails — `run()` ignores `api_key` and posts to the per-backend URL with model `qwen2.5-7b-instruct`, not the gateway with model `fast`.

- [ ] **Step 3: Rewrite `run` to call the gateway** — replace the `run` function body in `backends.py` (keep the registry/`get_backend`/`tier_for` for selection + tier mapping):

```python
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://llm-gateway:4000")


async def run(
    alias: str,
    prompt: str,
    params: Optional[dict[str, Any]] = None,
    *,
    api_key: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    """POST a chat completion to the LiteLLM gateway as the caller, return text.

    The alias IS the gateway model-group name (fast|background|reasoning), so the
    alias->concrete-model mapping lives in the gateway, not here. ``api_key`` is
    the caller's virtual key; the gateway enforces that key's quota.
    """
    if alias not in REGISTRY:
        raise KeyError(f"unknown alias: {alias!r}")
    if not api_key:
        raise RuntimeError("backends.run requires the caller's api_key in Phase B")
    params = dict(params or {})
    body: dict[str, Any] = {
        "model": alias,
        "messages": [{"role": "user", "content": prompt}],
    }
    for k in ("temperature", "top_p", "max_tokens", "stop", "seed"):
        if k in params:
            body[k] = params[k]
    headers = {"Authorization": f"Bearer {api_key}"}

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
    try:
        resp = await client.post(
            f"{GATEWAY_URL}/v1/chat/completions", json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"gateway returned no choices for {alias}: {data!r}")
        content = (choices[0].get("message") or {}).get("content")
        if content is None:
            raise RuntimeError(f"gateway returned no content for {alias}: {data!r}")
        return content
    finally:
        if own_client:
            await client.aclose()
```

> The test monkeypatches `httpx.AsyncClient` as a context manager; the production code uses `httpx.AsyncClient(...)` + `aclose()`. Both work because the fake supports `__aenter__/__aexit__` AND is also fine when constructed directly — but to match the test exactly, the fake is used as a plain object here (no `async with`), so `aclose` is never called on it. Keep the production `try/finally` as written; the fake's missing `aclose` is not invoked because `own_client` path calls `aclose()` — add `async def aclose(self): pass` to `FakeClient` in the test. (Update the test fake accordingly.)

- [ ] **Step 4: Add `aclose` to the test fake** — in the test from Step 1, add to `FakeClient`:

```python
        async def aclose(self): pass
```

- [ ] **Step 5: Run tests, expect pass**

Expected: new test passes. NOTE: `test_worker.py` and `test_mcp.py` use a `_fake_run` that will now be called with an extra `api_key=` kwarg — they already accept `**kw`/`**kwargs`, so confirm. If any fake `run` signature does not accept `api_key`, add `api_key=None` to it. Full suite green.

- [ ] **Step 6: Commit**

```bash
cd /docker/homelab-config
sudo git add nemesis/composed-apps/llm-queue/app/backends.py \
  nemesis/composed-apps/llm-queue/tests/test_backends.py
sudo git commit -m "feat(llm-queue): route backends.run through the LiteLLM gateway"
```

---

### Task 7: Worker decrypts the per-job key, passes it to `run`, scrubs on terminal

**Files:**
- Modify: `nemesis/composed-apps/llm-queue/app/worker.py`
- Modify: `nemesis/composed-apps/llm-queue/tests/test_worker.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_worker.py`:

```python
@pytest.mark.asyncio
async def test_worker_decrypts_key_and_scrubs(tmp_store):
    from app import crypto
    captured = {}

    async def fake_run(alias, prompt, params=None, *, api_key=None, **kw):
        captured["api_key"] = api_key
        return f"ran {alias}"

    await tmp_store.add_job(
        id="w1", owner="o", prompt="p", alias="fast", tier="gpu", params={},
        created_at="2026-01-01T00:00:00+00:00", enc_key=crypto.encrypt("sk-good-9"),
    )
    pool = worker.WorkerPool(tmp_store, run_fn=fake_run)
    ran = await pool.process_one("gpu")
    assert ran is True
    assert captured["api_key"] == "sk-good-9"          # decrypted before the call
    job = await tmp_store.get_job("w1")
    assert job.status == "done"
    assert job.enc_key is None                          # scrubbed after completion
```

(Reuse the store fixture name `test_worker.py` already uses.)

- [ ] **Step 2: Run it, expect failure**

Expected: fails — `process_one` calls `run_fn(job.alias, job.prompt, job.params)` with no `api_key`, and never scrubs.

- [ ] **Step 3: Update `process_one`** in `worker.py` — change the run call + add scrubbing in a `finally`:

```python
    async def process_one(self, tier: str) -> bool:
        """Claim and run a single job for ``tier``. Returns True if one ran."""
        job = await self.store.claim_next(tier, utcnow_iso())
        if job is None:
            return False
        log.info("tier=%s claimed job=%s alias=%s", tier, job.id, job.alias)
        from . import crypto
        try:
            api_key = crypto.decrypt(job.enc_key)
            result = await self.run_fn(job.alias, job.prompt, job.params, api_key=api_key)
            await self.store.complete_job(job.id, result, utcnow_iso())
            log.info("job=%s done (%d chars)", job.id, len(result))
        except asyncio.CancelledError:
            raise
        except Exception as e:  # record a real failure, don't swallow it
            await self.store.fail_job(job.id, f"{type(e).__name__}: {e}", utcnow_iso())
            log.warning("job=%s failed: %s", job.id, e)
        finally:
            await self.store.scrub_key(job.id)  # never keep the key past one run
        return True
```

Also update the `RunFn` type alias to allow the kwarg:

```python
RunFn = Callable[..., Awaitable[str]]
```

- [ ] **Step 4: Run tests, expect pass**

Expected: new test passes; existing worker tests green (their fakes accept `**kw`).

- [ ] **Step 5: Commit**

```bash
cd /docker/homelab-config
sudo git add nemesis/composed-apps/llm-queue/app/worker.py \
  nemesis/composed-apps/llm-queue/tests/test_worker.py
sudo git commit -m "feat(llm-queue): worker decrypts per-job key, scrubs after run"
```

---

### Task 8: Submit paths store the caller key; web login takes a key

**Files:**
- Modify: `nemesis/composed-apps/llm-queue/app/api.py`
- Modify: `nemesis/composed-apps/llm-queue/app/mcp_server.py`
- Modify: `nemesis/composed-apps/llm-queue/app/auth.py` (cookie carries owner + key)
- Modify: `nemesis/composed-apps/llm-queue/app/web.py`
- Modify: `nemesis/composed-apps/llm-queue/tests/test_api.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_api.py` (the REST submit must persist an encrypted key, and the worker must be able to spend it):

```python
def test_submit_persists_encrypted_caller_key(client):
    r = client.post("/api/jobs", headers={"Authorization": "Bearer sk-good-7"},
                    json={"prompt": "hello", "alias": "fast"})
    assert r.status_code == 200
    jid = r.json()["id"]
    # enc_key is never exposed publicly...
    got = client.get(f"/api/jobs/{jid}", headers={"Authorization": "Bearer sk-good-7"})
    assert "enc_key" not in got.json()
    # ...but it is stored, encrypted, and decrypts to the caller key.
    import asyncio
    from app import state, crypto
    job = asyncio.get_event_loop().run_until_complete(state.get_store().get_job(jid))
    assert job.enc_key is not None
    assert crypto.decrypt(job.enc_key) == "sk-good-7"
```

- [ ] **Step 2: Run it, expect failure**

Expected: fails — `job.enc_key is None` (submit does not store the key yet).

- [ ] **Step 3: Make the REST submit capture + store the key** — in `api.py`, the dependency must return both owner and key. Replace the `require_api_auth` dependency usage on `submit_job` with a small wrapper that also yields the raw token. Add to `auth.py`:

```python
from dataclasses import dataclass


@dataclass
class Caller:
    owner: str
    key: str


async def require_caller(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> "Caller":
    token = _extract_bearer(authorization, x_api_key)
    owner = await owner_for_token(token)
    if owner is None:
        raise HTTPException(status_code=401, detail="invalid or missing API token")
    return Caller(owner=owner, key=token)
```

In `api.py`, update the submit route to use it and store the encrypted key:

```python
from .auth import require_api_auth, require_caller, Caller
from . import crypto


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
```

(The other API routes keep `Depends(require_api_auth)`; they only need the owner.)

- [ ] **Step 4: Update the MCP tools to read the caller from the HTTP request and scope by owner** — FastMCP 2.13 exposes the current request's headers to a tool via `fastmcp.server.dependencies.get_http_headers()` (returns `{}` when there is no HTTP request, e.g. unit tests calling `.fn()` directly — so tests fall back to `OWNER_LOCAL` and stay green). This is more robust than a contextvar set in middleware. Add a helper to `mcp_server.py`:

```python
from fastmcp.server.dependencies import get_http_headers
from .auth import OWNER_LOCAL, _extract_bearer, owner_hash
from . import crypto


def _mcp_caller() -> tuple[str, str | None]:
    """(owner, key) for the current MCP request, from its Authorization header.
    Falls back to (OWNER_LOCAL, None) when there is no HTTP context (direct tests)."""
    headers = get_http_headers()
    key = _extract_bearer(headers.get("authorization"), headers.get("x-api-key"))
    return (owner_hash(key) if key else OWNER_LOCAL), key
```

`submit_job` stores the encrypted caller key + hash owner:

```python
    owner, key = _mcp_caller()
    job = await state.get_store().add_job(
        id=uuid.uuid4().hex, owner=owner, prompt=prompt, alias=alias,
        tier=tier, params=params or {}, created_at=utcnow_iso(),
        enc_key=crypto.encrypt(key),
    )
```

The read/cancel tools (`get_status`, `get_result`, `cancel_job`) must scope to the caller's owner so one user cannot read or cancel another's job by id (closes the gap the Task 5 review flagged). In each, after fetching the job, treat a foreign-owner job as not found:

```python
    owner, _ = _mcp_caller()
    job = await state.get_store().get_job(job_id)
    if not job or job.owner != owner:
        raise ValueError("job not found")
```

Apply that owner check in all three tools (in `cancel_job`, before acting on the job).

- [ ] **Step 5: Web login takes a key; cookie carries owner + key** — in `auth.py`, change the session cookie to carry both, and validate keys for the web path:

```python
def make_session_cookie(owner: str, key: str) -> str:
    return _serializer().dumps({"owner": owner, "key": key})


def read_session_cookie(token: str) -> dict | None:
    try:
        data = _serializer().loads(token, max_age=COOKIE_MAX_AGE)
        if isinstance(data, dict) and "owner" in data and "key" in data:
            return data
        return None
    except (BadSignature, Exception):
        return None
```

(Leave `verify_session_cookie` in place returning `read_session_cookie(token) is not None` so nothing breaks.)

In `web.py`, replace the password login + the `OWNER_LOCAL` usages:

```python
def _session(request: Request) -> dict | None:
    token = request.cookies.get(auth.COOKIE_NAME)
    return auth.read_session_cookie(token) if token else None


def _owner(request: Request) -> str | None:
    s = _session(request)
    return s["owner"] if s else None
```

Login submit becomes (field renamed `key`):

```python
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
```

Replace every `_authed(request)` with `_session(request) is not None`, and every `auth.OWNER_LOCAL` (in queue/history/job/submit/cancel routes) with `_owner(request)`. The web `submit_create` stores the key from the session:

```python
    s = _session(request)
    if not s:
        return _redirect_login()
    ...
    job = await state.get_store().add_job(
        id=uuid.uuid4().hex, owner=s["owner"], prompt=prompt, alias=chosen,
        tier=tier, params={}, created_at=utcnow_iso(),
        enc_key=auth_crypto_encrypt(s["key"]),
    )
```

where at the top of `web.py` you add `from . import crypto` and use `crypto.encrypt(s["key"])` (the `auth_crypto_encrypt` name above is illustrative — use `crypto.encrypt`).

Update `login.html` to post a field named `key` (password input) instead of `password`. (Template: change `name="password"` to `name="key"` and the label to "API key".)

- [ ] **Step 6: Run tests, expect pass**

Expected: new submit test passes; full suite green. Update any remaining test that logs in via `password=` form field to `key=` and uses `sk-good-...`.

- [ ] **Step 7: Commit**

```bash
cd /docker/homelab-config
sudo git add nemesis/composed-apps/llm-queue/app/api.py \
  nemesis/composed-apps/llm-queue/app/mcp_server.py \
  nemesis/composed-apps/llm-queue/app/auth.py \
  nemesis/composed-apps/llm-queue/app/web.py \
  nemesis/composed-apps/llm-queue/app/templates/login.html \
  nemesis/composed-apps/llm-queue/tests/test_api.py
sudo git commit -m "feat(llm-queue): key-as-login; submit paths persist caller key"
```

---

### Task 9: Wire env, rebuild, end-to-end smoke on the LAN

**Files:**
- Modify: `nemesis/composed-apps/llm-queue/.env.example`
- Modify: `nemesis/composed-apps/llm-queue/.env` (not committed)
- Modify: `nemesis/composed-apps/llm-queue/docker-compose.yml` (depends_on the gateway is cross-stack; instead document ordering)
- Modify: `nemesis/composed-apps/llm-queue/README.md`

- [ ] **Step 1: Add the new env keys to `.env.example`**

```sh
# Phase B: LiteLLM gateway the queue validates keys against and routes jobs to.
GATEWAY_URL=http://llm-gateway:4000
# /key/info auth mode: "self" (key validates itself) or "master".
GATEWAY_KEYINFO_AUTH=self
GATEWAY_MASTER_KEY=
# Fernet key for per-job key encryption. Generate:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
JOB_KEY_SECRET=REPLACE_ME
```

- [ ] **Step 2: Set the real values in `.env`** (generate `JOB_KEY_SECRET`; set `GATEWAY_*` per Task 2's recorded mode). Keep `APP_PASSWORD`/`SESSION_SECRET` (still used to sign the session cookie).

- [ ] **Step 3: Rebuild + restart the queue**

```bash
cd /docker/homelab-config/nemesis/composed-apps/llm-queue
sudo docker compose down && sudo docker compose up -d --build
sleep 10
curl -s -o /dev/null -w "%{http_code}\n" https://queue.rt-541.io/healthz   # 200
```

- [ ] **Step 4: End-to-end with a real key (issue one on the gateway first)**

```bash
# issue a key on the gateway (see llm-gateway README), call it $K
curl -s https://queue.rt-541.io/api/jobs -H "Authorization: Bearer $K" \
  -H 'Content-Type: application/json' -d '{"prompt":"say hi in one word","alias":"background"}'
# -> {"id": "...", ...}; poll:
curl -s https://queue.rt-541.io/api/jobs/<id>/result -H "Authorization: Bearer $K"
# -> status done, result present. Unauthenticated call -> 401:
curl -s -o /dev/null -w "%{http_code}\n" https://queue.rt-541.io/api/jobs -X POST \
  -H 'Content-Type: application/json' -d '{"prompt":"x","alias":"background"}'
```
Expected: authed job completes; unauth → 401.

- [ ] **Step 5: Update the queue README** (auth is now a LiteLLM key; point at the gateway; note JOB_KEY_SECRET). Replace the Phase A "APP_PASSWORD is the token" wording and the "Phase B (planned)" section with "Phase B (live)".

- [ ] **Step 6: Commit**

```bash
cd /docker/homelab-config
sudo git add nemesis/composed-apps/llm-queue/.env.example \
  nemesis/composed-apps/llm-queue/README.md \
  nemesis/composed-apps/llm-queue/docker-compose.yml
sudo git commit -m "feat(llm-queue): wire gateway + per-job key env; Phase B live on LAN"
```

---

## Part B3 — external exposure (Traefik). Last, reversible step.

### Task 10: Publish `queue.rt-541.io`; add rate limiting

**Files:**
- Modify: `nemesis/composed-apps/llm-queue/docker-compose.yml` (Traefik labels)

- [ ] **Step 1: Add rate-limit + in-flight middleware and drop `lan-only`** — in the `llm-queue` service labels, replace the middleware line and the `lan-only` definition with a public middleware chain:

```yaml
      - "traefik.http.routers.llm-queue.middlewares=queue-ratelimit@docker,queue-inflight@docker"
      - "traefik.http.middlewares.queue-ratelimit.ratelimit.average=30"
      - "traefik.http.middlewares.queue-ratelimit.ratelimit.burst=15"
      - "traefik.http.middlewares.queue-inflight.inflightreq.amount=20"
```

Remove the `traefik.http.routers.llm-queue.middlewares=lan-only@docker` line and the `lan-only` `sourcerange` definition line. Leave the gateway and all other apps on `lan-only`.

- [ ] **Step 2: Restart the queue**

```bash
cd /docker/homelab-config/nemesis/composed-apps/llm-queue
sudo docker compose down && sudo docker compose up -d
```

- [ ] **Step 3: Verify externally** (from off-LAN, e.g. a phone on cellular, or `curl --resolve` through the public IP):

```bash
# unauth -> 401 (reachable, but gated):
curl -s -o /dev/null -w "%{http_code}\n" https://queue.rt-541.io/api/models
# valid key -> 200:
curl -s -o /dev/null -w "%{http_code}\n" https://queue.rt-541.io/api/models \
  -H "Authorization: Bearer $K"
# the gateway must NOT be reachable externally:
curl -s -o /dev/null -w "%{http_code}\n" https://llm-gateway.rt-541.io/v1/models
# expect: timeout / 403 from off-LAN (lan-only still on it)
```
Expected: queue reachable + gated; gateway unreachable off-LAN.

- [ ] **Step 4: Update Homepage tile** — note the queue is now externally reachable (per the standing "keep Homepage updated" rule). Edit `nemesis/composed-apps/homepage/config/services.yaml` description if it states "LAN-only".

- [ ] **Step 5: Commit**

```bash
cd /docker/homelab-config
sudo git add nemesis/composed-apps/llm-queue/docker-compose.yml \
  nemesis/composed-apps/homepage/config/services.yaml
sudo git commit -m "feat(llm-queue): expose queue.rt-541.io publicly with rate limiting"
```

---

## Self-review notes (coverage vs. design)

- **Stand up LiteLLM first** → Tasks 1–2. **Queue rewire** → Tasks 3–9. **Expose** → Task 10. **Queue is sole public door / gateway stays LAN** → Task 1 keeps `lan-only` on the gateway; Task 10 verifies it stays unreachable externally. **Friend key passed through for real quota** → Tasks 3,4,7,8 (store/scrub) + Task 6 (run as caller) + gateway quotas (Task 2).
- **Owner = key hash everywhere**: `auth.owner_hash` (Task 5), API (Task 8 `require_caller`), MCP (Task 8 `get_http_headers` + per-owner scoping on read/cancel), web (Task 8 cookie). The Phase A `OWNER_LOCAL` survives only as the MCP no-HTTP-context fallback (unit tests).
- **Fail closed**: `_validate_key_remote` returns False on any gateway error (Task 5); submit-time gateway-down → 401; `crypto`/`auth` already refuse to start without their secrets.
- **Existing tests stay green**: the autouse `_fake_gateway` fixture (Task 5 Step 5) keeps `Bearer test-pw` valid without a live gateway; owner assertions updated to the hash form.

## Open items to decide during execution (from the design)
- Confirm the `/key/info` auth mode in Task 2 Step 4 and set `GATEWAY_KEYINFO_AUTH` accordingly.
- Tune default per-key quotas (budget / RPM / TPM / max-parallel / timeout) in the gateway key-issue command.
- Decide whether to add Cloudflare orange-cloud / move to the dormant `public-secure:10443` entrypoint now or defer (design says defer).
