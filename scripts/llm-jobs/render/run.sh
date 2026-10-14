#!/bin/bash
# run.sh <job_id> <recipe.json> - render a recipe with Blender Cycles into the job's artifact folder.
# Runs inside the jobs-render NanoClaw container: Blender is mounted read-only at
# /workspace/extra/blender/current, the artifact root read-write at /workspace/extra/artifacts.
# Prints one JSON summary line (render.json plus the file list) on success; on failure
# prints the tail of the Blender log and exits non-zero.
set -uo pipefail
job="${1:?job id}"; recipe="${2:?recipe.json}"
case "$job" in *[!A-Za-z0-9_-]*|"") echo "bad job id" >&2; exit 2 ;; esac
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
blender="${BLENDER:-/workspace/extra/blender/current/blender}"
out="${ARTIFACTS:-/workspace/extra/artifacts}/$job"
work="$(mktemp -d)"
mkdir -p "$out"
cp "$recipe" "$work/recipe.json"
if ! "$blender" -b --factory-startup -P "$here/render.py" -- --recipe "$work/recipe.json" --out "$out" > "$work/blender.log" 2>&1; then
  grep -vE '^(Fra:|Sample)' "$work/blender.log" | tail -30 >&2
  cp "$work/blender.log" "$out/blender.log" 2>/dev/null || true
  exit 1
fi
python3 - "$out" <<'PY'
import json, os, sys
out = sys.argv[1]
log = json.load(open(os.path.join(out, "render.json")))
log["files"] = sorted(f for f in os.listdir(out) if f.endswith(".png"))
print(json.dumps(log))
PY
rm -rf "$work"
