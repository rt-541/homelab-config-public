"""Garage Shop, revision B: the measured garage with every build placed per
sheet 02 of the drawing set.

Measured 2026-09-19: 18 ft across the overhead-door wall (16 ft door), 17 ft
of flat floor, then a 6 in concrete landing 3 ft deep and 15 ft wide across
the back (house) wall from the back-left corner, with the house door in
the middle of that wall standing on the landing behind a small step; the
exterior side door is on the east wall in the back-right corner with 3 ft
of flat floor in front of it; 12 ft ceiling.

Coordinates: X east (0 at the west wall), Y north (0 at the overhead-door
wall, 240 at the house wall), Z up, inches. Sheet 02 measures y from the
north wall, so N(y_from_north, depth) converts a plan-view position.

Everything a person would change is in DEFAULTS.
"""

import math

from shopcad.geometry import (BLUE, DRYWALL, GLASS, ORANGE, OSB, PLY, PLY_DARK, SLAB, STEEL, STEEL_DARK, STUD,
                              TOOL_BLACK, TOOL_YELLOW, TOTE_GREY, TOTE_LID, TRUCK, Scene, box, cyl)

NAME = "Garage Shop"
FUSION_NAME = "GarageShop"

DEFAULTS = dict(
    # room (measured)
    room_w=216.0, room_d=240.0, floor_d=204.0, ceiling=144.0, wall_t=4.5,
    door_x=12.0, door_w=192.0, door_h=84.0,
    house_door_x=92.0, house_door_w=32.0, house_door_h=80.0, step_w=36.0, step_d=12.0, step_h=4.0,
    side_door_yn=4.0, side_door_w=32.0, side_door_h=80.0,
    landing_x=0.0, landing_w=180.0, landing_d=36.0, landing_h=6.0,
    # vehicles (nose measured from the north wall; the nose overhangs the landing)
    truck_x=50.0, truck_nose=23.0, maverick_l=200.0, maverick_w=72.0, mirror_w=84.0, front_overhang=33.0,
    forester_l=182.0, forester_w=71.0, forester_nose=20.0,
    # sheet stock
    ply=0.75, osb=0.44, stud_t=1.5, stud_w=3.5,
    # tool cabinet (east wall)
    cab_yn=136.0, cab_w=48.0, cab_h=40.0, cab_d=12.0, cab_z=48.0, door_d=4.0, door_open=90.0,
    # flip bench (east wall, parked under the cabinet): table saw sunk in a fixed end section, miter saw on a
    # flip section in the middle, planer on a flip section at the other end; shaft along Y (the bench length)
    bench_yn=92.0, bench_d=30.0, bench_off=3.0, caster=3.0, shaft_h=30.5, bearing_h=4.5,
    sec_saw=24.0, sec_miter=32.0, sec_planer=30.0, panel_t=1.5, panel_h=29.0, apron_h=8.0, bay_gap=2.5,
    box_d=4.0, skin=0.75, plate_t=0.75, riser_h=4.5, concrete_miter=1.0, concrete_planer=2.5,
    plunger_off=10.0, hub_r=1.25, box_lb=35.0, riser_lb=22.0,
    planer_lb=92.0, planer_cg=9.0, miter_lb=56.0, miter_cg=7.0,
    ts_w=29.2, ts_l=22.7, ts_table_h=13.0, ts_lb=55.0,
    planer_w=24.0, planer_l=22.0, planer_h=20.0, miter_w=31.0, miter_l=24.5, miter_h=18.5,   # w across the bench (X), l along it (Y)
    # dust cart (east wall, parked end-on): two bays side by side on one base; the DeWalt DXV16P
    # 16 gal drum (own caster base removed) in a lipped bay at the wall end, the Dust Deputy bucket
    # on a 12 in pedestal at the room end with the spine and handle on the outer end
    dust_yn=210.0, dc_w=24.0, dc_len=38.0, dc_off=1.0, dc_base_t=1.5, dc_bay=24.0, dc_post_h=24.0, dc_rail_top=16.0,
    dc_ped_h=12.0, dc_spine_h=40.0, dc_spine_w=8.0, dc_caster=3.0,
    vac_r=9.75, vac_h=26.0, vac_inlet_z=20.0, bucket_r=5.95, bucket_h=14.5, cyclone_h=12.0, cradle=14.0,
    dc_cg_h=16.0, dc_weight=85.0,
    # tote rack (SE corner, against the east wall; compressor on its bottom level)
    # bulk rack on the landing in the back-left corner: bags two high on the landing under the first shelf, totes above
    bulk_w=42.0, bulk_d=24.0, bulk_h=84.0, bulk_levels=(24.0, 42.0, 60.0, 78.0),
    tote_l=31.0, tote_w=20.0, tote_h=15.0,
    # garden station (west wall, back corner; its back 36 in stands on the landing)
    # potting station (west wall, front): counter with a pot well and a sunken soil bin
    pot_y0=2.0, pot_w=48.0, pot_d=24.0, pot_h=36.0, bag_shelf=6.0, well_dia=14.0, well_x=10.0, well_from_y0=12.0,
    well_levels=(22.0, 26.0, 30.0), well_level=1, pot_dia=10.0, pot_h_in=10.0, bin_w=16.0, bin_l=12.0, bin_h=12.0,
    splash_h=6.0, upper_shelf=56.0, upper_d=12.0, upper_w=48.0,
    # machine bay behind it, nose to the wall (42 out, 26 along the wall), ends before the truck's rear door swing
    bay_y0=52.0, bay_w=42.0, bay_l=26.0, machine_h=40.0,
    # electrical and fixtures
    panel_yn=43.75, panel_w=14.5, panel_hh=30.0, panel_center=60.0, ws_w=30.0, ws_d=36.0,
    comp_w=19.0, comp_d=19.0, comp_h=20.0, comp_yn=189.0,
    rail_y0=84.0, rail_y1=140.0, rail_z=72.0,
    # garage door opener: rail on the ceiling centreline, motor at its back end, button beside the house door
    opener_x=116.0, opener_len=130.0, opener_z=94.0, motor_l=20.0, button_x=130.0,
    bike_x=(84.0, 124.0), bike_y=60.0,
    evse_y=150.0, evse_z=66.0,   # east wall, above the parked flip-top; short 6/3 run from the sub
    lights=((30.0, 10.0), (30.0, 180.0), (172.0, 60.0), (172.0, 116.0)), light_l=48.0,   # (x, y0): two over the plant side, two over the work zone
    hoist_z=96.0,
)

STATES = {
    "closed": dict(label="Closed up", description="Cabinet locked, bench flat (tools down), no vehicle", doors_open=False,
                   miter_up=False, planer_up=False, truck="none"),
    "open": dict(label="Working", description="Cabinet open, miter saw and planer up, no vehicle", doors_open=True,
                 miter_up=True, planer_up=True, truck="none"),
    "miter": dict(label="Miter station", description="Miter saw up, planer down as its outfeed wing", doors_open=False,
                  miter_up=True, planer_up=False, truck="none"),
    "planer": dict(label="Planing", description="Planer up, miter down as its infeed", doors_open=False,
                   miter_up=False, planer_up=True, truck="none"),
    "maverick": dict(label="Maverick parked", description="Truck in, nose over the landing, bench flat", doors_open=False,
                     miter_up=False, planer_up=False, truck="maverick"),
    "forester": dict(label="Forester parked", description="Forester in, bench flat", doors_open=False,
                     miter_up=False, planer_up=False, truck="forester"),
}
DEFAULT_STATE = "closed"
STEP_COMPONENTS = ["Tool Cabinet", "Door North", "Door South", "Flip Bench", "Dust Cart", "Potting Station", "Bulk Rack"]
ALL_COMPONENTS = ["Landing", "Wall North", "Wall West", "Wall East", "Wall South", "Truck", "Bike Hoists", "Tool Cabinet",
                  "Door North", "Door South", "Flip Bench", "Dust Cart", "Bulk Rack", "Compressor", "Potting Station",
                  "Machine Bay", "Wall Hooks", "Subpanel", "Heater", "Ceiling Lights", "Garage Opener"]


