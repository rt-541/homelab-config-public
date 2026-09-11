# plex-ops group - deploy runbook

Stands up the brain half of the plex-ops suite: the NanoClaw group on
devastator, its monitoring on tarkin, and the shadow-mode week. Manual,
step-by-step; nothing here is automated by this repo.

Artifacts in this directory:

| File | Installs as |
|---|---|
| `AGENTS.md` | the group's standing prompt (persona + capabilities + tiers) |
| `queue-triage.md`, `service-watchdog.md`, `library-audit.md`, `digest.md` | per-duty skills |
| `container.json.template` | `groups/plex-ops/container.json` (token filled in) |
| `schedules.md` | the five scheduled tasks (native `ncl tasks` or systemd fallback) |

## Prerequisites (nemesis side, from this repo)

- The runner is deployed and healthy: `plex-ops-runner.service` active,
  token present in `/etc/plex-ops/runner.env` (root:root, 0600), and port
  8377 restricted to the LAN per the runner README's Network restriction
  step (firewalld is not running on nemesis - use the LAN-address BIND or
  the nftables rule documented there, and verify it).
- Smoke test from devastator before touching NanoClaw:

  ```bash
  TOKEN=$(ssh nemesis.rt-541.io sudo -n grep '^PLEXOPS_TOKEN=' /etc/plex-ops/runner.env | cut -d= -f2-)
  curl -sS -H "Authorization: Bearer $TOKEN" http://nemesis.rt-541.io:8377/probe/disk
  ```

  Expect `"ok": true`. Do not paste the token into any chat, log, or note.

## Part 1 - devastator

### 1.1 NFS read-only media mount

The group container gets `/data` = nemesis `/docker/plex/media`, read-only.

On **nemesis** (one-time export; needs a stable client IP, so give
devastator a DHCP reservation on the HA Pi-hole pair first - managed from
kuat-drive-yards; devastator is currently 192.168.1.216):

```bash
sudo dnf install -y nfs-utils            # if not present
echo '/docker/plex/media 192.168.1.216(ro,root_squash,no_subtree_check)' | sudo tee -a /etc/exports
sudo systemctl enable --now nfs-server
sudo exportfs -ra && sudo exportfs -v
sudo firewall-cmd --add-service={nfs,rpc-bind,mountd} --permanent && sudo firewall-cmd --reload
```

On **devastator**:

```bash
sudo dnf install -y nfs-utils
sudo mkdir -p /mnt/nemesis-media
echo 'nemesis.rt-541.io:/docker/plex/media /mnt/nemesis-media nfs ro,nosuid,nodev,noexec,soft,timeo=100,retrans=2,_netdev 0 0' | sudo tee -a /etc/fstab
sudo systemctl daemon-reload && sudo mount /mnt/nemesis-media
ls /mnt/nemesis-media/downloads | head    # verify
touch /mnt/nemesis-media/x 2>&1 | grep -qi 'read-only\|denied' && echo "ro confirmed"
```

`soft` is deliberate: if nemesis is down, agent file inspection should fail
fast, not hang the container.

### 1.2 Chat channel and group

1. In your chat platform, create a channel for plex-ops notifications.
2. From `/docker/nanoclaw`, create the group (folder `plex-ops`) and wire
   the channel the same way the vault groups were wired:

   ```bash
   ./bin/ncl groups create --name plex-ops --folder plex-ops   # verify flags: ./bin/ncl groups create --help
   ```

   Then via the fleet's channel-binding flow, bind the chat channel to the
   group with the standard settings: `session_mode` shared, `engage_mode`
   pattern with `engage_pattern` `.` (answers every message), `sender_scope`
   all, `ignored_message_policy` drop, threads off,
   `unknown_sender_policy` request_approval. The operator is the owner.
3. Vault-group config posture:

   ```bash
   ./bin/ncl groups config update --id <gid> --cli-scope disabled   # verify exact flag name
   ./bin/ncl groups restart --id <gid>
   ```

   (NanoClaw ships breaking changes; on this checkout `cli_scope` lives in
   the DB via `ncl groups config update`, and there is no `--skills` flag.)

### 1.3 Install the artifacts

With `<gid>` from `./bin/ncl groups list`:

1. **Prompt**: install `AGENTS.md` as the group's standing instructions -
   `groups/plex-ops/instructions.prepend.md` on this checkout (main at
   `5c3082a1` composes the group `CLAUDE.md` from it via
   `src/project-doc-compose.ts`; releases up to 2.3.0 used
   `.claude-fragments/` - check which one the checkout does and place
   accordingly).
2. **Skills**: copy the four skill files into the fleet's vendored skill
   store under `groups/` (the Phase 6 `_skills` store), as
   `plexops-queue-triage`, `plexops-service-watchdog`,
   `plexops-library-audit`, `plexops-digest`, following the layout of the
   skills already there (the store is mounted at `~/.claude/skills` inside
   agent containers). Register them in the store MANIFEST scoped to the
   plex-ops group if the manifest supports scoping; the fleet's `skills`
   setting is currently "all", which also works but is an open hardening
   item.
