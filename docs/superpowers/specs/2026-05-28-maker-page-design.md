# Maker page: live printer cam + 3D-print gallery

**Status:** design
**Date:** 2026-05-28
**Owner:** rt-541 (Arthur Schneider)

## Background

A third content page on the about-site at `/maker`, covering 3D printing. Two halves: a live video feed of the Prusa Core One mid-print, and a photo gallery of finished prints. The printer exposes an RTSP stream on the LAN (`rtsp://192.168.1.220/live`); RTSP cannot play in a browser, so it must be restreamed into a browser-playable format.

This is one cohesive feature with two coupled parts: a streaming sidecar (new composed-app) and the page that embeds it (on the existing about-site).

## Part 1: Streaming infra (`composed-apps/go2rtc/`)

A new composed-app running **go2rtc** (lightweight RTSP restreamer with a built-in auto-fallback web player).

### Why go2rtc

Purpose-built for exactly this (ingest RTSP, republish as WebRTC/MSE/HLS/MJPEG), single small binary/container, ships its own embeddable player. Chosen over MediaMTX (heavier) and a DIY ffmpeg→HLS pipeline (brittle, manual segment management).

### Playback target: MSE, with HLS fallback

The page plays the stream via **MSE** (Media Source Extensions over a WebSocket) as primary, **HLS** as fallback. Both ride plain HTTPS through Traefik with no UDP, so they reverse-proxy cleanly. Latency ~1-2s (MSE) to ~5-10s (HLS), which is fine for watching a slow print. **WebRTC is deliberately not used** — its UDP/ICE/TURN requirements make public exposure painful and sub-second latency is not needed here.

### Container

`composed-apps/go2rtc/docker-compose.yml`:

```yaml
---
networks:
  proxy:
    external: true

services:
  go2rtc:
    image: alexxit/go2rtc:latest
    container_name: go2rtc
    restart: unless-stopped
    networks:
      - proxy
    volumes:
      - ./go2rtc.yaml:/config/go2rtc.yaml:ro
    labels:
      traefik.enable: true
      traefik.http.routers.go2rtc.rule: Host(`cam.rt-541.io`)
      traefik.http.routers.go2rtc.entrypoints: secure
      traefik.http.routers.go2rtc.tls.certresolver: default
      traefik.http.services.go2rtc.loadbalancer.server.port: 1984
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 256M
        reservations:
          cpus: '0.1'
          memory: 64M
```

Only port 1984 (HTTP API + player + MSE WebSocket + HLS) is proxied. WebRTC ports (8555) are intentionally not exposed since WebRTC is unused. Traefik must pass through WebSocket upgrades (default behavior) for MSE.

`composed-apps/go2rtc/go2rtc.yaml`:

```yaml
streams:
  printer: rtsp://192.168.1.220/live

api:
  listen: ":1984"
```

The WebRTC port (8555) is simply left unexposed, and the page embeds with `mode=mse` so the player never attempts WebRTC, so there is no need to disable it in config.

The RTSP URL is a LAN address with no credentials, so it lives in the config file in plain text (not a secret). If the camera later requires auth, the `rtsp://user:pass@...` form moves into this file, which should then be gitignored or sourced from env.

### DNS

`cam.rt-541.io` is already covered by the public wildcard `*.rt-541.io` → 68.48.142.234. Add a Pi-hole local record `cam.rt-541.io` → 192.168.1.214 for internal resolution (same pattern as the other services), via the Pi-hole v6 API at `http://localhost:6969/api`.

### Privacy and bandwidth (explicitly accepted)

- The `cam.rt-541.io` endpoint is **publicly reachable**. Click-to-load on the page (Part 2) prevents auto-broadcast to every page visitor and saves upload bandwidth, but it is a UX/bandwidth measure, **not access control** — anyone with the URL can watch 24/7. Locking the endpoint down would require basic-auth on the go2rtc router (out of scope for v1, noted as a future option).
- go2rtc's own web UI/API is reachable at `cam.rt-541.io` too. Acceptable for v1 (it is just a restreamer); a future hardening step could basic-auth everything except the specific stream embed path.
- Each viewer consumes home upload bandwidth. go2rtc shares the single RTSP source among consumers, but outbound is per-viewer. Fine for low-traffic personal use.

## Part 2: The `/maker` page (about-site)

### Route and nav

