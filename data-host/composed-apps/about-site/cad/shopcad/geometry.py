"""Inch-unit primitives and the scene container shared by every plan.

A plan module builds a Scene from boxes and cylinders placed in absolute
coordinates (X east, Y north, Z up, inches). Each Part belongs to a named
component so exporters can group bodies, color them and toggle them in the
viewer. Shapes may carry cuts (subtracted shapes) and a rotation about Z at
a pivot, which is enough for doors that swing and tops that flip.

Runs on Python 3.8 (the cadquery container) and inside Fusion 360, so keep
it to the standard library.
"""

from typing import Dict, List, Optional, Sequence, Tuple

Vec = Tuple[float, float, float]
RGB = Tuple[int, int, int]


class Shape(dict):
    """A box or cylinder as a plain dict so it serializes to JSON unchanged.

    box: origin (min corner), size (w, d, h)
    cyl: base (center of the start face), axis 'x'|'y'|'z', r, length
    Either may carry rz (degrees about +Z) and pivot (x, y) for the rotation.
    """


def box(origin: Vec, size: Vec, rz: float = 0.0, pivot: Optional[Tuple[float, float]] = None) -> Shape:
    s = Shape(shape="box", origin=tuple(float(v) for v in origin), size=tuple(float(v) for v in size))
    if rz:
        s["rz"] = float(rz)
        s["pivot"] = tuple(pivot) if pivot else (s["origin"][0], s["origin"][1])
    return s


def cyl(base: Vec, axis: str, r: float, length: float, rz: float = 0.0,
        pivot: Optional[Tuple[float, float]] = None) -> Shape:
    assert axis in ("x", "y", "z")
    s = Shape(shape="cyl", base=tuple(float(v) for v in base), axis=axis, r=float(r), length=float(length))
    if rz:
        s["rz"] = float(rz)
        s["pivot"] = tuple(pivot) if pivot else (s["base"][0], s["base"][1])
    return s


def _bbox(pts3):
    xs, ys, zs = [p[0] for p in pts3], [p[1] for p in pts3], [p[2] for p in pts3]
    return {"origin": (min(xs), min(ys), min(zs)), "size": (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))}


def _dedupe(pts, eps=0.05):
    """Drop consecutive (and wrap-around) points closer than eps; zero-length edges break the CAD kernel."""
    out = []
    for p in pts:
        if not out or abs(p[0] - out[-1][0]) > eps or abs(p[1] - out[-1][1]) > eps:
            out.append(p)
    while len(out) > 1 and abs(out[0][0] - out[-1][0]) <= eps and abs(out[0][1] - out[-1][1]) <= eps:
        out.pop()
    return out


def prism(pts: Sequence[Tuple[float, float]], z0: float, h: float, axis: str = "z", at: float = 0.0) -> Shape:
    """A polygon extruded. axis 'z': pts are (x, y), extruded from z0 up by h. axis 'x': pts are (y, z), extruded
    from x=z0 along +X by h. axis 'y': pts are (x, z), extruded from y=z0 along +Y by h. Polygons need not be convex.
    Fusion scripts get the bounding box (bbox) as an approximation."""
    pts = _dedupe([tuple(float(c) for c in p) for p in pts])
    assert axis in ("x", "y", "z") and len(pts) >= 3
    s = Shape(shape="prism", pts=[tuple(float(c) for c in p) for p in pts], z0=float(z0), h=float(h), axis=axis)
    if axis == "z":
        p3 = [(a, b, z0) for a, b in pts] + [(a, b, z0 + h) for a, b in pts]
    elif axis == "x":
        p3 = [(z0, a, b) for a, b in pts] + [(z0 + h, a, b) for a, b in pts]
    else:
        p3 = [(a, z0, b) for a, b in pts] + [(a, z0 + h, b) for a, b in pts]
    s["bbox"] = _bbox(p3)
    return s


