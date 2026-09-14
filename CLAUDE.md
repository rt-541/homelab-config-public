# Nemesis Configs - Project Guide

## Communication Style
- Never use emojis in responses to the user



## Project Structure
This repo is a per-system monorepo (one tree per host role; `data-host` is the
storage/services box "nemesis", `compute-node` is the GPU box "devastator"):
- `data-host/composed-apps/<app-name>/docker-compose.yml`: nemesis apps, one directory per app
- `compute-node/composed-apps/<app-name>/docker-compose.yml`: devastator apps (Plex, Pi-hole, Traefik, and the B70 vLLM stack)
- `scripts/`, `systemd-unit-files/`, `ansible/`, `docs/`: shared, host-agnostic, at the repo root
- Game server data lives under `/docker/game/<game-name>/`
- Media/Plex stack lives under `/docker/plex/`
- On-disk repo path: `/docker/homelab-config` on both hosts

## Network / DNS / DHCP Topology (authoritative — do NOT re-derive)

Do not infer DNS/DHCP authority from on-host Pi-hole state. A Docker `pihole`
container's `pihole.toml`, its `dhcp.leases` file, and the local ARP table are
**misleading** here: the nemesis and devastator Pi-holes are non-DHCP
secondaries with `dhcp.active = false`, so their lease/reservation data is inert
and stale. Use the facts below as the source of truth.

- **DNS + DHCP authority: the HA Pi-hole pair at VIP `192.168.1.2`.** Both
  services follow the VIP — the keepalived MASTER serves them, and they fail
  over together. The **router's own DHCP is OFF**; the router does not hand out
  leases or hold reservations.
  - `dns-incomm` `.3` (node incomm, keepalived MASTER) and `dns-sienar` `.4`
    (node sienar, BACKUP). Privileged Debian 12 LXCs, native **Pi-hole v6**.
- **DHCP reservations** (MAC -> fixed IP) and **DNS records** live on the HA
  pair, in Pi-hole **v6 `pihole.toml dns.hosts`** / v6 DHCP config. Edit on the
  primary `.3`; `nebula-sync` replicates to `.4`. The pair is managed from the
  `kuat-drive-yards` repo on the control plane (**tarkin**) — see its CLAUDE.md.
- **DEAD MECHANISM — do not use:** this repo's `ansible/pihole-dns.yml` +
  `ansible/vars/dns-entries.yml` + `custom.list` is the **v5** path and is a
  **no-op on the live v6 Pi-holes**. Editing it publishes nothing. The old
  nemesis Pi-hole `.214` (which it targeted) is decommissioned/unreachable.
- **Auto DNS from DHCP:** Pi-hole v6 registers leased hostnames under
  `rt-541.io`, so `<host>.rt-541.io` resolves to that host's **current lease IP**
  automatically — a name tracks the lease, not a fixed IP. Pin the IP with a
  reservation to make the name stable.
- **PREFER DNS NAMES OVER HARDCODED IPs when reaching a host (ssh/scp/curl):**
  use `<host>.rt-541.io`, not a baked-in `192.168.1.x`. DNS follows the current
  lease, so it keeps working when a reservation drifts or hasn't applied; a
  hardcoded "pinned" IP goes stale and fails (observed 2026-06-15: roci's pinned
  `192.168.1.247` gave "No route to host" while `rocinante.rt-541.io` connected).
  The ONE exception is the `lan-only` source-IP allowlist below, which genuinely
  needs a fixed IP.
- `*.rt-541.io` is a **wildcard** -> Traefik host `192.168.1.214` on the HA
  Pi-hole, so new web services need NO per-service DNS record. Service vhost
  entries in `dns-entries.yml` point at `server_ip` (`.214`); host records (a
  machine itself) use the machine's own IP.
- **Traefik access control matches source IP only.** The `lan-only@docker`
  middleware uses `ipallowlist.sourcerange` — it never resolves names, so a
  DNS name/CNAME does NOT make an allowlist "follow a host." Allowlisted hosts
  need a **stable IP** (DHCP reservation), e.g. azure-dragon `.164`, rocinante
  `.247`.

## External Exposure / Public Ingress (authoritative — do NOT re-derive)

The fleet already has a working public ingress; do not ask how to expose a
service externally — follow this.

