#!/usr/bin/env python3
"""Scaffold a shopcad plan module.

    python3 new_plan.py --init <project>                 # copy the framework to <project>/cad/
    python3 new_plan.py <slug> "<Display Name>" [--cad DIR]

Writes cad/plans/<slug_with_underscores>.py with the required attributes, a
build() that draws one labelled box so the pipeline runs end to end, one
check, and three views. Replace the box with the real geometry.
"""
import argparse
import os
import re
import shutil
import sys

FRAMEWORK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "framework")

TEMPLATE = '''"""{name}, revision A.

Coordinates, inches: X left to right, Y front to back (front at Y = 0,
doors would sit at negative Y), Z up. Everything a person would change on
the next revision is in DEFAULTS.
"""

from shopcad.geometry import PLY, STUD, Scene, box, cyl

NAME = "{name}"
FUSION_NAME = "{camel}"

DEFAULTS = dict(
    width=48.0, depth=24.0, height=36.0, ply=0.75, stud_t=1.5, stud_w=3.5,
)

STATES = {{
    "default": dict(label="As built", description=""),
}}
DEFAULT_STATE = "default"
STEP_COMPONENTS = ["Body"]
VIEWS = {{
    "iso": {{"state": "default", "w": 1400, "h": 1100}},
    "front": {{"state": "default", "view": "north", "w": 1200, "h": 900}},
    "body": {{"state": "default", "focus": "Body", "dir": "sw", "w": 1400, "h": 1000}},
}}


def build(P, state):
    S = Scene(NAME)
    S.meta = {{"state": state}}
    W, D, H, ply = P["width"], P["depth"], P["height"], P["ply"]
    # placeholder: replace with the real parts, one S.add per cut-list line
    S.add("Body", "top", box((0, 0, H - ply), (W, D, ply)), PLY)
    S.add("Body", "leg 1", box((0, 0, 0), (P["stud_w"], P["stud_t"], H - ply)), STUD)
    S.add("Body", "leg 2", box((W - P["stud_w"], 0, 0), (P["stud_w"], P["stud_t"], H - ply)), STUD)
    S.add("Body", "leg 3", box((0, D - P["stud_t"], 0), (P["stud_w"], P["stud_t"], H - ply)), STUD)
    S.add("Body", "leg 4", box((W - P["stud_w"], D - P["stud_t"], 0), (P["stud_w"], P["stud_t"], H - ply)), STUD)
    return S


def checks(P):
    out = []
    span = P["width"] - 2 * P["stud_w"]
    out.append(("top span for 3/4 plywood under load", span <= 48.0, "%.1f in between legs" % span))
    return out
'''


def init(project):
    cad = os.path.join(project, "cad")
    if os.path.isdir(os.path.join(cad, "shopcad")):
        sys.exit("%s already has shopcad; not overwriting" % cad)
    os.makedirs(cad, exist_ok=True)
    for name in ("shopcad", "plans"):
        shutil.copytree(os.path.join(FRAMEWORK, name), os.path.join(cad, name), dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("run.sh", "README.md"):
        shutil.copy(os.path.join(FRAMEWORK, name), os.path.join(cad, name))
    os.chmod(os.path.join(cad, "run.sh"), 0o755)
    print("installed shopcad in", cad)
    print("try:  %s/run.sh spool-cabinet --no-render" % cad)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--init":
        return init(sys.argv[2])
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("name")
    ap.add_argument("--cad", default=None, help="path to the cad/ directory (default: find cad/ with shopcad upward)")
    a = ap.parse_args()
    cad = a.cad
    if cad is None:
        here = os.getcwd()
        while here != "/":
            for cand in (os.path.join(here, "cad"), here):
                if os.path.isdir(os.path.join(cand, "shopcad")):
                    cad = cand
                    break
            if cad:
                break
            here = os.path.dirname(here)
    if not cad or not os.path.isdir(os.path.join(cad, "shopcad")):
        sys.exit("could not find a cad/ directory with shopcad; run --init <project> or pass --cad")
    mod = a.slug.replace("-", "_")
    if not re.match(r"^[a-z][a-z0-9_]*$", mod):
        sys.exit("slug must be lowercase letters, digits, dashes")
    camel = "".join(w.capitalize() for w in re.split(r"[\s_-]+", a.name))
    path = os.path.join(cad, "plans", mod + ".py")
    if os.path.exists(path):
        sys.exit("%s exists" % path)
    with open(path, "w") as f:
        f.write(TEMPLATE.format(name=a.name, camel=camel))
    print("wrote", path)
    print("next: edit DEFAULTS/build/checks, then  %s/run.sh %s --no-render" % (cad, a.slug))


if __name__ == "__main__":
    main()
