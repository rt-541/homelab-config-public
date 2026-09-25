---
name: build-plan
description: Design a physical build with the person and deliver a shop-drawing set they can take to the bench and the store, whether it is a cabinet, cart, workbench, shelving, a process jig (rock or soil screen, sifter, bagging station), a garage or basement layout, an electrical subpanel and circuits, a heater or dryer control chain, anything they will cut, assemble and wire themselves. Use this whenever someone wants to lay out a shop or a room, design storage or a fixture, size a circuit for tools, or asks for plans, drawings, a cut list, a parts list with prices, or a PDF for a build, even if they only say "help me design" or "figure out where things go". The deliverable is a standalone HTML drawing set plus PDF, and a 3D model through the shopcad-model skill when the build has fit questions.
---

# build-plan: shop drawing sets for physical builds

## Mental model

The deliverable is a **drawing set**, not an essay: numbered sheets a person
can take to the bench and to the lumber yard. Every number on a sheet is
one they will cut, buy or set a controller to, so the design dialogue comes
first and the drawings come from decisions, never the other way round. The
3D model (shopcad-model skill) is built from the same numbers and is the
fit check.

Worked examples ship with this plugin: `examples/rock-screen/` in this
skill (a tilt-tray jig whose sheets are generated from constants) and the
spool cabinet plan module in the shopcad-model skill's framework. Copy the
page pattern from `examples/rock-screen/page.html`.

## 1. Design dialogue (one question at a time)

If a brainstorming skill is available, use it and treat a new build as a
design task that needs approval before drawing. Ask one question per
message, prefer multiple choice, restate each answer before the next
question, and expect corrections mid-turn that change geometry. The
questions that change designs most:

1. **Where does it live?** Room, climate, floor, the wall it anchors to,
   what else must stay (a parked vehicle, a landing, a door swing). Ask for
   photos saved into the working directory; photo-sharing links are usually
   not fetchable by tools. Read the photo before drawing.
2. **What exactly does it hold?** Real object dimensions including the
   outliers. Ask for model numbers or order history; weights and amps come
   from spec sheets, not guesses.
3. **How is it reached?** Rods, cradle rails, shelves, drawers, a flip-top,
   free standing. Rows deep need a riser so the back row is visible.
4. **Which way is it oriented, and which side is which?** Left/right
   corrections move everything. Vehicles: get the models; length decides
   where the nose goes.
5. **Active or passive, and what draws power?** For a shop: EV charger,
   compressor or dust collector, heater, chargers; these size a subpanel
   feeder, the one thing that is expensive to change later.
6. **Tools on hand** for the build itself. Do not assume a table saw or
   router.
7. **Constraints the person states as a rule** go into the design as plain
   specs. If they ask that the reason not appear in the plan, keep it out
   of every published file and grep before publishing.
8. **For a process jig (screen, sifter, bagging, sorting):** what is the
   product, and does it stay on the screen or fall through; the size range
   kept; how much and over how long (an afternoon, or days beside the pile);
   and the container it ends up in. Ask for the container's rated weight,
   not just its size: a 50 lb sack and a 24 x 40 sack are different spouts.

When the person changes a spec mid-build ("use a 50 lb sack"), re-derive
every dimension it drives (spout, funnel depth, fill rule, cut list,
shopping list, copy) from the constants, then grep the page for the old
numbers before publishing.

Present the design in chat, sectioned (one per build, plus electrical and
cost), and get a yes before writing the page. Keep notes of the inventory
and decisions as they land; long sessions get interrupted.

## 2. Engineering checks to run every time

- **Humidity is absolute, not relative.** Heat lowers the RH reading without
  removing water; 10 g/m3 reads 25 percent at 35 C and 5 percent at 70 C.
  Only desiccant or venting removes water.
- **Material temperature limits.** Acrylic softens near 80 C, PC holds to
  115 C, PLA storage caps at 55 C, polyiso to 120 C, XPS is not, foam tape
  80 C, sleeve fans 70 C, ball-bearing fans 85 C.
- **Heater control chain.** Plug-in thermostat controller, SJ cord, metal
  box, a 90 C normally-closed snap disc (KSD301) in series, porcelain
  keyless holders with ceramic emitters, 14 AWG THHN, separate 12 V fan
  supply. Plug-in PTC fan heaters are the simple alternative.
- **Sealing a passive cabinet.** Shellac inside, silicone seams, gasket on
  the case edges, draw latches (magnets will not compress a gasket),
  continuous hinges, oversize holes so acrylic can move.
- **Desiccant.** 10 lb of indicating silica gel holds about 450 g of water;
  each door opening admits about 3 g; recharge at 250 F for 2 to 3 hours.
- **Rotating and swinging things.** A flip-top's swing radius is the corner
  of the hanging tool's box on the top's offset; the shaft must sit above
  radius plus shelf plus 1 in. Door swings must clear whatever parks beside
  them. Put these in the model's checks, not only on the sheet.
