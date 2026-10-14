"""Generate public/plans/backyard/index.html. Every drawing is computed from cad/plans/backyard.py (DEFAULTS and the
shared geometry helpers), so the site plan, the sections, the 3D model and the quantities agree. Page copy lives in
page.html with {{name}} slots: SVGs by figure name and numbers from V below."""
import hashlib
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CAD = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, CAD)
from plans import backyard as B  # noqa: E402

P = dict(B.DEFAULTS)
PUB = os.path.normpath(os.path.join(CAD, "..", "public", "plans", "backyard"))
OUT = os.path.join(PUB, "index.html")
FT = 12.0


def f(v, nd=2):
    return ("%.*f" % (nd, v)).rstrip("0").rstrip(".")


def fi(v):
    """inches -> 13 ft 6 in"""
    v = int(round(v))
    ft_, inch = divmod(abs(v), 12)
    s = "-" if v < 0 else ""
    if ft_ and inch:
        return "%s%d ft %d in" % (s, ft_, inch)
    if ft_:
        return "%s%d ft" % (s, ft_)
    return "%s%d in" % (s, inch)


class Draw:
    """World (inches) to viewBox. Plan views pass the north coordinate as z with yflip so north is up.
    s is px per inch; sz overrides the vertical scale for exaggerated sections."""

    def __init__(self, x0, x1, z0, z1, s=1.0, sz=None, pad=(16, 6, 6, 6)):
        self.s, self.sz = s, (sz or s)
        self.x0, self.z0, self.z1 = x0, z0, z1
        self.pt, self.pr, self.pb, self.pl = pad
        self.w = (x1 - x0) * s + self.pl + self.pr
        self.h = (z1 - z0) * self.sz + self.pt + self.pb
        self.parts = []

    def X(self, x): return (x - self.x0) * self.s + self.pl
    def Y(self, z): return (self.z1 - z) * self.sz + self.pt

    def rect(self, x0, z0, x1, z1, cls="ply"):
        xa, xb = sorted([self.X(x0), self.X(x1)]); ya, yb = sorted([self.Y(z0), self.Y(z1)])
        self.parts.append('<rect class="%s" x="%.1f" y="%.1f" width="%.1f" height="%.1f"/>' % (cls, xa, ya, xb - xa, yb - ya))

    def poly(self, pts, cls="ply", closed=True):
        tag = "polygon" if closed else "polyline"
        self.parts.append('<%s class="%s" points="%s"/>' % (tag, cls, " ".join("%.1f,%.1f" % (self.X(x), self.Y(z)) for x, z in pts)))

    def line(self, x0, z0, x1, z1, cls="thin"):
        self.parts.append('<line class="%s" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/>' % (cls, self.X(x0), self.Y(z0), self.X(x1), self.Y(z1)))

    def circle(self, x, z, r, cls="thin"):
        self.parts.append('<circle class="%s" cx="%.1f" cy="%.1f" r="%.1f"/>' % (cls, self.X(x), self.Y(z), r * self.s))

    def text(self, x, z, t, cls="", anchor="start", dx=0, dy=0):
        self.parts.append('<text class="%s" x="%.1f" y="%.1f" text-anchor="%s">%s</text>' % (cls, self.X(x) + dx, self.Y(z) + dy, anchor, t))

    def dimh(self, x0, x1, z, t, off=0, above=True):
        y = self.Y(z) + off
        a, b = self.X(x0), self.X(x1)
        self.parts.append('<g class="dim"><line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/><line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/><line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/></g>'
                          % (a, y, b, y, a, y - 3, a, y + 3, b, y - 3, b, y + 3))
        self.parts.append('<text class="dim-t" x="%.1f" y="%.1f" text-anchor="middle">%s</text>' % ((a + b) / 2, y - 2.5 if above else y + 8.5, t))

    def dimv(self, z0, z1, x, t, off=0, left=False):
        x_ = self.X(x) + off
        a, b = self.Y(z0), self.Y(z1)
        self.parts.append('<g class="dim"><line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/><line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/><line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/></g>'
                          % (x_, a, x_, b, x_ - 3, a, x_ + 3, a, x_ - 3, b, x_ + 3, b))
        self.parts.append('<text class="dim-t" x="%.1f" y="%.1f" text-anchor="%s">%s</text>' % (x_ - 3 if left else x_ + 3, (a + b) / 2 + 2.5, "end" if left else "start", t))

    def title(self, t):
        self.parts.append('<text class="lbl" x="4" y="10">%s</text>' % t)

    def svg(self, label):
        return '<svg viewBox="0 0 %d %d" role="img" aria-label="%s">\n%s\n</svg>' % (math.ceil(self.w), math.ceil(self.h), label, "\n".join("  " + p for p in self.parts))


G = B.grade
X0, X1, DD, Z = P["deck_x0"], P["deck_x1"], P["deck_d"], P["deck_z"]
WS = B.stair_w(P)
CK = B.cooking(P)
SW = B.seat_wall(P)
PC = B.pit_clearances(P)
DR = B.drain(P)
DH = B.deck_height(P)
POSTS = B.posts(P)
TREES = B.trees(P)
TOP_J = Z - P["board_t"]
JZ0 = TOP_J - P["joist_d"]
BZ0 = JZ0 - P["beam_d"]
PX0, PX1, PY0, PY1 = P["pat_x0"], P["pat_x1"], P["pat_y0"], P["pat_y1"]
SC = B.ac_screen(P)
SX = 520.0                                       # section A-A, north-south between the chimney and the bay
STONES = B.patio_stones(P)


def deck_outline():
    return B.deck_outline(P)


def stairs_plan(d, treads=True):
    ws = WS
    y0, y1 = P["wstair_yc"] - P["wstair_w"] / 2, P["wstair_yc"] + P["wstair_w"] / 2
    d.rect(ws["x_foot"], y0, X0, y1, "deck")
    for k in range(1, ws["n"]):
        d.line(X0 - k * P["tread"], y0, X0 - k * P["tread"], y1, "thin")


def house_bay(d):
    d.poly(B.bay_poly(P), "house")


def cooking(d, labels=True):
    for key, lbl in (("blackstone", "Blackstone"), ("smoker", "smoker")):
        x0, y0, x1, y1 = CK[key]
        d.rect(x0, y0, x1, y1, "metal-dark")
        if labels:
            d.text(x0 - 4, (y0 + y1) / 2, lbl, "zone-t", anchor="end", dy=2)


def walkway(d):
    for name, poly in B.walkway_polys(P):
        d.poly(poly, "flag")


def fire_ring(d, chairs=True):
    d.circle(P["pit_x"], P["pit_y"], P["pit_ro"], "ring")
    d.circle(P["pit_x"], P["pit_y"], P["pit_ri"], "pit")
    if chairs:
        for i in range(3):
            a = math.radians(210 + i * 60)
            d.circle(P["pit_x"] + P["chair_r"] * math.cos(a), P["pit_y"] + P["chair_r"] * math.sin(a), 11, "chair")


def seat_wall(d):
    d.poly(SW["arc"], "ring")
    d.poly(SW["straight"], "ring")


