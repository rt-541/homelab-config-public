"""Backyard, revision A5: a freestanding composite deck at the bay slider running from the west end of the chimney to
near the house's east corner, a 16 x 16 ft dry-laid buff flagstone patio off the deck's west side with a round stone
apron and fire ring centred on its northwest corner, a stone raised herb bed between the house and the patio, a flagstone walkway around the deck's north and east sides, five American Pillar arborvitae in a row along the
north fence on the slider's line, and a French drain along the east fence into the existing drain in the northeast
corner.

Revision A dimensions are estimates read from drone photos, not a tape: the lot, the house, the door positions and the
grade are all DEFAULTS so the tape-measured revision B only edits numbers here.

Coordinates, inches: X east (0 at the west fence), Y north (0 at the house's back wall, the house is at Y < 0), Z up
(0 = grade at the back wall on the west fence line). Grade is a plane falling north and east; see grade().

The drawing set's generator (cad/sheets/backyard/mk.py) imports this module, so the sheets and the model come from the
same numbers.
"""

import math
import random

from shopcad.geometry import STEEL, STEEL_DARK, Scene, box, cone, cyl, hip, prism, slab

NAME = "Backyard"
FUSION_NAME = "Backyard"

FT = 12.0

DEFAULTS = dict(
    # lot and house (estimated from the drone photos; revision B replaces these with tape numbers)
    lot_w=840.0, yard_d=600.0, side_d=240.0,
    house_x0=120.0, house_x1=744.0, house_d=360.0, house_h=108.0, roof_rise=78.0, eave=14.0,
    bay_x0=576.0, bay_x1=684.0, bay_d=24.0,                 # angled bay: 45 degree sides, the slider in its front face
    slider_x0=600.0, slider_x1=660.0,
    chim_x0=426.0, chim_x1=486.0, chim_d=30.0, chim_h=216.0,
    lwin_x0=372.0, lwin_x1=408.0,                            # living-room window west of the chimney (not a door)
    ac_x0=140.0, ac_x1=178.0, ac_y0=6.0, ac_y1=40.0, ac_h=36.0,
    # AC screen: vinyl privacy lattice over outdoor mass-loaded vinyl on the north side and the east gate only; the west
    # side (toward the fence) and the top stay open so the condenser draws fresh air and its exhaust does not recirculate
    acs_off=24.0, acs_h=52.0, acs_post=4.0, lat_pitch=2.5, lat_slat=1.25, mlv_gap=2.0,
    # deck: freestanding (no ledger on brick veneer), joists N-S on two beams, boards E-W
    deck_x0=426.0, deck_x1=726.0, deck_d=240.0, deck_z=24.0,
    beam_y=(33.0, 204.0), post_inset=12.0, post_max=96.0, post_w=5.5,
    chamfer=42.0,                                           # the deck's two outer corners cut at 45 degrees
    skirt_gap=0.375, skirt_inset=1.5, access_w=36.0,        # horizontal composite skirt, vented, access panel on the east side
    joist_oc=12.0, joist_d=9.25, beam_d=9.25, board_w=5.5, board_gap=0.1875, board_t=1.0, breaker_x=576.0,
    guard_h=36.0, guard_post_max=72.0, baluster_oc=4.75,
    tread=11.0, riser_max=7.75,
    wstair_yc=114.0, wstair_w=60.0,                          # deck's west side, down onto the patio
    # cooking along the east rail: a Blackstone 36 in griddle station and a pellet smoker (sizes assumed, see checks)
    cook_clear=36.0, bs_w=62.5, bs_d=22.0, bs_h=36.0, sm_w=49.0, sm_d=27.0, sm_h=55.0, cook_y0=60.0, cook_gap=12.0,
    table_xc=590.0, table_yc=150.0, table_w=40.0, table_d=84.0,
    # outdoor sofa set on the patio's southwest part: sofa on the west edge facing east, table, two chairs opposite
    lounge_x0=236.0, lounge_y0=40.0, lounge_x1=346.0, lounge_y1=150.0,
    umb_dining_x=590.0, umb_dining_y=222.0,
    umb_canopy_r=60.0, umb_h=96.0,
    # stone walkway (north and east of the deck) and the patio (west of the deck)
    wrap_w=36.0,
    pat_x0=234.0, pat_x1=426.0, pat_y0=36.0, pat_y1=228.0, apron_r=84.0,
    # raised herb bed: stone walls, its own back wall standing off the brick so no soil touches the veneer
    herb_x0=208.0, herb_x1=422.0, herb_gap=4.0, herb_d=30.0, herb_h=18.0, herb_wall=6.0,
    stone_t=2.0, dust_t=1.0, base_t=6.0, joint=0.75, stone_pitch=21.0,
    # circular stone fire ring centred on the patio's northwest corner (pit_x, pit_y follow pat_x0, pat_y1)
    # stone seat wall: an arc around the apron's north half, then straight east along the patio's north edge, stopping
    # a walkway's width short of the deck so the walkway still meets the patio
    seat_h=18.0, seat_t=14.0, seat_cap=2.0,
    pit_x=234.0, pit_y=228.0, pit_ro=26.0, pit_ri=18.0, pit_h=15.0, chair_r=62.0,
    fire_clear=60.0,                                          # owner's design clearance to any combustible, see checks()
    # evergreens: American Pillar arborvitae, one row on the slider's line
    tree_off=48.0, tree_pitch=66.0, tree_n=5, tree_w=48.0, tree_h=252.0,
    # French drain along the east fence into the existing NE-corner drain
    drain_off=24.0, drain_y0=-216.0, drain_y1=582.0, trench_w=12.0, trench_cover=18.0, drain_min_slope=0.125,
    fence_h=48.0,
)

# grade and the patio's fall, not lengths: kept out of DEFAULTS so Fusion does not make them inch parameters
SITE = dict(fall_n=30.0 / 600.0, fall_e=6.0 / 840.0, patio_fall=0.25 / 12.0, patio_raise=2.0)

STATES = {
    "summer": dict(label="Summer, furnished", description="Deck furnished, umbrellas open, trees at about ten years", furniture=True),
    "bare": dict(label="Built, unfurnished", description="What the contractors hand over, with young trees", furniture=False),
}
DEFAULT_STATE = "summer"
STEP_COMPONENTS = ["Deck Framing", "Deck Surface", "Deck Skirt", "Deck Guards", "Stairs", "Patio", "Fire Ring", "Seat Wall", "Walkway", "Herb Bed", "AC Screen"]

_ALL = ["Grade", "House", "AC Screen", "Fence", "Deck Framing", "Deck Surface", "Deck Skirt", "Deck Guards", "Stairs", "Cooking", "Furniture", "Umbrellas",
        "Patio", "Fire Ring", "Seat Wall", "Walkway", "Herb Bed", "Evergreens", "French Drain"]


def _solo(keep):
    return ",".join(c for c in _ALL if c not in keep.split(","))


VIEWS = {
    "iso-nw": {"state": "summer", "view": "iso-nw", "w": 1600, "h": 1100},
    "iso-ne": {"state": "summer", "view": "iso-ne", "w": 1600, "h": 1100},
    "hero": {"state": "summer", "focus": "Deck Surface,Patio,Walkway", "dir": "nw", "elev": 0.42, "zoom": 1.0, "hide": "Evergreens", "w": 1600, "h": 1000},
    "plan": {"state": "summer", "view": "plan", "hide": "Umbrellas", "w": 1400, "h": 1200},
    "cooking": {"state": "summer", "focus": "Cooking", "dir": "nw", "elev": 0.7, "zoom": 1.8, "hide": "Umbrellas", "w": 1400, "h": 1000},
    "deck": {"state": "summer", "focus": "Deck Surface,Deck Guards,Stairs", "dir": "ne", "elev": 0.45, "hide": "Evergreens", "w": 1600, "h": 1000},
    "framing": {"state": "bare", "focus": "Deck Framing,Stairs", "dir": "ne", "elev": 0.4, "hide": _solo("Deck Framing,Stairs,House"), "w": 1600, "h": 1000},
    "patio": {"state": "summer", "focus": "Patio,Fire Ring,Seat Wall", "dir": "ne", "elev": 0.6, "hide": "Umbrellas", "w": 1400, "h": 1000},
    "ac-screen": {"state": "summer", "focus": "AC Screen", "dir": "ne", "elev": 0.6, "zoom": 1.3, "hide": "Umbrellas", "w": 1400, "h": 1000},
    "trees": {"state": "summer", "focus": "Evergreens", "dir": "s", "elev": 0.3, "zoom": 0.7, "hide": "Umbrellas,Furniture,House", "w": 1600, "h": 900},
}


