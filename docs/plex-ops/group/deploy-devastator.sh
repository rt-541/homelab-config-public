#!/bin/bash
# deploy-devastator.sh - idempotent bring-up of the plex-ops NanoClaw group on
# devastator (DEPLOY.md Part 1, scripted). Run as the account that owns
# /docker/nanoclaw (aschneider), from any copy of this directory:
#
#   bash deploy-devastator.sh all        # everything below, in order
#   bash deploy-devastator.sh nfs        # read-only media mount (sudo)
#   bash deploy-devastator.sh channel    # create #plex-ops in Discord if missing
#   bash deploy-devastator.sh group      # ncl group + wiring + config + mount + env + model + prompt
#   bash deploy-devastator.sh skills     # four duty skills into groups/_skills + sync
#   bash deploy-devastator.sh tasks      # the five scheduled tasks (gated where >4/day)
#   bash deploy-devastator.sh verify     # env/mount/runner from inside the container, fire the watchdog once
#
# Prerequisites: the runner is live on nemesis and the token was pushed here
# with `deploy-nemesis.sh push-token devastator.rt-541.io`
# (-> ~/.config/plex-ops/runner.env, mode 600).
set -euo pipefail

ART="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"     # docs/plex-ops/group
NC=/docker/nanoclaw
NCL="$NC/bin/ncl"
FOLDER=plex-ops
GROUP_NAME="#plex-ops"
# ONE channel: the users' existing #plex-ops (id below). Help desk requests,
# maintenance reports, and Arthur's approvals all live there. Membership is
# the authorization; the bot engages on @mention or an approve/deny reply.
CHANNEL_ID="${CHANNEL_ID:?set CHANNEL_ID to the Discord channel snowflake}"
TOKEN_FILE="$HOME/.config/plex-ops/runner.env"
MOUNT=/mnt/nemesis-media
# claude-sonnet-5 via the OneCLI gateway (like #infra and the kids groups):
# the 14B local model could not follow the triage skill over 110 queue
# items (2026-09-13). Set MODEL=qwen3-14b to go back to the local backend
# (the script then also sets the proxy env + Anthropic block).
MODEL="${MODEL:-claude-sonnet-5}"
PROXY_URL=http://host.docker.internal:8788
MCP_URL="${MCP_URL:-https://plex-ops.rt-541.io/mcp}"     # Traefik route to the runner (traefik/config/plex-ops.yml)

log() { printf '[deploy-devastator] %s\n' "$*"; }

