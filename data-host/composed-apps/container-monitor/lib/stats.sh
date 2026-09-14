#!/bin/sh
# Container stats and metrics collection library

get_container_state() {
  local name="$1"
  local state
  state=$(docker inspect --format '{{.State.Status}}' "$name" 2>/dev/null)
  if [ -z "$state" ]; then
    echo "not-found"
  else
    echo "$state"
  fi
}

get_container_health() {
  local name="$1"
  local health
  health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$name" 2>/dev/null)
  if [ -z "$health" ]; then
    echo "unknown"
  else
    echo "$health"
  fi
}

get_container_uptime() {
  local name="$1"
  local started_at
  started_at=$(docker inspect --format '{{.State.StartedAt}}' "$name" 2>/dev/null)

  if [ -z "$started_at" ] || [ "$started_at" = "0001-01-01T00:00:00Z" ]; then
    echo "N/A"
    return
  fi

  local start_epoch now_epoch diff_seconds
  start_epoch=$(date -d "$started_at" +%s 2>/dev/null)
  now_epoch=$(date +%s)

  if [ -z "$start_epoch" ]; then
    echo "N/A"
    return
  fi

  diff_seconds=$((now_epoch - start_epoch))

  if [ "$diff_seconds" -lt 0 ]; then
    echo "N/A"
    return
  fi

  local days hours minutes
  days=$((diff_seconds / 86400))
  hours=$(( (diff_seconds % 86400) / 3600 ))
  minutes=$(( (diff_seconds % 3600) / 60 ))

  if [ "$days" -gt 0 ]; then
    echo "${days}d ${hours}h"
  elif [ "$hours" -gt 0 ]; then
    echo "${hours}h ${minutes}m"
  else
    echo "${minutes}m"
  fi
}

get_container_stats() {
  local name="$1"
  local stats
  stats=$(docker stats --no-stream --format '{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}}' "$name" 2>/dev/null)
  if [ -z "$stats" ]; then
    echo "N/A,N/A,N/A"
  else
    echo "$stats"
  fi
}
