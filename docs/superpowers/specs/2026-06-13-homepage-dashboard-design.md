# Homelab Landing Page: Homepage Dashboard + Public Services Page (Design)

Date: 2026-06-13
Status: Approved (LAN host `home.rt-541.io`; public links = a Services page on the about-site)

## Goal
A single place to reach everything. Two surfaces:
1. **LAN dashboard** — private, all ~28 services with live health/widgets, at `home.rt-541.io`.
2. **Public curated links** — a friend-safe Services page on the existing public about-site.

## Decisions (locked in brainstorming)
- Dashboard = **Homepage** (`gethomepage/homepage`), not a custom build.
- Public links = a **Services page in the Astro about-site** (`about.rt-541.io/services`), NOT a second public dashboard — keeps the public edge static (minimal attack surface).
- LAN host = `home.rt-541.io`.

## Component 1 — Homepage (LAN)
- **New composed-app** `data-host/composed-apps/homepage/`, image `ghcr.io/gethomepage/homepage`, `restart: unless-stopped`, on the `proxy` network.
- **Traefik:** `Host(\`home.rt-541.io\`)`, `secure` entrypoint, TLS, middleware **`lan-only@docker`** (already defined in `umami/docker-compose.yml`: ipallowlist `192.168.1.0/24,127.0.0.1/32`). Homepage needs `HOMEPAGE_ALLOWED_HOSTS=home.rt-541.io` env.
- **Config = committed YAML** in `./config/` (bind-mounted to `/app/config`): `settings.yaml`, `services.yaml`, `bookmarks.yaml`, `widgets.yaml`, `docker.yaml`.
- **Service groups** (tiles with href + icon + status):
  - **Media:** Plex, Overseerr, Sonarr, Radarr, Prowlarr, qBittorrent
  - **Infra/Monitoring:** Grafana, Uptime-Kuma (status), Pi-hole, Zabbix, GoAccess, Umami, Proxmox (sienar)
  - **Apps:** Mealie, Vikunja, Revolt, MinIO, cameras (go2rtc/cam)
  - **Game Servers:** Minecraft (ATM9/DeceasedCraft), Valheim, Palworld, Zomboid, Enshrouded, Core Keeper, Factorio, V Rising, Abiotic Factor
  - **LLM:** vLLM (B70, `192.168.1.216:8000`), llm-queue (when built)
- **Health/status:** Homepage `siteMonitor`/`ping` per service for up/down dots; **service widgets** (Plex now-playing, Sonarr/Radarr/Prowlarr queues, qBittorrent speeds, Pi-hole blocked %, Grafana) for the supported ones.
- **Container status:** via the existing read-only **docker-socket-proxy** (nemesis `:2375`, and devastator `192.168.1.216:2375`) — configured in `docker.yaml` as remote docker hosts. No raw socket mount → dashboard can't control anything.
- **Secrets:** widget API keys live in a gitignored `.env` referenced as `HOMEPAGE_VAR_*` (Homepage's env-var interpolation) — never committed, per repo convention. `.env.example` documents the needed vars.

## Component 2 — Services page on the about-site (public)
- New Astro page `src/pages/services.astro` at `about.rt-541.io/services`, plus a nav link.
- **Curated, friend-safe links only:** Plex (`plex.rt-541.io`), Overseerr (request media), Status page (`status.rt-541.io`), Revolt chat (`revolt.rt-541.io`), and back to About. **No admin tools** (no *arr, qbit, grafana, pihole, proxmox).
- Static tiles (reuse the site's existing card/Tailwind components). No health widgets, no API keys — purely static links.
- **i18n:** add the English strings to `src/i18n/ui.ts` `t.en` (page title, tagline, tile labels); the `prebuild`/`regen-i18n` pipeline (Ollama) auto-translates on build per the about-site i18n docs. Do NOT hand-edit translated `ui.ts` values (they don't survive regen) or the cache unless pinning.

## Security
- LAN dashboard: never public; `lan-only@docker` enforces LAN-only at Traefik; only read-only socket-proxy access; secrets gitignored.
- Public page: static Astro only; rides the existing about-site Cloudflare/Traefik path; exposes only friend-safe destinations.

## Out of scope
- Exposing the LAN Homepage publicly; any service control from the dashboard; a second public dashboard; SSO/auth on the LAN page (LAN-only middleware is the gate).

## Open/assumptions
- Homepage icons via its built-in icon set (`mdi-*`/dashboard-icons) — no asset hosting needed.
- Devastator socket-proxy reachable at `192.168.1.216:2375` (it is — used by the Kuma reconciler).
