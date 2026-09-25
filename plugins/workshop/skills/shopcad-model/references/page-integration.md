# Wiring the model into the site

Paths assume plans live at `public/plans/<slug>/` in the project that holds
the `cad/` tree; adjust to the site's layout.

## Plan page (`public/plans/<slug>/index.html`)

Add the CSS once, next to the other page styles:

```css
.render img{width:100%;height:auto;display:block;border:1px solid var(--rule)}
.viewer{width:100%;aspect-ratio:16/10;border:1px solid var(--rule);background:#ece8df}
.viewer iframe{width:100%;height:100%;border:0;display:block}
```

On the layout or main-drawing sheet, after the SVG figure:

```html
<div class="block">
  <h3>3D model</h3>
  <p>The same numbers build a CadQuery model. Orbit it, switch states and toggle
  components in the <a href="/plans/<slug>/model/">interactive viewer</a>; the
  checks it runs are listed on the build-sequence sheet.</p>
  <div class="viewer"><iframe src="/plans/<slug>/model/?view=iso&hide=Wall%20South,Wall%20East" loading="lazy" title="<Name> 3D model"></iframe></div>
  <div class="two">
    <figure class="fig render"><img src="model/render-iso.png" alt="..."><figcaption>...</figcaption></figure>
    <figure class="fig render"><img src="model/render-iso-nw.png" alt="..."><figcaption>...</figcaption></figure>
  </div>
</div>
```

On each build's sheet, one close-up render as a `figure.fig.render` before
the two-column detail lists. On the build-sequence sheet, a callout listing
the checks with their numbers, so the reader knows what the model verified.
In the sitebar, a link to `/plans/<slug>/model/` beside the PDF link.

## Project page or card (if the site has one)

Link the four model outputs from wherever the site lists the project:

```html
<a href="/plans/<slug>/model/">interactive viewer</a>
<a href="/plans/<slug>/model/<slug>.step">step file</a>
<a href="/plans/<slug>/model/<name>-fusion-script.zip">fusion 360 script (zip)</a>
<a href="/plans/<slug>/model/<slug>-<default-state>.glb">glb</a>
```

Two renders and a paragraph on what the model checks make a good project
page section. Add `?v=<hash>` to the render URLs if the host caches.

## PDF

The print wrapper (build-plan skill) adds `.viewer{display:none}` and
`.render img{max-height:4.2in;width:auto;margin:0 auto}` so the PNGs land on
the pages and the iframe does not. Regenerate the PDF after adding renders.

## Publishing

The model directory is static: copy `model/` and the plan page to the
host (or run the site's build and deploy). Verify with
`curl -sL -o /dev/null -w '%{http_code}'` on the viewer, one GLB, the STEP
and the PDF, and shoot the live viewer once with alpine-chrome to confirm
three.js loads from the CDN.
