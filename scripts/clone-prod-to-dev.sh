#!/usr/bin/env bash
# clone-prod-to-dev.sh
# Clones the latest production backup to the dev server.
# Intended to run at 5 AM daily (after the 4 AM production backup).
# Cron: 0 5 * * * /docker/homelab-config/scripts/clone-prod-to-dev.sh
set -e

BACKUP_DIR="/docker/game/zomboid/backups"
DEV_DATA_DIR="/docker/game/zomboid-dev"
DEV_COMPOSE_DIR="/docker/homelab-config/data-host/composed-apps/zomboid/zomboid-dev"
LOG="$DEV_DATA_DIR/clone.log"

mkdir -p "$DEV_DATA_DIR"

LATEST=$(ls -t "$BACKUP_DIR"/zomboid-*.tar.gz 2>/dev/null | head -1)
if [ -z "$LATEST" ]; then
  echo "[$(date)] ERROR: No backup found in $BACKUP_DIR" >> "$LOG"
  exit 1
fi

echo "[$(date)] Cloning $LATEST to dev server..." >> "$LOG"

# Stop dev server
cd "$DEV_COMPOSE_DIR"
docker compose down >> "$LOG" 2>&1

# Wipe and restore ZomboidConfig from backup
# Backup tarball has ZomboidConfig/ at its root
rm -rf "$DEV_DATA_DIR/ZomboidConfig"
tar -xzf "$LATEST" -C "$DEV_DATA_DIR" >> "$LOG" 2>&1

# Start dev server
# The bind-mounted ./server.ini preserves dev-specific settings (ports, name, etc.)
docker compose up -d >> "$LOG" 2>&1

echo "[$(date)] Done. Dev server now mirrors: $(basename "$LATEST")" >> "$LOG"
