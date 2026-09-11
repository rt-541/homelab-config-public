#!/usr/bin/env bash
# security-watch.sh — lightweight host IOC watcher for nemesis.
# Hardens against a known class of container-escape/cryptominer persistence
# and alerts the ENG Discord channel via scripts/claude-notify/notify.sh.
#
# Runs from a systemd timer as root (needs to read /proc/*/exe for all procs).
# State in $STATE_DIR dedups alerts so a persistent finding pings once, not every run.
set -uo pipefail

REPO="/docker/homelab-config"
# Note: scripts/claude-notify/ is not included in this public mirror; if it's
# missing, alerting below falls back to logger.
NOTIFY="$REPO/scripts/claude-notify/notify.sh"
STATE_DIR="/var/lib/security-watch"
SEEN="$STATE_DIR/seen"            # signatures already alerted
mkdir -p "$STATE_DIR"
touch "$SEEN"

HOST="$(hostname -s)"
findings=()        # human-readable lines for this run
sigs=()            # stable signatures for dedup

add() {            # add <signature> <message>
  sigs+=("$1"); findings+=("$2")
}

# --- 1. processes executing from tmpfs / world-writable dirs, or a deleted binary ---
# Cryptominers drop to /tmp,/dev/shm,/var/tmp and often delete the on-disk file.
for p in /proc/[0-9]*; do
  pid=${p#/proc/}
  exe=$(readlink "$p/exe" 2>/dev/null) || continue
  case "$exe" in
    *"/tmp/"*|*"/dev/shm/"*|*"/var/tmp/"*|*"(deleted)"*)
      cmd=$(tr '\0' ' ' < "$p/cmdline" 2>/dev/null | cut -c1-100)
      cg=$(grep -o 'docker-[0-9a-f]\{12\}' "$p/cgroup" 2>/dev/null | head -1)
      loc="${cg:-host}"
      add "proc:$exe:$loc" "Suspicious exe [$loc] pid=$pid exe='$exe' cmd='$cmd'"
      ;;
  esac
done

# --- 2. ld.so.preload rootkit/persistence ---
if [ -s /etc/ld.so.preload ]; then
  add "ldpreload:$(md5sum /etc/ld.so.preload | cut -d' ' -f1)" \
      "/etc/ld.so.preload is non-empty: $(tr '\n' ' ' < /etc/ld.so.preload)"
fi

# --- 3. qBittorrent AutoRun re-armed (a known RCE vector for cryptominer persistence) ---
QBT="/docker/qbittorrent/qBittorrent/config/qBittorrent.conf"
if [ -f "$QBT" ] && grep -qiE 'OnTorrent(Added|Finished)\\Enabled=true' "$QBT" 2>/dev/null; then
  prog=$(grep -iE 'OnTorrent.*Program=' "$QBT" | head -1 | cut -c1-120)
  add "qbt-autorun:$(md5sum "$QBT" | cut -d' ' -f1)" \
      "qBittorrent AutoRun is ENABLED again: $prog"
fi

# --- 4. cron additions (root/user crontabs + /etc/cron.d) ---
cronsig=$( { sudo_cat() { cat "$1" 2>/dev/null; }; \
            find /var/spool/cron /etc/cron.d -type f 2>/dev/null -exec md5sum {} + ; } | sort | md5sum | cut -d' ' -f1)
CRONSTATE="$STATE_DIR/cronsig"
if [ -f "$CRONSTATE" ] && [ "$(cat "$CRONSTATE")" != "$cronsig" ]; then
  add "cron:$cronsig" "Cron entries changed (root/user crontab or /etc/cron.d). Review with: ls -la /var/spool/cron /etc/cron.d"
fi
echo "$cronsig" > "$CRONSTATE"

# --- emit only NEW findings (dedup against $SEEN) ---
new_msgs=()
for i in "${!sigs[@]}"; do
  if ! grep -qxF "${sigs[$i]}" "$SEEN" 2>/dev/null; then
    new_msgs+=("${findings[$i]}")
    echo "${sigs[$i]}" >> "$SEEN"
  fi
done

if [ ${#new_msgs[@]} -gt 0 ]; then
  body="$(printf '%s\n' "${new_msgs[@]}")"
  logger -t security-watch "ALERT on $HOST: ${#new_msgs[@]} new finding(s)"
  if [ -x "$NOTIFY" ]; then
    "$NOTIFY" -t "security-watch: $HOST — ${#new_msgs[@]} new IOC(s)" "$body" || \
      logger -t security-watch "notify.sh failed; findings: $body"
  else
    logger -t security-watch "notify.sh missing; findings: $body"
  fi
  exit 0   # alerted via notify/journal; exit clean so systemd is not marked degraded
fi

logger -t security-watch "clean on $HOST"
exit 0
