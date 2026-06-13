# Zomboid World Reset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute a full save wipe + new-seed reset of the prod Zomboid server while preserving five player characters' looks/skills/traits via blob transplant, and apply per-character rolled boons + temporary bane traits via RCON.

**Architecture:** Phase 0 verifies RCON capabilities + resolves item IDs on dev. Phase 1 builds Python (`clear_inventory.py`) and shell wrappers (`apply_boons.sh`, `apply_bane.sh`, `remove_bane.sh`, `restore_items_only.sh`) driven by a single `boons-resolved.json` data file. Phase 2 smoke-tests on dev. Phase 3 is the production runbook executed during a planned downtime window.

**Tech Stack:** Python 3 (stdlib only — `sqlite3`, `re`, `argparse`), Bash, `rcon` CLI binary (already used by `restore_player.sh`), Docker Compose for server lifecycle, sqlite3 for `players.db` inspection.

**Spec:** `docs/superpowers/specs/2026-05-08-zomboid-world-reset-design.md`

---

## Phase 0 — Verification & ID Mapping

These tasks change strategy if RCON capabilities differ from assumptions. Run them first.

### Task 0.1: Build RCON capability probe script (target: prod)

**Files:**
- Create: `scripts/zomboid-world-reset/verify_rcon_capabilities.sh`

**Note:** Per the operator's direction, the dev server is NOT used for verification. The probe script targets the prod RCON endpoint (`127.0.0.1:27015`, password `CHANGEME`). It will be RUN later — during the prod reset window itself, after the first fresh boot but before any player joins. Probing prod is safe at that moment because (a) no players are on, (b) the test target is a non-existent username so any `addtrait`/`removeitem` either no-ops or returns "user not found" without touching real characters.

- [ ] **Step 1: Write the verification script**

Create `scripts/zomboid-world-reset/verify_rcon_capabilities.sh`:

```bash
#!/usr/bin/env bash
# verify_rcon_capabilities.sh — probe RCON capabilities on the prod server.
#
# Usage: ./verify_rcon_capabilities.sh [<test_username>]
#
# Prints PASS/FAIL for each capability the world reset depends on. Safe to
# run when no players are connected — the default test username does not
# exist, so any state-changing command should no-op or return "user not found".

set -uo pipefail

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
```

- [ ] **Step 2: Make executable**

Run: `chmod +x /docker/nemesis-configs/scripts/zomboid-world-reset/verify_rcon_capabilities.sh`

- [ ] **Step 3: Commit**

```bash
cd /docker/nemesis-configs
git add scripts/zomboid-world-reset/verify_rcon_capabilities.sh
git commit -m "feat(zomboid-reset): add RCON capability probe script (prod target)"
```

The script will be executed during the prod reset window (RUNBOOK §6.5) and the report captured then.

---

### Task 0.2: Resolve item IDs for all rolled boons

**Files:**
- Create: `scripts/zomboid-world-reset/item-id-mapping.md`

- [ ] **Step 1: Enumerate the items to map**

The five characters need these distinct items:

**Melee:** Hunting Knife (Bulbs), Machete (Emma, Curtis — same), Long-Handle Shovel (Vinny), Pickaxe (RT-541)

**Clothing:** Welder's overalls patched (Bulbs), USPS postal parka (Emma), UK Wildcats hoodie bloodstained (Vinny), Sweat-stained cowboy hat (RT-541), Clergy collar shirt (Curtis)

**Guns:** M14 + .308 mag + 20× .308 (Bulbs, RT-541 — same), M1911 + .45 mag + 7× .45 (Emma), Sawed-Off DB shotgun + 4× shotgun shells (Vinny), Hunting Rifle + scope + 2× .308 (Curtis)

- [ ] **Step 2: Find item definition files inside the prod container**

For each item, the canonical source of truth is the actual game files inside the running prod container. Vanilla item definitions live in `media/scripts/items_*.txt`; mod-added items live under each mod's directory under `Steam/steamapps/workshop/content/108600/<modid>/mods/<modname>/media/scripts/`.

Find the prod container's game files:

```bash
sudo docker exec zomboid-dedicated-server bash -c \
  "find / -path '*/media/scripts/items_*.txt' 2>/dev/null | head -20"
```

Then grep for each item by name. Examples:

```bash
# Vanilla weapons
sudo docker exec zomboid-dedicated-server bash -c \
  "grep -rE '^[[:space:]]*item (HuntingKnife|Machete|Pickaxe|Shovel|M14|M1911|HuntingRifle|DoubleBarrelShotgunSawnoff)' /<path>/media/scripts/items_weapons.txt 2>/dev/null"

# Vanilla clothing (likely items_clothing.txt)
sudo docker exec zomboid-dedicated-server bash -c \
  "grep -rE '^[[:space:]]*item.*(Cowboy|Welder|Postal|Hoodie|Priest|Clergy)' /<path>/media/scripts/items_clothing.txt 2>/dev/null"

# Ammo and magazines
sudo docker exec zomboid-dedicated-server bash -c \
  "grep -rE '^[[:space:]]*item.*(308|45Auto|45ACP|ShotgunShells)' /<path>/media/scripts/ 2>/dev/null"
```