- **Single edge: Traefik on nemesis `192.168.1.214`.** It terminates TLS for
  all `*.rt-541.io` via a **Cloudflare DNS-challenge wildcard cert**
  (`certResolver: default`). Public DNS for the `rt-541.io` zone is on
  Cloudflare; internally the wildcard `*.rt-541.io` resolves to `.214` (HA
  Pi-hole). So a new web service needs **no per-service DNS record**, public or
  private.
- **The internet-facing entrypoint is `secure:443`** (`asDefault: true`, HTTP/3
  on). Port 443 is forwarded from the router to nemesis `.214`. The `web:80`
  entrypoint just 301-redirects to `secure`.
- **A service is LAN-only iff its router carries the `lan-only@docker`
  middleware.** That middleware is the ONLY thing keeping a `secure:443` service
  internal. **To expose a service to the internet, drop `lan-only@docker` from
  that router** (Docker-label apps: remove the middleware label; file-provider
  apps under `traefik/config/*.yml`: remove the `middlewares` line). Everything
  is exposed-by-`secure` already; the allowlist is the gate.
- **Defense-in-depth for a public router:** the edge service is the bearer/login
  on the app itself; add Traefik `ratelimit` + `inflightreq` middleware on the
  public router. Cloudflare orange-cloud (WAF / edge rate-limit / hides origin)
  is available on the zone.
- **Dormant second entrypoint pair `public-web:10080` / `public-secure:10443`**
  exists for stronger *entrypoint-level* isolation (a separate port-forward that
  carries only public routers). Currently unused — all traffic rides
  `secure:443`. Activate it only if you want public traffic on its own
  entrypoint rather than sharing `secure` with LAN services.
- **Cross-host apps** (containers not on nemesis, e.g. `<host>`) are
  wired in via Traefik's **file provider** (`traefik/config/<host>-<app>.yml`),
  not Docker labels — same `secure` entrypoint, same `lan-only`-to-gate rule.

## When Creating a New Containerized App

When the user asks to create a new Docker Compose app, **always ask** which sidecars they want using AskUserQuestion with multiSelect. Present the following options:

### Sidecar Options

#### 1. Scheduled Backup (offen/docker-volume-backup)
Daily compressed backup of persistent data with automatic rotation.
```yaml
  <app>-backup:
    image: offen/docker-volume-backup:v2
    container_name: <app>-backup
    restart: unless-stopped
    environment:
      BACKUP_CRON_EXPRESSION: "0 4 * * *"
      BACKUP_RETENTION_DAYS: "21"
      BACKUP_FILENAME: "<app>-%Y-%m-%dT%H-%M-%S.tar.gz"
    volumes:
      - <data-volume-path>:/backup/<data-dir>:ro
      - <backup-storage-path>:/archive
```
- Default schedule: daily at 4 AM
- Default retention: 21 days
- Mount the app's data volume as read-only under `/backup/`
- Store archives in a dedicated backup directory

#### 2. Discord Notifications
Lightweight Alpine container that monitors the main app and sends Discord webhook alerts on start/stop.
```yaml
  <app>-discord:
    image: alpine:latest
    container_name: <app>-discord
    restart: unless-stopped
    depends_on:
      - <main-service>
    environment:
      - WEBHOOK_URL=<ask user for webhook URL>
    volumes:
      - ./notify.sh:/notify.sh:ro
    entrypoint: /bin/sh
    command: ["/notify.sh"]
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: "128M"
        reservations:
          cpus: '0.25'
          memory: "64M"
```
- Ask the user for their Discord webhook URL
- Create a `notify.sh` script tailored to the app (use the ATM9 survival one as a template: `composed-apps/minecraft-atm9-survival/notify.sh`)
- Monitor via TCP port check against the main service

#### 3. Healthcheck Monitor (autoheal)
Automatically restarts unhealthy containers.
```yaml
  <app>-autoheal:
    image: willfarrell/autoheal:latest
    container_name: <app>-autoheal
    restart: unless-stopped
    environment:
      AUTOHEAL_CONTAINER_LABEL: all
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
```
- Requires the main service to have a `healthcheck` defined in its compose config
- Restarts containers that report unhealthy status

