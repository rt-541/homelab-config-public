"""Container-side exporter: plan module -> STEP, GLB per state, viewer page,
Fusion script zip and a manifest.

    python -m shopcad.export plans.garage_shop /work/out --slug garage-shop

Runs inside cadquery/cadquery:latest (CadQuery 2.1, Python 3.8). Everything
it writes lands in the out directory, which cad/run.sh maps to
public/plans/<slug>/model/.
"""

import argparse
import importlib
import json
import os
import shutil
import sys
import time

import cadquery as cq

from . import fusion, viewer
from .glb import write_glb

HERE = os.path.dirname(os.path.abspath(__file__))


def _slab_solid(s):
    pts = s["pts"]
    b = s["bottom"]
    top = [(x, y, s["top0"] + s["gx"] * x + s["gy"] * y) for x, y in pts]
    bot = [(x, y, b) for x, y in pts]
    V = cq.Vector
    def poly(ps):
        return cq.Wire.makePolygon([V(*p) for p in ps] + [V(*ps[0])])
    faces = [cq.Face.makeFromWires(poly(bot)), cq.Face.makeFromWires(poly(top))]
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        faces.append(cq.Face.makeFromWires(poly([bot[i], bot[j], top[j], top[i]])))
    return cq.Workplane("XY").add(cq.Solid.makeSolid(cq.Shell.makeShell(faces)))


def _wp(s):
    if s["shape"] == "prism":
        plane = {"z": "XY", "x": "YZ", "y": "XZ"}[s["axis"]]
        if s["axis"] == "y":
            # XZ normal is -Y; draw at y=z0+h and extrude back toward +Y... simpler: extrude negative
            wp = cq.Workplane("XZ", origin=(0, s["z0"], 0)).polyline(s["pts"]).close().extrude(-s["h"])
        else:
            wp = cq.Workplane(plane).polyline(s["pts"]).close().extrude(s["h"])
            wp = wp.translate((0, 0, s["z0"]) if s["axis"] == "z" else (s["z0"], 0, 0))
        return wp
    if s["shape"] == "slab":
        return _slab_solid(s)
    if s["shape"] == "cone":
        x, y, z = s["base"]
        r1 = max(s["r1"], 0.01)
        return cq.Workplane("XY").add(cq.Solid.makeCone(s["r0"], r1, s["length"], cq.Vector(x, y, z), cq.Vector(0, 0, 1)))
    if s["shape"] == "hip":
        x0, y0, x1, y1 = s["rect"]
        w, d = x1 - x0, y1 - y0
        rl = abs(w - d) + 0.5
        top = (rl, 0.5) if w >= d else (0.5, rl)
        return (cq.Workplane("XY").workplane(offset=s["z"]).center((x0 + x1) / 2, (y0 + y1) / 2).rect(w, d)
                .workplane(offset=s["rise"]).rect(*top).loft())
    if s["shape"] == "box":
        x, y, z = s["origin"]
        w, d, h = s["size"]
        wp = cq.Workplane("XY").box(w, d, h, centered=False).translate((x, y, z))
    else:
        x, y, z = s["base"]
        plane = {"z": "XY", "x": "YZ", "y": "ZX"}[s["axis"]]
        wp = cq.Workplane(plane).circle(s["r"]).extrude(s["length"]).translate((x, y, z))
    if s.get("rz"):
        px, py = s["pivot"]
        wp = wp.rotate((px, py, 0), (px, py, 1), s["rz"])
    return wp


def solid_for(part):
    body = _wp(part["shape"])
    for c in part.get("cuts", []):
        body = body.cut(_wp(c))
    return body


def build_solids(scene):
    out = []
    for p in scene.parts:
        out.append((p, solid_for(p)))
    return out


def export_step(scene, solids, path):
    assy = cq.Assembly(name=scene.name + " assembly")
    subs = {}
    for p, body in solids:
        comp = p["component"]
        if comp not in subs:
            subs[comp] = cq.Assembly(name=comp)
        r, g, b = p["color"]
        subs[comp].add(body, name=p["name"], color=cq.Color(r / 255.0, g / 255.0, b / 255.0, p.get("opacity", 1.0)))
    for comp, sub in subs.items():
        assy.add(sub, name=comp)
    assy.save(path)
    return os.path.getsize(path)


