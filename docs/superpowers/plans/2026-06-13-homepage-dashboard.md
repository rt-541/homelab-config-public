# Homepage Dashboard + About Services Page — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or executing-plans. Steps use `- [ ]`.

**Goal:** Deploy a LAN Homepage dashboard at `home.rt-541.io` covering all services, and add a curated public Services page to the about-site.

**Architecture:** `gethomepage/homepage` container behind Traefik `lan-only@docker`, config-as-committed-YAML, health via siteMonitor + read-only docker-socket-proxy, widget API keys in a gitignored `.env`. Separately, a static Astro `services.astro` page on the public about-site.

**Spec:** `docs/superpowers/specs/2026-06-13-homepage-dashboard-design.md`

**Conventions:** `restart: unless-stopped`; `.env` gitignored; reference the existing `lan-only@docker` middleware + `proxy` network; deploy with `docker compose down && up -d` from the app dir. about-site: English in `ui.ts` `t.en`, let `prebuild` regen translations (don't hand-edit translated values).

---

## Part A — Homepage (LAN dashboard)

### Task 1: Scaffold the composed-app + Traefik
**Files:** create `nemesis/composed-apps/homepage/{docker-compose.yml,.env.example}` and `config/{settings,services,bookmarks,widgets,docker}.yaml`

- [ ] **Step 1: docker-compose.yml**
```yaml
services:
  homepage:
    image: ghcr.io/gethomepage/homepage:latest
    container_name: homepage
    restart: unless-stopped
    env_file: .env
    environment:
      HOMEPAGE_ALLOWED_HOSTS: home.rt-541.io
    volumes:
      - ./config:/app/config
      - ./icons:/app/public/icons
    networks: [proxy]
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.homepage.rule=Host(`home.rt-541.io`)"
      - "traefik.http.routers.homepage.entrypoints=secure"
      - "traefik.http.routers.homepage.tls=true"
      - "traefik.http.routers.homepage.middlewares=lan-only@docker"
      - "traefik.http.services.homepage.loadbalancer.server.port=3000"
networks:
  proxy:
    external: true
```
- [ ] **Step 2: .env.example** — document widget keys (do not commit real `.env`):
```
HOMEPAGE_VAR_SONARR_KEY=
HOMEPAGE_VAR_RADARR_KEY=
HOMEPAGE_VAR_PROWLARR_KEY=
HOMEPAGE_VAR_QBIT_USER=
HOMEPAGE_VAR_QBIT_PASS=
HOMEPAGE_VAR_PLEX_TOKEN=
HOMEPAGE_VAR_PIHOLE_KEY=
HOMEPAGE_VAR_OVERSEERR_KEY=
HOMEPAGE_VAR_GRAFANA_USER=
HOMEPAGE_VAR_GRAFANA_PASS=
```
- [ ] **Step 3:** confirm DNS — `home.rt-541.io` must resolve to the Traefik host (add to Pi-hole `dns.hosts` / local records like the other `*.rt-541.io`); verify with `dig home.rt-541.io @192.168.1.2`.
- [ ] **Step 4: commit** (just the homepage dir).

### Task 2: `settings.yaml` + `docker.yaml` (layout + container status)
- [ ] `settings.yaml`: title, theme, group columns, `layout:` ordering the groups (Media, Infra, Apps, Game Servers, LLM).
- [ ] `docker.yaml`: two remote docker hosts via the read-only socket-proxies:
```yaml
nemesis:
  host: 192.168.1.214
  port: 2375
devastator:
  host: 192.168.1.216
  port: 2375
```
- [ ] Commit.

### Task 3: `services.yaml` (tiles + health + widgets)
- [ ] One entry per service from the spec's groups: `href`, `icon`, `description`, `siteMonitor: <url>` (up/down), `server`/`container` for the Docker-managed ones (status from the proxy). Add **widget** blocks for the supported services using `{{HOMEPAGE_VAR_*}}`:
```yaml
- Media:
    - Plex:
        href: https://plex.rt-541.io
        icon: plex.png
        widget: { type: plex, url: http://192.168.1.216:32400, key: "{{HOMEPAGE_VAR_PLEX_TOKEN}}" }
    - Sonarr:
        href: https://sonarr.rt-541.io
        icon: sonarr.png
        widget: { type: sonarr, url: https://sonarr.rt-541.io, key: "{{HOMEPAGE_VAR_SONARR_KEY}}" }
    # ... radarr, prowlarr, qbittorrent, overseerr similarly
- Infra:
    - Pi-hole:
        href: https://pihole.rt-541.io
        widget: { type: pihole, url: http://192.168.1.2, key: "{{HOMEPAGE_VAR_PIHOLE_KEY}}" }
    - Grafana: { href: https://grafana.rt-541.io, widget: { type: grafana, url: https://grafana.rt-541.io, username: "{{HOMEPAGE_VAR_GRAFANA_USER}}", password: "{{HOMEPAGE_VAR_GRAFANA_PASS}}" } }
    # ... status, zabbix, goaccess, umami, proxmox
- LLM:
    - vLLM (B70): { href: http://192.168.1.216:8000, siteMonitor: http://192.168.1.216:8000/health }
```
- [ ] `bookmarks.yaml`: GitHub repo, docs, router, Proxmox UIs, Cloudflare.
- [ ] `widgets.yaml`: resources (cpu/mem/disk), search, datetime.
- [ ] Commit.

### Task 4: Deploy + verify
- [ ] On nemesis: create real `.env` from `.env.example` (pull keys from each app — Sonarr/Radarr/Prowlarr Settings→General, qBit creds, Plex token, Pi-hole API token, Overseerr, Grafana). `docker compose up -d`.
- [ ] Verify from a LAN browser: `https://home.rt-541.io` loads, all groups render, up/down dots correct, widgets populate (Plex/arr/pihole), container statuses show via the proxies. Confirm an off-LAN request is 403 (lan-only). Commit any config tweaks.

## Part B — About-site Services page (public)

### Task 5: `services.astro` + nav + i18n
**Files:** create `nemesis/composed-apps/about-site/src/pages/services.astro`; modify the nav component + `src/i18n/ui.ts` (`t.en`)
- [ ] Read an existing page (e.g. `gaming.astro`) + the nav component + `ui.ts` to match patterns.
- [ ] Add `t.en` keys: `services.title`, `services.tagline`, and tile labels (Plex/Overseerr/Status/Chat/About) + descriptions. (Let `prebuild`/`regen-i18n` translate; do not hand-edit translated values.)
- [ ] `services.astro`: reuse the site's card/grid component; **curated friend-safe tiles only** — Plex `https://plex.rt-541.io`, Overseerr `https://overseerr.rt-541.io`, Status `https://status.rt-541.io`, Revolt `https://revolt.rt-541.io`, About `/`. No admin tools.
- [ ] Add a "Services" nav entry linking `/services`.
- [ ] Commit.

### Task 6: Build + deploy about-site
- [ ] `cd nemesis/composed-apps/about-site && npm run build` (runs `prebuild`→`regen-i18n`; warm cache = fast, new keys hit Ollama). Confirm `/services` renders in the preview and translations generated.
- [ ] Deploy per the about-site's normal flow (`docker compose down && up -d`), verify `https://about.rt-541.io/services` publicly. Commit the updated `.translations-cache.json`.

---

## Self-review notes
- Spec coverage: LAN dashboard (Tasks 1-4), public Services page (Tasks 5-6), health via siteMonitor + socket-proxy (Tasks 2-3), secrets gitignored (Task 1), lan-only enforcement (Task 1,4), friend-safe-only public links (Task 5).
- Prereqs: `lan-only@docker` middleware + `proxy` network exist (they do); `home.rt-541.io` DNS record (Task 1 Step 3); read-only socket-proxies on both hosts (they exist).
- Widget URLs: use internal/LAN URLs where possible to avoid Cloudflare hops for *arr/pihole; Plex/qBit by host:port.
