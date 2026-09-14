# plex-ops group - deploy runbook

Stands up the brain half of the plex-ops suite: the NanoClaw group on
devastator, its monitoring on tarkin, and the shadow-mode week. Every step
is scripted and idempotent; the manual detail under each part explains what
the script does and how to do it by hand if a NanoClaw flag moves again.

Artifacts in this directory:

| File | Installs as |
|---|---|
| `deploy-devastator.sh` | the whole Part 1, as subcommands (`nfs`, `channel`, `group`, `skills`, `tasks`, `commit`, `verify`, `all`) |
| `AGENTS.md` | the group's standing prompt (`groups/plex-ops/instructions.prepend.md`) |
| `queue-triage.md`, `service-watchdog.md`, `library-audit.md`, `digest.md` | per-duty skills, installed as `plexops-<duty>` in the fleet skill store |
| `gates/triage-gate.sh`, `gates/watchdog-gate.sh` | host-side pre-task gates for the two frequent schedules |
| `container.json.template` | reference shape of the env/mount block the script merges into `groups/plex-ops/container.json` |
| `schedules.md` | the five scheduled tasks and the fallback timer mechanism |

Verified against the devastator checkout on 2026-09-13 (`/docker/nanoclaw`,
clanker branch at `44d7a67e`): `ncl groups create --folder --name`,
`ncl messaging-groups create`, `ncl wirings create` (engage flags),
`ncl groups config update --cli-scope --assistant-name`,
`ncl groups config add-mount --id --host --container --ro`,
`ncl tasks create --group --name --prompt --recurrence --script`. The
scheduler refuses recurrences above 4 fires/day unless the task carries a
`--script` gate, which is why triage and watchdog are gated.

## Part 0 - nemesis (from this repo)

```bash
cd /docker/homelab-config/scripts/plex-ops        # or the worktree while unmerged
sudo bash deploy-nemesis.sh all --worktree /docker/homelab-config/.claude/worktrees/plex-ops
sudo bash deploy-nemesis.sh recyclarr --apply     # after reading the preview
bash deploy-nemesis.sh push-token devastator.rt-541.io
```

- `runner`: token env file (root:root 0600, fresh `openssl rand -hex 32`),
  `BIND=192.168.1.214` (LAN-only, firewalld is not running on nemesis),
  systemd unit, log dir, start, smoke tests. `--worktree` adds a drop-in that
  runs the service from the worktree; re-run `runner` without it after the
  merge to drop the override.
- `nfs`: verifies the existing export. nemesis already serves the media
  tree over NFSv4 from plex-stack's `nfs` service (container `plex-nfs`,
  pseudo-root `/nfs`, media at `:/media`, exported `rw` to the whole LAN);
  a kernel `nfs-server` cannot bind 2049 next to it and is disabled if
  found. Read-only is enforced client-side (fstab `ro` plus the agent
  container's read-only mount). Open hardening item: a server-side
  `ro` export entry for `192.168.1.216` (`NFS_EXPORT_1`) in plex-stack's
  compose.
- `recyclarr`: state dir, `.env` from the arr config.xml keys, preview. Only
  `--apply` syncs the live arrs and starts the cron container.
- `push-token`: copies the runner token to `~/.config/plex-ops/runner.env`
  on devastator (mode 600, the NanoClaw account). The gate scripts and the
  deploy script read it there. It is the only copy on devastator besides the
  group's `container.json`.

Smoke test from devastator before touching NanoClaw:

```bash
. ~/.config/plex-ops/runner.env
curl -sS -H "Authorization: Bearer $RUNNER_TOKEN" "$RUNNER_URL/probe/disk"
```

Expect `"ok": true`. Do not paste the token into any chat, log, or note.

## Part 0.5 - the transcode worker (compression waves)

The `reclaim_*` tools drive `compute-node/composed-apps/media-transcoder/`
(B70 VA-API worker; see its README). It runs wherever the GPU is; on
devastator:

```bash
sudo mkdir -p /docker/transcode-scratch            # output only lands here (15-25G per film)
cd /docker/homelab-config/compute-node/composed-apps/media-transcoder
cp .env.example .env                                # PLEX_TOKEN (session guard), WEBHOOK_URL (optional)
sudo docker compose up -d && sudo docker compose logs --tail 20   # expect "using VA-API device /dev/dri/renderD128"
```

`transcode-policy.conf` carries the windows, the pilot gate (3 encodes,
then `reclaim_pilot_ack`) and `MIN_SCRATCH_GB` (40; devastator's root disk
has ~57 GB free). The worker idles until the queue has rows; the agent
fills the queue with `reclaim_schedule` on Arthur's "run it". Moving the
worker to nemesis (if a GPU goes in) is the same compose with local bind
mounts instead of the NFS volume.

## Part 1 - devastator

```bash
# after the branch is merged: git -C /docker/homelab-config pull
bash /docker/homelab-config/docs/plex-ops/group/deploy-devastator.sh all
```

What each subcommand does, with the manual equivalent:

### 1.1 `nfs` - read-only media mount

`/mnt/nemesis-media` = nemesis `/docker/plex/media`, mounted as
`nemesis.rt-541.io:/media` (NFSv4, plex-nfs pseudo-root) via fstab
(`ro,nosuid,nodev,noexec,soft,timeo=100,retrans=2,_netdev`). `soft` is
deliberate: if nemesis is down, agent file inspection fails fast instead of
hanging the container. The script refuses to continue if the mount turns out
writable.

### 1.2 `channel` - Discord channel

Confirms the users' channel `CHANNEL_ID` exists in the fleet guild (via the
bot token in `/docker/nanoclaw/.env`; name and guild feed the wiring) and
warns when the bot cannot read it. A private channel needs the bot (or its
role) added under channel Permissions with View Channel, Send Messages and
Read Message History; until then the wiring exists but no message reaches
the agent. Nothing is created.