# Photoreal recipe for the llm-jobs render tier (Blender Cycles): ordered [glob, preset] pairs matched against
# "Component/part", camera views in model inches, the sun (compass azimuth, elevation) and an endless ground plane
# following the grade so the lot does not float.
RENDER = {
    "materials": [
        ["House/*roof*", "shingle"], ["House/*frame*", "paint"], ["House/fascia", "paint"], ["House/*window*", "glass"],
        ["House/slider", "glass"], ["House/AC*", "metal"], ["House/chimney cap", "concrete"], ["House/*", "brick"],
        ["Grade/*", "grass"],
        ["Deck Surface/*", "composite"], ["Deck Skirt/access panel pull", "metal"], ["Deck Skirt/*", "composite"],
        ["Deck Guards/baluster*", "metal"], ["Deck Guards/*", "composite"], ["Deck Framing/footing*", "concrete"],
        ["Deck Framing/*", "keep"], ["Stairs/*", "composite"],
        ["Patio/stone*", "flagstone"], ["Walkway/*stone*", "flagstone"], ["Patio/*", "gravel"], ["Walkway/*", "gravel"],
        ["Fire Ring/ash*", "ash"], ["Fire Ring/log*", "keep"], ["Fire Ring/cap", "flagstone"], ["Fire Ring/setting*", "flagstone"],
        ["Fire Ring/*", "wallstone"], ["Seat Wall/*cap", "flagstone"], ["Seat Wall/*", "wallstone"],
        ["Herb Bed/soil", "soil"], ["Herb Bed/herb*", "foliage"], ["Herb Bed/cap", "flagstone"], ["Herb Bed/*", "wallstone"],
        ["Evergreens/*trunk", "keep"], ["Evergreens/*", "foliage"],
        ["AC Screen/*vinyl", "fabric"], ["AC Screen/*", "vinyl"],
        ["Fence/*", "metal"], ["French Drain/existing*", "metal"], ["French Drain/*", "gravel"],
        ["Cooking/*", "metal"], ["Umbrellas/*canopy", "fabric"], ["Umbrellas/*", "metal"],
        ["Furniture/*cushion*", "fabric"], ["Furniture/*", "keep"],
    ],
    "views": {
        "north": {"from": [240, 860, 300], "to": [440, 160, 0], "lens": 28},
        "ne": {"from": [1120, 640, 330], "to": [430, 150, 0], "lens": 28},
        "west": {"from": [-420, 330, 260], "to": [440, 150, 0], "lens": 28},
    },
    "sun": {"elevation": 28, "azimuth": 300},
    "ground": {"top0": -0.6, "gx": -SITE["fall_e"], "gy": -SITE["fall_n"], "cx": 420, "cy": 200},
}


# ---------------------------------------------------------------- shared geometry (also used by the sheet generator)

def grade(x, y):
    """Existing grade in inches at (x, y); planar fall to the north and east."""
    return -(SITE["fall_n"] * y + SITE["fall_e"] * x)


def patio_z(P, y):
    """Patio finish: patio_raise above grade at its south edge (by the herb bed), falling patio_fall per inch north."""
    z0 = grade((P["pat_x0"] + P["pat_x1"]) / 2, P["pat_y0"]) + SITE["patio_raise"]
    return z0 - SITE["patio_fall"] * (y - P["pat_y0"])


def walk_z(x, y):
    """The walkway follows the ground, set 1.5 in proud."""
    return grade(x, y) + 1.5


def stair_w(P):
    """West stair: off the deck's west side at wstair_yc, down onto the patio."""
    rise = P["deck_z"] - patio_z(P, P["wstair_yc"])
    n = int(math.ceil(rise / P["riser_max"] - 1e-9))
    run = (n - 1) * P["tread"]
    return dict(n=n, riser=rise / n, rise=rise, run=run, land_z=patio_z(P, P["wstair_yc"]), x_foot=P["deck_x0"] - run)


def posts(P):
    """Post x positions along each beam, evenly spaced between the insets, no bay over post_max."""
    a, b = P["deck_x0"] + P["post_inset"], P["deck_x1"] - P["post_inset"]
    bays = int(math.ceil((b - a) / P["post_max"] - 1e-9))
    return [a + i * (b - a) / bays for i in range(bays + 1)]


def trees(P):
    xc = (P["slider_x0"] + P["slider_x1"]) / 2
    n = P["tree_n"]
    y = P["yard_d"] - P["tree_off"]
    return [(xc + (i - (n - 1) / 2.0) * P["tree_pitch"], y) for i in range(n)]


def pit_clearances(P):
    """Distance from the fire ring's outer edge to the deck (its west edge, the landing and the west stair), the house
    wall, the nearest tree canopy and the west fence."""
    px, py, r = P["pit_x"], P["pit_y"], P["pit_ro"]

    def to_rect(x0, y0, x1, y1):
        dx = max(x0 - px, 0, px - x1)
        dy = max(y0 - py, 0, py - y1)
        return math.hypot(dx, dy) - r

    ws = stair_w(P)
    deck = min(min(math.hypot(x - px, y - py) for x, y in [(P["deck_x0"], yy) for yy in range(int(P["chim_d"]), int(P["deck_d"] - P["chamfer"]) + 1)]
                   + [(P["deck_x0"] + t, P["deck_d"] - P["chamfer"] + t) for t in range(int(P["chamfer"]) + 1)]) - r,
               to_rect(ws["x_foot"], P["wstair_yc"] - P["wstair_w"] / 2, P["deck_x0"], P["wstair_yc"] + P["wstair_w"] / 2))
    house = to_rect(P["house_x0"], -P["house_d"], P["house_x1"], 0)
    tree = min(math.hypot(tx - px, ty - py) - P["tree_w"] / 2 - r for tx, ty in trees(P))
    return dict(deck=deck, house=house, tree=tree, fence=px - r)


def drain(P):
    x = P["lot_w"] - P["drain_off"]
    g0, g1 = grade(x, P["drain_y0"]), grade(x, P["drain_y1"])
    length = P["drain_y1"] - P["drain_y0"]
    inv0 = g0 - P["trench_cover"] - 4.0
    inv1 = g1 - P["trench_cover"] - 4.0
    return dict(x=x, length=length, g0=g0, g1=g1, inv0=inv0, inv1=inv1, slope=(inv0 - inv1) / (length / FT))


def deck_height(P):
    z = P["deck_z"]
    return {"sw": z - grade(P["deck_x0"], 0), "se": z - grade(P["deck_x1"], 0),
            "nw": z - grade(P["deck_x0"], P["deck_d"]), "ne": z - grade(P["deck_x1"], P["deck_d"])}


def bay_poly(P):
    """The bay in plan: 45 degree sides from the wall to the front face that carries the slider."""
    x0, x1, d = P["bay_x0"], P["bay_x1"], P["bay_d"]
    return [(x0, 0), (x1, 0), (x1 - d, d), (x0 + d, d)]


def deck_outline(P):
    """Deck outline, counter-clockwise: notched around the chimney and the angled bay, the two outer corners cut."""
    X0, X1, D, c = P["deck_x0"], P["deck_x1"], P["deck_d"], P["chamfer"]
    b0, b1, bd = P["bay_x0"], P["bay_x1"], P["bay_d"]
    return [(P["chim_x1"], P["chim_d"]), (P["chim_x1"], 0), (b0, 0), (b0 + bd, bd), (b1 - bd, bd), (b1, 0), (X1, 0),
            (X1, D - c), (X1 - c, D), (X0 + c, D), (X0, D - c), (X0, P["chim_d"])]


def deck_edge_y(P, x):
    """North edge of the deck at x, following the cut corners."""
    X0, X1, D, c = P["deck_x0"], P["deck_x1"], P["deck_d"], P["chamfer"]
    if x < X0 + c:
        return D - c + (x - X0)
    if x > X1 - c:
        return D - c + (X1 - x)
    return D


def bay_front_y(P, x):
    """How far the bay stands out from the wall at x (0 outside it)."""
    b0, b1, bd = P["bay_x0"], P["bay_x1"], P["bay_d"]
    if x <= b0 or x >= b1:
        return 0.0
    return min(bd, x - b0, b1 - x)


def cooking(P):
    """Griddle and smoker footprints along the east rail, backs to the rail, cook_clear off the rail and the house."""
    x1 = P["deck_x1"] - P["cook_clear"]
    y0 = max(P["cook_y0"], P["bay_d"] + P["cook_clear"])
    bs = (x1 - P["bs_d"], y0, x1, y0 + P["bs_w"])
    y1 = y0 + P["bs_w"] + P["cook_gap"]
    sm = (x1 - P["sm_d"], y1, x1, y1 + P["sm_w"])
    return dict(blackstone=bs, smoker=sm)


def _ccw(poly):
    a = sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly)))
    return poly if a > 0 else list(reversed(poly))


