# Maker Page (printer live cam + print gallery) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/maker` page to the about-site that live-streams the Prusa printer (click-to-load) and shows a photo gallery of prints, backed by a new go2rtc container that restreams the printer's RTSP feed to browser-playable MSE/HLS.

**Architecture:** A new `composed-apps/go2rtc/` container ingests `rtsp://192.168.1.220/live` and republishes it over HTTP (MSE/HLS) at `cam.rt-541.io` via Traefik. The about-site gets a `/maker` page that embeds that stream behind a click-to-load button and renders a `prints` content collection as an image-optimized gallery.

**Tech Stack:** go2rtc (Docker), Traefik, Pi-hole v6 API, Astro 4 content collections + `astro:assets`, Tailwind, nginx.

**Reference spec:** `docs/superpowers/specs/2026-05-28-maker-page-design.md`

---

## File structure

```
composed-apps/go2rtc/
  docker-compose.yml          # go2rtc + traefik labels (Task 1)
  go2rtc.yaml                 # one stream: printer -> rtsp (Task 1)
  README.md                   # what it is / how to add streams (Task 1)

composed-apps/about-site/
  src/content/config.ts                 # + prints collection (Task 3)
  src/content/prints/
    sample-print.md                      # sample entry (Task 4)
    images/sample.jpg                    # placeholder image (Task 4)
  src/components/PrintCard.astro         # gallery card (Task 5)
  src/components/SiteHeader.astro        # + maker nav (Task 7, modify)
  src/pages/maker.astro                  # hero + cam + gallery (Task 6)
  src/pages/index.astro                  # + /maker elsewhere link (Task 7, modify)
```

Each task ends with a commit. Part A (Tasks 1-2) is the streaming infra; Part B (Tasks 3-8) is the page.

---

## Task 1: go2rtc container

**Files:**
- Create: `composed-apps/go2rtc/go2rtc.yaml`
- Create: `composed-apps/go2rtc/docker-compose.yml`
- Create: `composed-apps/go2rtc/README.md`

- [ ] **Step 1: Create the directory**

```bash
mkdir -p /docker/nemesis-configs/composed-apps/go2rtc
cd /docker/nemesis-configs/composed-apps/go2rtc
```

- [ ] **Step 2: Write `go2rtc.yaml`**

Path: `composed-apps/go2rtc/go2rtc.yaml`

```yaml
streams:
  printer: rtsp://192.168.1.220/live

api:
  listen: ":1984"
```

- [ ] **Step 3: Write `docker-compose.yml`**

Uses the existing external `proxy` network, `secure` entrypoint, and `default` certresolver (matching `composed-apps/mealie/docker-compose.yml`).

Path: `composed-apps/go2rtc/docker-compose.yml`

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

- [ ] **Step 4: Write `README.md`**

Path: `composed-apps/go2rtc/README.md`

```markdown
# go2rtc

Restreams the Prusa printer's RTSP feed to browser-playable formats (MSE/HLS)
for embedding on about.rt-541.io/maker.

- Source: `rtsp://192.168.1.220/live` (LAN, no auth)
- Published at `cam.rt-541.io` (Traefik, TLS via default resolver)
- Stream name: `printer`
- Player: `https://cam.rt-541.io/stream.html?src=printer&mode=mse`

## Add a stream

Edit `go2rtc.yaml` under `streams:` then `sudo docker compose down && sudo docker compose up -d`.

## Note

