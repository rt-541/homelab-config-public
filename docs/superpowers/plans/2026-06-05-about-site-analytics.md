# about.rt-541.io Analytics (by Region) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up privacy-friendly aggregate analytics for about.rt-541.io by region: Umami (cookieless JS, human page-views) + GoAccess (server-side, all-traffic from Traefik logs + GeoIP), both LAN-only dashboards.

**Architecture:** Two Docker Compose apps on nemesis (`nemesis/composed-apps/{umami,goaccess}`), behind the existing Traefik (`proxy` net, `secure` entrypoint, `default` Cloudflare certresolver). Traefik gets access logging enabled (JSON) on a shared volume that GoAccess reads. The about-site adds one cookieless `<script>` to `BaseLayout.astro`. Local DNS records point the two subdomains at nemesis (192.168.1.214).

**Tech Stack:** Docker Compose, Traefik v3, Umami v2 + Postgres 16, GoAccess + nginx:alpine, DB-IP Lite GeoIP mmdb, Astro (about-site), Pi-hole v6 (DNS).

**Conventions (from homelab-config/CLAUDE.md):** `restart: unless-stopped`; "restart" = `docker compose down` then `up -d`; run compose from the app dir; secrets in gitignored `.env`. Run all `docker compose` with `sudo`. Pi-holes: dns-incomm `192.168.1.3` (MASTER), dns-sienar `192.168.1.4`; reach as `ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa root@192.168.1.3`. The auto-classifier may block compound bash — prefer bare commands.

---

## File Structure

**Create:**
- `nemesis/composed-apps/umami/docker-compose.yml` — umami + postgres, Traefik split routing
- `nemesis/composed-apps/umami/.env` — secrets (gitignored)
- `nemesis/composed-apps/umami/.env.example` — documents the keys
- `nemesis/composed-apps/goaccess/docker-compose.yml` — goaccess + nginx report server
- `nemesis/composed-apps/goaccess/goaccess.conf` — GoAccess config (Traefik JSON parse + GeoIP)
- `nemesis/composed-apps/goaccess/nginx.conf` — serves the report dir

**Modify:**
- `nemesis/composed-apps/traefik/traefik.yml` — add `accessLog` (JSON)
- `nemesis/composed-apps/traefik/docker-compose.yml` — mount `/docker/traefik/logs:/logs`
- `nemesis/composed-apps/about-site/src/layouts/BaseLayout.astro` — add the Umami tag
- Pi-hole `dns.hosts` — add `analytics.rt-541.io`, `logs.rt-541.io` → 192.168.1.214

---

## Task 1: Umami app (umami + Postgres, Traefik split routing)

**Files:**
- Create: `nemesis/composed-apps/umami/.env.example`
- Create: `nemesis/composed-apps/umami/.env` (gitignored)
- Create: `nemesis/composed-apps/umami/docker-compose.yml`

- [ ] **Step 1: Write `.env.example`**

```bash
# Umami secrets — copy to .env and fill with real values
POSTGRES_PASSWORD=changeme-long-random
APP_SECRET=changeme-another-long-random-hex
```

- [ ] **Step 2: Create the real `.env` with generated secrets**

Run (generates two random secrets and writes `.env`):
```bash
cd /docker/homelab-config/nemesis/composed-apps/umami
printf 'POSTGRES_PASSWORD=%s\nAPP_SECRET=%s\n' "$(openssl rand -hex 24)" "$(openssl rand -hex 32)" > .env
cat .env
```
Expected: a `.env` with two long hex values.

- [ ] **Step 3: Ensure `.env` is gitignored**

Run:
```bash
grep -qxF 'nemesis/composed-apps/umami/.env' /docker/homelab-config/.gitignore || echo 'nemesis/composed-apps/umami/.env' >> /docker/homelab-config/.gitignore
git -C /docker/homelab-config check-ignore nemesis/composed-apps/umami/.env
```
Expected: prints the path (it is ignored).

- [ ] **Step 4: Write `docker-compose.yml`**