For each item: capture the module + ID (the `item ID` line tells you the local ID; the surrounding `module XYZ { ... }` block tells you the namespace, so the full ID is `XYZ.ID`).

- [ ] **Step 3: Build the mapping doc**

Create `scripts/zomboid-world-reset/item-id-mapping.md`:

```markdown
# Item ID Mapping for World Reset Boons

Resolved 2026-05-08 against B42 prod container `zomboid-dedicated-server`.

## Melee (Table 1 — rolled rows only)
| Row | Description | Item ID | Source file |
|---|---|---|---|
| 5 | Machete | Base.Machete | media/scripts/items_weapons.txt |
| 10 | Hunting Knife | Base.HuntingKnife | items_weapons.txt |
| 13 | Long-Handle Shovel | Base.<resolved> | items_weapons.txt |
| 14 | Pickaxe | Base.<resolved> | items_weapons.txt |

## Clothing (Table 2 — rolled rows only)
| Row | Description | Item ID | Source file | Notes |
|---|---|---|---|---|
| 5 | UK Wildcats hoodie | Base.<resolved> | items_clothing.txt | substitution if no Wildcats variant |
| 7 | Clergy collar shirt | Base.<resolved> | items_clothing.txt | |
| 9 | Welder's overalls | Base.<resolved> | items_clothing.txt | |
| 16 | USPS postal parka | Base.<resolved> | items_clothing.txt | substitution likely |
| 17 | Sweat-stained cowboy hat | Base.<resolved> | items_clothing.txt | |

## Guns + Ammo (Table 3 — rolled rows only)
| Roll | Description | Gun ID | Magazine ID | Ammo ID | Ammo Count | Attachment |
|---|---|---|---|---|---|---|
| 2 | M1911 + 1 mag (.45×7) | Base.<resolved> | Base.<resolved> | Base.<resolved> | 7 | — |
| 8 | M14 + 1 mag (.308×20) | Base.<resolved> | Base.<resolved> | Base.<resolved> | 20 | — |
| 12 | Sawed-Off DB + 4 shells | Base.<resolved> | — | Base.<resolved> | 4 | — |
| 16 | Hunting Rifle + scope + 2 rounds | Base.<resolved> | — | Base.<resolved> | 2 | Base.<resolved scope> |

## Substitutions
For exotic items without direct vanilla IDs, the closest analogue picked:
| Description | Substituted with | Reason |
|---|---|---|
| ... | ... | ... |
```

Only the rolled rows need IDs (4 melee, 5 clothing, 4 gun configs + 1 scope). Skip unrolled rows. Replace every `<resolved>` placeholder with the actual ID found in Step 2.

- [ ] **Step 4: Commit the mapping**

```bash
cd /docker/nemesis-configs
git add scripts/zomboid-world-reset/item-id-mapping.md
git commit -m "docs(zomboid-reset): resolve item IDs for rolled boons (prod source)"
```

---

## Phase 1 — Build Supporting Scripts

### Task 1.1: Build `clear_inventory.py` (strip inventory from blob)

**Files:**
- Create: `scripts/zomboid-world-reset/clear_inventory.py`
- Create: `scripts/zomboid-world-reset/test_clear_inventory.py`

**Background:** Player blobs in `players.db` are binary (the `data` column on the `players` table is a BLOB). The blob format includes serialized inventory items as length-prefixed string records embedded in the binary data. Items always follow a predictable character identity section (`name`, `gender`, `profession`, `VoiceFemale`, `OverEye` fields). We strip the inventory section so the RCON `additem` flow is the only source of truth for the player's starting inventory.

**Position handling is out of scope for this script.** The original plan included `strip_position` but blob position editing is fragile. We will use post-login RCON `teleport` instead (RUNBOOK §11). This task implements ONLY inventory stripping.

The b42-migration design (`docs/superpowers/specs/2026-04-02-zomboid-b42-migration-design.md`) "Step 2: clear_inventory.py" section describes the heuristic: scan the blob for the first occurrence of a module-prefixed item ID string (e.g. `Base.Necklace_Gold`) after the character identity section, then truncate from there.

- [ ] **Step 1: Write the failing test**

Create `scripts/zomboid-world-reset/test_clear_inventory.py`:

```python
import unittest
from clear_inventory import strip_inventory


class TestStripInventory(unittest.TestCase):
    def test_truncates_at_first_module_item_id(self):
        # Identity section ends; inventory begins with a Base.Item record.
        blob = b'IDENTITY_BLOCK_HEADER' + b'\x00\x10Base.HuntingKnife' + b'TRAILING_INVENTORY_BYTES'
        result = strip_inventory(blob)
        self.assertNotIn(b'Base.HuntingKnife', result)
        self.assertNotIn(b'TRAILING_INVENTORY_BYTES', result)
        self.assertIn(b'IDENTITY_BLOCK_HEADER', result)

    def test_returns_blob_unchanged_when_no_item_id_found(self):
        blob = b'just an identity blob with no items'
        self.assertEqual(strip_inventory(blob), blob)

    def test_truncation_skips_module_id_strings_inside_identity_section(self):
        # If the identity section contains a Base. substring (rare but possible), the
        # implementation must scan for module IDs only after the identity section ends.
        # Use whatever identity-end sentinel the b42 design specifies; placeholder here.
        # If the implementer can't find a reliable sentinel, document the heuristic
        # they chose (e.g., minimum byte offset before scanning starts).
        pass  # Mark as expected-to-evolve once heuristic is concrete.


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /docker/nemesis-configs/scripts/zomboid-world-reset && python3 -m unittest test_clear_inventory.py -v`
Expected: ImportError (`clear_inventory` module not defined).

