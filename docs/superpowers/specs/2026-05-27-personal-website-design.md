# Personal website at about.rt-541.io

**Status:** design  
**Date:** 2026-05-27  
**Owner:** rt-541 (Arthur Schneider)

## Background

A personal site for who I am and what I've built. Not framed as a job-hunt artifact: no "hire me" CTAs, no resume-download-as-hero, no positioning lines aimed at recruiters. Career arc, projects, and writing are content; identity is the spine. The Saturn theme (a tribute to the rt-541.io domain, named after a Saturn moon designation) runs through the visual language at a subtle vibe.

The site is published at `about.rt-541.io`, self-hosted in this repo behind the existing traefik reverse proxy.

## Audience

Primary: technically literate readers who land on the site directly or follow a link. They should be able to learn who I am and find what I've written or built without scanning past a sales pitch.

## Information architecture

Multi-page Astro routes. Each section gets its own URL so pages are independently shareable and the blog posts have stable slugs.

| Route | Purpose |
| --- | --- |
| `/` | Hero with name, role, short positioning sentence. Saturn mark watermark upper-right. Recent writing list + selected projects list below. Single CTA into `/about`. |
| `/about` | Long-form identity piece. Career arc 2016 → present as narrative, interests, what drives me. Heaviest Saturn theming. |
| `/experience` | Structured timeline: role, dates, scope per entry. Card or list rendering, not a resume layout. |
| `/projects` | Cards for built things: MCP safeguards, skills marketplace, redacted ADRs, self-hosted infra, side projects. |
| `/writing` | Index of blog posts, newest first, with date + title + dek. |
| `/writing/<slug>` | Individual post page. Renders Markdown/MDX from `src/content/writing/<slug>.md`. |

Header (cream) carries the brand mark and nav: `about`, `experience`, `projects`, `writing`. Footer (cream) carries social links: GitHub, LinkedIn, email.

## Visual system

### Palette

| Token | Hex | Use |
| --- | --- | --- |
| `chrome` | `#F4ECD8` | Cream — header background, footer background, accent borders, eyebrow text on slate, CTA outlines |
| `chrome-divider` | `#D7CDB5` | Cream border between header/footer and body |
| `body` | `#1C2A40` | Slate blue — page body background, brand mark on cream, nav text |
| `body-deep` | `#0F1622` | Optional deeper slate for code blocks / inset panels |
| `body-mid` | `#2A3B54` | Hairlines, Cassini Division in Saturn glyph |
| `muted` | `#4A5C77` | Secondary structural color |
| `subtle` | `#A6B3C9` | Role/metadata text on body, post dates |
| `ice` | `#DCE4EF` | Primary body text |

Single deviation from the palette is the C ring color (`#94A3B5`) inside the Saturn glyph — accepted as the cost of ring accuracy, contained inside the illustration.

### Typography

- Headings: `ui-serif, Georgia, "Times New Roman", serif`
- Body: `ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif`
- Metadata, eyebrows, section labels, code: `ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`

Letter-spacing: tight negative on display headings (`-0.015em`), wide positive on monospace metadata (`0.14em–0.24em`, uppercase).

### Layout posture

Editorial. Name leads left, content has generous left/right gutters, hero anchors on typography rather than imagery. Saturn mark renders as a watermark at the top-right of the hero only.

### Saturn mark

Two SVG symbols, rendered in three contexts:

1. **Hero watermark** — `saturn-detailed` symbol (full ring system + planet + wordmark), large (~340px), positioned upper-right of the home and section heroes, opacity `0.5`.
2. **Nav brand** — `saturn-brand` symbol (planet + single ring band, no wordmark), monochrome via `currentColor`, ~22px.
3. **Favicon** — same `saturn-brand` symbol rendered to a static SVG file in `public/favicon.svg`.

Construction inside the symbol (in render order):