```yaml
---
networks:
  proxy:
    external: true
  umami-internal:

services:
  umami-db:
    image: postgres:16-alpine
    container_name: umami-db
    restart: unless-stopped
    environment:
      POSTGRES_DB: umami
      POSTGRES_USER: umami
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - umami-db-data:/var/lib/postgresql/data
    networks:
      - umami-internal
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U umami -d umami"]
      interval: 10s
      timeout: 5s
      retries: 6

  umami:
    image: ghcr.io/umami-software/umami:postgresql-latest
    container_name: umami
    restart: unless-stopped
    depends_on:
      umami-db:
        condition: service_healthy
    environment:
      DATABASE_TYPE: postgresql
      DATABASE_URL: postgresql://umami:${POSTGRES_PASSWORD}@umami-db:5432/umami
      APP_SECRET: ${APP_SECRET}
      CLIENT_IP_HEADER: X-Forwarded-For   # read real visitor IP from Traefik for GeoIP
    networks:
      - proxy
      - umami-internal
    labels:
      traefik.enable: "true"
      traefik.docker.network: proxy
      traefik.http.services.umami-svc.loadbalancer.server.port: "3000"
      # --- public collector: script + beacons, no IP restriction, higher priority ---
      traefik.http.routers.umami-pub.rule: "Host(`analytics.rt-541.io`) && (Path(`/script.js`) || PathPrefix(`/api/send`))"
      traefik.http.routers.umami-pub.entrypoints: secure
      traefik.http.routers.umami-pub.tls.certresolver: default
      traefik.http.routers.umami-pub.priority: "100"
      traefik.http.routers.umami-pub.service: umami-svc
      # --- LAN-only dashboard: catch-all, lower priority, ipallowlist ---
      traefik.http.routers.umami-dash.rule: "Host(`analytics.rt-541.io`)"
      traefik.http.routers.umami-dash.entrypoints: secure
      traefik.http.routers.umami-dash.tls.certresolver: default
      traefik.http.routers.umami-dash.priority: "10"
      traefik.http.routers.umami-dash.service: umami-svc
      traefik.http.routers.umami-dash.middlewares: lan-only@docker
      traefik.http.middlewares.lan-only.ipallowlist.sourcerange: "192.168.1.0/24,127.0.0.1/32"

volumes:
  umami-db-data:
```

- [ ] **Step 5: Bring it up**

Run:
```bash
cd /docker/homelab-config/nemesis/composed-apps/umami
sudo docker compose up -d
sudo docker compose ps
```
Expected: `umami-db` healthy, `umami` running.

- [ ] **Step 6: Verify Umami is serving (from the host)**

Run:
```bash
sudo docker exec umami wget -qO- http://localhost:3000/api/heartbeat || sudo docker logs umami --tail 20
```
Expected: a small JSON/OK heartbeat (Umami is up). If it errors, check `docker logs umami` for DB connection.

- [ ] **Step 7: Commit (compose + .env.example only; .env is gitignored)**

```bash
git -C /docker/homelab-config add nemesis/composed-apps/umami/docker-compose.yml nemesis/composed-apps/umami/.env.example .gitignore
git -C /docker/homelab-config commit -m "feat(umami): add cookieless analytics app (umami + postgres) behind Traefik"
```

---

## Task 2: DNS records for the two subdomains

**Files:** Pi-hole v6 `dns.hosts` on dns-incomm (.3); the 5-min sync propagates to dns-sienar (.4).

- [ ] **Step 1: Read the current dns.hosts array**

Run:
```bash
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa root@192.168.1.3 "pihole-FTL --config dns.hosts"
```
Expected: a `[ ... ]` array of `IP host` strings. Note the format.

- [ ] **Step 2: Add both records via the v6 toml (safe targeted append)**