### 1.3 `group` - agent group, wiring, config

1. `ncl groups create --folder plex-ops --name "#plex-ops"` (idempotent).
2. Messaging group for `discord:<guild>:<channel-id>`,
   `unknown_sender_policy request_approval`.
3. Wiring with the vault-group settings: `engage_mode pattern`,
   `engage_pattern .`, `session_mode shared`, `sender_scope all`,
   `ignored_message_policy drop`, threads off.
4. One channel only: the users' existing `#plex-ops` (`CHANNEL_ID`, default
   `<channel-id>`; the bot must already see it) gets a messaging
   group with `unknown_sender_policy public` (membership of the channel is
   the authorization) and a `mention-sticky` wiring with threads ON and
   `session_mode per-thread`: an @mention opens a Discord thread, the
   agent's replies, typing indicator and follow-ups land in it, and every
   later message in that thread engages the agent without a mention; plain
   channel chatter never wakes it. Arthur's `approve` / `deny` / `go live`
   / `go back to shadow` therefore @mention the bot (or go in a thread).
   With threads off the adapter still opened the thread but answered in the
   channel. Help desk requests, maintenance reports, approval lists and
   receipts all live in that channel.
5. `config update --cli-scope group --assistant-name plex-ops`. `group`
   lets the agent create and cancel its own group's tasks, which the
   20-minute help-desk follow-up needs; `disabled` (the vault-group
   posture) silently broke it.
6. `config add-mount --host /mnt/nemesis-media --container data --ro`
   (container paths must be relative; it lands at `/workspace/extra/data`),
   plus `/mnt/nemesis-media` (read-only) in the host mount allowlist
   `~/.config/nanoclaw/mount-allowlist.json`; a mount outside an allowed
   root is silently not attached.
7. `groups/plex-ops/container.json` is materialized from the database at
   every spawn (hand edits are overwritten), so `RUNNER_URL`/`RUNNER_TOKEN`
   go into the `container_configs.env` JSON column (no `ncl` verb exists;
   the script writes it with sqlite). Model: `claude-sonnet-5` through the
   OneCLI gateway, like `#infra` and the kids groups; the local `qwen3-14b`
   backend could not follow the triage skill over 110 queue items
   (2026-09-13, output was junk, no actions ran). `MODEL=qwen3-14b` on the
   script restores the vault-group pattern (proxy env at
   `host.docker.internal:8788`, `CLAUDE_CODE_MAX_OUTPUT_TOKENS=4096`,
   `blocked_hosts ["api.anthropic.com"]`). The `plex-ops`
   MCP server is registered with `config add-mcp-server` at
   `https://plex-ops.rt-541.io/mcp` (Traefik route in
   `data-host/composed-apps/traefik/config/plex-ops.yml`, live after the
   merge); the CLI and loader refuse plain http off-host. Until the route
   is live the tools are absent and the agent falls back to curl against
   `RUNNER_URL`. The token therefore lives in the NanoClaw database and the
   materialized file inside the local-only `groups/` repo.
