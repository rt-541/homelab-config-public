# homelab-config Monorepo Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate the nemesis and devastator Docker-Compose configs into one history-preserving GitHub repo `homelab-config`, laid out per-system, after first relativizing the few absolute bind mounts so nothing breaks on the move.

**Architecture:** Work in three reversible phases. Phase A hardens the 5 absolute in-repo bind mounts into relative paths while everything is still at `/docker/nemesis-configs` (and devastator at `/docker/devastator-configs`), verifying each touched app. Phase B restructures the repo on nemesis (`git mv` to `data-host/composed-apps`, import devastator's configs to `compute-node/composed-apps`, update scripts/systemd/docs). Phase C renames the GitHub repo, repoints the remote, moves the on-disk dir to `/docker/homelab-config`, and clones it on devastator. Running containers use `restart: unless-stopped`, so they keep running by container ID throughout; only the apps with in-repo mounts (traefik on both hosts, nemesis-bot) get a deliberate `down/up`.

**Tech Stack:** Docker Compose (use `sudo docker compose`), git, systemd, RHEL 9, SSH to devastator (`aschneider@192.168.1.216`).

**Conventions (from CLAUDE.md):**
- Always `sudo docker compose`, never `docker` directly; run from the app's directory.
- "Restart" means `down` then `up -d` (re-reads the compose file), never `docker compose restart`.

**Reference spec:** `docs/superpowers/specs/2026-06-01-homelab-config-monorepo-migration-design.md`

---

## Phase A: Harden bind mounts in place (reversible, no move)

### Task A0: Working-tree hygiene and branch

**Files:** none (git state only)

- [ ] **Step 1: Inspect the current working tree**

Run: `git -C /docker/nemesis-configs status`
Expected: shows pre-existing unrelated changes (e.g. `composed-apps/zomboid/server.ini`, `composed-apps/plex-stack/docker-compose.yml`, a deleted `composed-apps/nemesis-bot/state/zomboid-prod-stale.json`). Note them; this plan must not commit unrelated changes into its commits.

- [ ] **Step 2: Decide handling of unrelated changes with the user**

If the pre-existing changes are intentional and ready, ask the user whether to commit them separately first. If not ready, leave them unstaged; the targeted `git add <specific file>` commands in this plan will avoid sweeping them in. Do NOT use `git add -A` or `git add .` anywhere in this plan.

- [ ] **Step 3: Create the working branch**

Run: `git -C /docker/nemesis-configs checkout -b feature/homelab-monorepo`
Expected: `Switched to a new branch 'feature/homelab-monorepo'`

### Task A1: Relativize the nemesis Traefik mounts

**Files:**
- Modify: `composed-apps/traefik/docker-compose.yml:45-46`

- [ ] **Step 1: Edit the two mount lines**

Change:
```yaml
      - /docker/nemesis-configs/composed-apps/traefik/traefik.yml:/traefik.yml
      - /docker/nemesis-configs/composed-apps/traefik/config:/config
```
To:
```yaml
      - ./traefik.yml:/traefik.yml
      - ./config:/config
```

- [ ] **Step 2: Restart Traefik to pick up the relative mounts**

Run:
```bash
cd /docker/nemesis-configs/composed-apps/traefik && sudo docker compose down && sudo docker compose up -d
```
Expected: traefik stops then starts; no errors.

- [ ] **Step 3: Verify the live mount now points at the same file via the relative path**

Run: `sudo docker inspect traefik --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}'`
Expected: includes `/docker/nemesis-configs/composed-apps/traefik/traefik.yml -> /traefik.yml` and `.../config -> /config` (relative resolved to the same absolute source).

- [ ] **Step 4: Verify Traefik is routing (TLS path intact)**

Run: `curl -skI https://about.rt-541.io | head -1`
Expected: `HTTP/2 200` (or a 3xx redirect). A connection refused / TLS error means stop and roll back this task (`git checkout -- composed-apps/traefik/docker-compose.yml` then restart traefik).

### Task A2: Relativize the nemesis-bot cross-app mount

**Files:**
- Modify: `composed-apps/nemesis-bot/docker-compose.yml:12`

- [ ] **Step 1: Edit the mount line**

Change:
```yaml
      - /docker/nemesis-configs/composed-apps/minecraft-atm9-survival/allowed_users.json:/mc/allowed_users.json
```
To:
```yaml
      - ../minecraft-atm9-survival/allowed_users.json:/mc/allowed_users.json
```

- [ ] **Step 2: Restart nemesis-bot**

Run:
```bash
cd /docker/nemesis-configs/composed-apps/nemesis-bot && sudo docker compose down && sudo docker compose up -d
```
Expected: nemesis-bot recreated, no errors.

- [ ] **Step 3: Verify the allowlist mount resolved correctly**

Run: `sudo docker inspect nemesis-bot --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}'`
Expected: includes `/docker/nemesis-configs/composed-apps/minecraft-atm9-survival/allowed_users.json -> /mc/allowed_users.json`.

- [ ] **Step 4: Verify the bot started cleanly**

Run: `sudo docker logs nemesis-bot --tail 20`
Expected: normal startup logs (Discord connect), no file-not-found error for the allowlist.

### Task A3: Commit Phase A (nemesis side)

- [ ] **Step 1: Stage only the two changed compose files**

Run:
```bash
git -C /docker/nemesis-configs add composed-apps/traefik/docker-compose.yml composed-apps/nemesis-bot/docker-compose.yml
```

- [ ] **Step 2: Commit**

Run:
```bash
git -C /docker/nemesis-configs commit -m "refactor(configs): relativize in-repo bind mounts (traefik, nemesis-bot)

Make repo location-independent ahead of the homelab-config monorepo move.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```
Expected: one commit, two files changed.

### Task A4: Commit a baseline of devastator's configs, then relativize its Traefik mounts

**Files (on devastator, 192.168.1.216):**
- Commit: `/docker/devastator-configs/composed-apps/*`
- Modify: `/docker/devastator-configs/composed-apps/traefik/docker-compose.yml:45-46`

- [ ] **Step 1: Commit the current working configs as a rollback baseline**

Run:
```bash
ssh aschneider@192.168.1.216 'cd /docker/devastator-configs && git add -A composed-apps && git commit -m "chore: baseline devastator configs before monorepo migration"'
```
Expected: first commit on devastator-configs (it had zero commits). This is our rollback point.

- [ ] **Step 2: Relativize the Traefik mounts**

Edit `/docker/devastator-configs/composed-apps/traefik/docker-compose.yml` on devastator, changing:
```yaml
      - /docker/devastator-configs/composed-apps/traefik/traefik.yml:/traefik.yml
      - /docker/devastator-configs/composed-apps/traefik/config:/config
```
To:
```yaml
      - ./traefik.yml:/traefik.yml
      - ./config:/config
```
(Do this with a precise `sed` or by editing the file over SSH; verify with `git -C /docker/devastator-configs diff` showing exactly those two lines changed.)

- [ ] **Step 3: Restart Traefik on devastator**

Run:
```bash
ssh aschneider@192.168.1.216 'cd /docker/devastator-configs/composed-apps/traefik && sudo docker compose down && sudo docker compose up -d'
```
Expected: traefik recreated, no errors.

- [ ] **Step 4: Verify devastator Traefik mounts and health**

Run:
```bash
ssh aschneider@192.168.1.216 "sudo docker inspect traefik --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{\"\n\"}}{{end}}'"
```
Expected: includes `/docker/devastator-configs/composed-apps/traefik/traefik.yml -> /traefik.yml` and the config dir.
Then confirm Plex is still reachable through it (open Plex or `ssh aschneider@192.168.1.216 'sudo docker ps --filter name=traefik --format "{{.Status}}"'` shows Up).

- [ ] **Step 5: Commit the relativization on devastator**

Run:
```bash
ssh aschneider@192.168.1.216 'cd /docker/devastator-configs && git add composed-apps/traefik/docker-compose.yml && git commit -m "refactor: relativize traefik bind mounts before monorepo migration"'
```

---

## Phase B: Restructure the repo on nemesis

### Task B1: Move composed-apps under nemesis/

**Files:** all of `composed-apps/` -> `data-host/composed-apps/`

- [ ] **Step 1: git mv the tree**

Run:
```bash
cd /docker/nemesis-configs && mkdir -p nemesis && git mv composed-apps data-host/composed-apps
```
Expected: git stages renames for every tracked file under composed-apps.

- [ ] **Step 2: Verify the move and that no running container is affected yet**

Run: `git -C /docker/nemesis-configs status | head -20`
Expected: renames `composed-apps/... -> data-host/composed-apps/...`. Running containers are untouched (they still reference the old on-disk path; the on-disk path does not change until Phase C).

- [ ] **Step 3: Commit the restructure**

Run:
```bash
git -C /docker/nemesis-configs commit -m "refactor(repo): move composed-apps under nemesis/ for per-system monorepo"
```

### Task B2: Import devastator configs into compute-node/composed-apps

**Files:** create `compute-node/composed-apps/{plex,traefik,pihole}/...`

- [ ] **Step 1: Copy devastator's committed configs to nemesis**

Run:
```bash
mkdir -p /docker/nemesis-configs/devastator
rsync -av --exclude='.git' aschneider@192.168.1.216:/docker/devastator-configs/composed-apps /docker/nemesis-configs/devastator/
```
Expected: `compute-node/composed-apps/{plex,traefik,pihole}/` now exist on nemesis, with the relativized traefik mounts from Task A4.

- [ ] **Step 2: Sanity-check the imported traefik mounts are relative**

Run: `grep -nE 'traefik.yml|/config' /docker/nemesis-configs/compute-node/composed-apps/traefik/docker-compose.yml`
Expected: shows `./traefik.yml:/traefik.yml` and `./config:/config` (NOT absolute `/docker/devastator-configs/...`).

- [ ] **Step 3: Commit**

Run:
```bash
git -C /docker/nemesis-configs add compute-node/composed-apps
git -C /docker/nemesis-configs commit -m "feat(repo): import devastator configs into compute-node/composed-apps"
```

### Task B3: Update nemesis scripts to the new paths

**Files:**
- Modify: `scripts/compose-manager.sh:11`
- Modify: `scripts/fix-compose-env.sh:20`
- Modify: `scripts/backup_minecraft.sh:21,42`
- Modify: `scripts/clone-prod-to-dev.sh:5,10` (also fixes the pre-existing path bug)
- Modify: `scripts/zomboid-world-reset/restore_items_only.sh:17`

- [ ] **Step 1: compose-manager.sh and fix-compose-env.sh**

In both, change `COMPOSE_DIR="/docker/nemesis-configs/composed-apps"` to `COMPOSE_DIR="/docker/homelab-config/data-host/composed-apps"`.

- [ ] **Step 2: backup_minecraft.sh (two lines)**

Change both occurrences of `/docker/nemesis-configs/composed-apps/minecraft/docker-compose.yml` to `/docker/homelab-config/data-host/composed-apps/minecraft/docker-compose.yml`.

- [ ] **Step 3: clone-prod-to-dev.sh (path move AND bug fix)**

Change line 5 comment `/docker/nemesis-configs/scripts/clone-prod-to-dev.sh` to `/docker/homelab-config/scripts/clone-prod-to-dev.sh`.
Change line 10 `DEV_COMPOSE_DIR="/docker/nemesis-configs/composed-apps/zomboid-dev"` to the CORRECT path `DEV_COMPOSE_DIR="/docker/homelab-config/data-host/composed-apps/zomboid/zomboid-dev"` (the old value pointed at a non-existent `composed-apps/zomboid-dev`; the real location is nested under `zomboid/`).

- [ ] **Step 4: restore_items_only.sh**

Change `RCON_DIR="/docker/nemesis-configs/scripts/zomboid-b42-migration/rcon-output"` to `RCON_DIR="/docker/homelab-config/scripts/zomboid-b42-migration/rcon-output"`.

- [ ] **Step 5: Grep to confirm no stray repo-path references remain in scripts**

Run: `grep -rn '/docker/nemesis-configs' /docker/nemesis-configs/scripts`
Expected: no output (all updated).

- [ ] **Step 6: Commit**

Run:
```bash
git -C /docker/nemesis-configs add scripts
git -C /docker/nemesis-configs commit -m "chore(scripts): repoint to /docker/homelab-config; fix clone-prod-to-dev path bug"
```

### Task B4: Update repo systemd-unit-files copies and docs

**Files:**
- Modify: `systemd-unit-files/backup_mcatm10.service:7`
- Modify: `systemd-unit-files/docker-clean.service:9`
- Modify: `CLAUDE.md` (the `cd /docker/nemesis-configs/...` examples)
- Modify: docs/README path references found by the scan (`scripts/README.md`, `scripts/zomboid-world-reset/RUNBOOK.md`, `scripts/zomboid-b42-migration/README.md`, `ansible/README.md`)

- [ ] **Step 1: systemd-unit-files copies**

In `systemd-unit-files/backup_mcatm10.service` change `ExecStart=/docker/nemesis-configs/scripts/backup_minecraft.sh` to `ExecStart=/docker/homelab-config/scripts/backup_minecraft.sh`.
In `systemd-unit-files/docker-clean.service` change `ExecStart=/docker/nemesis-configs/scripts/docker-clean.sh` to `ExecStart=/docker/homelab-config/scripts/docker-clean.sh`.

- [ ] **Step 2: Update CLAUDE.md path examples**

Replace the `cd /docker/nemesis-configs/composed-apps/zomboid` examples with `cd /docker/homelab-config/data-host/composed-apps/zomboid`. Update the "Project Structure" line to describe the per-system layout (`<system>/composed-apps/<app>`).

- [ ] **Step 3: Update doc/README path references**

Replace `/docker/nemesis-configs` occurrences in `scripts/README.md`, `scripts/zomboid-world-reset/RUNBOOK.md`, `scripts/zomboid-b42-migration/README.md`, and `ansible/README.md` with the corresponding `/docker/homelab-config[/data-host/composed-apps]` path.

- [ ] **Step 4: Grep for remaining references (excluding the design/plan docs which describe the migration)**

Run: `grep -rln '/docker/nemesis-configs' /docker/nemesis-configs --include='*.md' --include='*.service' | grep -v docs/superpowers`
Expected: no output.

- [ ] **Step 5: Commit**

Run:
```bash
git -C /docker/nemesis-configs add systemd-unit-files CLAUDE.md scripts ansible
git -C /docker/nemesis-configs commit -m "docs: update paths to /docker/homelab-config and per-system layout"
```

### Task B5: Update .claude allowlists (cosmetic) and push the branch

**Files:**
- Modify: `.claude/settings.local.json`, `data-host/composed-apps/.claude/settings.local.json`, `data-host/composed-apps/zomboid/.claude/settings.local.json`

- [ ] **Step 1: Repoint allowlist entries**

In each of the three settings files, replace `/docker/nemesis-configs` with the matching new path. These only affect permission prompts, not runtime; if any entry is ambiguous, leave it (it will simply re-prompt once).

- [ ] **Step 2: Commit**

Run:
```bash
git -C /docker/nemesis-configs add .claude/settings.local.json 'data-host/composed-apps/.claude/settings.local.json' 'data-host/composed-apps/zomboid/.claude/settings.local.json'
git -C /docker/nemesis-configs commit -m "chore(claude): repoint permission allowlists to homelab-config paths"
```

- [ ] **Step 3: Push the branch**

Run: `git -C /docker/nemesis-configs push -u origin feature/homelab-monorepo`
Expected: branch pushed to `rt-541/nemesis-configs` (still the old remote name at this point).

- [ ] **Step 4: Confirm containers are still healthy (nothing moved on disk yet)**

Run: `sudo docker ps --format '{{.Names}}\t{{.Status}}' | grep -iE 'traefik|nemesis-bot|about-site'`
Expected: all Up. The on-disk path is still `/docker/nemesis-configs`; the move happens in Phase C.

---

## Phase C: Rename remote, move on disk, clone on devastator

> Phase C contains the outward and hard-to-reverse actions (GitHub rename, on-disk move). Get explicit user confirmation before starting it.

### Task C1: Merge to main

- [ ] **Step 1: Merge the branch**

Run:
```bash
git -C /docker/nemesis-configs checkout main && git -C /docker/nemesis-configs merge --no-ff feature/homelab-monorepo
```
Expected: fast/clean merge. Resolve conflicts with the pre-existing unrelated changes if any (they were on `main`).

- [ ] **Step 2: Push main**

Run: `git -C /docker/nemesis-configs push origin main`

### Task C2: Rename the GitHub repo and repoint the remote

- [ ] **Step 1: Rename on GitHub (user action or gh)**

Rename `rt-541/nemesis-configs` to `rt-541/homelab-config` (GitHub Settings, or `gh repo rename homelab-config -R rt-541/nemesis-configs`). GitHub keeps a redirect from the old name.

- [ ] **Step 2: Update the local remote URL**

Run:
```bash
git -C /docker/nemesis-configs remote set-url origin git@github.com:rt-541/homelab-config.git
git -C /docker/nemesis-configs remote -v
```
Expected: origin now points at `homelab-config`.

- [ ] **Step 3: Verify fetch works against the new name**

Run: `git -C /docker/nemesis-configs fetch origin`
Expected: success, no auth/404 error.

### Task C3: Move the on-disk directory and re-anchor the in-repo-mount apps

> Only traefik and nemesis-bot mount FROM inside the repo. All other apps mount external paths (`/docker/game`, `/docker/plex`, etc.) and are unaffected by moving the repo dir. A same-filesystem `mv` is a rename (inode preserved), but we re-up the two in-repo-mount apps explicitly to make their mounts canonical at the new path.

- [ ] **Step 1: Move the directory**

Run: `sudo mv /docker/nemesis-configs /docker/homelab-config`
Expected: directory moved; `ls /docker/homelab-config/data-host/composed-apps` lists the apps.

- [ ] **Step 2: Re-up Traefik from the new path**

Run:
```bash
cd /docker/homelab-config/data-host/composed-apps/traefik && sudo docker compose down && sudo docker compose up -d
```

- [ ] **Step 3: Re-up nemesis-bot from the new path**

Run:
```bash
cd /docker/homelab-config/data-host/composed-apps/nemesis-bot && sudo docker compose down && sudo docker compose up -d
```

- [ ] **Step 4: Verify mounts now resolve under /docker/homelab-config and routing works**

Run:
```bash
sudo docker inspect traefik --format '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}'
curl -skI https://about.rt-541.io | head -1
sudo docker inspect nemesis-bot --format '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}'
```
Expected: traefik sources now under `/docker/homelab-config/data-host/composed-apps/traefik/...`; HTTP 200/3xx; nemesis-bot allowlist source under the new path.

### Task C4: Update the LIVE systemd units

**Files (host):**
- Modify: `/etc/systemd/system/backup_mcatm10.service:7`
- Modify: `/etc/systemd/system/docker-clean.service:9`

- [ ] **Step 1: Update ExecStart paths**

Run:
```bash
sudo sed -i 's#/docker/nemesis-configs/scripts#/docker/homelab-config/scripts#' /etc/systemd/system/backup_mcatm10.service /etc/systemd/system/docker-clean.service
```

- [ ] **Step 2: Reload systemd and confirm**

Run:
```bash
sudo systemctl daemon-reload
grep ExecStart /etc/systemd/system/backup_mcatm10.service /etc/systemd/system/docker-clean.service
```
Expected: both ExecStart lines show `/docker/homelab-config/scripts/...`.

- [ ] **Step 3: Dry-run the oneshot units**

Run:
```bash
sudo systemctl start docker-clean.service && systemctl status docker-clean.service --no-pager | tail -5
```
Expected: runs and exits success (it just prunes). Do NOT start backup_mcatm10 mid-day unless a backup now is fine; instead just confirm `systemd-analyze verify` finds the ExecStart binary:
`systemd-analyze verify /etc/systemd/system/backup_mcatm10.service` (expect no "command not found").

### Task C5: Clone the monorepo on devastator and re-anchor its apps

- [ ] **Step 1: Clone homelab-config on devastator**

Run:
```bash
ssh aschneider@192.168.1.216 'git clone git@github.com:rt-541/homelab-config.git /docker/homelab-config'
```
Expected: clone succeeds (devastator has the SSH key for the repo; if not, use HTTPS or add a deploy key first).

- [ ] **Step 2: Stop devastator apps at the OLD location**

Run:
```bash
ssh aschneider@192.168.1.216 'for a in plex traefik pihole; do cd /docker/devastator-configs/composed-apps/$a && sudo docker compose down; done'
```
Expected: plex, traefik, pihole stopped. (Brief Plex downtime here; do it at a quiet time.)

- [ ] **Step 3: Start them from the NEW location**

Run:
```bash
ssh aschneider@192.168.1.216 'for a in plex traefik pihole; do cd /docker/homelab-config/compute-node/composed-apps/$a && sudo docker compose up -d; done'
```

- [ ] **Step 4: Verify live mounts and health from the new path**

Run:
```bash
ssh aschneider@192.168.1.216 "sudo docker inspect plex traefik pihole --format '{{.Name}}: {{range .Mounts}}{{.Source}} {{end}}'"
ssh aschneider@192.168.1.216 'sudo docker ps --format "{{.Names}}\t{{.Status}}" | grep -iE "plex|traefik|pihole"'
```
Expected: plex config from `/docker/plex/config`, traefik from `/docker/homelab-config/compute-node/composed-apps/traefik/...`, pihole from `/docker/pihole/...`; all Up. Confirm Plex plays a title and Pi-hole resolves DNS.

### Task C6: Decommission the old locations (after full validation)

- [ ] **Step 1: Confirm everything green (see Phase D), then remove old dirs**

Run:
```bash
sudo rm -rf /docker/nemesis-configs.bak 2>/dev/null; sudo mv /docker/nemesis-configs /docker/nemesis-configs.bak 2>/dev/null || true
ssh aschneider@192.168.1.216 'mv /docker/devastator-configs /docker/devastator-configs.bak'
```
Keep the `.bak` copies for a few days as rollback, then delete. (We rename rather than hard-delete first.)

---

## Phase D: Final validation checklist

- [ ] nemesis: `sudo docker ps` shows all expected containers Up; `curl -skI https://about.rt-541.io` returns 200/3xx.
- [ ] nemesis: `git -C /docker/homelab-config remote -v` shows `homelab-config`; `git status` clean on main.
- [ ] nemesis: `grep -rn '/docker/nemesis-configs' /docker/homelab-config --include='*.sh' --include='*.service' --include='*.yml'` returns nothing (design/plan docs excepted).
- [ ] nemesis: both systemd units have ExecStart under `/docker/homelab-config/scripts`; `systemd-analyze verify` clean.
- [ ] devastator: plex/traefik/pihole Up from `/docker/homelab-config/compute-node/composed-apps`; Plex plays; Pi-hole resolves.
- [ ] devastator: `/docker/devastator-configs` renamed to `.bak`.
- [ ] Both `.bak` directories scheduled for deletion after a soak period.

## Rollback summary

- Phase A/B are branch commits: `git checkout main` (pre-merge) or `git revert` (post-merge) and restart the touched apps.
- Phase C on-disk move: `sudo mv /docker/homelab-config /docker/nemesis-configs` and re-up traefik + nemesis-bot from the old path; `git remote set-url` back (GitHub redirect makes the old name keep working regardless).
- devastator: re-up the three apps from `/docker/devastator-configs/composed-apps/*` (kept as `.bak`).
- Because every running container is `restart: unless-stopped`, nothing stops except the deliberate `down/up`s; a failed step is recovered by re-upping from the prior location.
