# Plan module contract

A plan module is a Python 3.8 file under `cad/plans/` that imports only the
standard library and `shopcad.geometry`. The exporter (`shopcad.export`),
the Fusion emitter (`shopcad.fusion`) and the host-side smoke test all read
the same attributes.

## Required attributes

| Attribute | Type | Meaning |
|---|---|---|
| `NAME` | str | Title shown in the viewer and manifest |
| `FUSION_NAME` | str | Script folder name, CamelCase, no spaces |
| `DEFAULTS` | dict | Every number a person would change. Floats are inches, ints are counts; the Fusion emitter makes each numeric key a user parameter (`in` unit for floats, unitless for ints). Non-numeric values are passed through untouched. |
| `STATES` | dict name -> state dict | Each state gets its own GLB. Keys `label` and `description` show in the viewer; every other key is yours (`doors_open`, `flip`, `truck`, `shell`). |
| `DEFAULT_STATE` | str | The state that also gets STEP export and is the manifest's default |
| `STEP_COMPONENTS` | list of str | Components that also get their own `<slug>-<component>.step` |
| `VIEWS` | dict name -> view dict | Renders to shoot (below) |
| `build(P, state)` | function | Returns a `shopcad.geometry.Scene` |
| `checks(P)` | function | Returns a list of `(name, ok, detail)`; any `ok == False` aborts the export |

## Geometry API (`shopcad.geometry`)

```python
from shopcad.geometry import Scene, box, cyl, sheet, slab_x, slab_y, PLY, STUD, STEEL, ...

box(origin=(x, y, z), size=(w, d, h), rz=0.0, pivot=(px, py))
cyl(base=(x, y, z), axis="x"|"y"|"z", r=radius, length=L, rz=0.0, pivot=(px, py))
sheet(origin, w, d, t)         # flat panel in XY, thickness up Z
slab_x(origin, d, h, t)        # vertical panel, thickness along X
slab_y(origin, w, h, t)        # vertical panel, thickness along Y

S = Scene(NAME)
S.add(component, name, shape, color=(r, g, b), cuts=[shape, ...], opacity=1.0)
S.meta = {...}                 # free-form, lands in model.json
```

`rz` is degrees about +Z at `pivot` (defaults to the shape's own origin).
`cuts` are subtracted. Colors are 0-255 tuples; the geometry module exports
a small palette (PLY, PLY_DARK, STUD, OSB, STEEL, STEEL_DARK, DRYWALL, SLAB,
TOOL_YELLOW, TOOL_BLACK, TOTE_GREY, TOTE_LID, ORANGE, BLUE, TRUCK, GLASS) so
plans agree on what plywood and steel look like.

## Loads and other non-inch numbers

Keep them out of `DEFAULTS`. The Fusion emitter turns every numeric
`DEFAULTS` key into a user parameter in inches (ints become unitless
counts), so a `planer_lb=92` there becomes a nonsense "92 in" parameter.
Use a sibling dict and read it in `checks()`:

```python
LOADS = dict(planer_lb=92.0, miter_lb=56.0, board_lb_per_ft=1.3, spf_pcf=28.0, caster_rating_lb=300.0)
```

## View dict fields

| Field | Values | Notes |
|---|---|---|
| `state` | a `STATES` key | Which GLB to load |
| `view` | `iso`, `iso-sw`, `iso-ne`, `iso-nw`, `plan`, `north`, `south`, `east`, `west`, `shop`, `garden` | Camera preset. `iso` looks from the southeast (+X, -Y side), `iso-sw` from the southwest, `iso-ne` and `iso-nw` from the north corners. `plan` is straight down. `north`/`south`/`east`/`west` are orthographic elevations named for the wall they look at: `north` stands south of the model looking north, so a cabinet whose front is at -Y shows its front in `north`. `shop` and `garden` aim at the east and west walls of a room. |
| `hide` | comma-separated component names | Hidden before framing and shooting |
| `focus` | comma-separated component names | Frame these components' bounding box instead of the whole scene |
| `dir` | `se`, `sw`, `ne`, `nw` | Corner the focus camera looks from (default `sw`) |
| `elev` | fraction, e.g. `0.5` | Focus camera height as a fraction of the focus size; `0.5` to `0.6` for a low, readable view |
| `zoom` | factor, default `1` | Scales the focus stand-off; `0.55` fills the frame with a long flat object seen straight on |
| `w`, `h` | pixels | Shot size, default 1600 x 1100 |

The interactive viewer accepts the same as URL parameters
(`?state=open&view=iso-sw&hide=Wall%20South&focus=Tool%20Cabinet&dir=sw`),
which is how the plan page's iframe opens on a chosen view. `dir` also takes a single side letter
(`n`, `s`, `e`, `w`) for a straight-on focus view. `run.sh` passes `zoom`
from the view dict; a new view field must be forwarded there too.
`?panel=0|1` forces the viewer's control panel open or folded.

## Template

```python
"""<Name>, revision A: one-line description.

Coordinates, inches: X ..., Y ..., Z up.
Everything a person would change on the next revision is in DEFAULTS.
"""
import math
from shopcad.geometry import Scene, box, cyl, PLY, STUD, STEEL

NAME = "<Name>"
FUSION_NAME = "<CamelName>"

DEFAULTS = dict(
    width=60.0, depth=30.0, height=36.0, ply=0.75, stud_t=1.5, stud_w=3.5,
    shelf_z=12.0, caster=3.0,
)

STATES = {
    "default": dict(label="As built", description=""),
}
DEFAULT_STATE = "default"
STEP_COMPONENTS = ["Top", "Frame"]
VIEWS = {
    "iso": {"state": "default", "w": 1400, "h": 1100},
    "front": {"state": "default", "view": "north", "w": 1200, "h": 900},
    "frame": {"state": "default", "focus": "Frame", "dir": "sw", "w": 1400, "h": 1000},
}


def build(P, state):
    S = Scene(NAME)
    S.meta = {"state": state}
    W, D, H, ply = P["width"], P["depth"], P["height"], P["ply"]
    S.add("Top", "top", box((0, 0, H - ply), (W, D, ply)), PLY)
    # ... frame, shelf, casters
    return S


def checks(P):
    out = []
    span = P["width"] - 2 * P["stud_w"]
    out.append(("shelf span under 48 in for 3/4 ply", span <= 48, "%.1f in" % span))
    return out
```

## Smoke test on the host

```
cd <project>/cad
python3 -c "import sys; sys.path.insert(0,'.'); from plans import <mod> as g
for r in g.checks(g.DEFAULTS): print(r)
for s, st in g.STATES.items(): print(s, len(g.build(dict(g.DEFAULTS), st).parts), 'parts')"
```

Then `cad/run.sh <slug> --no-render` for the exports, and `cad/run.sh <slug>` for the renders too.
