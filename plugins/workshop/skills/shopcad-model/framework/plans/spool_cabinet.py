"""Spool Cabinet (example plan), revision D.1: one BILLY-width plywood case with two
IKEA OXBERG glass doors, four cradle-rail shelves of spools two rows deep, a
cubby and a desiccant bay.

Coordinates, inches: X left to right (0 at the outside of the left side),
Y front to back (0 at the case front; the doors sit at negative Y), Z up
from the floor under the plinth. shopcad's "north" is +Y here, so the
viewer's "north" preset looks at the cabinet's front.
"""

import math

from shopcad.geometry import Scene, box, cyl

NAME = "Spool Cabinet"
FUSION_NAME = "SpoolCabinet"

DEFAULTS = dict(
    bays=1, bay_w=30.0, cab_h=76.0, cab_d=18.0, ply=0.75, back_t=0.75,
    plinth_h=3.5, plinth_setback=2.0, bay_h=6.0, row_pitch=14.0, rows=4, cubby_z=62.0, shelf_d=17.0,
    rail1=1.5, rail2=6.5, riser1=10.0, riser2=15.0,
    spool_dia=8.0, spool_w=3.0, spool_pitch=4.0, spools_per_row=7,
    face_strip_w=2.5, door_w=15.5, door_h=75.75, door_t=0.75, door_frame_w=2.0, glass_t=0.16,
    door_open=105.0, ceiling=84.0,
)

STATES = {
    "closed": dict(label="Closed", description="Both OXBERG doors shut", doors_open=False),
    "open": dict(label="Doors open", description="Doors swung 105 degrees", doors_open=True),
    "shell": dict(label="Shell only", description="Doors and spools removed, structure only", doors_open=False, shell=True),
}
DEFAULT_STATE = "closed"
STEP_COMPONENTS = ["Case", "Plinth", "Shelves", "Door Left", "Door Right"]
VIEWS = {
    "closed": {"state": "closed", "view": "iso", "w": 1200, "h": 1200},
    "open": {"state": "open", "view": "iso-sw", "w": 1400, "h": 1200},
    "front": {"state": "open", "view": "north", "hide": "Door Left,Door Right", "w": 1000, "h": 1250},
    "shelf": {"state": "open", "focus": "Shelves,Spools", "dir": "se", "hide": "Door Left,Door Right,Case", "w": 1400, "h": 1000},
}

PLY = (214, 186, 138)
PLY_THIN = (222, 200, 160)
POPLAR = (232, 220, 190)
PINE = (226, 200, 150)
SPF = (222, 196, 140)
DOOR_FRAME = (245, 245, 240)
GLASS = (190, 220, 240)
SPOOL = (60, 110, 170)
SPOOL_FLAT = (120, 150, 190)
FAN = (70, 70, 75)
PAN = (200, 200, 205)


def _drop(gap, r):
    half = gap / 2
    return math.sqrt(max(r * r - half * half, 0.0))


def geometry(P):
    """Derived numbers shared by build() and checks()."""
    ply = P["ply"]
    nb = int(P["bays"])
    W = nb * P["bay_w"] + (nb + 1) * ply
    z0 = P["plinth_h"]
    floor = z0 + ply
    r = P["spool_dia"] / 2
    front_zc = 0.75 + _drop(P["rail2"] - P["rail1"], r)
    back_zc = 2.5 + _drop(P["riser2"] - P["riser1"], r)
    shelf_z = [floor + P["bay_h"] + i * P["row_pitch"] for i in range(int(P["rows"]))]
    return dict(W=W, z0=z0, floor=floor, inner_h=P["cab_h"] - 2 * ply, r=r, front_zc=front_zc, back_zc=back_zc,
                shelf_z=shelf_z, cubby=floor + P["cubby_z"])


