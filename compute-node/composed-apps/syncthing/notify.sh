#!/bin/sh
# Discord up/down notifier for the syncthing container. Polls the Syncthing
# health endpoint over the compose network; posts once on each transition.
apk add --no-cache curl >/dev/null 2>&1
command -v curl >/dev/null 2>&1 || { echo "FATAL: curl install failed"; exit 1; }
[ -n "$WEBHOOK_URL" ] || { echo "FATAL: WEBHOOK_URL is empty - set it in .env"; exit 1; }

ST=http://syncthing:8384

send() {
  TITLE="$1"
  COLOR="$2"
  DESC="$3"
  if [ -n "$DESC" ]; then
    JSON="{\"username\":\"Syncthing\",\"embeds\":[{\"title\":\"${TITLE}\",\"description\":\"${DESC}\",\"color\":${COLOR},\"footer\":{\"text\":\"syncthing on devastator\"}}]}"
  else
    JSON="{\"username\":\"Syncthing\",\"embeds\":[{\"title\":\"${TITLE}\",\"color\":${COLOR},\"footer\":{\"text\":\"syncthing on devastator\"}}]}"
  fi
  curl -sf -X POST "$WEBHOOK_URL" -H 'Content-Type: application/json' -d "$JSON"
}

healthy() {
  curl -sf -m 5 "$ST/rest/noauth/health" >/dev/null 2>&1
}

echo "Waiting for Syncthing to become healthy..."
while ! healthy; do sleep 15; done
send "Syncthing Up" 65280 "Vault replicas at /docker/obsidian are syncing"

while true; do
  sleep 30
  if ! healthy; then
    send "Syncthing Down" 16711680
    while ! healthy; do sleep 30; done
    send "Syncthing Up" 65280 "Recovered"
  fi
done
