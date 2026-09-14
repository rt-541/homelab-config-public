#!/bin/sh
# Mod update monitor — reads locally installed mod versions from Steam's
# appworkshop ACF file, diffs against upstream Steam Workshop timestamps,
# and alerts when the server is running stale mods.
#
# Called by monitor.sh scheduler. Reads config from /config.yml.
# Usage: mod-monitor.sh [server-key]
#   If server-key given, check only that server.
#   If omitted, check all enabled servers.

set -e

CONFIG="/config.yml"
STATE_DIR="/state"

. /lib/discord.sh

# Parse WorkshopItemsInstalled from a Valve ACF file.
# Extracts {mod_id: timeupdated} pairs as JSON.
parse_acf_timestamps() {
  local acf_path="$1"

  awk '
    BEGIN { in_section=0; depth=0; current_id="" }
    /\"WorkshopItemsInstalled\"/ { in_section=1; next }
    !in_section { next }
    /\{/ { depth++; next }
    /\}/ { depth--; if (depth <= 0) { in_section=0 }; next }
    depth == 1 && /^[[:space:]]*\"[0-9]+\"/ {
      id = $0; gsub(/[^0-9]/, "", id); current_id = id; next
    }
    depth == 2 && /\"timeupdated\"/ {
      ts = $2; gsub(/"/, "", ts); print current_id " " ts
    }
  ' "$acf_path" | jq -Rn '[inputs | split(" ") | {(.[0]): (.[1] | tonumber)}] | add // {}'
}

# Query Steam Workshop API for mod details
# Args: space-separated workshop IDs
# Returns: JSON with publishedfiledetails
query_steam_api() {
  local ids="$1"
  local count=0
  local form_data=""

  for id in $ids; do
    [ -z "$id" ] && continue
    form_data="${form_data}&publishedfileids[${count}]=${id}"
    count=$((count + 1))
  done

  [ "$count" -eq 0 ] && return 1

  form_data="itemcount=${count}${form_data}"

  curl -sf -X POST \
    "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/" \
    -d "$form_data" 2>/dev/null
}

