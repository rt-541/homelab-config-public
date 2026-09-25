---
name: shopcad-model
description: Build a headless 3D CAD model of a physical build (cabinet, cart, workbench, shelving, a whole shop or room layout) with the shopcad framework bundled in this skill, and get back an interactive web viewer, per-build STEP files, PNG renders for the drawing set, and a Fusion 360 script, all from one Python scene module whose parameters are the drawing-set numbers. Use this whenever a build plan needs a 3D model, mockup, render, STEP, GLB, viewer, "show it in 3D", a fit check (does the cart clear the shelf, does the truck fit), or when someone mentions CadQuery, Fusion scripting, or "3dcad python"; also use it to revise an existing plan model when a dimension changes. Pairs with the build-plan skill, which owns the drawing set the model feeds.
---

# shopcad-model: headless CAD for build plans

## What you are producing

One plan module, `cad/plans/<slug>.py`, that describes the build with
inch-unit boxes and cylinders, plus the outputs `cad/run.sh` makes from it in
`public/plans/<slug>/model/`:

- `<slug>-<state>.glb` per state, and `index.html`, the three.js viewer
- `<slug>.step` for the scene and `<slug>-<component>.step` per build
- `render-<view>.png` for the sheets and the PDF
- `<name>-fusion-script.zip`, a Fusion 360 script with user parameters
- `model.json`, the manifest the viewer and the page read

The framework ships in this skill at `framework/` (`shopcad/`, `run.sh`,
`README.md`, and a worked plan, `plans/spool_cabinet.py`: a cabinet with
swinging doors, shelves and checks). Install it once into the project that
holds the plan pages with `python3 scripts/new_plan.py --init <project>`,
which copies it to `<project>/cad/`; `run.sh` writes to
`<project>/public/plans/<slug>/model/` unless `SHOPCAD_OUT` names another
plans root. Read the spool cabinet before writing a new module; it shows
the idioms below in use. `cad/README.md` is the short reference.

## Why a plan module and not a CAD session

The numbers on the drawing set are the numbers the person will cut. A model
built from the same `DEFAULTS` dict cannot drift from the sheets, and the
checks in the module fail the export when a number stops working (a flip-top
swing that no longer clears its shelf, a door that hits a parked tool).
That is the point of the model: it is the fit check, and the renders are a
by-product. Keep every dimension a person would change in `DEFAULTS`, and
derive everything else.

## Workflow

1. **Start from the sheet numbers.** Collect the dimensions from the drawing
   set (or the design dialogue) into `DEFAULTS`. Floats are inches, ints are
   counts; the Fusion emitter turns every numeric key into a user parameter.
   Run `scripts/new_plan.py <slug> "<Name>"` from this skill to scaffold the
   module, or copy the closest worked plan.
2. **Write `build(P, state)`.** Absolute coordinates: X east or left-to-right,
   Y north or front-to-back, Z up. Group parts into named components that
   match how the person thinks about the build ("Tool Cabinet", "Door North",
   "Tote Rack"); the viewer toggles them and the STEP groups them. Anything
   that moves (a door, a flipping top, whether a truck is parked) is a state
   key, and movement is a rotation about a pivot via `rz=` and `pivot=` on the
   shape. Reference objects that only set clearances (a vehicle, totes, a
   folded saw) get `opacity=0.45` so they read as ghosts.
3. **Write `checks(P)`.** Each check returns `(name, ok, detail)` with the
   numbers in the detail string. Write the checks you would otherwise verify
   with a tape or a mental sketch: swing radii, clearances between adjacent
   things, working spaces, that a part list still fits its stock. Two kinds
   are easy to forget and have both bitten: **interference with a moving
   part's swept volume** (a vac parked on a flip-top's shelf sat inside the
   hanging tool's swing; the check only measured to the shelf) and
   **hardware that must stay backed** when a dimension moves (raise a shaft
   2 in and the flange bearing hangs off the end panel). When a check needs
   weights or loads (tipping, caster ratings, bolt shear), put pounds and
   densities in a separate `LOADS` dict, not in `DEFAULTS`: every numeric
   `DEFAULTS` key becomes an inch user parameter in Fusion. A failing check
   stops the export on purpose; if a criterion is a judgment call (a 0.25 g
   sideways margin), keep the hard gate to the literal requirement and
   report the judgment figure as an information line. Add one information
   check for a figure worth printing (capacity, overhang).
4. **Declare `STATES` and `VIEWS`.** States are the poses worth a GLB
   (closed/open, planer up/miter up, vehicle in/out). Views are the renders
   the sheets need: an isometric or two, an orthographic elevation, and a
   `focus` close-up per build. See `references/plan-module.md` for every
   field the viewer understands.
5. **Test on the host first** (pure Python, no CadQuery):
   `cd cad && python3 -c "from plans import <mod> as g; [print(r) for r in g.checks(g.DEFAULTS)]; print(len(g.build(dict(g.DEFAULTS), g.STATES[g.DEFAULT_STATE]).parts))"`.
   This catches typos and failing checks in a second instead of a container run.
6. **Run the pipeline:** `cad/run.sh <slug>` (with sudo if your user cannot reach Docker) (add `--no-render` while
   iterating on geometry). It exports in `cadquery/cadquery:latest`, then
   shoots each view with `zenika/alpine-chrome` and software WebGL.