The endpoint is public. The /maker page uses click-to-load so it does not
auto-broadcast, but anyone with the URL can watch. Add basic-auth on the
Traefik router if you need to lock it down.
```

- [ ] **Step 5: Validate compose config**

```bash
cd /docker/nemesis-configs/composed-apps/go2rtc
sudo docker compose config >/dev/null && echo "compose valid"
```

Expected: `compose valid`.

- [ ] **Step 6: Bring it up**

```bash
cd /docker/nemesis-configs/composed-apps/go2rtc
sudo docker compose up -d
sleep 4
sudo docker compose ps --format '{{.Name}} {{.Status}}'
```

Expected: `go2rtc` shows `Up`.

- [ ] **Step 7: Verify go2rtc serves and the stream is registered**

```bash
curl -sI -k --resolve cam.rt-541.io:443:127.0.0.1 https://cam.rt-541.io/ | grep -iE '^HTTP'
curl -s -k --resolve cam.rt-541.io:443:127.0.0.1 https://cam.rt-541.io/api/streams | head -c 400
```

Expected: `HTTP/2 200` and JSON listing the `printer` stream. If TLS errors with "cert not ready," wait 30s and retry (Traefik is issuing the cert via the DNS challenge). If the `printer` producer shows an error, confirm `rtsp://192.168.1.220/live` is reachable from the host; the container still serves either way.

- [ ] **Step 8: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/go2rtc/go2rtc.yaml \
        composed-apps/go2rtc/docker-compose.yml \
        composed-apps/go2rtc/README.md
