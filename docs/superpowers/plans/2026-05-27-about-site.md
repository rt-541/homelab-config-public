# Personal Website (about.rt-541.io) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and self-host a personal site at `about.rt-541.io` — Astro + Tailwind, multi-page IA, cream-chrome / hex-pole-body palette, custom Saturn glyph, served by an nginx container behind the existing traefik proxy.

**Architecture:** New composed-app at `composed-apps/about-site/`. The directory is BOTH the Astro project root AND the Docker Compose context. Astro builds static HTML/CSS/SVG into `./dist/`, which is bind-mounted into an `nginx:alpine` container. Traefik labels route `about.rt-541.io` to the container using the same `proxy` network and `default` cert resolver every other consumer uses.

**Tech Stack:** Astro 4.x, Tailwind CSS, MDX, TypeScript (strict), nginx:alpine, Docker Compose, Traefik (existing).

**Reference spec:** `docs/superpowers/specs/2026-05-27-personal-website-design.md`

---

## File structure

```
composed-apps/about-site/
  docker-compose.yml                 # nginx + traefik labels (Task 15)
  nginx.conf                         # static serving + try_files for 404 (Task 15)
  README.md                          # one-paragraph + build notes (Task 15)
  .gitignore                         # node_modules/, dist/ (Task 1)
  package.json                       # Astro + integrations + scripts (Task 1)
  tsconfig.json                      # Astro strict TS (Task 1)
  astro.config.mjs                   # Tailwind + MDX + sitemap (Task 1)
  tailwind.config.mjs                # palette tokens (Task 2)
  public/
    favicon.svg                      # static SaturnBrand SVG (Task 6)
    og-image.svg                     # OpenGraph card (Task 14)
  src/
    styles/
      globals.css                    # Tailwind base + CSS variables (Task 2)
    content/
      config.ts                      # writing + projects schemas (Task 3)
      writing/
        2026-05-27-hello.md          # sample post (Task 14)
      projects/
        mcp-safeguards.md            # sample project (Task 14)
    layouts/
      BaseLayout.astro               # html, head, header, footer slot (Task 4)
      PostLayout.astro               # writing post wrapper (Task 13)
    components/
      SaturnMark.astro               # detailed Saturn watermark (Task 5)
      SaturnBrand.astro              # simplified Saturn nav mark (Task 6)
      SiteHeader.astro               # cream header w/ brand + nav (Task 7)
      SiteFooter.astro               # cream footer w/ socials (Task 7)
      TimelineEntry.astro            # experience row (Task 10)
      ProjectCard.astro              # project card (Task 11)
      WritingListItem.astro          # writing index row (Task 12)
    pages/
      index.astro                    # home (Task 8)
      about.astro                    # long-form bio (Task 9)
      experience.astro               # timeline (Task 10)
      projects.astro                 # projects (Task 11)
      writing/
        index.astro                  # blog index (Task 12)
        [...slug].astro              # post detail (Task 13)
      404.astro                      # not-found page (Task 14)
```

Each task ends with a commit. Build verification (`npm run build`) after most tasks so we never accumulate broken state.

---

## Task 1: Scaffold the Astro project

**Files:**
- Create: `composed-apps/about-site/.gitignore`
- Create: `composed-apps/about-site/package.json`
- Create: `composed-apps/about-site/tsconfig.json`
- Create: `composed-apps/about-site/astro.config.mjs`
- Create: `composed-apps/about-site/src/pages/index.astro` (placeholder)

- [ ] **Step 1: Create the directory and cd into it**

```bash
mkdir -p /docker/nemesis-configs/composed-apps/about-site/src/pages
cd /docker/nemesis-configs/composed-apps/about-site
```

- [ ] **Step 2: Write `.gitignore`**

Path: `composed-apps/about-site/.gitignore`

```
node_modules/
dist/
.astro/
.DS_Store
```

- [ ] **Step 3: Write `package.json`**

Path: `composed-apps/about-site/package.json`

```json
{
  "name": "about-site",
  "type": "module",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "astro dev",
    "build": "astro build",
    "preview": "astro preview",
    "check": "astro check"
  },
  "dependencies": {
    "astro": "^4.16.0",
    "@astrojs/check": "^0.9.0",
    "@astrojs/mdx": "^3.1.0",
    "@astrojs/sitemap": "^3.2.0",
    "@astrojs/tailwind": "^5.1.0",
    "tailwindcss": "^3.4.0",
    "typescript": "^5.6.0"
  }
}
```

- [ ] **Step 4: Write `tsconfig.json`**

Path: `composed-apps/about-site/tsconfig.json`

```json
{
  "extends": "astro/tsconfigs/strict",
  "include": [".astro/types.d.ts", "**/*"],
  "exclude": ["dist"]
}
```

- [ ] **Step 5: Write `astro.config.mjs`**

Path: `composed-apps/about-site/astro.config.mjs`

```js
import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';
import mdx from '@astrojs/mdx';
import sitemap from '@astrojs/sitemap';

export default defineConfig({
  site: 'https://about.rt-541.io',
  integrations: [
    tailwind({ applyBaseStyles: false }),
    mdx(),
    sitemap(),
  ],
});
```

Note: `applyBaseStyles: false` because we'll wire Tailwind ourselves in `globals.css` (Task 2).

- [ ] **Step 6: Write a placeholder home page**

Path: `composed-apps/about-site/src/pages/index.astro`

```astro
---
---
<html>
  <head><title>about.rt-541.io</title></head>
  <body><p>placeholder — site bootstrapping</p></body>
</html>
```

- [ ] **Step 7: Install dependencies and verify the build runs**

Run from `composed-apps/about-site/`:

```bash
npm install
npm run build
```

Expected: `npm install` completes without errors. `npm run build` produces `dist/index.html` and exits 0. If the build fails, fix before continuing.

- [ ] **Step 8: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/.gitignore \
        composed-apps/about-site/package.json \
        composed-apps/about-site/package-lock.json \
        composed-apps/about-site/tsconfig.json \
        composed-apps/about-site/astro.config.mjs \
        composed-apps/about-site/src/pages/index.astro
