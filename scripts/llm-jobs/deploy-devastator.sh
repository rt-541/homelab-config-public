#!/bin/bash
# deploy-devastator.sh - idempotent bring-up of llm-jobs on devastator: the
# service (user unit) and the two NanoClaw worker groups. Run as the account
# that owns /docker/nanoclaw (aschneider), from any copy of scripts/llm-jobs:
#
#   bash deploy-devastator.sh service    # app copy, env, worker key, user unit, health
#   bash deploy-devastator.sh groups     # jobs-local + jobs-claude: model, env, prompt, MCP
#   bash deploy-devastator.sh key --owner arthur --tiers local,claude   # issue a caller key
#   bash deploy-devastator.sh render     # render tier: Blender, mounts, jobs-render group, skill, tier entry
#   bash deploy-devastator.sh verify     # submit a job on each tier and wait for delivery
#   bash deploy-devastator.sh all
#
# The MCP registration on the groups needs https://jobs.rt-541.io to answer
# (Traefik file-provider route on nemesis, traefik/config/devastator-llm-jobs.yml);
# `groups` skips it and says so until the route is live, then re-run `groups`.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NC=/docker/nanoclaw
NCL="$NC/bin/ncl"
APP="$HOME/.local/share/llm-jobs/app"
ENVF="$HOME/.config/llm-jobs/jobs.env"
UNIT="$HOME/.config/systemd/user/llm-jobs.service"
WORKER_ENV="$HOME/.config/llm-jobs/worker.env"
PUBLIC_URL="${PUBLIC_URL:-https://jobs.rt-541.io}"
LOCAL_URL="http://127.0.0.1:8378"
PROXY_URL=http://host.docker.internal:8788
ARTIFACTS=/docker/llm-jobs/artifacts
BLENDER_DIR=/docker/blender
BLENDER_VER=4.2.3
BLENDER_URL="https://mirrors.ocf.berkeley.edu/blender/release/Blender4.2/blender-$BLENDER_VER-linux-x64.tar.xz"
RENDER_APT='["libsm6","libice6","libx11-6","libxi6","libxxf86vm1","libxfixes3","libxrender1","libxkbcommon0","libgl1","libegl1","libglu1-mesa","libxext6"]'

log() { printf '[llm-jobs] %s\n' "$*"; }
gid() { "$NCL" groups list --json | jq -r --arg f "$1" '.data[] | select(.folder==$f) | .id'; }

do_service() {
  [ -x "$NCL" ] || { echo "ncl not found at $NCL" >&2; exit 1; }
  command -v jq >/dev/null || { echo "jq missing" >&2; exit 1; }
  mkdir -p "$APP" "$(dirname "$ENVF")" "$(dirname "$UNIT")" "$HOME/.local/share/llm-jobs"
  cp "$SRC"/jobs_lib.py "$SRC"/mcp.py "$SRC"/server.py "$SRC"/admin.py "$APP/"
  mkdir -p "$ARTIFACTS"
  grep -q '^LLMJOBS_ARTIFACTS=' "$ENVF" 2>/dev/null || { [ -f "$ENVF" ] && printf 'LLMJOBS_ARTIFACTS=%s\n' "$ARTIFACTS" >> "$ENVF"; }
  if [ ! -f "$ENVF" ]; then
    sed "s#/home/aschneider#$HOME#g" "$SRC/jobs.env.example" > "$ENVF"; chmod 600 "$ENVF"; log "wrote $ENVF"
  fi
  cp "$SRC/../../systemd-unit-files/llm-jobs.service" "$UNIT"
  systemctl --user daemon-reload
  systemctl --user enable llm-jobs.service >/dev/null
  systemctl --user restart llm-jobs.service
  sleep 1
  curl -sf "$LOCAL_URL/healthz" >/dev/null && log "service healthy on $LOCAL_URL" || { journalctl --user -u llm-jobs -n 20 --no-pager; exit 1; }
  if [ ! -s "$WORKER_ENV" ]; then
    set -a; . "$ENVF"; set +a
    local wk; wk=$(python3 "$APP/admin.py" key issue --owner nanoclaw-worker --role worker --tiers "" --daily-jobs 100000 --daily-tokens 1000000000 | jq -r .key)
    [ -n "$wk" ] && [ "$wk" != null ] || { echo "worker key issue failed" >&2; exit 1; }
    (umask 077; printf 'WORKER_KEY=%s\n' "$wk" > "$WORKER_ENV")
    log "worker key issued -> $WORKER_ENV"
  fi
}

do_key() {
  set -a; . "$ENVF"; set +a
  python3 "$APP/admin.py" key issue "$@"
}

