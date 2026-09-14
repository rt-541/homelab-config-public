# LLM Queue + MCP + Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A small web app on nemesis where the user (and later friends) submit LLM jobs, see queue position, and collect results — plus a mounted MCP server so Claude sessions can do the same, with a rules-based "pick the best backend" chooser.

**Architecture:** Single FastAPI container (`data-host/composed-apps/llm-queue/`): SQLite jobs table, an async worker pool with one slot per backend tier, server-rendered Jinja2 + HTMX UI, and a FastMCP server mounted at `/mcp`. Phase A (LAN MVP) calls backends directly by capability alias (`gpu`→B70 vLLM `192.168.1.216:8000`, `cpu`→nemesis Ollama `127.0.0.1:11434`); Phase B swaps the backend client to LiteLLM for friend-facing auth/quota. Behind Traefik at `queue.rt-541.io`, LAN-only first.

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, SQLite (stdlib `sqlite3`/`aiosqlite`), Jinja2, HTMX, `httpx` (OpenAI-compatible calls), FastMCP, Docker Compose, Traefik.

**Spec:** `docs/superpowers/specs/2026-06-12-llm-queue-mcp-frontend-design.md`

**Decisions locked (from the spec):** app `llm-queue`; host `queue.rt-541.io` (MCP at `/mcp`); 1 worker slot per tier (`gpu`,`cpu`); 30-day retention + self-delete; FastAPI + Jinja2 + HTMX single container; `pick_best_backend` = transparent rules table; LAN-only first. Phase A has no LiteLLM (direct-to-backend), Phase B adds it.

**Conventions:** follow CLAUDE.md — `restart: unless-stopped`, `.env` for secrets, sidecars via the menu, container name = dir name. Copy the Traefik LAN-only pattern from `data-host/composed-apps/umami/docker-compose.yml`. Deploy from the app dir with `docker compose down && up -d`.

---

## File structure (all under `data-host/composed-apps/llm-queue/`)

- `docker-compose.yml` — the service + sidecars, Traefik labels
- `Dockerfile` — python:3.12-slim + deps
- `requirements.txt`
- `.env.example` → `.env` (gitignored) — `APP_PASSWORD`, backend URLs, webhook
- `app/main.py` — FastAPI app: lifespan (start worker), mounts UI + API + MCP
- `app/db.py` — SQLite schema + async CRUD for the `jobs` table
- `app/models.py` — dataclasses/Pydantic: `Job`, `JobStatus`, `SubmitRequest`
- `app/selection.py` — capability aliases + intent→alias rules table (`pick`)
- `app/backends.py` — alias→backend registry + OpenAI-compatible `run()` client
- `app/worker.py` — per-tier async worker loop (claim → run → write back)
- `app/api.py` — REST routes (submit/list/status/result/cancel/select/models)
- `app/web.py` — HTML routes (Jinja2 + HTMX)
- `app/mcp_server.py` — FastMCP server + the 6 tools (wraps api/db)
- `app/templates/*.html`, `app/static/*` — UI
- `tests/` — pytest

Keep each module one responsibility. `selection.py` and `backends.py` are the shared "brain" the worker, API, and MCP all call — no routing logic duplicated.

---

## Phase A — LAN MVP

### Task 1: Scaffold app, container, Traefik (LAN-only)

**Files:** create `docker-compose.yml`, `Dockerfile`, `requirements.txt`, `.env.example`, `app/main.py`, `tests/test_health.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_health.py
from fastapi.testclient import TestClient
from app.main import app
def test_health():
    r = TestClient(app).get("/healthz")
    assert r.status_code == 200 and r.json()["status"] == "ok"
```
- [ ] **Step 2: Run it, expect failure** — `pytest tests/test_health.py -v` → fails (no `app.main`).
- [ ] **Step 3: Minimal app**
```python
# app/main.py
from fastapi import FastAPI
app = FastAPI(title="llm-queue")
@app.get("/healthz")
def healthz():
    return {"status": "ok"}
```
- [ ] **Step 4: requirements.txt**
```
fastapi
uvicorn[standard]
jinja2
httpx
aiosqlite
fastmcp
python-multipart
pytest
```
- [ ] **Step 5: Dockerfile**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```
- [ ] **Step 6: docker-compose.yml** (LAN-only Traefik; copy umami's middleware names)
```yaml
services:
  llm-queue:
    build: .
    image: llm-queue:local
    container_name: llm-queue
    restart: unless-stopped
    env_file: .env
    volumes:
      - /docker/llm-queue/data:/data
    networks: [proxy]
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.llm-queue.rule=Host(`queue.rt-541.io`)"
      - "traefik.http.routers.llm-queue.entrypoints=secure"
      - "traefik.http.routers.llm-queue.tls=true"
      - "traefik.http.routers.llm-queue.middlewares=lan-only@docker"
      - "traefik.http.services.llm-queue.loadbalancer.server.port=8080"