def walkway_polys(P):
    """The walkway band around the deck's east and north sides and both cut corners, as convex pieces; the piece at
    the northwest corner is split where the patio square takes over, so stones never overlap."""
    w, X0, X1, D, c = P["wrap_w"], P["deck_x0"], P["deck_x1"], P["deck_d"], P["chamfer"]
    k = w * (math.sqrt(2) - 1)
    ay = D - c + k
    bx = X1 - c + k
    cx = X0 + c - k
    dy = D - c + k
    east = [(X1, 0), (X1 + w, 0), (X1 + w, ay), (X1, D - c)]
    ne = [(X1, D - c), (X1 + w, ay), (bx, D + w), (X1 - c, D)]
    north = [(X0 + c, D), (X1 - c, D), (bx, D + w), (cx, D + w)]
    nw = [(X0, D - c), (X0 + c, D), (cx, D + w), (X0 - w, dy)]
    big = 10000.0
    nw_a = _clip_convex(_ccw(nw), [(X0, -big), (big, -big), (big, big), (X0, big)])
    nw_b = _clip_convex(_ccw(nw), [(-big, P["pat_y1"]), (X0, P["pat_y1"]), (X0, big), (-big, big)])
    west = [(X0 - w, P["pat_y1"]), (X0, P["pat_y1"]), (X0, D - c), (X0 - w, min(dy, D - c))] if P["pat_y1"] < D - c else []
    out = [("east", _ccw(east)), ("ne corner", _ccw(ne)), ("north", _ccw(north)), ("nw corner", nw_a), ("nw by patio", nw_b)]
    if west:
        out.append(("west", _ccw(west)))
    return [(n, q) for n, q in out if len(q) >= 3]


def ac_screen(P):
    """Screen corners: west x, east x, north y; the south side is the house wall."""
    o = P["acs_off"]
    return dict(x0=P["ac_x0"] - o, x1=P["ac_x1"] + o, y1=P["ac_y1"] + o, y0=P["ac_y0"])


def walkway_area(P):
    return sum(_area(q) for _, q in walkway_polys(P)) / 144.0


def seat_wall(P):
    """Seat wall footprints: the arc (as a polygon) and the straight run along the patio's north edge."""
    r1 = P["apron_r"]
    r0 = r1 - P["seat_t"]
    n = 36
    outer = [(P["pit_x"] + r1 * math.cos(math.pi * k / n), P["pit_y"] + r1 * math.sin(math.pi * k / n)) for k in range(n + 1)]
    inner = [(P["pit_x"] + r0 * math.cos(math.pi * k / n), P["pit_y"] + r0 * math.sin(math.pi * k / n)) for k in range(n, -1, -1)]
    arc = outer + inner
    x_end = P["deck_x0"] - P["wrap_w"]
    straight = [(P["pit_x"] + r0, P["pat_y1"] - P["seat_t"]), (x_end, P["pat_y1"] - P["seat_t"]), (x_end, P["pat_y1"]), (P["pit_x"] + r0, P["pat_y1"])]
    length = math.pi * (r0 + r1) / 2 + (x_end - P["pit_x"] - r0)
    return dict(arc=arc, straight=straight, length=length, r0=r0, r1=r1, x_end=x_end)


def patio_area(P):
    """Square plus the three quarters of the apron circle outside it (the apron is centred on the square's corner)."""
    return ((P["pat_x1"] - P["pat_x0"]) * (P["pat_y1"] - P["pat_y0"]) + 0.75 * math.pi * P["apron_r"] ** 2) / 144.0


def circle_poly(cx, cy, r, n=48):
    return [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)]


# ---------------------------------------------------------------- flagstone generator

def _clip(poly, rect):
    """Sutherland-Hodgman clip of a polygon to an axis-aligned rectangle."""
    x0, y0, x1, y1 = rect
    for edge in range(4):
        def inside(p):
            return (p[0] >= x0, p[1] >= y0, p[0] <= x1, p[1] <= y1)[edge]

        def cross(p, q):
            if edge in (0, 2):
                xx = x0 if edge == 0 else x1
                t = (xx - p[0]) / (q[0] - p[0])
                return (xx, p[1] + t * (q[1] - p[1]))
            yy = y0 if edge == 1 else y1
            t = (yy - p[1]) / (q[1] - p[1])
            return (p[0] + t * (q[0] - p[0]), yy)
        out = []
        n = len(poly)
        for i in range(n):
            a, b = poly[i], poly[(i + 1) % n]
            if inside(b):
                if not inside(a):
                    out.append(cross(a, b))
                out.append(b)
            elif inside(a):
                out.append(cross(a, b))
        poly = out
        if len(poly) < 3:
            return []
    return poly


def _clip_convex(poly, clip):
    """Sutherland-Hodgman clip of a polygon to a convex, counter-clockwise clip polygon."""
    for i in range(len(clip)):
        a, b = clip[i], clip[(i + 1) % len(clip)]

        def inside(p):
            return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= 0

        def cross(p, q):
            x1, y1, x2, y2 = p[0], p[1], q[0], q[1]
            x3, y3, x4, y4 = a[0], a[1], b[0], b[1]
            den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
            t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
            return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
        out = []
        n = len(poly)
        for k in range(n):
            p, q = poly[k], poly[(k + 1) % n]
            if inside(q):
                if not inside(p):
                    out.append(cross(p, q))
                out.append(q)
            elif inside(p):
                out.append(cross(p, q))
        poly = out
        if len(poly) < 3:
            return []
    return poly


def _inside_convex(p, clip):
    return all((clip[(i + 1) % len(clip)][0] - clip[i][0]) * (p[1] - clip[i][1]) - (clip[(i + 1) % len(clip)][1] - clip[i][1]) * (p[0] - clip[i][0]) >= 0
               for i in range(len(clip)))


def patio_stones(P, seed=11):
    """Stones over the union of the patio square and the apron circle: one jittered grid over both, each cell clipped
    to the region its centroid falls in (square first), so neighbouring stones never overlap. The ring's footprint is
    left open."""
    sq = [(P["pat_x0"], P["pat_y0"]), (P["pat_x1"], P["pat_y0"]), (P["pat_x1"], P["pat_y1"]), (P["pat_x0"], P["pat_y1"])]
    ci = circle_poly(P["pit_x"], P["pit_y"], P["apron_r"])
    x0 = min(P["pat_x0"], P["pit_x"] - P["apron_r"])
    y0 = P["pat_y0"]
    x1 = P["pat_x1"]
    y1 = max(P["pat_y1"], P["pit_y"] + P["apron_r"])
    out = []
    for q in flagstones((x0, y0, x1, y1), P["stone_pitch"], P["joint"], seed, holes=[(P["pit_x"], P["pit_y"], P["pit_ro"] + 6)]):
        c = (sum(p[0] for p in q) / len(q), sum(p[1] for p in q) / len(q))
        if _inside_convex(c, sq):
            r = _clip_convex(q, sq)
        elif _inside_convex(c, ci):
            r = _clip_convex(q, ci)
        else:
            continue
        if len(r) >= 3 and _area(r) >= 12:
            out.append(r)
    return out


def _area(poly):
    n = len(poly)
    return abs(sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n))) / 2


def flagstones(rect, pitch, joint, seed, holes=()):
    """Irregular quadrilateral stones from a jittered grid over rect, pulled in toward their centroids to open the
    joints, clipped to rect. Stones whose centroid falls in a hole (x, y, r) are dropped."""
    x0, y0, x1, y1 = rect
    rnd = random.Random(seed)
    nx = max(1, int(round((x1 - x0) / pitch)))
    ny = max(1, int(round((y1 - y0) / pitch)))
    sx, sy = (x1 - x0) / nx, (y1 - y0) / ny
    g = {}
    for i in range(nx + 1):
        for j in range(ny + 1):
            jx = rnd.uniform(-0.3, 0.3) * sx if 0 < i < nx else 0
            jy = rnd.uniform(-0.3, 0.3) * sy if 0 < j < ny else 0
            g[i, j] = (x0 + i * sx + jx, y0 + j * sy + jy)
    out = []
    for i in range(nx):
        for j in range(ny):
            q = [g[i, j], g[i + 1, j], g[i + 1, j + 1], g[i, j + 1]]
            cx = sum(p[0] for p in q) / 4
            cy = sum(p[1] for p in q) / 4
            if any(math.hypot(cx - hx, cy - hy) < hr for hx, hy, hr in holes):
                continue
            q2 = []
            for px, py in q:
                d = max(math.hypot(cx - px, cy - py), 1e-6)
                k = min(joint * 0.7 / d, 0.4)
                q2.append((px + (cx - px) * k, py + (cy - py) * k))
            q2 = _clip(q2, rect)
            if len(q2) < 3 or _area(q2) < 12:
                continue
            out.append(q2)
    return out


# ---------------------------------------------------------------- colours