git commit -m "chore(about-site): scaffold Astro project"
```

---

## Task 2: Wire Tailwind with the palette tokens

**Files:**
- Create: `composed-apps/about-site/tailwind.config.mjs`
- Create: `composed-apps/about-site/src/styles/globals.css`

- [ ] **Step 1: Write `tailwind.config.mjs`**

Path: `composed-apps/about-site/tailwind.config.mjs`

```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{astro,html,js,ts,jsx,tsx,md,mdx}'],
  theme: {
    extend: {
      colors: {
        chrome: '#F4ECD8',
        'chrome-divider': '#D7CDB5',
        body: '#1C2A40',
        'body-deep': '#0F1622',
        'body-mid': '#2A3B54',
        muted: '#4A5C77',
        subtle: '#A6B3C9',
        ice: '#DCE4EF',
      },
      fontFamily: {
        serif: ['ui-serif', 'Georgia', '"Times New Roman"', 'serif'],
        sans: ['ui-sans-serif', 'system-ui', '-apple-system', '"Segoe UI"', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      letterSpacing: {
        'display': '-0.015em',
        'meta': '0.14em',
        'eyebrow': '0.24em',
      },
    },
  },
  plugins: [],
};
```

- [ ] **Step 2: Write `globals.css`**

Path: `composed-apps/about-site/src/styles/globals.css`

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  html {
    background: #1C2A40;
    color: #DCE4EF;
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    -webkit-font-smoothing: antialiased;
    text-rendering: optimizeLegibility;
  }
  body {
    margin: 0;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }
  main {
    flex: 1;
  }
  h1, h2, h3, h4 {
    font-family: ui-serif, Georgia, "Times New Roman", serif;
    color: #F4ECD8;
    letter-spacing: -0.015em;
  }
  a {
    color: inherit;
  }
  a:focus-visible {
    outline: 1.5px solid currentColor;
    outline-offset: 3px;
  }
}

/* Typography for rendered Markdown content (blog posts, project descriptions). */
/* Applied via a wrapper class on the rendered <Content /> output. */
.prose-content {
  --prose-fg: #DCE4EF;
  --prose-heading: #F4ECD8;
  --prose-link: #F4ECD8;
}
.prose-content p { margin: 0 0 1.25em; line-height: 1.75; color: var(--prose-fg); }
.prose-content h2 { margin: 2em 0 0.75em; font-size: 1.5rem; line-height: 1.25; color: var(--prose-heading); }
.prose-content h3 { margin: 1.6em 0 0.6em; font-size: 1.2rem; color: var(--prose-heading); }
.prose-content ul, .prose-content ol { margin: 0 0 1.25em; padding-left: 1.5em; }
.prose-content li { margin: 0.25em 0; line-height: 1.7; }
.prose-content a { text-decoration: underline; text-underline-offset: 3px; color: var(--prose-link); }
.prose-content code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.9em;
  padding: 1px 6px;
  border-radius: 3px;
  background: rgba(244, 236, 216, 0.08);
  color: #F4ECD8;
}
.prose-content pre {
  background: #0F1622;
  border: 1px solid rgba(244, 236, 216, 0.1);
  border-radius: 6px;
  padding: 1em;
  overflow-x: auto;
  margin: 0 0 1.25em;
}
.prose-content pre code { padding: 0; background: transparent; }
.prose-content blockquote {
  margin: 0 0 1.25em;
  padding-left: 1em;
  border-left: 2px solid rgba(244, 236, 216, 0.3);
  color: #A6B3C9;
}
```

- [ ] **Step 3: Verify build still works**

Run from `composed-apps/about-site/`:

```bash
npm run build
```

Expected: build succeeds. (The placeholder page doesn't yet import globals.css; we'll wire that up via BaseLayout in Task 4.)

- [ ] **Step 4: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/tailwind.config.mjs \
        composed-apps/about-site/src/styles/globals.css
git commit -m "chore(about-site): tailwind config + global styles"
```

---

## Task 3: Content collection schemas

**Files:**
- Create: `composed-apps/about-site/src/content/config.ts`

- [ ] **Step 1: Write the collection schemas**

Path: `composed-apps/about-site/src/content/config.ts`

```ts
import { defineCollection, z } from 'astro:content';

const writing = defineCollection({
  type: 'content',
  schema: z.object({
    title: z.string(),
    date: z.date(),
    dek: z.string(),
    draft: z.boolean().default(false),
    tags: z.array(z.string()).default([]),
  }),
});

const projects = defineCollection({
  type: 'content',
  schema: z.object({
    title: z.string(),
    order: z.number(),
    status: z.enum(['active', 'archived', 'redacted']),
    summary: z.string(),
    links: z
      .array(z.object({ label: z.string(), href: z.string().url() }))
      .default([]),
  }),
});

export const collections = { writing, projects };
```

- [ ] **Step 2: Create empty content directories so getCollection doesn't error**

```bash
mkdir -p /docker/nemesis-configs/composed-apps/about-site/src/content/writing
mkdir -p /docker/nemesis-configs/composed-apps/about-site/src/content/projects
touch /docker/nemesis-configs/composed-apps/about-site/src/content/writing/.gitkeep
touch /docker/nemesis-configs/composed-apps/about-site/src/content/projects/.gitkeep
```

- [ ] **Step 3: Verify type generation**

Run from `composed-apps/about-site/`:

```bash
npm run check
```

Expected: `astro check` exits 0 (or only reports diagnostics for the placeholder page, which is fine). Content collection types should regenerate without errors.

- [ ] **Step 4: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/src/content/
git commit -m "feat(about-site): content collection schemas for writing and projects"
```

---

## Task 4: BaseLayout

**Files:**
- Create: `composed-apps/about-site/src/layouts/BaseLayout.astro`
- Modify: `composed-apps/about-site/src/pages/index.astro` (use the layout)

- [ ] **Step 1: Write BaseLayout**

Path: `composed-apps/about-site/src/layouts/BaseLayout.astro`

```astro
---
import '../styles/globals.css';

interface Props {
  title?: string;
  description?: string;
}

const { title = 'about.rt-541.io', description = 'Personal site of Arthur Schneider' } = Astro.props;
---
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="description" content={description} />
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <title>{title}</title>
  </head>
  <body>
    <slot name="header" />
    <main>
      <slot />
    </main>
    <slot name="footer" />
  </body>
</html>
```

- [ ] **Step 2: Update the placeholder index to use BaseLayout**

Path: `composed-apps/about-site/src/pages/index.astro`

```astro
---
import BaseLayout from '../layouts/BaseLayout.astro';
---
<BaseLayout title="about.rt-541.io">
  <p class="p-8 text-ice">placeholder — site bootstrapping</p>
</BaseLayout>
```

- [ ] **Step 3: Verify the build and Tailwind utility classes work**

Run from `composed-apps/about-site/`:

```bash
npm run build
grep -q 'class="p-8 text-ice"' dist/index.html && echo OK
test -f dist/_astro/*.css && echo CSS-emitted
```

Expected: build succeeds, `OK` and `CSS-emitted` both print. The CSS file in `dist/_astro/` should contain Tailwind utility output.

- [ ] **Step 4: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/src/layouts/BaseLayout.astro \
        composed-apps/about-site/src/pages/index.astro
git commit -m "feat(about-site): BaseLayout with header/footer slots"
```

---

## Task 5: SaturnMark component (detailed)

**Files:**
- Create: `composed-apps/about-site/src/components/SaturnMark.astro`

- [ ] **Step 1: Write the SaturnMark component**

Path: `composed-apps/about-site/src/components/SaturnMark.astro`

This is the full detailed Saturn glyph from the spec — back rings + planet + level wordmark + front rings + cast shadow. The wordmark sits at `y=180` and does NOT rotate with the rings.

```astro
---
interface Props {
  class?: string;
  opacity?: number;
}
const { class: className = '', opacity = 1 } = Astro.props;
---
<svg
  viewBox="0 0 400 400"
  class={className}
  style={`opacity: ${opacity}`}
  role="img"
  aria-labelledby="saturn-title saturn-desc"
>
  <title id="saturn-title">Saturn glyph</title>
  <desc id="saturn-desc">A ringed planet with the designation RT-541 inscribed across its body.</desc>
  <defs>
    <radialGradient id="saturn-body" cx="38%" cy="35%" r="74%">
      <stop offset="0%"   stop-color="#F2E5B8" />
      <stop offset="42%"  stop-color="#D9BD7F" />
      <stop offset="78%"  stop-color="#9B7843" />
      <stop offset="100%" stop-color="#5B4424" />
    </radialGradient>
    <linearGradient id="saturn-bands" x1="0" y1="0" x2="0" y2="1">
      <stop offset="6%"  stop-color="rgba(90,65,25,0)" />
      <stop offset="16%" stop-color="rgba(90,65,25,0.22)" />
      <stop offset="24%" stop-color="rgba(90,65,25,0)" />
      <stop offset="36%" stop-color="rgba(90,65,25,0.12)" />
      <stop offset="48%" stop-color="rgba(90,65,25,0)" />
      <stop offset="58%" stop-color="rgba(90,65,25,0.18)" />
      <stop offset="68%" stop-color="rgba(90,65,25,0)" />
      <stop offset="80%" stop-color="rgba(90,65,25,0.24)" />
      <stop offset="92%" stop-color="rgba(90,65,25,0.1)" />
    </linearGradient>
    <radialGradient id="saturn-shadow" cx="72%" cy="55%" r="55%">
      <stop offset="0%"   stop-color="rgba(20,15,5,0)" />
      <stop offset="55%"  stop-color="rgba(20,15,5,0)" />
      <stop offset="100%" stop-color="rgba(20,15,5,0.55)" />
    </radialGradient>
  </defs>

  <!-- Back rings + planet (tilted -22deg) -->
  <g transform="translate(200,200) rotate(-22)">
    <path d="M -178,0 A 178,40 0 0,1 178,0" stroke="#D2B47C" stroke-width="7"  fill="none" opacity="0.7" />
    <path d="M -165,0 A 165,37 0 0,1 165,0" stroke="#2A3B54" stroke-width="2"  fill="none" opacity="0.9" />
    <path d="M -150,0 A 150,33 0 0,1 150,0" stroke="#EBD9A8" stroke-width="16" fill="none" opacity="0.92" />
    <path d="M -124,0 A 124,27 0 0,1 124,0" stroke="#94A3B5" stroke-width="7"  fill="none" opacity="0.5" />
    <path d="M -134,0 A 134,30 0 0,1 134,0" stroke="#2A3B54" stroke-width="1"  fill="none" opacity="0.55" />
    <circle cx="0" cy="0" r="80" fill="url(#saturn-body)" />
    <circle cx="0" cy="0" r="80" fill="url(#saturn-bands)" />
    <circle cx="0" cy="0" r="80" fill="url(#saturn-shadow)" />
  </g>

  <!-- Wordmark: level (no rotation), screen-space coords -->
  <text
    x="200"
    y="180"
    text-anchor="middle"
    font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    font-size="20"
    font-weight="700"
    letter-spacing="4"
    fill="#1C2A40"
  >RT-541</text>

  <!-- Front rings + cast shadow (tilted -22deg) -->
  <g transform="translate(200,200) rotate(-22)">
    <path d="M -178,0 A 178,40 0 0,0 178,0" stroke="#D2B47C" stroke-width="7"  fill="none" opacity="0.7" />
    <path d="M -165,0 A 165,37 0 0,0 165,0" stroke="#2A3B54" stroke-width="2"  fill="none" opacity="0.9" />
    <path d="M -150,0 A 150,33 0 0,0 150,0" stroke="#EBD9A8" stroke-width="16" fill="none" opacity="0.92" />
    <path d="M -124,0 A 124,27 0 0,0 124,0" stroke="#94A3B5" stroke-width="7"  fill="none" opacity="0.5" />
    <path d="M -134,0 A 134,30 0 0,0 134,0" stroke="#2A3B54" stroke-width="1"  fill="none" opacity="0.55" />
    <path d="M 95,17 A 160,36 0 0,1 160,5" stroke="rgba(20,15,5,0.4)" stroke-width="14" fill="none" />
  </g>
</svg>
```

- [ ] **Step 2: Smoke-test the component by dropping it onto the placeholder page**

Path: `composed-apps/about-site/src/pages/index.astro`

```astro
---
import BaseLayout from '../layouts/BaseLayout.astro';
import SaturnMark from '../components/SaturnMark.astro';
---
<BaseLayout title="about.rt-541.io">
  <div class="p-8">
    <SaturnMark class="w-80 h-80" />
  </div>
</BaseLayout>
```

- [ ] **Step 3: Build and verify the SVG renders**

```bash
npm run build
grep -q '<text x="200" y="180"' dist/index.html && echo wordmark-present
grep -q 'rotate(-22)' dist/index.html && echo rings-tilted
```

Expected: build succeeds; both echo lines print.

- [ ] **Step 4: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/src/components/SaturnMark.astro \
        composed-apps/about-site/src/pages/index.astro
git commit -m "feat(about-site): SaturnMark component with rings, planet, RT-541 wordmark"
```

---

## Task 6: SaturnBrand component + favicon

**Files:**
- Create: `composed-apps/about-site/src/components/SaturnBrand.astro`
- Create: `composed-apps/about-site/public/favicon.svg`

- [ ] **Step 1: Write SaturnBrand**

Path: `composed-apps/about-site/src/components/SaturnBrand.astro`

Simplified mark — planet + single ring band, monochrome via `currentColor`. Used in the nav.

```astro
---
interface Props {
  class?: string;
  size?: number;
}
const { class: className = '', size = 22 } = Astro.props;
---
<svg
  viewBox="0 0 60 60"
  width={size}
  height={size}
  class={className}
  role="img"
  aria-label="RT-541"
>
  <g transform="translate(30,30) rotate(-22)">
    <path d="M -26,0 A 26,7 0 0,1 26,0" stroke="currentColor" stroke-width="2.5" fill="none" />
    <circle cx="0" cy="0" r="11" fill="currentColor" />
    <path d="M -26,0 A 26,7 0 0,0 26,0" stroke="currentColor" stroke-width="2.5" fill="none" />
  </g>
</svg>
```

- [ ] **Step 2: Write the static favicon (same glyph, hard-coded slate color)**

Path: `composed-apps/about-site/public/favicon.svg`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 60">
  <g transform="translate(30,30) rotate(-22)" fill="#1C2A40" stroke="#1C2A40">
    <path d="M -26,0 A 26,7 0 0,1 26,0" stroke-width="2.5" fill="none"/>
    <circle cx="0" cy="0" r="11"/>
    <path d="M -26,0 A 26,7 0 0,0 26,0" stroke-width="2.5" fill="none"/>
  </g>
</svg>
```

- [ ] **Step 3: Build and verify**

```bash
npm run build
test -f dist/favicon.svg && echo favicon-copied
```

Expected: build succeeds, `favicon-copied` prints.

- [ ] **Step 4: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/src/components/SaturnBrand.astro \
        composed-apps/about-site/public/favicon.svg
git commit -m "feat(about-site): SaturnBrand component + favicon"
```

---

## Task 7: SiteHeader and SiteFooter

**Files:**
- Create: `composed-apps/about-site/src/components/SiteHeader.astro`
- Create: `composed-apps/about-site/src/components/SiteFooter.astro`
- Modify: `composed-apps/about-site/src/layouts/BaseLayout.astro` (default-slot the header/footer)

- [ ] **Step 1: Write SiteHeader**

Path: `composed-apps/about-site/src/components/SiteHeader.astro`

Cream background, brand mark on left, nav on right. The current route gets an underline. Astro exposes `Astro.url.pathname`.

```astro
---
import SaturnBrand from './SaturnBrand.astro';

const path = Astro.url.pathname;
const isActive = (href: string) =>
  href === '/' ? path === '/' : path === href || path.startsWith(href + '/');

const nav: { href: string; label: string }[] = [
  { href: '/about', label: 'about' },
  { href: '/experience', label: 'experience' },
  { href: '/projects', label: 'projects' },
  { href: '/writing', label: 'writing' },
];
---
<header class="bg-chrome text-body border-b border-chrome-divider">
  <div class="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
    <a href="/" class="flex items-center gap-2 font-serif font-semibold text-[15px] text-body no-underline">
      <SaturnBrand class="text-body" />
      <span>rt-541</span>
    </a>
    <nav class="flex gap-5 font-mono text-[11px] tracking-meta uppercase">
      {nav.map(item => (
        <a
          href={item.href}
          class:list={[
            'no-underline pb-0.5',
            isActive(item.href) ? 'border-b-2 border-body' : 'opacity-65 hover:opacity-100',
          ]}
        >{item.label}</a>
      ))}
    </nav>
  </div>
</header>
```

- [ ] **Step 2: Write SiteFooter**

Path: `composed-apps/about-site/src/components/SiteFooter.astro`

```astro
---
const social: { label: string; href: string }[] = [
  { label: 'github', href: 'https://github.com/rt-541' },
  { label: 'linkedin', href: 'https://www.linkedin.com/in/arthur-schneider' },
  { label: 'email', href: 'mailto:hi@rt-541.io' },
];
---
<footer class="bg-chrome text-body border-t border-chrome-divider mt-16">
  <div class="max-w-5xl mx-auto px-6 py-5 flex items-center justify-between text-[11px] font-mono">
    <span class="tracking-meta text-muted">rt-541.io &middot; built &amp; hosted on bare metal in Michigan</span>
    <div class="flex gap-5 tracking-meta uppercase">
      {social.map(item => (
        <a href={item.href} class="no-underline hover:underline">{item.label}</a>
      ))}
    </div>
  </div>
</footer>
```

Note: The social hrefs are placeholders the user will update. Keep them as-is for v1 launch; the user will adjust before deploying.

- [ ] **Step 3: Update BaseLayout to render header and footer directly (drop the slot pattern)**

Path: `composed-apps/about-site/src/layouts/BaseLayout.astro`

```astro
---
import '../styles/globals.css';
import SiteHeader from '../components/SiteHeader.astro';
import SiteFooter from '../components/SiteFooter.astro';

interface Props {
  title?: string;
  description?: string;
}

const { title = 'about.rt-541.io', description = 'Personal site of Arthur Schneider' } = Astro.props;
---
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="description" content={description} />
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <title>{title}</title>
  </head>
  <body>
    <SiteHeader />
    <main>
      <slot />
    </main>
    <SiteFooter />
  </body>
</html>
```

- [ ] **Step 4: Build and verify**

```bash
npm run build
grep -q 'class="bg-chrome' dist/index.html && echo header-rendered
grep -q 'rt-541.io' dist/index.html && echo footer-rendered
```

Expected: build succeeds, both echo lines print.

- [ ] **Step 5: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/src/components/SiteHeader.astro \
        composed-apps/about-site/src/components/SiteFooter.astro \
        composed-apps/about-site/src/layouts/BaseLayout.astro
git commit -m "feat(about-site): SiteHeader and SiteFooter components"
```

---

## Task 8: Home page (`/`)

**Files:**
- Modify: `composed-apps/about-site/src/pages/index.astro`

- [ ] **Step 1: Write the full home page**

Editorial hero — name leads left, Saturn watermark in upper-right at opacity 0.5. Below the hero: recent writing list, selected projects list, CTA into `/about`.

Path: `composed-apps/about-site/src/pages/index.astro`

```astro
---
import BaseLayout from '../layouts/BaseLayout.astro';
import SaturnMark from '../components/SaturnMark.astro';
import { getCollection } from 'astro:content';

const writing = (await getCollection('writing', ({ data }) => !data.draft))
  .sort((a, b) => b.data.date.getTime() - a.data.date.getTime())
  .slice(0, 3);

const projects = (await getCollection('projects'))
  .filter(p => p.data.status !== 'archived')
  .sort((a, b) => a.data.order - b.data.order)
  .slice(0, 3);
---
<BaseLayout>
  <section class="relative overflow-hidden max-w-5xl mx-auto px-6 pt-16 pb-20">
    <div class="absolute -right-16 -top-6 w-[340px] h-[340px] pointer-events-none">
      <SaturnMark class="w-full h-full" opacity={0.5} />
    </div>
    <div class="relative max-w-[52ch]">
      <p class="font-mono text-[10px] tracking-eyebrow uppercase text-chrome opacity-85 mb-5 pb-3 border-b border-chrome/20">
        observatory log &middot; entry 001
      </p>
      <h1 class="font-serif text-[40px] leading-[1.05] tracking-display text-chrome mb-2">Arthur Schneider</h1>
      <p class="text-[14px] text-subtle mb-6">Platform engineer &middot; AI infrastructure</p>
      <p class="text-[15px] leading-[1.65] text-ice mb-8">
        Nine years across Linux, security, and platform work. Lately: governance for AI agents that have to run in real production. Currently in Michigan.
      </p>
      <a
        href="/about"
        class="inline-block px-5 py-2.5 border border-chrome text-chrome rounded-full text-[11px] tracking-meta uppercase no-underline hover:bg-chrome hover:text-body transition-colors"
      >read more &rarr;</a>
    </div>
  </section>

  <section class="max-w-5xl mx-auto px-6 mb-16">
    <p class="font-mono text-[10px] tracking-eyebrow uppercase text-chrome opacity-70 mb-3">// recent writing</p>
    {writing.length === 0 ? (
      <p class="text-subtle text-[14px]">No posts yet.</p>
    ) : (
      <ul class="divide-y divide-chrome/10">
        {writing.map(post => (
          <li class="py-3 flex justify-between text-[14px]">
            <a href={`/writing/${post.slug}`} class="text-ice no-underline hover:underline">{post.data.title}</a>
            <time class="font-mono text-[11px] text-subtle" datetime={post.data.date.toISOString()}>
              {post.data.date.toISOString().slice(0,7).replace('-', '.')}
            </time>
          </li>
        ))}
      </ul>
    )}
  </section>

  <section class="max-w-5xl mx-auto px-6 mb-16">
    <p class="font-mono text-[10px] tracking-eyebrow uppercase text-chrome opacity-70 mb-3">// selected projects</p>
    {projects.length === 0 ? (
      <p class="text-subtle text-[14px]">No projects yet.</p>
    ) : (
      <ul class="divide-y divide-chrome/10">
        {projects.map(p => (
          <li class="py-3 flex justify-between text-[14px]">
            <span class="text-ice">{p.data.title}</span>
            <span class="font-mono text-[11px] text-subtle">{p.data.status}</span>
          </li>
        ))}
      </ul>
    )}
  </section>
</BaseLayout>
```

- [ ] **Step 2: Build and verify**

```bash
npm run build
grep -q 'observatory log' dist/index.html && echo eyebrow-rendered
grep -q 'Arthur Schneider' dist/index.html && echo name-rendered
```

Expected: build succeeds. Both echo lines print. `dist/index.html` should also contain the inline SaturnMark SVG.

- [ ] **Step 3: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/src/pages/index.astro
git commit -m "feat(about-site): home page with hero, recent writing, selected projects"
```

---

## Task 9: About page (`/about`)

**Files:**
- Create: `composed-apps/about-site/src/pages/about.astro`

- [ ] **Step 1: Write the about page**

Long-form identity piece. Sample content uses the user's career arc framed as narrative (NOT a resume). The user will edit this content before going live.

Path: `composed-apps/about-site/src/pages/about.astro`

```astro
---
import BaseLayout from '../layouts/BaseLayout.astro';
import SaturnMark from '../components/SaturnMark.astro';
---
<BaseLayout title="about &middot; rt-541.io" description="Who Arthur Schneider is.">
  <section class="relative overflow-hidden max-w-5xl mx-auto px-6 pt-16 pb-12">
    <div class="absolute -right-16 -top-6 w-[280px] h-[280px] pointer-events-none">
      <SaturnMark class="w-full h-full" opacity={0.4} />
    </div>
    <div class="relative max-w-[52ch]">
      <p class="font-mono text-[10px] tracking-eyebrow uppercase text-chrome opacity-85 mb-5 pb-3 border-b border-chrome/20">
        about
      </p>
      <h1 class="font-serif text-[34px] leading-[1.1] tracking-display text-chrome mb-6">Who I am</h1>
    </div>
  </section>

  <article class="max-w-2xl mx-auto px-6 pb-20">
    <p class="text-[16px] leading-[1.75] text-ice mb-5">
      Sample bio paragraph. Replace this with your own narrative. The structure here gives you room for three to five paragraphs without imposing a resume shape on the content.
    </p>
    <p class="text-[16px] leading-[1.75] text-ice mb-5">
      Sample paragraph two. Career arc, what you're interested in, what you're working on lately. Free-form.
    </p>
    <p class="text-[16px] leading-[1.75] text-ice mb-5">
      Sample paragraph three. Anything that doesn't fit the timeline or projects sections.
    </p>

    <p class="font-mono text-[10px] tracking-eyebrow uppercase text-chrome opacity-70 mt-12 mb-3">// elsewhere</p>
    <ul class="divide-y divide-chrome/10 text-[14px]">
      <li class="py-3 flex justify-between">
        <span class="text-ice">writing</span>
        <a href="/writing" class="font-mono text-[11px] text-subtle no-underline hover:underline">/writing &rarr;</a>
      </li>
      <li class="py-3 flex justify-between">
        <span class="text-ice">things I've built</span>
        <a href="/projects" class="font-mono text-[11px] text-subtle no-underline hover:underline">/projects &rarr;</a>
      </li>
      <li class="py-3 flex justify-between">
        <span class="text-ice">career timeline</span>
        <a href="/experience" class="font-mono text-[11px] text-subtle no-underline hover:underline">/experience &rarr;</a>
      </li>
    </ul>
  </article>
</BaseLayout>
```

- [ ] **Step 2: Build and verify**

```bash
npm run build
test -f dist/about/index.html && echo about-built
grep -q 'Who I am' dist/about/index.html && echo h1-rendered
```

Expected: build succeeds, both echo lines print.

- [ ] **Step 3: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/src/pages/about.astro
git commit -m "feat(about-site): about page"
```

---

## Task 10: Experience page (`/experience`) + TimelineEntry

**Files:**
- Create: `composed-apps/about-site/src/components/TimelineEntry.astro`
- Create: `composed-apps/about-site/src/pages/experience.astro`

- [ ] **Step 1: Write TimelineEntry**

Path: `composed-apps/about-site/src/components/TimelineEntry.astro`

```astro
---
interface Props {
  role: string;
  org: string;
  start: string;       // 'YYYY-MM' or 'YYYY'
  end?: string;        // omit / 'present'
  summary: string;
}
const { role, org, start, end = 'present', summary } = Astro.props;
---
<li class="py-6 border-b border-chrome/10 grid grid-cols-[7rem,1fr] gap-6">
  <time class="font-mono text-[11px] tracking-meta text-subtle pt-1">
    {start} &mdash; {end}
  </time>
  <div>
    <h3 class="font-serif text-[20px] text-chrome leading-tight">{role}</h3>
    <p class="font-mono text-[11px] tracking-meta text-subtle uppercase mt-1">{org}</p>
    <p class="text-[15px] text-ice leading-[1.65] mt-3">{summary}</p>
  </div>
</li>
```

- [ ] **Step 2: Write the experience page**

The entries are sample data — replace with the user's actual roles. The shape is what matters.

Path: `composed-apps/about-site/src/pages/experience.astro`

```astro
---
import BaseLayout from '../layouts/BaseLayout.astro';
import TimelineEntry from '../components/TimelineEntry.astro';

const entries: { role: string; org: string; start: string; end?: string; summary: string }[] = [
  {
    role: 'Sample role',
    org: 'Sample org',
    start: '2025',
    summary: 'One-paragraph summary of what you did in this role. Replace with real entries before launch.',
  },
  {
    role: 'Earlier role',
    org: 'Earlier org',
    start: '2020',
    end: '2024',
    summary: 'Another sample summary. The page renders entries in declaration order — newest first.',
  },
];
---
<BaseLayout title="experience &middot; rt-541.io" description="Career timeline.">
  <section class="max-w-3xl mx-auto px-6 pt-16 pb-8">
    <p class="font-mono text-[10px] tracking-eyebrow uppercase text-chrome opacity-85 mb-5 pb-3 border-b border-chrome/20">
      experience
    </p>
    <h1 class="font-serif text-[34px] leading-[1.1] tracking-display text-chrome mb-2">Career timeline</h1>
    <p class="text-[14px] text-subtle">Roles, in reverse-chronological order.</p>
  </section>

  <ul class="max-w-3xl mx-auto px-6 pb-20 list-none p-0">
    {entries.map(e => <TimelineEntry {...e} />)}
  </ul>
</BaseLayout>
```

- [ ] **Step 3: Build and verify**

```bash
npm run build
test -f dist/experience/index.html && echo experience-built
grep -q 'Career timeline' dist/experience/index.html && echo h1-rendered
```

Expected: build succeeds, both echo lines print.

- [ ] **Step 4: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/src/components/TimelineEntry.astro \
        composed-apps/about-site/src/pages/experience.astro
git commit -m "feat(about-site): experience page + TimelineEntry"
```

---

## Task 11: Projects page (`/projects`) + ProjectCard

**Files:**
- Create: `composed-apps/about-site/src/components/ProjectCard.astro`
- Create: `composed-apps/about-site/src/pages/projects.astro`

- [ ] **Step 1: Write ProjectCard**

Renders one card from a project content entry. The body of the markdown file becomes the rendered description; frontmatter drives title/status/links.

Path: `composed-apps/about-site/src/components/ProjectCard.astro`

```astro
---
import type { CollectionEntry } from 'astro:content';
interface Props {
  entry: CollectionEntry<'projects'>;
}
const { entry } = Astro.props;
const { Content } = await entry.render();
const { title, status, summary, links } = entry.data;
---
<article class="py-6 border-b border-chrome/10">
  <header class="flex justify-between items-baseline gap-4 mb-2">
    <h3 class="font-serif text-[20px] text-chrome leading-tight m-0">{title}</h3>
    <span class:list={[
      'font-mono text-[10px] tracking-meta uppercase shrink-0',
      status === 'active' ? 'text-chrome' : status === 'archived' ? 'text-subtle' : 'text-muted'
    ]}>{status}</span>
  </header>
  <p class="text-[15px] text-ice leading-[1.65] mb-3">{summary}</p>
  <div class="prose-content text-[14px]">
    <Content />
  </div>
  {links.length > 0 && (
    <ul class="flex gap-4 mt-3 list-none p-0 font-mono text-[11px] tracking-meta uppercase">
      {links.map(l => (
        <li><a href={l.href} class="text-chrome no-underline hover:underline">{l.label} &rarr;</a></li>
      ))}
    </ul>
  )}
</article>
```

- [ ] **Step 2: Write the projects page**

Path: `composed-apps/about-site/src/pages/projects.astro`

```astro
---
import BaseLayout from '../layouts/BaseLayout.astro';
import ProjectCard from '../components/ProjectCard.astro';
import { getCollection } from 'astro:content';

const projects = (await getCollection('projects'))
  .sort((a, b) => a.data.order - b.data.order);
---
<BaseLayout title="projects &middot; rt-541.io" description="Things I've built.">
  <section class="max-w-3xl mx-auto px-6 pt-16 pb-8">
    <p class="font-mono text-[10px] tracking-eyebrow uppercase text-chrome opacity-85 mb-5 pb-3 border-b border-chrome/20">
      projects
    </p>
    <h1 class="font-serif text-[34px] leading-[1.1] tracking-display text-chrome mb-2">Things I've built</h1>
    <p class="text-[14px] text-subtle">A grab-bag of work and side projects. Click through for details.</p>
  </section>

  <div class="max-w-3xl mx-auto px-6 pb-20">
    {projects.length === 0 ? (
      <p class="text-subtle text-[14px]">No projects yet.</p>
    ) : (
      projects.map(p => <ProjectCard entry={p} />)
    )}
  </div>
</BaseLayout>
```

- [ ] **Step 3: Build and verify (still empty content; page should still render)**

```bash
npm run build
test -f dist/projects/index.html && echo projects-built
grep -q "Things I've built" dist/projects/index.html && echo h1-rendered
grep -q 'No projects yet' dist/projects/index.html && echo empty-state-shown
```

Expected: build succeeds, all three echo lines print.

- [ ] **Step 4: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/src/components/ProjectCard.astro \
        composed-apps/about-site/src/pages/projects.astro
git commit -m "feat(about-site): projects page + ProjectCard"
```

---

## Task 12: Writing index (`/writing`) + WritingListItem

**Files:**
- Create: `composed-apps/about-site/src/components/WritingListItem.astro`
- Create: `composed-apps/about-site/src/pages/writing/index.astro`

- [ ] **Step 1: Write WritingListItem**

Path: `composed-apps/about-site/src/components/WritingListItem.astro`

```astro
---
import type { CollectionEntry } from 'astro:content';
interface Props {
  entry: CollectionEntry<'writing'>;
}
const { entry } = Astro.props;
const { title, date, dek } = entry.data;
---
<li class="py-6 border-b border-chrome/10">
  <a href={`/writing/${entry.slug}`} class="block no-underline group">
    <div class="flex justify-between items-baseline gap-4 mb-1">
      <h3 class="font-serif text-[20px] text-chrome leading-tight m-0 group-hover:underline">{title}</h3>
      <time class="font-mono text-[11px] tracking-meta text-subtle shrink-0" datetime={date.toISOString()}>
        {date.toISOString().slice(0,10)}
      </time>
    </div>
    <p class="text-[14px] text-ice leading-[1.6] m-0">{dek}</p>
  </a>
</li>
```

- [ ] **Step 2: Write the writing index page**

Path: `composed-apps/about-site/src/pages/writing/index.astro`

```astro
---
import BaseLayout from '../../layouts/BaseLayout.astro';
import WritingListItem from '../../components/WritingListItem.astro';
import { getCollection } from 'astro:content';

const posts = (await getCollection('writing', ({ data }) => !data.draft))
  .sort((a, b) => b.data.date.getTime() - a.data.date.getTime());
---
<BaseLayout title="writing &middot; rt-541.io" description="Long-form notes and posts.">
  <section class="max-w-3xl mx-auto px-6 pt-16 pb-8">
    <p class="font-mono text-[10px] tracking-eyebrow uppercase text-chrome opacity-85 mb-5 pb-3 border-b border-chrome/20">
      writing
    </p>
    <h1 class="font-serif text-[34px] leading-[1.1] tracking-display text-chrome mb-2">Long-form notes</h1>
    <p class="text-[14px] text-subtle">Newest first.</p>
  </section>

  <ul class="max-w-3xl mx-auto px-6 pb-20 list-none p-0">
    {posts.length === 0 ? (
      <p class="text-subtle text-[14px]">No posts yet.</p>
    ) : (
      posts.map(p => <WritingListItem entry={p} />)
    )}
  </ul>
</BaseLayout>
```

- [ ] **Step 3: Build and verify**

```bash
npm run build
test -f dist/writing/index.html && echo writing-index-built
grep -q 'Long-form notes' dist/writing/index.html && echo h1-rendered
grep -q 'No posts yet' dist/writing/index.html && echo empty-state-shown
```

Expected: build succeeds, all three echo lines print.

- [ ] **Step 4: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/src/components/WritingListItem.astro \
        composed-apps/about-site/src/pages/writing/index.astro
git commit -m "feat(about-site): writing index + WritingListItem"
```

---

## Task 13: Writing post detail (`/writing/<slug>`) + PostLayout

**Files:**
- Create: `composed-apps/about-site/src/layouts/PostLayout.astro`
- Create: `composed-apps/about-site/src/pages/writing/[...slug].astro`

- [ ] **Step 1: Write PostLayout**

Path: `composed-apps/about-site/src/layouts/PostLayout.astro`

```astro
---
import BaseLayout from './BaseLayout.astro';
interface Props {
  title: string;
  date: Date;
  dek: string;
}
const { title, date, dek } = Astro.props;
---
<BaseLayout title={`${title} | rt-541.io`} description={dek}>
  <article class="max-w-2xl mx-auto px-6 pt-16 pb-20">
    <p class="font-mono text-[10px] tracking-eyebrow uppercase text-chrome opacity-85 mb-5 pb-3 border-b border-chrome/20">
      <a href="/writing" class="no-underline hover:underline">&larr; writing</a>
    </p>
    <header class="mb-8">
      <h1 class="font-serif text-[36px] leading-[1.1] tracking-display text-chrome mb-3">{title}</h1>
      <p class="text-[15px] text-ice leading-[1.6] mb-3">{dek}</p>
      <time class="font-mono text-[11px] tracking-meta text-subtle" datetime={date.toISOString()}>
        {date.toISOString().slice(0,10)}
      </time>
    </header>
    <div class="prose-content text-[16px]">
      <slot />
    </div>
  </article>
</BaseLayout>
```

- [ ] **Step 2: Write the post detail page (dynamic route)**

Path: `composed-apps/about-site/src/pages/writing/[...slug].astro`

```astro
---
import { getCollection, type CollectionEntry } from 'astro:content';
import PostLayout from '../../layouts/PostLayout.astro';

export async function getStaticPaths() {
  const posts = await getCollection('writing', ({ data }) => !data.draft);
  return posts.map(post => ({
    params: { slug: post.slug },
    props: { post },
  }));
}

interface Props {
  post: CollectionEntry<'writing'>;
}
const { post } = Astro.props;
const { Content } = await post.render();
---
<PostLayout title={post.data.title} date={post.data.date} dek={post.data.dek}>
  <Content />
</PostLayout>
```

- [ ] **Step 3: Build and verify (still no posts, so no post pages emit yet — just confirm build doesn't break)**

```bash
npm run build
```

Expected: build succeeds. Zero post pages emit; that's fine — we add a sample post in Task 14.

- [ ] **Step 4: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/src/layouts/PostLayout.astro \
        composed-apps/about-site/src/pages/writing/\[...slug\].astro
git commit -m "feat(about-site): post detail page + PostLayout"
```

---

## Task 14: Sample content + 404 page + og-image

**Files:**
- Create: `composed-apps/about-site/src/content/writing/2026-05-27-hello.md`
- Create: `composed-apps/about-site/src/content/projects/mcp-safeguards.md`
- Create: `composed-apps/about-site/src/pages/404.astro`
- Create: `composed-apps/about-site/public/og-image.svg`
- Modify: `composed-apps/about-site/src/layouts/BaseLayout.astro` (add OpenGraph tags)

- [ ] **Step 1: Sample writing post**

Path: `composed-apps/about-site/src/content/writing/2026-05-27-hello.md`

```markdown
---
title: "Hello from rt-541.io"
date: 2026-05-27
dek: "Why I built this site, and what to expect here."
---

This is the first post. The site you're reading is statically generated by Astro and served by a small nginx container behind traefik on a server in Michigan.

Replace this post with something real once the structure is verified end-to-end.

## A second heading

The Markdown is rendered with Astro's default content pipeline. MDX is enabled, so component embeds work in `.mdx` files.

- bullet one
- bullet two
- bullet three
```

- [ ] **Step 2: Sample project entry**

Path: `composed-apps/about-site/src/content/projects/mcp-safeguards.md`

```markdown
---
title: "Sample project"
order: 1
status: active
summary: "Replace this with a real one-line description of one of your projects."
links:
  - label: "github"
    href: "https://github.com/example/sample"
---

Longer-form notes about this project. The card on `/projects` renders this body below the summary.

Replace this content with a real project before launch.
```

- [ ] **Step 3: 404 page**

Path: `composed-apps/about-site/src/pages/404.astro`

```astro
---
import BaseLayout from '../layouts/BaseLayout.astro';
import SaturnMark from '../components/SaturnMark.astro';
---
<BaseLayout title="not found &middot; rt-541.io" description="Page not found.">
  <section class="relative overflow-hidden max-w-3xl mx-auto px-6 pt-24 pb-24 text-center">
    <div class="mx-auto w-[220px] h-[220px] mb-8">
      <SaturnMark class="w-full h-full" opacity={0.6} />
    </div>
    <p class="font-mono text-[10px] tracking-eyebrow uppercase text-chrome opacity-85 mb-3">404</p>
    <h1 class="font-serif text-[34px] leading-[1.1] tracking-display text-chrome mb-3">Out of orbit</h1>
    <p class="text-[15px] text-ice leading-[1.65] max-w-md mx-auto mb-8">
      That path isn't on the map. Try the nav above, or head back home.
    </p>
    <a href="/" class="inline-block px-5 py-2.5 border border-chrome text-chrome rounded-full text-[11px] tracking-meta uppercase no-underline hover:bg-chrome hover:text-body transition-colors">
      home &rarr;
    </a>
  </section>
</BaseLayout>
```

- [ ] **Step 4: OpenGraph image (simple SVG card)**

Path: `composed-apps/about-site/public/og-image.svg`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630">
  <rect width="1200" height="630" fill="#1C2A40"/>
  <g transform="translate(950,315) rotate(-22)" opacity="0.5">
    <path d="M -178,0 A 178,40 0 0,1 178,0" stroke="#D2B47C" stroke-width="7" fill="none"/>
    <path d="M -150,0 A 150,33 0 0,1 150,0" stroke="#EBD9A8" stroke-width="16" fill="none" opacity="0.9"/>
    <path d="M -124,0 A 124,27 0 0,1 124,0" stroke="#94A3B5" stroke-width="7" fill="none" opacity="0.5"/>
    <circle cx="0" cy="0" r="80" fill="#D9BD7F"/>
    <path d="M -178,0 A 178,40 0 0,0 178,0" stroke="#D2B47C" stroke-width="7" fill="none"/>
    <path d="M -150,0 A 150,33 0 0,0 150,0" stroke="#EBD9A8" stroke-width="16" fill="none" opacity="0.9"/>
    <path d="M -124,0 A 124,27 0 0,0 124,0" stroke="#94A3B5" stroke-width="7" fill="none" opacity="0.5"/>
  </g>
  <text x="80" y="280" font-family="Georgia, serif" font-size="64" font-weight="600" fill="#F4ECD8">Arthur Schneider</text>
  <text x="80" y="335" font-family="ui-sans-serif, sans-serif" font-size="26" fill="#A6B3C9">Platform engineer · AI infrastructure</text>
  <text x="80" y="540" font-family="ui-monospace, monospace" font-size="20" fill="#F4ECD8" letter-spacing="4">ABOUT.RT-541.IO</text>
</svg>
```

- [ ] **Step 5: Add OpenGraph + Twitter meta to BaseLayout**

Path: `composed-apps/about-site/src/layouts/BaseLayout.astro`

Replace the entire file with:

```astro
---
import '../styles/globals.css';
import SiteHeader from '../components/SiteHeader.astro';
import SiteFooter from '../components/SiteFooter.astro';

interface Props {
  title?: string;
  description?: string;
}

const { title = 'about.rt-541.io', description = 'Personal site of Arthur Schneider' } = Astro.props;
const canonical = new URL(Astro.url.pathname, Astro.site);
const ogImage = new URL('/og-image.svg', Astro.site);
---
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="description" content={description} />
    <link rel="canonical" href={canonical.toString()} />
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />

    <meta property="og:type" content="website" />
    <meta property="og:url" content={canonical.toString()} />
    <meta property="og:title" content={title} />
    <meta property="og:description" content={description} />
    <meta property="og:image" content={ogImage.toString()} />

    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content={title} />
    <meta name="twitter:description" content={description} />
    <meta name="twitter:image" content={ogImage.toString()} />

    <title>{title}</title>
  </head>
  <body>
    <SiteHeader />
    <main>
      <slot />
    </main>
    <SiteFooter />
  </body>
</html>
```

- [ ] **Step 6: Build and verify**

```bash
npm run build
test -f dist/writing/2026-05-27-hello/index.html && echo post-emitted
test -f dist/404.html && echo 404-emitted
test -f dist/og-image.svg && echo og-copied
grep -q 'og:image' dist/index.html && echo og-meta-present
```

Expected: build succeeds, all four echo lines print. The post slug `2026-05-27-hello` is derived by Astro from the filename — if you change the filename or add a `slug:` to the post frontmatter, update this grep accordingly.

- [ ] **Step 7: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/src/content/writing/2026-05-27-hello.md \
        composed-apps/about-site/src/content/projects/mcp-safeguards.md \
        composed-apps/about-site/src/pages/404.astro \
        composed-apps/about-site/public/og-image.svg \
        composed-apps/about-site/src/layouts/BaseLayout.astro
git commit -m "feat(about-site): sample content, 404 page, og-image, social meta"
```

---

## Task 15: nginx.conf, docker-compose.yml, README

**Files:**
- Create: `composed-apps/about-site/nginx.conf`
- Create: `composed-apps/about-site/docker-compose.yml`
- Create: `composed-apps/about-site/README.md`

- [ ] **Step 1: Write `nginx.conf`**

Path: `composed-apps/about-site/nginx.conf`

```nginx
server {
  listen 80;
  server_name _;
  root /usr/share/nginx/html;
  index index.html;

  # gzip
  gzip on;
  gzip_types text/plain text/css application/javascript application/json image/svg+xml;
  gzip_min_length 256;

  # Long cache for hashed assets
  location /_astro/ {
    expires 1y;
    add_header Cache-Control "public, immutable";
  }

  # Default cache for everything else
  location / {
    try_files $uri $uri/ $uri.html =404;
    expires 1h;
    add_header Cache-Control "public, must-revalidate";
  }

  # Custom 404 page from Astro's prerendered 404.html
  error_page 404 /404.html;
  location = /404.html {
    internal;
  }
}
```

- [ ] **Step 2: Write `docker-compose.yml`**

Uses the existing `proxy` network and `default` cert resolver to match the pattern in `composed-apps/mealie/docker-compose.yml`.

Path: `composed-apps/about-site/docker-compose.yml`

```yaml
---
networks:
  proxy:
    external: true

services:
  about-site:
    image: nginx:alpine
    container_name: about-site
    restart: unless-stopped
    networks:
      - proxy
    volumes:
      - ./dist:/usr/share/nginx/html:ro
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
    labels:
      traefik.enable: true
      traefik.http.routers.about-site.rule: Host(`about.rt-541.io`)
      traefik.http.routers.about-site.entrypoints: secure
      traefik.http.routers.about-site.tls.certresolver: default
      traefik.http.services.about-site.loadbalancer.server.port: 80
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 128M
        reservations:
          cpus: '0.1'
          memory: 32M
```

- [ ] **Step 3: Write `README.md`**

Path: `composed-apps/about-site/README.md`

```markdown
# about-site

Personal site at `about.rt-541.io`. Astro + Tailwind static build, served by nginx behind traefik.

## Local development

```bash
npm install
npm run dev          # http://localhost:4321
```

## Build

```bash
npm run build        # outputs to ./dist/
npm run preview      # preview the built site
```

## Deploy

The Docker container bind-mounts `./dist/`, so:

```bash
npm run build
sudo docker compose up -d      # first time
# subsequent deploys: rebuild only — nginx serves new dist on next request
npm run build
```

Traefik routes `about.rt-541.io` to the container on the `proxy` network with the `default` cert resolver.

## Content

- Writing: `src/content/writing/*.md` — frontmatter schema in `src/content/config.ts`
- Projects: `src/content/projects/*.md` — frontmatter schema in `src/content/config.ts`

## Spec

`docs/superpowers/specs/2026-05-27-personal-website-design.md`
```

- [ ] **Step 4: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/nginx.conf \
        composed-apps/about-site/docker-compose.yml \
        composed-apps/about-site/README.md
git commit -m "feat(about-site): nginx + docker-compose + README"
```

---

## Task 16: First deploy and smoke test

**Files:** none modified (operational task)

- [ ] **Step 1: Confirm `dist/` exists with a fresh build**

```bash
cd /docker/nemesis-configs/composed-apps/about-site
npm run build
ls dist/index.html
```

Expected: `dist/index.html` exists.

- [ ] **Step 2: Bring the container up**

```bash
cd /docker/nemesis-configs/composed-apps/about-site
sudo docker compose up -d
sudo docker compose ps
```

Expected: `about-site` container shows `Up` status. If it's not, run `sudo docker compose logs about-site` and resolve.

- [ ] **Step 3: Verify traefik picked up the route**

```bash
sudo docker exec traefik wget -qO- 'http://127.0.0.1:8080/api/http/routers' | grep -o 'about-site[^"]*' | head -3
```

Expected: at least one match showing `about-site@docker`.

- [ ] **Step 4: Curl the site via traefik (https from another host or local with --resolve)**

From any host on the network:

```bash
curl -sI https://about.rt-541.io | head -5
```

Or from the server itself (resolving locally):

```bash
curl -sI --resolve about.rt-541.io:443:127.0.0.1 https://about.rt-541.io | head -5
```

Expected: `HTTP/2 200`. Headers include `content-type: text/html`.

- [ ] **Step 5: Spot-check pages**

```bash
for path in / /about /experience /projects /writing /writing/2026-05-27-hello /not-a-real-page; do
  code=$(curl -sk -o /dev/null -w '%{http_code}' --resolve about.rt-541.io:443:127.0.0.1 "https://about.rt-541.io$path")
  echo "$code $path"
done
```

Expected:
```
200 /
200 /about
200 /experience
200 /projects
200 /writing
200 /writing/2026-05-27-hello
404 /not-a-real-page
```

The 404 response should serve the custom `/404.html` body (nginx `error_page 404 /404.html`).

- [ ] **Step 6: No commit needed for the deploy itself, but verify nothing crept into git**

```bash
cd /docker/nemesis-configs
git status composed-apps/about-site/
```

Expected: clean working tree under `composed-apps/about-site/` (no untracked `node_modules/` or `dist/` — both should be gitignored).

---

## Self-review

**Spec coverage:**

| Spec section | Implemented in |
| --- | --- |
| Information architecture (6 routes) | Tasks 8–13 |
| Palette tokens | Task 2 |
| Typography | Task 2 |
| Saturn mark — detailed + brand + favicon | Tasks 5, 6 |
| Wordmark at y=180, level | Task 5 step 1 |
| Content schemas (writing, projects) | Task 3 |
| BaseLayout + meta | Tasks 4, 14 |
| Header + footer (cream chrome) | Task 7 |
| Accessibility (focus states, semantic HTML, SVG title) | Tasks 2, 5, 7 |
| nginx.conf, docker-compose, traefik labels | Task 15 |
| Build workflow + smoke test | Tasks 1–14 build steps + Task 16 |
| 404 page | Task 14 |
| OpenGraph + favicon | Tasks 6, 14 |

All spec sections are covered.

**Out-of-scope items confirmed unimplemented:** light-mode toggle, analytics, comments, search, RSS, per-project detail routes, CI/CD. These are intentionally not in any task.

**Known accepted gaps for v1:**
- Social links in `SiteFooter` are placeholder values the user will personalize before launch (called out in Task 7).
- Sample content in writing/projects/experience is placeholder text the user replaces with real content.
- Slug for the sample post matches Astro's default filename-derived slug; if a custom slug is added to frontmatter, the smoke-test path in Task 16 step 5 needs to follow.

These are content gaps, not implementation gaps — the site renders correctly with the placeholders.