def lounge_set(d):
    lx0, ly0, lx1, ly1 = P["lounge_x0"], P["lounge_y0"], P["lounge_x1"], P["lounge_y1"]
    d.rect(lx0, ly0 + 10, lx0 + 32, ly0 + 94, "sofa")
    d.rect(lx0 + 38, ly0 + 30, lx0 + 62, ly0 + 74, "table")
    for yy in (ly0 + 14, ly1 - 42):
        d.rect(lx1 - 32, yy, lx1, yy + 30, "sofa")


def patio_stones(d):
    d.circle(P["pit_x"], P["pit_y"], P["apron_r"], "flag")
    d.rect(PX0, PY0, PX1, PY1, "flag-nostroke")
    for q in STONES:
        d.poly(q, "stone-j")


def herb_bed(d):
    y0, y1, w = P["herb_gap"], P["herb_gap"] + P["herb_d"], P["herb_wall"]
    d.rect(P["herb_x0"], y0, P["herb_x1"], y1, "ring")
    d.rect(P["herb_x0"] + w, y0 + w, P["herb_x1"] - w, y1 - w, "herb")


def ac_screen(d):
    d.rect(P["ac_x0"], P["ac_y0"], P["ac_x1"], P["ac_y1"], "metal")
    d.poly([(SC["x0"], SC["y1"]), (SC["x1"], SC["y1"]), (SC["x1"], SC["y0"])], "lattice", closed=False)
    for px, py in ((SC["x0"], SC["y1"]), (SC["x1"], SC["y1"]), (SC["x1"], SC["y0"])):
        d.rect(px - 2, py - 2, px + 2, py + 2, "post")


# ------------------------------------------------------------------ sheet 02: site plan and section A-A

def site_plan():
    d = Draw(-40, 880, -150, 640, s=0.8, pad=(18, 6, 6, 30))
    d.title("Site plan, north up (revision A, estimated)")
    W, D = P["lot_w"], P["yard_d"]
    d.rect(0, -150, W, D, "grass")
    d.rect(P["house_x0"], -150, P["house_x1"], 0, "house")
    house_bay(d)
    d.rect(P["chim_x0"], 0, P["chim_x1"], P["chim_d"], "house")
    d.text((P["house_x0"] + P["house_x1"]) / 2, -90, "HOUSE", "big", anchor="middle")
    ac_screen(d)
    d.text(SC["x0"] - 4, SC["y1"], "AC screen", "", anchor="end")
    herb_bed(d)
    patio_stones(d)
    fire_ring(d)
    seat_wall(d)
    lounge_set(d)
    walkway(d)
    d.poly(deck_outline(), "deck")
    stairs_plan(d)
    tx, ty = P["table_xc"], P["table_yc"]
    d.rect(tx - 44, ty - 64, tx + 44, ty + 64, "zone")
    d.rect(tx - P["table_w"] / 2, ty - P["table_d"] / 2, tx + P["table_w"] / 2, ty + P["table_d"] / 2, "thin")
    d.text(tx, ty + 56, "dining", "zone-t", anchor="middle", dy=2)
    cooking(d, labels=False)
    for ux, uy in ((P["umb_dining_x"], P["umb_dining_y"]),):
        d.rect(ux - 8, uy - 8, ux + 8, uy + 8, "metal")
    for x, y in TREES:
        d.circle(x, y, P["tree_w"] / 2, "tree")
        d.circle(x, y, 3, "trunk")
    d.line(DR["x"], P["drain_y0"], DR["x"], P["drain_y1"], "drain")
    d.circle(DR["x"] + 6, P["drain_y1"] + 6, 7, "metal")
    d.text(DR["x"] - 6, P["drain_y1"] + 4, "existing drain", "", anchor="end")
    d.text(DR["x"] - 6, 300, "French drain", "", anchor="end")
    d.poly([(0, -150), (0, D), (W, D), (W, -150)], "fence", closed=False)
    d.line(SX, -20, SX, D + 16, "cut")
    d.text(SX + 4, D + 12, "A", "lbl")
    d.text(SX + 4, -16, "A", "lbl")
    d.poly([(860, 600), (852, 578), (868, 578)], "arrow-fill")
    d.text(860, 566, "N", "lbl", anchor="middle", dy=6)
    d.dimh(0, W, D + 30, "%s est." % fi(W))
    d.dimv(0, D, -24, "%s est." % fi(D), left=True)
    d.dimh(P["chim_x0"], X1, -8, fi(X1 - P["chim_x0"]) + " deck", above=False)
    d.dimv(0, DD, X1 + 50, fi(DD))
    d.dimh(PX0, PX1, PY0 - 4, fi(PX1 - PX0), above=False)
    d.dimv(PY0, PY1, PX0 - 12, fi(PY1 - PY0), left=True)
    d.text(PX1 - 70, PY0 + 70, "stone patio", "zone-t")
    d.text(P["herb_x0"] + 4, P["herb_gap"] + P["herb_d"] + 6, "raised herb bed", "zone-t")
    d.text((X0 + X1) / 2, DD + P["wrap_w"] + 12, "stone walkway", "zone-t", anchor="middle")
    d.text(TREES[0][0] - 36, TREES[0][1], "5 American Pillar", "zone-t", anchor="end", dy=2)
    for (x, y) in ((0, 0), (0, D), (W, D), (W, 0)):
        d.text(x + (8 if x == 0 else -8), y + (-10 if y == 0 else 10), "%+d" % int(round(G(x, y))), "spot", anchor="start" if x == 0 else "end")
    return d.svg("Site plan: the deck across the back from the chimney to near the house's east corner, the 16 ft stone patio west of the deck with a round apron and fire ring centred on its northwest corner, the raised herb bed along the house, the screened AC, the stone walkway around the deck's north and east sides, five American Pillar arborvitae in a row on the slider's line along the north fence, and the French drain along the east fence")


def tree_elev(d, y, g):
    h, r = P["tree_h"], P["tree_w"] / 2
    d.rect(y - 3, g, y + 3, g + 12, "trunk")
    d.poly([(y - r * 0.75, g + 8), (y - r, g + 8 + h * 0.12), (y - r * 0.72, g + 8 + h * 0.70), (y, g + h),
            (y + r * 0.72, g + 8 + h * 0.70), (y + r, g + 8 + h * 0.12), (y + r * 0.75, g + 8)], "tree")