git commit -m "feat(go2rtc): restream printer RTSP to MSE/HLS at cam.rt-541.io"
```

---

## Task 2: Pi-hole internal DNS for cam.rt-541.io

**Files:** none (operational; configures Pi-hole via its API).

- [ ] **Step 1: Add the local DNS record**

Pi-hole runs on the host (port 6969). Authenticate and append the host, mirroring the existing records.

```bash
PASS=$(grep ^WEBPASSWORD /docker/nemesis-configs/composed-apps/pihole/.env | cut -d= -f2- | tr -d '"')
SID=$(curl -s -X POST http://localhost:6969/api/auth -H 'Content-Type: application/json' -d "{\"password\":\"$PASS\"}" | jq -r .session.sid)
ENCODED=$(jq -rn --arg s "192.168.1.214 cam.rt-541.io" '$s|@uri')
curl -s -X PUT -H "X-FTL-SID: $SID" "http://localhost:6969/api/config/dns/hosts/$ENCODED" | jq '{error: .error}'
curl -s -X DELETE -H "X-FTL-SID: $SID" http://localhost:6969/api/auth > /dev/null
```

Expected: `{ "error": null }`.

- [ ] **Step 2: Verify resolution**

```bash
dig +short cam.rt-541.io @127.0.0.1
```

Expected: `192.168.1.214`.

No commit (Pi-hole config lives in its own data dir, not this repo).

---

## Task 3: prints content collection

**Files:**
- Modify: `composed-apps/about-site/src/content/config.ts`

- [ ] **Step 1: Add the prints collection**

Overwrite the file so it defines and exports the `prints` collection alongside the existing two:

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

const prints = defineCollection({
  type: 'content',
  schema: ({ image }) => z.object({
    title: z.string(),
    date: z.date(),
    material: z.string(),
    settings: z.string().optional(),
    blurb: z.string(),
    image: image(),
    order: z.number().default(0),
  }),
});

export const collections = { writing, projects, prints };
```

- [ ] **Step 2: Verify types regenerate**

```bash
cd /docker/nemesis-configs/composed-apps/about-site
npm run check
```

Expected: exits 0 (the `prints` collection is empty until Task 4, which is fine).

- [ ] **Step 3: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/src/content/config.ts
git commit -m "feat(about-site): prints content collection"
```

---

## Task 4: Sample print entry + placeholder image

**Files:**
- Create: `composed-apps/about-site/src/content/prints/images/sample.jpg`
- Create: `composed-apps/about-site/src/content/prints/sample-print.md`

- [ ] **Step 1: Generate a placeholder image with sharp**

sharp is already a dependency (Astro uses it). Generate an 800x600 slate-colored JPG so the build has a real image to optimize.

```bash
cd /docker/nemesis-configs/composed-apps/about-site
mkdir -p src/content/prints/images
node -e "const s=require('sharp'); s({create:{width:800,height:600,channels:3,background:'#1C2A40'}}).jpeg({quality:80}).toFile('src/content/prints/images/sample.jpg').then(i=>console.log('made',i.width+'x'+i.height)).catch(e=>{console.error(e);process.exit(1)})"
ls -la src/content/prints/images/sample.jpg
```

Expected: `made 800x600` and the file exists.

- [ ] **Step 2: Write the sample print entry**

Path: `composed-apps/about-site/src/content/prints/sample-print.md`

```markdown
---
title: "Sample print"
date: 2026-05-28
material: "PLA"
settings: "0.2mm layers, 15% gyroid"
blurb: "Placeholder. Replace with a real print: drop a photo in images/ and update these fields."
image: "./images/sample.jpg"
order: 1
---
```

- [ ] **Step 3: Build to confirm the image optimizes cleanly**

```bash
cd /docker/nemesis-configs/composed-apps/about-site
npm run build
```

Expected: build succeeds (the `prints` collection now has one entry; no page renders it yet until Task 6, but the collection and image must validate).

- [ ] **Step 4: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/src/content/prints/
git commit -m "feat(about-site): sample print entry + placeholder image"
```

---

## Task 5: PrintCard component

**Files:**
- Create: `composed-apps/about-site/src/components/PrintCard.astro`

- [ ] **Step 1: Write PrintCard**

Path: `composed-apps/about-site/src/components/PrintCard.astro`

```astro
---
import { Image } from 'astro:assets';
import type { CollectionEntry } from 'astro:content';

interface Props {
  entry: CollectionEntry<'prints'>;
}
const { entry } = Astro.props;
const { title, material, settings, blurb, image } = entry.data;
const meta = settings ? `${material} · ${settings}` : material;
---
<figure class="m-0 border border-chrome/15 rounded-lg overflow-hidden bg-body-deep">
  <Image
    src={image}
    alt={title}
    widths={[240, 480, 720]}
    sizes="(max-width: 640px) 100vw, 320px"
    class="block w-full h-auto"
  />
  <figcaption class="p-4">
    <h3 class="font-serif text-[18px] text-chrome leading-tight m-0">{title}</h3>
    <p class="font-mono text-[11px] tracking-meta text-subtle uppercase mt-1 mb-0">{meta}</p>
    <p class="text-[14px] text-ice leading-[1.6] mt-2 mb-0">{blurb}</p>
  </figcaption>
</figure>
```

- [ ] **Step 2: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/src/components/PrintCard.astro
git commit -m "feat(about-site): PrintCard gallery component"
```

---

## Task 6: The /maker page

**Files:**
- Create: `composed-apps/about-site/src/pages/maker.astro`

- [ ] **Step 1: Write the page**

Hero + click-to-load live cam + prints gallery. The cam iframe is created and inserted only on button click (via the safe `replaceChildren` DOM method), so nothing streams until the visitor opts in.

Path: `composed-apps/about-site/src/pages/maker.astro`

```astro
---
import BaseLayout from '../layouts/BaseLayout.astro';
import PrintCard from '../components/PrintCard.astro';
import { getCollection } from 'astro:content';

const prints = (await getCollection('prints'))
  .sort((a, b) => a.data.order - b.data.order || b.data.date.getTime() - a.data.date.getTime());
---
<BaseLayout title="maker &middot; rt-541.io" description="3D printing: a live printer cam and a gallery of prints.">
  <section class="max-w-3xl mx-auto px-6 pt-16 pb-8">
    <p class="font-mono text-[10px] tracking-eyebrow uppercase text-chrome opacity-85 mb-5 pb-3 border-b border-chrome/20">
      maker
    </p>
    <h1 class="font-serif text-[34px] leading-[1.1] tracking-display text-chrome mb-3">3D printing</h1>
    <p class="text-[15px] text-ice leading-[1.65] max-w-[52ch]">
      A Prusa Core One that runs more often than not. Below is a live look at whatever is on the bed right now, and a gallery of things that came off it.
    </p>
  </section>

  <section class="max-w-3xl mx-auto px-6 pt-6">
    <p class="font-mono text-[10px] tracking-eyebrow uppercase text-chrome opacity-70 mb-4">// live</p>
    <div class="cam" data-cam>
      <button type="button" class="cam-go" data-cam-go>
        <span class="cam-go-icon">&#9658;</span>
        <span>go live</span>
      </button>
    </div>
    <p class="text-[13px] text-subtle mt-3">Live feed from the workshop. Loads only when you press play, and may be dark when the printer is off.</p>
  </section>

  <section class="max-w-3xl mx-auto px-6 pt-12 pb-20">
    <p class="font-mono text-[10px] tracking-eyebrow uppercase text-chrome opacity-70 mb-4">// prints</p>
    {prints.length === 0 ? (
      <p class="text-subtle text-[14px]">No prints yet.</p>
    ) : (
      <div class="print-grid">
        {prints.map(p => <PrintCard entry={p} />)}
      </div>
    )}
  </section>
</BaseLayout>

<style>
  .cam {
    position: relative;
    aspect-ratio: 16 / 9;
    width: 100%;
    background: #0F1622;
    border: 1px solid rgba(244, 236, 216, 0.15);
    border-radius: 10px;
    overflow: hidden;
  }
  .cam :global(iframe) {
    width: 100%;
    height: 100%;
    border: 0;
    display: block;
  }
  .cam-go {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    background: transparent;
    border: 0;
    cursor: pointer;
    color: #F4ECD8;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 12px;
    letter-spacing: 0.18em;
    text-transform: uppercase;
  }
  .cam-go:hover { background: rgba(244, 236, 216, 0.05); }
  .cam-go-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 56px;
    height: 56px;
    border: 1.5px solid #F4ECD8;
    border-radius: 50%;
    font-size: 18px;
    padding-left: 4px;
  }

  .print-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 1.25rem;
  }
