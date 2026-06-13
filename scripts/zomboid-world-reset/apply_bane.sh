#!/usr/bin/env bash
# apply_bane.sh — apply the rolled bane trait(s) for one player via RCON.
#
# Usage:
#   ./apply_bane.sh <RCON_username>
#   ./apply_bane.sh Vinny
#
# Reads bane.trait (string) or bane.traits (array) from boons-resolved.json.
# If bane.rp_only is true, prints the flavor and exits without RCON calls.

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
    echo "ERROR: no data for '$USER' in $DATA"
    exit 1
fi

FLAVOR=$(jq -r ".\"$USER\".bane.flavor" "$DATA")
RP_ONLY=$(jq -r ".\"$USER\".bane.rp_only" "$DATA")

echo "=== Bane for $USER: $FLAVOR ==="

if [[ "$RP_ONLY" == "true" ]]; then
    echo "  RP-only bane — no RCON action. Player honor-applies."
    exit 0
fi

# Collect traits: either single .bane.trait (string) or .bane.traits (array)
TRAITS=$(jq -r '
    if .["'"$USER"'"].bane.traits then
        .["'"$USER"'"].bane.traits[]
    elif .["'"$USER"'"].bane.trait then
        .["'"$USER"'"].bane.trait
    else
        empty
    end
' "$DATA")

if [[ -z "$TRAITS" ]]; then
    echo "  No trait specified. Skipping."
    exit 0
fi

while IFS= read -r trait; do
    [[ -z "$trait" ]] && continue
    cmd="addtrait \"$USER\" $trait"
    result=$(rcon -a "$RCON_HOST" -p "$RCON_PASS" "$cmd" 2>&1 || true)
    if echo "$result" | grep -qiE "error|unknown|invalid|failed|connection refused|dial tcp"; then
        echo "  WARN  addtrait $trait -> $result"
    else
        echo "  OK    addtrait $trait"
    fi
done <<< "$TRAITS"

echo "=== Done. Remove later with remove_bane.sh ==="
