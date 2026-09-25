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
