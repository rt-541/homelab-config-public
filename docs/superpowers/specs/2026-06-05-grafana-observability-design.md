# HA Observability Stack (Prometheus + Grafana) — Design

Date: 2026-06-05
Status: Approved (brainstorming) — pending implementation plan
Repos: `kuat-drive-yards` (the two obs LXCs + stack + provisioning) and
`homelab-config` (host exporters, Traefik route, DNS)

## Goal

Host-health + capacity + disk-SMART monitoring with dashboards, a node/mesh
topology view, and metric alerts to Discord — complementing Kuma (up/down).
Pinned to baremetal LXCs, HA (mirrors the DNS/Kuma pairs). Catches the incident
class we hit: degraded arrays, missing PVs, pool capacity, failing disks, host
resource exhaustion.

## Architecture

Two **privileged** Debian 12 LXCs (kuat-drive-yards `lxc-container` module):

| LXC | Node | IP | VMID | keepalived |
|-----|------|----|------|-----------|
| obs-sienar | sienar (PSU) | 192.168.1.16 | 9401 | MASTER (prio 150) |
| obs-incomm | incomm | 192.168.1.18 | 9402 | BACKUP (prio 100) |

- **keepalived VIP `192.168.1.17`** (VRRP, virtual_router_id 55). `grafana.rt-541.io`
  → Traefik → VIP → the live Grafana. Privileged LXC for VRRP. DNS via Pi-hole VIP
  (so it resolves LOCAL — same nameserver=`192.168.1.2` fix as the Kuma LXCs).
- Each LXC runs the stack natively (systemd):
  - **Prometheus** (`:9090`, `--storage.tsdb.retention.time=30d`) — scrapes all
    targets; identical scrape config on both (redundant HA scraping).
  - **Grafana** (`:3000`) — datasource = `http://127.0.0.1:9090` (its local
    Prometheus); dashboards/datasources/alerting **provisioned from files** so both
    instances are identical (config-as-code).
  - **Alertmanager** (`:9093`) — the two run as a **gossip cluster**
    (`--cluster.peer`), so duplicate alerts from the two Prometheis are **deduped**
    → exactly one Discord message. (Native HA; no keepalived toggle needed.)

## Exporters (scrape targets)

- **prometheus-pve-exporter** (`:9221`, in each obs LXC, talks to the **PVE API**
  with a read-only token — no host install) → Proxmox **node + guest + storage**
  metrics (LVM/pool/capacity/degraded state).
- **node_exporter** (`:9100`) installed on the **4 hosts**: sienar, incomm
  (PVE hosts, native systemd), nemesis, devastator (docker hosts — run as the
  `prom/node-exporter` container via compose) → host CPU/RAM/disk/net/load/temp.
- **smartctl_exporter** (`:9633`) native on the two **PVE hosts** (sienar, incomm)
  → physical-disk **SMART** health.
- **Kuma `/metrics`** (`http://192.168.1.14:3001/metrics`) → service up/down into
  Grafana.

## Dashboards (provisioned as code)

Node Exporter Full (id 1860), Proxmox via pve-exporter, SMART/disk health, a
**Canvas topology** (nodes → guests → services, elements colored by live up/down
+ load), and a Kuma overview.

## Alerting → Discord (reuse the nemesis-bot webhook)

Prometheus alert rules → Alertmanager (deduped) → a Discord receiver:
- disk usage > 85% (`node_filesystem_avail_bytes`)
- Proxmox storage degraded / PV missing / pool > 90% (pve-exporter)
- SMART health failed or failure-predicted (smartctl_exporter)
- host/exporter down (`up == 0` for 5m)
- RAM > 90% or load sustained-high for 10m

## Exposure

`grafana.rt-541.io` → Traefik (`secure`/`default`) → VIP `:3000`, **LAN-only**
(ipAllowList `192.168.1.0/24`). Prometheus + Alertmanager stay internal (no
Traefik route). DNS `grafana.rt-541.io → 192.168.1.214` on the Pi-holes.

## Components

- `kuat-drive-yards`: `environments/homelab/main.tf` (`obs_primary`/`obs_secondary`,
  nameserver `.2`); `ansible/playbooks/setup_observability.yml` (Prometheus +
  Alertmanager + Grafana + pve-exporter + keepalived); provisioning under
  `ansible/observability/` (prometheus.yml, alert.rules.yml, alertmanager.yml,
  grafana datasource + dashboards + alerting). A read-only PVE API token for
  pve-exporter (gitignored).
- `homelab-config`: `ansible/playbooks/node_exporter.yml` (native on sienar/incomm
  + smartctl_exporter there) + `nemesis|devastator/composed-apps/node-exporter/`
  (container on the docker hosts); `nemesis/composed-apps/traefik/config/grafana.yml`
  (route → VIP, LAN-only); DNS record.

## Data flow / HA

Each Prometheus scrapes all targets every 15s → local 30d TSDB → local Grafana
queries it. Both Prometheis evaluate the same alert rules → both Alertmanagers →
gossip-dedupe → **one** Discord alert. keepalived moves the VIP on node failure;
Grafana/alerts continue on the survivor (it has its own continuous TSDB +
provisioned config). Discord alerts are independent of Traefik.

## Testing

1. Both LXCs up; Prometheus `:9090/-/healthy` ok on both; targets all `UP` in
   Prometheus (4 node_exporters, 2 pve-exporters, 2 smartctl, kuma).
2. `grafana.rt-541.io` loads from LAN, refused off-LAN; dashboards render with data.
3. Canvas topology shows the estate colored by live status.
4. Alert test: fill a tmpfs to >85% (or stop an exporter) → **one** Discord alert
   (dedupe verified) → clear.
5. HA drill: stop keepalived on the MASTER → VIP + Grafana follow to the secondary;
   Alertmanager cluster still sends single alerts.
6. SMART: confirm smartctl_exporter surfaces the sienar disks (incl. the array
   state) in the SMART dashboard.

## Security / scope

- pve-exporter uses a **read-only** PVE API token; exporters are read-only;
  Grafana LAN-only + admin login. Non-goals: long-term (>30d) storage / Thanos,
  log aggregation (Loki) — could follow later; tracing.
