# LLM Fleet: Friend-Facing Inference Gateway (Design)

Date: 2026-06-01
Status: Approved for spec review
Repo: nemesis-configs (gateway lives on nemesis)

## Goal

Expose homelab LLM inference to a few off-LAN friends as a small, secure,
multi-user service. Friends get inference only (chat / generate / list models)
through per-user credentials with quotas and easy revocation. Everything built so
far assumed internal-only, single-user; this design replaces that assumption.

## Verified context (checked first-hand on the infra, 2026-06-01)

These supersede the secondhand handoff briefing.

- **nemesis** (192.168.1.214): RHEL 9.7, Docker 29.3, 97Gi RAM with ~70Gi free.
  The "~80% RAM" warning applied to the Proxmox hosts (sienar/incomm), not this
  VM. A gateway container is trivially affordable here. Runs Traefik (80/443) and
  a CPU-only Ollama (127.0.0.1:11434, `qwen2.5:7b` + `deepseek-r1:7b`).
- **Traefik** on nemesis: docker-label provider on the `proxy` network
  (`exposedByDefault: false`), Cloudflare DNS-challenge wildcard certs. A separate
  public entrypoint pair (`public-web:10080` / `public-secure:10443`) is defined
  but currently unused; all public traffic today rides `secure:443`.
- **devastator** (192.168.1.216): incomm VM 103, 18 vCPU / 23Gi RAM, the Plex VM.
  Its passthrough GPU was upgraded from the Arc A380 to an **Intel Arc Pro B70**
  (`[8086:e223]`, Battlemage, 32GB) about an hour before this design. No driver is
  bound yet (5.14 kernel, no `xe`/`i915`), so it is not yet usable for compute or
  modern transcode. incomm has only 32GB RAM total and is ~80% used.
- **Rocinante** (192.168.1.247): the user's RTX 5080 desktop. Not always on,
  wanted for personal use only. Reached today via the existing `gpu-llm` plugin
  (SSH tunnel + on-demand container).
- **No Tailscale** anywhere. **No LiteLLM** anywhere.
- The dedicated dual-B70 Threadripper "beast" from the build plan is **not built**.
  The B70-in-devastator is the MVP step toward it.

## Hard constraints (non-negotiable)

1. Friends get **inference only**. No host-control surface, no SSH, no Pi-hole, no
   game ports, no dashboards.
2. Per-user credentials, per-user quotas / rate limits / concurrency caps /
   timeouts, and immediate revocation.
3. The friend-facing service contains **no privileged path**. Rocinante's
   bring-up (`run-task.ps1`, a scoped `claude -p` agent that runs arbitrary
   commands) is excluded from the friend system entirely; it stays personal-only
   via the existing plugin. This satisfies "bring-up stays internal" by removing
   bring-up from the friend system rather than guarding it.
4. Standing up the B70 must **not break Plex transcoding**. devastator is a single
   VM that runs both Plex and the planned vLLM on the one shared, passed-through
   B70.

## Decisions (locked during brainstorming)

- **A. Ingress:** public Traefik route at `llm.rt-541.io` on the `secure:443`
  entrypoint, behind Cloudflare orange-cloud, on its own isolated router/middleware
  and Docker network. Per-user API keys.
- **B. Gateway:** LiteLLM proxy (buy), one container on nemesis, file-based virtual
  keys for now.
- **C. Phase 0 backend:** the existing always-warm nemesis CPU Ollama, so the first
  shippable milestone has zero GPU and zero privileged surface.
- **Rocinante:** out of the friend service. Personal-only, unchanged plugin.
- **B70 / devastator:** the MVP always-warm GPU backend (Phase 1), stood up as a
  Plex-safe sub-project. The dedicated beast slots in later as one more backend.

## Architecture

```
friends
  -> Cloudflare (orange-cloud: edge TLS, WAF, bot/DDoS, edge rate-limit, hides origin IP)
  -> ASUS port-forward
  -> Traefik on nemesis (llm.rt-541.io router, strict middleware, isolated Docker net)
  -> LiteLLM proxy
       authN: per-friend virtual keys
       authZ: per-key budget / RPM / TPM / max-parallel / request timeout
       global concurrency cap (protect the single scarce GPU)
       model allowlist; only chat/completions/models exposed
       availability-first routing across backends
         |- nemesis CPU Ollama       (direct, always-warm)        Phase 0
         |- devastator B70 vLLM       (direct, always-warm)        Phase 1 (MVP)
         '- [future dedicated beast]  (direct)                     drop-in later
```

No SSH, tunnels, or bring-up exist anywhere in this path.

## Components (each independently understandable and testable)

1. **Cloudflare config** (config, not code). Orange-cloud `llm.rt-541.io`; WAF and
   rate-limit rules; origin pull to the existing nemesis public TLS path.
2. **Traefik router + middleware**. A new labeled service on the `proxy` network,
   host `llm.rt-541.io` on the proven `secure:443` entrypoint, strict middleware
   (no dashboard, only the inference routes). Future hardening: activate the
   dormant `public-secure:10443` entrypoint with its own port-forward for
   entrypoint-level isolation.
