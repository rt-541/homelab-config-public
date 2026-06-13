#!/usr/bin/env bash
# restore_items_only.sh — like restore_player.sh but skips addxp (skills come from blob).
#
# Usage:
#   ./restore_items_only.sh <username>
#
# Reads .rcon files from /docker/homelab-config/scripts/zomboid-b42-migration/rcon-output/
# The player must be online when this runs.

set -euo pipefail
export PATH="/usr/local/bin:$PATH"

command -v rcon >/dev/null 2>&1 || { echo "ERROR: rcon binary not in PATH" >&2; exit 1; }

RCON_HOST="${RCON_HOST:-127.0.0.1:27015}"
RCON_PASS="${RCON_PASS:-CHANGEME}"
RCON_DIR="/docker/homelab-config/scripts/zomboid-b42-migration/rcon-output"

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <username>"
    echo "Available: $(ls "$RCON_DIR"/*.rcon 2>/dev/null | xargs -n1 basename | sed 's/\.rcon//')"
    exit 1
fi

USER="$1"
FILE="$RCON_DIR/${USER}.rcon"

if [[ ! -f "$FILE" ]]; then
    echo "ERROR: no .rcon file at $FILE"
    exit 1
fi

echo "=== Restoring items only for $USER (must be online) ==="
ITEM_COUNT=0
FAIL_COUNT=0

while IFS= read -r line; do
    [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
    # only additem lines; skip /grantxp (and any other) commands
    if [[ "$line" =~ ^/additem[[:space:]](.+)[[:space:]](([A-Za-z0-9_]+)\.([A-Za-z0-9_]+))$ ]]; then
        player="${BASH_REMATCH[1]}"
        item="${BASH_REMATCH[2]}"
        cmd="additem \"$player\" \"$item\" 1"
        result=$(rcon -a "$RCON_HOST" -p "$RCON_PASS" "$cmd" 2>&1 || true)
        if echo "$result" | grep -qiE "error|unknown|invalid|failed|not found|connection refused|dial tcp"; then
            echo "  WARN [item] $item -> $result"
            ((FAIL_COUNT++)) || true
        else
            echo "  OK   [item] $item"
            ((ITEM_COUNT++)) || true
        fi
    fi
done < "$FILE"

echo "=== Done: $ITEM_COUNT items restored, $FAIL_COUNT warnings ==="
