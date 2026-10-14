"""Photoreal renders of a shopcad model with Blender Cycles, headless.

    blender -b --factory-startup -P render.py -- --recipe recipe.json --out /path/to/dir

The recipe (JSON) says what to render:

    {
      "model_url": "https://about.rt-541.io/plans/backyard/model/model.json",   # or "glb_url"
      "state": "summer",                  # which GLB when model_url is a shopcad model.json
      "views": ["north", "ne", "west"],   # names from the model's render block, or inline dicts
      "samples": 64, "width": 1600, "height": 1000, "device": "auto",
      "materials": [["House/roof*", "shingle"], ...],   # optional, prepended to the model's own map
      "sun": {"elevation": 28, "azimuth": 300}          # optional, overrides the model's
    }

A shopcad model.json may carry a "render" block (from the plan module's RENDER)
with "materials" (ordered [glob, preset] pairs matched against "Component/part"),
"views" (name -> {"from": [x, y, z], "to": [x, y, z], "lens": mm} in model
inches), "sun" and "ground" ({"top0", "gx", "gy"}: an endless ground plane
following the site's grade). Coordinates are the model's: X east, Y north, Z up,
inches. Materials are procedural (no image textures), tinted by each part's own
colour so the model's palette carries through.

Writes <view>.png per view and render.json (device, seconds per view) to --out.
Exits non-zero with a message on stderr if anything fails.
"""

import argparse
import fnmatch
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request

import bmesh
import bpy
from mathutils import Vector

IN = 0.0254


def fetch(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "llm-jobs-render/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        f.write(r.read())
    return dest


def load_recipe(path):
    with open(path) as f:
        recipe = json.load(f)
    work = os.path.dirname(os.path.abspath(path))
    block = {}
    if recipe.get("model_url"):
        mpath = fetch(recipe["model_url"], os.path.join(work, "model.json"))
        with open(mpath) as f:
            model = json.load(f)
        state = recipe.get("state") or model.get("default_state")
        glb_name = model["states"][state]["file"]
        glb_url = urllib.parse.urljoin(recipe["model_url"], glb_name)
        block = model.get("render") or {}
    elif recipe.get("glb_url"):
        glb_url = recipe["glb_url"]
    else:
        raise SystemExit("recipe needs model_url or glb_url")
    glb = fetch(glb_url, os.path.join(work, "model.glb"))
    mats = [tuple(m) for m in (recipe.get("materials") or [])] + [tuple(m) for m in (block.get("materials") or [])]
    views = {}
    for v in recipe.get("views") or list((block.get("views") or {}).keys()):
        if isinstance(v, dict):
            views[v.get("name", "view%d" % len(views))] = v
        elif v in (block.get("views") or {}):
            views[v] = block["views"][v]
        else:
            raise SystemExit("unknown view %r (the model defines: %s)" % (v, ", ".join(block.get("views") or {})))
    sun = dict(block.get("sun") or {"elevation": 30, "azimuth": 300})
    sun.update(recipe.get("sun") or {})
    return dict(glb=glb, materials=mats, views=views, sun=sun, ground=block.get("ground"),
                samples=int(recipe.get("samples", 64)), width=int(recipe.get("width", 1600)),
                height=int(recipe.get("height", 1000)), device=recipe.get("device", "auto"))


# ---------------------------------------------------------------- scene

def import_model(glb):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    for ob in list(bpy.context.scene.objects):
        if ob.parent is None:
            ob.scale = (IN, IN, IN)
            ob.location = ob.location * IN
    bpy.context.view_layer.update()
    for ob in bpy.context.scene.objects:
        if ob.type != "MESH":
            continue
        me = ob.data
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.005)
        bm.to_mesh(me)
        bm.free()
        try:
            me.shade_smooth()
            me.set_sharp_from_angle(angle=math.radians(35))
        except AttributeError:
            for p in me.polygons:
                p.use_smooth = True


def part_name(ob):
    comp = ob.parent.name if ob.parent is not None else ""
    name = ob.name
    return name if "/" in name else "%s/%s" % (comp, name)


# ---------------------------------------------------------------- materials

def _nodes(mat):
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return nt, bsdf


def _mix(nt, a, b, fac):
    m = nt.nodes.new("ShaderNodeMix")
    m.data_type = "RGBA"
    if isinstance(fac, float):
        m.inputs["Factor"].default_value = fac
    else:
        nt.links.new(fac, m.inputs["Factor"])
    for sock, val in ((m.inputs[6], a), (m.inputs[7], b)):
        if isinstance(val, tuple):
            sock.default_value = val
        else:
            nt.links.new(val, sock)
    return m.outputs[2]


