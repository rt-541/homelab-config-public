#!/usr/bin/env bash
#
# reset-spncc-customisation.sh
#
# Resets the SPNCharCustom "hasCustomised" flag for player(s) in a PZ save,
# so the SPNCC mod re-opens the character customisation window on next login.
# Use this when adding TombBody/TombBodyTexNUDE to an existing save — players
# need to re-customise to pick up the new body textures.
#
# ═══════════════════════════════════════════════════════════════════════
# FULL SETUP GUIDE — Adding TombBody + SPNCC to an existing server
# ═══════════════════════════════════════════════════════════════════════
#
# STEP 1: Add mod IDs to server.ini Mods= line and docker-compose MOD_NAMES
#   Load order matters — add in this order (at the end of your mod list):
#
#   1. SpnCharCustom        (SPNCC framework — must be AFTER any mod that adds body locations)
#   2. SPNCC
#   3. SpnCharCustomDetails
#   4. SPNCCDetails
#   5. SpnCharCustomDetailsHD
#   6. SPNCCDetailsHD
#   7. SpnCharCustomFaces
#   8. SPNCCFaces
#   9. TombBody
#  10. TombBodyCustom
#  11. TombBodyTexNUDE       (pick ONE tex pack: TombBodyTex, TombBodyTexDOLL, or TombBodyTexNUDE)
#  12. TombBodyCompat        (from Compat workshop item — load LAST, after all clothing mods)
#
#   Also add Tomb's Wardrobe if desired:
#  13. TombWardrobeALT       (pick ONE: TombWardrobeALT or TombWardrobeALTVanilla, NOT both)
#
# STEP 2: Add workshop IDs to server.ini WorkshopItems= and docker-compose MOD_WORKSHOP_IDS
#   3414634809;3429790870;3431734923;3616536783;3672913009
#
# STEP 3: Test on a SINGLE PLAYER game first
#   a. Launch PZ, go to Mods, enable all the mods above in the correct order
#   b. Start a new single player game to verify the character creation screen
#      shows the new body options (nude textures, face customisation, etc.)
#   c. If it works, proceed to server deployment
#
# STEP 4: Deploy to server
#   a. Stop the server:
#        cd /docker/homelab-config/data-host/composed-apps/zomboid && sudo docker compose down
#   b. Run this script to reset existing players:
#        ./scripts/reset-spncc-customisation.sh prod
#   c. Start the server:
#        cd /docker/homelab-config/data-host/composed-apps/zomboid && sudo docker compose up -d
#   d. Players will get the customisation window on next login
#
# ═══════════════════════════════════════════════════════════════════════
#
# Usage:
#   ./reset-spncc-customisation.sh <prod|dev>
#
# IMPORTANT:
#   - Stop the server BEFORE running this script
#   - The server must be stopped or the database will be locked
#

set -euo pipefail

PROD_DB="/docker/game/zomboid/ZomboidConfig/Saves/Multiplayer/Flight_Group_Alpha_PZ_Server/players.db"
DEV_DB="/docker/game/zomboid-dev/ZomboidConfig/Saves/Multiplayer/Flight_Group_Alpha_PZ_Server/players.db"

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <prod|dev>"
    exit 1
fi

SERVER="$1"

case "$SERVER" in
    prod) DB_PATH="$PROD_DB" ;;
    dev)  DB_PATH="$DEV_DB" ;;
    *)    echo "Error: server must be 'prod' or 'dev'"; exit 1 ;;
esac

if [[ ! -f "$DB_PATH" ]]; then
    echo "Error: database not found at $DB_PATH"
    exit 1
fi

# Remove stale journal if present (left behind when server doesn't shut down cleanly)
JOURNAL="${DB_PATH}-journal"
if [[ -f "$JOURNAL" ]]; then
    echo "Removing stale journal file..."
    sudo rm -f "$JOURNAL"
fi

# List all players
echo ""
echo "Players in database:"
echo "--------------------"
sqlite3 "$DB_PATH" -column -header "SELECT id, username, name, isDead FROM networkPlayers;"

echo ""
echo "Select a player to reset (enter username), or type 'all' to reset everyone:"
read -p "> " SELECTION

if [[ -z "$SELECTION" ]]; then
    echo "No selection made. Aborted."
    exit 0
fi

if [[ "$SELECTION" == "all" ]]; then
    WHERE=""
    echo ""
    echo "Will reset ALL players."
else
    # Verify the player exists
    MATCH=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM networkPlayers WHERE username='$SELECTION';")
    if [[ "$MATCH" -eq 0 ]]; then
        echo "Error: no player found with username '$SELECTION'"
        exit 1
    fi
    WHERE="WHERE username='$SELECTION'"
    echo ""
    echo "Will reset: $SELECTION"
fi

read -p "Proceed? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

# Extract, patch, and update each player's blob
PLAYER_IDS=$(sqlite3 "$DB_PATH" "SELECT id FROM networkPlayers $WHERE;")

COUNT=0
for PID in $PLAYER_IDS; do
    PNAME=$(sqlite3 "$DB_PATH" "SELECT username FROM networkPlayers WHERE id=$PID;")
    TMPFILE=$(mktemp /tmp/pz_player_${PID}_XXXXX.bin)

    # Extract blob
    sqlite3 "$DB_PATH" "SELECT writefile('$TMPFILE', data) FROM networkPlayers WHERE id=$PID;" > /dev/null

    # Check if this player has SPNCharCustom data
    if ! grep -q "hasCustomised" "$TMPFILE" 2>/dev/null; then
        echo "  [$PNAME] No SPNCharCustom data found — skipping"
        rm -f "$TMPFILE"
        continue
    fi

    # Flip hasCustomised from true (0x01) to false (0x00)
    python3 -c "
data = bytearray(open('$TMPFILE', 'rb').read())
idx = data.find(b'hasCustomised')
if idx == -1:
    print('  [$PNAME] hasCustomised not found — skipping')
    exit(1)
# type byte is at idx+13 (0x03 = boolean), value byte is at idx+14
if data[idx+14] == 0x00:
    print('  [$PNAME] Already reset — skipping')
    exit(1)
data[idx+14] = 0x00
open('$TMPFILE', 'wb').write(data)
print('  [$PNAME] hasCustomised flipped to false')
" && {
        # Write patched blob back
        sqlite3 "$DB_PATH" "UPDATE networkPlayers SET data = readfile('$TMPFILE') WHERE id=$PID;"
        COUNT=$((COUNT + 1))
    }

    rm -f "$TMPFILE"
done

echo ""
echo "Done. Reset $COUNT player(s). Start the server and they'll get the customisation window on next login."