- **Long-handle tools hang to the floor.** A 60 in shovel on a rail at 60 in
  hits a 36 in counter; hooks go where nothing sits under them and nothing
  sweeps in front.
- **Wall-hung cases stand off the wall** by the cleat stack (1.5 in for two
  3/4 cleats); the closed depth on the sheet includes it.
- **Electrical (US, 2023 NEC base; check local amendments).** One feeder to
  a main-breaker subpanel beats fishing four circuits; 4-wire feeder,
  neutral isolated at the sub, 30 x 36 in working space; every garage
  120 V receptacle GFCI; a dedicated 20 A per stationary tool; a hardwired
  EVSE can be roughed in to a capped box before the car exists; NEC 220
  load calc with 125 percent on continuous loads and the largest motor;
  exposed runs below 8 ft in EMT; state the permit and inspection steps.
- **Heat loss and warm-up.** State watts, warm-up time and kWh per cycle.
- **Dense bulk material sets a fill rule by weight.** River rock and sand
  run about 100 lb per cubic foot, topsoil 75 to 80, mulch 20 to 30. A
  50 lb sack filled to the top with rock is 120 lb and splits, so the rule
  is a weight and a count ("3 shovels, 45 lb, about 8 in in the sack"),
  plus sacks per cubic yard (2,700 lb of rock is 60 sacks). A filled
  container is never lifted off the ground: it fills standing on a hand
  truck's nose plate and rolls away, which sets the spout height.
- **Spouts and funnels.** Spout perimeter a few inches under the sack's
  mouth perimeter so a cuff fits over it with a bungee; hopper side walls
  at 50 degrees or steeper for wet rock on plywood; the mouth an inch wider
  than the tray each side.
- **Tilting trays.** Put the pivot behind the discharge end (9 in on a
  48 in tray) so the tray's own front weight offsets the load: compute the
  handle force as a moment about the pivot, loaded and empty, and state
  both. Check the swept corner at full tilt against the receiving wall
  (rotate the corner about the pivot, compare to the wall top) and where
  the lip lands inside the mouth. Add a chain stop so it cannot pass
  vertical. Rest on rubber (hockey pucks) so it can be bounced.

## 3. The drawing set page

One self-contained HTML file with inline CSS and inline SVG drawings, no
external scripts, Google Fonts only (Barlow Condensed display, IBM Plex
Sans body, IBM Plex Mono data), light palette on `:root`, dark palette
under `prefers-color-scheme` and `[data-theme="dark"]`. Copy the head from
`examples/rock-screen/page.html`. Sheets, each
`<section class="sheet" id="sN">` with
`<header><h2>Title</h2><span class="num">Sheet N of M</span></header>`:

| Sheet | Content |
|---|---|
| 01 Design basis | Decisions, assumptions (vehicles, tools, room), the why-not callouts |
| 02 Layout or main drawings | Plan view or elevations, dimensioned in inches, placement table, clearances checked, the 3D model block |
| 03 to 05 One per build | Elevation and section SVGs, a model close-up, part-by-part lists |
| 06 Electrical (if any) | One-line SVG, load calc table, wire and device schedule, permit steps |
| 07 Cut list | Per sheet of stock, width by length, part names matching the model |
| 08 Shopping list | Store named per line, posted price and date, "not read" lines excluded from the total, allowances labelled |
| 09 Build sequence | Weekend by weekend, bench order, plus the checks the model runs |
| 10 Operating guide | Daily and seasonal routine, limits, maintenance |

Above the sheets: a title block (eyebrow, name, summary, meta grid) and a
sheet index nav; a small bar with links to the 3D model and the PDF.
Color-code assemblies (one accent per moving or fixed assembly, or
woodwork versus electrical) so a reader always knows which box a sheet is
about.

**Generate the drawings from numbers.** Do not hand-type SVG coordinates.
Keep a generator beside the plan (`sheets/<slug>/mk.py`): geometry
constants in inches at the top, a small `Draw` class (world-to-viewBox
transform, `rect`, `poly`, `line`, `circle`, `text`, `dimh`, `dimv`), one
function per figure, and the sheet copy in `sheets/<slug>/page.html` with
`{{name}}` slots it fills; it writes the published `index.html`. Moving
parts are drawn by rotating their outline about the pivot, so the at-rest
and tilted views, the clearance numbers and the text all come from one set
of constants. `examples/rock-screen/` is the worked example
(`python3 examples/rock-screen/mk.py --out <dir>`). Hand-edits to the
published HTML are lost on the next run; edit the generator.

**Drawing hygiene.** Scale per figure: 4 px per inch for a whole-rig
elevation, 8 to 10 for a part plan or section; a 560-wide viewBox with a
200 px drawing is unreadable. Put the figure title at the top-left of the
SVG and keep the viewBox tight to the drawing. Labels wider than their
boxes collide: short labels, leader lines, the rest in the figcaption.
Draw the near member last (the rail in front of the tray, the wheel in
front of the leg); a translucent fill lets hidden parts read through.