</style>

<script>
  const cam = document.querySelector<HTMLElement>('[data-cam]');
  const btn = document.querySelector<HTMLButtonElement>('[data-cam-go]');
  btn?.addEventListener('click', () => {
    if (!cam) return;
    const frame = document.createElement('iframe');
    frame.src = 'https://cam.rt-541.io/stream.html?src=printer&mode=mse';
    frame.setAttribute('allow', 'fullscreen');
    frame.setAttribute('allowfullscreen', 'true');
    cam.replaceChildren(frame);
  });
</script>
```

- [ ] **Step 2: Build and verify**

```bash
cd /docker/nemesis-configs/composed-apps/about-site
npm run build
test -f dist/maker/index.html && echo maker-built
grep -q '// live' dist/maker/index.html && echo cam-section
grep -q 'Sample print' dist/maker/index.html && echo gallery-rendered
echo "stream url should be absent from static HTML (injected at runtime):" && grep -c 'cam.rt-541.io' dist/maker/index.html
```

Expected: build succeeds; `maker-built`, `cam-section`, `gallery-rendered` all print; the `grep -c 'cam.rt-541.io'` count is `0` (the stream URL only exists in the bundled script, not the static markup).

- [ ] **Step 3: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/src/pages/maker.astro
git commit -m "feat(about-site): maker page with click-to-load cam and prints gallery"
```

---

## Task 7: Nav + home link

**Files:**
- Modify: `composed-apps/about-site/src/components/SiteHeader.astro`
- Modify: `composed-apps/about-site/src/pages/index.astro`

- [ ] **Step 1: Add "maker" to the nav**

In `composed-apps/about-site/src/components/SiteHeader.astro`, the `nav` array currently is:

```ts
const nav: { href: string; label: string }[] = [
  { href: '/experience', label: 'experience' },
  { href: '/projects', label: 'projects' },
  { href: '/gaming', label: 'gaming' },
];
```

Replace it with:

```ts
const nav: { href: string; label: string }[] = [
  { href: '/experience', label: 'experience' },
  { href: '/projects', label: 'projects' },
  { href: '/gaming', label: 'gaming' },
  { href: '/maker', label: 'maker' },
];
```

