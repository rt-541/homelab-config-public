#!/bin/sh
# Discord notifier for the ollama service: polls TCP 11434 on the
# ollama container, fires WEBHOOK_URL on up/down state transitions.

apk add --no-cache curl >/dev/null 2>&1

if [ -z "$WEBHOOK_URL" ]; then
  echo "WEBHOOK_URL not set; exiting" >&2
  exit 1
fi

# Grace period so a slow first start does not immediately announce a flap.
sleep 30

prev=
while true; do
  if nc -z ollama 11434 2>/dev/null; then
    cur=up
  else
    cur=down
  fi
  if [ "$cur" != "$prev" ]; then
    if [ -n "$prev" ]; then
      if [ "$cur" = up ]; then
        msg="Ollama: model server up"
      else
        msg="Ollama: model server down"
      fi
      curl -sS -X POST -H "Content-Type: application/json" \
        -d "$(printf '{"content":"%s"}' "$msg")" \
        "$WEBHOOK_URL" >/dev/null
    fi
    prev="$cur"
  fi
  sleep 15
done
