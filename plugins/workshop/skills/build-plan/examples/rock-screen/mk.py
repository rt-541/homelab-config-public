"""Generate the rock screen drawing set (default out/index.html, or --out). All geometry is in inches from the constants below; every SVG is
computed from them so the general arrangement, the tray plan, the stand and the funnel agree with the cut list."""
import argparse, math, os
HERE = os.path.dirname(os.path.abspath(__file__))
_ap = argparse.ArgumentParser(description="Write the rock screen drawing set.")
_ap.add_argument("--out", default=os.path.join(HERE, "out", "index.html"), help="output HTML path")
OUT = _ap.parse_args().out

# ---- geometry (inches). X along the tilt direction, discharge end negative, pivot at X=0. Y across. Z up. ----
TILT = 35.0
STAND_X0, STAND_X1 = -4.0, 36.0          # outside faces of the front and back legs (stringer length 40)
LEG_H = 37.5                             # legs and stringer top
STR_Z0 = LEG_H - 3.5                     # stringer bottom
IN_W = 24.5                              # between the stringers
STR_Y = [(1.5, 3.0), (1.5 + IN_W, 3.0 + IN_W)]
LEG_Y = [(0.0, 1.5), (3.0 + IN_W + 1.5 - 1.5, 3.0 + IN_W + 1.5)]   # legs outside the stringers
STAND_W = 3.0 + IN_W + 1.5 + 1.5 - 1.5 + 1.5                     # 30.5
PUCK_RAIL = (30.5, 34.0, 29.0, 32.5)     # x0 x1 z0 z1, top 32.5, puck 1 in on top
LOW_Z = (8.0, 11.5)
WHEEL_D, WHEEL_X, WHEEL_Z = 8.0, -2.25, 4.5
PIV = (0.0, 36.0)                        # pivot bolt through stringer and tray side rail
TRAY_X0, TRAY_X1 = -9.0, 39.0            # side rails 48 long
TRAY_Z0 = PIV[1] - 2.5                   # 33.5 at rest
RAIL_H = 5.5
MESH_Z = TRAY_Z0 + 1.5                   # 35, on top of the 2x2 slats
BACK_RAIL = (27.0, 28.5)                 # mesh section 36 long
SLATS = [-8.25, 0.0, 9.0, 18.0]          # 2x2 centers, the first is the front strip
HANDLE_X = 37.5
LIP_X = -12.0
TRAY_W = 24.0
TRAY_Y0 = 3.0 + (IN_W - TRAY_W) / 2      # 3.25
# funnel
FUN_Z_TOP, FUN_Z_SPOUT, FUN_Z_BOT = 27.5, 17.5, 13.5
FUN_X0, FUN_X1 = STAND_X0, STAND_X0 - 9.0       # 9 deep, back wall on the front legs
MOUTH_Y = (2.25, 28.25)
SPOUT_Y = (10.75, 19.75)
# hand truck and sack
NOSE = (-17.0, -3.0, 0.0, 0.5)
SACK_W = 15.0

def f(v):
    return ("%.2f" % v).rstrip("0").rstrip(".")