networks:
  proxy:
    external: true
```
(Verify the exact LAN-only middleware name + proxy network name in `umami/docker-compose.yml` and match them; nemesis Ollama is reachable from the container at `host.docker.internal` or the host IP — confirm and set in `.env`.)
- [ ] **Step 7: .env.example**
```
APP_PASSWORD=changeme
GPU_BACKEND_URL=http://192.168.1.216:8000/v1
CPU_BACKEND_URL=http://192.168.1.214:11434/v1
GPU_MODEL=qwen2.5-7b-instruct
CPU_MODEL=qwen2.5:7b
WEBHOOK_URL=
RETENTION_DAYS=30
```
- [ ] **Step 8: run test green, commit.**

### Task 2: Jobs table + store (`app/db.py`, `app/models.py`)

- [ ] **Step 1: failing test** — `tests/test_db.py`: create job → status `queued`, queue position counts earlier queued rows, claim moves to `running`, complete writes result + `done`.
- [ ] **Step 2: schema** (in `db.py`, created on startup):
```sql
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,            -- uuid4 hex
  owner TEXT NOT NULL,           -- key prefix / 'local' in Phase A
  prompt TEXT NOT NULL,
  alias TEXT NOT NULL,           -- gpu|cpu (resolved at submit)
  tier  TEXT NOT NULL,           -- gpu|cpu
  params TEXT,                   -- json
  status TEXT NOT NULL,          -- queued|running|done|failed|cancelled
  result TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);
CREATE INDEX IF NOT EXISTS jobs_status_tier ON jobs(status, tier, created_at);
```
- [ ] **Step 3** async functions: `add_job`, `get_job`, `list_jobs(owner)`, `claim_next(tier)` (atomic `UPDATE ... WHERE id=(SELECT id ... status='queued' AND tier=? ORDER BY created_at LIMIT 1) RETURNING *`), `complete_job`, `fail_job`, `cancel_job`, `queue_position(id)`, `prune(older_than)`. Pass timestamps in from the caller (no `datetime.now()` inside pure helpers if you unit-test them — use `utcnow()` in the route layer).
- [ ] **Step 4: green, commit.**

### Task 3: Selection rules + backend registry (`app/selection.py`, `app/backends.py`)

- [ ] **Step 1: failing test** — `pick("summarize this log", latency="batch")` → alias `cpu` w/ rationale; `pick("write and debug this code", latency="interactive")` → `gpu`; unknown → default `gpu`.
- [ ] **Step 2: selection.py** — pure rules table:
```python
ALIASES = {"gpu": "fast GPU model (B70 vLLM)", "cpu": "CPU model (Ollama), slower/cheaper"}
def pick(task: str, latency: str = "interactive", est_context: int = 0) -> tuple[str, str]:
    t = task.lower()
    if latency == "batch" or any(w in t for w in ("summarize", "bulk", "translate", "overnight")):
        return "cpu", "batch/low-urgency → CPU tier"
    if est_context > 12000:
        return "gpu", "large context → GPU tier"
    if any(w in t for w in ("code", "debug", "reason", "analyze", "fast")):
        return "gpu", "interactive/reasoning → GPU tier"
    return "gpu", "default → GPU tier"