- [ ] **Step 3: Inspect a real blob to identify the heuristic**

Run `hexdump -C /docker/game/zomboid/manual-backups/player-exports/Curtis.bin | head -200` and study the layout. Look for:
- The character identity section (name string, profession string, etc.)
- The first module-prefixed item ID (`Base.X` or similar) — this is where inventory begins
- Any consistent sentinel bytes between identity and inventory

Document your findings as a comment in `clear_inventory.py` so the next reader (or future-you) understands the heuristic.

If the identity section contains substrings that look like module IDs (false positives), pick a minimum-byte-offset before which the scan won't start (e.g., "scan only after byte 1024"), and document why that offset is safe.

- [ ] **Step 4: Implement `clear_inventory.py`**

Create `scripts/zomboid-world-reset/clear_inventory.py`:

```python
#!/usr/bin/env python3
"""
clear_inventory.py — strip the inventory section from PZ player blobs.

Usage:
    sudo python3 clear_inventory.py --save-dir <path-to-server-save-dir> [--dry-run] [--players USER ...]

Reads players.db, strips the inventory section from each player's data blob,
and writes back. Snapshots the original blobs to ./blob-backups/ before mutating.

Heuristic (from the b42 migration design): the inventory section begins at the
first occurrence of a module-prefixed item ID string (e.g. b'Base.<name>') after
the character identity section. We truncate the blob at that point, leaving the
identity section intact and dropping all inventory bytes that follow.

Position metadata is NOT touched. Forced spawn-point and post-login `teleport`
RCON commands handle that concern.
"""

import argparse
import re
import sqlite3
import sys
from pathlib import Path

# Minimum byte offset before scanning for an item ID. The character identity
# section is assumed to fit within this prefix. Tune in Step 3 if a real blob
# contains identity strings beyond this offset.
MIN_SCAN_OFFSET = 256

# Module ID pattern: bytes spelling "<Module>.<ItemName>" where Module is one or
# more capitalized words. Matches Base.HuntingKnife, Base.Necklace_Gold, etc.
ITEM_ID_PATTERN = re.compile(rb'[A-Z][A-Za-z0-9_]+\.[A-Za-z][A-Za-z0-9_]+')


def strip_inventory(blob: bytes) -> bytes:
    """Truncate blob at the first module-prefixed item ID after MIN_SCAN_OFFSET.

    Returns the original blob if no item ID is found (nothing to strip)."""
    if len(blob) <= MIN_SCAN_OFFSET:
        return blob
    match = ITEM_ID_PATTERN.search(blob, pos=MIN_SCAN_OFFSET)
    if match is None:
        return blob
    return blob[:match.start()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--save-dir', required=True, help='path to save dir containing players.db')
    parser.add_argument('--dry-run', action='store_true', help='report changes without writing')
    parser.add_argument('--players', nargs='*', help='only process these usernames (default: all)')
    args = parser.parse_args()

    db_path = Path(args.save_dir) / 'players.db'
    if not db_path.exists():
        print(f"ERROR: players.db not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    backup_dir = Path(__file__).parent / 'blob-backups'
    backup_dir.mkdir(exist_ok=True)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    rows = cur.execute("SELECT username, data FROM players").fetchall()

    for username, blob in rows:
        if args.players and username not in args.players:
            continue
        original_size = len(blob)
        backup_path = backup_dir / f"{username}_prestrip.blob"
        if not args.dry_run:
            backup_path.write_bytes(blob)
        new_blob = strip_inventory(blob)
        new_size = len(new_blob)
        action = "DRY-RUN" if args.dry_run else "STRIPPED"
        print(f"  {action} {username}: {original_size} -> {new_size} bytes (snapshot: {backup_path.name})")
        if not args.dry_run:
            cur.execute("UPDATE players SET data=? WHERE username=?", (new_blob, username))

    if not args.dry_run:
        conn.commit()
    conn.close()
    print("done")


if __name__ == '__main__':
    main()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /docker/nemesis-configs/scripts/zomboid-world-reset && python3 -m unittest test_clear_inventory.py -v`
Expected: tests PASS.

- [ ] **Step 6: Tune `MIN_SCAN_OFFSET` against a real blob**

After implementation, smoke-test with a real backup blob (Step 7) and confirm the truncation point falls AFTER the character identity section (you should see name, profession, etc. preserved in the stripped output via `hexdump -C` of the truncated blob). If MIN_SCAN_OFFSET=256 truncates too early (cuts identity), bump it. If too late (leaves item bytes), drop it.

