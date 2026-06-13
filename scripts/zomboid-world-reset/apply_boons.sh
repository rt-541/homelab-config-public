#!/usr/bin/env bash
# apply_boons.sh — apply rolled boons (items + XP) to one player via RCON.
# The player must be online when this runs.
#
# Usage:
#   ./apply_boons.sh <RCON_username>
#   ./apply_boons.sh Bulbs
#
# Reads boons-resolved.json. Skips trait application — that is apply_bane.sh's job.

set -euo pipefail
export PATH="/usr/local/bin:$PATH"

command -v rcon >/dev/null 2>&1 || { echo "ERROR: rcon binary not in PATH" >&2; exit 1; }
command -v jq   >/dev/null 2>&1 || { echo "ERROR: jq binary not in PATH" >&2; exit 1; }

RCON_HOST="${RCON_HOST:-127.0.0.1:27015}"
RCON_PASS="${RCON_PASS:-CHANGEME}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA="$SCRIPT_DIR/boons-resolved.json"

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <RCON_username>"
    echo "Available: $(jq -r 'keys | join(", ")' "$DATA")"
    exit 1
fi

USER="$1"

if ! jq -e ".\"$USER\"" "$DATA" >/dev/null; then
    echo "ERROR: no boon data for '$USER' in $DATA"
    exit 1
fi

echo "=== Applying boons for $USER (must be online) ==="

# Items
jq -r ".\"$USER\".items[] | \"\(.id)\t\(.count)\t\(.comment)\"" "$DATA" \
| while IFS=$'\t' read -r id count comment; do
    cmd="additem \"$USER\" \"$id\" $count"
    result=$(rcon -a "$RCON_HOST" -p "$RCON_PASS" "$cmd" 2>&1 || true)
    if echo "$result" | grep -qiE "error|unknown|invalid|failed|not found|connection refused|dial tcp"; then
        echo "  WARN  [item] $id x$count -> $result"
    else
        echo "  OK    [item] $id x$count  ($comment)"
    fi
done

# XP
jq -r ".\"$USER\".xp[] | \"\(.skill)\t\(.amount)\t\(.comment)\"" "$DATA" \
| while IFS=$'\t' read -r skill amount comment; do
    cmd="addxp \"$USER\" $skill=$amount"
    result=$(rcon -a "$RCON_HOST" -p "$RCON_PASS" "$cmd" 2>&1 || true)
    if echo "$result" | grep -qiE "error|unknown|invalid|failed|connection refused|dial tcp"; then
        echo "  WARN  [xp]   $skill +$amount -> $result"
    else
        echo "  OK    [xp]   $skill +$amount  ($comment)"
    fi
done

echo "=== Done. Apply bane separately with apply_bane.sh ==="
