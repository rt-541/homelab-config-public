# Deep-page i18n (translate the rest of the site)

**Status:** design
**Date:** 2026-05-28
**Owner:** rt-541 (Arthur Schneider)

## Background

The language switcher (front page + chrome) shipped in `2026-05-28-i18n-language-switcher`. This extends translation to the four remaining content pages: `/experience`, `/projects`, `/gaming`, `/maker`. Six languages as before (English default + ja, ko, zh, es, de). Translations are AI-authored; native polish later.

No new mechanism is introduced. The global apply-script in `BaseLayout` already runs on every page; this work only adds more `data-i18n`-tagged elements and more dictionary keys.

## English-source and SEO strategy

For the deep pages, the dictionary supplies the **five non-English translations** per key; the **English stays the static source** in the page markup (`.astro` files and content-collection frontmatter). The apply-script already falls back to the existing element text when a key is absent from a language (so missing or English stays visible). This keeps the static HTML English (no-JS and SEO safe) and avoids duplicating large English prose into the dictionary.

**One exception:** project-card bodies. They currently render as Markdown via `<Content />`, which the text-swap mechanism cannot translate in place. Those bodies move fully into the dictionary as plain-text strings (English included), and `ProjectCard` renders them as a plain `data-i18n` element. The single inline Markdown link in the `game-servers` body (to `/gaming`) is rendered as a separate static link beside the text, not inside the translated string.

## Key naming conventions

- Page chrome/static: `exp.*`, `projects.*`, `gaming.*`, `maker.*` (e.g. `exp.h1`, `gaming.label.atTable`).
- Per-collection entries keyed by slug: `project.<slug>.title|summary|body`, `print.<slug>.title|blurb`.
- Per data-array entries keyed by a stable `key` field added to the array: `exp.entry.<key>.role|summary`, `gaming.now.<key>.detail`.
- Shared enums: `status.active`, `status.archived`, `status.redacted`.

## Per-page coverage

### /experience
- Hero: `exp.eyebrow`, `exp.h1` ("Career timeline"), `exp.subtitle`.
- Timeline entries (`entries` array gains a `key`): translate **role** (`exp.entry.<key>.role`) and **summary** (`exp.entry.<key>.summary`). Org names and dates stay English (proper nouns / numerals).
- Skills: `exp.skills.label` (`// skills`); each category label (`exp.skill.<n>`). Skill **items** (RHEL, Docker, Ansible, …) stay English (technical terms).
- Certifications: `exp.certs.label`, `exp.certs.held`, `exp.certs.inprogress`. Cert names (RHCE, CySA+, EX294…) stay English.

### /projects
- Hero: `projects.eyebrow`, `projects.h1` ("Things I've built"), `projects.subtitle`.
- `ProjectCard` refactor: tag `title` (`project.<slug>.title`) and `summary` (`project.<slug>.summary`) with `data-i18n` (English from frontmatter). Status badge text via shared `status.<status>`. Replace `<Content />` with a plain `data-i18n="project.<slug>.body"` element whose text is sourced from the dictionary (English + five languages). Render the game-servers `/gaming` link as a static anchor beside the body.
- The `projects` collection `.md` files keep their structural frontmatter (order, status, links, image, and title/summary as the English source). Their Markdown bodies are superseded by dictionary `project.<slug>.body` strings for display.

### /gaming
- Hero: `gaming.eyebrow`, `gaming.h1` ("Games I run and play"), `gaming.subtitle`.
- Section labels: `gaming.label.runningNow`, `gaming.label.rotation`, `gaming.label.howItRuns`, `gaming.label.howToJoin`, `gaming.label.atTable`, `gaming.label.asDM`, `gaming.label.asPlayer`.
- Running-now: each entry's **detail** sentence (`gaming.now.<key>.detail`) and the join hint where it is words not an address (`whitelist via Discord` → `gaming.now.<key>.join`; the `zomboid.rt-541.io` address stays). Game names stay English.
- Rotation: the intro line (`gaming.rotation.intro`). The game list stays English.
- How-it-runs / how-to-join: each prose paragraph keyed (`gaming.howItRuns.p1`, …, `gaming.howToJoin.p1`, …). The Steam link stays; only its surrounding text translates if needed.
- D&D: the three sections' paragraphs (`gaming.atTable.p1`, `gaming.asDM.p1`, `gaming.asPlayer.p1`, `gaming.asPlayer.p2`). Proper nouns inside (Strixhaven, Aelrith Varn, Azur, Boros, MTG, the five colleges) stay as written within the translated prose.

### /maker
- Hero: `maker.eyebrow`, `maker.h1` ("3D printing"), `maker.intro`.
- `// live`: label (`maker.live.label`) and caption (`maker.live.caption`).
- `// prints`: label (`maker.prints.label`). Each print's **title** (`print.<slug>.title`) and **blurb** (`print.<slug>.blurb`) via `data-i18n` (English from frontmatter). Material and slicer settings stay English (technical).

## Kept in English (policy)

Proper and technical nouns are not translated: organization names, product/feature names, game titles, certification names, skill/tech items, `RT-541`, hostnames/addresses, the `@alphasierra6victor` handle, filament material, slicer settings, and personal names (Arthur Schneider, Azur, Aelrith Varn).

## Files

```
composed-apps/about-site/
  src/i18n/ui.ts                        # MODIFY: add deep-page keys (5 non-en per key; project bodies include en)
  src/pages/experience.astro            # MODIFY: data-i18n on hero/labels/certs; key timeline + skill arrays
  src/components/TimelineEntry.astro     # MODIFY: data-i18n on role + summary (keyed by entry)
  src/pages/projects.astro              # MODIFY: data-i18n on hero
  src/components/ProjectCard.astro       # MODIFY: data-i18n on title/summary/status; body from dictionary; static /gaming link
  src/pages/gaming.astro                # MODIFY: data-i18n on hero/labels/running-now/rotation/prose/D&D
  src/pages/maker.astro                 # MODIFY: data-i18n on hero/live/prints label
  src/components/PrintCard.astro         # MODIFY: data-i18n on title + blurb (keyed by entry)
```

## Out of scope

- Per-locale routes / translated OpenGraph (still client-side switch only).
- Translating proper/technical nouns (see policy).
- Traditional Chinese (Simplified only).
- The home/profile page and chrome (already done in the prior feature).

## Open questions

None — validated through brainstorming.

## Implementation references

- Existing dictionary + mechanism: `src/i18n/ui.ts`, the apply-script in `src/layouts/BaseLayout.astro`, and the `readout` keyed-array pattern in `src/pages/index.astro`.
- Prior i18n spec: `docs/superpowers/specs/2026-05-28-i18n-language-switcher-design.md`.