- [ ] **Step 2: Add a /maker link to the home "// elsewhere" list**

In `composed-apps/about-site/src/pages/index.astro`, find the "gaming" list item in the `// elsewhere` `<ul>`:

```astro
      <li class="py-3 flex justify-between">
        <span class="text-ice">gaming</span>
        <a href="/gaming" class="font-mono text-[11px] text-subtle no-underline hover:underline">/gaming &rarr;</a>
      </li>
```

Insert this new list item immediately after it:

```astro
      <li class="py-3 flex justify-between">
        <span class="text-ice">3d printing</span>
        <a href="/maker" class="font-mono text-[11px] text-subtle no-underline hover:underline">/maker &rarr;</a>
      </li>
```

- [ ] **Step 3: Build and verify**

```bash
cd /docker/nemesis-configs/composed-apps/about-site
npm run build
grep -oc 'href="/maker"' dist/index.html
```

Expected: build succeeds; the count is `2` (one in the header nav, one in the elsewhere list).

- [ ] **Step 4: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/src/components/SiteHeader.astro \
        composed-apps/about-site/src/pages/index.astro
git commit -m "feat(about-site): add maker to nav and home links"
```

---

## Task 8: Deploy and smoke test

**Files:** none (operational).

- [ ] **Step 1: Rebuild the site**

```bash
cd /docker/nemesis-configs/composed-apps/about-site
npm run build
ls dist/maker/index.html
```

Expected: file exists (nginx serves the bind-mounted `dist/`, no container restart needed).

- [ ] **Step 2: Smoke-test the routes**

```bash
for path in / /maker; do
  code=$(curl -sk -o /dev/null -w '%{http_code}' --resolve about.rt-541.io:443:127.0.0.1 "https://about.rt-541.io$path")
  echo "$code $path"
done
```

Expected:
```
200 /
200 /maker
```

- [ ] **Step 3: Confirm the cam endpoint is reachable (for the click-to-load embed)**

```bash
curl -sI -k --resolve cam.rt-541.io:443:127.0.0.1 "https://cam.rt-541.io/stream.html?src=printer" | grep -iE '^HTTP'
```

Expected: `HTTP/2 200`.

- [ ] **Step 4: Confirm clean git state under the changed app dirs**

```bash
cd /docker/nemesis-configs
git status --short composed-apps/go2rtc/ composed-apps/about-site/
```

Expected: clean (no untracked `node_modules/`, `dist/`, or `.astro/`).

No commit (deploy verification only).

---

## Self-review

**Spec coverage:**

| Spec requirement | Task |
| --- | --- |
| go2rtc container restreaming RTSP, Traefik route cam.rt-541.io | Task 1 |
| MSE/HLS playback (no WebRTC), port 1984 only | Task 1 (compose + embed `mode=mse`) |
| Pi-hole internal record cam.rt-541.io | Task 2 |
| prints content collection (astro:assets image) | Task 3 |
| Sample print + image | Task 4 |
| Gallery card | Task 5 (PrintCard) |
| /maker page: hero, click-to-load cam, gallery | Task 6 |
| Nav "maker" + home elsewhere link | Task 7 |
| Build/deploy + smoke test | Tasks 1-7 build steps + Task 8 |
| Click-to-load (no auto-stream) | Task 6 (iframe injected on click; verified absent from static HTML) |

All spec requirements are covered.

**Out-of-scope items confirmed unimplemented:** only-while-printing gating, WebRTC, stream basic-auth, multi-camera, slicer/PrusaLink metadata. None appear in any task.

**Known accepted gaps for v1:**
- The `cam.rt-541.io` endpoint (and go2rtc UI) is public; click-to-load is bandwidth/UX, not access control (per spec).
- Sample print uses a generated solid-slate placeholder image; the owner replaces it with real photos.
- Live cam playback can only be fully verified in a browser (the click handler runs client-side); the build/smoke tests confirm the endpoint serves and the page ships without auto-loading the stream.
