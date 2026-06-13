#!/usr/bin/env bash
# verify_rcon_capabilities.sh — probe RCON capabilities on the prod server.
#
# Usage: ./verify_rcon_capabilities.sh [<test_username>]
#
# Prints PASS/FAIL for each capability the world reset depends on. Safe to
# run when no players are connected — the default test username does not
# exist, so any state-changing command should no-op or return "user not found".

set -uo pipefail
export PATH="/usr/local/bin:$PATH"

command -v rcon >/dev/null 2>&1 || { echo "ERROR: rcon binary not in PATH" >&2; exit 1; }

RCON_HOST="${RCON_HOST:-127.0.0.1:27015}"
RCON_PASS="${RCON_PASS:-CHANGEME}"
PROBE_USER="${1:-WorldResetProbe}"

probe() {
    local label="$1"
    local cmd="$2"
    local result
    result=$(rcon -a "$RCON_HOST" -p "$RCON_PASS" "$cmd" 2>&1 || true)
    if [[ -z "$result" ]]; then
        echo "FAIL  $label  -> (empty response)"
    elif echo "$result" | grep -qiE "unknown command|invalid command"; then
        echo "FAIL  $label  -> $result"
    else
        echo "PASS  $label  -> $result"
    fi
}

echo "=== RCON capability probe against $RCON_HOST as user '$PROBE_USER' ==="
probe "addtrait"    "addtrait $PROBE_USER Asthmatic"
probe "removetrait" "removetrait $PROBE_USER Asthmatic"
probe "teleport"    "teleport $PROBE_USER 10776,10947,0"
probe "removeitem"  "removeitem $PROBE_USER Base.Shoes_Random"
probe "addxp neg"   "addxp $PROBE_USER Fitness=-100"
echo "=== done ==="
