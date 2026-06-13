# Zomboid B42.16 Migration Design

**Date:** 2026-04-02
**Status:** Draft

## Context

The production Zomboid server is running B42.15. The save format changed between B42.15 and B42.16, making direct upgrade incompatible. The plan is to boot a fresh B42.16 world and selectively import player data, base chunks, and vehicles from the B42.15 backup.

### Scope

- **Players:** 8 players — character save blobs imported as-is (preserves appearance/traits/skills); inventory cleared post-conversion, then restored via RCON
- **Chunks:** 22 chunkdata files covering the fire station base (cells X 30-34, Y 44-49, 250 tiles/cell)
- **Vehicles:** 48 vehicles within ~200 tiles of the fire station base (tile range X 7950-8350, Y 11550-11950)

### Inventory Strategy

Player blobs are imported into B42.16 intact. The server boots once to convert them to B42.16 format. After that conversion, `clear_inventory.py` strips the inventory section from each player's converted blob in-place. Players then log in to a character with correct appearance, traits, and skills — but empty inventory. The `gen_rcon.py` output is used to restore items via RCON.

This avoids importing B42.15 item IDs into a B42.16 world while still preserving everything about the character that isn't inventory.

### Existing Backups

All source files are in `/docker/game/zomboid/manual-backups/`:

| Path | Contents |
|---|---|
| `player-exports/*.bin` | Raw B42.15 player save blobs (8 players) |
| `player-exports/*.txt` | Human-readable skills + inventory per player |
| `firestation-chunk-backup/chunkdata_*.bin` | 22 chunkdata files |
| `firestation-chunk-backup/vehicles_base.sql` | 48 vehicle INSERT statements |
| `firestation-chunk-backup/vehicles_full_backup.db` | Full vehicles.db snapshot |

---

## Execution Environment

- Python 3.9+ (already present on the host)
- Standard library only (`sqlite3`, `shutil`, `os`, `re`, `argparse`)
- Run as root (required to read/write `/docker/game/zomboid/` paths)
- Target fresh save path passed as a CLI argument — no hardcoded paths

---

## Prerequisites

Before running `migrate.py`:

1. Boot the fresh B42.16 server with `docker compose up -d`
2. Wait ~30 seconds for save files to be generated (no players need to log in)
3. Stop the server: `docker compose down`
4. Take a snapshot of the fresh save directory before running any migration:
   ```
   cp -r <fresh-save-path> <fresh-save-path>.premigration-bak
   ```
   This is the rollback point. If migration fails, delete the save and restore this backup.

Players do NOT need to log in during the prerequisite boot. The server generates the required database files (`players.db`, `vehicles.db`) on startup.

---

## Approach

Two scripts in `scripts/zomboid-b42-migration/`, always run with `--dry-run` first.

### Primary: `migrate.py` (Approach B — Database Transplant)

Selectively inserts B42.15 data into the freshly generated B42.16 save.

**Usage:**
```
sudo python3 migrate.py --backup-dir /docker/game/zomboid/manual-backups \
                        --save-dir <fresh-b42-save-path> \
                        [--dry-run]
```

**Phase 1 — Players**

- Compare the schema of `players.db` from the backup vs the fresh save
- For each column present in BOTH schemas, copy it. Columns added in B42.16 that don't exist in the backup receive `NULL` or their SQLite default
- If B42.16 has any `NOT NULL` columns without defaults that are absent from the backup schema, abort and list them — these require manual handling before proceeding
- Use `INSERT OR REPLACE` — the fresh save has no player rows (no one logged in), so this behaves as a plain INSERT
- After insert, query the count of rows in fresh `players.db` and verify it equals 8

**Phase 2 — Vehicles**

`vehicles_base.sql` format: the file contains a `BEGIN TRANSACTION`, one `INSERT OR REPLACE INTO vehicles (id, wx, wy, x, y, worldversion, data) VALUES (...)` per vehicle, and a `COMMIT`. Vehicle IDs are the first value in each VALUES clause.