def _solo(keep):
    """Hide list that leaves only `keep` and the slab."""
    return ",".join(c for c in ALL_COMPONENTS if c != keep)


VIEWS = {
    "iso": {"state": "closed", "hide": "Truck,Wall South,Wall East,Ceiling Lights"},
    "iso-open": {"state": "open", "view": "iso", "hide": "Truck,Wall South,Wall East,Ceiling Lights"},
    "iso-nw": {"state": "closed", "view": "iso-nw", "hide": "Truck,Wall North,Wall West,Ceiling Lights"},
    "plan": {"state": "closed", "view": "plan", "hide": "Truck,Ceiling Lights,Heater,Bike Hoists"},
    "east": {"state": "open", "view": "east", "hide": "Truck,Wall West,Wall South,Ceiling Lights,Potting Station,Machine Bay"},
    "west": {"state": "closed", "view": "west", "hide": "Truck,Wall East,Wall South,Ceiling Lights,Tool Cabinet,Door North,Door South,Flip Bench,Dust Cart,Compressor,Bulk Rack"},
    "north": {"state": "open", "view": "north", "hide": "Truck,Wall South,Ceiling Lights"},
    # the shop wall as a group, from the southwest so the open cabinet, the bench with both tools up and the
    # carts in the front corner all read at once; bikes and opener would hang in front of the camera
    "shop": {"state": "open", "focus": "Tool Cabinet,Door North,Door South,Flip Bench,Dust Cart,Compressor,Subpanel", "dir": "sw", "elev": 0.5,
             "hide": "Truck,Wall South,Wall West,Ceiling Lights,Bike Hoists,Garage Opener,Potting Station,Machine Bay,Wall Hooks,Bulk Rack", "w": 1600, "h": 1000},
    "cabinet": {"state": "open", "focus": "Tool Cabinet,Door North,Door South", "dir": "sw", "hide": "Truck,Wall South,Ceiling Lights,Flip Bench,Bike Hoists,Garage Opener", "w": 1400, "h": 1000},
    "dust": {"state": "open", "focus": "Dust Cart", "dir": "sw", "hide": "Truck,Wall South,Ceiling Lights,Tool Cabinet,Door North,Door South", "w": 1400, "h": 1000},
    # the whole 15 ft slab straight on from the south, nothing standing on or hanging over it
    "landing": {"state": "closed", "focus": "Landing", "dir": "s", "elev": 0.6, "zoom": 0.55, "hide": "Truck,Wall South,Wall East,Wall West,Ceiling Lights,Bike Hoists,Garage Opener,Wall Hooks,Machine Bay,Potting Station,Bulk Rack,Heater,Tool Cabinet,Door North,Door South,Dust Cart,Flip Bench,Compressor,Subpanel", "w": 1600, "h": 900},
    # isolated detail views for the sub pages: only the component, on the slab
    **{"flip-" + k: dict(state=st, focus="Flip Bench", dir=d, elev=e, hide=_solo("Flip Bench"), w=1500, h=1000)
       for k, (st, d, e) in {"bench-sw": ("closed", "sw", 0.45), "miter-sw": ("miter", "sw", 0.45), "planer-sw": ("planer", "sw", 0.45),
                             "both-ne": ("open", "ne", 0.45), "end": ("miter", "s", 0.2), "side": ("open", "w", 0.2), "top": ("open", "sw", 1.6)}.items()},
    **{"dust-" + k: dict(state="open", focus="Dust Cart", dir=d, elev=e, hide=_solo("Dust Cart"), w=1400, h=1000)
       for k, (d, e) in {"sw": ("sw", 0.45), "ne": ("ne", 0.45), "side": ("s", 0.2), "end": ("w", 0.2), "top": ("sw", 1.6)}.items()},
    "station": {"state": "open", "focus": "Potting Station", "dir": "se", "hide": "Wall South,Ceiling Lights,Truck,Bike Hoists,Garage Opener", "w": 1400, "h": 1000},
    "station-well": {"state": "open", "focus": "Potting Station", "dir": "e", "elev": 1.2, "hide": _solo("Potting Station"), "w": 1400, "h": 1000},
    "opener": {"state": "closed", "focus": "Garage Opener,Bike Hoists", "dir": "se", "elev": 0.35, "hide": "Wall South,Wall East,Wall West,Ceiling Lights,Truck,Potting Station,Machine Bay,Wall Hooks,Bulk Rack,Flip Bench,Dust Cart,Compressor,Tool Cabinet,Door North,Door South,Subpanel,Heater", "w": 1600, "h": 1000},
    "rack": {"state": "open", "focus": "Bulk Rack", "dir": "se", "hide": "Wall South,Ceiling Lights,Truck,Bike Hoists,Garage Opener", "w": 1400, "h": 1000},
}


def N(P, yn, depth):
    """Y origin of a thing whose plan-view y (from the north wall) is yn and that is depth deep."""
    return P["room_d"] - yn - depth