```
1. Group A — translate(200,200) rotate(-22)
   - Back rings: A ring (#D2B47C, sw 7, op 0.7),
                 Cassini line (#2A3B54, sw 2, op 0.9),
                 B ring (#EBD9A8, sw 16, op 0.92),
                 C ring (#94A3B5, sw 7, op 0.5),
                 C/B hairline (#2A3B54, sw 1, op 0.55)
   - Planet:    circle r=80 fill url(#saturn-body)
                circle r=80 fill url(#saturn-bands)
                circle r=80 fill url(#saturn-shadow)
2. Wordmark — NOT in the rotated group, screen coords:
   text x=200 y=180 text-anchor=middle
        font-family monospace, font-size 20, weight 700,
        letter-spacing 4, fill #1C2A40
        content "RT-541"
3. Group B — translate(200,200) rotate(-22)
   - Front rings: same five strokes as back, sweep flag flipped
   - Cast shadow: M 95,17 A 160,36 0 0,1 160,5 stroke rgba(20,15,5,0.4) sw 14
```

Z-order rationale: back rings → planet (covers back rings inside silhouette) → wordmark (sits in front of planet, no tilt) → front rings (cross diagonally over wordmark and the planet's lower hemisphere). The wordmark intentionally reads horizontally while the rings stay tilted; the diagonal crossing is part of the mark's character.

Gradient defs:

- `saturn-body` (radial cx=38% cy=35% r=74%): `#F2E5B8` → `#D9BD7F` → `#9B7843` → `#5B4424`
- `saturn-bands` (linear top-to-bottom): alternating `rgba(90,65,25, 0–0.24)` stops at 6/16/24/36/48/58/68/80/92%
- `saturn-shadow` (radial cx=72% cy=55% r=55%): transparent → `rgba(20,15,5,0.55)` to suggest terminator on east limb

Working reference for the SVG markup: the v7 mockup produced during brainstorming, in this session's `.superpowers/brainstorm/` directory (gitignored, ephemeral). Everything that mockup contained is captured in the construction order and gradient definitions above — the spec is self-sufficient. The canonical implementation lives in `src/components/SaturnMark.astro` once built.

## Content model

Astro content collections define schemas for `writing` and `projects`.

**`src/content/writing/*.md`** frontmatter:

```yaml
title: string
slug: string               # auto-derived from filename if absent
date: Date                 # ISO YYYY-MM-DD
dek: string                # 1-sentence summary, shown in /writing index
draft: boolean             # default false; drafts excluded from index in prod build
tags: string[]             # optional
```

**`src/content/projects/*.md`** frontmatter:

```yaml
title: string
slug: string
order: number              # sort order on /projects (lower = higher)
status: 'active' | 'archived' | 'redacted'
summary: string            # 1-sentence card description
links:                     # optional
  - label: string
    href: string
```

Project entry body is rendered as the project detail (if linked from a card). For v1 a card-only view without per-project detail pages is acceptable; can add `/projects/<slug>` later if needed.

## Tech stack

- **Astro** for static site generation. Reasons: content-focused, native Markdown/MDX with typed frontmatter via content collections, ships zero JS by default, small island model if interactivity ever becomes necessary.
- **Tailwind** for styling. Configure custom palette tokens above as Tailwind theme extensions so utility classes like `bg-chrome` and `text-ice` are available.
- **MDX** enabled for blog posts that need component embeds.
- **No client-side JS** required for v1. Pages are fully static HTML/CSS.

## Repo layout

New composed-app under `composed-apps/about-site/`. The Astro project lives directly at this path (no nested project root):

```
composed-apps/about-site/
  docker-compose.yml        # nginx:alpine + traefik labels
  nginx.conf                # static file serving, gzip, cache headers, 404 → 404.html
  README.md                 # one-paragraph description + build/deploy notes
  .gitignore                # node_modules/, dist/
  astro.config.mjs          # MDX + Tailwind integrations, sitemap
  package.json
  tsconfig.json
  tailwind.config.mjs       # extends theme with palette tokens
  public/
    favicon.svg             # simplified Saturn brand mark
    og-image.png            # OpenGraph card
  src/
    components/
      SaturnMark.astro      # full detailed Saturn (hero watermark)
      SaturnBrand.astro     # simplified mark (nav)
      SiteHeader.astro
      SiteFooter.astro
      WritingListItem.astro
      ProjectCard.astro
      TimelineEntry.astro
    content/
      config.ts             # content collection schemas
      writing/              # *.md, *.mdx posts
      projects/             # *.md project entries
    layouts/
      BaseLayout.astro      # html, head, header, footer, slot
      PostLayout.astro      # writing post wrapper
    pages/
      index.astro
      about.astro
      experience.astro
      projects.astro
      writing/index.astro
      writing/[...slug].astro
    styles/
      globals.css           # Tailwind base + custom CSS variables for palette
  dist/                     # build output, gitignored, generated by `npm run build`
```

The Docker container bind-mounts `./dist/` (the host's build output) rather than baking it into the image. Keeps the image small and the iteration loop fast.

## Hosting and deployment

**docker-compose.yml** runs one service:

```yaml
services:
  about-site:
    image: nginx:alpine
    container_name: about-site
    restart: unless-stopped
    volumes:
      - ./dist:/usr/share/nginx/html:ro
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
    labels:
      - traefik.enable=true
      - traefik.http.routers.about-site.rule=Host(`about.rt-541.io`)
      - traefik.http.routers.about-site.entrypoints=websecure
      - traefik.http.routers.about-site.tls.certresolver=$CERTRESOLVER
    networks:
      - $TRAEFIK_NETWORK
```

Where `$CERTRESOLVER` and `$TRAEFIK_NETWORK` are read at implementation time from the existing pattern in `composed-apps/traefik/docker-compose.yml` and one consumer (e.g. `composed-apps/pihole/docker-compose.yml`). This is a lookup, not an open design decision — the same tokens every other consumer uses.

**Build/deploy workflow** (manual for v1, automatable later):

1. `cd composed-apps/about-site && npm install` (once, and on dependency changes)
2. `npm run build` produces `composed-apps/about-site/dist/`
3. `sudo docker compose up -d` from the same directory (first time only)
4. On subsequent content changes: rebuild with `npm run build`. nginx serves the new `dist/` on next request — no container restart needed since `dist/` is bind-mounted

DNS: wildcard `*.rt-541.io` is already in place; no DNS change required for `about.rt-541.io`.

## Accessibility

- All Saturn SVGs include `<title>` for screen readers ("Saturn glyph: planet with rings, designation RT-541").
- Nav anchors carry visible focus states (cream outline on slate, slate outline on cream).
- Color contrast minimum: AA between text and background pairings in the palette table. Verify `subtle` (`#A6B3C9`) on `body` (`#1C2A40`) hits AA — if not, reserve it for metadata only and use `ice` for any text that conveys meaning.
- Page structure uses semantic HTML (`<header>`, `<main>`, `<nav>`, `<footer>`, `<article>`, `<time>`).
- No motion in v1; no `prefers-reduced-motion` needed yet.

## Out of scope for v1

- Light-mode toggle.
- Analytics / tracking.
- Comments on posts.
- Site search.
- RSS feed (could be a quick add; defer until there's content to syndicate).
- Per-project detail pages (cards only for v1).
- Automated build/deploy via CI; manual build for v1.

## Open questions

None — this design has been fully validated through brainstorming.

## Implementation references

- Existing self-hosted-app pattern: `composed-apps/pihole/docker-compose.yml` and `composed-apps/traefik/docker-compose.yml` for the traefik label and network conventions, certresolver name, and traefik network name.
- Astro content collections docs: https://docs.astro.build/en/guides/content-collections/
- Astro + Tailwind setup: https://docs.astro.build/en/guides/integrations-guide/tailwind/