group_one() {
  local folder=$1 name=$2 model=$3 local_backend=$4 prepend=${5:-instructions.prepend.md} extra_env=${6:-} g sdir s tmp env blocked
  "$NCL" groups create --folder "$folder" --name "$name" >/dev/null
  g=$(gid "$folder"); [ -n "$g" ] || { echo "group $folder missing after create" >&2; exit 1; }
  "$NCL" groups config update --id "$g" --cli-scope disabled --assistant-name llm-jobs --model "$model" >/dev/null
  # env + blocked hosts live in the container_configs row (no ncl verb); the
  # local tier talks to vLLM through the proxy and must not reach Anthropic.
  if [ "$local_backend" = yes ]; then
    env="{\"ANTHROPIC_BASE_URL\":\"$PROXY_URL\",\"NO_PROXY\":\"host.docker.internal\",\"no_proxy\":\"host.docker.internal\",\"CLAUDE_CODE_MAX_OUTPUT_TOKENS\":\"8192\"$extra_env}"
    blocked='["api.anthropic.com"]'
  else
    env="{${extra_env#,}}"; blocked='null'
  fi
  ENVJ="$env" BLOCKED="$blocked" GID="$g" python3 - <<'PY'
import os, sqlite3
c = sqlite3.connect("/docker/nanoclaw/data/v2.db", timeout=10)
b = None if os.environ["BLOCKED"] == "null" else os.environ["BLOCKED"]
c.execute("update container_configs set env=?, blocked_hosts=?, timezone=coalesce(timezone,'America/Detroit'), updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') where agent_group_id=?",
          (os.environ["ENVJ"], b, os.environ["GID"]))
c.commit()
PY
  sdir="$NC/data/v2-sessions/$g/.claude-shared"; mkdir -p "$sdir"; s="$sdir/settings.json"
  if [ ! -f "$s" ]; then
    tmp=$(grep -l "\"$model\"" "$NC"/data/v2-sessions/*/.claude-shared/settings.json 2>/dev/null | head -1)
    [ -n "$tmp" ] && cp "$tmp" "$s" || echo '{}' > "$s"
  fi
  tmp=$(mktemp); jq --arg m "$model" '.model = $m | .autoMemoryEnabled = false' "$s" > "$tmp" && mv "$tmp" "$s"
  mkdir -p "$NC/groups/$folder"
  install -m 0644 "$SRC/group/$prepend" "$NC/groups/$folder/instructions.prepend.md"
  # MCP: HTTPS route only (the loader refuses plain http off-host, and an
  # unreachable MCP breaks every turn), so register only when it answers.
  . "$WORKER_ENV"
  local code; code=$(curl -sS -m 8 -o /dev/null -w '%{http_code}' -X POST -H "Authorization: Bearer $WORKER_KEY" \
    -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"ping"}' "$PUBLIC_URL/mcp" 2>/dev/null || echo 000)
  if [ "$code" = 200 ]; then
    "$NCL" groups config remove-mcp-server --id "$g" --name llm-jobs >/dev/null 2>&1 || true
    "$NCL" groups config add-mcp-server --id "$g" --name llm-jobs --url "$PUBLIC_URL/mcp" \
      --headers "{\"Authorization\":\"Bearer $WORKER_KEY\"}" >/dev/null
    log "$folder ($g): model=$model, MCP registered at $PUBLIC_URL/mcp"
  else
    log "$folder ($g): model=$model, MCP route not live (HTTP $code); re-run 'groups' once jobs.rt-541.io answers"
  fi
  "$NCL" groups restart --id "$g" >/dev/null 2>&1 || true
}

do_groups() {
  [ -f "$WORKER_ENV" ] || { echo "run 'service' first (worker key)" >&2; exit 1; }
  group_one jobs-local "llm-jobs local" qwen3-14b yes
  group_one jobs-claude "llm-jobs claude" claude-sonnet-5 no
}

do_render() {
  [ -f "$WORKER_ENV" ] || { echo "run 'service' first (worker key)" >&2; exit 1; }
  # Blender, read-only for the agents
  if [ ! -x "$BLENDER_DIR/current/blender" ]; then
    sudo -n mkdir -p "$BLENDER_DIR" && sudo -n chown "$USER:$USER" "$BLENDER_DIR"
    curl -sfL -o "$BLENDER_DIR/b.tar.xz" "$BLENDER_URL"
    tar -xf "$BLENDER_DIR/b.tar.xz" -C "$BLENDER_DIR" && rm -f "$BLENDER_DIR/b.tar.xz"
    ln -sfn "blender-$BLENDER_VER-linux-x64" "$BLENDER_DIR/current"
  fi
  log "blender: $("$BLENDER_DIR/current/blender" --version 2>/dev/null | head -1 || echo 'installed (host lacks X libs; runs in the agent image)')"
  [ -d "$ARTIFACTS" ] || { sudo -n mkdir -p "$ARTIFACTS" && sudo -n chown "$USER:$USER" "$ARTIFACTS"; }
  # NanoClaw only mounts host paths under an allowlisted root
  python3 - "$BLENDER_DIR" "$ARTIFACTS" <<'PY'
import json, os, sys
p = os.path.expanduser("~/.config/nanoclaw/mount-allowlist.json")
d = json.load(open(p))
roots = {r["path"] for r in d["allowedRoots"]}
want = [(sys.argv[1], False, "Blender for the llm-jobs render tier (ro)"), (sys.argv[2], True, "llm-jobs artifacts, written by jobs-render")]
for path, rw, desc in want:
    if path not in roots:
        d["allowedRoots"].append({"path": path, "allowReadWrite": rw, "description": desc})
tmp = p + ".tmp"
json.dump(d, open(tmp, "w"), indent=2)
os.replace(tmp, p)
PY
  # Sonnet drives it: the job is a few tool calls (write the recipe, run the render, deliver), and qwen3 through
  # the proxy fails on tool-call turns ("Content block is not a text block"); the tier's daily cap bounds the spend
  group_one jobs-render "llm-jobs render" claude-sonnet-5 no render.prepend.md ',"BASH_DEFAULT_TIMEOUT_MS":"3600000","BASH_MAX_TIMEOUT_MS":"3600000"'
  local g; g=$(gid jobs-render)
  MOUNTS="[{\"hostPath\":\"$BLENDER_DIR\",\"containerPath\":\"blender\",\"readonly\":true},{\"hostPath\":\"$ARTIFACTS\",\"containerPath\":\"artifacts\",\"readonly\":false}]" \
  APT="$RENDER_APT" GID="$g" python3 - <<'PY'
import os, sqlite3
c = sqlite3.connect("/docker/nanoclaw/data/v2.db", timeout=10)
c.execute("update container_configs set packages_apt=?, additional_mounts=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') where agent_group_id=?",
          (os.environ["APT"], os.environ["MOUNTS"], os.environ["GID"]))
c.commit()
PY
  local sk="$NC/data/v2-sessions/$g/.claude-shared/skills/blender-render"
  mkdir -p "$sk"
  install -m 0644 "$SRC/render/SKILL.md" "$SRC/render/render.py" "$sk/"
  install -m 0755 "$SRC/render/run.sh" "$sk/"
  # tier entry (JSON inside the single-quoted env value; no apostrophes allowed)
  python3 - "$ENVF" <<'PY'
import json, re, sys
p = sys.argv[1]
s = open(p).read()
m = re.search(r"^LLMJOBS_TIERS='(.*)'$", s, re.M)
tiers = json.loads(m.group(1))
tiers["render"] = {"group": "jobs-render", "model": "Blender 4.2 Cycles on the CPU, driven by claude-sonnet-5",
                   "timeout_s": 3600, "speed": "slow", "cost": "metered (a few tool calls per job)", "artifacts": True,
                   "daily_jobs": 30, "daily_tokens": 300000,
                   "contract_note": "This is a render job: the job text is a JSON render recipe. Render it with the blender-render skill; the images land in /workspace/extra/artifacts/{job_id}/ and your result is the JSON summary line the skill prints. If the recipe has a photo field, run the photo step of the skill (request_photo, then photo_status) before delivering.",
                   "notes": "Prompt is a JSON render recipe (model_url of a shopcad model.json, views, samples, width, height; photo: true adds a FLUX Kontext photo-<view>.png per view via the gpu-arbiter). Result lists PNG artifacts fetched with the same key."}
line = "LLMJOBS_TIERS='%s'" % json.dumps(tiers, separators=(",", ":"))
assert "'" not in line[len("LLMJOBS_TIERS='"):-1]
open(p, "w").write(s[:m.start()] + line + s[m.end():])
PY
  systemctl --user restart llm-jobs.service; sleep 1
  curl -sf "$LOCAL_URL/healthz" | jq -c .
  "$NCL" groups restart --id "$g" >/dev/null 2>&1 || true
  log "jobs-render ($g) ready: apt image builds on its first spawn"
}

do_verify() {
  set -a; . "$ENVF"; set +a
  local key jid st i
  key=$(python3 "$APP/admin.py" key issue --owner verify --tiers local,claude --daily-jobs 10 | jq -r .key)
  for tier in local claude; do
    jid=$(curl -sf -X POST -H "Authorization: Bearer $key" -H 'Content-Type: application/json' \
      -d "{\"prompt\":\"Reply with exactly the word PONG and nothing else.\",\"tier\":\"$tier\"}" "$LOCAL_URL/api/jobs" | jq -r .job_id)
    log "$tier: job $jid submitted"
    for i in $(seq 1 60); do
      st=$(curl -sf -H "Authorization: Bearer $key" "$LOCAL_URL/api/jobs/$jid" | jq -r .status)
      case "$st" in done|failed|cancelled) break ;; esac
      sleep 5
    done
    curl -sf -H "Authorization: Bearer $key" "$LOCAL_URL/api/jobs/$jid/result" | jq -c '{status, result, error}'
  done
}

case "${1:-}" in
  service) do_service ;;
  groups) do_groups ;;
  key) shift; do_key "$@" ;;
  render) do_render ;;
  verify) do_verify ;;
  all) do_service; do_groups; do_verify ;;
  *) sed -n '2,15p' "$0"; exit 2 ;;
esac