```
- [ ] **Step 3: backends.py** — alias→(url, model, tier) from env; `async run(alias, prompt, params) -> str` POSTs OpenAI-compatible `/chat/completions` via httpx (long timeout), returns the assistant text. Tier = alias in Phase A.
- [ ] **Step 4: green, commit.**

### Task 4: Worker pool (`app/worker.py`)

- [ ] **Step 1: failing test** (integration, fake backend): submit 1 gpu + 1 cpu job; both reach `done`; a slow gpu job does NOT delay the cpu job (per-tier slots).
- [ ] **Step 2:** one `asyncio.Task` per tier in `("gpu","cpu")`; loop: `claim_next(tier)` → if none `sleep(1)` → else `backends.run(...)` → `complete_job`/`fail_job`. Started from FastAPI lifespan in `main.py`; cancelled on shutdown.
- [ ] **Step 3: green, commit.**

### Task 5: REST API (`app/api.py`)

- [ ] Routes (each with a test): `POST /api/jobs` (body: prompt, alias?|task+latency, params) → resolves alias via `selection.pick` if not given, writes `queued`, returns `{id, tier, position}`; `GET /api/jobs` (owner) ; `GET /api/jobs/{id}` (+position) ; `GET /api/jobs/{id}/result` ; `DELETE /api/jobs/{id}` (cancel if queued, else delete own row) ; `GET /api/models` (alias list) ; `POST /api/select` → `pick`. Owner in Phase A = `"local"` after password gate. Commit per route group.

### Task 6: Web UI (`app/web.py`, templates)

- [ ] Server-rendered pages + HTMX polling: `/` login (password → signed cookie); `/submit` (prompt textarea, tier/auto select, params); `/queue` (live list w/ position+status, `hx-get` every 2s); `/jobs/{id}` (detail/result, copy button); `/history`. Minimal CSS, no build step. Test the password gate and that submit creates a row. Commit.

### Task 7: MCP server (`app/mcp_server.py`, mounted at `/mcp`)

- [ ] FastMCP server with tools mirroring the API, sharing `db`/`selection`/`backends`: `list_models()`, `pick_best_backend(task, latency?, est_context?)`, `submit_job(prompt, model_or_alias?, params?)`, `get_status(job_id)`, `get_result(job_id)`, `cancel_job(job_id)`. Mount on the FastAPI app at `/mcp` (streamable HTTP). Test each tool calls through to the same store the API uses. Commit.

### Task 8: Retention + deploy + smoke test

- [ ] **Step 1:** daily prune task (asyncio) deleting `done/failed/cancelled` older than `RETENTION_DAYS`; friend self-delete already in `DELETE`.
- [ ] **Step 2:** add sidecars per CLAUDE.md menu — `offen/docker-volume-backup` of `/docker/llm-queue/data`, `autoheal` (label-scoped: add `healthcheck` hitting `/healthz` + `autoheal=true` label), `dozzle` on a chosen port. Ask the user for the Dozzle port + confirm webhook before adding the discord sidecar.
- [ ] **Step 3:** deploy on nemesis: `mkdir -p /docker/llm-queue/data`, `.env` from example (real `APP_PASSWORD`), `docker compose up -d --build`. Add the Traefik file/DNS for `queue.rt-541.io` if needed (mirror umami).
- [ ] **Step 4: smoke test** — from LAN: login, submit a "say hello" job to `gpu` → returns the B70's output; submit a `cpu` job → Ollama output; both show correct queue position; MCP `submit_job` from a quick client returns an id and `get_result` returns text. Commit.

---

## Phase B — friend-facing (after LiteLLM gateway exists)

### Task 9: LiteLLM backend + key-as-login
- [ ] Swap `backends.run` to call the LiteLLM proxy with the **friend's** virtual key (passed as Bearer); make the key the login (validate against LiteLLM `/key/info`); `owner` = key hash. Move alias→backend into LiteLLM model groups (`fast`/`background`/`reasoning`). Keep `selection.pick` (intent→alias) unchanged. Tests with a mock LiteLLM. Then Cloudflare-publish `queue.rt-541.io` per the parent spec and flip the Traefik middleware off LAN-only.

---

## The skill — `llm-job` (after MCP is live)

### Task 10: MCP registration + Claude Code skill
- [ ] **Step 1:** document/register the queue MCP in Claude Code settings (`mcp` entry pointing at `https://queue.rt-541.io/mcp`, streamable HTTP, LAN-only initially). Verify the 6 tools appear in a session.
- [ ] **Step 2:** author a `llm-job` skill (`.claude/skills/llm-job/` or the user's skills dir) that scripts the common flows over those tools: `/llm-job <prompt>` → `pick_best_backend` → `submit_job` → poll `get_status` → render `get_result`; `/llm-job --queue` → list; `/llm-job --tier cpu <prompt>`. Keep it a thin wrapper (the MCP does the work). Test the happy path end-to-end against the live queue.

---

## Self-review notes

- Spec coverage: queue (Tasks 2,4), frontend (Task 6), MCP (Task 7), selection brain (Task 3, shared by worker/API/MCP — no duplication), auth (Phase A password / Phase B key, Task 9), hosting+Traefik LAN-only (Task 1,8), retention (Task 8), the skill (Task 10). All resolved decisions map to a task.
- Phase A is buildable **today** (vLLM GPU is live; Ollama is live); it does not wait on the LiteLLM gateway. Phase B and public exposure are gated on Phase 0 of the parent design.
- Prerequisite for Task 8 smoke test: the B70 vLLM stack (`plex-compute`) must be deployed and serving — that's the in-flight deploy from the bring-up plan.