def build(P, state):
    S = Scene(NAME)
    S.meta = {"state": state}
    W, D, H, T = P["room_w"], P["room_d"], P["ceiling"], P["wall_t"]
    ply = P["ply"]
    st, sw = P["stud_t"], P["stud_w"]
    LH = P["landing_h"]

    # ---------------- room ----------------
    S.add("Slab", "slab", box((-T, -T, -4), (W + 2 * T, D + 2 * T, 4)), SLAB)
    S.add("Landing", "landing", box((P["landing_x"], D - P["landing_d"], 0), (P["landing_w"], P["landing_d"], LH)), (92, 88, 84))
    S.add("Wall North", "north wall", box((-T, D, 0), (W + 2 * T, T, H)), DRYWALL,
          cuts=[box((P["house_door_x"], D - 1, 0), (P["house_door_w"], T + 2, P["house_door_h"]))])
    S.add("Wall West", "west wall", box((-T, 0, 0), (T, D, H)), DRYWALL)
    sd_y = N(P, P["side_door_yn"], P["side_door_w"])
    S.add("Wall East", "east wall", box((W, 0, 0), (T, D, H)), DRYWALL,
          cuts=[box((W - 1, sd_y, 0), (T + 2, P["side_door_w"], P["side_door_h"]))])
    S.add("Landing", "door step", box((P["house_door_x"] + P["house_door_w"] / 2 - P["step_w"] / 2, D - P["step_d"], LH), (P["step_w"], P["step_d"], P["step_h"])), (64, 60, 58))
    S.add("Wall South", "south return west", box((-T, -T, 0), (P["door_x"] + T, T, H)), DRYWALL)
    S.add("Wall South", "south return east", box((P["door_x"] + P["door_w"], -T, 0), (W - P["door_x"] - P["door_w"] + T, T, H)), DRYWALL)
    S.add("Wall South", "door header", box((P["door_x"], -T, P["door_h"]), (P["door_w"], T, H - P["door_h"])), DRYWALL)

    # ---------------- vehicle ----------------
    truck = state.get("truck", "maverick")
    if truck == "maverick":
        L, Wb = P["maverick_l"], P["maverick_w"]
        x0, nose = P["truck_x"], P["truck_nose"]
        y_nose = D - nose
        hood, cab, bed = 55.0, 80.0, L - 135.0
        S.add("Truck", "hood", box((x0, y_nose - hood, 12), (Wb, hood, 32)), TRUCK, opacity=0.45)
        S.add("Truck", "cab", box((x0, y_nose - hood - cab, 12), (Wb, cab, 56)), TRUCK, opacity=0.45)
        S.add("Truck", "bed", box((x0, y_nose - L, 12), (Wb, bed, 40)), TRUCK, opacity=0.45)
        for i, ya in enumerate((y_nose - P["front_overhang"], y_nose - P["front_overhang"] - 121.0)):
            for xs in (x0 - 1, x0 + Wb - 8):
                S.add("Truck", "wheel %d" % (i * 2 + (xs > x0 + 1)), cyl((xs, ya, 14), "x", 14, 9), STEEL_DARK, opacity=0.6)
        mw = (P["mirror_w"] - Wb) / 2
        S.add("Truck", "mirror L", box((x0 - mw, y_nose - hood - 8, 40), (mw, 6, 6)), TRUCK, opacity=0.45)
        S.add("Truck", "mirror R", box((x0 + Wb, y_nose - hood - 8, 40), (mw, 6, 6)), TRUCK, opacity=0.45)
    elif truck == "forester":
        L, Wb = P["forester_l"], P["forester_w"]
        x0, nose = P["truck_x"], P["forester_nose"]
        y_nose = D - nose
        hood, cabin = 45.0, 80.0
        S.add("Truck", "hood", box((x0, y_nose - hood, 12), (Wb, hood, 33)), TRUCK, opacity=0.45)
        S.add("Truck", "cabin", box((x0, y_nose - hood - cabin, 12), (Wb, cabin, 56)), TRUCK, opacity=0.45)
        S.add("Truck", "cargo", box((x0, y_nose - L, 12), (Wb, L - hood - cabin, 54)), TRUCK, opacity=0.45)
        for i, ya in enumerate((y_nose - 36.0, y_nose - 36.0 - 105.0)):
            for xs in (x0 - 1, x0 + Wb - 8):
                S.add("Truck", "wheel %d" % (i * 2 + (xs > x0 + 1)), cyl((xs, ya, 14), "x", 14, 9), STEEL_DARK, opacity=0.6)

    # garage door opener: rail from the door header back along the ceiling centreline, motor at its end, wall button by the house door
    ox, oz = P["opener_x"], P["opener_z"]
    S.add("Garage Opener", "rail", box((ox - 1.5, 0, oz), (3, P["opener_len"], 3)), STEEL_DARK)
    S.add("Garage Opener", "motor", box((ox - 10, P["opener_len"] - P["motor_l"], oz - 6), (20, P["motor_l"], 14)), STEEL_DARK)
    S.add("Garage Opener", "hanger 1", box((ox - 0.75, P["opener_len"] - 4, oz + 3), (1.5, 1.5, H - oz - 3)), STEEL)
    S.add("Garage Opener", "hanger 2", box((ox - 0.75, P["opener_len"] - P["motor_l"] + 2, oz + 3), (1.5, 1.5, H - oz - 3)), STEEL)
    S.add("Garage Opener", "wall button", box((P["button_x"], D - 1.0, 58), (3, 1, 4.5)), ORANGE)
    # bike hoists either side of the opener rail, above the truck's cab
    for i, bx in enumerate(P["bike_x"]):
        S.add("Bike Hoists", "bike %d" % (i + 1), box((bx, P["bike_y"], P["hoist_z"]), (24, 68, 40)), STEEL, opacity=0.5)

    # ---------------- tool cabinet (east wall, faces west) ----------------
    cleat = 2 * ply  # wall cleat + case cleat stack behind the back
    cx = W - cleat - P["cab_d"]
    cy = N(P, P["cab_yn"], P["cab_w"])
    cz, cw, ch, cd = P["cab_z"], P["cab_w"], P["cab_h"], P["cab_d"]
    wb = W - cleat  # back face against the cleats
    S.add("Tool Cabinet", "back", box((wb - ply, cy, cz), (ply, cw, ch)), PLY)
    S.add("Tool Cabinet", "bottom", box((cx, cy, cz), (cd - ply, cw, ply)), PLY)
    S.add("Tool Cabinet", "top", box((cx, cy, cz + ch - ply), (cd - ply, cw, ply)), PLY)
    S.add("Tool Cabinet", "side south", box((cx, cy, cz), (cd - ply, ply, ch)), PLY)
    S.add("Tool Cabinet", "side north", box((cx, cy + cw - ply, cz), (cd - ply, ply, ch)), PLY)
    for k, zz in enumerate((12.0, 24.0)):
        S.add("Tool Cabinet", "shelf %d" % (k + 1), box((cx + ply, cy + ply, cz + zz), (cd - 2 * ply - ply, cw - 2 * ply, ply)), PLY)
    S.add("Tool Cabinet", "case cleat", box((wb, cy + ply, cz + ch - 5), (ply, cw - 2 * ply, 4)), PLY_DARK)
    S.add("Tool Cabinet", "wall cleat", box((W - ply, cy + 2, cz + ch - 5), (ply, cw - 4, 4)), PLY_DARK)
    S.add("Tool Cabinet", "spacer", box((wb, cy + ply, cz), (ply, cw - 2 * ply, 4)), PLY_DARK)
    S.add("Tool Cabinet", "LBT rack", box((cx + 2, cy + 11, cz + 26), (8, 26, 13)), STEEL_DARK)
    tools = [("circ saw", 9, 8), ("router", 7, 8), ("nailer", 8, 9), ("charger", 7, 4), ("charger 2", 7, 4)]
    yy = cy + 2
    for name, tw, th in tools:
        S.add("Tool Cabinet", name, box((cx + 2, yy, cz + ply), (8, tw, th)), TOOL_YELLOW if "charger" not in name else TOOL_BLACK)
        yy += tw + 1
    tools2 = [("jigsaw", 9, 8), ("sander", 7, 7), ("oscillating", 6, 6), ("light", 6, 6)]
    yy = cy + 2
    for name, tw, th in tools2:
        S.add("Tool Cabinet", name, box((cx + 2, yy, cz + 12 + ply), (8, tw, th)), TOOL_YELLOW)
        yy += tw + 1
    for i in range(3):
        S.add("Tool Cabinet", "battery %d" % (i + 1), box((cx + 3, yy + i * 4, cz + 12 + ply), (5, 3, 5)), TOOL_BLACK)
    # door boxes: north door hinged at Y = cy + cw, south door at Y = cy
    dd, hd = P["door_d"], cw / 2
    ang = P["door_open"] if state.get("doors_open") else 0.0
    dx = cx - dd
    for side, y0, pivot, sign in (("Door South", cy, (cx, cy), 1), ("Door North", cy + hd, (cx, cy + cw), -1)):
        rz = sign * ang
        lip = ply if side == "Door North" else 0.0
        S.add(side, "face", box((dx, y0 - (lip if side == "Door North" else 0), cz), (ply, hd + lip, ch), rz=rz, pivot=pivot), PLY)
        S.add(side, "rail bottom", box((dx + ply, y0, cz), (dd - ply, hd, ply), rz=rz, pivot=pivot), PLY)
        S.add(side, "rail top", box((dx + ply, y0, cz + ch - ply), (dd - ply, hd, ply), rz=rz, pivot=pivot), PLY)
        S.add(side, "rail hinge", box((dx + ply, y0 if side == "Door South" else y0 + hd - ply, cz), (dd - ply, ply, ch), rz=rz, pivot=pivot), PLY)
        S.add(side, "rail meeting", box((dx + ply, y0 + hd - ply if side == "Door South" else y0, cz), (dd - ply, ply, ch), rz=rz, pivot=pivot), PLY)
        for k in range(4):
            S.add(side, "cleat strip %d" % (k + 1), box((dx + ply, y0 + 2, cz + 8 + k * 8), (0.5, hd - 4, 2.5), rz=rz, pivot=pivot), PLY_DARK)
    for k, zz in enumerate((6.0, ch - 8.0)):
        S.add("Tool Cabinet", "hasp %d" % (k + 1), box((dx - 0.4, cy + hd - 3.6, cz + zz), (0.4, 7.25, 2)), STEEL_DARK)

    # ---------------- flip bench (parked along the east wall, length along Y) ----------------
    bd, pt, gap = P["bench_d"], P["panel_t"], P["bay_gap"]
    secs = (("saw", P["sec_saw"]), ("miter", P["sec_miter"]), ("planer", P["sec_planer"]))
    bl = 4 * pt + sum(l for _, l in secs)
    fx = W - P["bench_off"] - bd
    fy = N(P, P["bench_yn"], bl)
    cxm = fx + bd / 2
    casz = P["caster"] + 1.0
    S.add("Flip Bench", "base rail W", box((fx, fy, casz), (sw, bl, st)), STUD)
    S.add("Flip Bench", "base rail E", box((fx + bd - sw, fy, casz), (sw, bl, st)), STUD)
    # panels: S, A (saw|miter), B (miter|planer), C (north end), each on a cross rail
    ys = [fy]
    for _, l in secs:
        ys.append(ys[-1] + pt + l)
    pz = casz + st
    for name, yy in zip("SABC", ys):
        S.add("Flip Bench", "cross rail %s" % name, box((fx + sw, yy, casz), (bd - 2 * sw, pt, st)), STUD)
        S.add("Flip Bench", "end panel %s" % name, box((fx, yy, pz), (bd, pt, P["panel_h"])), PLY)
    for i, (xx, yy2) in enumerate(((fx + 3, fy + 3), (fx + bd - 3, fy + 3), (fx + 3, fy + bl / 2), (fx + bd - 3, fy + bl / 2), (fx + 3, fy + bl - 3), (fx + bd - 3, fy + bl - 3))):
        S.add("Flip Bench", "caster %d" % (i + 1), cyl((xx, yy2 - 1, 0), "y", P["caster"] / 2, 2), STEEL_DARK)
        S.add("Flip Bench", "caster plate %d" % (i + 1), box((xx - 2, yy2 - 2, P["caster"]), (4, 4, 1)), STEEL)
    S.add("Flip Bench", "apron", box((fx + bd - ply, fy + pt, pz), (ply, bl - 2 * pt, P["apron_h"])), PLY)
    sh, bxd, sk, tp, rh = P["shaft_h"], P["box_d"], P["skin"], P["plate_t"], P["riser_h"]
    H = sh + bxd / 2 + tp + rh                       # bench top, miter table and saw table height
    # --- fixed saw section: top at H with the DWE7491 sunk so its table is flush; shelves below
    y_saw = ys[0] + pt
    tsw, tsl, tsh = P["ts_w"], P["ts_l"], P["ts_table_h"]
    S.add("Flip Bench", "saw section top", box((fx, y_saw, H - ply), (bd, P["sec_saw"], ply)), PLY,
          cuts=[box((cxm - tsw / 2 - 0.25, y_saw + (P["sec_saw"] - tsl) / 2 - 0.25, H - ply - 0.1), (tsw + 0.5, tsl + 0.5, ply + 0.2))])
    S.add("Flip Bench", "saw well platform", box((fx + ply, y_saw, H - tsh - ply), (bd - 2 * ply, P["sec_saw"], ply)), PLY)
    S.add("Flip Bench", "DWE7491 body", box((cxm - tsw / 2, y_saw + (P["sec_saw"] - tsl) / 2, H - tsh), (tsw, tsl, tsh - 1.0)), TOOL_YELLOW, opacity=0.95)
    S.add("Flip Bench", "DWE7491 table", box((cxm - tsw / 2, y_saw + (P["sec_saw"] - tsl) / 2, H - 1.0), (tsw, tsl, 1.0)), STEEL)
    S.add("Flip Bench", "saw blade", box((cxm + 2, y_saw + P["sec_saw"] / 2 - 5, H), (0.125, 10, 3)), STEEL_DARK)
    S.add("Flip Bench", "rip fence", box((cxm - tsw / 2, y_saw + 2, H), (tsw, 1.5, 2.5)), TOOL_YELLOW)
    for k, zz in enumerate((6.0, 15.0)):
        S.add("Flip Bench", "saw shelf %d" % (k + 1), box((fx + ply, y_saw, zz), (bd - 2 * ply, P["sec_saw"], ply)), PLY)
    # --- flip sections
    up_flags = {"miter": state.get("miter_up", False), "planer": state.get("planer_up", False)}
    tools = {"miter": (P["miter_w"], P["miter_l"], P["miter_h"], "DCS785 miter", P["concrete_miter"]),
             "planer": (P["planer_w"], P["planer_l"], P["planer_h"], "DW735 planer", P["concrete_planer"])}
    po = P["plunger_off"]
    for idx, (name, seclen) in enumerate(secs[1:], start=1):
        y_bay = ys[idx] + pt                            # bay between panel idx and idx+1
        y_box = y_bay + gap
        boxl = seclen - 2 * gap
        bx0, bz0 = cxm - bd / 2, sh - bxd / 2
        tw, tl, th, tname, conc = tools[name]
        up = up_flags[name]
        S.add("Flip Bench", "%s box skin top" % name, box((bx0, y_box + ply, bz0 + bxd - sk), (bd, boxl - 2 * ply, sk)), PLY)
        S.add("Flip Bench", "%s box skin bottom" % name, box((bx0, y_box + ply, bz0), (bd, boxl - 2 * ply, sk)), PLY)
        for nm, yy5 in (("S", y_box), ("N", y_box + boxl - ply)):
            S.add("Flip Bench", "%s box end plate %s" % (name, nm), box((bx0, yy5, bz0), (bd, ply, bxd)), PLY,
                  cuts=[cyl((cxm + po, yy5 - 0.1, sh), "y", 0.4, ply + 0.2), cyl((cxm - po, yy5 - 0.1, sh), "y", 0.4, ply + 0.2)])
        for k, rx_ in enumerate((cxm - 8, cxm + 8 - ply)):
            S.add("Flip Bench", "%s box rib %d" % (name, k + 1), box((rx_, y_box + ply, bz0 + sk), (ply, boxl - 2 * ply, bxd - 2 * sk)), PLY_DARK)
        S.add("Flip Bench", "%s shaft" % name, cyl((cxm, ys[idx] + pt - 0.5, sh), "y", 0.5, seclen + 1.0), STEEL_DARK)
        S.add("Flip Bench", "%s hub S" % name, cyl((cxm, y_box - 0.5, sh), "y", P["hub_r"], 0.5), STEEL)
        S.add("Flip Bench", "%s hub N" % name, cyl((cxm, y_box + boxl, sh), "y", P["hub_r"], 0.5), STEEL)
        # bearings on the panel faces inside the bay
        S.add("Flip Bench", "%s bearing S" % name, box((cxm - P["bearing_h"] / 2, y_bay, sh - P["bearing_h"] / 2), (P["bearing_h"], 1.5, P["bearing_h"])), STEEL)
        S.add("Flip Bench", "%s bearing N" % name, box((cxm - P["bearing_h"] / 2, y_bay + seclen - 1.5, sh - P["bearing_h"] / 2), (P["bearing_h"], 1.5, P["bearing_h"])), STEEL)
        # plunger through the outer panel, latch on the shared panel B
        if name == "miter":
            py_ = ys[idx]                                # panel A, plunger enters from the saw side
            S.add("Flip Bench", "miter index plunger", cyl((cxm + po, py_ - 2.0, sh), "y", 0.375, pt + 2.0 + gap), STEEL_DARK)
            S.add("Flip Bench", "miter plunger knob", cyl((cxm + po, py_ - 3.2, sh), "y", 0.8, 1.2), ORANGE)
            S.add("Flip Bench", "miter draw latch", box((cxm - po - 1.5, ys[idx + 1] - 1.0, sh - 1.0), (3.0, 1.0, 2.0)), STEEL)
        else:
            py_ = ys[idx + 1] + pt                       # panel C, plunger enters from the north end
            S.add("Flip Bench", "planer index plunger", cyl((cxm + po, py_ - pt - gap, sh), "y", 0.375, pt + 2.0 + gap), STEEL_DARK)
            S.add("Flip Bench", "planer plunger knob", cyl((cxm + po, py_ + 2.0, sh), "y", 0.8, 1.2), ORANGE)
            S.add("Flip Bench", "planer draw latch", box((cxm - po - 1.5, ys[idx] + pt, sh - 1.0), (3.0, 1.0, 2.0)), STEEL)
        # tool plate on one face, riser bench top (with cast concrete) on the other
        if up:
            S.add("Flip Bench", "%s tool plate" % name, box((bx0, y_box, bz0 + bxd), (bd, boxl, tp)), PLY)
            S.add("Flip Bench", tname, box((cxm - tw / 2, y_box + (boxl - tl) / 2, bz0 + bxd + tp), (tw, tl, th)), TOOL_YELLOW)
            rz0 = bz0 - tp - rh
            S.add("Flip Bench", "%s riser plate" % name, box((bx0, y_box, bz0 - tp), (bd, boxl, tp)), PLY)
        else:
            S.add("Flip Bench", "%s tool plate" % name, box((bx0, y_box, bz0 - tp), (bd, boxl, tp)), PLY)
            S.add("Flip Bench", tname, box((cxm - tw / 2, y_box + (boxl - tl) / 2, bz0 - tp - th), (tw, tl, th)), TOOL_YELLOW)
            rz0 = bz0 + bxd + tp
            S.add("Flip Bench", "%s riser plate" % name, box((bx0, y_box, bz0 + bxd), (bd, boxl, tp)), PLY)
        S.add("Flip Bench", "%s riser top" % name, box((bx0, y_box, rz0 + rh - ply if not up else rz0), (bd, boxl, ply)), PLY)
        S.add("Flip Bench", "%s riser side W" % name, box((bx0, y_box, rz0), (ply, boxl, rh)), PLY)
        S.add("Flip Bench", "%s riser side E" % name, box((bx0 + bd - ply, y_box, rz0), (ply, boxl, rh)), PLY)
        S.add("Flip Bench", "%s riser end S" % name, box((bx0, y_box, rz0), (bd, ply, rh)), PLY)
        S.add("Flip Bench", "%s riser end N" % name, box((bx0, y_box + boxl - ply, rz0), (bd, ply, rh)), PLY)
        cz0 = (rz0 + rh - ply - conc) if not up else (rz0 + ply)
        S.add("Flip Bench", "%s concrete ballast" % name, box((bx0 + ply, y_box + ply, cz0), (bd - 2 * ply, boxl - 2 * ply, conc)), SLAB)

    # ---------------- dust cart (parked end-on at the east wall; vac bay at the wall, pedestal toward the room) ----------------
    dw, dl = P["dc_w"], P["dc_len"]           # width along Y, length along X
    kx = W - P["dc_off"] - dl
    ky = N(P, P["dust_yn"], dw)
    kz = P["dc_caster"] + 1.0                 # top of the caster plates
    bt = P["dc_base_t"]
    S.add("Dust Cart", "base", box((kx, ky, kz), (dl, dw, bt)), PLY_DARK)
    for i, (xx, yy8) in enumerate(((kx + 2, ky + 2), (kx + dl - 2, ky + 2), (kx + 2, ky + dw - 2), (kx + dl - 2, ky + dw - 2))):
        S.add("Dust Cart", "caster %d" % (i + 1), cyl((xx, yy8 - 1, 0), "y", P["dc_caster"] / 2, 2), STEEL_DARK)
        S.add("Dust Cart", "caster plate %d" % (i + 1), box((xx - 1.75, yy8 - 1.75, P["dc_caster"]), (3.5, 3.5, 1)), STEEL)
    sz = kz + bt
    bay = P["dc_bay"]
    bx0 = kx + dl - bay                       # vac bay from the wall end inward
    # 2x4 corral around the drum: four posts, a ring on flat at the base, a ring on edge at 16 in
    ph_ = P["dc_post_h"]
    for i, (xx, yy9) in enumerate(((bx0, ky), (bx0 + bay - st, ky), (bx0, ky + dw - sw), (bx0 + bay - st, ky + dw - sw))):
        S.add("Dust Cart", "post %d" % (i + 1), box((xx, yy9, sz), (st, sw, ph_)), STUD)
    rail_in = bay - 2 * st
    for nm, z0, hgt, thick in (("bottom", sz, st, sw), ("top", sz + P["dc_rail_top"] - sw, sw, st)):
        S.add("Dust Cart", "rail %s S" % nm, box((bx0 + st, ky, z0), (rail_in, thick, hgt)), STUD)
        S.add("Dust Cart", "rail %s N" % nm, box((bx0 + st, ky + dw - thick, z0), (rail_in, thick, hgt)), STUD)
        S.add("Dust Cart", "rail %s E" % nm, box((bx0 + bay - thick, ky + sw, z0), (thick, dw - 2 * sw, hgt)), STUD)
        S.add("Dust Cart", "rail %s W" % nm, box((bx0, ky + sw, z0), (thick, dw - 2 * sw, hgt)), STUD)
    # pedestal: two sides, a wall shared with the bay, the cradle top with its U open toward the bay
    ph = P["dc_ped_h"]
    px0, pl = kx, dl - bay
    S.add("Dust Cart", "pedestal side S", box((px0, ky, sz), (pl, ply, ph)), PLY)
    S.add("Dust Cart", "pedestal side N", box((px0, ky + dw - ply, sz), (pl, ply, ph)), PLY)
    S.add("Dust Cart", "pedestal wall", box((bx0 - ply, ky + ply, sz), (ply, dw - 2 * ply, ph)), PLY)
    S.add("Dust Cart", "spine", box((px0, ky + (dw - P["dc_spine_w"]) / 2, sz), (ply, P["dc_spine_w"], P["dc_spine_h"])), PLY,
          cuts=[box((px0 - 1, ky + (dw - P["dc_spine_w"]) / 2 + 1.5, sz + P["dc_spine_h"] - 3.5), (ply + 2, P["dc_spine_w"] - 3, 1.5))])
    cz = sz + ph
    cx0, cy0 = px0 + pl / 2, ky + dw / 2
    S.add("Dust Cart", "bucket cradle", box((px0, ky, cz), (pl, dw, ply)), PLY_DARK,
          cuts=[cyl((cx0, cy0, cz - 0.1), "z", P["bucket_r"] + 0.06, ply + 0.2),
                box((cx0, cy0 - P["bucket_r"] - 0.06, cz - 0.1), (pl / 2 + 0.1, 2 * P["bucket_r"] + 0.12, ply + 0.2))])
    bz = cz + ply
    S.add("Dust Cart", "5 gal bucket", cyl((cx0, cy0, bz), "z", P["bucket_r"], P["bucket_h"]), STEEL, opacity=0.85)
    S.add("Dust Cart", "bucket lid", cyl((cx0, cy0, bz + P["bucket_h"]), "z", P["bucket_r"] + 0.4, 1.0), TOOL_BLACK)
    S.add("Dust Cart", "Dust Deputy cyclone", cyl((cx0, cy0, bz + P["bucket_h"] + 1.0), "z", 4.2, P["cyclone_h"] - 2), TOOL_BLACK, opacity=0.9)
    S.add("Dust Cart", "cyclone inlet", cyl((cx0, cy0 - 4.2 - 4, bz + P["bucket_h"] + P["cyclone_h"] - 3), "y", 1.3, 4), ORANGE)
    S.add("Dust Cart", "cyclone outlet", cyl((cx0, cy0, bz + P["bucket_h"] + P["cyclone_h"] - 1), "z", 1.3, 3), ORANGE)
    S.add("Dust Cart", "bucket strap", cyl((cx0, cy0, bz + P["bucket_h"] / 2), "z", P["bucket_r"] + 0.35, 1.0), ORANGE,
          cuts=[cyl((cx0, cy0, bz + P["bucket_h"] / 2 - 0.1), "z", P["bucket_r"] + 0.05, 1.2)])
    # the 16 gal drum in its bay, head on, inlet facing the pedestal
    vx, vy = bx0 + bay / 2, ky + dw / 2
    S.add("Dust Cart", "DXV16P drum", cyl((vx, vy, sz), "z", P["vac_r"], P["vac_h"] - 6), TOOL_YELLOW, opacity=0.95)
    S.add("Dust Cart", "DXV16P head", cyl((vx, vy, sz + P["vac_h"] - 6), "z", P["vac_r"] + 0.5, 6), TOOL_BLACK, opacity=0.95)
    S.add("Dust Cart", "vac inlet", cyl((vx - P["vac_r"] - 3, vy, sz + P["vac_inlet_z"]), "x", 1.3, 3), ORANGE)


    # ---------------- bulk rack (back-left corner, on the landing): bags under the first shelf, totes above ----------------
    bw_, bd_, bh_ = P["bulk_w"], P["bulk_d"], P["bulk_h"]
    ry = D - bd_
    for i, xx2 in enumerate((0.0, bw_ - st)):
        for j, yy5 in enumerate((ry, ry + bd_ - sw)):
            S.add("Bulk Rack", "upright %d%s" % (i + 1, "FB"[j]), box((xx2, yy5, LH), (st, sw, bh_)), STUD)
    for k, zt in enumerate(P["bulk_levels"]):
        z = LH + zt
        S.add("Bulk Rack", "ledger F%d" % (k + 1), box((0, ry, z - sw), (bw_, st, sw)), STUD)
        S.add("Bulk Rack", "ledger B%d" % (k + 1), box((0, ry + bd_ - st, z - sw), (bw_, st, sw)), STUD)
        S.add("Bulk Rack", "shelf %d" % (k + 1), box((0, ry, z), (bw_, bd_, P["osb"])), OSB)
        if k <= 2:
            for b in range(2):
                x_b = st + 1.0 + b * (P["tote_w"] + 1.0)
                S.add("Bulk Rack", "tote %d-%d" % (k + 1, b + 1), box((x_b, D - P["tote_l"], z + P["osb"]), (P["tote_w"], P["tote_l"], P["tote_h"] - 1.5)), TOTE_GREY)
                S.add("Bulk Rack", "lid %d-%d" % (k + 1, b + 1), box((x_b, D - P["tote_l"], z + P["osb"] + P["tote_h"] - 1.5), (P["tote_w"], P["tote_l"], 1.5)), TOTE_LID)
        else:
            S.add("Bulk Rack", "light bins", box((3, ry + 2, z + P["osb"]), (bw_ - 6, bd_ - 4, 10)), STEEL, opacity=0.5)
    # bags two high on the landing under the rack and beside it
    for b, (bx_, by_) in enumerate(((2, ry + 2), (21, ry + 2), (2, D - P["landing_d"] + 4), (21, D - P["landing_d"] + 4))):
        for lvl in range(2):
            S.add("Bulk Rack", "bag %d-%d" % (b + 1, lvl + 1), box((bx_, by_, LH + lvl * 8), (18, 10 if b >= 2 else 20, 8)), TOTE_GREY if lvl == 0 else TOTE_LID, opacity=0.9)
    # ---------------- compressor, SE corner beside the dust cart ----------------
    cyv = N(P, P["comp_yn"], P["comp_w"])
    S.add("Compressor", "pancake compressor", box((W - P["comp_d"], cyv, 0), (P["comp_d"], P["comp_w"], P["comp_h"])), STEEL, opacity=0.85)

    # ---------------- potting station (west wall, front): counter with a pot well, sunken soil bin, bag shelf ----------------
    gd, gh, gw, gy0 = P["pot_d"], P["pot_h"], P["pot_w"], P["pot_y0"]
    for i, (xx3, yy6) in enumerate(((0, gy0), (gd - sw, gy0), (0, gy0 + gw - st), (gd - sw, gy0 + gw - st), (0, gy0 + gw / 2 - st / 2), (gd - sw, gy0 + gw / 2 - st / 2))):
        S.add("Potting Station", "leg %d" % (i + 1), box((xx3, yy6, 0), (sw, st, gh - ply)), STUD)
    S.add("Potting Station", "top rail W", box((0, gy0, gh - ply - sw), (st, gw, sw)), STUD)
    S.add("Potting Station", "top rail E", box((gd - st, gy0, gh - ply - sw), (st, gw, sw)), STUD)
    wx, wy, wr = P["well_x"], gy0 + P["well_from_y0"], P["well_dia"] / 2
    bin_x, bin_y = gd - 2 - P["bin_w"], gy0 + gw - 3 - P["bin_l"]
    S.add("Potting Station", "counter top", box((0, gy0, gh - ply), (gd, gw, ply)), PLY,
          cuts=[cyl((wx, wy, gh - ply - 0.1), "z", wr, ply + 0.2), box((bin_x, bin_y, gh - ply - 0.1), (P["bin_w"], P["bin_l"], ply + 0.2))])
    # pot well: platform on cleats at three heights; the pot sits rim-flush
    wl = P["well_levels"][P["well_level"]]
    for k, zc in enumerate(P["well_levels"]):
        S.add("Potting Station", "well cleat W%d" % (k + 1), box((wx - 8, wy - 8, zc - ply - 0.75), (0.75, 16, 0.75)), PLY_DARK)
        S.add("Potting Station", "well cleat E%d" % (k + 1), box((wx + 7.25, wy - 8, zc - ply - 0.75), (0.75, 16, 0.75)), PLY_DARK)
    S.add("Potting Station", "well platform", box((wx - 7.25, wy - 8, wl - ply), (14.5, 16, ply)), PLY)
    S.add("Potting Station", "pot", cyl((wx, wy, wl), "z", P["pot_dia"] / 2, P["pot_h_in"]), (176, 96, 60), opacity=0.9)
    # soil bin sunk into the top, lip on the counter
    S.add("Potting Station", "soil bin", box((bin_x, bin_y, gh - P["bin_h"]), (P["bin_w"], P["bin_l"], P["bin_h"])), STEEL, opacity=0.7)
    S.add("Potting Station", "bin lip", box((bin_x - 0.75, bin_y - 0.75, gh), (P["bin_w"] + 1.5, P["bin_l"] + 1.5, 0.5)), STEEL, opacity=0.7,
          cuts=[box((bin_x, bin_y, gh - 0.1), (P["bin_w"], P["bin_l"], 0.7))])
    S.add("Potting Station", "splash back", box((0, gy0, gh), (ply, gw, P["splash_h"])), PLY)
    S.add("Potting Station", "trowel strip", box((ply, gy0 + 4, gh + 3.5), (1.5, gw - 8, 1.5)), STUD)
    bs = P["bag_shelf"]
    S.add("Potting Station", "bag ledger W", box((sw, gy0 + st, bs - st - ply), (st, gw - 2 * st, sw)), STUD)
    S.add("Potting Station", "bag ledger E", box((gd - sw - st, gy0 + st, bs - st - ply), (st, gw - 2 * st, sw)), STUD)
    S.add("Potting Station", "bag shelf", box((sw, gy0 + st, bs - ply), (gd - 2 * sw, gw - 2 * st, ply)), PLY)
    S.add("Potting Station", "soil bag", box((2, gy0 + 3, bs), (18, 20, 8)), TOTE_GREY)
    S.add("Potting Station", "open bag", box((2, gy0 + 25, bs), (18, 20, 8)), TOTE_LID)
    us, ud, uw = P["upper_shelf"], P["upper_d"], P["upper_w"]
    S.add("Potting Station", "upper shelf", box((0, gy0, us), (ud, uw, ply)), PLY)
    for k in range(3):
        S.add("Potting Station", "bracket %d" % (k + 1), box((0, gy0 + 2 + k * (uw / 2 - 2.5), us - 8), (8, 1, 8)), STEEL)
    S.add("Potting Station", "FlexVolt charger", box((2, gy0 + 4, us + ply), (7, 7, 4)), TOOL_YELLOW)
    S.add("Potting Station", "EGO charger", box((2, gy0 + 13, us + ply), (7, 8, 4)), TOOL_BLACK)
    S.add("Potting Station", "seed trays", box((1, gy0 + 26, us + ply), (10, 20, 3)), STEEL, opacity=0.6)
    S.add("Potting Station", "C7 receptacle", box((0, gy0 + 24, 48), (1, 4.5, 4.5)), ORANGE)
    # machine bay behind the station, nose to the wall, handles folded; 2x4 stop at the wall
    S.add("Machine Bay", "EGO mower/snowblower", box((0, P["bay_y0"], 0), (P["bay_w"], P["bay_l"], P["machine_h"])), (60, 140, 60), opacity=0.7)
    S.add("Machine Bay", "wheel stop", box((sw, P["bay_y0"] + 2, 0), (st, P["bay_l"] - 4, sw)), STUD)
    # hook rail on the west wall behind the bay: trimmer, edger, long-handle tools
    S.add("Wall Hooks", "hook rail", box((0, P["rail_y0"], P["rail_z"] - sw), (st, P["rail_y1"] - P["rail_y0"], sw)), STUD)
    S.add("Wall Hooks", "trimmer", box((0.5, P["rail_y0"] + 3, 12), (4, 4, 60)), TOOL_YELLOW)
    S.add("Wall Hooks", "edger", box((0.5, P["rail_y0"] + 11, 12), (4, 4, 60)), TOOL_YELLOW)
    for k in range(4):
        S.add("Wall Hooks", "long tool %d" % (k + 1), box((0.5, P["rail_y0"] + 22 + k * 9, 14), (2.5, 2, 58)), STUD)

    # ---------------- electrical and fixtures ----------------
    pw, phh = P["panel_w"], P["panel_hh"]
    py = N(P, P["panel_yn"], pw)
    S.add("Subpanel", "load center", box((W - 4, py, P["panel_center"] - phh / 2), (4, pw, phh)), STEEL)
    S.add("Subpanel", "working space", box((W - P["ws_d"], py + pw / 2 - P["ws_w"] / 2, 0), (P["ws_d"], P["ws_w"], 0.25)), ORANGE, opacity=0.35)
    S.add("Subpanel", "EVSE box", box((W - 2.1, P["evse_y"] - 2.35, P["evse_z"] - 2.35), (2.1, 4.7, 4.7)), ORANGE)
    S.add("Heater", "unit heater", box((W - 18, D - 20, 100), (14, 14, 14), rz=45, pivot=(W - 11, D - 13)), STEEL_DARK)
    for k, (lx, ly) in enumerate(P["lights"]):
        S.add("Ceiling Lights", "light %d" % (k + 1), box((lx - 2.5, ly, H - 4), (5, P["light_l"], 3)), GLASS)
    return S


