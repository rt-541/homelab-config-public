"""Minimal glTF 2.0 binary writer for triangle meshes.

Takes a list of parts, each {"component", "name", "color", "opacity", "v", "t"}
with v a flat list of xyz floats and t a flat list of triangle indices, and
writes one GLB with a node per part under a node per component. Triangles are
de-indexed so the viewer's computed normals are flat, which is what plywood
boxes should look like. No dependencies beyond the standard library, so it
runs anywhere the tessellation does.
"""

import json
import struct
from typing import Dict, List


def _pad4(b: bytes, fill: bytes = b"\x00") -> bytes:
    return b + fill * ((4 - len(b) % 4) % 4)


def write_glb(parts: List[dict], path: str, up_axis: str = "z") -> int:
    """Write parts to path. up_axis 'z' rotates the model so glTF's +Y is up."""
    bufs: List[bytes] = []
    views: List[dict] = []
    accessors: List[dict] = []
    materials: List[dict] = []
    meshes: List[dict] = []
    nodes: List[dict] = []
    mat_index: Dict[tuple, int] = {}
    offset = 0

    def add_view(data: bytes, target: int) -> int:
        nonlocal offset
        data = _pad4(data)
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(data), "target": target})
        bufs.append(data)
        offset += len(data)
        return len(views) - 1

    comp_children: Dict[str, List[int]] = {}
    comp_order: List[str] = []
    for p in parts:
        v, t = p["v"], p["t"]
        if not t:
            continue
        # de-index: one vertex triple per triangle corner
        pos: List[float] = []
        for i in t:
            pos.extend(v[3 * i:3 * i + 3])
        n = len(pos) // 3
        if up_axis == "z":
            # (x, y, z) z-up -> (x, z, -y) y-up
            conv: List[float] = []
            for k in range(n):
                x, y, z = pos[3 * k:3 * k + 3]
                conv.extend((x, z, -y))
            pos = conv
        xs, ys, zs = pos[0::3], pos[1::3], pos[2::3]
        pv = add_view(struct.pack("<%df" % len(pos), *pos), 34962)
        accessors.append({"bufferView": pv, "componentType": 5126, "count": n, "type": "VEC3",
                          "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]})
        pa = len(accessors) - 1
        idx = list(range(n))
        iv = add_view(struct.pack("<%dI" % n, *idx), 34963)
        accessors.append({"bufferView": iv, "componentType": 5125, "count": n, "type": "SCALAR"})
        ia = len(accessors) - 1
        r, g, b = p["color"]
        a = float(p.get("opacity", 1.0))
        key = (r, g, b, a)
        if key not in mat_index:
            m = {"name": "rgb%02x%02x%02x" % (r, g, b),
                 "pbrMetallicRoughness": {"baseColorFactor": [r / 255.0, g / 255.0, b / 255.0, a],
                                          "metallicFactor": 0.0, "roughnessFactor": 0.85},
                 "doubleSided": True}
            if a < 1.0:
                m["alphaMode"] = "BLEND"
            materials.append(m)
            mat_index[key] = len(materials) - 1
        meshes.append({"name": p["name"], "primitives": [{"attributes": {"POSITION": pa}, "indices": ia,
                                                            "material": mat_index[key], "mode": 4}]})
        nodes.append({"name": p["component"] + "/" + p["name"], "mesh": len(meshes) - 1})
        comp = p["component"]
        if comp not in comp_children:
            comp_children[comp] = []
            comp_order.append(comp)
        comp_children[comp].append(len(nodes) - 1)

    roots: List[int] = []
    for comp in comp_order:
        nodes.append({"name": comp, "children": comp_children[comp]})
        roots.append(len(nodes) - 1)

    bin_blob = b"".join(bufs)
    gltf = {
        "asset": {"version": "2.0", "generator": "shopcad"},
        "scene": 0,
        "scenes": [{"nodes": roots}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(bin_blob)}],
    }
    js = _pad4(json.dumps(gltf, separators=(",", ":")).encode("utf-8"), b" ")
    total = 12 + 8 + len(js) + 8 + len(bin_blob)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, total))
        f.write(struct.pack("<II", len(js), 0x4E4F534A))
        f.write(js)
        f.write(struct.pack("<II", len(bin_blob), 0x004E4942))
        f.write(bin_blob)
    return total
