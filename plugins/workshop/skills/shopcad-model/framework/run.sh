#!/usr/bin/env bash
# Build a plan's 3D model: STEP, GLB per state, viewer page, Fusion script zip,
# then headless PNG renders. Needs Docker (cadquery/cadquery and
# zenika/alpine-chrome); run with sudo if your user cannot reach Docker.
#
#   cad/run.sh spool-cabinet               # module plans.spool_cabinet -> <site>/public/plans/spool-cabinet/model/
#   cad/run.sh spool-cabinet --no-render
#   SHOPCAD_OUT=/path/to/plans cad/run.sh spool-cabinet   # write <path>/<slug>/model/ instead
#
set -euo pipefail
SLUG="${1:?slug}"; shift || true
NO_RENDER=0
for a in "$@"; do [ "$a" = "--no-render" ] && NO_RENDER=1; done
CAD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SITE="$(dirname "$CAD")"
MODULE="plans.${SLUG//-/_}"
OUT="${SHOPCAD_OUT:-$SITE/public/plans}/$SLUG/model"
U="${SUDO_UID:-$(id -u)}:${SUDO_GID:-$(id -g)}"
install -d -o "${U%%:*}" -g "${U##*:}" "$OUT"

echo "== export ($MODULE)"
docker run --rm --user "$U" -e HOME=/tmp -v "$CAD:/cad:ro" -v "$OUT:/out" -w /cad -e PYTHONPATH=/cad \
  cadquery/cadquery:latest python -m shopcad.export "$MODULE" /out --slug "$SLUG"
rm -rf "$OUT/fusion/${SLUG}"  # keep only the zip of the Fusion folder
find "$OUT/fusion" -mindepth 1 -maxdepth 1 -type d -exec rm -rf {} +
mv "$OUT"/fusion/*.zip "$OUT/" && rmdir "$OUT/fusion"

[ "$NO_RENDER" = 1 ] && { rm -f "$OUT/render.html"; exit 0; }

echo "== render"
# Views come from model.json "views": name -> {state, view, hide}. Each is a
# screenshot of the viewer page in shot mode via software WebGL.
python3 - "$OUT" > "$OUT/.views" <<'EOF'
import json, sys, urllib.parse
m = json.load(open(sys.argv[1] + "/model.json"))
for name, v in m["views"].items():
    q = {"shot": "1", "state": v.get("state", m["default_state"]), "view": v.get("view", name), "hide": v.get("hide", ""),
         "w": v.get("w", 1600), "h": v.get("h", 1100)}
    if v.get("focus"): q["focus"] = v["focus"]; q["dir"] = v.get("dir", "sw")
    if v.get("elev") is not None: q["elev"] = v["elev"]
    if v.get("zoom") is not None: q["zoom"] = v["zoom"]
    print(name, urllib.parse.urlencode(q), q["w"], q["h"])
EOF
while read -r name qs w h; do
  docker run --rm --user "$U" -v "$OUT:/work" zenika/alpine-chrome:latest \
    --headless --no-sandbox --disable-gpu --hide-scrollbars --allow-file-access-from-files \
    --use-angle=swiftshader --enable-unsafe-swiftshader --ignore-gpu-blocklist \
    --host-resolver-rules="MAP fonts.googleapis.com 127.0.0.1, MAP fonts.gstatic.com 127.0.0.1" \
    --window-size="$w,$h" --virtual-time-budget=40000 \
    --screenshot="/work/render-$name.png" "file:///work/render.html?$qs" 2>/dev/null \
    && echo "wrote $OUT/render-$name.png"
done < "$OUT/.views"
rm -f "$OUT/.views" "$OUT/render.html"
