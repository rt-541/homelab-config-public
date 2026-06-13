# Analytics for about.rt-541.io

Two complementary, privacy-friendly views of visitors **by region**:

## Umami — cookieless human page-views
- Dashboard: https://analytics.rt-541.io (**LAN-only**, login). Collector
  (`/script.js`, `/api/send`) is **public** so real visitors can report.
- Tracking tag lives in the about-site base layout
  (`../about-site/src/layouts/BaseLayout.astro`, website id
  `fc7a4f23-8d89-4a13-ac70-696cb89c903b`).
- GeoIP: **country** built-in. For region/city set `MAXMIND_LICENSE_KEY` in `.env`.
- Secrets in gitignored `.env` (see `.env.example`). Default admin was `admin`/`umami`
  on first run — change it under Settings → Profile.

## GoAccess — all-traffic by region (server-side)
- Dashboard: https://logs.rt-541.io (**LAN-only**), app in `../goaccess/`.
- Reads `/docker/traefik/logs/access.log` (Traefik JSON), filtered to
  `about.rt-541.io`, GeoIP via DB-IP Lite (`/docker/goaccess/geoip/`).
- Sees **all** requests (bots, non-JS, direct) — complements Umami's human view.

## Privacy
- Umami retains no raw IPs (cookieless, daily-rotating hash).
- Raw IPs exist only transiently in the Traefik access log, rotated after 7 days
  (`/etc/logrotate.d/traefik`). GoAccess output is aggregate.

## Ops
- Restart = `docker compose down` then `up -d` from the app dir.
- Traefik routing: `lan-only@docker` ipallowlist middleware is defined by this
  umami compose and reused by goaccess.
- Caveat: GoAccess geo uses Traefik `ClientHost`; if about.rt-541.io is
  Cloudflare-proxied, point it at the real-client-IP header for accuracy.
