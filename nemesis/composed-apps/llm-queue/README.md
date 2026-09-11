# llm-queue

A small job queue for LLM work across the homelab fleet. Submit a prompt, it gets
routed to the right backend tier, runs on a per-tier worker, and you poll for the
result. Reachable at `queue.rt-541.io`.

Auth is **per-user LiteLLM virtual keys** (Phase B): the bearer/login is a key
issued by the `llm-gateway` (LiteLLM) app; the queue validates it against the
gateway, scopes every job to `owner = sha256(key)`, and runs each job through the
gateway *as that user* so the gateway enforces their quota. The submitter's key is
stored Fernet-encrypted on the job row and scrubbed once the job is terminal.

## Surfaces

The same FastAPI app exposes three things (`app/main.py`):

- **Web UI** (`app/web.py`, HTMX) — dashboard to submit jobs and watch them; log
  in with a LiteLLM key. Polls every 2s until a job leaves `queued`/`running`.
- **REST API** (`app/api.py`) — `submit_job` / `get_result` / `cancel_job` /
  list. Every route requires the key as a bearer token (`require_api_auth` /
  `require_caller`); results are owner-scoped.
- **MCP** (`app/mcp_server.py`) — FastMCP mounted at `/mcp` for agent/tool use;
  bearer-gated and owner-scoped (a caller only sees their own jobs).

## Tiers & backends

Capability aliases map to concrete backends in `app/backends.py`. Callers only
ever pass an alias, so Phase B can swap the backend layer for LiteLLM without
touching callers.

| Alias | Runs on | Default model |
|-------|---------|---------------|
| `fast` | B70 vLLM (GPU, devastator, OpenAI-compatible) | `qwen2.5:7b` |
| `background` | nemesis Ollama (CPU) | `qwen2.5:7b` |
| `reasoning` | nemesis Ollama (CPU) | `deepseek-r1:7b` |

Each tier has its own async worker (`app/worker.py`) so a slow CPU job never
blocks a GPU job. Jobs are claimed with an atomic `UPDATE ... RETURNING`
(`app/db.py`) — correct concurrency without locks. SQLite runs in WAL mode.

## Routing

`app/selection.py` picks the alias: a rules table first, with an optional LLM
fallback for ambiguous jobs (`SELECTION_LLM_ENABLED`, prompt in
`prompts/model-selection.md`). The LLM path fails closed to the rules table.

## Config

Copy `.env.example` to `.env` and fill it in. Required (the app refuses to start
without them):

- `SESSION_SECRET` — signs the web session cookie (any long random string).
- `JOB_KEY_SECRET` — Fernet key encrypting each job's caller key at rest.
- `GATEWAY_URL` — the LiteLLM gateway (default `http://llm-gateway:4000`, reached
  over the shared `proxy` Docker network). `GATEWAY_KEYINFO_AUTH` is `self`
  (a key validates itself; verified) or `master` (+ `GATEWAY_MASTER_KEY`).
- `APP_PASSWORD` — legacy; still required to be non-empty (fail-closed) but no
  longer the login.

Issue a key for a user with the `llm-gateway` app (see its README), then use that
key as the bearer / web login here. `FAST_*` / `BACKGROUND_*` / `REASONING_*` now
only supply selection/tier *metadata* (runtime calls go through the gateway).
Other knobs: `RETENTION_DAYS`, `DB_PATH`, `WEBHOOK_URL`.

## Run

```sh
cd /docker/homelab-config/nemesis/composed-apps/llm-queue
sudo docker compose down && sudo docker compose up -d   # restart = down+up
```

Tests:

```sh
pytest          # tests/ covers api, db, worker, selection, mcp, backends, health
```

## Security notes / known gaps

- LAN-only is enforced at the edge by the Traefik `lan-only` middleware. The
  REST routes require the bearer token, and the `/mcp` mount is now guarded by
  the same token via a raw-ASGI middleware (`app/middleware.py`,
  `MCPBearerAuth`) — raw ASGI so it doesn't buffer MCP's SSE streams. So both
  the LAN allowlist and the bearer token must pass before Phase B opens it up.
- `auth.py` fails closed if `APP_PASSWORD`/`SESSION_SECRET` are unset (no
  built-in default credential).

## Phase B (live)

Per-user LiteLLM virtual keys are the login, validated against the gateway
`/key/info`, with `owner = sha256(key)`. The queue routes each job through the
gateway as the submitting user (`backends.run` posts to `GATEWAY_URL` with the
caller's key; the alias is the gateway model-group name), so per-key budgets /
rate limits live in the gateway. The submitter's key is persisted Fernet-encrypted
(`app/crypto.py`, `jobs.enc_key`) and scrubbed by the worker once the job is
terminal. REST/MCP/web all derive owner from the key and scope reads to it.

Design + plan: `docs/superpowers/specs/2026-06-15-llm-queue-phase-b-design.md`,
`docs/superpowers/plans/2026-06-15-llm-queue-phase-b.md`.
