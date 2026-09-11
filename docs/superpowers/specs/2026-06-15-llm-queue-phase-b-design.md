# llm-queue Phase B — friend-facing, externally exposed, API-gated (Design)

Date: 2026-06-15
Status: Approved (brainstormed with user 2026-06-15)
Repo: homelab-config (gateway + queue both on nemesis)
Supersedes the Phase B sketch in `2026-06-12-llm-queue-mcp-frontend.md` (Task 9)
and grounds it in the `2026-06-01-llm-fleet-friend-gateway-design.md` gateway.

## Goal

Take the LAN-only single-user `llm-queue` (Phase A, live at `queue.rt-541.io`)
to a multi-user, internet-exposed service where access is **gated by per-user
API keys** with real quotas and instant revocation. Friends submit jobs (REST /
MCP / web UI), each authenticated by their own key, each spending their own
budget on the shared fleet GPU/CPU.

## Verified starting state (2026-06-15)

- **Phase A is live and healthy.** `queue.rt-541.io` behind Traefik with
  `lan-only@docker`. REST + `/mcp` require a bearer token; `/mcp` is now
  bearer-gated (commit `96ab20a`), `auth.py` fails closed without
  `APP_PASSWORD`/`SESSION_SECRET`.
- **Backends are direct.** `backends.run` calls B70 vLLM (`.216:8000`, GPU) and
  nemesis CPU Ollama (`127.0.0.1:11434`) by capability alias.
- **No LiteLLM exists anywhere yet.** The friend-gateway design specced it but
  it was never built. This is the gating dependency for Phase B.
- **Public ingress already works** (now documented authoritatively in
  `CLAUDE.md`): single Traefik edge on nemesis `.214`, `secure:443` is
  internet-facing, Cloudflare wildcard cert for `*.rt-541.io`. A service is
  LAN-only iff its router carries `lan-only@docker`; **dropping that middleware
  publishes it.** No per-service DNS record needed.

## Locked decisions (from brainstorming)

1. **Stand up LiteLLM first**, then rewire the queue to it. (Not the queue's own
   keys table.) LiteLLM owns authN + quotas; the queue delegates.
2. **All three queue surfaces go public**: REST API, `/mcp`, web UI. Each stays
   auth-gated (key bearer / session cookie).
3. **Ingress is the existing Traefik path**: expose `queue.rt-541.io` by dropping
   `lan-only` from its router on `secure:443`. No new entrypoint, no new DNS.
4. **Queue is the sole public door.** The LiteLLM gateway stays LAN-only behind
   the queue (queue → gateway over the LAN). Smallest external attack surface.
5. **The friend's key is passed through to the gateway** so per-user budget is
   enforced by LiteLLM, not faked by a shared service key.

## Architecture

```
friend
  -> Cloudflare (wildcard TLS for *.rt-541.io; orange-cloud WAF/rate-limit optional)
  -> router :443 -> nemesis Traefik (.214), secure:443
       queue.rt-541.io router: NO lan-only  + ratelimit + inflightreq
  -> llm-queue (FastAPI: REST /api, /mcp, web UI)
       authN: bearer/login is a LiteLLM virtual key, validated via /key/info
       owner = sha256(key); job persists the (encrypted) key for the worker
  -> worker runs job -> backends.run() -> LiteLLM gateway (LAN-only, .214:<port>)
       LiteLLM: per-key budget/RPM/TPM/max-parallel/timeout, global concurrency
                cap, model allowlist, model groups fast/background/reasoning
         |- B70 vLLM (.216:8000)   GPU, default
         '- nemesis CPU Ollama     fallback
```

Everything except `queue.rt-541.io` stays on `lan-only`. The gateway is never
internet-reachable.

## Components

### B1 — `llm-gateway` (new composed-app, LAN-only)
- `nemesis/composed-apps/llm-gateway/`: LiteLLM proxy container + `config.yaml`.
- **Virtual keys**: file/db-backed (LiteLLM `--config` + a keys store). Per key:
  `max_budget`, `rpm_limit`, `tpm_limit`, `max_parallel_requests`, `timeout`.
- **Model groups** map the queue's aliases: `fast`→vLLM, `background`→Ollama,
  `reasoning`→Ollama (`deepseek-r1`). Model allowlist = exactly these.
- **Global concurrency cap** to protect the single GPU.
- Master key in `.env` (gitignored). Issue/revoke = documented key-store edit +
  reload. Router carries `lan-only@docker`; bound only to the LAN.