GRASS = (104, 150, 70)
BRICK = (206, 184, 146)
ROOF = (84, 86, 92)
TRIM = (236, 232, 222)
COMPOSITE = (190, 166, 136)
COMPOSITE_DARK = (150, 126, 100)
PT = (164, 142, 104)
CONCRETE = (190, 188, 182)
FLAGS = [(222, 206, 172), (212, 194, 156), (230, 216, 186), (204, 186, 150)]
DUST = (196, 188, 172)
RING = (184, 170, 146)
ASH = (58, 54, 50)
GRAVEL = (180, 176, 166)
SOIL = (92, 70, 52)
HERB = (86, 128, 72)
TREE = (72, 122, 70)
TREE_LIGHT = (86, 136, 80)
TRUNK = (96, 72, 52)
CHAIR = (52, 54, 58)
CUSHION = (196, 190, 176)
CANVAS = (224, 214, 190)
BLACK = (32, 32, 34)
GLASS_DARK = (70, 86, 98)


def _chair(S, cx, cy, z, facing_deg, name, comp="Furniture", seat=18.0):
    """A chair: seat, a back on the side away from where it faces, four legs."""
    a = math.radians(facing_deg)
    h = seat / 2
    S.add(comp, name + " seat", box((cx - h, cy - h, z + 16), (seat, seat, 2), rz=facing_deg, pivot=(cx, cy)), CHAIR)
    bx, by = cx - math.cos(a) * (h - 1), cy - math.sin(a) * (h - 1)
    S.add(comp, name + " back", box((bx - 1, by - h, z + 18), (2, seat, 16), rz=facing_deg, pivot=(bx, by)), CHAIR)
    for sx in (-1, 1):
        for sy in (-1, 1):
            lx = cx + (sx * math.cos(a) - sy * math.sin(a)) * (h - 1.5)
            ly = cy + (sx * math.sin(a) + sy * math.cos(a)) * (h - 1.5)
            S.add(comp, "%s leg %d%d" % (name, sx, sy), box((lx - 0.75, ly - 0.75, z), (1.5, 1.5, 16)), CHAIR)


