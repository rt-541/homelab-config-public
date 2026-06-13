#!/bin/sh
# Discord webhook notification library

send_discord_notification() {
  TITLE="$1"
  COLOR="$2"
  DESC="$3"
  USERNAME="${4:-Container Monitor}"
  FOOTER="${5:-Container Status}"
  WEBHOOK_URL="$6"

  if [ -z "$WEBHOOK_URL" ]; then
    echo "[discord] ERROR: No webhook URL provided"
    return 1
  fi

  local JSON
  if [ -n "$DESC" ]; then
    JSON=$(jq -n \
      --arg title "$TITLE" \
      --arg desc "$DESC" \
      --argjson color "$COLOR" \
      --arg user "$USERNAME" \
      --arg foot "$FOOTER" \
      '{username: $user, embeds: [{title: $title, description: $desc, color: $color, footer: {text: $foot}}]}')
  else
    JSON=$(jq -n \
      --arg title "$TITLE" \
      --argjson color "$COLOR" \
      --arg user "$USERNAME" \
      --arg foot "$FOOTER" \
      '{username: $user, embeds: [{title: $title, color: $color, footer: {text: $foot}}]}')
  fi

  curl -sf -X POST "$WEBHOOK_URL" -H 'Content-Type: application/json' -d "$JSON"
}