7. Model `qwen3-14b` in `data/v2-sessions/<gid>/.claude-shared/settings.json`
   (copied from an existing vault group's settings so the hooks match).
8. `AGENTS.md` -> `groups/plex-ops/instructions.prepend.md`. This group is
   bespoke and not produced by `_persona/build-personas.ts`; it is the one
   hand-maintained prompt in `groups/`.

### 1.4 `skills`

Each duty file becomes `groups/_skills/plexops-<duty>/SKILL.md` (frontmatter
prepended), `MANIFEST` gains `plexops-<duty> = plex-ops`, and
`sync-skills.sh` installs them into the group's skill store. Then
`ncl groups restart`.

### 1.5 `tasks`

The five schedules from `schedules.md`. Triage and watchdog carry their gate
scripts, which NanoClaw runs inside the group container before the model
wakes (bash + curl + node; creds from the container env); the deploy script
self-tests both gates on the host first via the token-file fallback (last
stdout line must be the `wakeAgent` JSON). A gate that finds nothing costs
zero model tokens; on a runner outage the watchdog gate wakes the agent once
per six hours, not every 30 minutes.

### 1.6 `verify`

Fires the watchdog task once (`ncl tasks run`), then from inside the group
container checks env (token not printed), that `api.anthropic.com` is
blocked, that the runner answers, and that `/workspace/extra/data` lists the media tree.
Expect a `SHADOW`-mode report in `#plex-ops`. `memory/mode.md` absent means
`SHADOW`. Then @mention the bot with "is S01E01 of Dune there?" and expect a
one-line `lookup` answer. Help desk actions are not shadowed, so only ask
for a fix on an item you actually want fixed.

### 1.7 Homepage

Done in this repo: the `plex-ops runner` tile under Infra in
`data-host/composed-apps/homepage/config/services.yaml` (live after the merge
and the next homepage `down`/`up -d`).

## Part 2 - tarkin (Kuma monitoring)

From the control plane (tarkin, root or lo204), with the token read from
nemesis:

```bash
scp nemesis.rt-541.io:/docker/homelab-config/scripts/plex-ops/kuma-monitors.py /tmp/
PLEXOPS_TOKEN=$(ssh nemesis.rt-541.io sudo -n grep -oP '^PLEXOPS_TOKEN=\K.*' /etc/plex-ops/runner.env) \
  python3 /tmp/kuma-monitors.py http://192.168.1.14:3001 <kuma-admin> <kuma-password>
```

Adds three HTTP monitors (60s, 2 retries) and attaches the existing
`discord` notification:

1. `plex-ops-runner` - `GET /probe/service-health` with the bearer header
   stored server-side in Kuma. Exercises auth, sudo, docker, prowlarr ping.
2. `prowlarr-ping` - `GET nemesis:9696/ping`.
3. `plex-ops-healthz` - `GET /healthz`, process liveness only.

These are the detection path for "runner down" and "prowlarr livelocked
while the agent or vLLM is also down": the runner is intentionally dumb and
does nothing autonomously, so Kuma is the only watcher of the watcher. Fold
the entries into `kuat-drive-yards/ansible/monitors/monitors.py` when that
file next changes.

## Part 3 - shadow week, then going live

1. **Week 1 (SHADOW, default)**: the auto tier is disabled; every duty posts
   `SHADOW:` lines for what it would have done and normal numbered approval
   lists for approval-tier items. The acceptance fixture is the live Sonarr
   backlog (96 stuck warnings as of 2026-09-10): the first triage runs
   should classify it and propose the cleanup. During the week, review in
   `#plex-ops`:
   - Are the `malware-ext` / `not-upgrade` shadow calls all correct? Any
     item shadow-marked for removal that should have stayed is a classifier
     bug - fix it in `scripts/plex-ops/plexops_lib.py` before going live.
   - Are approval lists actionable (evidence readable, numbering stable,
     `approve 1,3-5` round-trips correctly)?
   - Do the scheduled runs fire (`ncl tasks list`; gated runs that found
     nothing show as runs with zero token cost)?
   Approving items during shadow week is fine and encouraged - approval is
   explicit consent and exercises the full execute path.
2. **Flip**: after reviewing a full week of shadow reports, say in
   `#plex-ops`: "go live". The agent writes `LIVE` to its `memory/mode.md`
   and confirms. Verify the next triage run posts `[auto]` receipts instead
   of `SHADOW:` lines, and spot-check one receipt against the runner audit
   log on nemesis (`/docker/plex/logs/plex-ops/audit.jsonl`).
3. **Rollback**: "go back to shadow" in-channel at any time. Token rotation
   or runner outage does not change the mode; it just makes every duty post
   its runner-unreachable alert.

## Post-merge cutover (nemesis)

While `worktree-plex-ops` was unmerged the runner and recyclarr ran from the
worktree. After the merge:

```bash
cd /docker/homelab-config && git pull
sudo bash scripts/plex-ops/deploy-nemesis.sh runner            # drops the worktree drop-in
cd data-host/composed-apps/recyclarr && sudo docker compose up -d # re-points the compose mount
cd ../homepage && sudo docker compose down && sudo docker compose up -d
```

Then the worktree can go.