def build(P, state):
    S = Scene(NAME)
    S.meta = {"state": state, "revision": "A2", "units": "in", "sky": "#cfdfe9"}
    furnished = state.get("furniture", True)
    W, D = P["lot_w"], P["yard_d"]
    base = -72.0
    X0, X1, DD, Z = P["deck_x0"], P["deck_x1"], P["deck_d"], P["deck_z"]

    # ---- grade: one slab with a sloped top over the whole lot
    S.add("Grade", "ground", slab([(0, -P["side_d"]), (W, -P["side_d"]), (W, D), (0, D)], base, 0.0,
                                  -SITE["fall_e"], -SITE["fall_n"]), GRASS)

    # ---- house: brick walls, hip roof with eaves, bay, chimney, windows, doors, AC
    hx0, hx1, hd = P["house_x0"], P["house_x1"], P["house_d"]
    gh = grade((hx0 + hx1) / 2, 0)
    top = gh + P["house_h"]
    S.add("House", "walls", box((hx0, -hd, base), (hx1 - hx0, hd, top - base)), BRICK)
    e = P["eave"]
    S.add("House", "roof", hip(hx0 - e, -hd - e, hx1 + e, e, top, P["roof_rise"]), ROOF)
    S.add("House", "fascia", box((hx0 - e, -hd - e, top - 6), (hx1 - hx0 + 2 * e, hd + 2 * e, 6)), TRIM,
          cuts=[box((hx0 - e + 1, -hd - e + 1, top - 7), (hx1 - hx0 + 2 * e - 2, hd + 2 * e - 2, 8))])
    bp = bay_poly(P)
    S.add("House", "bay", prism(bp, gh, P["house_h"] - 6), BRICK)
    S.add("House", "bay roof", prism([(x + (6 if x > (P["bay_x0"] + P["bay_x1"]) / 2 else -6) * (1 if y == 0 else 0.4), y + (4 if y > 0 else -2))
                                      for x, y in bp], top - 6, 4), ROOF)
    S.add("House", "bay roof cap", hip(P["bay_x0"] + 10, -2, P["bay_x1"] - 10, P["bay_d"] - 2, top - 2, 16), ROOF)
    bd = P["bay_d"]
    for name, (ax, ay, bx, by) in (("west", (P["bay_x0"] + 3, 3, P["bay_x0"] + bd - 3, bd - 3)), ("east", (P["bay_x1"] - 3, 3, P["bay_x1"] - bd + 3, bd - 3))):
        L = math.hypot(bx - ax, by - ay)
        S.add("House", "bay side window " + name, box((ax, ay - 0.3, gh + 36), (L, 0.6, 50), rz=math.degrees(math.atan2(by - ay, bx - ax)), pivot=(ax, ay)), GLASS_DARK)
    S.add("House", "chimney", box((P["chim_x0"], 0, gh), (P["chim_x1"] - P["chim_x0"], P["chim_d"], P["chim_h"])), BRICK)
    S.add("House", "chimney cap", box((P["chim_x0"] - 2, -2, gh + P["chim_h"]), (P["chim_x1"] - P["chim_x0"] + 4, P["chim_d"] + 4, 4)), CONCRETE)
    dz = Z + 1.0
    S.add("House", "slider", box((P["slider_x0"], P["bay_d"], dz), (P["slider_x1"] - P["slider_x0"], 0.6, 80)), GLASS_DARK)
    S.add("House", "slider frame", box((P["slider_x0"] - 2, P["bay_d"], dz - 1), (P["slider_x1"] - P["slider_x0"] + 4, 0.4, 83)), TRIM)
    S.add("House", "living room window", box((P["lwin_x0"], 0, gh + 40), (P["lwin_x1"] - P["lwin_x0"], 0.6, 44)), GLASS_DARK)
    S.add("House", "living room window frame", box((P["lwin_x0"] - 2, 0, gh + 38), (P["lwin_x1"] - P["lwin_x0"] + 4, 0.4, 48)), TRIM)
    for i, (wx0, wx1) in enumerate(((250.0, 300.0), (510.0, 560.0), (700.0, 736.0), (150.0, 190.0))):
        S.add("House", "window %d" % i, box((wx0, 0, gh + 40), (wx1 - wx0, 0.6, 44)), GLASS_DARK)
        S.add("House", "window %d frame" % i, box((wx0 - 2, 0, gh + 38), (wx1 - wx0 + 4, 0.4, 48)), TRIM)
    ag = grade(P["ac_x0"], P["ac_y0"])
    S.add("House", "AC condenser", box((P["ac_x0"], P["ac_y0"], ag), (P["ac_x1"] - P["ac_x0"], P["ac_y1"] - P["ac_y0"], P["ac_h"])), (150, 154, 158))
    S.add("House", "AC fan", cyl(((P["ac_x0"] + P["ac_x1"]) / 2, (P["ac_y0"] + P["ac_y1"]) / 2, ag + P["ac_h"]), "z", 14, 0.5), BLACK)

    # ---- AC screen: posts, lattice (square grid of slats) and the dark mass-loaded vinyl behind it; east side hung as a gate
    sc = ac_screen(P)
    ps = P["acs_post"]
    lat = (214, 196, 160)
    hgt = P["acs_h"]
    for (px, py) in ((sc["x0"], sc["y1"]), (sc["x1"], sc["y1"]), (sc["x1"], sc["y0"])):
        g = grade(px, py)
        S.add("AC Screen", "post %d %d" % (px, py), box((px - ps / 2, py - ps / 2, g), (ps, ps, hgt + 4)), TRIM)
        S.add("AC Screen", "post cap %d %d" % (px, py), cone((px, py, g + hgt + 4), ps * 0.75, 0.5, 2.5), TRIM)
    sides = [("north", (sc["x0"] + ps / 2, sc["y1"]), (sc["x1"] - ps / 2, sc["y1"])),
             ("gate east", (sc["x1"], sc["y0"] + ps / 2), (sc["x1"], sc["y1"] - ps / 2))]
    for name, (ax, ay), (bx, by) in sides:
        horiz = ay == by
        L = (bx - ax) if horiz else (by - ay)
        g = min(grade(ax, ay), grade(bx, by)) + P["mlv_gap"]
        pitch, t = P["lat_pitch"], P["lat_slat"]
        inward = -1 if name == "north" else (1 if name == "west" else -1)
        if horiz:
            S.add("AC Screen", name + " vinyl", box((ax, ay + inward * 1.2, g), (L, 0.2, hgt - 4)), (58, 60, 62))
            S.add("AC Screen", name + " top rail", box((ax, ay - 1, g + hgt - 3), (L, 2, 2)), TRIM)
            S.add("AC Screen", name + " bottom rail", box((ax, ay - 1, g - 1), (L, 2, 2)), TRIM)
        else:
            S.add("AC Screen", name + " vinyl", box((ax + inward * 1.2, ay, g), (0.2, L, hgt - 4)), (58, 60, 62))
            S.add("AC Screen", name + " top rail", box((ax - 1, ay, g + hgt - 3), (2, L, 2)), TRIM)
            S.add("AC Screen", name + " bottom rail", box((ax - 1, ay, g - 1), (2, L, 2)), TRIM)
        k = 1
        while k * pitch < L - 1:
            u = k * pitch
            if horiz:
                S.add("AC Screen", "%s slat v%d" % (name, k), box((ax + u - t / 2, ay - 0.4, g + 1), (t, 0.4, hgt - 5)), lat)
            else:
                S.add("AC Screen", "%s slat v%d" % (name, k), box((ax - 0.4, ay + u - t / 2, g + 1), (0.4, t, hgt - 5)), lat)
            k += 1
        k = 1
        while k * pitch < hgt - 4:
            zz = g + k * pitch
            if horiz:
                S.add("AC Screen", "%s slat h%d" % (name, k), box((ax, ay + 0.0, zz), (L, 0.4, t)), lat)
            else:
                S.add("AC Screen", "%s slat h%d" % (name, k), box((ax, ay, zz), (0.4, L, t)), lat)
            k += 1

    # ---- fence: chain link on the west, north and east lines
    fh = P["fence_h"]
    for name, (x0, y0, x1, y1) in {"west": (0, -P["side_d"], 0, D), "north": (0, D, W, D), "east": (W, -P["side_d"], W, D)}.items():
        L = math.hypot(x1 - x0, y1 - y0)
        n = int(math.ceil(L / 120.0))
        for i in range(n + 1):
            px = x0 + (x1 - x0) * i / n
            py = y0 + (y1 - y0) * i / n
            S.add("Fence", "fence post %s %d" % (name, i), cyl((px, py, grade(px, py) - 6), "z", 1.0, fh + 6), STEEL)
        if y0 == y1:
            S.add("Fence", "fence top rail " + name, cyl((x0, y0, grade(x1, y0) + fh), "x", 0.8, x1 - x0), STEEL)
            S.add("Fence", "fence mesh " + name, box((x0, y0 - 0.1, grade(x1, y0)), (x1 - x0, 0.2, fh)), STEEL, opacity=0.22)
        else:
            S.add("Fence", "fence top rail " + name, cyl((x0, y0, grade(x0, y1) + fh), "y", 0.8, y1 - y0), STEEL)
            S.add("Fence", "fence mesh " + name, box((x0 - 0.1, y0, grade(x0, y1)), (0.2, y1 - y0, fh)), STEEL, opacity=0.22)

    # ---- deck framing: joists end on the cut corners and on the bay's angled face
    top_joist = Z - P["board_t"]
    jz0 = top_joist - P["joist_d"]
    bz0 = jz0 - P["beam_d"]
    for k, by in enumerate(P["beam_y"]):
        S.add("Deck Framing", "beam %d" % k, box((X0 + 6, by - 2.25, bz0), (X1 - X0 - 12, 4.5, P["beam_d"])), PT)
        for i, px in enumerate(posts(P)):
            g = grade(px, by)
            S.add("Deck Framing", "post %d-%d" % (k, i), box((px - P["post_w"] / 2, by - P["post_w"] / 2, g), (P["post_w"], P["post_w"], bz0 - g)), PT)
            S.add("Deck Framing", "footing %d-%d" % (k, i), cyl((px, by, g - 42), "z", 6.0, 44), CONCRETE)
    nj = int(round((X1 - X0) / P["joist_oc"]))
    for i in range(nj + 1):
        jx = X0 + min(i * P["joist_oc"], X1 - X0 - 1.5)
        y0 = 1.0 + (P["chim_d"] if P["chim_x0"] - 1.5 < jx < P["chim_x1"] else bay_front_y(P, jx + 0.75))
        y1 = deck_edge_y(P, jx + 0.75)
        S.add("Deck Framing", "joist %d" % i, box((jx, y0, jz0), (1.5, y1 - y0, P["joist_d"])), PT)
    S.add("Deck Framing", "rim north", box((X0 + P["chamfer"], DD - 1.5, jz0), (X1 - X0 - 2 * P["chamfer"], 1.5, P["joist_d"])), PT)
    for bx, by in ((P["umb_dining_x"], P["umb_dining_y"]),):
        S.add("Deck Framing", "umbrella blocking %d" % bx, box((bx - 12, by - 12, jz0), (24, 24, P["joist_d"])), PT)

    # ---- deck boards, E-W, split at the breaker board; the cut corners, the bay and the chimney are cut out of them
    c = P["chamfer"]
    pitch = P["board_w"] + P["board_gap"]
    rows = int(DD // pitch)
    big = 50.0
    cutters = [box((P["chim_x0"] - 0.5, -1, Z - 3), (P["chim_x1"] - P["chim_x0"] + 1, P["chim_d"] + 1.5, 6)),
               prism([(P["bay_x0"] - 0.5, -1), (P["bay_x1"] + 0.5, -1), (P["bay_x1"] - P["bay_d"] + 0.5, P["bay_d"] + 0.5),
                      (P["bay_x0"] + P["bay_d"] - 0.5, P["bay_d"] + 0.5)], Z - 3, 6),
               prism([(X1 - c, DD), (X1, DD - c), (X1 + big, DD - c), (X1 + big, DD + big), (X1 - c, DD + big)], Z - 3, 6),
               prism([(X0 + c, DD), (X0 + c, DD + big), (X0 - big, DD + big), (X0 - big, DD - c), (X0, DD - c)], Z - 3, 6)]

    def hits(cut, a, b, y0, y1):
        o, sz = cut["bbox"]["origin"], cut["bbox"]["size"]
        return o[0] < b and o[0] + sz[0] > a and o[1] < y1 and o[1] + sz[1] > y0
    bk = P["breaker_x"]
    for r in range(rows):
        by = 1.0 + r * pitch
        for seg_, (a, b) in enumerate(((X0, bk - P["board_w"] / 2 - 0.1), (bk + P["board_w"] / 2 + 0.1, X1))):
            mine = [ct for ct in cutters if hits(ct if "bbox" in ct else dict(ct, bbox={"origin": ct["origin"], "size": ct["size"]}), a, b, by, by + P["board_w"])]
            S.add("Deck Surface", "board %d%s" % (r, "ab"[seg_]), box((a, by, Z - P["board_t"]), (b - a, P["board_w"], P["board_t"])),
                  COMPOSITE, cuts=mine)
    S.add("Deck Surface", "breaker board", box((bk - P["board_w"] / 2, P["bay_d"] + 1, Z - P["board_t"]), (P["board_w"], DD - P["bay_d"] - 1, P["board_t"])), COMPOSITE_DARK)
    fz = bz0 + 4
    ol = deck_outline(P)
    # fascia along the open edges: east, the two cut corners, north, west (from the chimney face)
    edges = [ol[6:8], ol[7:9], ol[8:10], ol[9:11], ol[10:12]]
    for k, (pa, pb) in enumerate(edges):
        L = math.hypot(pb[0] - pa[0], pb[1] - pa[1])
        ang = math.degrees(math.atan2(pb[1] - pa[1], pb[0] - pa[0]))
        S.add("Deck Surface", "fascia %d" % k, box((pa[0], pa[1] - 0.375, fz), (L, 0.75, Z - fz), rz=ang, pivot=(pa[0], pa[1])), COMPOSITE_DARK)

    # ---- skirt: horizontal composite boards on every open side, 3/8 in gaps for air, set just inside the fascia
    for k, (pa, pb) in enumerate(edges):
        L = math.hypot(pb[0] - pa[0], pb[1] - pa[1])
        dx, dy = (pb[0] - pa[0]) / L, (pb[1] - pa[1]) / L
        nx, ny = -dy, dx                                   # inward, the outline runs counter-clockwise
        ox, oy = pa[0] + nx * P["skirt_inset"], pa[1] + ny * P["skirt_inset"]
        ang = math.degrees(math.atan2(dy, dx))
        zmin = min(grade(*pa), grade(*pb)) - 2
        z = fz - P["board_w"]
        r = 0
        while z + P["board_w"] > zmin:
            S.add("Deck Skirt", "skirt %d row %d" % (k, r), box((ox, oy - 0.375, z), (L, 0.75, P["board_w"]), rz=ang, pivot=(ox, oy)), COMPOSITE_DARK)
            z -= P["board_w"] + P["skirt_gap"]
            r += 1
    pa, pb = edges[0]
    ax_ = pa[0] + P["skirt_inset"] * -1 + 0.4
    ay_ = (pa[1] + pb[1]) / 2
    zb = grade(ax_, ay_)
    for nm, (y0_, y1_, z0_, z1_) in (("left", (ay_ - P["access_w"] / 2, ay_ - P["access_w"] / 2 + 2, zb, fz)), ("right", (ay_ + P["access_w"] / 2 - 2, ay_ + P["access_w"] / 2, zb, fz)),
                                     ("top", (ay_ - P["access_w"] / 2, ay_ + P["access_w"] / 2, fz - 2, fz))):
        S.add("Deck Skirt", "access panel frame " + nm, box((pa[0] - 1.9, y0_, z0_), (0.5, y1_ - y0_, z1_ - z0_)), COMPOSITE)
    S.add("Deck Skirt", "access panel pull", box((pa[0] - 2.2, ay_ - 3, (zb + fz) / 2), (0.4, 6, 1)), BLACK)

    # ---- guards with balusters along every open edge, broken for the west stair
    ws = stair_w(P)
    gh_ = P["guard_h"]
    sy0, sy1 = P["wstair_yc"] - P["wstair_w"] / 2, P["wstair_yc"] + P["wstair_w"] / 2
    runs = [("east", ol[6], ol[7]), ("ne corner", ol[7], ol[8]), ("north", ol[8], ol[9]), ("nw corner", ol[9], ol[10]),
            ("west north", ol[10], (X0, sy1)), ("west south", (X0, sy0), ol[11])]
    for name, (ax, ay), (bx, by) in runs:
        L = math.hypot(bx - ax, by - ay)
        if L < 6:
            continue
        ang = math.degrees(math.atan2(by - ay, bx - ax))
        n = max(1, int(math.ceil(L / P["guard_post_max"])))
        for i in range(n + 1):
            px, py = ax + (bx - ax) * i / n, ay + (by - ay) * i / n
            S.add("Deck Guards", "guard post %s %d" % (name, i), box((px - 2.5, py - 2.5, Z), (5, 5, gh_ + 1.5)), COMPOSITE_DARK)
            S.add("Deck Guards", "post cap %s %d" % (name, i), box((px - 3, py - 3, Z + gh_ + 1.5), (6, 6, 1)), COMPOSITE)
        S.add("Deck Guards", "top rail " + name, box((ax, ay - 2.75, Z + gh_ - 1.5), (L, 5.5, 1.5), rz=ang, pivot=(ax, ay)), COMPOSITE)
        S.add("Deck Guards", "bottom rail " + name, box((ax, ay - 1, Z + 3), (L, 2, 2.5), rz=ang, pivot=(ax, ay)), COMPOSITE)
        step = L / n
        nb = int(L // P["baluster_oc"])
        for k in range(1, nb):
            t = k * P["baluster_oc"]
            if (t % step) < 3.5 or (step - (t % step)) < 3.5:
                continue
            px, py = ax + (bx - ax) * t / L, ay + (by - ay) * t / L
            S.add("Deck Guards", "baluster %s %d" % (name, k), box((px - 0.375, py - 0.375, Z + 5.5), (0.75, 0.75, gh_ - 7)), BLACK)

    # ---- the one stair: west side, down onto the patio, closed-riser blocks and stringers
    for k in range(1, ws["n"]):
        tz = Z - k * ws["riser"]
        xa = X0 - k * P["tread"]
        S.add("Stairs", "west tread %d" % k, box((xa, sy0, ws["land_z"] - 2), (P["tread"], P["wstair_w"], tz - ws["land_z"] + 2)), COMPOSITE)
    for side, y_ in (("s", sy0 - 1.0), ("n", sy1)):
        S.add("Stairs", "west stringer " + side, prism([(X0, Z), (ws["x_foot"], ws["land_z"] + ws["riser"]), (ws["x_foot"], ws["land_z"]), (X0, ws["land_z"])],
                                                       y_, 1.0, axis="y"), COMPOSITE_DARK)

    # ---- patio: base under the square, flagstones on top, the fire ring's footprint left for the ring
    px0, px1, py0, py1 = P["pat_x0"], P["pat_x1"], P["pat_y0"], P["pat_y1"]
    zlo = patio_z(P, py1)
    bot = min(grade(px1, py1), zlo) - P["base_t"]
    t0 = patio_z(P, 0) - P["stone_t"] - 0.2
    zlo_all = patio_z(P, P["pit_y"] + P["apron_r"])
    bot = min(grade(px1, P["pit_y"] + P["apron_r"]), zlo_all) - P["base_t"]
    S.add("Patio", "base", slab([(px0, py0), (px1, py0), (px1, py1), (px0, py1)], bot, t0, 0.0, -SITE["patio_fall"]), DUST)
    S.add("Patio", "apron base", slab(circle_poly(P["pit_x"], P["pit_y"], P["apron_r"]), bot, t0, 0.0, -SITE["patio_fall"]), DUST)
    for i, q in enumerate(patio_stones(P)):
        cy = sum(p[1] for p in q) / len(q)
        S.add("Patio", "stone %d" % i, prism(q, patio_z(P, cy) - P["stone_t"], P["stone_t"]), FLAGS[i % len(FLAGS)])

    # ---- fire ring: stone ring with a cap, ash inside; chairs around it
    cx_, cy_ = P["pit_x"], P["pit_y"]
    zp = patio_z(P, cy_)
    S.add("Fire Ring", "stone ring", cyl((cx_, cy_, zp - P["stone_t"]), "z", P["pit_ro"], P["pit_h"] - 2 + P["stone_t"]), RING,
          cuts=[cyl((cx_, cy_, zp - P["stone_t"] - 1), "z", P["pit_ri"], P["pit_h"] + 4)])
    S.add("Fire Ring", "cap", cyl((cx_, cy_, zp + P["pit_h"] - 2), "z", P["pit_ro"] + 1.5, 2.5), FLAGS[3],
          cuts=[cyl((cx_, cy_, zp + P["pit_h"] - 3), "z", P["pit_ri"] - 0.5, 5)])
    S.add("Fire Ring", "setting stones", cyl((cx_, cy_, zp - P["stone_t"]), "z", P["pit_ro"] + 6, P["stone_t"] - 0.1), FLAGS[2],
          cuts=[cyl((cx_, cy_, zp - 5), "z", P["pit_ro"] - 0.5, 8)])
    S.add("Fire Ring", "ash and liner", cyl((cx_, cy_, zp - P["stone_t"]), "z", P["pit_ri"], 3), ASH)
    if furnished:
        for k in range(3):
            S.add("Fire Ring", "log %d" % k, box((cx_ - 9, cy_ - 2, zp + 1 + k * 0.5), (18, 4, 4), rz=30 + k * 60, pivot=(cx_, cy_)), (110, 80, 56))
        for i, a in enumerate((210, 270, 330)):
            ax_, ay_ = cx_ + P["chair_r"] * math.cos(math.radians(a)), cy_ + P["chair_r"] * math.sin(math.radians(a))
            _chair(S, ax_, ay_, patio_z(P, ay_), a + 180, "fire chair %d" % i, seat=22.0)

    # ---- seat wall: stone, a flat cap, around the apron's north half and along the patio's north edge
    sw = seat_wall(P)
    ztop = patio_z(P, cy_) + P["seat_h"] - P["seat_cap"]
    for name, poly in (("arc", sw["arc"]), ("straight", sw["straight"])):
        low = min(grade(x, y) for x, y in poly) - 6
        S.add("Seat Wall", name + " wall", prism(poly, low, ztop - low), RING)
        S.add("Seat Wall", name + " cap", prism(poly, ztop, P["seat_cap"]), FLAGS[3])

    # ---- walkway: flagstones following the ground around the deck's east and north sides and both cut corners
    for k, (name, poly) in enumerate(walkway_polys(P)):
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        by_patio = name in ("nw by patio", "west")
        b0 = min(grade(max(xs), max(ys)), patio_z(P, max(ys))) - 6
        if by_patio:
            S.add("Walkway", name + " base", prism(poly, b0, patio_z(P, max(ys)) - P["stone_t"] - 0.2 - b0), DUST)
        else:
            S.add("Walkway", name + " base", slab(poly, b0, -0.8, -SITE["fall_e"], -SITE["fall_n"]), DUST)
        for i, q in enumerate(flagstones((min(xs), min(ys), max(xs), max(ys)), 18.0, P["joint"], 20 + k)):
            q = _clip_convex(q, poly)
            if len(q) < 3 or _area(q) < 12:
                continue
            mx = sum(p[0] for p in q) / len(q)
            my = sum(p[1] for p in q) / len(q)
            z = patio_z(P, my) if by_patio else walk_z(mx, my)
            S.add("Walkway", "%s stone %d" % (name, i), prism(q, z - P["stone_t"], P["stone_t"]), FLAGS[(i + k) % len(FLAGS)])

    # ---- raised herb bed: four stone walls with their own back wall off the brick, soil and herbs
    hx0_, hx1_, hg, hdp, hh, hw = P["herb_x0"], P["herb_x1"], P["herb_gap"], P["herb_d"], P["herb_h"], P["herb_wall"]
    hy0, hy1 = hg, hg + hdp
    gb = grade(hx1_, hy1) - 4
    ztop = grade(hx0_, hy0) + hh
    for name, (a0, b0, a1, b1) in (("back", (hx0_, hy0, hx1_, hy0 + hw)), ("front", (hx0_, hy1 - hw, hx1_, hy1)),
                                   ("west", (hx0_, hy0 + hw, hx0_ + hw, hy1 - hw)), ("east", (hx1_ - hw, hy0 + hw, hx1_, hy1 - hw))):
        S.add("Herb Bed", "wall " + name, prism([(a0, b0), (a1, b0), (a1, b1), (a0, b1)], gb, ztop - gb), RING)
    S.add("Herb Bed", "cap", prism([(hx0_ - 0.75, hy0 - 0.75), (hx1_ + 0.75, hy0 - 0.75), (hx1_ + 0.75, hy1 + 0.75), (hx0_ - 0.75, hy1 + 0.75)], ztop, 2.0), FLAGS[3],
          cuts=[box((hx0_ + hw, hy0 + hw, ztop - 1), (hx1_ - hx0_ - 2 * hw, hdp - 2 * hw, 4))])
    S.add("Herb Bed", "soil", prism([(hx0_ + hw, hy0 + hw), (hx1_ - hw, hy0 + hw), (hx1_ - hw, hy1 - hw), (hx0_ + hw, hy1 - hw)], gb, ztop - 2 - gb), SOIL)
    if furnished:
        rnd = random.Random(5)
        x = hx0_ + hw + 8
        while x < hx1_ - hw - 6:
            r = rnd.uniform(5, 7.5)
            S.add("Herb Bed", "herb %d" % int(x), cone((x, (hy0 + hy1) / 2 + rnd.uniform(-2, 2), ztop - 2), r, r * 0.35, rnd.uniform(9, 16)), HERB)
            x += rnd.uniform(12, 17)

    # ---- evergreens: American Pillar, a narrow column
    for i, (x, y) in enumerate(trees(P)):
        g = grade(x, y)
        h = P["tree_h"] if furnished else 84.0
        r = P["tree_w"] / 2 if furnished else 12.0
        S.add("Evergreens", "tree %d trunk" % i, cyl((x, y, g), "z", 2.5, 14), TRUNK)
        S.add("Evergreens", "tree %d base" % i, cone((x, y, g + 8), r * 0.75, r, h * 0.12), TREE)
        S.add("Evergreens", "tree %d body" % i, cone((x, y, g + 8 + h * 0.12), r, r * 0.72, h * 0.58), TREE_LIGHT if i % 2 else TREE)
        S.add("Evergreens", "tree %d top" % i, cone((x, y, g + 8 + h * 0.70), r * 0.72, 1.0, h * 0.30 - 8), TREE)

    # ---- French drain: a washed-stone strip at the surface over the trench, the existing NE drain
    dr = drain(P)
    tw = P["trench_w"] / 2
    S.add("French Drain", "stone strip", slab([(dr["x"] - tw, P["drain_y0"]), (dr["x"] + tw, P["drain_y0"]), (dr["x"] + tw, P["drain_y1"]),
                                               (dr["x"] - tw, P["drain_y1"])], -60, 0.6, -SITE["fall_e"], -SITE["fall_n"]), GRAVEL)
    S.add("French Drain", "existing NE drain", cyl((dr["x"] + 6, P["drain_y1"] + 6, grade(dr["x"], P["drain_y1"]) - 1), "z", 6, 1.8), STEEL_DARK)

    # ---- cooking: Blackstone griddle station and a pellet smoker along the east rail
    ck = cooking(P)
    x0_, y0_, x1_, y1_ = ck["blackstone"]
    S.add("Cooking", "griddle cart", box((x0_ + 2, y0_ + 10, Z), (x1_ - x0_ - 4, y1_ - y0_ - 20, P["bs_h"] - 4)), BLACK)
    S.add("Cooking", "griddle top", box((x0_, y0_ + 12, Z + P["bs_h"] - 4), (x1_ - x0_, y1_ - y0_ - 24, 3)), STEEL_DARK)
    S.add("Cooking", "griddle hood", box((x1_ - 6, y0_ + 12, Z + P["bs_h"] - 1), (6, y1_ - y0_ - 24, 14)), BLACK)
    for k, (ya, yb) in enumerate(((y0_, y0_ + 12), (y1_ - 12, y1_))):
        S.add("Cooking", "griddle shelf %d" % k, box((x0_ + 1, ya, Z + P["bs_h"] - 3), (x1_ - x0_ - 2, yb - ya, 1)), BLACK)
    x0_, y0_, x1_, y1_ = ck["smoker"]
    cxs = (x0_ + x1_) / 2
    S.add("Cooking", "smoker legs and shelf", box((x0_ + 3, y0_ + 4, Z), (x1_ - x0_ - 6, y1_ - y0_ - 8, 20)), BLACK,
          cuts=[box((x0_ + 5, y0_ + 2, Z - 1), (x1_ - x0_ - 10, y1_ - y0_ - 4, 15))])
    S.add("Cooking", "smoker barrel", cyl((cxs, y0_ + 4, Z + 33), "y", 11, y1_ - y0_ - 16), BLACK)
    S.add("Cooking", "smoker hopper", box((x0_ + 2, y1_ - 14, Z + 20), (x1_ - x0_ - 4, 14, 26)), BLACK)
    S.add("Cooking", "smoker chimney", cyl((x1_ - 6, y0_ + 10, Z + 40), "z", 2, 16), STEEL_DARK)

    # ---- furniture and umbrellas
    if furnished:
        tx, ty = P["table_xc"], P["table_yc"]
        tw_, td = P["table_w"], P["table_d"]
        S.add("Furniture", "dining table top", box((tx - tw_ / 2, ty - td / 2, Z + 28.5), (tw_, td, 1.5)), (120, 96, 72))
        for sx in (-1, 1):
            for sy in (-1, 1):
                S.add("Furniture", "table leg %d%d" % (sx, sy), box((tx + sx * (tw_ / 2 - 4) - 1, ty + sy * (td / 2 - 4) - 1, Z), (2, 2, 28.5)), CHAIR)
        for k in range(3):
            cy = ty - 24 + k * 24
            _chair(S, tx - tw_ / 2 - 11, cy, Z, 0, "dining chair w%d" % k)
            _chair(S, tx + tw_ / 2 + 11, cy, Z, 180, "dining chair e%d" % k)
        _chair(S, tx, ty - td / 2 - 11, Z, 90, "dining chair s")
        _chair(S, tx, ty + td / 2 + 11, Z, 270, "dining chair n")
        lx0, ly0, lx1, ly1 = P["lounge_x0"], P["lounge_y0"], P["lounge_x1"], P["lounge_y1"]
        zl = patio_z(P, (ly0 + ly1) / 2)
        S.add("Furniture", "sofa base", box((lx0, ly0 + 10, zl), (32, 84, 16)), CHAIR)
        S.add("Furniture", "sofa back", box((lx0, ly0 + 10, zl + 16), (8, 84, 16)), CHAIR)
        S.add("Furniture", "sofa cushions", box((lx0 + 8, ly0 + 16, zl + 16), (24, 72, 4)), CUSHION)
        for k, yy in enumerate((ly0 + 14, ly1 - 42)):
            S.add("Furniture", "lounge chair %d base" % k, box((lx1 - 32, yy, zl), (32, 30, 16)), CHAIR)
            S.add("Furniture", "lounge chair %d back" % k, box((lx1 - 8, yy, zl + 16), (8, 30, 16)), CHAIR)
            S.add("Furniture", "lounge chair %d cushion" % k, box((lx1 - 30, yy + 3, zl + 16), (22, 24, 4)), CUSHION)
        S.add("Furniture", "coffee table", box((lx0 + 38, ly0 + 30, zl), (24, 44, 16)), (120, 96, 72))
        for name, (bx, by), (cx, cy) in (("dining", (P["umb_dining_x"], P["umb_dining_y"]), (tx, ty)),):
            S.add("Umbrellas", name + " plate", box((bx - 8, by - 8, Z), (16, 16, 0.5)), STEEL_DARK)
            S.add("Umbrellas", name + " pole", cyl((bx, by, Z), "z", 1.5, P["umb_h"] + 8), STEEL_DARK)
            L = math.hypot(cx - bx, cy - by)
            S.add("Umbrellas", name + " arm", box((bx, by - 1, Z + P["umb_h"] + 6), (L, 2, 2), rz=math.degrees(math.atan2(cy - by, cx - bx)), pivot=(bx, by)), STEEL_DARK)
            S.add("Umbrellas", name + " canopy", cone((cx, cy, Z + P["umb_h"] - 8), P["umb_canopy_r"], 4, 18), CANVAS)
    # colours above are picked as screen (sRGB) colours; the GLB stores linear factors, so convert or it renders washed out
    for part in S.parts:
        part["color"] = tuple(int(round(255 * (c / 255.0) ** 2.2)) for c in part["color"])
    return S


def checks(P):
    out = []
    dh = deck_height(P)
    out.append(("deck needs guards (over 30 in above grade)", max(dh.values()) > 30,
                "SW %.0f, SE %.0f, NW %.0f, NE %.0f in above grade" % (dh["sw"], dh["se"], dh["nw"], dh["ne"])))
    ws = stair_w(P)
    out.append(("west stair risers at or under %.2f in" % P["riser_max"], ws["riser"] <= P["riser_max"] + 1e-6,
                "%d risers of %.2f in, %.1f in rise, %.0f in run" % (ws["n"], ws["riser"], ws["rise"], ws["run"])))
    out.append(("west stair lands on the patio", ws["x_foot"] >= P["pat_x0"] + 36, "foot at x %.0f, %.0f in of patio beyond it" % (ws["x_foot"], ws["x_foot"] - P["pat_x0"])))
    out.append(("the west stair is the only stair", True, "the deck is reached from the slider and left by the patio"))
    out.append(("west stair clear of the cut corner", P["wstair_yc"] + P["wstair_w"] / 2 + 6 <= P["deck_d"] - P["chamfer"],
                "%.0f in of straight edge north of it" % (P["deck_d"] - P["chamfer"] - P["wstair_yc"] - P["wstair_w"] / 2)))
    out.append(("slider lands on the deck with 3 ft to spare", P["deck_x1"] - P["slider_x1"] >= 36, "%.0f in east of the slider" % (P["deck_x1"] - P["slider_x1"])))
    pb = posts(P)
    bay = max(b - a for a, b in zip(pb, pb[1:]))
    out.append(("beam post spacing at or under post_max", bay <= P["post_max"] + 1e-6, "%d posts per beam, %.1f in bays" % (len(pb), bay)))
    by = P["beam_y"]
    span = max(b - a for a, b in zip(by, by[1:]))
    cant_s, cant_n = by[0], P["deck_d"] - by[-1]
    out.append(("joist spans and cantilevers (2x10 at 12 in, 16 ft max)", span <= 192 and max(cant_s, cant_n) <= span / 4 + 1e-6,
                "longest span %.1f in, cantilever %.0f in toward the house, %.0f in north" % (span, cant_s, cant_n)))
    out.append(("south beam clears the chimney and the bay", by[0] - 2.25 > max(P["chim_d"], P["bay_d"]), "%.1f in off the wall" % (by[0] - 2.25)))
    ck = cooking(P)
    bs, sm = ck["blackstone"], ck["smoker"]
    out.append(("griddle and smoker 3 ft from the rail and the house", P["deck_x1"] - bs[2] >= 36 and bs[1] - P["bay_d"] >= 36,
                "%.0f in to the east rail, %.0f in to the bay" % (P["deck_x1"] - bs[2], bs[1] - P["bay_d"])))
    out.append(("smoker clear of the cut corner", sm[3] <= deck_edge_y(P, sm[2]) - 36, "%.0f in to the corner rail" % (deck_edge_y(P, sm[2]) - sm[3])))
    out.append(("cooks' aisle to the table", bs[0] - (P["table_xc"] + P["table_w"] / 2 + 20) >= 30,
                "%.0f in between the griddle front and the east chairs" % (bs[0] - P["table_xc"] - P["table_w"] / 2 - 20)))
    out.append(("skirt vented and serviceable", P["skirt_gap"] >= 0.25 and P["access_w"] >= 30,
                "%.3f in gaps between skirt boards, a %.0f in access panel on the east side" % (P["skirt_gap"], P["access_w"])))
    out.append(("cut corners 3.5 ft at 45 degrees", P["chamfer"] >= 36, "%.0f in each way" % P["chamfer"]))
    pc = pit_clearances(P)
    for k in ("deck", "house"):
        out.append(("fire ring at least %d in from the %s (owner's design value)" % (P["fire_clear"], k), pc[k] >= P["fire_clear"],
                    "%.0f in (%.1f ft) from the ring" % (pc[k], pc[k] / FT)))
    out.append(("fire ring at least 15 ft from the tree canopies", pc["tree"] >= 180, "%.0f in (%.1f ft)" % (pc["tree"], pc["tree"] / FT)))
    out.append(("fire ring clearances against the published code (information)", True,
                "deck %.1f ft, house %.1f ft; IFC 307.4 lists 25 ft for an open wood fire, 15 ft for a listed portable one" % (pc["deck"] / FT, pc["house"] / FT)))
    out.append(("fire ring centred on the patio's northwest corner", P["pit_x"] == P["pat_x0"] and P["pit_y"] == P["pat_y1"], "(%.0f, %.0f)" % (P["pit_x"], P["pit_y"])))
    sw = seat_wall(P)
    out.append(("seat wall legroom to the fire ring", sw["r0"] - P["pit_ro"] >= 36, "%.0f in between the bench front and the ring" % (sw["r0"] - P["pit_ro"])))
    out.append(("seat wall leaves the walkway open to the patio", P["deck_x0"] - sw["x_end"] >= 36, "%.0f in gap at its east end" % (P["deck_x0"] - sw["x_end"])))
    out.append(("seat wall at bench height", 16 <= P["seat_h"] <= 20 and P["seat_t"] >= 12, "%.0f in tall, %.0f in deep" % (P["seat_h"], P["seat_t"])))
    ws_ = stair_w(P)
    out.append(("sofa set on the patio, clear of the fire apron", P["lounge_x0"] >= P["pat_x0"] and P["lounge_y1"] <= P["pit_y"] - P["apron_r"] + 6,
                "set spans y %.0f to %.0f; apron starts at y %.0f" % (P["lounge_y0"], P["lounge_y1"], P["pit_y"] - P["apron_r"])))
    out.append(("path from the stair to the fire past the sofa set", ws_["x_foot"] - P["lounge_x1"] >= 36, "%.0f in between the chairs and the stair foot" % (ws_["x_foot"] - P["lounge_x1"])))
    out.append(("chairs on the stone apron", P["chair_r"] + 11 <= P["apron_r"], "%.0f in of apron beyond the chair backs" % (P["apron_r"] - P["chair_r"] - 11)))
    out.append(("apron inside the lot and clear of the AC", P["pit_x"] - P["apron_r"] >= 24 and P["pit_y"] - P["apron_r"] > P["ac_y1"] + 24,
                "%.0f in to the west fence, %.0f in north of the AC" % (P["pit_x"] - P["apron_r"], P["pit_y"] - P["apron_r"] - P["ac_y1"])))
    out.append(("herb bed stands off the brick", P["herb_gap"] >= 3, "%.0f in air gap behind its own back wall" % P["herb_gap"]))
    sc = ac_screen(P)
    out.append(("AC screen 24 in off the unit, open top and open west side", P["acs_off"] >= 24 and P["acs_h"] >= P["ac_h"] + 12,
                "%.0f in to the north side and the east gate, west side and top open, screen %.0f in tall over a %.0f in unit" % (P["acs_off"], P["acs_h"], P["ac_h"])))
    out.append(("herb bed clear of the AC screen", P["herb_x0"] - sc["x1"] >= 4, "%.0f in" % (P["herb_x0"] - sc["x1"])))
    out.append(("AC screen clear of the fire apron", P["pit_y"] - P["apron_r"] - sc["y1"] >= 24, "%.0f in" % (P["pit_y"] - P["apron_r"] - sc["y1"])))
    out.append(("herb bed ends at the chimney", P["herb_x1"] <= P["chim_x0"], "%.0f in short of the chimney" % (P["chim_x0"] - P["herb_x1"])))
    out.append(("patio starts in front of the herb bed", P["pat_y0"] >= P["herb_gap"] + P["herb_d"], "%.0f in" % (P["pat_y0"] - P["herb_gap"] - P["herb_d"])))
    tr = trees(P)
    gap = P["tree_pitch"] - P["tree_w"]
    out.append(("five trees in one row", len(tr) == 5, "x %s" % ", ".join("%.0f" % t[0] for t in tr)))
    out.append(("gap between trees at maturity", gap >= 12, "%.0f in at %.0f in wide" % (gap, P["tree_w"])))
    out.append(("service lane behind the trees", P["tree_off"] - P["tree_w"] / 2 >= 18, "%.0f in" % (P["tree_off"] - P["tree_w"] / 2)))
    dr = drain(P)
    near = min(dr["x"] - x for x, _ in tr)
    out.append(("trees 4 ft or more from the drain trench", near >= 48, "%.0f in" % near))
    out.append(("drain falls at least 1/8 in per ft", dr["slope"] >= P["drain_min_slope"], "%.2f in per ft over %.0f ft" % (dr["slope"], dr["length"] / FT)))
    out.append(("drain outlet depth (information: the existing line must be lower)", True, "pipe invert %.0f in below grade at the NE corner" % (dr["g1"] - dr["inv1"])))
    return out