#### 4. Log Aggregation (Dozzle)
Web-based real-time log viewer for all containers in the compose stack.
```yaml
  <app>-logs:
    image: amir20/dozzle:latest
    container_name: <app>-logs
    restart: unless-stopped
    ports:
      - "<ask-port>:8080"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      DOZZLE_FILTER: "name=<app>*"
```
- Ask the user which host port to expose
- Filter to only show logs for containers in this app's stack

## Docker Commands
- **Always use `docker compose` (not `docker` directly) for starting/stopping/restarting services**
- **"Restart" always means `down` then `up -d`** — never `docker compose restart`, as it does not re-read the compose file or pick up environment variable changes
- Run from the app's compose directory, e.g.:
  ```
  cd /docker/homelab-config/data-host/composed-apps/zomboid && sudo docker compose down
  cd /docker/homelab-config/data-host/composed-apps/zomboid && sudo docker compose up -d
  ```
- Never use `docker stop <container>` or `docker start <container>` — always go through compose

## Conventions
- Use `restart: unless-stopped` on all services
- Define resource limits (`deploy.resources`) for game servers
- Game server data paths: `/docker/game/<game-name>/`
- Backup data paths: `/docker/game/<game-name>/backups/` (or `backups-daily/` if the app has its own backup dir)
- Container names should be descriptive and match the directory name
- Use `.env` files for sensitive values when possible rather than inline environment variables

## Existing Servers with Backup Sidecars
- Zomboid: `composed-apps/zomboid/` → backups at `/docker/game/zomboid/backups/`
- Valheim: `composed-apps/valheim/` → backups at `/docker/game/valheim/backups-daily/`
- Minecraft ATM9 Survival: `composed-apps/minecraft-atm9-survival/` → backups at `/docker/game/minecraft/minecraftatm9s_backups/`

## about-site i18n pipeline

- English source of truth: `composed-apps/about-site/src/i18n/ui.ts` (the `t.en` block).
- Translations are auto-generated by `composed-apps/ollama/` running `qwen2.5:7b` (CPU-only; no GPU on this host). Initially specced for `deepseek-r1:7b` but switched to `qwen2.5:7b` after empirical testing: ~20x faster on CPU and better at short UI labels.
- `npm run build` runs `prebuild` which runs `regen-i18n` automatically.
  - Warm cache → near-instant (no Ollama calls).
  - New/edited English → only the deltas hit Ollama.
- Cache lives at `composed-apps/about-site/src/i18n/.translations-cache.json` and is committed to git.
- To pin a specific translation: edit the value inside `.translations-cache.json` directly. The recorded `hash` must match the current English; the next regen will treat your edit as canonical for that (lang, key).
- Hand-editing `ui.ts` directly does NOT survive a regen; always go through the cache.
- Force a full re-translation: `npm run regen-i18n -- --force`.
- Dry-run (list misses without writing): `npm run regen-i18n -- --dry-run`.
- Translator outages never block deploys: Ollama unreachable → warn, leave files untouched, exit 0.
- Orphan keys (in cache but not in `t.en`) are auto-pruned on each full run.
- Sidecars: `ollama-discord` (Discord webhook on up/down), `ollama-autoheal` (label-scoped), `ollama-logs` (Dozzle at port 9999).
- Quality gate (opt-in via `OLLAMA_GATE_ENABLED=true`): each translation passes a free programmatic check (`scripts/validate-translation.ts`: script presence, English-passthrough, foreign-script soup, dropped verbatim tokens, length blowout) then a 7b LLM judge (`OLLAMA_JUDGE_MODEL`, returns `PASS`/`FAIL: reason`). Up to 3 attempts per string; a string that never passes is logged and falls back to English (build still exits 0). Gate is OFF by default, so warm-cache CPU prebuilds are unchanged.
- GPU cold-fill (runs on Rocinante's RTX 5080, not this host): bring up an ephemeral Ollama container there, open an SSH tunnel from nemesis (`ssh -fN -L 11435:localhost:11434 arthu@192.168.1.247`), then `OLLAMA_URL=http://127.0.0.1:11435 OLLAMA_MODEL=qwen2.5:14b OLLAMA_JUDGE_MODEL=qwen2.5:7b OLLAMA_GATE_ENABLED=true npm run regen-i18n`. Tear the container down afterward (the user games on that box); the model volume persists.