def _noise(nt, scale, detail=6.0, vec=None, rough=0.55):
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = scale
    n.inputs["Detail"].default_value = detail
    n.inputs["Roughness"].default_value = rough
    if vec is not None:
        nt.links.new(vec, n.inputs["Vector"])
    return n


def _bump(nt, bsdf, height, strength, distance=0.02):
    b = nt.nodes.new("ShaderNodeBump")
    b.inputs["Strength"].default_value = strength
    b.inputs["Distance"].default_value = distance
    nt.links.new(height, b.inputs["Height"])
    nt.links.new(b.outputs["Normal"], bsdf.inputs["Normal"])


def _world_pos(nt):
    g = nt.nodes.new("ShaderNodeNewGeometry")
    return g


def _wall_uv(nt, scale_z=1.0):
    """World position projected onto the wall plane: (x, z) on faces pointing north/south, (y, z) on east/west."""
    g = _world_pos(nt)
    sp = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(g.outputs["Position"], sp.inputs[0])
    sn = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(g.outputs["Normal"], sn.inputs[0])
    ax = nt.nodes.new("ShaderNodeMath"); ax.operation = "ABSOLUTE"; nt.links.new(sn.outputs[0], ax.inputs[0])
    ay = nt.nodes.new("ShaderNodeMath"); ay.operation = "ABSOLUTE"; nt.links.new(sn.outputs[1], ay.inputs[0])
    gt = nt.nodes.new("ShaderNodeMath"); gt.operation = "GREATER_THAN"
    nt.links.new(ax.outputs[0], gt.inputs[0]); nt.links.new(ay.outputs[0], gt.inputs[1])
    zz = nt.nodes.new("ShaderNodeMath"); zz.operation = "MULTIPLY"; zz.inputs[1].default_value = scale_z
    nt.links.new(sp.outputs[2], zz.inputs[0])
    a = nt.nodes.new("ShaderNodeCombineXYZ"); nt.links.new(sp.outputs[0], a.inputs[0]); nt.links.new(zz.outputs[0], a.inputs[1])
    b = nt.nodes.new("ShaderNodeCombineXYZ"); nt.links.new(sp.outputs[1], b.inputs[0]); nt.links.new(zz.outputs[0], b.inputs[1])
    m = nt.nodes.new("ShaderNodeMix"); m.data_type = "VECTOR"
    nt.links.new(gt.outputs[0], m.inputs["Factor"])
    nt.links.new(a.outputs[0], m.inputs[4]); nt.links.new(b.outputs[0], m.inputs[5])
    return m.outputs[1]


def _shade(c, k):
    return (min(1.0, c[0] * k), min(1.0, c[1] * k), min(1.0, c[2] * k), 1.0)


