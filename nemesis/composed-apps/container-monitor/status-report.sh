#!/bin/sh

CONFIG="/config.yml"

# Source libraries
. /lib/discord.sh
. /lib/stats.sh

# Load config
include_stopped=$(yq e '.status_report.include_stopped // "true"' "$CONFIG" 2>/dev/null)
include_resource_usage=$(yq e '.status_report.include_resource_usage // "true"' "$CONFIG" 2>/dev/null)
include_uptime=$(yq e '.status_report.include_uptime // "true"' "$CONFIG" 2>/dev/null)
include_health=$(yq e '.status_report.include_health // "true"' "$CONFIG" 2>/dev/null)

# Webhook: env var -> status_report config -> defaults config
webhook_url=$(yq e '.status_report.webhook_url // ""' "$CONFIG" 2>/dev/null)
if [ -z "$webhook_url" ]; then
  webhook_url="${DEFAULT_WEBHOOK_URL:-$(yq e '.defaults.webhook_url' "$CONFIG" 2>/dev/null)}"
fi

username=$(yq e '.defaults.username // "Container Monitor"' "$CONFIG" 2>/dev/null)
footer=$(yq e '.defaults.footer // "Container Status"' "$CONFIG" 2>/dev/null)

# Build exclude list
exclude_list=$(yq e '.exclude[]' "$CONFIG" 2>/dev/null)

is_excluded() {
  local name="$1"
  for ex in $exclude_list; do
    if [ "$name" = "$ex" ]; then
      return 0
    fi
  done
  return 1
}

get_display_name() {
  local name="$1"
  local display
  display=$(yq e ".overrides.\"${name}\".display_name // \"\"" "$CONFIG" 2>/dev/null)
  if [ -n "$display" ] && [ "$display" != "null" ]; then
    echo "$display"
  else
    echo "$name"
  fi
}

# Counters
running_count=0
stopped_count=0
unhealthy_count=0
report_lines=""

NL='
'

echo "[status-report] Generating daily status report..."

# Get all containers
containers=$(docker ps -a --format '{{.Names}}' | sort)

for name in $containers; do
  if is_excluded "$name"; then
    continue
  fi

  display_name=$(get_display_name "$name")
  state=$(get_container_state "$name")

  case "$state" in
    running)
      running_count=$((running_count + 1))

      health=$(get_container_health "$name")
      case "$health" in
        unhealthy)
          unhealthy_count=$((unhealthy_count + 1))
          emoji="🟡"
          ;;
        *)
          emoji="🟢"
          ;;
      esac

      line="${emoji} **${display_name}**"

      if [ "$include_uptime" = "true" ]; then
        uptime=$(get_container_uptime "$name")
        line="${line}: Up ${uptime}"
      fi

      if [ "$include_resource_usage" = "true" ]; then
        stats=$(get_container_stats "$name")
        cpu=$(echo "$stats" | cut -d',' -f1)
        mem=$(echo "$stats" | cut -d',' -f2)
        line="${line} | CPU: ${cpu} | Mem: ${mem}"
      fi

      if [ "$include_health" = "true" ] && [ "$health" = "unhealthy" ]; then
        line="${line} | Health: ${health}"
      fi
      ;;
    exited|dead)
      stopped_count=$((stopped_count + 1))
      line="🔴 **${display_name}**: Stopped"
      ;;
    paused)
      stopped_count=$((stopped_count + 1))
      line="⏸️ **${display_name}**: Paused"
      ;;
    *)
      stopped_count=$((stopped_count + 1))
      line="❓ **${display_name}**: ${state}"
      ;;
  esac

  if [ "$include_stopped" != "true" ] && [ "$state" != "running" ]; then
    continue
  fi

  if [ -n "$report_lines" ]; then
    report_lines="${report_lines}${NL}${line}"
  else
    report_lines="${line}"
  fi
done

# Determine overall status color
if [ "$unhealthy_count" -gt 0 ]; then
  color=16776960   # Yellow
elif [ "$stopped_count" -gt 0 ]; then
  color=16753920   # Orange
else
  color=65280      # Green
fi

summary="Running: ${running_count} | Stopped: ${stopped_count} | Unhealthy: ${unhealthy_count}"
description="${summary}${NL}${NL}${report_lines}"

echo "[status-report] ${summary}"

send_discord_notification \
  "📊 Daily Container Status Report" \
  "$color" \
  "$description" \
  "$username" \
  "$footer" \
  "$webhook_url"

echo "[status-report] Report sent."