class Draw:
    def __init__(self, x0, x1, z0, z1, s=4.0, pad=(6, 6, 6, 6), yflip=True):
        self.s, self.x0, self.z1, self.yflip = s, x0, z1, yflip
        self.z0 = z0
        self.pt, self.pr, self.pb, self.pl = pad
        self.w = (x1 - x0) * s + self.pl + self.pr
        self.h = (z1 - z0) * s + self.pt + self.pb
        self.parts = []
    def X(self, x): return (x - self.x0) * self.s + self.pl
    def Y(self, z): return ((self.z1 - z) if self.yflip else (z - self.z0)) * self.s + self.pt
    def rect(self, x0, z0, x1, z1, cls="ply"):
        xa, xb = sorted([self.X(x0), self.X(x1)]); ya, yb = sorted([self.Y(z0), self.Y(z1)])
        self.parts.append('<rect class="%s" x="%.1f" y="%.1f" width="%.1f" height="%.1f"/>' % (cls, xa, ya, xb - xa, yb - ya))
    def poly(self, pts, cls="ply"):
        self.parts.append('<polygon class="%s" points="%s"/>' % (cls, " ".join("%.1f,%.1f" % (self.X(x), self.Y(z)) for x, z in pts)))
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
        self.parts.append('<text class="dim-t" x="%.1f" y="%.1f" text-anchor="middle">%s</text>' % ((a + b) / 2, y - 2 if above else y + 8, t))
    def dimv(self, z0, z1, x, t, off=0, left=False):
        x_ = self.X(x) + off
        a, b = self.Y(z0), self.Y(z1)
        self.parts.append('<g class="dim"><line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/><line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/><line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/></g>'
                          % (x_, a, x_, b, x_ - 3, a, x_ + 3, a, x_ - 3, b, x_ + 3, b))
        self.parts.append('<text class="dim-t" x="%.1f" y="%.1f" text-anchor="%s">%s</text>' % (x_ - 3 if left else x_ + 3, (a + b) / 2 + 2.5, "end" if left else "start", t))
    def svg(self, label, extra_w=0, extra_h=0):
        return '<svg viewBox="0 0 %d %d" role="img" aria-label="%s">\n%s\n</svg>' % (math.ceil(self.w + extra_w), math.ceil(self.h + extra_h), label, "\n".join("  " + p for p in self.parts))