- [ ] **Step 7: Smoke-test against a copy of one real blob**

Copy a backup blob into a throwaway sqlite db, run `clear_inventory.py --dry-run`, then non-dry-run, verify size decreased and that re-running on the stripped blob is idempotent (size unchanged).

```bash
cd /docker/nemesis-configs/scripts/zomboid-world-reset
mkdir -p /tmp/test-clear-inventory
cp /docker/game/zomboid/manual-backups/player-exports/Curtis.bin /tmp/test-clear-inventory/
# build a one-row players.db for testing
python3 -c "
import sqlite3
conn = sqlite3.connect('/tmp/test-clear-inventory/players.db')
conn.execute('CREATE TABLE players (username TEXT, data BLOB)')
with open('/tmp/test-clear-inventory/Curtis.bin','rb') as f:
    conn.execute('INSERT INTO players VALUES (?,?)', ('Curtis', f.read()))
conn.commit()
"
sudo python3 clear_inventory.py --save-dir /tmp/test-clear-inventory --dry-run
sudo python3 clear_inventory.py --save-dir /tmp/test-clear-inventory
sudo python3 clear_inventory.py --save-dir /tmp/test-clear-inventory  # re-run for idempotency check
```

Expected: first non-dry-run reports size decrease; second non-dry-run reports unchanged size.

- [ ] **Step 8: Commit**

```bash
cd /docker/nemesis-configs
git add scripts/zomboid-world-reset/clear_inventory.py \
        scripts/zomboid-world-reset/test_clear_inventory.py
git commit -m "feat(zomboid-reset): add clear_inventory.py for blob inventory + position stripping"
```

---

### Task 1.2: Build `boons-resolved.json` (single source of truth for per-character boons)

**Files:**
- Create: `scripts/zomboid-world-reset/boons-resolved.json`

- [ ] **Step 1: Write the JSON with all five resolved characters**

Create `scripts/zomboid-world-reset/boons-resolved.json` (item IDs from `item-id-mapping.md` produced in Task 0.2):

```json
{
  "Bulbs": {
    "display_name": "Step-fist (Stephen)",
    "rolls": [10, 9, 8, 19, 15],
    "items": [
      {"id": "<MELEE_HUNTING_KNIFE_ID>", "count": 1, "comment": "Table 1 #10 melee"},
      {"id": "<CLOTHING_WELDER_OVERALLS_ID>", "count": 1, "comment": "Table 2 #9 clothing"},
      {"id": "<GUN_M14_ID>", "count": 1, "comment": "Table 3 #8 gun"},
      {"id": "<M14_MAG_ID>", "count": 1, "comment": "Table 3 #8 mag"},
      {"id": "<308_AMMO_ID>", "count": 20, "comment": "Table 3 #8 ammo"}
    ],
    "xp": [
      {"skill": "Husbandry", "amount": 2000, "comment": "Table 4 #19"}
    ],
    "bane": {
      "flavor": "Memory gap — last 3 days before the fire are blank",
      "trait": "SlowReader",
      "rp_only": false
    }
  },
  "Emma_M7": {
    "display_name": "Emma",
    "rolls": [5, 16, 2, 19, 15],
    "items": [
      {"id": "<MELEE_MACHETE_ID>", "count": 1, "comment": "Table 1 #5 melee"},
      {"id": "<CLOTHING_USPS_PARKA_ID>", "count": 1, "comment": "Table 2 #16 clothing"},
      {"id": "<GUN_M1911_ID>", "count": 1, "comment": "Table 3 #2 gun"},
      {"id": "<M1911_MAG_ID>", "count": 1, "comment": "Table 3 #2 mag"},
      {"id": "<45_AMMO_ID>", "count": 7, "comment": "Table 3 #2 ammo"}
    ],
    "xp": [
      {"skill": "Husbandry", "amount": 2000, "comment": "Table 4 #19"}
    ],
    "bane": {
      "flavor": "Memory gap — last 3 days before the fire are blank",
      "trait": "SlowReader",
      "rp_only": false
    }
  },
  "Vinny": {
    "display_name": "Vinny",
    "rolls": [13, 5, 12, 6, 10],
    "items": [
      {"id": "<MELEE_LONG_SHOVEL_ID>", "count": 1, "comment": "Table 1 #13 melee"},
      {"id": "<CLOTHING_WILDCATS_HOODIE_ID>", "count": 1, "comment": "Table 2 #5 clothing"},
      {"id": "<GUN_SAWED_OFF_DB_ID>", "count": 1, "comment": "Table 3 #12 gun"},
      {"id": "<SHOTGUN_SHELL_ID>", "count": 4, "comment": "Table 3 #12 ammo"}
    ],
    "xp": [
      {"skill": "Reloading", "amount": 2500, "comment": "Table 4 #6"}
    ],
    "bane": {
      "flavor": "Lost hearing in one ear",
      "trait": "HardOfHearing",
      "rp_only": false
    }
  },
  "Artie": {
    "display_name": "RT-541",
    "rolls": [14, 17, 8, 17, 12],
    "items": [
      {"id": "<MELEE_PICKAXE_ID>", "count": 1, "comment": "Table 1 #14 melee"},
      {"id": "<CLOTHING_COWBOY_HAT_ID>", "count": 1, "comment": "Table 2 #17 clothing"},
      {"id": "<GUN_M14_ID>", "count": 1, "comment": "Table 3 #8 gun"},
      {"id": "<M14_MAG_ID>", "count": 1, "comment": "Table 3 #8 mag"},
      {"id": "<308_AMMO_ID>", "count": 20, "comment": "Table 3 #8 ammo"}
    ],
    "xp": [
      {"skill": "Spear", "amount": 2500, "comment": "Table 4 #17"}
    ],
    "bane": {
      "flavor": "Coughing blood for a week",
      "traits": ["SlowHealer", "ProneToIllness"],
      "rp_only": false
    }
  },
  "Curtis": {
    "display_name": "Curtis",
    "rolls": [5, 7, 16, 20, 11],
    "items": [
      {"id": "<MELEE_MACHETE_ID>", "count": 1, "comment": "Table 1 #5 melee"},
      {"id": "<CLOTHING_CLERGY_SHIRT_ID>", "count": 1, "comment": "Table 2 #7 clothing"},
      {"id": "<GUN_HUNTING_RIFLE_ID>", "count": 1, "comment": "Table 3 #16 gun"},
      {"id": "<RIFLE_SCOPE_ID>", "count": 1, "comment": "Table 3 #16 scope attachment"},
      {"id": "<308_AMMO_ID>", "count": 2, "comment": "Table 3 #16 ammo"}
    ],
    "xp": [
      {"skill": "Electrical", "amount": 2000, "comment": "Table 4 #20"},
      {"skill": "MetalWelding", "amount": 1000, "comment": "Table 4 #20 (verify B42 skill ID)"}
    ],
    "bane": {
      "flavor": "All hair burned off",
      "trait": null,
      "rp_only": true
    }
  }
}
```