def section_a():
    d = Draw(-70, 640, -75, 275, s=0.9, pad=(18, 6, 6, 6))
    d.title("Section A-A, looking west, true scale")
    gl = [(y, G(SX, y)) for y in range(-60, 601, 10)]
    d.poly(gl + [(600, -75), (-60, -75)], "earth")
    d.rect(-70, G(SX, 0), 0, G(SX, 0) + P["house_h"], "house")
    d.text(-35, 50, "house", "", anchor="middle")
    for by in P["beam_y"]:
        g = G(SX, by)
        d.rect(by - 6, g - 42, by + 6, g, "concrete")
        d.rect(by - 2.75, g, by + 2.75, BZ0, "frame")
        d.rect(by - 2.25, BZ0, by + 2.25, JZ0, "frame")
    d.rect(P["chim_d"] + 1, JZ0, DD, TOP_J, "frame")
    d.rect(P["chim_d"], TOP_J, DD, Z, "deck")
    d.rect(DD - 2.5, Z, DD + 2.5, Z + P["guard_h"], "deck")
    d.line(P["chim_d"], Z + P["guard_h"], DD, Z + P["guard_h"], "hidden")
    d.rect(DD, G(SX, DD + P["wrap_w"]) - 1, DD + P["wrap_w"], G(SX, DD) + 1.5, "flag")
    x_t = min(TREES, key=lambda t: abs(t[0] - SX))
    tree_elev(d, x_t[1], G(SX, x_t[1]))
    d.line(600, G(SX, 600), 600, G(SX, 600) + P["fence_h"], "fence")
    d.text(DD / 2, Z + 44, "deck", "", anchor="middle")
    d.text(DD + 18, G(SX, DD) + 8, "walkway", "", anchor="middle")
    d.text(x_t[1], 200, "American Pillar", "", anchor="middle")
    d.dimv(G(SX, DD), Z, DD + 44, "%.0f" % (Z - G(SX, DD)))
    d.dimh(0, DD, -70, fi(DD), above=True)
    d.dimh(DD, x_t[1], -70, fi(x_t[1] - DD), above=True)
    d.dimh(x_t[1], 600, -70, fi(600 - x_t[1]), above=True)
    d.text(610, G(SX, 600) - 8, "fence", "", anchor="end")
    d.text(380, G(SX, 380) - 22, "existing grade falls %s in over the yard" % f(G(SX, 0) - G(SX, 600)), "spot", anchor="middle")
    return d.svg("North-south section between the chimney and the bay: the deck on two beams and piers, the stone walkway at its north edge, open lawn, one American Pillar arborvitae and the fence")


# ------------------------------------------------------------------ sheet 03: deck

def deck_framing():
    d = Draw(330, 790, -18, 262, s=1.35, pad=(18, 6, 6, 6))
    d.title("Deck framing plan, north up")
    d.rect(330, -18, 790, 0, "house")
    d.rect(P["chim_x0"], 0, P["chim_x1"], P["chim_d"], "house")
    house_bay(d)
    d.poly(deck_outline(), "deck-light")
    nj = int(round((X1 - X0) / P["joist_oc"]))
    for i in range(nj + 1):
        jx = X0 + min(i * P["joist_oc"], X1 - X0 - 1.5) + 0.75
        y0 = 1.0 + (P["chim_d"] if P["chim_x0"] - 1.5 < jx < P["chim_x1"] else B.bay_front_y(P, jx))
        d.line(jx, y0, jx, B.deck_edge_y(P, jx), "joist")
    d.line(P["chim_x0"] - 1, P["chim_d"] + 1, P["chim_x1"] + 1, P["chim_d"] + 1, "beam-l")
    d.poly([(P["bay_x0"], 1), (P["bay_x0"] + P["bay_d"], P["bay_d"] + 1), (P["bay_x1"] - P["bay_d"], P["bay_d"] + 1), (P["bay_x1"], 1)], "beam-l", closed=False)
    ol = deck_outline()
    d.poly(ol[6:12], "beam-l", closed=False)
    for by in P["beam_y"]:
        d.rect(X0 + 6, by - 2.25, X1 - 6, by + 2.25, "beam")
        for px in POSTS:
            d.rect(px - 2.75, by - 2.75, px + 2.75, by + 2.75, "post")
    for bx, by in ((P["umb_dining_x"], P["umb_dining_y"]),):
        d.rect(bx - 12, by - 12, bx + 12, by + 12, "block-hatch")
    d.line(P["breaker_x"], P["bay_d"] + 1, P["breaker_x"], DD, "breaker")
    stairs_plan(d)
    d.dimh(P["chim_x0"], X1, DD + 14, "%s deck" % fi(X1 - P["chim_x0"]))
    d.dimh(X1 - P["chamfer"], X1, DD - P["chamfer"] - 8, "%s cut" % f(P["chamfer"]), above=False)
    d.dimv(0, P["beam_y"][0], X1 + 20, f(P["beam_y"][0]))
    d.dimv(P["beam_y"][0], P["beam_y"][1], X1 + 20, fi(P["beam_y"][1] - P["beam_y"][0]))
    d.dimv(P["beam_y"][1], DD, X1 + 20, f(DD - P["beam_y"][1]))
    d.dimv(0, DD, X1 + 58, fi(DD))
    d.dimh(POSTS[0], POSTS[1], P["beam_y"][0] - 12, f(POSTS[1] - POSTS[0], 1), above=False)
    d.text(POSTS[0] + 8, P["beam_y"][0] + 6, "beam S, 3-ply 2x10", "")
    d.text(POSTS[0] + 8, P["beam_y"][1] - 12, "beam N, 3-ply 2x10", "")
    d.text(X0 + 30, 110, "2x10 joists 12 in oc", "")
    d.text(P["breaker_x"] + 4, 110, "breaker board", "")
    d.text(P["chim_x0"] + 30, P["chim_d"] - 12, "chimney", "", anchor="middle")
    d.text(P["bay_x0"] + 54, P["bay_d"] - 10, "bay, slider", "", anchor="middle")
    d.text(WS["x_foot"] - 4, P["wstair_yc"], "west stair", "", anchor="end", dy=2)
    return d.svg("Deck framing plan: two three-ply beams on four posts each, 2x10 joists at 12 in running north-south with headers at the chimney and the bay, blocking under the umbrella plates, the breaker board line, and the west and northeast stairs")