The records point at nemesis (Traefik). Append two entries to the `dns.hosts` array in pihole.toml (mirrors how tarkin/pellaeon were added). Run on dns-incomm:
```bash
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa root@192.168.1.3 "sed -i 's|    \"192.168.1.214 cam.rt-541.io\"|    \"192.168.1.214 cam.rt-541.io\",\n    \"192.168.1.214 analytics.rt-541.io\",\n    \"192.168.1.214 logs.rt-541.io\"|' /etc/pihole/pihole.toml && pihole reloaddns"
```
(If the anchor line `192.168.1.214 cam.rt-541.io` isn't the last entry, anchor on whatever the final array entry is — read it from Step 1. The point is to append two lines before the closing `]`.)

- [ ] **Step 3: Verify resolution via the VIP**

Run:
```bash
nslookup analytics.rt-541.io 192.168.1.2
nslookup logs.rt-541.io 192.168.1.2
```
Expected: both → `192.168.1.214`.

- [ ] **Step 4: Confirm the sync carried it to .4 (wait up to 5 min or trigger)**

Run:
```bash
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa root@192.168.1.3 "systemctl start pihole-sync.service"; sleep 5; nslookup analytics.rt-541.io 192.168.1.4
```
Expected: `.4` also returns `192.168.1.214`.

(No git commit — Pi-hole config is on the LXCs, not in this repo yet.)

---

## Task 3: Create the Umami website + add the tracking tag to the about-site

**Files:**
- Modify: `nemesis/composed-apps/about-site/src/layouts/BaseLayout.astro`

- [ ] **Step 1: Create the about.rt-541.io website in Umami (get WEBSITE_ID)**

From a LAN browser, open `https://analytics.rt-541.io`, log in (first run: default admin `admin` / `umami` — change the password immediately under Settings → Profile). Settings → Websites → Add → Name `about`, Domain `about.rt-541.io`. Open it → "Edit" / "Tracking code" → copy the `data-website-id` UUID.

- [ ] **Step 2: Add the tag to BaseLayout.astro `<head>`**

In `nemesis/composed-apps/about-site/src/layouts/BaseLayout.astro`, immediately before `</head>` (the head opens at line 18, `<title>` is at line 36), add (replace `WEBSITE_ID` with the UUID from Step 1):

```html
    <!-- Umami cookieless analytics (self-hosted) -->
    <script defer src="https://analytics.rt-541.io/script.js" data-website-id="WEBSITE_ID"></script>
```

- [ ] **Step 3: Rebuild the about-site**

Run (warm i18n cache → fast; `prebuild` runs regen-i18n automatically):
```bash
cd /docker/homelab-config/nemesis/composed-apps/about-site
npm run build 2>&1 | tail -15
```
Expected: build completes, `dist/` regenerated. The new `<script>` appears in the built HTML — verify:
```bash
grep -r "analytics.rt-541.io/script.js" dist/ | head -1
```
Expected: a match in the built pages.

- [ ] **Step 4: Redeploy the about-site**

Run:
```bash
cd /docker/homelab-config/nemesis/composed-apps/about-site
sudo docker compose up -d
curl -sS -o /dev/null -w "%{http_code}\n" --resolve about.rt-541.io:443:192.168.1.214 https://about.rt-541.io/
```
Expected: `200`.

- [ ] **Step 5: Verify a pageview lands + no cookies**

Visit `https://about.rt-541.io` from a browser. In Umami → the `about` website → Realtime, confirm a visit with a country appears within ~30s. In browser devtools → Application → Cookies: confirm **no cookies** set by about.rt-541.io.

- [ ] **Step 6: Commit**

```bash
git -C /docker/homelab-config add nemesis/composed-apps/about-site/src/layouts/BaseLayout.astro nemesis/composed-apps/about-site/dist
git -C /docker/homelab-config commit -m "feat(about-site): add cookieless Umami tracking tag"
```

---

## Task 4: Enable Traefik JSON access logging

**Files:**
- Modify: `nemesis/composed-apps/traefik/traefik.yml`
- Modify: `nemesis/composed-apps/traefik/docker-compose.yml`

- [ ] **Step 1: Create the host log dir**

Run:
```bash
sudo mkdir -p /docker/traefik/logs
```

- [ ] **Step 2: Add `accessLog` to traefik.yml**

In `nemesis/composed-apps/traefik/traefik.yml`, after the `log:` block (which sets `level: DEBUG`), add:

```yaml
accessLog:
  filePath: "/logs/access.log"
  format: json
  bufferingSize: 100
```

- [ ] **Step 3: Mount the log volume in the traefik compose**

In `nemesis/composed-apps/traefik/docker-compose.yml`, under the traefik service `volumes:` list, add:

```yaml
      - /docker/traefik/logs:/logs
```

- [ ] **Step 4: Restart Traefik (down/up per convention — brief proxy bounce)**

Run:
```bash
cd /docker/homelab-config/nemesis/composed-apps/traefik
sudo docker compose down
sudo docker compose up -d
sleep 3
sudo docker compose ps
```
Expected: traefik running again.

- [ ] **Step 5: Verify the access log is being written (JSON lines)**

Run (generate a request, then read the log):
```bash
curl -sS -o /dev/null --resolve about.rt-541.io:443:192.168.1.214 https://about.rt-541.io/
sudo tail -2 /docker/traefik/logs/access.log
```
Expected: JSON lines with fields incl. `ClientHost`, `RequestHost`, `RequestPath`, `DownstreamStatus`, `request_User-Agent`, `StartUTC`.

- [ ] **Step 6: Add log rotation (keep raw IPs transient, ~7 days)**

Create `/etc/logrotate.d/traefik`:
```bash
sudo tee /etc/logrotate.d/traefik >/dev/null <<'EOF'
/docker/traefik/logs/access.log {
  daily
  rotate 7
  compress
  missingok
  notifempty
  copytruncate
}
EOF
sudo logrotate -d /etc/logrotate.d/traefik 2>&1 | tail -5
```
Expected: dry-run shows the rotation plan, no errors. (`copytruncate` avoids needing to signal Traefik.)

- [ ] **Step 7: Commit**

```bash
git -C /docker/homelab-config add nemesis/composed-apps/traefik/traefik.yml nemesis/composed-apps/traefik/docker-compose.yml
git -C /docker/homelab-config commit -m "feat(traefik): enable JSON access logging for analytics + add log rotation"
```

---

## Task 5: GoAccess all-traffic region report (LAN-only)

**Files:**
- Create: `nemesis/composed-apps/goaccess/goaccess.conf`
- Create: `nemesis/composed-apps/goaccess/nginx.conf`
- Create: `nemesis/composed-apps/goaccess/docker-compose.yml`

- [ ] **Step 1: Download the DB-IP Lite country GeoIP mmdb (no account needed)**

Run:
```bash
sudo mkdir -p /docker/goaccess/geoip /docker/goaccess/report
cd /tmp
curl -sSL -o dbip-country.mmdb.gz "https://download.db-ip.com/free/dbip-country-lite-2026-06.mmdb.gz"
gunzip -f dbip-country.mmdb.gz
sudo mv dbip-country.mmdb /docker/goaccess/geoip/dbip-country.mmdb
ls -l /docker/goaccess/geoip/
```
Expected: `dbip-country.mmdb` present (~a few MB). (Adjust the `2026-06` month in the URL to the current month if 404 — DB-IP publishes monthly; verify the latest at https://db-ip.com/db/download/ip-to-country-lite.)

- [ ] **Step 2: Write `goaccess.conf`** (parses Traefik JSON; about.rt-541.io filtered via the compose command in Step 4)

```
time-format %H:%M:%S
date-format %Y-%m-%d
log-format {"StartUTC":"%dT%t%^","DownstreamStatus":%s,"DownstreamContentSize":%b,"RequestMethod":"%m","RequestPath":"%U","RequestProtocol":"%H","ClientHost":"%h","request_User-Agent":"%u","request_Referer":"%R","RequestHost":"%v"}
geoip-database /geoip/dbip-country.mmdb
real-time-html true
ws-url wss://logs.rt-541.io:443/ws
port 7890
output /report/index.html
```

- [ ] **Step 3: Write `nginx.conf`** (serves the report + proxies the GoAccess websocket)

```nginx
server {
    listen 80;
    server_name logs.rt-541.io;
    root /usr/share/nginx/html;
    index index.html;

    location /ws {
        proxy_pass http://goaccess:7890;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 7d;
    }
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

- [ ] **Step 4: Write `docker-compose.yml`**

```yaml
---
networks:
  proxy:
    external: true
  goaccess-internal:

services:
  goaccess:
    image: allinurl/goaccess:latest
    container_name: goaccess
    restart: unless-stopped
    # Tail the Traefik log, keep only about.rt-541.io lines, feed GoAccess on stdin.
    entrypoint: ["/bin/sh","-c"]
    command:
      - >-
        tail -n +1 -F /srv/logs/access.log
        | grep --line-buffered '"RequestHost":"about.rt-541.io"'
        | goaccess - --config-file=/srv/goaccess.conf
    volumes:
      - /docker/traefik/logs:/srv/logs:ro
      - /docker/goaccess/geoip:/geoip:ro
      - /docker/goaccess/report:/report
      - ./goaccess.conf:/srv/goaccess.conf:ro
    networks:
      - goaccess-internal

  goaccess-web:
    image: nginx:alpine
    container_name: goaccess-web
    restart: unless-stopped
    depends_on:
      - goaccess
    volumes:
      - /docker/goaccess/report:/usr/share/nginx/html:ro
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
    networks:
      - proxy
      - goaccess-internal
    labels:
      traefik.enable: "true"
      traefik.docker.network: proxy
      traefik.http.services.goaccess-svc.loadbalancer.server.port: "80"
      traefik.http.routers.goaccess.rule: "Host(`logs.rt-541.io`)"
      traefik.http.routers.goaccess.entrypoints: secure
      traefik.http.routers.goaccess.tls.certresolver: default
      traefik.http.routers.goaccess.middlewares: lan-only@docker
```

(Reuses the `lan-only@docker` middleware defined by the umami compose. If Traefik warns the middleware is undefined at first compose-up ordering, it resolves once umami is up; both are.)

- [ ] **Step 5: Bring it up + verify GoAccess is parsing**

Run:
```bash
cd /docker/homelab-config/nemesis/composed-apps/goaccess
sudo docker compose up -d
sleep 5
sudo docker logs goaccess --tail 20
```
Expected: GoAccess running, no "unable to parse" spam. If it reports a parse/format error, compare a real log line (`sudo tail -1 /docker/traefik/logs/access.log`) against the `log-format` in `goaccess.conf` and adjust field names/timestamp to match Traefik's actual JSON keys, then `sudo docker compose up -d` again. (Traefik's exact JSON keys for headers can be `request_User-Agent` / `request_Referer`; the timestamp field is `StartUTC` in ISO8601.)

- [ ] **Step 6: Verify the report + LAN-only access**

Generate a few hits, then check:
```bash
for i in 1 2 3; do curl -sS -o /dev/null --resolve about.rt-541.io:443:192.168.1.214 https://about.rt-541.io/; done
sleep 3
ls -l /docker/goaccess/report/index.html
```
From a LAN browser open `https://logs.rt-541.io` → the GoAccess dashboard loads with a **Geo Location** panel. From off-LAN (or `curl` with a non-LAN source), the dashboard route returns **403** (ipallowlist).

- [ ] **Step 7: Commit**

```bash
git -C /docker/homelab-config add nemesis/composed-apps/goaccess/docker-compose.yml nemesis/composed-apps/goaccess/goaccess.conf nemesis/composed-apps/goaccess/nginx.conf
git -C /docker/homelab-config commit -m "feat(goaccess): all-traffic by-region report from Traefik logs (LAN-only)"
```

---

## Task 6: Final verification + docs

**Files:**
- Create: `nemesis/composed-apps/umami/README.md` (short ops note)

- [ ] **Step 1: End-to-end check**

```bash
echo "umami:";    sudo docker ps --filter name=umami --format '{{.Names}} {{.Status}}'
echo "goaccess:"; sudo docker ps --filter name=goaccess --format '{{.Names}} {{.Status}}'
echo "DNS:";       nslookup analytics.rt-541.io 192.168.1.2 | tail -2; nslookup logs.rt-541.io 192.168.1.2 | tail -2
echo "collector public path:"; curl -sS -o /dev/null -w "%{http_code}\n" --resolve analytics.rt-541.io:443:192.168.1.214 https://analytics.rt-541.io/script.js
```
Expected: containers up, DNS → .214, `/script.js` returns `200`.

- [ ] **Step 2: Write `nemesis/composed-apps/umami/README.md`**

```markdown
# Analytics for about.rt-541.io

- **Umami** (cookieless human page-views): dashboard at https://analytics.rt-541.io (LAN-only).
  Collector (`/script.js`, `/api/send`) is public. Tag lives in about-site `BaseLayout.astro`.
  GeoIP: country built-in; set MAXMIND_LICENSE_KEY in .env for city/region.
- **GoAccess** (all-traffic by region from Traefik logs): https://logs.rt-541.io (LAN-only),
  in `../goaccess/`. Reads /docker/traefik/logs/access.log (JSON), filtered to about.rt-541.io.
- Privacy: Umami retains no raw IPs; Traefik access logs (raw IPs) rotate after 7 days
  (`/etc/logrotate.d/traefik`).
- Restart = `docker compose down` then `up -d` from the app dir.
```

- [ ] **Step 3: Commit**

```bash
git -C /docker/homelab-config add nemesis/composed-apps/umami/README.md
git -C /docker/homelab-config commit -m "docs(umami): analytics ops README"
```

---

## Self-Review notes (addressed)

- **Spec coverage:** Umami app + split routing (Task 1), DNS (Task 2), tracking tag + rebuild (Task 3), Traefik accessLog + retention (Task 4), GoAccess all-traffic + GeoIP + LAN-only (Task 5), privacy/no-cookies + verification + docs (Tasks 3,5,6). GeoIP: DB-IP for GoAccess (Task 5), Umami country built-in + optional MaxMind (Task 1/README).
- **Naming consistency:** middleware `lan-only@docker` (defined in Task 1, reused in Task 5); services `umami-svc`/`goaccess-svc`; subdomains `analytics.rt-541.io`/`logs.rt-541.io` throughout.
- **No placeholders:** the one runtime value is the Umami `WEBSITE_ID` (created in the UI in Task 3 Step 1, used in Step 2) — documented, not a TODO. The GoAccess `log-format` is given concretely with an explicit verify-and-adjust step because Traefik's exact JSON keys must be matched against live output.
```

