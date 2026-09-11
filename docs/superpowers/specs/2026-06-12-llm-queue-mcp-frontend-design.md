# LLM Fleet Sub-Project 2: Queueing Front End + MCP Router (Design)

Date: 2026-06-12
Status: Finalized with default decisions (pending user review) — the open
questions below were resolved autonomously with the recommended defaults so an
implementation plan could be written; each is flagged so the user can override.
Parent: `2026-06-01-llm-fleet-friend-gateway-design.md`
Sibling dependency: `2026-06-12-devastator-b70-bringup-design.md` (B70 vLLM backend — GPU now LIVE)

> The body below (options + recommendations) is the design exploration. The
> **Resolved decisions** and **Claude Code skill** sections at the end are the
> finalized choices that the implementation plan
> (`docs/superpowers/plans/2026-06-12-llm-queue-mcp-frontend.md`) builds against.

## Goal

Give friends (and the user, via Claude Code) a way to submit LLM jobs that may
take minutes on the CPU backend, see where they sit in line, and collect
results later — plus an MCP server so any MCP client can submit/inspect jobs
and ask "what backend/model is best for this?" All authN/quota/revocation
stays in LiteLLM per the parent design.

User's vision, verbatim: "I want to build a web front end for queueing and
have an MCP that will decide what is best."

## Sequencing note

Sits on top of the LiteLLM gateway (parent Phase 0), which is approved but
**not yet deployed**. The B70 vLLM backend is being stood up. Everything below
talks to LiteLLM's OpenAI-compatible endpoint, never to backends directly.

## Question 1: Where does the queue live?

- **1A — LiteLLM built-in concurrency only:** zero new components, but no job
  identity, no queue position, no "come back later"; a 10-minute CPU job holds
  an HTTP connection open. Doesn't satisfy the vision.
- **1B — Dedicated queue service (Redis + worker):** battle-tested, but three
  new containers for a few friends; over-built (YAGNI).
- **1C — Job table inside the frontend's own service (SQLite + in-process
  async worker):** one container; rows go `queued → running → done/failed`;
  queue position is SQL; durable across restarts; LiteLLM caps remain the
  backstop. **Recommended.** Interactive/streaming chat does NOT go through
  the queue — it hits LiteLLM directly per the parent design; the queue is for
  jobs.

## Question 2: Frontend — buy vs build

- **2A — Open WebUI / LibreChat:** polished chat UX, but it is a chat UI, not
  a job queue (no position, no submit-and-leave); brings its own user DB
  duplicating LiteLLM keys; admin surface to lock away.
- **2B — Small custom app (FastAPI + server-rendered UI):** exactly the
  vision; async by construction; tiny surface (submit/status/result); same API
  serves the MCP server. **Recommended.** v1 renders text results, no
  streaming, no markdown arms race.
- **2C — Both:** defer; chat-through-key already works with any
  OpenAI-compatible client.

## Question 3: The MCP router and "decide what is best"

Avoid two routing brains. LiteLLM already does availability-first routing,
fallbacks, health.

- **3A — LiteLLM is the brain; MCP thin:** capability aliases as LiteLLM model
  groups (`fast` → B70 vLLM w/ CPU fallback; `background` → CPU qwen2.5:7b;
  `reasoning` → deepseek-r1). "Deciding" = static mapping from job intent to
  alias; LiteLLM handles the dynamic part.
- **3B — MCP is the brain:** duplicates LiteLLM's router; web UI would need
  the same brain; violates parent design. Rejected.
- **3C — Brain lives in the job service; MCP and web are thin clients of it:**
  3A's philosophy with a home. **Recommended.**

MCP tools (streamable-HTTP, authenticated with the caller's LiteLLM virtual
key): `list_models`, `pick_best_backend(task_description, latency_tolerance?,
est_context?)`, `submit_job(prompt, model_or_alias?, params?)`,
`get_status(job_id)`, `get_result(job_id)`, `cancel_job(job_id)`.

Implementation note: the MCP server can be the same FastAPI process as the job
service (FastMCP mounted at `/mcp`) — one container, one auth path.

## Question 4: Auth

- **4A — The LiteLLM virtual key IS the login (recommended):** pasted once,
  stored client-side, sent as Bearer; job service validates against LiteLLM;
  the worker dispatches each job **with the friend's own key** so quotas meter
  queued work exactly like direct use, and revocation kills both instantly.
- **4B — Separate frontend accounts mapping to server-held keys:** second
  credential store, bigger blast radius. Rejected for this scale.

Rule that must hold: the worker never uses a master key.

## Question 5: Hosting, layout, Traefik

- Host: **nemesis** (next to Traefik + LiteLLM; ~70Gi free RAM).
- Layout: `nemesis/composed-apps/llm-queue/` — single service container (job
  API + web UI + worker + mounted MCP), SQLite volume; standard sidecar menu
  applies; ~256–512M memory limit.
- Traefik: Phase A `queue.rt-541.io` with the existing `lan-only@docker`
  ipallowlist (umami pattern). Phase B: drop allowlist, orange-cloud through
  Cloudflare like `llm.rt-541.io`. MCP endpoint rides the same router at
  `/mcp`.