def tessellate(solids, tol=0.05, ang=0.3):
    parts = []
    for p, body in solids:
        verts, tris = body.val().tessellate(tol, ang)
        parts.append({"component": p["component"], "name": p["name"], "color": p["color"],
                      "opacity": p.get("opacity", 1.0),
                      "v": [round(c, 3) for v in verts for c in (v.x, v.y, v.z)],
                      "t": [i for t in tris for i in t]})
    return parts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("module")
    ap.add_argument("out")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--no-step", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    os.makedirs(args.out, exist_ok=True)
    mod = importlib.import_module(args.module)
    P = dict(mod.DEFAULTS)

    # 1. checks: a failed check stops the export, the numbers are the point.
    results = mod.checks(P)
    bad = [r for r in results if not r[1]]
    for name, ok, detail in results:
        print("%s %s: %s" % ("PASS" if ok else "FAIL", name, detail))
    if bad:
        print("%d check(s) failed" % len(bad))
        sys.exit(2)

    manifest = {"slug": args.slug, "name": mod.NAME, "states": {}, "components": [], "checks":
                [{"name": n, "ok": ok, "detail": d} for n, ok, d in results],
                "params": P, "generated": time.strftime("%Y-%m-%d %H:%M")}

    # 2. one GLB per state; STEP for the default state only.
    default_state = mod.DEFAULT_STATE
    for sname, state in mod.STATES.items():
        scene = mod.build(P, state)
        solids = build_solids(scene)
        parts = tessellate(solids)
        glb = os.path.join(args.out, "%s-%s.glb" % (args.slug, sname))
        size = write_glb(parts, glb)
        print("wrote", glb, size, "bytes,", len(parts), "parts")
        manifest["states"][sname] = {"file": os.path.basename(glb), "label": state.get("label", sname),
                                     "description": state.get("description", "")}
        if sname == default_state:
            manifest["components"] = list(scene.order)
            manifest["meta"] = scene.meta
            if not args.no_step:
                step = os.path.join(args.out, "%s.step" % args.slug)
                print("wrote", step, export_step(scene, solids, step), "bytes")
                comps = scene.components()
                for comp, plist in comps.items():
                    if comp in getattr(mod, "STEP_COMPONENTS", comps.keys()):
                        sub = [(p, b) for p, b in solids if p["component"] == comp]
                        sub_scene = type(scene)(comp)
                        sub_scene.parts = [p for p, _ in sub]
                        sub_scene.order = [comp]
                        fn = os.path.join(args.out, "%s-%s.step" % (args.slug, comp.lower().replace(" ", "-")))
                        export_step(sub_scene, sub, fn)
                        print("wrote", fn)

    manifest["default_state"] = default_state
    manifest["views"] = getattr(mod, "VIEWS", {})
    # optional photoreal render recipe (materials map, camera views, sun, ground) for the llm-jobs render tier
    if getattr(mod, "RENDER", None):
        manifest["render"] = mod.RENDER
    with open(os.path.join(args.out, "model.json"), "w") as f:
        json.dump(manifest, f, indent=1)

    # 3. viewer page next to the GLBs.
    viewer.write(os.path.join(args.out, "index.html"), manifest)
    embed = {}
    for st in manifest["states"].values():
        with open(os.path.join(args.out, st["file"]), "rb") as f:
            embed[st["file"]] = f.read()
    viewer.write(os.path.join(args.out, "render.html"), manifest, embed=embed)

    # 4. Fusion 360 script folder + zip.
    plan_file = mod.__file__
    fz = fusion.emit(mod, plan_file, os.path.join(args.out, "fusion"), HERE)
    print("wrote", fz)
    print("done in %.1fs" % (time.time() - t0))


if __name__ == "__main__":
    main()