3. **LiteLLM proxy**. One container on nemesis. A `config.yaml` defines backends,
   the model allowlist, per-key budgets/limits, and the global concurrency cap.
   Owns all authN/authZ and routing. Exposes only OpenAI-compatible inference
   endpoints. New composed-app at `nemesis/composed-apps/llm-gateway/` in the
   `homelab-config` monorepo (see migration spec). **Key storage:
   simple file-based virtual keys for now** (no database); revisit a DB only if the
   friend count or audit needs grow.
4. **Backend registry** (inside LiteLLM config). Each backend tagged with an access
   mode. Phase 0 and Phase 1 backends are both `direct`; no `tunnel`/`bringup`
   mode is implemented because no friend backend needs it.

## Data flow

1. Friend sends an OpenAI-compatible request with their API key to
   `https://llm.rt-541.io/...`.
2. Cloudflare terminates TLS, applies WAF/rate-limit, forwards to the nemesis
   origin.
3. Traefik matches the `llm.rt-541.io` router, applies middleware, forwards to
   LiteLLM.
4. LiteLLM authenticates the key, enforces budget/rate/concurrency/timeout and the
   model allowlist, then routes availability-first to a warm backend.
5. The backend (CPU Ollama, later B70 vLLM) runs inference and the response returns
   the same way.

## Phasing

- **Phase 0 (whole shippable service):** Cloudflare + Traefik + LiteLLM (keys,
  quotas, limits, model allowlist) in front of the nemesis CPU Ollama. Success
  criterion: a friend with their own key runs a real test workload through
  `llm.rt-541.io`; quotas and instant revocation are demonstrably enforced. No GPU,
  no hardware risk, no privileged path.
- **Phase 1 (real capacity, the B70 MVP):** stand up Battlemage serving on
  devastator as a Plex-safe sub-project (see below), then add it to LiteLLM as a
  `direct`, always-warm backend that becomes the default. CPU Ollama drops to
  fallback. The vLLM stack config lives at
  `devastator/composed-apps/plex-compute/` in the `homelab-config` monorepo (see the
  migration spec, `2026-06-01-homelab-config-monorepo-migration-design.md`).
- **Future (the beast):** the dedicated Threadripper dual-B70 node joins as another
  `direct` backend and becomes primary. Gateway change is a single config entry.

### Phase 1 sub-project: B70 on devastator without breaking Plex

This is a dependency of Phase 1, not part of the gateway, and the gateway does not
wait on it.

- A passthrough GPU is exclusive to one VM, and devastator already owns the B70, so
  Plex and vLLM share the one card inside the one VM. No SR-IOV, no second VM.
- Battlemage needs the `xe` driver (modern kernel, e.g. Ubuntu 24.04+ with Intel
  oneAPI, or an equivalent mainline-kernel path). Modern Plex VA-API transcode on
  the B70 needs the same stack, so the upgrade is required for transcode regardless
  of LLM. The risk is purely the migration restoring VA-API transcode.
- Serve LLM with vLLM (`llm-scaler` build) or IPEX-LLM on oneAPI. Resource-cap vLLM
  (VRAM reservation and request limits) so an LLM load cannot starve Plex transcode.
- incomm has only 32GB RAM total (~80% used) and devastator is allotted 23Gi, which
  is the squeeze for running both. This phase likely needs a small incomm RAM bump.

## Error handling and failure modes

- Backend cold or down with nothing warm: LiteLLM returns a clean 503. Phase 0's
  always-warm CPU Ollama prevents this in practice; a friend is never left hanging
  past the configured request timeout.
- Key over budget or rate: 429 with a clear message. Revocation is immediate
  (delete the virtual key).
- Plex/vLLM contention on the B70 (Phase 1): vLLM is resource-capped so transcode is
  protected; under heavy LLM load, LiteLLM can fall back to the CPU Ollama.
- Surface isolation: Cloudflare and Traefik expose only the inference routes; SSH,
  Pi-hole, dashboards, and game ports are unreachable by construction. Friends never
  share a trust zone with internal services.

## Testing

- Phase 0: an automated check that an unauthenticated request is rejected; that a
  valid key gets a completion; that an over-budget or over-rate key gets 429; that a
  revoked key immediately gets 401; that only allowlisted models are visible; that
  no non-inference path is reachable through `llm.rt-541.io`.
- Phase 1: the same suite plus a load test confirming an LLM workload does not
  degrade Plex transcode below an acceptable threshold.

## Out of scope

- Rocinante in the friend service (personal-only, existing plugin).
- The dedicated Threadripper beast build (future; this design only reserves a
  drop-in backend slot for it).
- Any queue/broker beyond LiteLLM's built-in concurrency control, unless contention
  proves it necessary.

## Open items for the implementation plan

- Confirm the exact external-to-nemesis port-forward for `secure:443` reaching the
  new `llm.rt-541.io` router.
- Choose the Cloudflare origin-pull mode and cert (reuse the existing wildcard).
- Define the file-based key issue/revoke flow in practice (where the keys file
  lives, how a key is added or deleted).
- Propose concrete default quotas (budget, RPM/TPM, max-parallel, timeout) per
  friend for the user to tune.
