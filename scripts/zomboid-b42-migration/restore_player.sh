#!/usr/bin/env bash
# restore_player.sh — send addxp + additem RCON commands for one player
#
# Usage:
#   ./restore_player.sh <username>
#   ./restore_player.sh Artie
#
# The player must be online when you run this.
# Run from: /docker/homelab-config/scripts/zomboid-b42-migration/

set -euo pipefail
export PATH="/usr/local/bin:$PATH"

RCON_HOST="127.0.0.1:27015"
RCON_PASS="CHANGEME"
RCON_DIR="$(dirname "$0")/rcon-output"

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <username>"
    echo "Available players:"
    ls "$RCON_DIR"/*.rcon | xargs -n1 basename | sed 's/\.rcon//'
    exit 1
fi

USERNAME="$1"
RCON_FILE="$RCON_DIR/${USERNAME}.rcon"

if [[ ! -f "$RCON_FILE" ]]; then
    echo "ERROR: No rcon file found for '$USERNAME' at $RCON_FILE"
    exit 1
fi

echo "=== Restoring $USERNAME (player must be online) ==="
echo ""

SKILL_COUNT=0
ITEM_COUNT=0
FAIL_COUNT=0

while IFS= read -r line; do
    # Skip comments and blanks
    [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue

    # Fix grantxp → addxp with correct syntax
    if [[ "$line" =~ ^/grantxp[[:space:]](.+)[[:space:]](.+)$ ]]; then
        player="${BASH_REMATCH[1]}"
        skill_xp="${BASH_REMATCH[2]}"
        cmd="addxp \"${player}\" ${skill_xp} -true"
        result=$(rcon -a "$RCON_HOST" -p "$RCON_PASS" "$cmd" 2>&1)
        if echo "$result" | grep -qi "error\|unknown\|invalid\|failed"; then
            echo "  WARN [skill] $cmd -> $result"
            ((FAIL_COUNT++)) || true
        else
            echo "  OK   [skill] $skill_xp"
            ((SKILL_COUNT++)) || true
        fi

    # Handle additem — add count=1 and quote the item ID
    elif [[ "$line" =~ ^/additem[[:space:]](.+)[[:space:]](([A-Za-z0-9_]+)\.([A-Za-z0-9_]+))$ ]]; then
        player="${BASH_REMATCH[1]}"
        item="${BASH_REMATCH[2]}"
        cmd="additem \"${player}\" \"${item}\" 1"
        result=$(rcon -a "$RCON_HOST" -p "$RCON_PASS" "$cmd" 2>&1)
        if echo "$result" | grep -qi "error\|unknown\|invalid\|failed\|not found"; then
            echo "  WARN [item ] $item -> $result"
            ((FAIL_COUNT++)) || true
        else
            echo "  OK   [item ] $item"
            ((ITEM_COUNT++)) || true
        fi
    fi

done < "$RCON_FILE"

echo ""
echo "=== Done: $SKILL_COUNT skills, $ITEM_COUNT items restored, $FAIL_COUNT warnings ==="