- Parse `vehicles_base.sql` line by line to extract vehicle IDs before executing anything
- Query fresh `vehicles.db` for any existing IDs that conflict; report them
- Execute inserts row-by-row using `cursor.execute()` with `INSERT OR IGNORE` (not `executescript()`) so individual conflicting rows are skipped without aborting the whole batch
- After insert, query count of vehicle rows in fresh db and compare to 48; report any discrepancy
- Validation: "inserted cleanly" means the row count matches and no SQL constraint errors were raised

**Phase 3 — Chunks**

- For each of the 22 chunkdata files, check if a file with the same name already exists in the fresh save's `chunkdata/` directory
- If it does, copy it to `<filename>.bak` before overwriting
- Copy the backup file into place
- Chunk format compatibility check: read the first 4 bytes of each backup file. If any fresh-world chunkdata files exist, compare against the first 4 bytes of any one of them. If they differ, log a **DATA LOSS WARNING** for those chunks: the server may regenerate them from vanilla on first load, erasing all base modifications. If no fresh-world chunkdata files exist (common for a server with no player visits), skip the comparison and log a note that the check was skipped

**Output:** `migration_report.txt` written to the script directory (under `--dry-run`, output goes to stdout only and no files are written). Report lists:
- Schema differences detected
- Player row counts (expected vs actual)
- Vehicle row counts (expected vs actual)
- Chunk files copied, skipped, or flagged with data loss warning
- Overall pass/fail status

---

### Step 2: `clear_inventory.py` — Strip Inventory from Converted Blobs

Runs after the server has booted once and converted player saves to B42.16 format. Opens the B42.16 `players.db` and strips the inventory section from each player's `data` BLOB, leaving character appearance, traits, and skills intact.

**Usage:**
```
sudo python3 clear_inventory.py --save-dir <fresh-b42-save-path> [--dry-run]
```

**How it works:**

The B42.15 blob format (confirmed by analysis this session) stores inventory items as length-prefixed string records embedded in the binary data. Items always follow a predictable character identity section (`name`, `gender`, `profession`, `VoiceFemale`, `OverEye` fields). The script:

1. Opens B42.16 `players.db` and reads each player's `data` BLOB
2. Scans the blob for the inventory section boundary — the first occurrence of a `Base.` or module-prefixed item ID string (e.g. `Base.Necklace_Gold`) after the character identity section
3. Backs up the original blob as `<username>_prestrip.blob` in the script directory before modifying
4. Truncates the blob at the inventory boundary, replacing the inventory section with the correct empty-inventory sentinel bytes (determined by comparing against a known-empty character blob if available, otherwise zero-fills)
5. Writes the stripped blob back to `players.db`
6. Reports: player name, original blob size, stripped blob size, bytes removed

**Unknown at spec time:** The exact empty-inventory sentinel for B42.16 is not known until the server generates one. The script includes a `--reference-blob` argument that accepts a path to a known-empty B42.16 character blob to use as the sentinel template instead of zero-filling. If zero-fill causes issues, revert using the `.blob` backup and retry with a reference blob.

**Dry-run:** prints what would be stripped per player without modifying the database.

---

### Step 3: `gen_rcon.py` — RCON Inventory Restoration (and Skills Fallback)

Parses the `.txt` player exports and generates one `.rcon` command file per player. Safe to run at any time — reads only, writes only to `rcon-output/`.

**Usage:**
```
sudo python3 gen_rcon.py --export-dir /docker/game/zomboid/manual-backups/player-exports \
                         --vehicles-sql /docker/game/zomboid/manual-backups/firestation-chunk-backup/vehicles_base.sql \
                         --output-dir ./rcon-output
```

`<username>` in all emitted commands is the filename stem of the `.txt` export (e.g., `Artie.txt` → `Artie`, `Emma_M7.txt` → `Emma_M7`).

**Skills**
- For each skill line with XP > 0, emit: `/grantxp <username> <skill>=<xp>`
- Uses raw XP values so the server computes correct levels natively
- Known B42 skill names (skip anything not in this list):
  `Strength, Fitness, Sprinting, Lightfoot, Nimble, Sneak, Axe, Blunt, SmallBlunt, LongBlade, SmallBlade, Spear, Maintenance, Aiming, Reloading, Carpentry, Cooking, Farming, FirstAid, Electrical, Mechanics, MetalWelding, Tailoring, Doctor, Woodwork, Electricity, Metalwork, PlantScavenging, Husbandry, Carving, Trapping, Fishing`

