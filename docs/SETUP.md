# Setting up this environment

How the homelab in this repo is put together and how to stand up your own copy of
it. This is a description of a real, running environment, not a one-click installer:
expect to substitute your own hostnames, IPs, domain and secrets.

## 1. Shape of the environment

```
                     Internet
                        |
                 router (443 -> data-host)
                        |
   +--------------------+--------------------+
   |                    LAN 192.168.1.0/24   |
   |                                         |
 data-host (nemesis)                 compute-node (devastator)
   Traefik edge (TLS, *.rt-541.io)     Plex (GPU transcode)
   media arrays /docker/plex/media     vLLM on Arc Pro B70
   arr stack + qBittorrent (VPN)       NanoClaw agent fleet
   Seerr, Recyclarr, Homepage          media-transcoder worker
   game servers, backups               Pi-hole secondary
   plex-ops runner (:8377)
   |                                         |
   +--------------------+--------------------+
                        |
      control plane (Proxmox nodes, HA Pi-hole DNS/DHCP VIP,
      Uptime Kuma, Grafana) - kuat-drive-yards-public
```

Both Docker hosts are VMs on a two-node Proxmox cluster; the small always-on
services (DNS/DHCP, monitoring, control plane) are HA pairs of LXCs pinned to
different physical nodes. Everything in this repo is deployed as Docker Compose
stacks, one directory per app, plus a few systemd units and scripts on the hosts.

## 2. Prerequisites

Per Docker host:

- A Linux VM (RHEL 9/10 here; anything with Docker Engine + Compose v2 works).
  On Proxmox, give the VM `cpu: host` (or at least x86-64-v3): a generic CPU model
  makes recent kernels panic on this hardware.
- Docker Engine with the Compose plugin; an admin account with passwordless sudo
  (the maintenance scripts and the plex-ops runner call `sudo -n`).
- This repo cloned to `/docker/homelab-config` on every host (systemd units and
  scripts reference that path).
- Storage under `/docker`: app config dirs (`/docker/<app>`), media at
  `/docker/plex/media` (and `/docker/plex/media2`), game data at
  `/docker/game/<game>`. The data host owns the arrays; the compute node reaches
  them over NFS (the `plex-nfs` service in the plex stack exports them, NFSv4).
- A GPU on the compute node for Plex transcode, vLLM and the transcode worker.
  The Arc Pro B70 runs on the stock RHEL 10 kernel with the `xe` driver; VA-API
  needs the render node (`/dev/dri/renderD128`) passed into containers.

For the control plane, DNS/DHCP and monitoring, follow
[kuat-drive-yards-public](https://github.com/rt-541/kuat-drive-yards-public); the
notes below assume it exists.

## 3. Network, DNS and ingress

- **DNS + DHCP** come from an HA Pi-hole pair behind a keepalived VIP
  (`192.168.1.2`). The router's DHCP is off. Leased hostnames are registered
  automatically under the domain, so `<host>.rt-541.io` follows a machine's lease.
  Anything that must be allowlisted by IP gets a DHCP reservation.
- **Wildcard DNS**: internally `*.rt-541.io` resolves to the Traefik host, so a
  new web service needs no DNS record. Publicly the zone is on Cloudflare.
- **Traefik** (`data-host/composed-apps/traefik/`) is the single edge. It
  terminates TLS for every service with one wildcard certificate obtained via the
  Cloudflare DNS challenge (`certResolver: default`). Port 443 is forwarded from
  the router to it; port 80 only redirects.
- **LAN-only vs public** is one middleware: a router that carries
  `lan-only@docker` (an IP allowlist of the LAN) is internal; drop it and the
  service is public. Cross-host services (on the compute node or an LXC) are
  attached through Traefik's file provider (`traefik/config/<name>.yml`), same
  rule.
- **Secrets** never sit in tracked files. Every stack has a `.env.example`; copy
  it to `.env` and fill it in. Cloudflare API token, VPN keys, Discord webhooks,
  arr API keys and the plex-ops bearer token all live that way (or in root-owned
  env files under `/etc`).

## 4. Bringing up a stack

```bash
cd /docker/homelab-config/data-host/composed-apps/<app>
cp .env.example .env && $EDITOR .env          # only if the stack has one
sudo docker compose up -d
sudo docker compose logs --tail 50
```

House rules that the scripts and agents rely on:

- Restart means `down` then `up -d`, never `docker compose restart` (which does
  not re-read the compose file or `.env`). Never `docker start/stop` a container
  directly.
- `restart: unless-stopped` on every service; resource limits on game servers.
- Container names match the directory name. Sidecars follow a fixed menu
  (scheduled backup, Discord notifier, autoheal, Dozzle logs); see the root
  `CLAUDE.md` for the templates.
- Pin image tags where the registry has no `latest` or where a stale `latest`
  has bitten before (Recyclarr, gluetun, byparr).
- When a service is added or retired, update Homepage
  (`data-host/composed-apps/homepage/config/services.yaml`) so the dashboard
  stays the index of what runs.

Suggested order on a fresh build: Traefik and Pi-hole first (ingress and name
resolution), then the plex stack on the data host (arr apps, qBittorrent through
gluetun, Seerr, the NFS export), Plex on the compute node, then everything else.

## 5. The media pipeline

- `data-host/composed-apps/plex-stack/`: Sonarr, Radarr, Prowlarr (indexers),
  qBittorrent riding gluetun's VPN network namespace, byparr (Cloudflare
  challenge solver), Seerr (requests) and the NFS export of the media tree.