preflight() {
  [ -x "$NCL" ] || { echo "ncl not found at $NCL" >&2; exit 1; }
  command -v jq >/dev/null || { echo "jq missing" >&2; exit 1; }
  command -v curl >/dev/null || { echo "curl missing" >&2; exit 1; }
  [ -f "$TOKEN_FILE" ] || { echo "$TOKEN_FILE missing - run deploy-nemesis.sh push-token first" >&2; exit 1; }
  # shellcheck disable=SC1090
  . "$TOKEN_FILE"
  [ "${#RUNNER_TOKEN}" -ge 32 ] || { echo "RUNNER_TOKEN too short in $TOKEN_FILE" >&2; exit 1; }
  local code
  code=$(curl -s -m 10 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $RUNNER_TOKEN" "$RUNNER_URL/probe/disk")
  [ "$code" = 200 ] || { echo "runner not reachable/authed from this host (HTTP $code)" >&2; exit 1; }
  log "runner reachable at $RUNNER_URL"
}

gid() { "$NCL" groups list --json | jq -r --arg f "$FOLDER" '.data[] | select(.folder==$f) | .id'; }

discord_env() {
  BOT=$(grep -oP '^DISCORD_BOT_TOKEN=\K.*' "$NC/.env" | tr -d '"')
  GUILD=$(grep -oP '^DISCORD_GUILD_ID=\K.*' "$NC/.env" | tr -d '"')
  [ -n "$BOT" ] && [ -n "$GUILD" ] || { echo "DISCORD_BOT_TOKEN/DISCORD_GUILD_ID missing in $NC/.env" >&2; exit 1; }
}

channel_json() {
  # The guild listing shows every channel even when the bot lacks View
  # Channel on a private one (GET /channels/<id> would be "Missing Access"),
  # so wiring can be prepared before the bot is added to the channel.
  discord_env
  curl -sS -m 15 -H "Authorization: Bot $BOT" "https://discord.com/api/v10/guilds/$GUILD/channels" \
    | jq -c --arg id "$CHANNEL_ID" --arg g "$GUILD" '.[] | select(.id==$id) | {id, name, guild_id: $g}'
}

channel_visible() {
  discord_env
  curl -sS -m 15 -o /dev/null -w '%{http_code}' -H "Authorization: Bot $BOT" \
    "https://discord.com/api/v10/channels/$CHANNEL_ID"
}

do_nfs() {
  rpm -q nfs-utils >/dev/null || sudo dnf install -y nfs-utils
  sudo mkdir -p "$MOUNT"
  # nemesis serves NFSv4 from the plex-stack plex-nfs container: pseudo-root
  # /nfs (fsid=0), media at /nfs/media -> client path `:/media`.
  local line="nemesis.rt-541.io:/media $MOUNT nfs4 ro,nosuid,nodev,noexec,soft,timeo=100,retrans=2,_netdev 0 0"
  if grep -qsF "$line" /etc/fstab; then
    log "fstab entry present"
  else
    mountpoint -q "$MOUNT" && sudo umount "$MOUNT"
    sudo sed -i "\# $MOUNT #d" /etc/fstab            # drop any stale entry for the mountpoint
    echo "$line" | sudo tee -a /etc/fstab >/dev/null
    log "fstab entry written"
  fi
  sudo systemctl daemon-reload
  mountpoint -q "$MOUNT" || sudo mount "$MOUNT"
  ls "$MOUNT/downloads" >/dev/null && log "mounted: $(ls "$MOUNT" | tr '\n' ' ')"
  if touch "$MOUNT/.rw-probe" 2>/dev/null; then rm -f "$MOUNT/.rw-probe"; echo "MOUNT IS WRITABLE - export is not ro" >&2; exit 1; else log "read-only confirmed"; fi
}

do_channel() {
  local cj name guild
  cj=$(channel_json)
  name=$(printf '%s' "$cj" | jq -r '.name // empty'); guild=$(printf '%s' "$cj" | jq -r '.guild_id // empty')
  [ -n "$name" ] && [ -n "$guild" ] || { echo "channel $CHANNEL_ID is not in guild $GUILD (check the id)" >&2; exit 1; }
  log "channel #$name ($CHANNEL_ID) exists in guild $guild"
  if [ "$(channel_visible)" = 200 ]; then
    log "bot can read #$name"
  else
    log "WARNING: bot cannot read #$name (Missing Access). In Discord: channel settings > Permissions > add the bot (or its role) with View Channel + Send Messages + Read Message History. Wiring is prepared regardless."
  fi
}

do_group() {
  # shellcheck disable=SC1090
  . "$TOKEN_FILE"
  local cj name guild pid mgid g app_id
  cj=$(channel_json)
  name=$(printf '%s' "$cj" | jq -r '.name // empty'); guild=$(printf '%s' "$cj" | jq -r '.guild_id // empty')
  [ -n "$guild" ] || { echo "channel $CHANNEL_ID not found in the guild - run: $0 channel" >&2; exit 1; }
  pid="discord:$guild:$CHANNEL_ID"
  app_id=$(grep -oP '^DISCORD_APPLICATION_ID=\K.*' "$NC/.env" | tr -d '"')
  "$NCL" groups create --folder "$FOLDER" --name "$GROUP_NAME" >/dev/null   # idempotent on --folder
  g=$(gid); [ -n "$g" ] || { echo "group not found after create" >&2; exit 1; }
  log "group $g ($FOLDER)"
  mgid=$("$NCL" messaging-groups list --json | jq -r --arg p "$pid" '.data[] | select(.platform_id==$p) | .id')
  if [ -z "$mgid" ]; then
    # public: everyone in the channel is authorized by being there.
    "$NCL" messaging-groups create --channel-type discord --platform-id "$pid" --instance discord \
      --name "$name" --is-group 1 --unknown-sender-policy public >/dev/null
    log "messaging group created for #$name ($pid)"
  else
    log "messaging group present: $mgid"
  fi
  # mention-sticky: an @mention opens a Discord thread (threads ON,
  # per-thread session) and every later message in that thread engages the
  # agent without re-mentioning; plain channel chatter never wakes it.
  # Arthur's approvals / mode switches therefore @mention the bot (or go in
  # the thread). With threads off the adapter still opened the thread but
  # answered in the channel (2026-09-13).
  "$NCL" wirings create --channel-type discord --platform-id "$pid" --instance discord --agent-group "$FOLDER" \
    --engage-mode mention-sticky --session-mode per-thread --sender-scope all \
    --ignored-message-policy drop --threads 1 >/dev/null
  W=$("$NCL" wirings list --json | jq -r --arg a "$g" '.data[] | select(.agent_group_id==$a) | .id' | head -1)
  [ -n "$W" ] && "$NCL" wirings update "$W" --engage-mode mention-sticky --session-mode per-thread --threads 1 >/dev/null 2>&1 || true
  log "wiring ensured for #$name (mention-sticky, replies in-thread)"
  # cli-scope "group": the agent may create/cancel its OWN group's tasks (the
  # 20-minute help-desk follow-up needs it); "disabled" broke that.
  "$NCL" groups config update --id "$g" --cli-scope group --assistant-name plex-ops >/dev/null
  # groups/<folder>/container.json is MATERIALIZED FROM THE DATABASE at every
  # spawn (src/container-config.ts materializeContainerJson); hand edits to
  # the file are overwritten. Everything below therefore goes to the DB row
  # (container_configs) or the host allowlist, never to the file.
  # containerPath must be RELATIVE (mount-security rejects "/data" silently);
  # it lands at /workspace/extra/<name> inside the container.
  if ! "$NCL" groups config get --id "$g" --json | jq -e '.data.additional_mounts[]? | select(.containerPath=="data")' >/dev/null 2>&1; then
    "$NCL" groups config add-mount --id "$g" --host "$MOUNT" --container data --ro >/dev/null
    log "mount added: $MOUNT -> /workspace/extra/data (ro)"
  fi
  # Host mount allowlist (~/.config/nanoclaw/mount-allowlist.json): a mount
  # outside an allowed root is silently not attached.
  local al="$HOME/.config/nanoclaw/mount-allowlist.json" tmp; tmp=$(mktemp)
  [ -f "$al" ] || echo '{"allowedRoots": [], "blockedPatterns": []}' > "$al"
  jq --arg p "$MOUNT" '.allowedRoots |= (if map(.path) | index($p) then . else
      . + [{path: $p, allowReadWrite: false, description: "nemesis media export (ro) - #plex-ops agent"}] end)' "$al" > "$tmp" && mv "$tmp" "$al"
  log "mount allowlist covers $MOUNT (read-only)"
  # Runner creds (+ the local-vLLM proxy env and Anthropic block when MODEL is
  # the local backend) as the container_configs.env / blocked_hosts JSON
  # columns (no ncl verb exists for them).
  RUNNER_URL="$RUNNER_URL" RUNNER_TOKEN="$RUNNER_TOKEN" PROXY_URL="$PROXY_URL" GID="$g" MODEL="$MODEL" python3 - <<'PY'
import json, os, sqlite3
local = not os.environ["MODEL"].startswith("claude-")
env = {"RUNNER_URL": os.environ["RUNNER_URL"], "RUNNER_TOKEN": os.environ["RUNNER_TOKEN"]}
if local:
    env.update({"ANTHROPIC_BASE_URL": os.environ["PROXY_URL"], "NO_PROXY": "host.docker.internal",
                "no_proxy": "host.docker.internal", "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "4096"})
c = sqlite3.connect("/docker/nanoclaw/data/v2.db", timeout=10)
c.execute("update container_configs set env=?, blocked_hosts=?, timezone=coalesce(timezone, 'America/Detroit'),"
          " updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') where agent_group_id=?",
          (json.dumps(env), json.dumps(["api.anthropic.com"]) if local else None, os.environ["GID"]))
c.commit()
PY
  log "stored env set for model $MODEL (runner creds$( [ "${MODEL#claude-}" = "$MODEL" ] && echo ', proxy backend, Anthropic blocked' ))"
  "$NCL" groups config update --id "$g" --model "$MODEL" >/dev/null
  # MCP server in the stored config. The CLI (and the loader) require HTTPS
  # off-host, so this is the Traefik route to the runner, not :8377 directly.
  # An unreachable MCP server breaks every model turn ("Content block is not
  # a text block", observed 2026-09-13), so register it only once the route
  # answers over valid TLS (Traefik default cert = route not live yet).
  local mcp_code; mcp_code=$(curl -sS -m 8 -o /dev/null -w '%{http_code}' -X POST -H "Authorization: Bearer $RUNNER_TOKEN" \
    -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"ping"}' "$MCP_URL" 2>/dev/null || echo 000)
  if [ "$mcp_code" = 200 ]; then
    if ! "$NCL" groups config get --id "$g" --json | jq -e '.data.mcp_servers["plex-ops"]' >/dev/null 2>&1; then
      "$NCL" groups config add-mcp-server --id "$g" --name plex-ops --url "$MCP_URL" \
        --headers "{\"Authorization\":\"Bearer $RUNNER_TOKEN\"}" >/dev/null
      log "MCP server registered: $MCP_URL"
    fi
  else
    if "$NCL" groups config get --id "$g" --json | jq -e '.data.mcp_servers["plex-ops"]' >/dev/null 2>&1; then
      "$NCL" groups config remove-mcp-server --id "$g" --name plex-ops >/dev/null 2>&1 || true
      log "MCP route not live (HTTP $mcp_code): removed the stale MCP registration"
    else
      log "MCP route not live (HTTP $mcp_code): skipping MCP registration; agent uses curl against RUNNER_URL. Re-run 'group' after the Traefik route is merged."
    fi
  fi
  # Model lives in the group's shared Claude settings, like the other vault groups.
  local sdir="$NC/data/v2-sessions/$g/.claude-shared" s tpl
  mkdir -p "$sdir"; s="$sdir/settings.json"
  if [ ! -f "$s" ]; then
    tpl=$(grep -l "\"$MODEL\"" "$NC"/data/v2-sessions/*/.claude-shared/settings.json 2>/dev/null | head -1)
    [ -n "$tpl" ] && cp "$tpl" "$s" || echo '{}' > "$s"
  fi
  tmp=$(mktemp); jq --arg m "$MODEL" '.model = $m' "$s" > "$tmp" && mv "$tmp" "$s"
  log "model=$MODEL in $s"
  install -m 0644 "$ART/AGENTS.md" "$NC/groups/$FOLDER/instructions.prepend.md"
  log "prompt installed"
}

do_skills() {
  local store="$NC/groups/_skills" d name desc
  for d in queue-triage service-watchdog library-audit digest reclaim; do
    name="plexops-$d"
    case "$d" in
      queue-triage)     desc="plex-ops duty: classify both arr queues via the runner and act per the auto/approval tiers (shadow-aware). Use for any queue, stuck download, or malware-grab question." ;;
      service-watchdog) desc="plex-ops duty: check service-health via the runner and apply the three known-signature fixes (prowlarr restart, pull-recreate, resurrect stragglers), report the rest. Use for any 'is the stack healthy' question." ;;
      library-audit)    desc="plex-ops duty: nightly chunked library audit and weekly rollup via the runner (missing/sparse/orphan/duplicate findings), report-only. Use for library integrity questions." ;;
      digest)           desc="plex-ops duty: weekly digest of fixed / waiting / disk trajectory from memory and the disk probe." ;;
      reclaim)          desc="plex-ops compression waves: 'what movies can we compress tonight' (reclaim_plan: counts by size band + expected gain), 'run it' (reclaim_schedule, Arthur only), compression status, pause/resume, pilot ack. Use for anything about compressing/transcoding the movie library or reclaiming space." ;;
    esac
    mkdir -p "$store/$name"
    { printf -- '---\nname: %s\ndescription: %s\n---\n\n' "$name" "$desc"; cat "$ART/$d.md"; } > "$store/$name/SKILL.md"
    grep -q "^$name = " "$store/MANIFEST" || echo "$name = $FOLDER" >> "$store/MANIFEST"
  done
  bash "$store/sync-skills.sh"
  log "skills synced; restarting group"
  "$NCL" groups restart --id "$(gid)" >/dev/null || true
}

task_exists() { "$NCL" tasks list 2>/dev/null | awk '{print $1}' | grep -q "^$1-"; }
task_id() { "$NCL" tasks list 2>/dev/null | awk -v p="^$1-" '$1 ~ p {print $1; exit}'; }
# Existing gated tasks get the current gate script (the gates run inside the
# agent container; docker cp / scp nesting bit us once, so always refresh).
refresh_gate() { task_exists "$1" && "$NCL" tasks update --id "$(task_id "$1")" --script "$(cat "$2")" >/dev/null && log "gate refreshed on $1"; }

do_tasks() {
  local g; g=$(gid)
  log "gate self-test (must end with a wakeAgent JSON line):"
  bash -c "$(cat "$ART/gates/watchdog-gate.sh")" | tail -n 1 | cut -c1-200
  bash -c "$(cat "$ART/gates/triage-gate.sh")" | tail -n 1 | cut -c1-200
  refresh_gate plexops-queue-triage "$ART/gates/triage-gate.sh" || true
  refresh_gate plexops-watchdog "$ART/gates/watchdog-gate.sh" || true
  task_exists plexops-queue-triage || "$NCL" tasks create --group "$g" --name plexops-queue-triage --recurrence "15 */2 * * *" \
    --script "$(cat "$ART/gates/triage-gate.sh")" \
    --prompt "Scheduled run: invoke the plexops-queue-triage skill and execute it now. The data attached to this prompt is the gate's queue-health summary that triggered the run. Post results to #plex-ops."
  task_exists plexops-watchdog || "$NCL" tasks create --group "$g" --name plexops-watchdog --recurrence "*/30 * * * *" \
    --script "$(cat "$ART/gates/watchdog-gate.sh")" \
    --prompt "Scheduled run: invoke the plexops-service-watchdog skill and execute it now. The data attached to this prompt is the gate's service-health summary that triggered the run. Post to #plex-ops only if something needs action or approval."
  task_exists plexops-audit-chunk || "$NCL" tasks create --group "$g" --name plexops-audit-chunk --recurrence "30 3 * * *" \
    --prompt "Scheduled run: invoke the plexops-library-audit skill and run the nightly chunk for today's weekday. Log to memory; post to #plex-ops only if urgent."
  task_exists plexops-audit-rollup || "$NCL" tasks create --group "$g" --name plexops-audit-rollup --recurrence "0 8 * * 0" \
    --prompt "Scheduled run: invoke the plexops-library-audit skill and run the weekly rollup. Post the summary and approval list to #plex-ops."
  task_exists plexops-digest || "$NCL" tasks create --group "$g" --name plexops-digest --recurrence "0 9 * * 0" \
    --prompt "Scheduled run: invoke the plexops-digest skill and post the weekly digest to #plex-ops."
  "$NCL" tasks list | grep -E '^(SERIES|plexops-)' || true
}

do_commit() {
  ( cd "$NC/groups" && git add "$FOLDER" _skills 2>/dev/null && git commit -q -m "feat($FOLDER): plex-ops group, duty skills, and prompt" && log "groups repo committed" ) || log "groups repo: nothing to commit"
}

do_verify() {
  local g; g=$(gid)
  local tid; tid=$("$NCL" tasks list | awk '/^plexops-watchdog-/{print $1}' | head -1)
  [ -n "$tid" ] || { echo "watchdog task missing - run: $0 tasks" >&2; exit 1; }
  log "firing the watchdog task once ($tid); watch #plex-ops for a SHADOW report"
  "$NCL" tasks run "$tid" || true
  sleep 20
  local c; c=$(docker ps -q --filter "label=nanoclaw-group-folder=$FOLDER" | head -1)
  if [ -n "$c" ]; then
    log "container env:"; docker exec "$c" env | grep -E '^(RUNNER_URL|ANTHROPIC_BASE_URL|NO_PROXY|CLAUDE_CODE_MAX_OUTPUT_TOKENS)=' || true
    log "anthropic blocked: $(docker inspect "$c" | grep -c 'api.anthropic.com')"
    log "runner from inside: $(docker exec "$c" sh -c 'curl -sS -m 10 -H "Authorization: Bearer $RUNNER_TOKEN" "$RUNNER_URL/probe/disk" | head -c 120')"
    log "mcp from inside: $(docker exec "$c" sh -c 'curl -sS -m 10 -H "Authorization: Bearer $RUNNER_TOKEN" -H "Content-Type: application/json" -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}" "$RUNNER_URL/mcp" | grep -o "\"name\":\"[a-z_]*\"" | wc -l') tools"
    log "media mount: $(docker exec "$c" sh -c 'ls /workspace/extra/data | head -5' | tr '\n' ' ')"
  else
    log "no running container yet (spawns on the first message/task); re-run verify in a minute"
  fi
}

case "${1:-}" in
  nfs) do_nfs ;;
  channel) do_channel ;;
  group) preflight; do_group ;;
  skills) do_skills ;;
  tasks) preflight; do_tasks ;;
  commit) do_commit ;;
  verify) preflight; do_verify ;;
  all) preflight; do_nfs; do_channel; do_group; do_skills; do_tasks; do_commit; do_verify ;;
  *) sed -n 2,20p "$0"; exit 1 ;;
esac