- No new privileged surface; app holds no master key.

## Recommended combination

| Question | Choice |
|---|---|
| Queue | SQLite job table + in-process async worker; LiteLLM caps as backstop |
| Frontend | Small custom app; Open WebUI deferred |
| MCP | Mounted in same app; selection = intent→alias mapping; LiteLLM model groups do dynamic routing |
| Auth | Friend's LiteLLM virtual key is the login; worker uses the friend's key |
| Hosting | `nemesis/composed-apps/llm-queue/`, `queue.rt-541.io`, LAN-only first |

## Data flow

1. Friend opens `queue.rt-541.io`, enters their LiteLLM key (validated).
2. Submits a job (prompt + tier or "pick for me"); selection maps intent →
   alias; row written `queued`; UI shows position.
3. Worker claims the row, calls LiteLLM (`model=<alias>`, friend's key);
   LiteLLM enforces quota and routes to B70 vLLM or CPU Ollama.
4. Result (or error) written to the row; friend collects whenever.
5. Same via MCP tools for Claude Code and other MCP clients.

## Open questions — RESOLVED (defaults chosen autonomously; override freely)

1. **Naming:** composed-app `llm-queue`; hostname `queue.rt-541.io` (separate
   host, not a path under `llm.rt-541.io` — cleaner lifecycle/cert). MCP at
   `queue.rt-541.io/mcp`.
2. **Budget:** queued-job spend counts against the **same** per-friend
   LiteLLM key as direct chat (single key, simplest; revisit if batch abuse).
3. **Worker concurrency:** **1 slot per backend tier** (a CPU job never blocks
   a GPU job). Tiers: `gpu` (B70 vLLM), `cpu` (Ollama).
4. **Retention:** completed jobs kept **30 days then pruned** (a daily sweep);
   a friend can delete their own job rows on demand.
5. **Web stack:** **Python / FastAPI**, single container, server-rendered
   Jinja2 + HTMX for live updates, FastMCP mounted at `/mcp`. No build step.
6. **`pick_best_backend` v1:** **transparent rules table** (intent → capability
   alias) returning the alias + a human-readable rationale string. Any
   LLM-assisted classification is explicitly deferred.
7. **Exposure:** **LAN-only first** (Traefik `lan-only@docker` ipallowlist,
   the umami pattern), including the MCP. Promote to public via Cloudflare
   only after the LiteLLM gateway (parent Phase 0) is deployed and stable.

## Sequencing reality (post-B70 bring-up)

The B70 vLLM backend is the live GPU now (`devastator/composed-apps/plex-compute`,
serving an OpenAI-compatible endpoint at `192.168.1.216:8000`). The **LiteLLM
gateway (parent Phase 0) is still NOT deployed**. To avoid blocking this
sub-project on the gateway, the plan is **two-phase**:

- **Phase A — LAN MVP (no LiteLLM):** the queue worker calls the backends
  **directly** by capability alias — `gpu` → vLLM (`192.168.1.216:8000`),
  `cpu`/`background` → nemesis Ollama (`127.0.0.1:11434`). Auth is a simple
  local app password (LAN-only). This is buildable today and gives the user
  the web queue + MCP immediately.
- **Phase B — friend-facing (with LiteLLM):** swap the worker's backend client
  to LiteLLM, make the friend's LiteLLM virtual key the login, and let LiteLLM
  own auth/quota/dynamic-routing. The alias→backend map moves into LiteLLM
  model groups. Then Cloudflare-publish per the parent design.

The selection rules table and the queue/MCP code are identical across both
phases — only the backend client and the auth source change.

## Claude Code skill (`the skill`)

A thin Claude Code skill, `llm-job`, wraps the queue so you can drive it from
any Claude session without leaving the terminal. Two layers:

1. **MCP registration (the real integration):** the queue app exposes the
   FastMCP server at `queue.rt-541.io/mcp` (streamable HTTP). Registering it as
   an MCP server in Claude Code/Desktop gives every Claude session the tools
   `list_models`, `pick_best_backend`, `submit_job`, `get_status`,
   `get_result`, `cancel_job` natively. This is the primary interface and needs
   no skill code — just an `mcp` entry in settings.
2. **`llm-job` skill (ergonomics):** a small skill that scripts the common
   flows on top of those tools — e.g. "run this prompt on the best backend and
   wait", "show my queue", "summarize this file via the background tier" —
   handling submit → poll → render so the user types `/llm-job <prompt>`
   instead of orchestrating tool calls by hand. Pure convenience over the MCP;
   buildable once the MCP is live.

> Interpretation note: "the skill" was inferred to mean this Claude Code skill
> over the queue/MCP. If you meant something else by "the skill," say so and
> I'll re-aim it.

## Artifacts produced (2026-06-13)

- Model-selection prompt (LLM-assisted `pick_best_backend` path): `nemesis/composed-apps/llm-queue/prompts/model-selection.md`
- Claude Code skill: `.claude/skills/llm-job/SKILL.md`
