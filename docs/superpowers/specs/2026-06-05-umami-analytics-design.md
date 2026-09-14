# about.rt-541.io Analytics (by Region) — Design

Date: 2026-06-05
Status: Approved (brainstorming) — pending implementation plan
Repo: `homelab-config` (per-host monorepo; about-site + new apps under `data-host/composed-apps/`)

## Goal

Privacy-friendly **aggregate** analytics for `about.rt-541.io`, showing
visitors/requests **by country/region over time**, via two complementary views:

1. **Umami** (cookieless JS) — clean **human page-views** by country (bots/non-JS
   excluded), polished dashboard + trends. No raw IPs retained.
2. **GoAccess** (server-side logs) — **all traffic** (humans, bots, non-JS, direct
   hits) by region, from the Traefik access logs + GeoIP. Raw IPs are transient
   (short log retention); the report is aggregate.

No per-person profiling. Fully self-hosted on **nemesis**.

## Architecture

Two new Docker Compose apps on nemesis, following the existing pattern
(`proxy` network + Traefik labels, like `about-site`):

### Component 1 — Umami (`data-host/composed-apps/umami/`)
- `umami` (`ghcr.io/umami-software/umami:postgresql-latest`) on `proxy` + a
  private `umami-internal` net; `umami-db` (`postgres:16-alpine`) on the internal
  net with a named volume + healthcheck.
- Traefik at **`analytics.rt-541.io`** (`secure` entrypoint, `default`
  certresolver). **Split routing:**
  - *Public collector* (high priority): `Host(analytics.rt-541.io) &&
    (Path(/script.js) || PathPrefix(/api/send))` → umami, no IP restriction.
  - *LAN-only dashboard* (catch-all): `Host(analytics.rt-541.io)` → umami +
    **ipAllowList** middleware (`192.168.1.0/24`).
- Must read the real client IP from `X-Forwarded-For` (trust the Traefik proxy)
  so GeoIP uses the visitor IP, not Traefik's.

### Component 2 — GoAccess (`data-host/composed-apps/goaccess/`)
- `goaccess` (`allinurl/goaccess`) reads the **Traefik access log** (mounted
  read-only) in real-time, with a **GeoIP mmdb** (DB-IP Lite free country DB — no
  account/license needed), writing a self-updating HTML report to a volume.
- A tiny `nginx:alpine` serves that report; Traefik exposes it **LAN-only** at
  **`logs.rt-541.io`** (ipAllowList `192.168.1.0/24`). (GoAccess real-time WS, if
  used, gets a matching LAN-only Traefik route; otherwise periodic static HTML.)
- Scope GoAccess to `about.rt-541.io` requests (filter by Host) for v1.

### Traefik change
- Enable **access logging** in `data-host/composed-apps/traefik/traefik.yml`
  (`accessLog` to a file on a shared volume, JSON or CLF; include `ClientHost`).
  Restart Traefik (down/up) to apply.
- **Log retention:** rotate the access log with short retention (≈7 days) so raw
  IPs are transient; GoAccess keeps the aggregate report.

### DNS
Add `analytics.rt-541.io → 192.168.1.214` and `logs.rt-541.io → 192.168.1.214`
to the HA Pi-holes' v6 `dns.hosts` on **dns-incomm (.3)** (sync propagates to .4).

## Tracking hook (about-site)

Add Umami's cookieless tag to the about-site's **base Astro layout head** (survives
the i18n `regen-i18n` rebuilds):

```html
<script defer src="https://analytics.rt-541.io/script.js"
        data-website-id="<WEBSITE_ID from Umami>"></script>
```

Then rebuild (`npm run build`) + `docker compose up -d` the about-site. The
`WEBSITE_ID` is generated in Umami after adding the `about.rt-541.io` website.

## Data flow

- **Umami path:** visitor → about.rt-541.io (script) → beacon to
  `analytics.rt-541.io/api/send` → Umami derives country (built-in GeoIP from the
  XFF client IP), stores cookieless aggregates in Postgres → LAN dashboard.
- **GoAccess path:** every request → Traefik logs `ClientHost` (real IP) to the
  access log → GoAccess parses it + GeoIP → aggregate region report → LAN
  dashboard at logs.rt-541.io. Raw log lines rotate out after ≈7 days.

## Privacy

- Umami: cookieless, no PII, daily-rotating salted hash; no raw IP retained.
- GoAccess: report is aggregate (country, counts, trends). Raw IPs live only in
  the Traefik access log, kept short (≈7 days) then rotated. No per-IP store.
- Both dashboards LAN-only; only the Umami collector (`/script.js`, `/api/send`)
  is public.

## GeoIP

- GoAccess: **DB-IP Lite free** country mmdb (no account). Updatable monthly.
- Umami: built-in **country** GeoIP out of the box. Finer region/city via an
  optional free **MaxMind GeoLite2** license key in the umami env (off by default).

## Secrets

`data-host/composed-apps/umami/.env` (gitignored): `POSTGRES_PASSWORD`,
`DATABASE_URL`, `APP_SECRET` (random), optional `MAXMIND_LICENSE_KEY`. Committed
`.env.example` documents the keys. GoAccess needs no secrets (free mmdb).

## Components

- Create: `data-host/composed-apps/umami/docker-compose.yml` + `.env` (gitignored) + `.env.example`
- Create: `data-host/composed-apps/goaccess/docker-compose.yml` (+ goaccess.conf, nginx.conf)
- Modify: `data-host/composed-apps/traefik/traefik.yml` (enable accessLog) + log rotation
- Modify: about-site base Astro layout/head (add the tracking tag)
- DNS: `analytics.rt-541.io`, `logs.rt-541.io` records on the Pi-holes

## Testing

1. Umami up → `analytics.rt-541.io` dashboard loads from LAN, refused off-LAN;
   `/script.js` + `/api/send` reachable publicly.
2. Create the `about.rt-541.io` website → get WEBSITE_ID → add tag → rebuild +
   redeploy about-site → visit it → a pageview with a country appears in Umami;
   confirm **no cookies** set.
3. Traefik accessLog enabled + GoAccess up → `logs.rt-541.io` shows a region
   breakdown of about.rt-541.io traffic (generate a few hits) from LAN; refused
   off-LAN. Confirm log rotation is configured.

## Scope / non-goals

- Two small self-contained apps + a Traefik tweak + a one-line site edit.
  Independently buildable; one plan with two tracks.
- Non-goals: per-visitor profiling, retaining raw IPs long-term, events/funnels
  beyond pageviews, other sites (only about.rt-541.io for now).
```