def slab(pts: Sequence[Tuple[float, float]], bottom: float, top0: float, gx: float = 0.0, gy: float = 0.0) -> Shape:
    """A slab over a convex or concave footprint (x, y) from z=bottom up to a sloped top plane
    z = top0 + gx*x + gy*y. Used for ground that falls across a site."""
    pts = _dedupe([tuple(float(c) for c in p) for p in pts])
    s = Shape(shape="slab", pts=[tuple(float(c) for c in p) for p in pts], bottom=float(bottom), top0=float(top0), gx=float(gx), gy=float(gy))
    s["bbox"] = _bbox([(a, b, bottom) for a, b in pts] + [(a, b, top0 + gx * a + gy * b) for a, b in pts])
    return s


def cone(base: Vec, r0: float, r1: float, length: float) -> Shape:
    """A vertical frustum: radius r0 at base z, r1 at base z + length (r1 may be 0)."""
    s = Shape(shape="cone", base=tuple(float(v) for v in base), r0=float(r0), r1=float(r1), length=float(length))
    x, y, z = s["base"]
    r = max(r0, r1)
    s["bbox"] = {"origin": (x - r, y - r, z), "size": (2 * r, 2 * r, length)}
    return s


def hip(x0: float, y0: float, x1: float, y1: float, z: float, rise: float) -> Shape:
    """A hip roof over the rectangle at eave height z, rising to a ridge along the longer side."""
    s = Shape(shape="hip", rect=(float(x0), float(y0), float(x1), float(y1)), z=float(z), rise=float(rise))
    s["bbox"] = {"origin": (x0, y0, z), "size": (x1 - x0, y1 - y0, rise)}
    return s


def sheet(origin: Vec, w: float, d: float, t: float, **kw) -> Shape:
    """A flat panel lying in XY: w along X, d along Y, thickness t up Z."""
    return box(origin, (w, d, t), **kw)


def slab_x(origin: Vec, d: float, h: float, t: float, **kw) -> Shape:
    """A vertical panel in the YZ plane (thickness along X)."""
    return box(origin, (t, d, h), **kw)


def slab_y(origin: Vec, w: float, h: float, t: float, **kw) -> Shape:
    """A vertical panel in the XZ plane (thickness along Y)."""
    return box(origin, (w, t, h), **kw)


class Part(dict):
    """One solid: name, component, color, shape, cuts, opacity."""


class Scene:
    def __init__(self, name: str):
        self.name = name
        self.parts: List[Part] = []
        self.order: List[str] = []
        self.meta: Dict[str, object] = {}

    def add(self, component: str, name: str, shape: Shape, color: RGB,
            cuts: Sequence[Shape] = (), opacity: float = 1.0) -> Part:
        if component not in self.order:
            self.order.append(component)
        p = Part(component=component, name=name, shape=shape, color=tuple(int(c) for c in color),
                 cuts=list(cuts), opacity=float(opacity))
        self.parts.append(p)
        return p

    def components(self) -> Dict[str, List[Part]]:
        out: Dict[str, List[Part]] = {c: [] for c in self.order}
        for p in self.parts:
            out[p["component"]].append(p)
        return out

    def to_json(self) -> dict:
        return {"name": self.name, "meta": self.meta, "parts": [dict(p) for p in self.parts]}


# A small palette so plans agree on what wood, steel and outlines look like.
PLY = (222, 196, 150)
PLY_DARK = (196, 166, 118)
STUD = (214, 190, 150)
OSB = (205, 178, 126)
STEEL = (150, 156, 162)
STEEL_DARK = (90, 96, 104)
DRYWALL = (236, 232, 224)
SLAB = (176, 172, 164)
TOOL_YELLOW = (250, 190, 20)
TOOL_BLACK = (40, 42, 46)
TOTE_GREY = (90, 92, 96)
TOTE_LID = (240, 200, 40)
ORANGE = (200, 84, 27)
BLUE = (47, 111, 159)
TRUCK = (120, 140, 160)
GLASS = (216, 235, 247)