def rot(dx, dz, deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return dx * c - dz * s, dx * s + dz * c

def tray_pts(theta):
    """Polygons of the tray side elevation rotated about the pivot: side rail, back rail, slats, handle, lip, mesh line."""
    def P(x, z):
        dx, dz = rot(x - PIV[0], z - PIV[1], theta)
        return PIV[0] + dx, PIV[1] + dz
    rail = [P(TRAY_X0, TRAY_Z0), P(TRAY_X1, TRAY_Z0), P(TRAY_X1, TRAY_Z0 + RAIL_H), P(TRAY_X0, TRAY_Z0 + RAIL_H)]
    mesh = (P(TRAY_X0, MESH_Z), P(BACK_RAIL[0], MESH_Z))
    lip = (P(TRAY_X0, MESH_Z), P(LIP_X, MESH_Z - 0.75))
    handle = P(HANDLE_X, TRAY_Z0 + RAIL_H / 2)
    piv = P(*PIV)
    return rail, mesh, lip, handle, piv, P

def title(d, t):
    d.parts.append('<text class="lbl" x="2" y="8">%s</text>' % t)

def stand_side(d, labels=True):
    d.line(-30, 0, 52, 0, "ground")
    d.rect(STAND_X0, 0, STAND_X0 + 3.5, LEG_H, "lumber")
    d.rect(STAND_X1 - 3.5, 0, STAND_X1, LEG_H, "lumber")
    d.rect(STAND_X0 + 3.5, LOW_Z[0], STAND_X1 - 3.5, LOW_Z[1], "lumber")
    d.rect(PUCK_RAIL[0], PUCK_RAIL[2], PUCK_RAIL[1], PUCK_RAIL[3], "hidden")
    d.rect(PUCK_RAIL[0] + 0.25, PUCK_RAIL[3], PUCK_RAIL[1] - 0.25, PUCK_RAIL[3] + 1.0, "puck")
    # funnel: vertical back and front walls and the spout line, side view
    d.rect(FUN_X1, FUN_Z_BOT, FUN_X0, FUN_Z_TOP, "funnel-face")
    d.rect(FUN_X0 - 0.375, FUN_Z_BOT, FUN_X0, FUN_Z_TOP, "ply")
    d.rect(FUN_X1, FUN_Z_BOT, FUN_X1 + 0.375, FUN_Z_TOP, "ply")
    d.line(FUN_X1, FUN_Z_SPOUT, FUN_X0, FUN_Z_SPOUT, "thin")
    # hand truck and the sack cuffed on the spout
    d.rect(NOSE[0], NOSE[2], NOSE[1], NOSE[3], "metal-solid")
    d.rect(NOSE[0] - 1.25, 0.5, NOSE[0], 46, "metal-solid")
    d.circle(NOSE[0] - 2.5, 5, 5, "wheel")
    sx0, sx1 = FUN_X1 + 1.5, FUN_X0 - 1.5
    d.poly([(sx0 + 1, 0.5), (sx1 - 1, 0.5), (sx1, FUN_Z_BOT + 2), (sx0, FUN_Z_BOT + 2)], "sack")
    d.rect(sx0 - 0.5, FUN_Z_BOT + 1, sx1 + 0.5, FUN_Z_BOT + 3.5, "sack-cuff")
    d.line(sx0 + 1, 8, sx1 - 1, 8, "fill")
    # wheel on the front leg, drawn last since it is nearest the viewer
    d.circle(WHEEL_X, WHEEL_Z, WHEEL_D / 2, "wheel")
    d.circle(WHEEL_X, WHEEL_Z, 0.5, "thin")
    if labels:
        d.text(sx0 + 1.5, 8, "45 lb", "dim-t", dy=-1.5)
        d.text(-8.5, 21, "funnel", "", anchor="middle")
        d.text(NOSE[0] + 0.5, 30.5, "hand truck")
        d.text(WHEEL_X + 4.5, WHEEL_Z, "8 in wheel", "", dy=2)
        d.text(PUCK_RAIL[0] - 1, PUCK_RAIL[2] - 1.5, "pucks", "", dy=4)
        d.dimv(0, FUN_Z_BOT, -22, "13.5", left=True)

def ga(theta):
    zt = 62 if theta else 50
    d = Draw(-30, 52, -3, zt, s=4, pad=(14, 4, 4, 4))
    stand_side(d, labels=not theta)
    rail, mesh, lip, handle, piv, P = tray_pts(theta)
    d.poly(rail, "tray")
    d.line(*mesh[0], *mesh[1], "mesh")
    d.line(*lip[0], *lip[1], "metal-solid")
    d.poly([P(BACK_RAIL[0], TRAY_Z0), P(BACK_RAIL[1], TRAY_Z0), P(BACK_RAIL[1], TRAY_Z0 + RAIL_H), P(BACK_RAIL[0], TRAY_Z0 + RAIL_H)], "hidden")
    for sx in SLATS:
        d.poly([P(sx - 0.75, TRAY_Z0), P(sx + 0.75, TRAY_Z0), P(sx + 0.75, TRAY_Z0 + 1.5), P(sx - 0.75, TRAY_Z0 + 1.5)], "hidden")
    d.rect(STAND_X0, STR_Z0, STAND_X1, LEG_H, "lumber-glass")
    d.rect(STAND_X0, STR_Z0, STAND_X1, LEG_H, "lumber-glass")
    d.circle(*handle, 0.625, "dowel")
    d.circle(*piv, 0.5, "bolt")
    if not theta:
        for i in range(9):
            d.circle(TRAY_X0 + 2.5 + i * 3.6, MESH_Z + 1.1, 1.1, "rock")
    else:
        for i in range(6):
            rx, rz = P(TRAY_X0 + 6 + i * 3.6, MESH_Z + 1.1)
            d.circle(rx, rz, 1.1, "rock")
        ax, az = P(TRAY_X0 - 1, MESH_Z + 2)
        d.circle(FUN_X0 - 6, FUN_Z_TOP - 3, 1.1, "rock")
        d.circle(FUN_X0 - 5, FUN_Z_SPOUT - 1.5, 1.0, "rock")
        d.line(ax, az, FUN_X0 - 7, FUN_Z_TOP + 1, "arrow")
    return d, P, handle

def ga_rest():
    d, P, handle = ga(0)
    title(d, "General arrangement, side, at rest")
    d.dimv(0, LEG_H, STAND_X1 + 2, "37.5")
    d.dimv(0, MESH_Z, STAND_X1 + 8, "35 mesh")
    d.dimh(STAND_X0, STAND_X1, -0.5, "40 stand", above=False)
    d.dimh(TRAY_X0, TRAY_X1, TRAY_Z0 + RAIL_H + 1.5, "48 tray")
    d.dimh(TRAY_X0, BACK_RAIL[0], TRAY_Z0 + RAIL_H + 5, "36 mesh")
    d.dimh(TRAY_X0, PIV[0], TRAY_Z0 - 1.5, "9", above=False)
    d.text(1.5, TRAY_Z0 - 0.5, "pivot", "", dy=6)
    d.text(TRAY_X1 + 2, TRAY_Z0 + RAIL_H / 2, "handle", "", dy=2)
    return d.svg("Side elevation of the rock screen at rest: stand, tray on its pivot, funnel on the front legs, sack on a hand truck")

def ga_tilt():
    d, P, handle = ga(TILT)
    title(d, "Tilted %d degrees, rock sliding into the sack" % int(TILT))
    hx, hz = handle
    d.dimv(0, hz, STAND_X1 + 4, "%.0f handle" % hz)
    fx, fz = P(TRAY_X0, TRAY_Z0)
    d.text(fx - 0.5, fz + 1.7, "%.1f clear" % (fz - FUN_Z_TOP), "", anchor="end")
    d.text(hx - 1.5, hz + 1.5, "23 lb lift", "", anchor="end")
    return d.svg("Side elevation with the tray tilted 35 degrees: the back end raised by the handle, rock sliding off the lip into the funnel and sack")

def tray_plan():
    d = Draw(-14, 46, -4.5, 28, s=10, pad=(14, 4, 4, 4), yflip=False)
    y0, y1 = 0, TRAY_W
    title(d, "Tray, plan from above")
    d.rect(TRAY_X0, y0, TRAY_X1, y0 + 1.5, "tray")
    d.rect(TRAY_X0, y1 - 1.5, TRAY_X1, y1, "tray")
    d.rect(TRAY_X0, 1.5, BACK_RAIL[0], y1 - 1.5, "meshfill")
    for sx in SLATS:
        d.rect(sx - 0.75, 1.5, sx + 0.75, y1 - 1.5, "hidden")
    d.rect(BACK_RAIL[0], 1.5, BACK_RAIL[1], y1 - 1.5, "tray")
    d.rect(TRAY_X0, 1.5, BACK_RAIL[0], 2.25, "batten")
    d.rect(TRAY_X0, y1 - 2.25, BACK_RAIL[0], y1 - 1.5, "batten")
    d.rect(BACK_RAIL[0] - 0.75, 2.25, BACK_RAIL[0], y1 - 2.25, "batten")
    d.rect(LIP_X, 1.5, TRAY_X0, y1 - 1.5, "metal-solid")
    d.rect(HANDLE_X - 0.625, y0, HANDLE_X + 0.625, y1, "dowel")
    d.circle(PIV[0], y0 + 0.75, 0.3, "bolt"); d.circle(PIV[0], y1 - 0.75, 0.3, "bolt")
    d.dimh(TRAY_X0, TRAY_X1, -1.2, "48")
    d.dimh(TRAY_X0, PIV[0], -3.0, "9")
    d.dimh(LIP_X, TRAY_X0, 25.2, "3 lip", above=False)
    d.dimh(TRAY_X0, BACK_RAIL[0], 25.2, "36 mesh", above=False)
    d.dimh(BACK_RAIL[1], TRAY_X1, 25.2, "10.5 handle", above=False)
    d.dimv(y0, y1, TRAY_X1 + 1.5, "24")
    d.dimv(1.5, y1 - 1.5, TRAY_X1 + 4.5, "21")
    d.text(0.9, 12.5, "2x2 slats, 9 in oc")
    d.text(HANDLE_X - 1.2, 12.5, "1-1/4 dowel", "", anchor="end")
    d.text(1.0, 4.0, "9/16 pivot hole")
    d.text(BACK_RAIL[0] - 1.2, 6.5, "back rail", "", anchor="end")
    d.text(LIP_X + 0.4, 6.5, "lip")
    return d.svg("Plan of the tray from above: 2x6 side rails 48 in long, a 36 in screen section with 2x2 slats under the mesh, the back rail, a 10.5 in handle bay with the dowel, and the flashing lip at the front")

def tray_section():
    d = Draw(-3, 31, -1.6, 8.5, s=10, pad=(14, 4, 4, 4))
    title(d, "Tray section, looking at the discharge end")
    z0 = 0
    d.rect(0, z0, 1.5, RAIL_H, "tray"); d.rect(TRAY_W - 1.5, z0, TRAY_W, RAIL_H, "tray")
    d.rect(1.5, z0, TRAY_W - 1.5, 1.5, "lumber")
    d.line(1.5, 1.5, TRAY_W - 1.5, 1.5, "mesh")
    d.line(1.5, 1.5, 1.5, 3.0, "mesh"); d.line(TRAY_W - 1.5, 1.5, TRAY_W - 1.5, 3.0, "mesh")
    d.rect(1.5, 1.5, 2.25, 3.0, "batten"); d.rect(TRAY_W - 2.25, 1.5, TRAY_W - 1.5, 3.0, "batten")
    for i, r in enumerate([1.5, 0.6, 1.0, 1.9, 0.5, 1.2, 0.8, 1.6, 0.7]):
        d.circle(3.5 + i * 2.3, 1.5 + r, r, "rock")
    d.dimv(z0, RAIL_H, TRAY_W + 2, "5.5")
    d.dimv(z0, 1.5, TRAY_W + 5, "1.5")
    d.dimh(0, TRAY_W, -0.3, "24", above=False)
    d.text(2.2, 0.75, "2x2 slat", "", dy=2)
    d.text(3.2, 7.3, "1x2 batten over the mesh edge, both rails and the back")
    d.line(3.0, 7.0, 2.0, 3.2, "thin")
    d.text(14, 6.2, "1/2 in hardware cloth on the slats")
    d.line(13.8, 5.9, 12.8, 1.7, "thin")
    return d.svg("Cross section of the tray: 2x6 side rails, 2x2 slat, hardware cloth on top of the slat turned up the rails and clamped by 1x2 battens, one layer of rock")

def stand_back():
    d = Draw(-6, 48, -1.6, 43, s=8, pad=(14, 4, 4, 4))
    title(d, "Stand, looking at the back")
    d.line(-6, 0, 40, 0, "ground")
    for (a, b) in LEG_Y:
        d.rect(a, 0, b, LEG_H, "lumber")
    for (a, b) in STR_Y:
        d.rect(a, STR_Z0, b, LEG_H, "lumber-far")
    d.rect(STR_Y[0][1], PUCK_RAIL[2], STR_Y[1][0], PUCK_RAIL[3], "lumber")
    for py in (TRAY_Y0 + 0.75, TRAY_Y0 + TRAY_W - 0.75):
        d.rect(py - 1.5, PUCK_RAIL[3], py + 1.5, PUCK_RAIL[3] + 1, "puck")
    d.rect(LEG_Y[0][1], LOW_Z[0], LEG_Y[1][0], LOW_Z[1], "lumber")
    d.rect(TRAY_Y0, TRAY_Z0, TRAY_Y0 + TRAY_W, TRAY_Z0 + RAIL_H, "hidden")
    d.rect(-1.75, WHEEL_Z - 4, 0, WHEEL_Z + 4, "wheel")
    d.rect(STAND_W, WHEEL_Z - 4, STAND_W + 1.75, WHEEL_Z + 4, "wheel")
    d.dimh(0, STAND_W, -0.3, "30.5", above=False)
    d.dimh(STR_Y[0][1], STR_Y[1][0], 41.5, "24.5 between stringers")
    d.dimv(0, LEG_H, STAND_W + 3.5, "37.5")
    d.dimv(0, PUCK_RAIL[3] + 1, -3.5, "33.5", left=True)
    d.text(STAND_W / 2, PUCK_RAIL[2] - 1.2, "puck rail 2x4 x 24.5, pucks on top", "", anchor="middle")
    d.text(STAND_W / 2, LOW_Z[0] - 1.2, "low rail 2x4 x 27.5", "", anchor="middle")
    d.text(STAND_W / 2, TRAY_Z0 + RAIL_H + 0.5, "tray, dashed, between the stringers", "", anchor="middle")
    d.text(STAND_W / 2, 20, "stringers behind the legs", "", anchor="middle")
    d.text(-1.75, WHEEL_Z + 5.6, "wheels on the front legs")
    return d.svg("Back elevation of the stand: legs outside the stringers, puck rail between them with the two pucks, low rail, and the tray shown dashed hanging between the stringers")

def stand_plan():
    d = Draw(-8, 46, -4.5, 36, s=8, pad=(14, 4, 4, 4), yflip=False)
    title(d, "Stand, top frame from above")
    for (a, b) in STR_Y:
        d.rect(STAND_X0, a, STAND_X1, b, "lumber")
    for (a, b) in LEG_Y:
        d.rect(STAND_X0, a, STAND_X0 + 3.5, b, "lumber-far"); d.rect(STAND_X1 - 3.5, a, STAND_X1, b, "lumber-far")
    d.rect(PUCK_RAIL[0], STR_Y[0][1], PUCK_RAIL[1], STR_Y[1][0], "lumber")
    d.rect(FUN_X0 - 0.375, 0, FUN_X0, STAND_W, "ply")
    d.rect(TRAY_X0, TRAY_Y0, TRAY_X1, TRAY_Y0 + TRAY_W, "hidden")
    d.circle(PIV[0], STR_Y[0][0] + 0.75, 0.3, "bolt"); d.circle(PIV[0], STR_Y[1][1] - 0.75, 0.3, "bolt")
    d.dimh(STAND_X0, STAND_X1, -3.2, "40")
    d.dimh(STAND_X0, PIV[0], -1.2, "4")
    d.dimh(PUCK_RAIL[0], PUCK_RAIL[1], 31.8, "3.5", above=False)
    d.dimv(0, STAND_W, STAND_X1 + 2.5, "30.5")
    d.text(15, STAND_W / 2, "tray outline, 24 x 48, dashed", "", anchor="middle", dy=2)
    d.text(FUN_X0 - 0.2, 33.5, "funnel back wall on the front legs")
    d.text(PIV[0] + 1, STR_Y[0][1] + 2.2, "pivot bolts")
    d.text(PUCK_RAIL[0] - 1, STR_Y[1][0] - 2.2, "puck rail", "", anchor="end")
    return d.svg("Plan of the stand top frame: two 40 in stringers with the legs outside them, the puck rail near the back, the pivot bolts 4 in from the front, and the funnel back wall on the front legs")

def funnel_front():
    d = Draw(-4, 36, 9.5, 31.5, s=9, pad=(14, 4, 4, 4))
    title(d, "Funnel, looking at the front")
    for (a, b) in LEG_Y:
        d.rect(a, 9.5, b, 31.5, "lumber-far")
    d.rect(0, FUN_Z_BOT, STAND_W, FUN_Z_TOP, "ply")
    d.poly([(MOUTH_Y[0], FUN_Z_TOP), (MOUTH_Y[1], FUN_Z_TOP), (SPOUT_Y[1], FUN_Z_SPOUT), (SPOUT_Y[1], FUN_Z_BOT), (SPOUT_Y[0], FUN_Z_BOT), (SPOUT_Y[0], FUN_Z_SPOUT)], "funnel-face")
    d.rect(SPOUT_Y[0] - 1, FUN_Z_BOT - 0.5, SPOUT_Y[1] + 1, FUN_Z_BOT + 2.5, "sack-cuff")
    d.dimh(MOUTH_Y[0], MOUTH_Y[1], FUN_Z_TOP + 1.2, "26 mouth")
    d.dimh(SPOUT_Y[0], SPOUT_Y[1], FUN_Z_BOT - 1.4, "9 spout", above=False)
    d.dimv(FUN_Z_SPOUT, FUN_Z_TOP, STAND_W + 2.5, "10")
    d.dimv(FUN_Z_BOT, FUN_Z_SPOUT, STAND_W + 2.5, "4")
    d.dimv(FUN_Z_BOT, FUN_Z_TOP, -1.8, "14", left=True)
    d.text(STAND_W / 2, FUN_Z_TOP - 4.2, "3/8 ply sides at 50 deg", "", anchor="middle")
    d.text(SPOUT_Y[1] + 2, FUN_Z_BOT + 1.2, "sack cuff, bungee")
    d.text(0.75, 11.5, "leg", "", anchor="middle"); d.text(STAND_W - 0.75, 11.5, "leg", "", anchor="middle")
    return d.svg("Front elevation of the funnel between the front legs: 26 in mouth narrowing to an 11 in spout over 9 in, then 4 in of straight spout with the sack cuffed on it")

def funnel_side():
    d = Draw(-30, 10, 9.5, 36, s=9, pad=(14, 4, 4, 4))
    title(d, "Funnel, side section")
    d.rect(STAND_X0, 9.5, STAND_X0 + 3.5, 36, "lumber-far")
    d.rect(FUN_X1, FUN_Z_BOT, FUN_X0, FUN_Z_TOP, "funnel-face")
    d.rect(FUN_X0 - 0.375, FUN_Z_BOT, FUN_X0, FUN_Z_TOP, "ply")
    d.rect(FUN_X1, FUN_Z_BOT, FUN_X1 + 0.375, FUN_Z_TOP, "ply")
    d.line(FUN_X1 + 0.375, FUN_Z_SPOUT, FUN_X0 - 0.375, FUN_Z_SPOUT, "thin")
    d.rect(FUN_X0 - 1.125, FUN_Z_BOT, FUN_X0 - 0.375, FUN_Z_TOP, "batten")
    d.rect(FUN_X1 + 0.375, FUN_Z_BOT, FUN_X1 + 1.125, FUN_Z_TOP, "batten")
    _, mesh, lip, _, _, P = tray_pts(TILT)
    lx, lz = lip[1]; tx, tz = lip[0]
    d.line(tx, tz, lx, lz, "metal-solid")
    d.line(P(-3, MESH_Z)[0], P(-3, MESH_Z)[1], tx, tz, "mesh")
    d.dimh(FUN_X1, FUN_X0, FUN_Z_BOT - 1.2, "9 deep", above=False)
    d.dimv(FUN_Z_BOT, FUN_Z_TOP, FUN_X1 - 2, "14", left=True)
    d.text(lx - 0.8, lz + 1.2, "lip at full tilt", "", anchor="end")
    d.text(STAND_X0 + 4.2, 33.5, "tray front, tilted")
    d.text(STAND_X0 + 1.75, 11.5, "front leg", "", anchor="middle")
    d.text(FUN_X0 - 4.5, FUN_Z_SPOUT - 2.2, "spout", "", anchor="middle")
    d.text(FUN_X0 - 4.5, FUN_Z_TOP - 4.2, "1x2 cleats", "", anchor="middle")
    return d.svg("Side section of the funnel: 11 in deep with vertical back and front walls, 1x2 cleats in the corners, and the tray lip shown where it lands at full tilt")

svgs = dict(ga_rest=ga_rest(), ga_tilt=ga_tilt(), tray_plan=tray_plan(), tray_section=tray_section(),
            stand_back=stand_back(), stand_plan=stand_plan(), funnel_front=funnel_front(), funnel_side=funnel_side())

tpl = open(os.path.join(HERE, "page.html")).read()
for k, v in svgs.items():
    tpl = tpl.replace("{{%s}}" % k, v)
assert "{{" not in tpl, [l for l in tpl.splitlines() if "{{" in l]

os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT, "w").write(tpl)
print("wrote", OUT, len(tpl))