def make_material(preset, color, alpha=1.0):
    mat = bpy.data.materials.new("%s-%02x%02x%02x" % (preset, int(color[0] * 255), int(color[1] * 255), int(color[2] * 255)))
    nt, bsdf = _nodes(mat)
    c = (color[0], color[1], color[2], 1.0)
    bsdf.inputs["Base Color"].default_value = c
    bsdf.inputs["Roughness"].default_value = 0.7
    if preset == "grass":
        n = _noise(nt, 18.0, 8.0)
        col = _mix(nt, _shade(c, 0.65), _shade(c, 1.25), n.outputs["Fac"])
        nt.links.new(col, bsdf.inputs["Base Color"])
        fine = _noise(nt, 900.0, 2.0)
        _bump(nt, bsdf, fine.outputs["Fac"], 0.6, 0.01)
        bsdf.inputs["Roughness"].default_value = 0.95
    elif preset == "foliage":
        v = nt.nodes.new("ShaderNodeTexVoronoi"); v.inputs["Scale"].default_value = 60.0
        n = _noise(nt, 30.0, 6.0)
        col = _mix(nt, _shade(c, 0.55), _shade(c, 1.2), n.outputs["Fac"])
        nt.links.new(col, bsdf.inputs["Base Color"])
        _bump(nt, bsdf, v.outputs["Distance"], 0.9, 0.05)
        bsdf.inputs["Roughness"].default_value = 0.9
    elif preset in ("brick", "wallstone", "shingle"):
        br = nt.nodes.new("ShaderNodeTexBrick")
        dims = {"brick": (0.2, 0.066, 0.009, 0.5), "wallstone": (0.44, 0.15, 0.006, 0.5), "shingle": (0.34, 0.14, 0.004, 0.5)}[preset]
        br.offset = dims[3]
        br.inputs["Scale"].default_value = 1.0
        br.inputs["Brick Width"].default_value = dims[0]
        br.inputs["Row Height"].default_value = dims[1]
        br.inputs["Mortar Size"].default_value = dims[2]
        br.inputs["Bias"].default_value = 0.0
        nt.links.new(_wall_uv(nt), br.inputs["Vector"])
        br.inputs["Color1"].default_value = _shade(c, 0.85)
        br.inputs["Color2"].default_value = _shade(c, 1.12)
        br.inputs["Mortar"].default_value = (0.55, 0.53, 0.5, 1.0) if preset != "shingle" else _shade(c, 0.5)
        n = _noise(nt, 40.0, 6.0)
        col = _mix(nt, br.outputs["Color"], _shade(c, 0.9), 0.0)
        tint = _mix(nt, col, _shade(c, 0.75), n.outputs["Fac"])
        nt.links.new(_mix(nt, col, _shade(c, 0.8), 0.25) if preset == "shingle" else tint, bsdf.inputs["Base Color"])
        inv = nt.nodes.new("ShaderNodeMath"); inv.operation = "SUBTRACT"; inv.inputs[0].default_value = 1.0
        nt.links.new(br.outputs["Fac"], inv.inputs[1])
        _bump(nt, bsdf, inv.outputs[0], 0.5 if preset != "shingle" else 0.35, 0.01)
        bsdf.inputs["Roughness"].default_value = 0.85
    elif preset == "composite":
        g = _world_pos(nt)
        mp = nt.nodes.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (0.4, 12.0, 12.0)
        nt.links.new(g.outputs["Position"], mp.inputs["Vector"])
        n = _noise(nt, 6.0, 10.0, mp.outputs["Vector"], 0.65)
        col = _mix(nt, _shade(c, 0.82), _shade(c, 1.1), n.outputs["Fac"])
        nt.links.new(col, bsdf.inputs["Base Color"])
        _bump(nt, bsdf, n.outputs["Fac"], 0.25, 0.005)
        bsdf.inputs["Roughness"].default_value = 0.55
    elif preset == "flagstone":
        n = _noise(nt, 9.0, 8.0)
        col = _mix(nt, _shade(c, 0.85), _shade(c, 1.1), n.outputs["Fac"])
        nt.links.new(col, bsdf.inputs["Base Color"])
        fine = _noise(nt, 120.0, 4.0)
        _bump(nt, bsdf, fine.outputs["Fac"], 0.35, 0.01)
        bsdf.inputs["Roughness"].default_value = 0.85
    elif preset in ("gravel", "soil", "concrete", "mulch"):
        scale = {"gravel": 400.0, "soil": 150.0, "concrete": 60.0, "mulch": 200.0}[preset]
        n = _noise(nt, scale, 3.0)
        col = _mix(nt, _shade(c, 0.75), _shade(c, 1.2), n.outputs["Fac"])
        nt.links.new(col, bsdf.inputs["Base Color"])
        _bump(nt, bsdf, n.outputs["Fac"], 0.6, 0.01)
        bsdf.inputs["Roughness"].default_value = 0.95
    elif preset == "glass":
        bsdf.inputs["Base Color"].default_value = (0.02, 0.025, 0.03, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.04
        bsdf.inputs["Specular IOR Level"].default_value = 1.0
    elif preset == "metal":
        bsdf.inputs["Metallic"].default_value = 0.85
        bsdf.inputs["Roughness"].default_value = 0.35
    elif preset in ("paint", "vinyl"):
        bsdf.inputs["Roughness"].default_value = 0.45
    elif preset == "fabric":
        bsdf.inputs["Roughness"].default_value = 1.0
        bsdf.inputs["Sheen Weight"].default_value = 0.4
    elif preset == "ash":
        n = _noise(nt, 80.0, 4.0)
        col = _mix(nt, (0.02, 0.02, 0.02, 1.0), (0.15, 0.14, 0.13, 1.0), n.outputs["Fac"])
        nt.links.new(col, bsdf.inputs["Base Color"])
        bsdf.inputs["Roughness"].default_value = 1.0
    if alpha < 1.0:
        bsdf.inputs["Alpha"].default_value = alpha
        mat.blend_method = "BLEND" if hasattr(mat, "blend_method") else None
    return mat


def apply_materials(rules):
    cache = {}
    counts = {}
    for ob in bpy.context.scene.objects:
        if ob.type != "MESH":
            continue
        name = part_name(ob)
        preset = None
        for pat, pre in rules:
            if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(name.lower(), pat.lower()):
                preset = pre
                break
        if preset is None or preset == "keep":
            continue
        for slot in ob.material_slots:
            m = slot.material
            if m is None or not m.use_nodes:
                continue
            p = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if p is None:
                continue
            col = tuple(p.inputs["Base Color"].default_value)[:3]
            alpha = p.inputs["Alpha"].default_value
            key = (preset, tuple(round(v, 3) for v in col), round(alpha, 2))
            if key not in cache:
                cache[key] = make_material(preset, col, alpha)
            slot.material = cache[key]
        counts[preset] = counts.get(preset, 0) + 1
    return counts


# ---------------------------------------------------------------- world, ground, camera, render

def add_ground(ground):
    if not ground:
        return
    s = 400.0 / IN   # a 400 m apron in model inches, centred on the model
    top0, gx, gy = ground.get("top0", 0.0), ground.get("gx", 0.0), ground.get("gy", 0.0)
    cx, cy = ground.get("cx", 0.0), ground.get("cy", 0.0)
    verts = []
    for x, y in ((cx - s, cy - s), (cx + s, cy - s), (cx + s, cy + s), (cx - s, cy + s)):
        verts.append(((x) * IN, (y) * IN, (top0 + gx * x + gy * y) * IN))
    me = bpy.data.meshes.new("ground-apron")
    me.from_pydata(verts, [], [(0, 1, 2, 3)])
    ob = bpy.data.objects.new("ground-apron", me)
    bpy.context.scene.collection.objects.link(ob)
    ob.data.materials.append(make_material("grass", tuple(ground.get("color", (0.12, 0.26, 0.07)))))


def setup_world(sun):
    world = bpy.data.worlds.new("sky")
    bpy.context.scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    sky = nt.nodes.new("ShaderNodeTexSky")
    sky.sky_type = "NISHITA"
    sky.sun_elevation = math.radians(sun.get("elevation", 30))
    # azimuth is a compass bearing (0 north, 90 east); measured: Blender's sun_rotation follows the same bearing
    sky.sun_rotation = math.radians(sun.get("azimuth", 300) % 360)
    sky.sun_intensity = sun.get("intensity", 0.6)
    sky.air_density = 1.0
    sky.dust_density = sun.get("haze", 1.5)
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = sun.get("strength", 0.14)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])