- [ ] **Step 2: Replace placeholder IDs with resolved values**

Walk through `item-id-mapping.md` (from Task 0.2) and substitute each `<...>` placeholder with the actual `Base.X` ID. Verify every placeholder gets a real value — if any don't, flag them and pick the closest substitute.

For trait names (`SlowReader`, `HardOfHearing`, etc.), confirm the canonical PZ trait IDs by inspecting:
```bash
sudo docker exec zomboid-dev-server bash -c "grep -ri 'SlowReader\|HardOfHearing\|SlowHealer\|ProneToIllness' /opt/zomboid/media/lua/shared/NPCs/ 2>/dev/null | head -10"
```

For skill names (`Husbandry`, `Reloading`, `Spear`, `Electrical`, `MetalWelding`), confirm against:
```bash
sudo docker exec zomboid-dev-server bash -c "find /opt/zomboid -name 'Perks.lua' 2>/dev/null | xargs grep -E 'Husbandry|Reloading|Spear' 2>/dev/null | head -20"
```

- [ ] **Step 3: Validate JSON syntax**

Run: `python3 -c "import json; json.load(open('/docker/nemesis-configs/scripts/zomboid-world-reset/boons-resolved.json'))"`
Expected: no output (valid JSON).

- [ ] **Step 4: Commit**

```bash
cd /docker/nemesis-configs
git add scripts/zomboid-world-reset/boons-resolved.json
git commit -m "feat(zomboid-reset): add resolved per-character boon data file"
```

---

### Task 1.3: Build `apply_boons.sh` (drive RCON boon application from JSON)

**Files:**
- Create: `scripts/zomboid-world-reset/apply_boons.sh`

- [ ] **Step 1: Write the script**

Create `scripts/zomboid-world-reset/apply_boons.sh`:

```bash
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
    result=$(rcon -a "$RCON_HOST" -p "$RCON_PASS" "$cmd" 2>&1)
    if echo "$result" | grep -qiE "error|unknown|invalid|failed|not found"; then
        echo "  WARN  [item] $id x$count -> $result"
    else
        echo "  OK    [item] $id x$count  ($comment)"
    fi
done

# XP
jq -r ".\"$USER\".xp[] | \"\(.skill)\t\(.amount)\t\(.comment)\"" "$DATA" \
| while IFS=$'\t' read -r skill amount comment; do
    cmd="addxp \"$USER\" $skill=$amount"
    result=$(rcon -a "$RCON_HOST" -p "$RCON_PASS" "$cmd" 2>&1)
    if echo "$result" | grep -qiE "error|unknown|invalid|failed"; then
        echo "  WARN  [xp]   $skill +$amount -> $result"
    else
        echo "  OK    [xp]   $skill +$amount  ($comment)"
    fi
done

echo "=== Done. Apply bane separately with apply_bane.sh ==="
```

- [ ] **Step 2: Make executable**

Run: `chmod +x /docker/nemesis-configs/scripts/zomboid-world-reset/apply_boons.sh`

- [ ] **Step 3: Confirm `jq` is available**