New route `src/pages/maker.astro`. Nav label "maker" added to `SiteHeader` (→ experience · projects · gaming · maker). The home page "// elsewhere" list gets a `/maker` link.

### Page structure

- **Hero** — eyebrow "maker", h1 "3D printing", a one-paragraph intro. Matches the cream-chrome / slate-body palette and mono section labels used site-wide.
- **// live** — a **click-to-load** player. Renders a placeholder panel (poster + "go live" button). A small inline script sets an `<iframe>` src to `https://cam.rt-541.io/stream.html?src=printer&mode=mse` only on click, so nothing streams until the visitor opts in. A short caption notes it is a live feed of the printer and may be offline when the printer is idle.
- **// prints** — a responsive photo gallery driven by a new `prints` content collection, rendered as cards (optimized image + caption: title, material, settings, blurb).

### `prints` content collection

Add to `src/content/config.ts`:

```ts
const prints = defineCollection({
  type: 'content',
  schema: ({ image }) => z.object({
    title: z.string(),
    date: z.date(),
    material: z.string(),            // e.g. "PLA", "PETG"
    settings: z.string().optional(), // e.g. "0.2mm, 15% gyroid"
    blurb: z.string(),               // one-line caption
    image: image(),                  // optimized via astro:assets
    order: z.number().default(0),    // gallery sort, lower first
  }),
});
```

Register it alongside `writing` and `projects` in the `collections` export. Print photos are co-located with the entries (e.g. `src/content/prints/<slug>.md` referencing `./images/<file>.jpg`) so Astro's `astro:assets` optimizes them (responsive sizes, modern formats, lazy loading). This avoids shipping raw multi-MB phone photos.

### Gallery rendering

A `PrintCard.astro` component renders one entry: `<Image>` (from `astro:assets`) plus a caption block (title, material · settings, blurb). The page maps the collection (sorted by `order` then `date` desc) into a responsive CSS grid (e.g. `repeat(auto-fill, minmax(240px, 1fr))`).

### Sample content

One sample print entry with a placeholder image so the gallery renders at launch, clearly marked for replacement. (If no real photo is ready, a small placeholder image is committed under the collection's images dir.)

## Repo layout

```
composed-apps/go2rtc/
  docker-compose.yml          # go2rtc + traefik labels
  go2rtc.yaml                 # one stream: printer -> rtsp://192.168.1.220/live
  README.md                   # what it is, how to add streams

composed-apps/about-site/
  src/content/config.ts       # + prints collection
  src/content/prints/
    <sample>.md               # sample print entry
    images/<sample>.jpg       # co-located, optimized by astro:assets
  src/components/
    PrintCard.astro           # gallery card
    SiteHeader.astro          # + maker nav item (modify)
  src/pages/
    maker.astro               # hero + live cam (click-to-load) + prints gallery
    index.astro               # + /maker link in "// elsewhere" (modify)
```

## Deployment

1. **go2rtc:** `cd composed-apps/go2rtc && sudo docker compose up -d`. Verify `cam.rt-541.io` serves the go2rtc UI and the `printer` stream plays.
2. **Pi-hole:** add the `cam.rt-541.io` → 192.168.1.214 local record via the API.
3. **about-site:** `npm run build` (Astro optimizes the gallery images), nginx serves the new `dist/` (bind-mounted, no container restart needed).

## Smoke test

- `cam.rt-541.io` returns the go2rtc player; the `printer` stream renders video.
- `https://about.rt-541.io/maker` returns 200, shows the placeholder (no auto-stream), and clicking "go live" starts the feed.
- The prints gallery renders the sample card with an optimized image.
- Nav shows "maker"; home "// elsewhere" links to it.

## Out of scope for v1

- Only-while-printing gating (needs PrusaLink/Connect status integration).
- WebRTC low-latency playback.
- Basic-auth / private gating of the stream endpoint.
- Multiple cameras.
- Pulling print metadata automatically from the slicer or PrusaLink.

## Open questions

None — validated through brainstorming.

## Implementation references

- Existing Traefik consumer pattern: `composed-apps/mealie/docker-compose.yml` (proxy network, `secure` entrypoint, `default` certresolver, colon-style labels).
- Apex/redirect + about-site routing precedent: `composed-apps/about-site/docker-compose.yml`.
- Astro content collections + images: https://docs.astro.build/en/guides/images/#images-in-content-collections
- go2rtc: https://github.com/AlexxIT/go2rtc
