# homelab-config Monorepo Migration (Design)

Date: 2026-06-01
Status: Approved for spec review
Scope: consolidate nemesis + devastator Docker-Compose configs into one repo

## Goal

Consolidate the two homelab config sources into a single, history-preserving
monorepo named `homelab-config`, laid out per-system, and harden the few absolute
bind-mount paths into relative ones so the repo is location-independent from now on.
This gives Phase 1 of the LLM gateway (the devastator B70 vLLM stack) a versioned
home and brings devastator's currently-unversioned configs under git.

## Current state (verified 2026-06-01 by parallel scans)

- **nemesis**: repo at `/docker/nemesis-configs`, remote
  `git@github.com:rt-541/nemesis-configs.git`, branch `main`. ~28 apps under
  `composed-apps/<app>/`. Plus `scripts/`, `systemd-unit-files/`, `ansible/`, docs.
- **devastator**: configs at `/docker/devastator-configs`, a git repo with **zero
  commits and no remote** (files staged, `composed-apps/pihole/` untracked). Three
  apps: `plex`, `traefik`, `pihole`. RHEL 9.6, kernel 5.14.0-570. The B70 has no
  compute driver bound yet (only the bochs virtual display in `dmesg`).
- No CI, no git hooks, no `.gitmodules`, no auto-pull, no boot-time `compose up` on
  either host. All containers run `restart: unless-stopped`, so the Docker daemon
  restarts them by container ID and only re-reads a compose file on a manual
  `down/up`. The migration therefore does not threaten uptime; risk is confined to
  the deliberate re-up of touched apps.

## Target structure

```
homelab-config/                     (renamed from nemesis-configs; on disk /docker/homelab-config)
  nemesis/
    composed-apps/                  git mv of today's composed-apps/ (28 apps)
      ...                           incl. llm-gateway/ (added by the gateway spec)
  devastator/
    composed-apps/
      plex/  traefik/  pihole/      committed from the unversioned devastator-configs
      plex-compute/                 B70 vLLM stack (added in gateway Phase 1)
  scripts/                          nemesis ops scripts (paths updated)
  systemd-unit-files/               updated ExecStart paths
  ansible/                          updated paths
  docs/superpowers/specs/           design docs
```

No name collision: `nemesis/composed-apps/traefik` and
`devastator/composed-apps/traefik` are distinct paths.

## Dependency surface to fix (from the scans)

### Absolute bind mounts that hardcode the repo path (convert to RELATIVE)

| Host | File:line | Current | Becomes |
|------|-----------|---------|---------|
| nemesis | `traefik/docker-compose.yml:45` | `/docker/nemesis-configs/composed-apps/traefik/traefik.yml` | `./traefik.yml` |
| nemesis | `traefik/docker-compose.yml:46` | `/docker/nemesis-configs/composed-apps/traefik/config` | `./config` |
| nemesis | `nemesis-bot/docker-compose.yml:12` | `/docker/nemesis-configs/composed-apps/minecraft-atm9-survival/allowed_users.json` | `../minecraft-atm9-survival/allowed_users.json` |
| devastator | `traefik/docker-compose.yml:45` | `/docker/devastator-configs/composed-apps/traefik/traefik.yml` | `./traefik.yml` |
| devastator | `traefik/docker-compose.yml:46` | `/docker/devastator-configs/composed-apps/traefik/config` | `./config` |

Relative paths make these immune to any future move.

### Host systemd units on nemesis (edit ExecStart, then `daemon-reload`)

`scripts/`, `systemd-unit-files/`, `ansible/`, and `docs/` stay at the repo root
(they are not per-system app configs), so script paths keep the `/scripts/` prefix
without a `nemesis/` level:

- `/etc/systemd/system/backup_mcatm10.service:7` ->
  `/docker/homelab-config/scripts/backup_minecraft.sh`
- `/etc/systemd/system/docker-clean.service:9` ->
  `/docker/homelab-config/scripts/docker-clean.sh`

### Scripts on nemesis (update hardcoded `/docker/nemesis-configs`)