- Sidecars per repo menu (autoheal at minimum; backup of the keys store).

### B2 — queue rewire (only `auth.py` + `backends.py` change behaviorally)
- **`auth.py`**: a bearer/login is now a LiteLLM virtual key. `token_is_valid`,
  `require_api_auth`, `require_web_auth`, `current_owner` keep their signatures
  (callers untouched). Validate against gateway `/key/info`; cache briefly;
  `owner = sha256(key)`. Web `/login` accepts a key instead of the shared
  password. Fail closed if the gateway is unreachable.
- **`backends.py`**: `run(alias, prompt, ..., api_key=...)` calls the LiteLLM
  gateway (OpenAI-compatible) with the **caller's** key as Bearer; alias →
  LiteLLM model group. `selection.pick` (intent→alias) unchanged.
- **Job/worker key handoff**: `add_job` persists the submitter's key encrypted
  at rest (Fernet, key in `.env`); the worker decrypts to call the gateway, then
  scrubs it on terminal status. `owner` column already exists (becomes the hash).
- **MCPBearerAuth** unchanged in shape — it already routes through
  `token_is_valid`, so it picks up key-validation for free.

### B3 — external exposure (Traefik only, reversible)
- Drop `lan-only@docker` from the `queue.rt-541.io` router; add `ratelimit`
  (avg/burst) + `inflightreq` middleware on it. No other router changes.
- Optional hardening (deferred): move the public router to the dormant
  `public-secure:10443` entrypoint; Cloudflare orange-cloud + WAF.

## Data flow (a friend job)

1. Friend → `POST https://queue.rt-541.io/api/jobs` with `Authorization: Bearer
   sk-...` (their LiteLLM key).
2. Queue validates the key via the LAN gateway `/key/info`; `owner = hash(key)`.
3. Queue enqueues the job, persisting the encrypted key with it.
4. The tier worker claims it, decrypts the key, calls the LAN gateway with it.
5. LiteLLM enforces that key's budget/rate/concurrency/timeout + model allowlist,
   routes to a warm backend, returns the completion.
6. Worker stores the result, scrubs the stored key. Friend polls
   `/api/jobs/{id}/result`.

## Error handling / failure modes

- Gateway unreachable at submit → 503, job not accepted (fail closed).
- Invalid/revoked key → 401 at the queue (validation miss) or at the gateway.
- Over budget / rate → 429 surfaced from the gateway into the job error.
- Backend cold/down with nothing warm → gateway 503; CPU Ollama is the warm
  fallback so this is rare.
- Surface isolation: only `queue.rt-541.io` is public; gateway, dashboards, SSH,
  Pi-hole, game ports unreachable from outside by construction.

## Testing

- B1: unauth→401, valid key→completion, over-budget→429, revoked→401, only
  allowlisted models visible, gateway not reachable off-LAN.
- B2: key-as-login (mock gateway `/key/info`); `owner`=hash; encrypted key
  round-trips and is scrubbed on completion; `backends.run` hits the gateway with
  the caller's key; gateway-down → fail closed. Existing 45 tests stay green.
- B3: external unauth→401, valid key end-to-end→result, revoked→401,
  over-quota→429, no non-queue path reachable through the public name.

## Sequencing

B1 ships and is verified entirely on the LAN. B2 rewires the queue against the
live LAN gateway (existing tests stay green throughout). B3 — flipping
`lan-only` off — is the last, single-line, reversible step, done only after B1+B2
pass. Phase A keeps working at every step (the queue stays up; auth swap is the
cutover).

## Out of scope

- The queue's own keys table (rejected: LiteLLM owns keys).
- Exposing the LiteLLM gateway directly (`llm.rt-541.io`) — the queue is the
  door. The OpenAI-compatible gateway can be published later if friends want raw
  inference, but that is a separate decision.
- The dedicated Threadripper "beast" backend (future drop-in).
- Rocinante in the friend path (personal-only).

## Open items for the plan

- Pick the LiteLLM key store (config-file keys vs its DB mode) and the
  issue/revoke ergonomics.
- Concrete default quotas (budget, RPM/TPM, max-parallel, timeout) per friend.
- Encryption-at-rest detail for the per-job key (Fernet key lifecycle in `.env`).
- Whether to add the optional Cloudflare orange-cloud / `public-secure:10443`
  hardening now or defer.