**Half-screen width is a required layout.** People read these on half a
monitor (about 720 px). Every plan page needs:
`.two` stacking at `max-width:860px`; `.block{align-content:start}` (or
stacked headings float above a gap); the title block as
`grid-template-columns:minmax(0,1fr) minmax(260px,340px)` stacking at
900 px, meta values `overflow-wrap:anywhere`; `td.m` wrapping below
860 px while `td.n` (quantities, sizes) stays `nowrap`. Two drawings that
belong side by side are two SVGs inside a `.two`, sharing one viewBox
width, never one wide SVG: split an existing pair by starting the second
SVG's viewBox at the split x.

**Look at every sheet before publishing, with the real fonts.** Build a
review copy in a temp directory: the plan with the Google Fonts link
swapped for a local `fonts.css` (fetch the css2 URL with a browser
User-Agent, download the woff2 files it names, rewrite the URLs), and one
`sN.html` per sheet that hides the title block, index and every other
sheet. Shoot each with headless Chrome (the `zenika/alpine-chrome` image
works: `--allow-file-access-from-files`, font hosts mapped to 127.0.0.1)
at 1100 wide and again at 720. Fallback fonts are wider and overstate
collisions; full-page shots taller than a few thousand px hang Chrome.
Read each image and fix before moving on.

**Prices.** The person prices against retail. Every line is a posted
listing read that day with the store named (search snippets usually carry
the price; big-box product pages often do not render for fetch). A price
you could not read is "not read" and out of the total, never a guess. If
you only have typical prices, say so in the sheet's intro.

## 4. Delivery

On first use, ask where the person keeps project pages (a static site, a
repo's docs folder, a local folder) and remember the answer. Do not
publish to a hosted chat artifact unless they ask for one.

1. **Plan directory:** `<plans>/<slug>/index.html` (the drawing set),
   `<slug>.pdf` beside it, `model/` from shopcad-model. If the site has a
   projects index or cards, add an entry with a one-paragraph summary and
   a link; follow the site's own pattern.
2. **3D model:** invoke `shopcad-model` for rooms, cabinets and anything
   with fit questions. Do it before the PDF, because its renders go on the
   sheets and its checks tend to correct a number. A single small jig whose
   drawings are generated from constants can ship without one; say so and
   offer it.
3. **Cache busting.** If the host caches static files, a re-rendered PNG
   keeps its filename and browsers show the old image. Append a content
   hash (`?v=<sha256[:8]>`) to every render, the PDF link and the viewer
   iframe `src` after each re-render, and serve HTML with `no-cache`.
4. **Branch base.** If the site deploys from a build directory that someone
   syncs by hand, it holds whatever was synced last. When an unmerged
   branch is live, cut the new branch from it (or rebase onto it) and open
   the PR against it, or the next deploy reverts that work.
5. **PDF.** Print wrapper: copy the plan page with `data-theme="light"`,
   `@page{size:letter;margin:14mm 12mm}`, hide the nav, bar and viewer,
   `.render img{max-height:4.2in;width:auto;margin:0 auto}`,
   `break-before:page` per `.sheet`, then
   `docker run --rm -v "$PWD:/work" zenika/alpine-chrome --headless --no-sandbox --disable-gpu --no-pdf-header-footer --virtual-time-budget=8000 --host-resolver-rules="MAP fonts.googleapis.com 127.0.0.1, MAP fonts.gstatic.com 127.0.0.1" --print-to-pdf=/work/<slug>.pdf file:///work/<slug>-print.html`.
   The print page is about 720 px wide, so the narrow-window rules fire on
   paper too and double the page count; the wrapper re-declares them inside
   `@media (max-width:860px)` and `(max-width:900px)` (`.two` two columns,
   the title block two columns, `td.m` nowrap). Compare the page count with
   the previous PDF, delete the wrapper, and state the page count in the
   PDF link.
6. **Verify live** (fetch the plan, the PDF and the model URLs), commit,
   and record the plan URL, revision, decisions and open items (the
   measurements or photos revision B needs).

## Checklist

1. Dialogue: place, contents, access, orientation, power, tools, stated rules, container.
2. Present the sectioned design; get a yes; note inventory and decisions.
3. Engineering checks; every limit becomes a sheet line or a model check.
4. Generate the sheets' SVGs from constants; shoot each sheet alone with real fonts at 1100 and 720 px and fix collisions.
5. Price every line from a named listing; exclude what could not be read.
6. shopcad-model for the 3D model when it has fit questions; correct sheet numbers the model disputes.
7. Branch from whatever is live; `?v=` on re-rendered assets; publish, PDF (page count unchanged by the narrow rules), verify live.
8. Commit; record URL, revision and open items.