- `scripts/compose-manager.sh:11` (`COMPOSE_DIR`) -> `/docker/homelab-config/nemesis/composed-apps`
- `scripts/fix-compose-env.sh:20` (`COMPOSE_DIR`) -> same
- `scripts/backup_minecraft.sh:21,42` (compose `-f` path) -> `/docker/homelab-config/nemesis/composed-apps/minecraft/docker-compose.yml`
- `scripts/clone-prod-to-dev.sh:5,10` -> new path AND fix the pre-existing bug
  (`composed-apps/zomboid-dev` is wrong; real path is `composed-apps/zomboid/zomboid-dev`)
- `scripts/zomboid-world-reset/restore_items_only.sh:17` (`RCON_DIR`) -> new path

### Cosmetic (no runtime breakage, update for cleanliness)

- Docs/RUNBOOKs: `CLAUDE.md`, `scripts/README.md`, `scripts/zomboid-world-reset/RUNBOOK.md`,
  `scripts/zomboid-b42-migration/README.md`, `ansible/README.md`.
- `.claude/settings.local.json` allowlists (~40 entries) and the two nested
  `.claude/settings.local.json` files; stale entries only cause permission
  re-prompts.

### Confirmed safe (no action)

- zomboid-dev `../zomboid` build context and `../Flight_Group_..._SandboxVars.lua`:
  the inserted `<system>/` level is above `composed-apps/`, so depth inside is
  unchanged and these relative mounts still resolve.
- External `proxy` network (path-independent).
- All data outside the repo: `/docker/game`, `/docker/plex`, `/docker/pihole`,
  `/docker/traefik/acme.json`, NFS volume, `/dev/dri`, `/var/run/docker.sock`.

## Migration sequence (each step reversible before the next)

1. **Harden in place (branch `feature/relativize-mounts`).** Convert the 5 absolute
   mounts to relative. Fix `clone-prod-to-dev.sh`. Commit. Re-up only `traefik` and
   `nemesis-bot` on nemesis and `traefik` on devastator; confirm healthy. This is
   safe and reversible on its own and de-risks everything after it.
2. **Restructure (branch `feature/homelab-monorepo`).** `git mv composed-apps
   nemesis/composed-apps`. Commit devastator's working configs into
   `devastator/composed-apps/`. Update the 2 systemd units (+ `daemon-reload`), the
   ~6 scripts, and the docs/`.claude` files. Keep `scripts/`, `systemd-unit-files/`,
   `ansible/`, `docs/` at repo root.
3. **Rename + repoint.** Rename the GitHub repo `nemesis-configs` ->
   `homelab-config` (GitHub auto-redirects the old URL). `git remote set-url` on
   nemesis. Move the on-disk dir `/docker/nemesis-configs` -> `/docker/homelab-config`
   (or re-clone). Clone the repo on devastator at `/docker/homelab-config`.
4. **Validate.** From the new paths, re-up the touched apps and confirm: Traefik
   serves TLS and routes; nemesis-bot mounts `allowed_users.json`; Plex, traefik,
   pihole on devastator come up from the new clone with correct live mounts
   (`docker inspect`). Run the systemd units once (`systemctl start ...`) to confirm
   ExecStart resolves.

## Rollback

- Steps 1-2 are branch commits; revert or `git restore` before merge.
- Keep `/docker/nemesis-configs` on disk until step 4 validates, then remove it.
- GitHub redirects the old repo name, so an un-updated remote keeps working as a
  safety net; update it deliberately.
- Because containers run by ID under `restart: unless-stopped`, nothing stops until
  a deliberate `down/up`; a failed re-up is fixed by pointing back at the old dir.

## Testing / verification

- After step 1: `docker inspect traefik nemesis-bot` (nemesis) and `traefik`
  (devastator) show the expected mount sources; services healthy; a test request
  through Traefik succeeds (e.g. `about.rt-541.io`).
- After step 4: same inspections against the new `/docker/homelab-config` paths;
  Plex playable; Pi-hole resolving; both systemd units start cleanly.

## Risks

- **Traefik re-up** is the highest-value service to verify (TLS + all routes). Do it
  first in step 1 while still in the old location, so a mount mistake surfaces before
  any move.
- **Plex on devastator**: only re-up after confirming the new clone's relative mounts
  match the live mounts; the media NFS and `/dev/dri` are external and unaffected.
- **GitHub rename**: low risk due to auto-redirect, but update the nemesis remote and
  add the devastator clone in the same sitting to avoid confusion.

## Out of scope

- The B70 driver/kernel/vLLM standup on devastator (gateway Phase 1 sub-project).
- Any change to game-server data or the `/docker/game` tree.