Run: `which jq`
Expected: shows path to jq binary. If missing, install via `sudo dnf install -y jq` (or note as a host prereq).

- [ ] **Step 4: Commit**

```bash
cd /docker/nemesis-configs
git add scripts/zomboid-world-reset/apply_boons.sh
git commit -m "feat(zomboid-reset): add apply_boons.sh driven by boons-resolved.json"
```

---

### Task 1.4: Build `apply_bane.sh` and `remove_bane.sh`

**Files:**
- Create: `scripts/zomboid-world-reset/apply_bane.sh`
- Create: `scripts/zomboid-world-reset/remove_bane.sh`

- [ ] **Step 1: Write `apply_bane.sh`**

Create `scripts/zomboid-world-reset/apply_bane.sh`:

```bash
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

RCON_HOST="${RCON_HOST:-127.0.0.1:27015}"
RCON_PASS="${RCON_PASS:-CHANGEME}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA="$SCRIPT_DIR/boons-resolved.json"

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <RCON_username>"
    exit 1
fi

USER="$1"

if ! jq -e ".\"$USER\"" "$DATA" >/dev/null; then
    echo "ERROR: no data for '$USER'"
    exit 1
fi

FLAVOR=$(jq -r ".\"$USER\".bane.flavor" "$DATA")
RP_ONLY=$(jq -r ".\"$USER\".bane.rp_only" "$DATA")

echo "=== Bane for $USER: $FLAVOR ==="

if [[ "$RP_ONLY" == "true" ]]; then
    echo "  RP-only bane — no RCON action. Player honor-applies."
    exit 0
fi

# Collect traits: either single .trait or array .traits
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
    cmd="addtrait \"$USER\" $trait"
    result=$(rcon -a "$RCON_HOST" -p "$RCON_PASS" "$cmd" 2>&1)
    if echo "$result" | grep -qiE "error|unknown|invalid|failed"; then
        echo "  WARN  addtrait $trait -> $result"
    else
        echo "  OK    addtrait $trait"
    fi
done <<< "$TRAITS"

echo "=== Done. Remove later with remove_bane.sh ==="
```

- [ ] **Step 2: Write `remove_bane.sh`**

Create `scripts/zomboid-world-reset/remove_bane.sh` — same structure but `removetrait` instead of `addtrait`:

```bash
#!/usr/bin/env bash
# remove_bane.sh — remove the rolled bane trait(s) for one player via RCON.
#
# Usage:
#   ./remove_bane.sh <RCON_username>
#
# Inverse of apply_bane.sh. Skips RP-only banes.

set -euo pipefail

RCON_HOST="${RCON_HOST:-127.0.0.1:27015}"
RCON_PASS="${RCON_PASS:-CHANGEME}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA="$SCRIPT_DIR/boons-resolved.json"

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <RCON_username>"
    exit 1
fi

USER="$1"
RP_ONLY=$(jq -r ".\"$USER\".bane.rp_only" "$DATA")

if [[ "$RP_ONLY" == "true" ]]; then
    echo "RP-only bane for $USER — nothing to remove."
    exit 0
fi

TRAITS=$(jq -r '
    if .["'"$USER"'"].bane.traits then
        .["'"$USER"'"].bane.traits[]
    elif .["'"$USER"'"].bane.trait then
        .["'"$USER"'"].bane.trait
    else
        empty
    end
' "$DATA")

while IFS= read -r trait; do
    [[ -z "$trait" ]] && continue
    cmd="removetrait \"$USER\" $trait"
    result=$(rcon -a "$RCON_HOST" -p "$RCON_PASS" "$cmd" 2>&1)
    echo "  $trait -> $result"
done <<< "$TRAITS"
```

- [ ] **Step 3: Make executable**

Run:
```bash
chmod +x /docker/nemesis-configs/scripts/zomboid-world-reset/apply_bane.sh \
         /docker/nemesis-configs/scripts/zomboid-world-reset/remove_bane.sh
```

- [ ] **Step 4: Commit**

```bash
cd /docker/nemesis-configs
git add scripts/zomboid-world-reset/apply_bane.sh \
        scripts/zomboid-world-reset/remove_bane.sh
git commit -m "feat(zomboid-reset): add apply_bane.sh and remove_bane.sh trait wrappers"
```

---

### Task 1.5: Build `restore_items_only.sh` (sibling to restore_player.sh, additem only)

**Files:**
- Create: `scripts/zomboid-world-reset/restore_items_only.sh`

**Background:** The world reset uses blob transplant to restore skills (so `addxp` from the .rcon files is redundant and would double-up). We need a variant of `restore_player.sh` that only runs the `additem` lines.

- [ ] **Step 1: Write the script**

Create `scripts/zomboid-world-reset/restore_items_only.sh`:

```bash
#!/usr/bin/env bash
# restore_items_only.sh — like restore_player.sh but skips addxp (skills come from blob).
#
# Usage:
#   ./restore_items_only.sh <username>
#
# Reads .rcon files from /docker/nemesis-configs/scripts/zomboid-b42-migration/rcon-output/

set -euo pipefail

RCON_HOST="${RCON_HOST:-127.0.0.1:27015}"
RCON_PASS="${RCON_PASS:-CHANGEME}"
RCON_DIR="/docker/nemesis-configs/scripts/zomboid-b42-migration/rcon-output"

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
        result=$(rcon -a "$RCON_HOST" -p "$RCON_PASS" "$cmd" 2>&1)
        if echo "$result" | grep -qiE "error|unknown|invalid|failed|not found"; then
            echo "  WARN [item] $item -> $result"
            ((FAIL_COUNT++)) || true
        else
            echo "  OK   [item] $item"
            ((ITEM_COUNT++)) || true
        fi
    fi
done < "$FILE"

echo "=== Done: $ITEM_COUNT items restored, $FAIL_COUNT warnings ==="
```

- [ ] **Step 2: Make executable**

Run: `chmod +x /docker/nemesis-configs/scripts/zomboid-world-reset/restore_items_only.sh`

- [ ] **Step 3: Commit**

```bash
cd /docker/nemesis-configs
git add scripts/zomboid-world-reset/restore_items_only.sh
git commit -m "feat(zomboid-reset): add restore_items_only.sh (additem from .rcon, skip addxp)"
```

---

### Task 1.6: Write the operational RUNBOOK

**Files:**
- Create: `scripts/zomboid-world-reset/RUNBOOK.md`

- [ ] **Step 1: Write the runbook**

Create `scripts/zomboid-world-reset/RUNBOOK.md`:

```markdown
# Zomboid World Reset Runbook

Operational steps for executing the world reset described in
`docs/superpowers/specs/2026-05-08-zomboid-world-reset-design.md`.

## Pre-flight

- [ ] All five players notified, downtime window agreed.
- [ ] `boons-resolved.json` has no remaining `<...>` placeholder IDs.
- [ ] `clear_inventory.py` smoke-tested per Task 1.1 Step 7 (against a copied backup blob in /tmp).
- [ ] Confirm latest daily backup exists at `/docker/game/zomboid/backups/zomboid-*-T04-00-00.tar.gz`.

> **Note on dev verification:** Per operator direction, dev server is NOT used for pre-flight verification. RCON capability probing happens during the live reset window (step 6.5) once the fresh prod server is up but before any player joins. This trades the safety of dev verification for operational simplicity — accept that bane traits and other RCON behaviors will be discovered live.

## Execution sequence

### 1. Snapshot (live save)
```
sudo cp -a /docker/game/zomboid/ZomboidConfig/Saves/Multiplayer/Flight_Group_Alpha_PZ_Server \
           /docker/game/zomboid/ZomboidConfig/Saves/Multiplayer/Flight_Group_Alpha_PZ_Server.preworldreset-bak
```

### 2. Stop server
```
cd /docker/nemesis-configs/composed-apps/zomboid && sudo docker compose down
```

### 3. Edit server.ini (SpawnPoint, Seed)
Edit `composed-apps/zomboid/server.ini`:
- `SpawnPoint=10776,10947,0`
- `Seed=<new 16-char random>`

Generate new seed: `python3 -c "import random,string; print(''.join(random.choices(string.ascii_letters,k=16)))"`

Commit the edits:
```
cd /docker/nemesis-configs
git add composed-apps/zomboid/server.ini
git commit -m "chore(zomboid): set spawn point + new world seed for reset"
```

### 4. Edit SandboxVars (StartMonth)
Edit `composed-apps/zomboid/Flight_Group_Alpha_PZ_Server_SandboxVars.lua`:
- `StartMonth = 9`

Commit:
```
git add composed-apps/zomboid/Flight_Group_Alpha_PZ_Server_SandboxVars.lua
git commit -m "chore(zomboid): advance StartMonth to September for reset"
```

### 5. Wipe save
```
sudo rm -rf /docker/game/zomboid/ZomboidConfig/Saves/Multiplayer/Flight_Group_Alpha_PZ_Server
```

### 6. First boot (fresh world)
```
cd /docker/nemesis-configs/composed-apps/zomboid && sudo docker compose up -d
```

Wait ~60 seconds. Confirm via:
```
ls /docker/game/zomboid/ZomboidConfig/Saves/Multiplayer/Flight_Group_Alpha_PZ_Server/
```
(should show `players.db`, `vehicles.db`, `map_worldgen.bin`)

Capture new ResetID:
```
grep '^ResetID=' /docker/nemesis-configs/composed-apps/zomboid/server.ini
```
Update memory entry at `/home/aschneider/.claude/projects/-docker-nemesis-configs/memory/<file>.md`
with the new value.

### 6.5. RCON capability probe (replaces dev verification)

With the fresh server up and no players connected, run the probe:
```
sudo /docker/nemesis-configs/scripts/zomboid-world-reset/verify_rcon_capabilities.sh
```

Capture the output. If `addtrait`/`removetrait` show FAIL (unknown command), the bane traits cannot be applied — the bane portion of the reset becomes RP-only for all five characters. Decide whether to proceed; if yes, mark bane application as RP-only in your operator notes and skip steps in §11/§13 that call `apply_bane.sh`/`remove_bane.sh`.

### 7. Stop for blob transplant
```
cd /docker/nemesis-configs/composed-apps/zomboid && sudo docker compose down
```

### 8. Strip inventory + position from each backup blob, then transplant

For each of the five backup files (Bulbs, Emma_M7, Vinny, Artie, Curtis):

a) Copy backup blob into a working players.db and strip:
```
sudo cp /docker/game/zomboid/manual-backups/player-exports/<USER>.bin \
        /docker/game/zomboid/ZomboidConfig/Saves/Multiplayer/Flight_Group_Alpha_PZ_Server/<USER>.bin