def checks(P):
    out = []
    D, W = P["room_d"], P["room_w"]
    LH = P["landing_h"]
    curb = D - P["landing_d"]
    off = P["box_d"] / 2 + P["plate_t"]            # tool base above the shaft axis
    rails_top = P["caster"] + 1.0 + P["stud_t"]     # 2x4 on flat along the bench edges; open floor between them
    rail_in = P["bench_d"] / 2 - P["stud_w"]        # inner face of the side rails from the bench centreline
    H = P["shaft_h"] + off + P["riser_h"]
    for nm, w, h in (("planer", P["planer_w"], P["planer_h"]), ("miter", P["miter_w"], P["miter_h"])):
        r = math.hypot(w / 2, h + off)
        floor_clear = P["shaft_h"] - r
        # at the rails' inner face the hanging corner is this high (its arc is centred on the shaft)
        rail_clear = (P["shaft_h"] - math.sqrt(max(r * r - rail_in * rail_in, 0.0)) - rails_top) if w / 2 > rail_in else 99.0
        out.append(("flip bench swing (%s hanging)" % nm, floor_clear >= 1.0 and rail_clear >= 0.75,
                    "radius %.1f in, shaft %.1f: %.1f in over the floor, %.2f in over the side rails where the corner passes them" % (r, P["shaft_h"], floor_clear, rail_clear)))
    riser_r = math.hypot(P["bench_d"] / 2, off + P["riser_h"])
    out.append(("flip bench swing (riser hanging)", P["shaft_h"] - riser_r >= 1.0, "radius %.1f in, %.1f in over the floor" % (riser_r, P["shaft_h"] - riser_r)))
    panel_top = rails_top + P["panel_h"]
    bearing_top = P["shaft_h"] + P["bearing_h"] / 2
    out.append(("flange bearings backed by the end panels", panel_top - bearing_top >= 1.0,
                "panel top %.2f in, bearing top %.2f in" % (panel_top, bearing_top)))
    out.append(("index plungers inside the panel width", P["plunger_off"] + 1.5 <= P["bench_d"] / 2,
                "plunger %.0f in off the shaft, panel half-width %.0f" % (P["plunger_off"], P["bench_d"] / 2)))
    for nm, lb, cg, conc, seclen, tl in (("miter", P["miter_lb"], P["miter_cg"], P["concrete_miter"], P["sec_miter"], P["miter_l"]),
                                         ("planer", P["planer_lb"], P["planer_cg"], P["concrete_planer"], P["sec_planer"], P["planer_l"])):
        boxl = seclen - 2 * P["bay_gap"]
        m_tool = lb * (off + cg)
        m_riser = P["riser_lb"] * (off + P["riser_h"] / 2)
        conc_lb = (P["bench_d"] - 1.5) * (boxl - 1.5) * conc * 0.087
        m_conc = conc_lb * (off + P["riser_h"] - P["ply"] - conc / 2)
        resid = m_tool - m_riser - m_conc
        hand = abs(resid) / (P["bench_d"] / 2)
        out.append(("%s section balanced about its shaft" % nm, hand <= 20 and tl <= boxl - 1.0,
                    "tool %.0f lb-in vs riser %.0f + %.0f lb of concrete (%.1f in) %.0f; residual %.0f lb-in = %.0f lb at the bench edge; box %.0f long for a %.0f in tool" %
                    (m_tool, m_riser, conc_lb, conc, m_conc, resid, hand, boxl, tl)))
    out.append(("table saw sunk flush: well platform above the bottom shelf", H - P["ts_table_h"] - P["ply"] >= 15.0 + P["ply"] + 4.0,
                "bench top %.2f, saw table %.1f tall, platform at %.2f in" % (H, P["ts_table_h"], H - P["ts_table_h"] - P["ply"])))
    out.append(("bench parks under the cabinet in bench mode", H + 0.5 <= P["cab_z"], "bench top %.2f in, cabinet bottom %.0f; tools up only with the bench rolled out" % (H, P["cab_z"])))
    out.append(("tool heights (information)", True, "bench, miter table and saw table %.2f in; planer bed %.2f in" % (H, P["shaft_h"] + off + 6.0)))
    # parking
    tail = D - P["truck_nose"] - P["maverick_l"]
    out.append(("Maverick inside the door line", tail >= 16, "tail %.0f in inside the overhead door" % tail))
    tire_front = D - P["truck_nose"] - P["front_overhang"] + 14
    out.append(("front tires stop short of the landing curb", 2 <= curb - tire_front <= 12,
                "tire face at y %.0f, curb at %.0f: %.0f in short" % (tire_front, curb, curb - tire_front)))
    over = D - P["truck_nose"] - curb
    out.append(("nose overhangs the landing above the curb", over > 0 and LH < 12,
                "%.0f in over a %.0f in curb; bumper bottom 12 in" % (over, LH)))
    mirror_l = P["truck_x"] - (P["mirror_w"] - P["maverick_w"]) / 2
    mirror_r = P["truck_x"] + P["maverick_w"] + (P["mirror_w"] - P["maverick_w"]) / 2
    walk = P["landing_x"] + P["landing_w"] - mirror_r
    out.append(("landing walkway from the house door, east of the nose, kept clear", walk >= 36,
                "%.0f in from the mirror line x %.0f to the landing's end at %.0f" % (walk, mirror_r, P["landing_x"] + P["landing_w"])))
    out.append(("house door on the landing behind its step, nose short of the step", D - P["truck_nose"] <= D - P["step_d"] - 4,
                "nose at y %.0f, step face at %.0f" % (D - P["truck_nose"], D - P["step_d"])))
    out.append(("bulk rack west of the truck's mirror line", P["bulk_w"] + 2 <= mirror_l,
                "rack to x %.0f, mirror line %.0f" % (P["bulk_w"], mirror_l)))
    rear_hinge = D - P["truck_nose"] - 55.0 - 40.0            # the cab's rear door hinges at its B pillar and sweeps forward of it
    out.append(("machine bay ends before the truck's rear door swing", P["bay_y0"] + P["bay_l"] <= rear_hinge - 40.0 + 2.0 or P["bay_w"] <= P["truck_x"] - 40.0,
                "bay y %.0f to %.0f, %.0f in out; rear door sweeps y %.0f to %.0f over x 10 to %.0f" % (P["bay_y0"], P["bay_y0"] + P["bay_l"], P["bay_w"], rear_hinge - 40.0, rear_hinge, P["truck_x"])))
    lane = P["truck_x"] - P["pot_d"]
    out.append(("mower lane past the potting station with the truck in", lane >= 26, "%.0f in between the counter's edge and the truck body" % lane))
    out.append(("potting station clear of the truck's bed side", P["pot_d"] + 2 <= mirror_l, "counter to x %.0f, mirror line %.0f" % (P["pot_d"], mirror_l)))
    for k, zc in enumerate(P["well_levels"]):
        pot_max = P["pot_h"] - zc
        out.append(("pot well level %d takes a pot rim-flush" % (k + 1), 4 <= pot_max <= 16, "platform at %.0f in: a %.0f in tall pot sits with its rim at the counter" % (zc, pot_max)))
    out.append(("bulk rack top tote level within reach", LH + P["bulk_levels"][2] <= 70, "top tote shelf %.0f in above the floor, light bins at %.0f" % (LH + P["bulk_levels"][2], LH + P["bulk_levels"][3])))
    out.append(("bags stack two high under the bulk rack's first shelf", P["bulk_levels"][0] - P["stud_w"] - P["osb"] >= 16.5, "%.2f in clear over the landing" % (P["bulk_levels"][0] - P["stud_w"] - P["osb"])))
    for i, bx in enumerate(P["bike_x"]):
        clear = (P["opener_x"] - 1.5) - (bx + 24) if bx < P["opener_x"] else bx - (P["opener_x"] + 1.5)
        out.append(("bike %d clears the opener rail" % (i + 1), clear >= 4 and P["hoist_z"] >= 68 + 20, "%.0f in from the rail, %.0f in above the cab roof" % (clear, P["hoist_z"] - 68)))
    east_depth = max(P["cab_d"] + P["door_d"] + 2 * P["ply"], P["bench_off"] + P["bench_d"],
                     P["dc_off"] + P["dc_len"], P["tote_l"])
    aisle = W - east_depth - mirror_r
    out.append(("aisle from mirror to east-wall parking", aisle >= 36, "%.0f in (east wall depth %.0f)" % (aisle, east_depth)))
    # electrical and doors
    py = N(P, P["panel_yn"], P["panel_w"])
    ws_y0 = py + P["panel_w"] / 2 - P["ws_w"] / 2
    ws_y1 = ws_y0 + P["ws_w"]
    bench_len = 4 * P["panel_t"] + P["sec_saw"] + P["sec_miter"] + P["sec_planer"]
    bench_y0 = N(P, P["bench_yn"], bench_len)
    dust_y0 = N(P, P["dust_yn"], P["dc_w"])
    out.append(("subpanel working space on the flat floor, clear of the parked dust cart", ws_y1 <= curb and dust_y0 + P["dc_w"] <= ws_y0,
                "working space y %.0f to %.0f, curb %.0f, dust cart ends %.0f" % (ws_y0, ws_y1, curb, dust_y0 + P["dc_w"])))
    comp_y0 = N(P, P["comp_yn"], P["comp_w"])
    out.append(("bench parked between the compressor and the walkway", bench_y0 - (comp_y0 + P["comp_w"]) >= 2 and bench_y0 + bench_len <= ws_y0 - 20,
                "bench y %.0f to %.0f (%.1f in long), compressor ends %.0f, working space starts %.0f" % (bench_y0, bench_y0 + bench_len, bench_len, comp_y0 + P["comp_w"], ws_y0)))
    out.append(("dust cart and compressor share the front corner clear of the door track", dust_y0 >= 4 and comp_y0 - (dust_y0 + P["dc_w"]) >= 2,
                "dust cart y %.0f to %.0f, compressor y %.0f to %.0f" % (dust_y0, dust_y0 + P["dc_w"], comp_y0, comp_y0 + P["comp_w"])))
    sd_y = N(P, P["side_door_yn"], P["side_door_w"])
    out.append(("side door keeps its 3 ft of flat floor (landing stops short, working space south of it)",
                P["landing_x"] + P["landing_w"] <= W - 36 and ws_y1 <= sd_y,
                "landing ends x %.0f, working space ends y %.0f, side door starts y %.0f" % (P["landing_x"] + P["landing_w"], ws_y1, sd_y)))

    door_reach = P["cab_z"] - 44
    out.append(("cabinet bottom clears a car door top (44 in)", door_reach >= 0, "bottom at %.0f in" % P["cab_z"]))
    # dust cart
    track = P["dc_w"] - 2 * 2.0
    tip = math.degrees(math.atan2(track / 2, P["dc_cg_h"]))
    out.append(("dust cart tip angle (across the narrow way)", tip >= 18,
                "%.0f in track, CG %.0f in up: tips at %.0f deg, about %.0f lb of shove at the handle" % (track, P["dc_cg_h"], tip, P["dc_weight"] * track / 2 / (P["dc_spine_h"] + P["dc_caster"] + 1))))
    vac_fit = min(P["dc_bay"], P["dc_w"]) - 2 * P["stud_t"] - 2 * P["vac_r"]
    out.append(("16 gal drum fits inside the 2x4 corral", 0.5 <= vac_fit <= 2.5, "%.2f in total clearance around a %.1f in drum inside the rails" % (vac_fit, 2 * P["vac_r"])))
    out.append(("corral rail braces the drum above its centre of gravity", P["dc_rail_top"] >= P["vac_h"] * 0.5 and P["dc_rail_top"] <= P["vac_h"] - 4,
                "rail top %.0f in, drum %.0f tall, CG near %.0f" % (P["dc_rail_top"], P["vac_h"], P["vac_h"] * 0.4)))
    outlet_z = P["dc_caster"] + 1.0 + P["dc_base_t"] + P["dc_ped_h"] + P["ply"] + P["bucket_h"] + P["cyclone_h"]
    inlet_z = P["dc_caster"] + 1.0 + P["dc_base_t"] + P["vac_inlet_z"]
    out.append(("cyclone outlet above the drum inlet (hose falls to the vac)", outlet_z - inlet_z >= 6,
                "outlet %.1f in, inlet %.1f in" % (outlet_z, inlet_z)))
    out.append(("vac head lifts off in place", True, "drum top at %.1f in with nothing above it" % (P["dc_caster"] + 1.0 + P["dc_base_t"] + P["vac_h"])))
    out.append(("dust cart overall height (information)", True, "%.1f in to the cyclone outlet, spine handle at %.1f, footprint %.0f x %.0f" % (outlet_z, P["dc_caster"] + 1.0 + P["dc_base_t"] + P["dc_spine_h"], P["dc_len"], P["dc_w"])))
    # rack and hoists
    out.append(("bike hoists parked above the open overhead door", P["hoist_z"] >= P["door_h"] + 10 and P["hoist_z"] + 40 <= P["ceiling"] - 2,
                "bikes %.0f to %.0f in, door %.0f, ceiling %.0f" % (P["hoist_z"], P["hoist_z"] + 40, P["door_h"], P["ceiling"])))
    return out
