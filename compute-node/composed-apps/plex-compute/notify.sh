#!/bin/sh
apk add --no-cache curl >/dev/null 2>&1
command -v curl >/dev/null 2>&1 || { echo "FATAL: curl install failed"; exit 1; }
[ -n "$WEBHOOK_URL" ] || { echo "FATAL: WEBHOOK_URL is empty - set it in .env"; exit 1; }

THRESHOLD="${QUEUE_ALERT_THRESHOLD:-5}"
VLLM=http://vllm:8000

send() {
  TITLE="$1"
  COLOR="$2"
  DESC="$3"
  if [ -n "$DESC" ]; then
    JSON="{\"username\":\"B70 vLLM\",\"embeds\":[{\"title\":\"${TITLE}\",\"description\":\"${DESC}\",\"color\":${COLOR},\"footer\":{\"text\":\"plex-compute on devastator\"}}]}"
  else
    JSON="{\"username\":\"B70 vLLM\",\"embeds\":[{\"title\":\"${TITLE}\",\"color\":${COLOR},\"footer\":{\"text\":\"plex-compute on devastator\"}}]}"
  fi
  curl -sf -X POST "$WEBHOOK_URL" -H 'Content-Type: application/json' -d "$JSON"
}

healthy() {
  curl -sf -m 5 "$VLLM/health" >/dev/null 2>&1
}

queue_depth() {
  curl -sf -m 5 "$VLLM/metrics" 2>/dev/null \
    | grep '^vllm:num_requests_waiting' | tail -1 \
    | awk '{print int($NF)}'
}

echo "Waiting for vLLM to become healthy (model load can take many minutes)..."
while ! healthy; do sleep 30; done
send "vLLM Up" 65280 "Serving qwen2.5-7b-instruct on the B70"

QUEUE_ALERTED=0
while true; do
  sleep 30
  if ! healthy; then
    send "vLLM Down" 16711680
    while ! healthy; do sleep 30; done
    send "vLLM Up" 65280 "Back online"
    QUEUE_ALERTED=0
    continue
  fi
  DEPTH=$(queue_depth)
  [ -z "$DEPTH" ] && DEPTH=0
  if [ "$DEPTH" -gt "$THRESHOLD" ] && [ "$QUEUE_ALERTED" -eq 0 ]; then
    send "vLLM Queue Backlog" 16753920 "${DEPTH} requests waiting (threshold ${THRESHOLD})"
    QUEUE_ALERTED=1
  elif [ "$DEPTH" -le "$THRESHOLD" ] && [ "$QUEUE_ALERTED" -eq 1 ]; then
    send "vLLM Queue Drained" 65280 "${DEPTH} requests waiting"
    QUEUE_ALERTED=0
  fi
done