sudo python3 /docker/nemesis-configs/scripts/zomboid-world-reset/clear_inventory.py \
        --save-dir /docker/game/zomboid/ZomboidConfig/Saves/Multiplayer/Flight_Group_Alpha_PZ_Server \
        --players <USER>
```

b) Insert the stripped blob into the fresh players.db. Reuse migrate.py's player phase logic — see `scripts/zomboid-b42-migration/migrate.py` for the schema-aware INSERT pattern. If migrate.py supports `--players <USER>`, use it directly; if not, run a one-off `sqlite3` INSERT command.

### 9. Second boot
```
cd /docker/nemesis-configs/composed-apps/zomboid && sudo docker compose up -d
```

### 10. Players log in (notify them)

Each player connects. Verify they see their character (looks, traits, skills intact).

### 11. Per player — apply boons + bane (player must be online)

For each connected player:
```
cd /docker/nemesis-configs/scripts/zomboid-world-reset
sudo ./restore_items_only.sh <RCON_username>
sudo ./apply_boons.sh <RCON_username>
sudo ./apply_bane.sh <RCON_username>
```

If post-login teleport is the chosen position-fix path:
```
rcon -a 127.0.0.1:27015 -p CHANGEME "teleport \"<RCON_username>\" 10776,10947,0"
```

### 12. Validation

Walk the [Validation Checklist](../../docs/superpowers/specs/2026-05-08-zomboid-world-reset-design.md#validation-checklist) from the spec.

### 13. Session end — remove banes
```
cd /docker/nemesis-configs/scripts/zomboid-world-reset
for u in Bulbs Emma_M7 Vinny Artie Curtis; do
    sudo ./remove_bane.sh "$u"
done
```

## Rollback

See [Rollback Plan](../../docs/superpowers/specs/2026-05-08-zomboid-world-reset-design.md#rollback-plan) in the spec.
```

- [ ] **Step 2: Commit**

```bash
cd /docker/nemesis-configs
git add scripts/zomboid-world-reset/RUNBOOK.md
git commit -m "docs(zomboid-reset): add operational runbook"
```

---

## Phase 2 — SKIPPED

Per operator direction (2026-05-08), the dev-server smoke test phase is skipped. The reset will be executed directly on prod with the RCON capability probe (RUNBOOK §6.5) standing in as the only live verification. Accepted risk: bane traits, item IDs, and RCON command behaviors are validated live on prod rather than rehearsed on dev.

---

## Phase 3 — Production Execution

This phase is the human-driven runbook in `scripts/zomboid-world-reset/RUNBOOK.md`. It is NOT a single automatable task — it requires player coordination and real-time judgment. The agentic worker should hand off here.

### Task 3.1: Hand off to operator

- [ ] **Step 1: Confirm pre-flight checklist in RUNBOOK.md**

All Phase 0 / 1 tasks complete and committed (Phase 2 skipped per operator direction). Player downtime window scheduled.

- [ ] **Step 2: Print final summary**

Print the resolved boons table from `boons-resolved.json` to confirm correctness:

```bash
jq -r 'to_entries[] | "\(.key) (\(.value.display_name)): rolls=\(.value.rolls)"' \
    /docker/nemesis-configs/scripts/zomboid-world-reset/boons-resolved.json
```

- [ ] **Step 3: Stop here**

The operator (the user) executes the RUNBOOK during the downtime window. The plan does not auto-execute prod actions.

---

## Self-Review Notes

Spec coverage: every numbered step in the spec's "World Reset Plan" maps to either a Phase 1 build task (scripts to enable that step) or to the RUNBOOK (operational instruction). Spec's bane enforcement primary + fallback paths are covered by Phase 0.1 (verification) + apply_bane.sh logic. Open questions in the spec are addressed in Phase 0 (RCON capability, item ID resolution) or Phase 1 (clear_inventory.py build, position metadata stripping in same script).

Type/name consistency: `restore_items_only.sh` is the only sibling-script name introduced (spec mentioned it generically); all script names referenced across tasks match. Trait names in `boons-resolved.json` (SlowReader, HardOfHearing, SlowHealer, ProneToIllness) match the spec's Bane Enforcement section. `Husbandry` skill appears in both Bulbs and Emma's xp arrays — matches spec's Table 4 row 19.

Placeholder scan: the only `<...>` placeholders are in `boons-resolved.json` item IDs, which Task 1.2 Step 2 explicitly resolves. Marker bytes in `clear_inventory.py` (`<TBD: ...>`) are explicitly resolved in Task 1.1 Step 6.