7. **Look at the renders before wiring them in.** Make a contact sheet
   (PIL, four images side by side) and read it: is the near wall hiding the
   thing you wanted, is the camera inside the bounding box, is an
   elevation one flat grey slab (lighting), is a `focus` view framing the
   whole room because a component spans it (split the component). Adjust
   `VIEWS` and rerun; a full run is about a minute.
8. **Say what you assumed.** "Arms sticking out 12 in" can mean past the
   post or past the frame, and the two differ by a factor of two in tipping
   margin. State the reading you modelled and which `DEFAULTS` key flips it.
9. **Wire the outputs into the plan page and the detail page** per
   `references/page-integration.md`: a "3D model" block with the embedded
   viewer and two renders on the layout or main-drawing sheet, one close-up
   per build sheet, STEP, Fusion zip and GLB links on the detail page. Then
   rebuild the site, regenerate the PDF (the print wrapper hides the viewer
   and keeps the PNGs), sync `dist/`, commit.
10. **Let the model correct the sheets.** When the model disagrees with a
   sheet number, the model is usually right because it had to close the
   geometry: a cabinet on a French cleat stands 1.5 in off the wall, a
   flip-top's 30 in top overhangs its 24 in cart. Fix the sheet, and say so
   in the commit message.

## Things that will bite (each cost an hour once)

- **Chrome will not `fetch()` a GLB over `file://`**, flags or not. The
  exporter writes `render.html` with the GLBs inlined as data URLs for the
  headless shots and deletes it afterward; the served `index.html` loads
  the GLBs normally. Do not try to screenshot `index.html` from disk.
- **three.js sanitizes node names** (spaces to underscores, slashes
  removed), so component matching in the viewer normalizes both sides. Keep
  component names readable; do not work around this by removing spaces.
- **The CadQuery container runs as an unprivileged user.** `run.sh` creates
  the output dir owned by the invoking user and passes `--user`; running the
  container as root leaves root-owned files in the checkout.
- **Light from the camera's side.** With the sun on the far side, an
  elevation renders as one grey slab because every face you see is in
  shadow. The viewer places the light relative to the camera and enlarges
  the shadow frustum to the model's largest dimension; if you add a preset,
  keep that.
- **Isometric distance must account for height.** A room is wide and a
  cabinet is tall; the preset uses the largest dimension, and orthographic
  views size to the taller of width and height.
- **Near walls hide the shop.** For a room, hide the two walls between the
  camera and the interest (`"hide": "Wall South,Wall East"`), or the
  render shows drywall.
- **Assembly names must be unique** in CadQuery: the scene assembly and a
  component sub-assembly cannot share a name, which is why the exporter
  suffixes the root.
- **Head-on orthographic views are flat by nature**; put something with
  depth in them (the loaded shelves, not the empty shell) or they read
  as a wash.
- **Photo-sharing links are usually not fetchable** by tools; photos the
  person saves into the working directory are. Ask for that when you need
  a reference photo.
- **Re-rendered PNGs keep their names, so browsers show the old ones.**
  Every render reference needs a content hash when the host caches
  static files: a `?v=<sha256[:8]>` on each `model/render-*.png`, the PDF
  link and the iframe `src`, computed at build time if the site has a
  build step. "Not all the renders are updated"
  is this, not a deploy bug; compare the live file's sha256 before
  debugging anything else.
- **`--no-render` still rewrites the STEP files, the Fusion zip and
  `model.json`** with fresh timestamps. When only the viewer or a view
  changed, `git checkout --` those files so the commit carries real changes
  only. Delete the renders and STEPs of views or components you removed.
- **The viewer panel must fold away completely.** It is a
  `<details class="card" id="panel">` that folds to a bare 30 px menu
  button with no title, and starts folded when embedded in the plan page's
  iframe (`window.self !== window.top`) or under 600 px wide; `?panel=`
  overrides. Anything that covers the model in the small embedded frame
  gets reported as broken.
- **A `focus` view frames the whole room** when a focused component spans
  it, and straight-on views of long flat things sit too far away: split the
  component, hide what is in front, and use `zoom` below 1.
- **Check for an existing install first.** `ls cad/shopcad` before
  running `--init`; a project may already carry a newer copy, and
  `--init` refuses to overwrite one.

## Coordinate and naming conventions

- Plan-view drawings on the sheets often measure y from the far wall; keep
  a helper like `N(P, y_from_north, depth)` in the module so the sheet
  numbers can be typed as they appear.
- A door hinged on its outer stile rotates about `(hinge_x, hinge_y)`; the
  sign of `rz` follows the swing direction (worked out per door in both
  plans). A left door and a right door need opposite signs.
- Name parts the way the cut list does ("side south", "shelf 2", "stile
  hinge side"); the STEP and Fusion bodies inherit them.

## Deliverable checklist

- `cad/plans/<slug>.py` with `DEFAULTS`, `STATES`, `DEFAULT_STATE`,
  `STEP_COMPONENTS`, `VIEWS`, `build`, `checks`, all checks passing
- `public/plans/<slug>/model/` regenerated by `run.sh`
- Model block and per-build renders on the plan page; links on the detail
  page; PDF regenerated; `dist/` synced
- Sheet numbers corrected where the model disagreed, noted in the commit
