# HA Synthetic Monitor + Status Page (Uptime Kuma) — Design

Date: 2026-06-05
Status: Approved (brainstorming) — pending implementation plan
Repos: `kuat-drive-yards` (the two monitor LXCs + keepalived + Kuma install +
monitors-as-code) and `homelab-config` (socket-proxies, Traefik route, DNS)

## Goal

A **highly-available** self-hosted synthetic monitor that probes the **whole
homelab** (web, infra, game servers, Docker health), renders a **public status
page**, and sends **Discord alerts** — and that keeps working when any single
Proxmox node fails. Tool: **Uptime Kuma**. Pinned to **baremetal LXCs on the
Proxmox nodes** (not a VM), so the watcher doesn't share fate with the watched.

## Architecture

Two dedicated **privileged** Debian 12 LXCs running Uptime Kuma **natively**
(Node.js LTS + Kuma + a systemd service), provisioned via the kuat-drive-yards
`lxc-container` OpenTofu module (like the Pi-hole/control LXCs):

| LXC | Node | IP | VMID | keepalived |
|-----|------|----|------|-----------|
| kuma-sienar | sienar (redundant PSU) | 192.168.1.13 | 9301 | MASTER (prio 150) |
| kuma-incomm | incomm | 192.168.1.15 | 9302 | BACKUP (prio 100) |

- **keepalived VIP `192.168.1.14`** floats between them (VRRP, virtual_router_id
  54). `status.rt-541.io` resolves to Traefik, which proxies to the VIP → the live
  Kuma. Privileged LXC because keepalived VRRP needs it (same as the DNS pair).
- **Both Kumas independently probe the full estate** (no shared DB — each has its
  own SQLite). Identical monitor sets are kept in sync by applying a
  version-controlled **`monitors.py`** (uptime-kuma-api) to both — idempotent.
- **Single alerter:** a keepalived `notify` script enables the Discord
  notification on the MASTER Kuma and disables it on the BACKUP (toggled via
  uptime-kuma-api) — exactly one alert, and alerting fails over with the VIP.
  Mirrors the Pi-hole DHCP-follows-VIP pattern.
- **Docker container health:** read-only `tecnativa/docker-socket-proxy` on
  **nemesis** and **devastator** (`CONTAINERS=1` only, LAN-restricted to the Kuma
  IPs); both Kumas add these as Docker Hosts. (Kuma is remote to both docker
  hosts now, so each needs a proxy.)
- **DNS:** `status.rt-541.io → 192.168.1.214` (Traefik) on the HA Pi-holes.

### Traefik exposure (public status page, LAN-only admin)

Traefik runs on nemesis; the Kuma backend is the **VIP (not a Docker container)**,
so use Traefik's **file provider** (`/config`) to define the service →
`http://192.168.1.14:3001` and the routers/middlewares:
- **Public router** (high priority): `Host(status.rt-541.io)` + PathPrefix any of
  `/status`, `/assets`, `/api/status-page`, `/api/entry-page`, `/upload`,
  `/icon.svg` → kuma VIP, no allowlist. (Verify the public page fully loads
  off-LAN; add any blocked asset prefix.)
- **LAN-only admin router** (catch-all): `Host(status.rt-541.io)` → kuma VIP +
  an ipAllowList middleware (`192.168.1.0/24`). Covers `/`, `/dashboard`,
  `/settings`, `/socket.io`, other `/api`. Kuma's login is defense-in-depth.

## Monitors (as code via `uptime-kuma-api`, applied to both)

`kuat-drive-yards` `ansible/monitors/monitors.py` (+ requirements) — a
version-controlled list applied idempotently to each Kuma:
- **Web (HTTP/keyword):** about, analytics (`/script.js`→200), logs, plex,
  traefik (`proxy.rt-541.io`), pi-hole admin, sonarr/radarr/prowlarr/qbit/overseerr.
- **Infra (ping/TCP):** sienar `.5`, incomm `.6`, nemesis `.214`, devastator `.216`,
  DNS VIP `.2:53`, dns `.3`/`.4`, tarkin `.11`, pellaeon `.12`, the Kuma peer.
- **Game servers (TCP/port):** Zomboid, Valheim, Minecraft ATM9 (ports per
  `/docker/game/*` composes).
- **Docker health:** key containers on nemesis + devastator via the two proxies.
- Each monitor gets the Discord notification + `retries ≥ 2` (flap protection).

## Data flow / HA behavior

Each Kuma probes on its interval → own SQLite → renders dashboard + status page.
The VIP-holder's notification is enabled → single Discord alert on state change.
Node failure: keepalived moves the VIP to the survivor, its notify script enables
its Discord notification, and it keeps probing + alerting. The status page (via
Traefik→VIP) follows. **Discord alerts go directly from the Kuma LXCs, not through
Traefik** — so alerting survives even a nemesis/Traefik outage.

## Components

- `kuat-drive-yards`: `environments/homelab/main.tf` (`monitor_primary` /
  `monitor_secondary` LXC modules); `ansible/playbooks/setup_kuma.yml` (Node +
  Kuma + systemd + keepalived + the notify script); `ansible/monitors/monitors.py`.
- `homelab-config`: `data-host/composed-apps/docker-socket-proxy/` +
  `compute-node/composed-apps/docker-socket-proxy/`; a Traefik file-provider config
  `data-host/composed-apps/traefik/config/status.yml`; DNS record on the Pi-holes.
- Manual one-time (Kuma UI, each instance or scripted): admin account; paste the
  Discord webhook into a notification named consistently so `monitors.py` can
  attach it; build the public status page (select monitors).

## Testing

1. Both LXCs up, Kuma reachable on each (`.13:3001`, `.15:3001`); VIP `.14` on the
   MASTER.
2. `monitors.py` applied to both → monitors appear and go green on both.
3. `https://status.rt-541.io` public page loads **off-LAN**; admin **refused
   off-LAN**, allowed on LAN.
4. Force a monitor down → **exactly one** Discord alert (from the VIP holder) →
   recovery clears it.
5. **HA drill:** stop keepalived/Kuma on the MASTER → VIP + alerting move to the
   secondary within seconds, monitoring continues, status page still served →
   restore.
6. devastator + nemesis container health visible via the proxies.

## Security / scope

- Docker sockets exposed **read-only**, restricted to the Kuma IPs; admin LAN-only.
- Non-goals: HA Traefik for the *public* page (alerting is already node-independent
  via Discord); distributed/off-site probes; paging beyond Discord; a shared Kuma
  DB cluster (independent instances + monitors-as-code is the HA model).
