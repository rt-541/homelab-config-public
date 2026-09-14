#!/bin/sh
set -e

CONFIG="/config.yml"

# Source libraries
. /lib/discord.sh
. /lib/stats.sh
. /lib/scheduler.sh

# Check if a container should be monitored
is_monitored() {
  local name="$1"

  # Check exclude list
  local excluded
  excluded=$(yq e '.exclude[]' "$CONFIG" 2>/dev/null)
  for ex in $excluded; do
    if [ "$name" = "$ex" ]; then
      return 1
    fi
  done

  # Check for monitor.disabled label
  local disabled
  disabled=$(docker inspect --format '{{index .Config.Labels "monitor.disabled"}}' "$name" 2>/dev/null)
  if [ "$disabled" = "true" ]; then
    return 1
  fi

  return 0
}

# Get webhook URL for a container, checking env vars first
get_webhook_url() {
  local name="$1"

  # Check for container-specific env var (mapped in config)
  local env_var
  env_var=$(yq e ".overrides.\"${name}\".webhook_env // \"\"" "$CONFIG" 2>/dev/null)
  if [ -n "$env_var" ] && [ "$env_var" != "null" ]; then
    local env_val
    eval "env_val=\${${env_var}:-}"
    if [ -n "$env_val" ]; then
      echo "$env_val"
      return
    fi
  fi

  # Check for override webhook_url in config
  local val
  val=$(yq e ".overrides.\"${name}\".webhook_url // \"\"" "$CONFIG" 2>/dev/null)
  if [ -n "$val" ] && [ "$val" != "null" ]; then
    echo "$val"
    return
  fi

  # Fall back to DEFAULT_WEBHOOK_URL env var, then config default
  if [ -n "$DEFAULT_WEBHOOK_URL" ]; then
    echo "$DEFAULT_WEBHOOK_URL"
  else
    yq e '.defaults.webhook_url // ""' "$CONFIG" 2>/dev/null
  fi
}

# Get config value with cascade: override -> default
get_config_value() {
  local name="$1"
  local key="$2"

  # Webhook URLs use dedicated lookup with env var support
  if [ "$key" = "webhook_url" ]; then
    get_webhook_url "$name"
    return
  fi

  # Try container-specific override first
  local val
  val=$(yq e ".overrides.\"${name}\".${key} // \"\"" "$CONFIG" 2>/dev/null)

  if [ -n "$val" ] && [ "$val" != "null" ]; then
    echo "$val"
    return
  fi

  # Fall back to defaults
  val=$(yq e ".defaults.${key} // \"\"" "$CONFIG" 2>/dev/null)

  if [ -n "$val" ] && [ "$val" != "null" ]; then
    echo "$val"
    return
  fi

  # Special case: display_name falls back to container name
  if [ "$key" = "display_name" ]; then
    echo "$name"
  fi
}

# Send notification for a container event
notify_event() {
  local name="$1"
  local action="$2"

  local display_name webhook_url username footer

  display_name=$(get_config_value "$name" "display_name")
  [ -z "$display_name" ] && display_name="$name"

  webhook_url=$(get_config_value "$name" "webhook_url")
  username=$(get_config_value "$name" "username")
  footer=$(get_config_value "$name" "footer")

  local title color desc=""

  case "$action" in
    start)
      local emoji
      emoji=$(get_config_value "$name" "start_emoji")
      color=$(get_config_value "$name" "color_start")
      title="${emoji} ${display_name} Started"
      desc=$(get_config_value "$name" "start_message")
      # start_message_env lets the message live in an env var (e.g. it
      # contains a join password that must stay out of config.yml)
      local msg_env
      msg_env=$(yq e ".overrides.\"${name}\".start_message_env // \"\"" "$CONFIG" 2>/dev/null)
      if [ -n "$msg_env" ] && [ "$msg_env" != "null" ]; then
        local msg_val
        eval "msg_val=\${${msg_env}:-}"
        [ -n "$msg_val" ] && desc="$msg_val"
      fi
      ;;
    stop)
      local emoji
      emoji=$(get_config_value "$name" "stop_emoji")
      color=$(get_config_value "$name" "color_stop")
      title="${emoji} ${display_name} Stopped"
      desc=$(get_config_value "$name" "stop_message")
      ;;
    die|kill)
      local exit_code
      exit_code=$(docker inspect --format '{{.State.ExitCode}}' "$name" 2>/dev/null || echo "unknown")
      # die with exit code 0 is a normal stop (e.g. docker stop sends SIGTERM -> die(0))
      if [ "$exit_code" = "0" ]; then
        local emoji
        emoji=$(get_config_value "$name" "stop_emoji")
        color=$(get_config_value "$name" "color_stop")
        title="${emoji} ${display_name} Stopped"
        desc=$(get_config_value "$name" "stop_message")
      else
        local emoji
        emoji=$(get_config_value "$name" "crash_emoji")
        color=$(get_config_value "$name" "color_crash")
        title="${emoji} ${display_name} Crashed"
        desc="Exit code: ${exit_code}"
      fi
      ;;
  esac

  echo "[monitor] ${title}"
  send_discord_notification "$title" "$color" "$desc" "$username" "$footer" "$webhook_url"
}

