#!/usr/bin/env bash
#
# backup-zomboid-prod.sh — Full backup of prod Zomboid server data
#
# Usage: ./scripts/backup-zomboid-prod.sh
#
# Creates a timestamped compressed tarball in the backups directory.
# Excludes the backups directory itself to avoid recursive inclusion.
# Server should be stopped before running this.

set -euo pipefail

SOURCE="/docker/game/zomboid"
BACKUP_DIR="${SOURCE}/backups"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/zomboid-prod-full-${TIMESTAMP}.tar.gz"

mkdir -p "$BACKUP_DIR"

echo "Backing up ${SOURCE} ..."
echo "Destination: ${BACKUP_FILE}"
echo ""

tar cf "$BACKUP_FILE" \
  --exclude='zomboid/backups' \
  -C /docker/game \
  zomboid/

SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo ""
echo "Done. Backup size: ${SIZE}"
echo "File: ${BACKUP_FILE}"
