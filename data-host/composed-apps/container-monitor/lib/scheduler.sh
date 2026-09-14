#!/bin/sh
# Simple cron-like scheduler for periodic tasks
# Supports: exact values (0), wildcards (*), and step values (*/6)

match_field() {
  local cron_val="$1"
  local now_val="$2"

  # Wildcard
  if [ "$cron_val" = "*" ]; then
    return 0
  fi

  # Step values: */N
  case "$cron_val" in
    \*/*)
      local step="${cron_val#\*/}"
      if [ "$((now_val % step))" -eq 0 ]; then
        return 0
      fi
      return 1
      ;;
  esac

  # Exact match
  if [ "$cron_val" = "$now_val" ]; then
    return 0
  fi

  return 1
}

should_run_now() {
  local cron_expr="$1"
  local cron_minute cron_hour
  cron_minute=$(echo "$cron_expr" | awk '{print $1}')
  cron_hour=$(echo "$cron_expr" | awk '{print $2}')

  local now_minute now_hour
  now_minute=$(date +%-M)
  now_hour=$(date +%-H)

  if match_field "$cron_minute" "$now_minute" && match_field "$cron_hour" "$now_hour"; then
    return 0
  fi
  return 1
}
