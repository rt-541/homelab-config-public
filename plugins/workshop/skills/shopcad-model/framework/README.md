# shopcad: headless 3D models for build plans

`shopcad` is a small framework that turns one Python scene module per plan
into everything the plan page needs: GLB files for an interactive viewer,
STEP for the scene and each build, PNG renders for the sheets and the PDF,
and a Fusion 360 script that rebuilds the parts with user parameters.

```
cad/
  shopcad/        the framework (geometry, GLB writer, exporter, viewer, Fusion emitter)
  plans/          one module per plan, e.g. spool_cabinet.py
  run.sh          docker orchestration: export + renders
```

## Writing a plan module

```python
NAME = "Spool Cabinet"          # title
FUSION_NAME = "SpoolCabinet"    # script folder name
DEFAULTS = dict(bay_w=30.0, cab_h=76.0, ...)     # inches; ints are counts
STATES = {"closed": dict(label=..., doors_open=False), ...}
DEFAULT_STATE = "closed"
STEP_COMPONENTS = ["Case", ...]          # components that also get their own STEP
VIEWS = {"iso": {"state": "closed"},
         "open": {"state": "open", "focus": "Case,Door Left,Door Right", "dir": "sw"}}

def build(P, state) -> shopcad.geometry.Scene   # boxes and cylinders in absolute inches
def checks(P) -> [(name, ok, detail), ...]       # a failed check stops the export
```

Coordinates are X east, Y north, Z up. Shapes take an optional `rz`
(degrees about Z) and `pivot` for doors and flips. Every part belongs to a
named component, which is what the viewer toggles and the STEP groups.

## Running

```
cad/run.sh spool-cabinet              # -> <site>/public/plans/spool-cabinet/model/
cad/run.sh spool-cabinet --no-render  # skip the headless PNGs
SHOPCAD_OUT=docs/plans cad/run.sh spool-cabinet   # another output root
```

Needs `cadquery/cadquery:latest` and `zenika/alpine-chrome:latest`. The
renders shoot `render.html` (GLBs inlined as data URLs, since Chrome will not
fetch a GLB over file://) with software WebGL; that page is deleted
afterward and the served viewer (`index.html`) loads the GLBs normally.

The viewer accepts `?state=`, `?view=` (iso, iso-nw, plan, north, east,
west, shop, garden), `?hide=A,B`, `?focus=A,B&dir=sw` (dir is a corner or
a single side letter for a straight-on view; `&elev=` sets camera height as
a fraction of the focus size, `&zoom=` scales the stand-off, 0.6 fills the
frame with a long flat object), `?panel=0|1` (the control panel starts folded
when embedded in an iframe or on a phone; this overrides) and, for the headless
shots, `?shot=1&w=&h=`.

## Fusion 360

`model/<name>-fusion-script.zip` unzips to a script folder; install under
`%APPDATA%\Autodesk\Autodesk Fusion 360\API\Scripts\` and run it from
Shift+S in an empty design. The first run creates user parameters from
DEFAULTS; edit them and run again to rebuild.

## Generated drawing sheets

`sheets/<slug>/mk.py` holds a plan whose 2D SVG drawings are computed from
one set of geometry constants (inches) rather than drawn by hand, with the
sheet copy in `sheets/<slug>/page.html` as a template (`{{name}}` slots).
`python3 cad/sheets/<slug>/mk.py --out <plans>/<slug>/index.html` writes the page;
change a dimension in the constants and every view, dim and clearance moves
together. The build-plan skill ships a worked example (`examples/rock-screen/`).