# Background scheduler for periodic tasks
start_scheduler() {
  local enabled
  enabled=$(yq e '.status_report.enabled // "true"' "$CONFIG" 2>/dev/null)

  if [ "$enabled" != "true" ]; then
    echo "[scheduler] Status reports disabled"
    return
  fi

  local schedule
  schedule=$(yq e '.status_report.schedule // "0 8 * * *"' "$CONFIG" 2>/dev/null)
  echo "[scheduler] Status report schedule: ${schedule}"

  while true; do
    if should_run_now "$schedule"; then
      echo "[scheduler] Running status report"
      /bin/sh /status-report.sh
      # Sleep 60s after execution to prevent duplicate runs
      sleep 60
    fi

    # Check mod monitor schedules
    local mod_servers
    mod_servers=$(yq e '.mod_monitor.servers | keys | .[]' "$CONFIG" 2>/dev/null || true)
    for server in $mod_servers; do
      local mod_enabled mod_schedule
      mod_enabled=$(yq e ".mod_monitor.servers.${server}.enabled // \"true\"" "$CONFIG" 2>/dev/null)
      mod_schedule=$(yq e ".mod_monitor.servers.${server}.schedule // \"\"" "$CONFIG" 2>/dev/null)

      if [ "$mod_enabled" = "true" ] && [ -n "$mod_schedule" ] && should_run_now "$mod_schedule"; then
        echo "[scheduler] Running mod monitor for ${server}"
        /bin/sh /mod-monitor.sh "$server" || true
      fi
    done

    sleep 30
  done
}

# --- Main ---

echo "[monitor] Container Monitor starting..."
echo "[monitor] Config: ${CONFIG}"

# Start scheduler in background
start_scheduler &
SCHEDULER_PID=$!
echo "[monitor] Scheduler started (PID: ${SCHEDULER_PID})"

# Send startup notification
startup_webhook="${DEFAULT_WEBHOOK_URL:-$(yq e '.defaults.webhook_url' "$CONFIG" 2>/dev/null)}"
startup_username=$(yq e '.defaults.username // "Container Monitor"' "$CONFIG" 2>/dev/null)
startup_footer=$(yq e '.defaults.footer // "Container Status"' "$CONFIG" 2>/dev/null)
send_discord_notification "Container Monitor Online" 65280 "Monitoring all containers for lifecycle events." "$startup_username" "$startup_footer" "$startup_webhook"

echo "[monitor] Listening for container events..."

# Main event loop - listen for Docker container lifecycle events
docker events --format '{{json .}}' \
  --filter type=container \
  --filter event=start \
  --filter event=stop \
  --filter event=die \
  --filter event=kill | while IFS= read -r event; do

  # Parse event JSON
  container_name=$(echo "$event" | jq -r '.Actor.Attributes.name // empty')
  action=$(echo "$event" | jq -r '.Action // empty')

  if [ -z "$container_name" ] || [ -z "$action" ]; then
    continue
  fi

  # Skip unmonitored containers
  if ! is_monitored "$container_name"; then
    echo "[monitor] Skipping excluded container: ${container_name} (${action})"
    continue
  fi

  # Deduplicate: docker stop produces both 'die' and 'stop' events.
  # We handle 'die' (which comes first and carries the exit code) and skip 'stop'.
  if [ "$action" = "stop" ]; then
    continue
  fi

  notify_event "$container_name" "$action"
done