# Check a single server for stale mods
check_server() {
  local server="$1"

  local acf_path
  acf_path=$(yq e ".mod_monitor.servers.${server}.acf_path // \"\"" "$CONFIG" 2>/dev/null)
  if [ -z "$acf_path" ] || [ ! -f "$acf_path" ]; then
    echo "[mod-monitor] ERROR: ACF not found for ${server}: ${acf_path}"
    return 1
  fi

  # Parse local installed state from ACF
  local local_state
  local_state=$(parse_acf_timestamps "$acf_path")

  local mod_ids
  mod_ids=$(echo "$local_state" | jq -r 'keys[]')
  local mod_count
  mod_count=$(echo "$mod_ids" | grep -c . || true)

  if [ "$mod_count" -eq 0 ]; then
    echo "[mod-monitor] ${server}: No mods found in ACF"
    return 0
  fi

  echo "[mod-monitor] Checking ${server}: ${mod_count} mods installed locally"

  # Query Steam API for upstream state
  local response
  response=$(query_steam_api "$mod_ids")
  if [ -z "$response" ]; then
    echo "[mod-monitor] ERROR: Steam API request failed for ${server}"
    return 1
  fi

  # Build upstream state: {id: time_updated}
  local upstream_state
  upstream_state=$(echo "$response" | jq -r \
    '[.response.publishedfiledetails[] | {(.publishedfileid): .time_updated}] | add // {}')

  # Find stale mods: upstream time_updated > local timeupdated
  local stale_ids
  stale_ids=$(jq -n \
    --argjson local "$local_state" \
    --argjson upstream "$upstream_state" \
    '[$upstream | to_entries[] | select(($local[.key] // 0) < .value)] | map(.key) | .[]' \
    2>/dev/null | tr -d '"')

  if [ -z "$stale_ids" ]; then
    echo "[mod-monitor] ${server}: All mods up to date"
    # Clear any previous stale notifications
    rm -f "${STATE_DIR}/${server}-stale.json"
    return 0
  fi

  # Load notification state — avoid re-alerting for same stale version
  local state_file="${STATE_DIR}/${server}-stale.json"
  mkdir -p "$STATE_DIR"
  local notified_state="{}"
  if [ -f "$state_file" ]; then
    notified_state=$(cat "$state_file")
  fi

  # Filter to only newly-stale mods (not already notified for this upstream version)
  local new_stale_ids=""
  local new_notified="$notified_state"
  for mod_id in $stale_ids; do
    local upstream_ts
    upstream_ts=$(echo "$upstream_state" | jq -r ".[\"${mod_id}\"]")
    local already_notified_ts
    already_notified_ts=$(echo "$notified_state" | jq -r ".[\"${mod_id}\"] // 0")

    if [ "$upstream_ts" != "$already_notified_ts" ]; then
      new_stale_ids="${new_stale_ids} ${mod_id}"
      # Track that we notified about this upstream version
      new_notified=$(echo "$new_notified" | jq --arg id "$mod_id" --argjson ts "$upstream_ts" '. + {($id): $ts}')
    fi
  done

  # Remove mods from notified state that are no longer stale
  new_notified=$(jq -n \
    --argjson notified "$new_notified" \
    --argjson local "$local_state" \
    --argjson upstream "$upstream_state" \
    '[$notified | to_entries[] | select(($local[.key] // 0) < ($upstream[.key] // 0))] | from_entries // {}')

  echo "$new_notified" > "$state_file"

  # Trim leading space
  new_stale_ids=$(echo "$new_stale_ids" | sed 's/^ //')

  if [ -z "$new_stale_ids" ]; then
    local total_stale
    total_stale=$(echo "$stale_ids" | wc -w | tr -d ' ')
    echo "[mod-monitor] ${server}: ${total_stale} stale mod(s) but already notified"
    return 0
  fi

  # Build notification message listing ALL stale mods, marking new ones
  local mod_list=""
  local new_count=0
  local total_stale=0
  for mod_id in $stale_ids; do
    local mod_name
    mod_name=$(echo "$response" | jq -r \
      ".response.publishedfiledetails[] | select(.publishedfileid == \"${mod_id}\") | .title // \"Unknown (${mod_id})\"")

    local local_ts upstream_ts
    local_ts=$(echo "$local_state" | jq -r ".[\"${mod_id}\"]")
    upstream_ts=$(echo "$upstream_state" | jq -r ".[\"${mod_id}\"]")
    local age_hours=$(( (upstream_ts - local_ts) / 3600 ))

    # Check if this one is newly stale
    local is_new=""
    for nid in $new_stale_ids; do
      if [ "$nid" = "$mod_id" ]; then
        is_new=" 🆕"
        new_count=$((new_count + 1))
        break
      fi
    done

    mod_list="${mod_list}• [${mod_name}](https://steamcommunity.com/sharedfiles/filedetails/?id=${mod_id}) — ${age_hours}h behind${is_new}\n"
    total_stale=$((total_stale + 1))
  done

  echo "[mod-monitor] ${server}: ${total_stale} stale mod(s), ${new_count} new"

  # Read notification config
  local webhook_env webhook_url username footer auto_restart display_name container_name notify
  notify=$(yq e ".mod_monitor.servers.${server}.notify // \"true\"" "$CONFIG" 2>/dev/null)
  webhook_env=$(yq e ".mod_monitor.servers.${server}.webhook_env // \"\"" "$CONFIG" 2>/dev/null)
  if [ -n "$webhook_env" ] && [ "$webhook_env" != "null" ]; then
    eval "webhook_url=\${${webhook_env}:-}"
  fi
  [ -z "$webhook_url" ] && webhook_url="${DEFAULT_WEBHOOK_URL}"

  username=$(yq e ".mod_monitor.servers.${server}.username // \"Mod Monitor\"" "$CONFIG" 2>/dev/null)
  footer=$(yq e ".mod_monitor.servers.${server}.footer // \"Mod Update Monitor\"" "$CONFIG" 2>/dev/null)
  display_name=$(yq e ".mod_monitor.servers.${server}.display_name // \"${server}\"" "$CONFIG" 2>/dev/null)
  auto_restart=$(yq e ".mod_monitor.servers.${server}.auto_restart // \"false\"" "$CONFIG" 2>/dev/null)
  container_name=$(yq e ".mod_monitor.servers.${server}.container_name // \"\"" "$CONFIG" 2>/dev/null)

  local title desc color

  if [ "$auto_restart" = "true" ] && [ -n "$container_name" ] && [ "$container_name" != "null" ]; then
    title="🔄 ${display_name} — Stale Mods Detected"
    desc=$(printf "%s mod(s) behind Steam Workshop (%s new):\n%s\n⏳ Server restarting to update..." "$total_stale" "$new_count" "$mod_list")
    color=16753920  # Orange

    # notify: false silences routine stale/restarted messages; restart FAILURES
    # still alert below since those need a human.
    [ "$notify" = "false" ] || send_discord_notification "$title" "$color" "$desc" "$username" "$footer" "$webhook_url"

    echo "[mod-monitor] Restarting ${container_name}..."
    if docker restart "$container_name" 2>/dev/null; then
      echo "[mod-monitor] ${container_name} restarted successfully"
      # Clear stale state — server will download updates on startup
      rm -f "$state_file"
      [ "$notify" = "false" ] || send_discord_notification "✅ ${display_name} — Restarted" 65280 \
        "Server has been restarted to pick up mod updates." \
        "$username" "$footer" "$webhook_url"
    else
      echo "[mod-monitor] ERROR: Failed to restart ${container_name}"
      send_discord_notification "❌ ${display_name} — Restart Failed" 16711680 \
        "Auto-restart failed. Manual intervention required." \
        "$username" "$footer" "$webhook_url"
    fi
  else
    title="📦 ${display_name} — Stale Mods Detected"
    desc=$(printf "%s mod(s) behind Steam Workshop (%s new):\n%s\nManual restart required to update." "$total_stale" "$new_count" "$mod_list")
    color=16753920  # Orange

    [ "$notify" = "false" ] || send_discord_notification "$title" "$color" "$desc" "$username" "$footer" "$webhook_url"
  fi
}

# --- Main ---

if [ -n "$1" ]; then
  check_server "$1"
else
  servers=$(yq e '.mod_monitor.servers | keys | .[]' "$CONFIG" 2>/dev/null)
  for server in $servers; do
    enabled=$(yq e ".mod_monitor.servers.${server}.enabled // \"true\"" "$CONFIG" 2>/dev/null)
    if [ "$enabled" = "true" ]; then
      check_server "$server" || true
    fi
  done
fi