def place_camera(view):
    cam = bpy.data.cameras.new("cam")
    cam.lens = view.get("lens", 28)
    cam.clip_start, cam.clip_end = 0.1, 2000
    ob = bpy.data.objects.new("cam", cam)
    bpy.context.scene.collection.objects.link(ob)
    frm = Vector(view["from"]) * IN
    to = Vector(view["to"]) * IN
    ob.location = frm
    ob.rotation_euler = (to - frm).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = ob
    return ob


def pick_device(want):
    sc = bpy.context.scene
    sc.cycles.device = "CPU"
    if want == "cpu":
        return "CPU"
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for backend in ("ONEAPI", "CUDA", "OPTIX", "HIP"):
            try:
                prefs.compute_device_type = backend
            except TypeError:
                continue
            prefs.get_devices()
            gpus = [d for d in prefs.devices if d.type == backend]
            if gpus:
                for d in prefs.devices:
                    d.use = d.type == backend
                sc.cycles.device = "GPU"
                return "GPU %s (%s)" % (backend, ", ".join(d.name for d in gpus))
    except Exception as e:  # noqa: BLE001
        print("GPU probe failed: %s" % e, file=sys.stderr)
    return "CPU"


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    r = load_recipe(a.recipe)
    import_model(r["glb"])
    counts = apply_materials(r["materials"])
    add_ground(r["ground"])
    setup_world(r["sun"])
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    device = pick_device(r["device"])
    sc.cycles.samples = r["samples"]
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.adaptive_threshold = 0.02
    sc.cycles.use_denoising = True
    sc.cycles.max_bounces = 6
    sc.render.resolution_x, sc.render.resolution_y = r["width"], r["height"]
    sc.render.image_settings.file_format = "PNG"
    try:
        sc.view_settings.view_transform = "AgX"
        sc.view_settings.look = "AgX - Punchy"
    except TypeError:
        pass
    log = {"device": device, "samples": r["samples"], "materials": counts, "views": {}}
    for name, view in r["views"].items():
        place_camera(view)
        t0 = time.time()
        sc.render.filepath = os.path.join(a.out, "%s.png" % name)
        bpy.ops.render.render(write_still=True)
        log["views"][name] = {"file": "%s.png" % name, "seconds": round(time.time() - t0, 1)}
        print("rendered %s in %.1fs on %s" % (name, time.time() - t0, device))
    with open(os.path.join(a.out, "render.json"), "w") as f:
        json.dump(log, f, indent=1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        sys.exit(1)
