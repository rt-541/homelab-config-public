#!/bin/sh
apk add --no-cache curl > /dev/null 2>&1

send() {
  TITLE="$1"
  COLOR="$2"
  DESC="$3"
  if [ -n "$DESC" ]; then
    JSON="{\"username\":\"ATM9 Survival\",\"embeds\":[{\"title\":\"${TITLE}\",\"description\":\"${DESC}\",\"color\":${COLOR},\"footer\":{\"text\":\"ATM9 Survival Server\"}}]}"
  else
    JSON="{\"username\":\"ATM9 Survival\",\"embeds\":[{\"title\":\"${TITLE}\",\"color\":${COLOR},\"footer\":{\"text\":\"ATM9 Survival Server\"}}]}"
  fi
  curl -sf -X POST "$WEBHOOK_URL" -H 'Content-Type: application/json' -d "$JSON"
}

echo "Waiting for server to start..."
while ! nc -z minecraft-atm9-survival 25565 2>/dev/null; do
  sleep 10
done
echo "Server is up, sending start notification"
send "Server Started" 65280 "Connect: minecraft.rt-541.io:25567"

while true; do
  sleep 30
  if ! nc -z minecraft-atm9-survival 25565 2>/dev/null; then
    echo "Server went down, sending stop notification"
    send "Server Stopped" 16711680
    echo "Waiting for server to restart..."
    while ! nc -z minecraft-atm9-survival 25565 2>/dev/null; do
      sleep 10
    done
    echo "Server is back up, sending start notification"
    send "Server Started" 65280 "Connect: minecraft.rt-541.io:25567"
  fi
done
