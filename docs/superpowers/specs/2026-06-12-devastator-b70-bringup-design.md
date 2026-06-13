# Devastator B70 Bring-up: RHEL 10 + xe Driver + vLLM (Design)

Date: 2026-06-12
Status: IMPLEMENTED 2026-06-13. Kernel path: **stock RHEL 10.2** (`6.12.0-211.22.1.el10_2`,
Red Hat backported the B70 `e223` ID into `xe` — ELRepo kernel-ml was abandoned
because Secure Boot rejects it even when self-signed). Plex HW transcode (VA-API
iHD 25.2.6, latest Plex image) decode+encode on the B70: WORKING. vLLM
(`plex-compute`, Qwen2.5-7B) serving on the B70 at 192.168.1.216:8000: WORKING
(0.92 VRAM split = ~29GB vLLM / ~2.5GB Plex; 8 concurrent gens, no OOM). See
memory `b70-gpu-devastator`.
Parent: `2026-06-01-llm-fleet-friend-gateway-design.md` (this is its "Phase 1
sub-project: B70 on devastator without breaking Plex")

## Goal

Make the Intel Arc Pro B70 (32GB, `8086:e223`) in devastator usable for compute:
in-place upgrade to RHEL 10 via leapp, bind the `xe` kernel driver, stand up a
containerized vLLM serving an OpenAI-compatible endpoint on the LAN, and enable
Plex hardware transcode on the same card — without an LLM load ever starving
Plex. All host changes are codified as Ansible in `kuat-drive-yards` and
executed from the control plane (tarkin).

## Verified context (checked first-hand, 2026-06-12)

- devastator (incomm qemu/103, 192.168.1.216): RHEL 9.6, kernel
  5.14.0-570.35.1. The B70 (`8086:e223`) is passed through but has **no kernel
  driver bound**; `/dev/dri` has only the bochs virtual display. Plex is
  therefore CPU-transcode-only today — this project cannot regress transcode.
- The B70 Pro device ID `e223` entered the mainline `xe` driver in **kernel
  6.17** (consumer B580 landed in 6.12). RHEL 10.0 ships a 6.12-based kernel;
  Red Hat backports DRM aggressively in minor releases (RHEL 9.8 rebased DRM to
  6.16), but `e223` coverage in the current RHEL 10.x kernel is **unverified**
  — it is a runtime check in the plan, with ELRepo as fallback.
- ELRepo publishes `kernel-ml` (mainline, currently 7.0.x) for EL10; it
  installs alongside the RHEL kernel, so rollback is a GRUB menu pick.
- The HA Pi-hole pair owns DNS/DHCP (VIP .2); devastator's Docker Pi-hole is a
  rollback spare. The leapp upgrade is no longer blocked by it.
- RAM stays as-is: incomm has 32GB total, devastator keeps 23Gi. vLLM gets hard
  caps instead of more memory.

## Decisions (locked during brainstorming)

- **OS path:** in-place `leapp` upgrade RHEL 9.6 → 10. No VM rebuild.
- **Kernel:** try the stock RHEL 10 kernel first; if it does not bind `e223`,
  install ELRepo `kernel-ml` in the same window (Option A). The RHEL kernel
  remains the GRUB fallback.
- **Execution:** Ansible playbooks in `kuat-drive-yards/ansible/playbooks/`,
  run from tarkin (pellaeon syncs via the pull cron). Direct SSH from nemesis
  only for read-only checks.
- **Serving stack:** Intel `llm-scaler-vllm` container (Intel's official Arc
  Pro B-series serving path). All GPU userspace (oneAPI, compute runtime,
  vLLM) lives in containers; the host provides only kernel driver + firmware +
  `/dev/dri`.
- **First model:** one mid-size validation model (14B–32B class, quantized) to
  prove the stack. Multi-model serving and routing belong to the next
  sub-project (web queueing front end + MCP router).

## Components

1. **`devastator_b70_preflight.yml`** (kuat-drive-yards, read-only, no
   downtime). Checks: RHSM subscription status; `leapp preupgrade` report with
   zero inhibitors; `docker-ce` EL10 repo availability (the stack stays on
   Docker, not Podman); vzdump target on incomm with space for VM 103; `lo204`
   present on devastator with passwordless sudo; Battlemage GuC/HuC firmware
   blobs present in the RHEL 10 `linux-firmware` package.
2. **`devastator_b70_upgrade.yml`** (kuat-drive-yards, the maintenance
   window). Stops all compose stacks; runs a **stopped** vzdump backup of VM
   103 from incomm (PCI passthrough blocks live snapshots); runs
   `leapp upgrade` with `reboot`/`wait_for_connection` and generous timeouts
   (the leapp initramfs phase is slow); verifies RHEL 10 boots and Docker plus
   all compose stacks return; checks `xe` binding on `8086:e223`; if unbound,
   installs ELRepo `kernel-ml` and reboots into it; verifies `/dev/dri` gains
   the B70's card + render node and a containerized `sycl-ls`/`clinfo` sees
   the GPU.
3. **vLLM composed-app** at `devastator/composed-apps/plex-compute/` in
   homelab-config (location locked by the parent spec). Intel
   `llm-scaler-vllm` image, `/dev/dri` device mount, `restart:
   unless-stopped`, OpenAI-compatible endpoint exposed LAN-only.
4. **Plex compose change**: `/dev/dri` device mount + HW transcode enabled.
   Gated on Plex's bundled transcoder supporting Battlemage — if it does not
   yet, Plex stays on CPU transcode (current behavior) and HW flips on later.

## Resource caps (Plex-safe by construction)

- vLLM container: hard memory limit ~8Gi and a CPU cap via
  `deploy.resources`, so the 23Gi VM always has room for Plex and the rest of
  the stack.
- VRAM: vLLM `--gpu-memory-utilization` **0.92** (~29.4GB), reserving ~2.5GB of
  the 32GB for Plex — sized for 1 concurrent 4K HDR transcode (~2GB) plus driver
  headroom; additional Plex streams fall back to CPU transcoding (18 vCPUs).

## Execution flow

1. Run preflight from tarkin; fix findings until clean.
2. Schedule the window (Plex, rollback Pi-hole, devastator Traefik, exporters
   go down for its duration).
3. Run the upgrade playbook from tarkin; gate at each phase (backup done →
   leapp done → boots → GPU bound).
4. Deploy the vLLM composed-app; smoke-test a completion from nemesis.
5. Enable Plex `/dev/dri`; verify transcode path.
6. Contention test (below). Done.

## Error handling and rollback

- Full rollback at any point: vzdump restore of VM 103 returns RHEL 9.6
  exactly as it was.
- Kernel-only issues: GRUB fallback between `kernel-ml` and the RHEL kernel.
- Leapp inhibitors are resolved in preflight, never during the window.
- Plex transcode cannot regress: it is CPU-only today.
- vLLM OOM/runaway: contained by the compose memory cap; Docker restarts it,
  Plex unaffected.
- Kuma's dynamic reconciler auto-monitors the new container once running; the
  existing node_exporter/Grafana stack covers host metrics. No new monitoring
  config.

## Testing

- Preflight playbook is itself the upgrade test gate (zero inhibitors).
- Post-upgrade: all pre-existing compose stacks healthy; `xe` bound;
  containerized `sycl-ls`/`clinfo` enumerates the B70.
- Inference: OpenAI-compatible completion from nemesis against the LAN
  endpoint returns sane output.
- Contention: sustained vLLM load concurrent with a Plex transcode (HW if
  available, else CPU); pass = no transcode stutter, no OOM, VM RAM within
  limits on Grafana.

## Out of scope

- LiteLLM gateway (Phase 0 of the parent spec) and wiring this backend into
  it.
- Web queueing front end and the MCP "decide what is best" router
  (sub-project 2; will revisit whether LiteLLM remains the routing layer).
- Multi-model serving, model benchmarking/selection beyond one validation
  model.
- incomm RAM upgrade (explicitly declined; caps instead).

## Open items for the implementation plan

- Confirm the supported leapp path for 9.6 (direct 9.6 → 10.0, or update to a
  newer 9.x first) against current Red Hat guidance.
- Pick the concrete validation model and quantization for the 32GB card.
- Confirm whether current Plex Media Server supports Battlemage VA-API
  transcode.
- Decide the vLLM endpoint port and whether to keep the `plex-compute/` name
  or rename to `vllm/`.