3. **container.json**: copy `container.json.template` to
   `groups/plex-ops/container.json` and replace `__PLEXOPS_TOKEN__` with
   the value of `PLEXOPS_TOKEN` from nemesis `/etc/plex-ops/runner.env`.
   The template carries the standard vault-group backend pattern
   (`ANTHROPIC_BASE_URL` at the cch proxy `host.docker.internal:8788`,
   `NO_PROXY`, `blockedHosts: ["api.anthropic.com"]`,
   `CLAUDE_CODE_MAX_OUTPUT_TOKENS=4096`) plus `RUNNER_URL`/`RUNNER_TOKEN`
   and the `/data` mount. Verify the `additionalMounts` key shape against
   the checkout's `ContainerConfig` type and add `/mnt/nemesis-media` to
   the host mount allowlist (`/manage-mounts`).
4. **Model**: like the other vault groups, set the model in
   `data/v2-sessions/<gid>/.claude-shared/settings.json` (the current vault
   backend is `qwen3-14b` through proxy :8788; match whatever the vault
   groups run today). Leave `container_configs.model` alone.
5. Restart the group: `./bin/ncl groups restart --id <gid>`.
6. Commit the `groups/` repo changes on its branch model
   (`chore(spawn): add plex-ops group`).

### 1.4 Verify

```bash
# env made it into the container (match by label, names are key-derived):
docker exec $(docker ps -q --filter label=nanoclaw-group-folder=plex-ops) \
  env | grep -E 'RUNNER_URL|ANTHROPIC_BASE_URL|NO_PROXY|MAX_OUTPUT'      # token stays unprinted
# Anthropic is blocked:
docker inspect $(docker ps -q --filter label=nanoclaw-group-folder=plex-ops) \
  | grep 'api.anthropic.com'
# runner reachable and /data mounted, from inside the container:
docker exec $(docker ps -q --filter label=nanoclaw-group-folder=plex-ops) \
  sh -c 'curl -sS -H "Authorization: Bearer $RUNNER_TOKEN" "$RUNNER_URL/probe/disk" | head -c 200; ls /data | head'
```

Then in the chat channel: ask "run the service watchdog now" and expect a
SHADOW-mode report. Confirm `memory/mode.md` was created as `SHADOW` (or is
absent, which means the same).

### 1.5 Schedules

Create the five scheduled tasks per `schedules.md` (Mechanism A, `ncl
tasks`; Mechanism B only if the checkout lost native recurrence). Test each
once with `ncl tasks run <id>`.

### 1.6 Homepage

Standing rule: new service -> update the Homepage dashboard. Add the runner
(`nemesis.rt-541.io:8377`, plex-ops action runner) and the chat channel
entry to `home.rt-541.io`'s `services.yaml`.

## Part 2 - tarkin (Kuma monitoring)

From the control plane (tarkin, `/opt/kuat-drive-yards`), in Kuma at
`status.rt-541.io` (VIP .14 pair), add these HTTP(s) monitors (per the spec's
Monitoring section and the runner README):

1. **plex-ops runner (probe layer)**
   - URL: `http://nemesis.rt-541.io:8377/probe/service-health`
   - Interval 60s, retries 2, accepted status 200.
   - Custom header `Authorization: Bearer <token>` (the `PLEXOPS_TOKEN`
     value; Kuma stores headers server-side - never put the token in the
     monitor name or notes).
   - This exercises the full path (auth, sudo, docker, prowlarr ping), not
     just process liveness.
2. **Prowlarr ping**
   - URL: `http://nemesis.rt-541.io:9696/ping`
   - Interval 60s, retries 2, accepted status 200.
3. **plex-ops runner liveness (optional)**
   - URL: `http://nemesis.rt-541.io:8377/healthz` (unauthenticated by
     contract - see CONTRACT.md section 1; no header needed).
   - Interval 60s, retries 2, accepted status 200. Detects only "process
     up"; keep monitor 1 as the real health signal.

Attach the monitors to the existing Discord notification and to the status page
group that carries the other nemesis services. These two monitors are the
detection path for "runner down" and "prowlarr livelocked while the agent
or vLLM is also down" - the runner is intentionally dumb and does nothing
autonomously, so Kuma is the only watcher of the watcher.

## Part 3 - shadow week, then going live

1. **Week 1 (SHADOW, default)**: the auto tier is disabled; every duty
   posts `SHADOW:` lines for what it would have done and normal numbered
   approval lists for approval-tier items. The acceptance fixture is the
   live Sonarr backlog (96 stuck warnings as of 2026-09-10): the first
   triage runs should classify it and propose the cleanup.
   During the week, review in the chat channel:
   - Are the `malware-ext` / `not-upgrade` shadow calls all correct? Any
     item shadow-marked for removal that should have stayed is a
     classifier bug - fix it in `scripts/plex-ops/probes.py` (nemesis repo)
     before going live.
   - Are approval lists actionable (evidence readable, numbering stable,
     `approve 1,3-5` round-trips correctly)?
   - Do the scheduled runs fire on time (`ncl tasks list`, work-log lines
     in `groups/plex-ops/tasks/`)?
   Approving items during shadow week is fine and encouraged - approval is
   explicit consent and exercises the full execute path.
2. **Flip**: after reviewing a full week of shadow reports, say in
   the chat channel: "go live" (any explicit wording works; the agent quotes
   back what changes). The agent writes `LIVE` to its `memory/mode.md` and
   confirms. Verify the next 2h triage run posts `[auto]` receipts instead
   of `SHADOW:` lines, and spot-check one receipt against the runner audit
   log on nemesis (`/docker/plex/logs/plex-ops/audit.jsonl`).
3. **Rollback**: "go back to shadow" in-channel at any time; the agent
   writes `SHADOW` back. Token rotation or runner outage does not change
   the mode; it just makes every duty post its runner-unreachable alert.
