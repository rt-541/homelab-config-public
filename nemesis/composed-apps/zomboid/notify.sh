#!/bin/sh
apk add --no-cache curl grep coreutils > /dev/null 2>&1

LOG_DIR="/zomboid-logs"
CONSOLE_LOG="${LOG_DIR}/server-console.txt"
LAST_POS=0

send() {
  TITLE="$1"
  COLOR="$2"
  DESC="$3"
  if [ -n "$DESC" ]; then
    JSON="{\"username\":\"ZP-742\",\"embeds\":[{\"title\":\"${TITLE}\",\"description\":\"${DESC}\",\"color\":${COLOR},\"footer\":{\"text\":\"Flight Group Alpha PZ Server\"}}]}"
  else
    JSON="{\"username\":\"ZP-742\",\"embeds\":[{\"title\":\"${TITLE}\",\"color\":${COLOR},\"footer\":{\"text\":\"Flight Group Alpha PZ Server\"}}]}"
  fi
  curl -sf -X POST "$WEBHOOK_URL" -H 'Content-Type: application/json' -d "$JSON"
}

check_logs() {
  if [ ! -f "$CONSOLE_LOG" ]; then
    return
  fi

  CURRENT_SIZE=$(stat -c%s "$CONSOLE_LOG" 2>/dev/null || echo "0")

  if [ "$CURRENT_SIZE" -lt "$LAST_POS" ]; then
    LAST_POS=0
  fi

  if [ "$CURRENT_SIZE" -gt "$LAST_POS" ]; then
    tail -c +$((LAST_POS + 1)) "$CONSOLE_LOG" | while IFS= read -r line; do
      # Player joined patterns - look for "Username" fully connected
      if echo "$line" | grep -q "fully connected"; then
        PLAYER=$(echo "$line" | grep -oE '"[^"]+"' | head -1 | tr -d '"')
        if [ -n "$PLAYER" ]; then
          echo "Player joined: $PLAYER"
          send "🟢 Player Joined" 3447003 "**${PLAYER}** has entered the game"
        fi
      fi

      # Player left patterns - look for Connection disconnect
      if echo "$line" | grep -q "Connection disconnect"; then
        STEAMID=$(echo "$line" | grep -oE "id=[0-9]+" | cut -d'=' -f2)
        # Try to find username from recent logs
        PLAYER=$(grep -B 50 "Connection disconnect" "$CONSOLE_LOG" | grep "$STEAMID" | grep -oE '"[^"]+"' | head -1 | tr -d '"')
        if [ -z "$PLAYER" ]; then
          PLAYER="A player"
        fi
        echo "Player left: $PLAYER"
        send "🔴 Player Left" 15158332 "**${PLAYER}** has left the game"
      fi
    done
    LAST_POS=$CURRENT_SIZE
  fi
}

echo "Waiting for Zomboid server to start..."
while ! nc -z zomboid-dedicated-server 27015 2>/dev/null; do
  sleep 10
done
echo "Server is up, sending start notification"
send "🟢 Server Started" 65280 "The zombie apocalypse awaits!"

# Monitor server status and logs
while true; do
  sleep 5

  # Check if server is still running
  if ! nc -z zomboid-dedicated-server 27015 2>/dev/null; then
    echo "Server went down, sending stop notification"
    send "🔴 Server Stopped" 16711680
    echo "Waiting for server to restart..."
    while ! nc -z zomboid-dedicated-server 27015 2>/dev/null; do
      sleep 10
    done
    echo "Server is back up, sending start notification"
    send "🟢 Server Started" 65280 "The zombie apocalypse awaits!"
    LAST_POS=0
  fi

  # Check for player join/leave events
  check_logs
done