- `data-host/composed-apps/recyclarr/`: TRaSH-guides custom formats and quality
  profile settings synced into both arrs daily, so junk releases are rejected at
  grab time. Preview first (`recyclarr sync --preview`), then apply.
- `compute-node/composed-apps/plex/`: Plex Media Server with the GPU and the NFS
  media volume.
- `scripts/media-reclaim/` + `compute-node/composed-apps/media-transcoder/`: the
  space-reclaim campaign that compresses 4K remuxes on the GPU in scheduled
  windows, with a keep-list, a pilot gate and a holding directory for originals.

## 6. The agent layer (optional)

`scripts/plex-ops/` is a small stdlib-only HTTP service on the data host that
exposes read-only probes and a whitelist of re-verifying, audit-logged actions
over the media pipeline, both as REST and as MCP tools. A NanoClaw group on the
compute node (`docs/plex-ops/group/`) drives it from a Discord channel: a help
desk ("this episode is missing", "stats for X", "what can we compress tonight"),
scheduled maintenance (queue triage, service watchdog, library audit, digest) and
the compression waves. Bring-up is scripted:

1. `scripts/plex-ops/deploy-nemesis.sh` on the data host (token, systemd unit,
   Recyclarr, token push).
2. `docs/plex-ops/group/deploy-devastator.sh` on the compute node (NFS mount,
   Discord wiring, group config, skills, scheduled tasks).
3. `scripts/plex-ops/kuma-monitors.py` from the control plane.

`docs/plex-ops/group/DEPLOY.md` is the runbook; `scripts/plex-ops/CONTRACT.md`
the API contract. The agent starts in shadow mode (it says what it would do) and
goes live on an explicit instruction.

## 7. The compute node's LLM stack

`compute-node/composed-apps/plex-compute/` runs vLLM on the Arc Pro B70 with an
Anthropic-compatible API, sized for a Claude Code harness (long context, tool
calls). The NanoClaw fleet's lightweight channels run on it through a small
normalizing proxy; channels that need a stronger model use the Claude API through
the gateway. See `docs/superpowers/plans/` for the bring-up notes.

## 8. Monitoring and backups

- Uptime Kuma (HA pair, VIP) monitors every running container through read-only
  Docker socket proxies on both hosts, plus HTTP checks such as the plex-ops
  runner; alerts go to Discord. Grafana/Prometheus cover host metrics and SMART.
- Game servers and app data use the `offen/docker-volume-backup` sidecar pattern
  (daily, rotated); see the existing stacks for the template.
- The plex-ops runner writes one JSON audit line per call to
  `/docker/plex/logs/plex-ops/audit.jsonl`; the reclaim campaign keeps its
  ledger and queue on the media share under `.reclaim/`.

## 9. Adapting it

Search-and-replace is most of the work: the domain (`rt-541.io`), the two
hostnames, the LAN prefix (`192.168.1.`), the Discord identifiers (redacted here
as placeholders) and the paths under `/docker`. Keep the structure: one
directory per app, `.env.example` next to every compose file, and the
down/up restart rule.