def deck_elev_north():
    d = Draw(320, 770, -60, 72, s=1.3, pad=(18, 6, 6, 6))
    d.title("Deck, north elevation (looking south)")
    xs = list(range(320, 771, 10))
    d.poly([(x, G(x, DD)) for x in xs] + [(770, -60), (320, -60)], "earth")
    for px in POSTS:
        g = G(px, P["beam_y"][1])
        d.rect(px - 6, g - 42, px + 6, g, "concrete-h")
    c = P["chamfer"]
    fz = BZ0 + 4
    d.poly([(X0, fz), (X1, fz), (X1, G(X1, DD)), (X0, G(X0, DD))], "skirt")
    z = fz - P["board_w"] - P["skirt_gap"]
    while z > min(G(X0, DD), G(X1, DD)):
        d.line(X0, z, X1, z, "thin")
        z -= P["board_w"] + P["skirt_gap"]
    for px in POSTS:
        d.rect(px - 2.75, G(px, P["beam_y"][1]), px + 2.75, BZ0, "hidden")
    d.rect(X0 - 0.75, fz, X1 + 0.75, Z, "deck")
    d.line(X0 + c, BZ0 + 4, X0 + c, Z, "thin")
    d.line(X1 - c, BZ0 + 4, X1 - c, Z, "thin")
    for px in (X0, X0 + c, X1 - c, X1) + tuple(X0 + c + (X1 - X0 - 2 * c) * i / 4 for i in (1, 2, 3)):
        d.rect(px - 2.5, Z, px + 2.5, Z + P["guard_h"] + 1.5, "deck")
    d.rect(X0, Z + P["guard_h"] - 1.5, X1, Z + P["guard_h"], "deck")
    for k in range(int((X1 - X0) // P["baluster_oc"])):
        bx = X0 + (k + 0.5) * P["baluster_oc"]
        d.line(bx, Z + 5.5, bx, Z + P["guard_h"] - 1.5, "baluster")
    pts = [(X0, Z)]
    for k in range(1, WS["n"]):
        pts += [(X0 - (k - 1) * P["tread"], Z - k * WS["riser"]), (X0 - k * P["tread"], Z - k * WS["riser"])]
    pts += [(WS["x_foot"], WS["land_z"]), (X0, WS["land_z"])]
    d.poly(pts, "deck")
    d.rect(330, WS["land_z"] - 8, X0, WS["land_z"], "flag")
    d.dimv(G(X0, DD), Z, X0 + c + 10, "%.0f" % DH["nw"])
    d.dimv(G(X1, DD), Z, X1 - c - 10, "%.0f" % DH["ne"], left=True)
    d.dimv(Z, Z + P["guard_h"], X0 + c + 40, "%d guard" % P["guard_h"])
    d.dimv(G(POSTS[1], P["beam_y"][1]) - 42, G(POSTS[1], P["beam_y"][1]), POSTS[1] + 10, "42 frost")
    d.text(X0 - WS["run"] / 2, Z + 6, "%d risers" % WS["n"], "", anchor="middle")
    d.text(340, WS["land_z"] - 12, "patio", "")
    d.text(X0 + c / 2, Z - 12, "cut", "", anchor="middle")
    d.text(X1 - c / 2, Z - 12, "cut", "", anchor="middle")
    d.text((X0 + X1) / 2, (fz + G((X0 + X1) / 2, DD)) / 2, "vented composite skirt", "", anchor="middle", dy=2)
    return d.svg("North elevation of the deck: posts on 42 in frost footings under the north beam, fascia and guard across the north side and the two cut corners, and the west stair in profile down to the patio")


def deck_section():
    d = Draw(-30, 260, -64, 70, s=3.0, pad=(18, 6, 6, 6))
    d.title("Deck, typical section between the chimney and the bay, looking west")
    gl = [(y, G(SX, y)) for y in range(-30, 261, 10)]
    d.poly(gl + [(260, -64), (-30, -64)], "earth")
    g0 = G(SX, 0)
    d.rect(-30, g0, 0, 70, "house")
    d.rect(-30, Z + 1, 0, Z + 1.5, "metal")
    for by in P["beam_y"]:
        g = G(SX, by)
        d.rect(by - 6, g - 42, by + 6, g, "concrete")
        d.rect(by - 2.75, g, by + 2.75, BZ0, "frame")
        d.rect(by - 2.25, BZ0, by + 2.25, JZ0, "beam")
    d.rect(1, JZ0, DD - 1.5, TOP_J, "frame")
    d.rect(DD - 1.5, JZ0, DD, TOP_J, "frame")
    d.rect(DD, BZ0 + 4, DD + 0.75, Z, "deck")
    d.rect(0.5, TOP_J, DD, Z, "deck")
    d.rect(DD - 5, Z, DD, Z + P["guard_h"] + 1, "deck")
    d.rect(DD + 0.75, G(SX, DD + 36) - 1, DD + 36, G(SX, DD) + 1.5, "flag")
    by0, by1 = P["beam_y"]
    d.dimv(G(SX, by0) - 42, G(SX, by0), by0 - 12, "42", left=True)
    d.dimv(JZ0, TOP_J, 100, "9.25 joist")
    d.dimv(Z, Z + P["guard_h"], DD + 6, "%d" % P["guard_h"])
    d.dimh(0, by0, TOP_J + 10, f(by0) + " cant.")
    d.dimh(by0, by1, TOP_J + 10, fi(by1 - by0) + " span")
    d.dimh(by1, DD, TOP_J + 10, f(DD - by1))
    d.text(by0 + 8, G(SX, by0) - 30, "12 in pier", "")
    d.text(by1 - 8, G(SX, by1) + 10, "6x6 post", "", anchor="end")
    d.text(4, Z + 20, "1 in below threshold, no ledger", "")
    d.text(DD + 18, G(SX, DD) - 6, "walkway", "", anchor="middle")
    return d.svg("Typical north-south section of the deck: freestanding, the south beam 33 in off the house with the joists cantilevering toward the wall, the north beam 3 ft in from the rim, 6x6 posts on 12 in piers 42 in deep, composite boards and a 36 in guard, the stone walkway beyond")


def stair_west():
    st = WS
    x_end = st["x_foot"] - 30
    d = Draw(x_end, X0 + 10, -12, 30, s=5.0, pad=(18, 110, 6, 6))
    d.title("West stair, side view looking north")
    gl = [(x, G(x, P["wstair_yc"])) for x in range(int(x_end), int(X0 + 11), 4)]
    d.poly(gl + [(X0 + 10, -12), (x_end, -12)], "earth")
    d.rect(x_end, st["land_z"] - 9, st["x_foot"] + 2, st["land_z"] - 3, "base")
    d.rect(x_end, st["land_z"] - 3, st["x_foot"] + 2, st["land_z"] - 2, "dust")
    d.rect(x_end, st["land_z"] - 2, st["x_foot"] + 2, st["land_z"], "flag")
    pts = [(X0, Z)]
    for k in range(1, st["n"]):
        pts += [(X0 - (k - 1) * P["tread"], Z - k * st["riser"]), (X0 - k * P["tread"], Z - k * st["riser"])]
    pts += [(st["x_foot"], st["land_z"]), (X0, st["land_z"])]
    d.poly(pts, "deck")
    d.rect(X0, TOP_J - P["joist_d"], X0 + 8, Z, "frame")
    d.line(X0, Z - 9, st["x_foot"] + 2, st["land_z"] + 1, "hidden")
    d.dimv(st["land_z"], Z, X0 + 12, "%d x %s = %s" % (st["n"], f(st["riser"]), f(st["rise"], 1)))
    d.dimh(st["x_foot"], X0, Z + 3, "%d x %d = %d run" % (st["n"] - 1, P["tread"], st["run"]))
    d.text(x_end + 2, st["land_z"] + 2, "patio", "")
    return d.svg("Side view of the west stair: four risers from the deck down onto the flagstone patio")


def patio_plan():
    x0, x1 = min(P["pit_x"] - P["apron_r"], SC["x0"]) - 20, X0 + 40
    y1 = P["pit_y"] + P["apron_r"] + 28
    d = Draw(x0, x1, -14, y1, s=1.8, pad=(18, 6, 6, 6))
    d.title("Patio, fire ring, herb bed and AC screen, north up")
    d.rect(x0, -14, x1, y1, "grass")
    d.rect(x0, -14, x1, 0, "house")
    d.rect(P["chim_x0"], 0, x1, P["chim_d"], "house")
    ac_screen(d)
    herb_bed(d)
    patio_stones(d)
    fire_ring(d)
    seat_wall(d)
    lounge_set(d)
    d.rect(X0 - P["wrap_w"], PY1, X0, y1, "flag")
    d.poly([(P["chim_x0"], P["chim_d"]), (x1, P["chim_d"]), (x1, y1), (X0, y1), (X0, P["chim_d"])], "deck")
    y0s, y1s = P["wstair_yc"] - P["wstair_w"] / 2, P["wstair_yc"] + P["wstair_w"] / 2
    d.rect(WS["x_foot"], y0s, X0, y1s, "deck")
    for k in range(1, WS["n"]):
        d.line(X0 - k * P["tread"], y0s, X0 - k * P["tread"], y1s, "thin")
    d.text(P["pit_x"], P["pit_y"] - P["pit_ro"] - 6, "fire ring", "", anchor="middle", dy=2)
    d.text(P["pit_x"] + SW["r1"] * 0.72 + 6, P["pit_y"] + SW["r1"] * 0.72 + 6, "seat wall", "")
    d.text((P["lounge_x0"] + P["lounge_x1"]) / 2, P["lounge_y0"] + 4, "sofa set", "", anchor="middle")
    d.text((P["herb_x0"] + P["herb_x1"]) / 2, P["herb_gap"] + P["herb_d"] / 2, "raised herb bed", "on-dark", anchor="middle", dy=2)
    d.text((SC["x0"] + SC["x1"]) / 2, (P["ac_y0"] + P["ac_y1"]) / 2, "AC", "", anchor="middle", dy=2)
    d.text(SC["x1"] + 2, SC["y1"] + 8, "screen N + E, west open", "")
    d.text(X0 + 20, PY1 - 20, "deck", "", anchor="middle")
    d.dimh(PX0, PX1, PY0 + 8, fi(PX1 - PX0), above=True)
    d.dimv(PY0, PY1, PX1 - 10, fi(PY1 - PY0), left=True)
    d.dimh(P["pit_x"] - P["apron_r"], P["pit_x"] + P["apron_r"], P["pit_y"] + P["apron_r"] + 6, fi(2 * P["apron_r"]) + " apron")
    d.dimh(P["pit_x"] + P["pit_ro"], X0, P["pit_y"] - 40, fi(X0 - P["pit_x"] - P["pit_ro"]) + " to deck", above=True)
    d.dimv(0, P["pit_y"] - P["pit_ro"], P["pit_x"] - 34, fi(P["pit_y"] - P["pit_ro"]) + " to house", left=True)
    d.text(P["pit_x"] + P["pit_ro"] + 4, P["pit_y"] + 8, "ring centre = patio NW corner", "spot")
    return d.svg("Plan of the patio: the 16 ft square of irregular buff flagstone off the deck's west side, a 14 ft round apron centred on its northwest corner with the stone fire ring at the centre and six chairs, the stone raised herb bed along the house, the lattice screen around the AC, the stone seat wall around the ring's north half and along the patio's north edge, the sofa set, and the west stair from the deck")


def herb_section():
    d = Draw(-10, 40, -8, 24, s=8.0, pad=(18, 6, 6, 6))
    d.title("Raised herb bed, section")
    y0, y1, w, h = P["herb_gap"], P["herb_gap"] + P["herb_d"], P["herb_wall"], P["herb_h"]
    d.rect(-10, -8, 40, -2, "earth")
    d.rect(-10, -8, 0, 24, "house")
    d.rect(y0, -6, y1, -2, "base")
    d.rect(y0, -2, y0 + w, h, "ring")
    d.rect(y1 - w, -2, y1, h, "ring")
    d.rect(y0 - 0.75, h, y1 + 0.75, h + 2, "flag-dark")
    d.rect(y0 + w, -2, y1 - w, h - 2, "soil")
    d.rect(y1, -2, 40, 0, "flag")
    d.dimh(0, y0, h + 4, "%s gap" % f(y0))
    d.dimh(y0, y1, -7, "%s" % f(P["herb_d"]), above=False)
    d.dimv(-2, h, y1 + 2, "%s" % f(h))
    d.text(-5, 12, "brick", "", anchor="middle")
    d.text((y0 + y1) / 2, 8, "soil", "on-dark", anchor="middle")
    d.text(y1 + 3, 3, "patio", "")
    d.text(y0 + w / 2, h + 4.5, "cap", "", anchor="middle", dy=4)
    return d.svg("Section through the raised herb bed: its own stone back wall stands 4 in off the brick so no soil touches the veneer, 18 in walls with a flat cap, soil between, the patio in front")


def seat_section():
    d = Draw(-8, 40, -12, 24, s=8.0, pad=(18, 6, 6, 6))
    d.title("Seat wall, section at the apron's north edge")
    t, h, cap = P["seat_t"], P["seat_h"], P["seat_cap"]
    d.poly([(-8, -2), (0, -2), (0, -6), (t, -6), (t, -9), (40, -9), (40, -12), (-8, -12)], "earth")
    d.rect(t, -9, 40, -3, "earth-l")
    d.rect(-8, -8, 0, -2, "base")
    d.rect(-8, -2, 0, 0, "flag")
    for k in range(3):
        d.rect(0, -6 + k * (h - cap + 6) / 3, t / 2 - 0.2, -6 + (k + 1) * (h - cap + 6) / 3, "ring")
        d.rect(t / 2 + 0.2, -6 + k * (h - cap + 6) / 3, t, -6 + (k + 1) * (h - cap + 6) / 3, "ring")
    d.rect(-0.75, h - cap, t + 0.75, h, "flag-dark")
    d.dimv(0, h, -4, "%d seat" % h, left=True)
    d.dimh(0, t, h + 3, "%d" % t)
    d.text(-6, 1.5, "apron", "")
    d.text(t + 2, -5, "fill held back", "")
    d.text(t + 2, 4, "lawn falls away north", "")
    return d.svg("Section through the seat wall: two wythes of wall stone 14 in deep on a compacted base, a flat cap at 18 in above the apron, holding back the fill on the low north side")


def ac_elev():
    d = Draw(SC["x0"] - 16, SC["x1"] + 16, -4, 64, s=4.2, pad=(18, 6, 6, 6))
    d.title("AC screen, north side elevation")
    d.line(SC["x0"] - 16, 0, SC["x1"] + 16, 0, "ground-l")
    h = P["acs_h"]
    d.rect(P["ac_x0"], 0, P["ac_x1"], P["ac_h"], "hidden")
    d.rect(SC["x0"], P["mlv_gap"], SC["x1"], h - 2, "mlv")
    k = 1
    while SC["x0"] + k * P["lat_pitch"] < SC["x1"]:
        d.line(SC["x0"] + k * P["lat_pitch"], P["mlv_gap"], SC["x0"] + k * P["lat_pitch"], h - 2, "lat")
        k += 1
    k = 1
    while k * P["lat_pitch"] < h - 2:
        d.line(SC["x0"], P["mlv_gap"] + k * P["lat_pitch"], SC["x1"], P["mlv_gap"] + k * P["lat_pitch"], "lat")
        k += 1
    for px in (SC["x0"], SC["x1"]):
        d.rect(px - 2, 0, px + 2, h + 4, "post-l")
    d.dimh(SC["x0"], SC["x1"], h + 8, fi(SC["x1"] - SC["x0"]))
    d.dimv(0, h, SC["x1"] + 6, "%d" % h)
    d.dimv(0, P["ac_h"], SC["x0"] - 6, "%d unit" % P["ac_h"], left=True)
    d.text((SC["x0"] + SC["x1"]) / 2, h + 1, "open top", "", anchor="middle", dy=-1)
    return d.svg("North elevation of the AC screen: vinyl privacy lattice between vinyl-sleeved posts, the dark mass-loaded vinyl behind it, 52 in tall over the 36 in unit, open at the top, 2 in off the ground at the bottom")


def ring_detail():
    d = Draw(-40, 40, -12, 22, s=7.5, pad=(18, 6, 6, 6))
    d.title("Fire ring, section")
    ro, ri, h = P["pit_ro"], P["pit_ri"], P["pit_h"]
    d.rect(-40, -12, 40, -9, "earth")
    d.rect(-40, -9, 40, -3, "base")
    d.line(-40, -9, 40, -9, "fabric")
    d.rect(-40, -3, 40, -2, "dust")
    courses = 4
    ch = (h - 2.5 + 2) / courses
    for sgn in (-1, 1):
        a, b = sorted((sgn * ri, sgn * ro))
        o0, o1 = sorted((sgn * ro, sgn * (ro + 12)))
        d.rect(o0, -2, o1, 0, "flag")
        for k in range(courses):
            off = 0.4 if k % 2 else 0
            d.rect(a + off, -2 + k * ch, b - off, -2 + (k + 1) * ch, "ring")
        d.rect(a - 0.75, h - 2.5, b + 0.75, h, "flag-dark")
    d.rect(-ri, -2, ri, 1, "ash")
    d.line(-ri, -2, -ri, h - 3, "liner")
    d.line(ri, -2, ri, h - 3, "liner")
    d.dimh(-ro, ro, h + 2, "%d outside" % (2 * ro))
    d.dimh(-ri, ri, h - 5, "%d liner" % (2 * ri), above=False)
    d.dimv(-2, h, ro + 14, "%d" % h)
    d.text(ro + 13, -6, "6 in 21AA", "")
    d.text(0, -0.2, "gravel and ash, no concrete", "on-dark", anchor="middle")
    d.text(-ro - 11, h + 3, "stone courses, flat cap", "", anchor="start")
    return d.svg("Section through the fire ring: four courses of stone around a 36 in steel liner, a flat stone cap, standing on the patio's compacted base with gravel in the bottom and no concrete, the flagstones butting the ring")


def patio_section():
    d = Draw(-4, 100, -14, 8, s=6.2, pad=(18, 6, 6, 6))
    d.title("Patio and walkway, section at the edge")
    d.rect(-4, -14, 100, -9, "earth")
    d.poly([(90, -9), (100, -9), (100, -4), (90, -4)], "earth")
    d.rect(-4, -9, 90, -3, "base")
    d.line(-4, -9, 90, -9, "fabric")
    d.rect(-4, -3, 88, -2, "dust")
    xs = [-4]
    while xs[-1] < 80:
        xs.append(xs[-1] + [18, 24, 15, 21][len(xs) % 4])
    xs[-1] = 86
    for a, b in zip(xs, xs[1:]):
        d.rect(a, -2, b - 0.6, 0, "flag")
    d.rect(86, -8, 90, 0, "ring")
    d.dimv(-9, -3, 60, "6 in 21AA")
    d.dimv(-3, -2, 30, "1 in dust")
    d.dimv(-2, 0, 10, "2 in stone")
    d.text(88, -11.5, "edge stone set deep", "", anchor="end")
    d.text(2, -11.5, "geotextile on compacted subgrade", "")
    d.text(20, 4, "joints: stone dust or polymeric, 1/2 to 1 in", "")
    return d.svg("Section of the dry-laid flagstone at an edge: 2 in stone on 1 in of stone dust on 6 in of compacted 21AA over geotextile, with a deeper edge stone")


# ------------------------------------------------------------------ sheet 05: evergreens and drain

def tree_plan():
    d = Draw(380, 852, 440, 612, s=1.3, pad=(18, 6, 6, 6))
    d.title("American Pillar row along the north fence, north up")
    d.rect(380, 440, 852, 600, "grass")
    for x, y in TREES:
        d.circle(x, y, P["tree_w"] / 2, "tree")
        d.circle(x, y, 3, "trunk")
    d.line(380, 600, 840, 600, "fence")
    d.line(DR["x"], 440, DR["x"], P["drain_y1"], "drain")
    d.circle(DR["x"] + 6, P["drain_y1"] + 6, 7, "metal")
    xc = (P["slider_x0"] + P["slider_x1"]) / 2
    d.line(xc, 440, xc, 600, "cut")
    d.text(xc + 4, 448, "slider centre line", "")
    y = TREES[0][1]
    d.dimh(TREES[0][0], TREES[1][0], y - 36, f(P["tree_pitch"]), above=False)
    d.dimh(TREES[1][0] + P["tree_w"] / 2, TREES[2][0] - P["tree_w"] / 2, y + 30, "%s gap" % f(P["tree_pitch"] - P["tree_w"]))
    d.dimv(y, 600, TREES[0][0] - 36, f(P["tree_off"]), left=True)
    d.dimh(TREES[-1][0], DR["x"], y - 36, f(DR["x"] - TREES[-1][0]), above=False)
    d.dimh(TREES[0][0] - P["tree_w"] / 2, TREES[0][0] + P["tree_w"] / 2, y + 30, f(P["tree_w"]))
    d.text(DR["x"] - 6, 470, "French drain", "", anchor="end")
    return d.svg("Plan of the five American Pillar arborvitae in one row 4 ft off the north fence at 66 in spacing, centred on the bay slider, with the French drain and the existing drain at the east end")


def drain_profile():
    y0, y1 = P["drain_y0"], P["drain_y1"]
    d = Draw(y0 - 20, y1 + 50, -64, 14, s=0.72, sz=2.2, pad=(18, 6, 6, 6))
    d.title("French drain profile along the east fence, vertical x3")
    x = DR["x"]
    ys = list(range(int(y0) - 20, int(y1) + 51, 10))
    d.poly([(y, G(x, y)) for y in ys] + [(y1 + 50, -64), (y0 - 20, -64)], "earth-l")
    d.poly([(y0, G(x, y0)), (y1, G(x, y1)), (y1, DR["inv1"] - 2), (y0, DR["inv0"] - 2)], "stone")
    d.line(y0, DR["inv0"] + 2, y1, DR["inv1"] + 2, "pipe")
    d.rect(y1, DR["inv1"] - 12, y1 + 24, G(x, y1), "hidden")
    d.text(y1 - 30, G(x, y1) + 6, "existing drain: confirm its depth", "warn-t", anchor="end")
    d.text(y0 + 4, G(x, y0) - 6, "start, south end of the wet strip", "")
    d.text((y0 + y1) / 2, (DR["inv0"] + DR["inv1"]) / 2 + 9, "4 in perforated SDR35, holes down, %s in per ft" % f(DR["slope"]), "", anchor="middle")
    d.text(0, G(x, 0) + 5, "house back wall line", "", anchor="middle")
    d.dimh(y0, y1, 10, "%s trench" % fi(y1 - y0))
    d.dimv(DR["inv1"] + 2, G(x, y1), y1 - 20, "%.0f cover" % (G(x, y1) - DR["inv1"] - 2), left=True)
    return d.svg("Profile of the French drain along the east fence: the trench follows the grade toward the northeast corner at a constant depth, the perforated pipe in washed stone, into the existing drain whose depth must be confirmed")


def drain_section():
    d = Draw(-14, 36, -26, 6, s=8.0, pad=(18, 6, 6, 6))
    d.title("French drain, trench section")
    d.rect(-14, -26, 36, 0, "earth-l")
    w = P["trench_w"] / 2
    bot = -(P["trench_cover"] + 4 + 2)
    d.rect(-w, bot, w, 0, "stone")
    d.rect(-w, bot, w, 0, "fabric-box")
    d.circle(0, bot + 4, 2, "pipe-c")
    for a in (-35, 0, 35):
        d.circle(2 * math.sin(math.radians(a)) * 0.9, bot + 4 - 1.7 * math.cos(math.radians(a)), 0.25, "screw")
    d.rect(-w, -3, w, 0.4, "gravel")
    d.line(P["drain_off"], 0, P["drain_off"], 5.5, "fence")
    d.text(P["drain_off"] + 1, 4, "east fence", "")
    d.dimh(-w, w, bot - 1.2, "%d" % P["trench_w"], above=False)
    d.dimv(bot, 0, -w - 3, "%s" % f(-bot), left=True)
    d.dimh(0, P["drain_off"], 2.5, "%d to fence" % P["drain_off"])
    d.text(w + 1, bot + 4, "4 in pipe, holes down", "")
    d.text(w + 1, -8, "3/4 washed stone", "")
    d.text(w + 1, -12, "fabric wraps the stone", "")
    d.text(w + 1, -1.5, "3 in stone at the surface", "")
    return d.svg("Cross section of the French drain trench: 12 in wide and 24 in deep, fabric-wrapped washed stone, 4 in perforated pipe with the holes down, stone to the surface, 24 in inside the east fence")


# ------------------------------------------------------------------ quantities and page values

def quantities():
    q = {}
    q["patio_sf"] = B.patio_area(P) - math.pi * P["pit_ro"] ** 2 / 144.0
    q["walk_sf"] = B.walkway_area(P)
    q["seat_lf"] = SW["length"] / 12.0
    q["seat_blocks"] = int(math.ceil(SW["length"] / 17.44 * 2 * 4 * 1.05))
    ol = B.deck_outline(P)
    sk = 0.0
    for i in range(6, 11):
        (ax, ay), (bx, by) = ol[i], ol[i + 1]
        L = math.hypot(bx - ax, by - ay)
        sk += L * ((BZ0 + 4) - (G(ax, ay) + G(bx, by)) / 2 + 2)
    q["skirt_sf"] = sk / 144.0
    q["skirt_lf"] = sk / (P["board_w"] + P["skirt_gap"]) / 12.0 * 1.1
    sf = q["patio_sf"] + q["walk_sf"]
    q["stone_sf"] = sf
    q["flag_tons"] = sf / 80.0 * 1.1
    q["base_cy"] = sf * P["base_t"] / 12 / 27.0
    q["dust_cy"] = sf * P["dust_t"] / 12 / 27.0
    q["ring_stones"] = int(math.ceil(2 * math.pi * (P["pit_ro"] + P["pit_ri"]) / 2 / 12.0 * 4))
    iw = P["herb_x1"] - P["herb_x0"] - 2 * P["herb_wall"]
    idp = P["herb_d"] - 2 * P["herb_wall"]
    q["herb_cuft"] = iw * idp * (P["herb_h"] - 2) / 1728.0
    q["herb_bags"] = int(math.ceil(q["herb_cuft"] / 1.5))
    q["herb_blocks"] = int(math.ceil(2 * (P["herb_x1"] - P["herb_x0"] + P["herb_d"]) / 17.44 * math.ceil((P["herb_h"] + 4) / 6.0) * 1.05))
    sc_len = (SC["y1"] - SC["y0"]) + (SC["x1"] - SC["x0"])
    q["screen_lf"] = sc_len / 12.0
    q["lattice_panels"] = 2
    q["mlv_sf"] = sc_len * (P["acs_h"] - 4) / 144.0
    q["drain_lf"] = DR["length"] / 12.0
    q["pipe_sticks"] = int(math.ceil(q["drain_lf"] / 10.0 + 0.5))
    depth = (P["trench_cover"] + 6) / 12.0
    q["stone_cy"] = q["drain_lf"] * (P["trench_w"] / 12.0) * depth / 27.0
    q["fabric_sf"] = q["drain_lf"] * (2 * depth + 2 * P["trench_w"] / 12.0 + 1)
    area = B._area(B.deck_outline(P)) / 144.0
    q["deck_sf"] = area
    rows = int(DD // (P["board_w"] + P["board_gap"]))
    q["board_lf"] = rows * (X1 - X0) / 12.0 * 1.1
    q["boards16"] = int(math.ceil(q["board_lf"] / 16.0))
    ol = B.deck_outline(P)
    guard = sum(math.hypot(ol[i + 1][0] - ol[i][0], ol[i + 1][1] - ol[i][1]) for i in range(6, 11)) - P["wstair_w"]
    q["guard_lf"] = guard / 12.0
    q["rail6"] = int(math.ceil(guard / 72.0))
    q["posts"] = len(P["beam_y"]) * len(POSTS)
    q["joists"] = int(round((X1 - X0) / P["joist_oc"])) + 1
    return q


Q = quantities()

PRICES = [
    ("Cantilever umbrella deck plate", 2, 119.00, "Purple Leaf ZYBASE-TB plate, sale price (reg. $199)", "Match to your umbrella first."),
    ("36 in round steel fire ring insert", 1, 32.96, "Walmart, BTY 36 in Round Fire Pit Ring Insert", "The liner inside the stone ring."),
    ("Raised bed and garden soil, 1.5 cu ft", Q["herb_bags"], 9.97, "Home Depot, Miracle-Gro Organic 74059430", "Fills the raised herb bed."),
    ("Veranda 4 x 8 ft privacy vinyl lattice, Sierra Cedar", Q["lattice_panels"], 38.48, "Home Depot 79940 (search listing)", "AC screen, north side and east gate."),
    ("Outdoor mass-loaded vinyl, 1 lb, 4 x 25 ft", 1, None, "Home Depot Technoflex MLV104825 / TotalMass, price not read", "Behind the lattice; %.0f sq ft needed. Not in the total." % Q["mlv_sf"]),
    ("Vinyl 4x4 post sleeves and caps, 3 posts", 3, None, "price not read", "Over ground-contact 4x4 posts. Not in the total."),
    ("Herb plants", 1, None, "Garden centre, price not read", "Basil, thyme, oregano, rosemary, parsley, chives. Not in the total."),
]

ALLOW = [
    ("Deck: demo, footings, framing, composite, guards, the stair", "%.0f sq ft" % Q["deck_sf"], 40, 80, "HomeGuide composite deck installed $40 to $80 per sq ft; demo $5 to $15 per sq ft extra"),
    ("Flagstone patio and walkway, dry-laid", "%.0f sq ft" % Q["stone_sf"], 9.5, 22, "Angi $1,900 to $4,400 per 200 sq ft"),
    ("French drain", "%.0f lin ft" % Q["drain_lf"], 10, 35, "HomeGuide $10 to $35 per lin ft"),
    ("Five American Pillar, delivered and planted", "5 trees", 100, 550, "HomeGuide $100 to $550 each when planting several"),
]


def qty_of(s):
    return float(s.split()[0])


V = {}


def money(v):
    return "${:,.0f}".format(v)


def build_values():
    V["rev_date"] = "2026-09-25"
    V["deck_w"] = fi(X1 - P["chim_x0"])
    V["deck_d"] = fi(DD)
    V["deck_sf"] = "%.0f" % Q["deck_sf"]
    V["dh_sw"], V["dh_se"], V["dh_nw"], V["dh_ne"] = ["%.0f" % DH[k] for k in ("sw", "se", "nw", "ne")]
    V["ws_n"], V["ws_r"], V["ws_run"] = str(WS["n"]), f(WS["riser"]), "%d" % WS["run"]
    V["chamfer"] = f(P["chamfer"] / 12, 1)
    V["seat_lf"] = f(Q["seat_lf"], 1)
    V["seat_blocks"] = str(Q["seat_blocks"])
    V["skirt_sf"] = "%.0f" % Q["skirt_sf"]
    V["skirt_lf"] = "%.0f" % Q["skirt_lf"]
    V["bs_size"] = "%s x %s" % (f(P["bs_w"]), f(P["bs_d"]))
    V["sm_size"] = "%s x %s" % (f(P["sm_w"]), f(P["sm_d"]))
    V["posts"] = str(len(POSTS))
    V["post_bay"] = f(POSTS[1] - POSTS[0], 1)
    V["span"] = f(P["beam_y"][1] - P["beam_y"][0])
    V["joists"] = str(Q["joists"])
    V["pc_deck"], V["pc_house"], V["pc_tree"], V["pc_fence"] = [f(PC[k] / 12, 1) for k in ("deck", "house", "tree", "fence")]
    V["ring_to_deck"] = f((X0 - P["pit_x"] - P["pit_ro"]) / 12, 1)
    V["patio_sf"] = "%.0f" % Q["patio_sf"]
    V["walk_sf"] = "%.0f" % Q["walk_sf"]
    V["stone_sf"] = "%.0f" % Q["stone_sf"]
    V["flag_t"] = f(Q["flag_tons"], 1)
    V["base_cy"] = f(Q["base_cy"], 1)
    V["dust_cy"] = f(Q["dust_cy"], 1)
    V["ring_stones"] = str(Q["ring_stones"])
    V["herb_bags"] = str(Q["herb_bags"])
    V["herb_blocks"] = str(Q["herb_blocks"])
    V["screen_lf"] = f(Q["screen_lf"], 1)
    V["mlv_sf"] = "%.0f" % Q["mlv_sf"]
    V["ring_house"] = f((P["pit_y"] - P["pit_ro"]) / 12, 1)
    V["drain_lf"] = "%.0f" % Q["drain_lf"]
    V["drain_slope"] = f(DR["slope"])
    V["drain_cover"] = "%.0f" % (DR["g1"] - DR["inv1"])
    V["pipe_sticks"] = str(Q["pipe_sticks"])
    V["stone_cy"] = f(Q["stone_cy"], 1)
    V["fabric_sf"] = "%.0f" % Q["fabric_sf"]
    V["boards16"] = str(Q["boards16"])
    V["board_lf"] = "%.0f" % Q["board_lf"]
    V["guard_lf"] = "%.0f" % Q["guard_lf"]
    V["rail6"] = str(Q["rail6"])
    V["post_total"] = str(Q["posts"])
    V["fall"] = f(G(SX, 0) - G(SX, P["yard_d"]))
    V["tree_gap"] = f(P["tree_pitch"] - P["tree_w"])
    V["pit_d"] = "%d" % (2 * P["pit_ro"])
    rows, total = [], 0.0
    for item, qty, each, src, note in PRICES:
        if each is None:
            rows.append('<tr><td>%s</td><td class="n">%d</td><td class="n">not read</td><td class="n"></td><td>%s. %s</td></tr>' % (item, qty, src, note))
        else:
            line = qty * each
            total += line
            rows.append('<tr><td>%s</td><td class="n">%d</td><td class="n">$%.2f</td><td class="n">%s</td><td>%s. %s</td></tr>' % (item, qty, each, money(line), src, note))
    V["diy_rows"] = "\n        ".join(rows)
    V["diy_total"] = money(total)
    arows, lo_t, hi_t = [], 0.0, 0.0
    for scope, qty, lo, hi, src in ALLOW:
        qn = qty_of(qty)
        lo_t += qn * lo
        hi_t += qn * hi
        arows.append('<tr><td>%s</td><td class="n">%s</td><td class="n">%s to %s</td><td class="n">%s to %s</td><td>%s</td></tr>'
                     % (scope, qty, money(lo) if lo >= 10 else "$%s" % f(lo), money(hi), money(qn * lo), money(qn * hi), src))
    V["allow_rows"] = "\n        ".join(arows)
    V["allow_total"] = "%s to %s" % (money(lo_t), money(hi_t))
    V["all_total"] = "%s to %s" % (money(lo_t + total), money(hi_t + total))
    for name in ("hero", "iso-nw", "iso-ne", "plan", "deck", "cooking", "framing", "patio", "ac-screen", "trees"):
        pth = os.path.join(PUB, "model", "render-%s.png" % name)
        V["v_" + name.replace("-", "_")] = hashlib.sha256(open(pth, "rb").read()).hexdigest()[:8] if os.path.exists(pth) else "0"
    for name in ("north", "ne", "west"):
        pth = os.path.join(PUB, "model", "photo-%s.png" % name)
        V["v_photo_" + name] = hashlib.sha256(open(pth, "rb").read()).hexdigest()[:8] if os.path.exists(pth) else "0"
    pdf = os.path.join(PUB, "backyard.pdf")
    V["v_pdf"] = hashlib.sha256(open(pdf, "rb").read()).hexdigest()[:8] if os.path.exists(pdf) else "0"
    mj = os.path.join(PUB, "model", "model.json")
    V["v_model"] = hashlib.sha256(open(mj, "rb").read()).hexdigest()[:8] if os.path.exists(mj) else "0"


if __name__ == "__main__":
    build_values()
    svgs = dict(site_plan=site_plan(), section_a=section_a(), deck_framing=deck_framing(), deck_elev=deck_elev_north(),
                deck_section=deck_section(), stair_west=stair_west(), patio_plan=patio_plan(), ring_detail=ring_detail(),
                patio_section=patio_section(), herb_section=herb_section(), seat_section=seat_section(), ac_elev=ac_elev(), tree_plan=tree_plan(), drain_profile=drain_profile(), drain_section=drain_section())
    tpl = open(os.path.join(HERE, "page.html")).read()
    for k, v in svgs.items():
        tpl = tpl.replace("{{%s}}" % k, v)
    for k, v in V.items():
        tpl = tpl.replace("{{%s}}" % k, v)
    left = [l.strip() for l in tpl.splitlines() if "{{" in l]
    assert not left, left
    os.makedirs(PUB, exist_ok=True)
    open(OUT, "w").write(tpl)
    print("wrote", OUT, len(tpl))
    for k in ("diy_total", "allow_total", "all_total"):
        print(k, V[k])