**Inventory**
- For each item line, emit: `/additem <username> <item_id>`
- Known limitation: items added at default condition, quantity of 1 each
- If an item ID doesn't match `Module.ItemName` format, log a warning and skip

**Vehicles**
- Not recoverable via RCON
- Parse `--vehicles-sql` to extract vehicle IDs and (x, y) coordinates
- Generate `vehicles_lost.txt` listing each vehicle ID and its world tile coordinates for manual reference

**Error handling:**
- Missing `.txt` file for a player: log warning, skip that player, continue
- Empty `.txt` file: log warning, generate empty `.rcon` with a comment noting the issue
- Malformed line: skip the line, log the filename and line number

**Output (generated at runtime, not source files):**
```
rcon-output/           ← generated by gen_rcon.py
  Artie.rcon
  Artie1.rcon
  Bulbs.rcon
  Curtis.rcon
  Emma_M7.rcon
  KnobleOutlaw.rcon
  Vinny.rcon
  bleedfuel.rcon
  vehicles_lost.txt
```

Run `.rcon` files by pasting into the server console or piping through an RCON client.

---

## Rollback

If migration fails or produces bad results:

1. Stop the server
2. Delete the fresh save directory
3. Restore from pre-migration snapshot: `cp -r <save-path>.premigration-bak <save-path>`
4. Review the `migration_report.txt` from the failed run to diagnose what went wrong before trying again

The B42.15 backups are never modified by either script.

---

## Validation Criteria

After step 8 (server boot post-inventory-clear), one player logs in and confirms:

- [ ] Character appearance and traits are correct
- [ ] Skills match the `.txt` export for that player
- [ ] Inventory is empty (expected at this stage)
- [ ] Fire station base loads (barricades, containers, placed items present)
- [ ] Vehicles appear at the fire station
- [ ] No server crash on chunk load

After step 9 (RCON inventory restore), same player confirms:

- [ ] Inventory contains expected items
- [ ] No duplicate or missing items

If skills are wrong, use the `/grantxp` lines from the `.rcon` files. If inventory restore fails for specific items (item ID not found in B42.16), log those as manual handouts.

---

## Known Limitations

- Approach C inventory: item quantities default to 1, item condition defaults to new
- Approach C vehicles: no RCON command exists to spawn a vehicle with saved state
- Chunk format: if B42.16 changed the chunk binary format, affected chunks will be silently regenerated from vanilla — base builds in those chunks will be lost
- Player blob data (`data BLOB` column) may contain B42.15-specific structures that B42.16 rejects silently — character appearance or traits may reset even if skills and inventory restore correctly

---

## File Locations

```
scripts/zomboid-b42-migration/
  migrate.py               ← Step 1: transplant blobs, vehicles, chunks into fresh B42.16 save
  clear_inventory.py       ← Step 2: strip inventory from converted B42.16 blobs
  gen_rcon.py              ← Step 3: generate RCON commands to restore inventory (and skills fallback)
  README.md                ← step-by-step operator instructions
  migration_report.txt     ← generated by migrate.py
  rcon-output/             ← generated by gen_rcon.py
  blob-backups/            ← generated by clear_inventory.py (<username>_prestrip.blob files)
```

## Recommended Execution Order

1. Run `gen_rcon.py` first (read-only, always safe to run); review `rcon-output/`
2. Take pre-migration snapshot of fresh save
3. Run `migrate.py --dry-run` and review `migration_report.txt`
4. Run `migrate.py` for real (imports blobs, vehicles, chunks)
5. Boot server once (converts B42.15 blobs to B42.16 format); stop server
6. Run `clear_inventory.py --dry-run`; review output
7. Run `clear_inventory.py` for real (strips inventory from converted blobs)
8. Boot server — players log in with clean characters (appearance/traits/skills intact, empty inventory)
9. Run RCON commands from `rcon-output/` per player to restore inventory
10. If skills are also wrong, use the `/grantxp` lines from the same `.rcon` files