def build(P, state):
    S = Scene(NAME)
    S.meta = {"state": state}
    G = geometry(P)
    ply, D, H = P["ply"], P["cab_d"], P["cab_h"]
    W, z0, floor, inner_h = G["W"], G["z0"], G["floor"], G["inner_h"]
    nb = int(P["bays"])
    bw = P["bay_w"]
    shell = state.get("shell", False)

    # plinth: 2x4 frame, set back at the front
    pw, pd, pt = W - 4.0, D - 3.0, 1.5
    px, py = 2.0, P["plinth_setback"]
    S.add("Plinth", "front 2x4", box((px, py, 0), (pw, pt, z0)), SPF)
    S.add("Plinth", "back 2x4", box((px, py + pd - pt, 0), (pw, pt, z0)), SPF)
    for i, x in enumerate((px, px + pw / 2 - pt / 2, px + pw - pt)):
        S.add("Plinth", "cross 2x4 %d" % (i + 1), box((x, py + pt, 0), (pt, pd - 2 * pt, z0)), SPF)

    # case
    S.add("Case", "side left", box((0, 0, z0), (ply, D, H)), PLY)
    S.add("Case", "side right", box((W - ply, 0, z0), (ply, D, H)), PLY)
    S.add("Case", "bottom", box((ply, 0, z0), (W - 2 * ply, D, ply)), PLY)
    S.add("Case", "top", box((ply, 0, z0 + H - ply), (W - 2 * ply, D, ply)), PLY)
    fsw = P["face_strip_w"]
    for b in range(1, nb):
        xp = ply + b * bw + (b - 1) * ply
        S.add("Case", "partition %d" % b, box((xp, ply, floor), (ply, D - ply, inner_h)), PLY)
        S.add("Case", "face strip %d" % b, box((xp + ply / 2 - fsw / 2, 0, floor), (fsw, ply, inner_h)), POPLAR)
    if nb == 1:
        S.add("Case", "center stile 1x3", box((W / 2 - fsw / 2, 0, floor), (fsw, ply, inner_h)), POPLAR)
    S.add("Case", "back", box((0, D, z0), (W, P["back_t"], H)), PLY_THIN)

    # shelves, rails, risers, cubby, desiccant, spools
    sd = P["shelf_d"]
    sy = ply
    rails, risers = (P["rail1"], P["rail2"]), (P["riser1"], P["riser2"])
    front_yc = sy + sum(rails) / 2
    back_yc = sy + sum(risers) / 2
    for b in range(nb):
        sx = ply + b * (bw + ply)
        for i, z in enumerate(G["shelf_z"]):
            S.add("Shelves", "shelf %d" % (i + 1), box((sx, sy, z), (bw, sd, ply)), PLY)
            top = z + ply
            for j, yc in enumerate(rails):
                S.add("Shelves", "shelf %d rail 1x2 %d" % (i + 1, j + 1), box((sx, sy + yc - 0.75, top), (bw, 1.5, 0.75)), PINE)
            for j, yc in enumerate(risers):
                S.add("Shelves", "shelf %d riser 2x3 %d" % (i + 1, j + 1), box((sx, sy + yc - 0.75, top), (bw, 1.5, 2.5)), SPF)
        cz = G["cubby"]
        S.add("Shelves", "cubby shelf", box((sx, sy, cz), (bw, sd, ply)), PLY)
        if shell:
            continue
        S.add("Desiccant", "gel pan", box((sx + 1.0, 2.0, floor), (18.0, 13.0, 1.0)), PAN)
        S.add("Desiccant", "120 mm USB fan", box((sx + bw - 6.0, 0.5, floor), (4.72, 1.0, 4.72)), FAN)
        n = int(P["spools_per_row"])
        x_start = sx + (bw - n * P["spool_pitch"]) / 2 + P["spool_pitch"] / 2
        for i, z in enumerate(G["shelf_z"]):
            top = z + ply
            for k in range(n):
                xc = x_start + k * P["spool_pitch"]
                S.add("Spools", "row %d front %d" % (i + 1, k + 1),
                      cyl((xc - P["spool_w"] / 2, front_yc, top + G["front_zc"]), "x", G["r"], P["spool_w"]), SPOOL)
                S.add("Spools", "row %d back %d" % (i + 1, k + 1),
                      cyl((xc - P["spool_w"] / 2, back_yc, top + G["back_zc"]), "x", G["r"], P["spool_w"]), SPOOL)
        for k in range(2):
            S.add("Spools", "cubby flat %d" % (k + 1),
                  cyl((sx + 1.0 + G["r"], sy + 0.5 + G["r"], cz + ply + k * P["spool_w"]), "z", G["r"], P["spool_w"]), SPOOL_FLAT)

    # doors: OXBERG pairs overlaying the front, hinged on their outer stiles
    dw, dh, dt, fw, gt = P["door_w"], P["door_h"], P["door_t"], P["door_frame_w"], P["glass_t"]
    pitch = W / (2 * nb)
    reveal = (H - dh) / 2
    ang = P["door_open"] if state.get("doors_open") else 0.0
    for k in range(2 * nb):
        left = (k % 2 == 0)
        comp = "Door Left" if left else "Door Right"
        if nb > 1:
            comp += " %d" % (k // 2 + 1)
        dx = k * pitch + (pitch - dw) / 2
        dz = z0 + reveal
        y = -dt
        pivot = (dx, 0.0) if left else (dx + dw, 0.0)
        rz = -ang if left else ang
        kw = dict(rz=rz, pivot=pivot)
        S.add(comp, "stile hinge side", box((dx if left else dx + dw - fw, y, dz), (fw, dt, dh), **kw), DOOR_FRAME)
        S.add(comp, "stile latch side", box((dx + dw - fw if left else dx, y, dz), (fw, dt, dh), **kw), DOOR_FRAME)
        S.add(comp, "rail bottom", box((dx + fw, y, dz), (dw - 2 * fw, dt, fw), **kw), DOOR_FRAME)
        S.add(comp, "rail top", box((dx + fw, y, dz + dh - fw), (dw - 2 * fw, dt, fw), **kw), DOOR_FRAME)
        S.add(comp, "tempered glass 4 mm", box((dx + fw - 0.25, y + dt / 2 - gt / 2, dz + fw - 0.25),
                                              (dw - 2 * fw + 0.5, gt, dh - 2 * fw + 0.5), **kw), GLASS, opacity=0.25)
    return S


def checks(P):
    G = geometry(P)
    out = []
    n = int(P["spools_per_row"])
    out.append(("spools fit the bay width", n * P["spool_pitch"] <= P["bay_w"],
                "%d x %g in pitch = %g in, bay %g in" % (n, P["spool_pitch"], n * P["spool_pitch"], P["bay_w"])))
    rim = (G["back_zc"] - G["front_zc"])
    out.append(("back row rim stands proud of the front row", rim >= 1.5, "%.2f in higher" % rim))
    clear = P["row_pitch"] - P["ply"] - (G["back_zc"] + G["r"])
    out.append(("spool top clears the shelf above", clear >= 1.0,
                "row pitch %g, back spool top at %.2f above the shelf, %.2f in clear" % (P["row_pitch"], G["back_zc"] + G["r"], clear)))
    depth_used = (P["riser1"] + P["riser2"]) / 2 + G["r"]
    out.append(("back spool inside the shelf depth", depth_used <= P["shelf_d"],
                "back spool reaches %.1f in from the front, shelf %g in" % (depth_used, P["shelf_d"])))
    top_of_rows = G["shelf_z"][-1] + P["ply"] + G["back_zc"] + G["r"]
    out.append(("cubby shelf clears the top row", G["cubby"] >= top_of_rows + 0.5,
                "cubby at %.2f, top spool at %.2f" % (G["cubby"], top_of_rows)))
    cubby_clear = (G["z0"] + P["cab_h"] - P["ply"]) - (G["cubby"] + P["ply"])
    out.append(("cubby takes a spool on edge", cubby_clear >= P["spool_dia"] + 0.5, "%.2f in clear" % cubby_clear))
    door_span = 2 * P["door_w"]
    out.append(("two OXBERG doors span the case", G["W"] - 1.0 <= door_span <= G["W"] + 0.5,
                "doors %g in, case %g in" % (door_span, G["W"])))
    out.append(("door height inside the case height", P["door_h"] <= P["cab_h"] - 0.25,
                "door %g in, case %g in, reveal %.3f in each end" % (P["door_h"], P["cab_h"], (P["cab_h"] - P["door_h"]) / 2)))
    total_h = G["z0"] + P["cab_h"]
    out.append(("stands under the ceiling", total_h <= P["ceiling"] - 1.0,
                "%.1f in tall, ceiling %g in" % (total_h, P["ceiling"])))
    cap = int(P["bays"]) * int(P["rows"]) * 2 * n
    out.append(("capacity (information)", True, "%d spools on rails" % cap))
    return out
