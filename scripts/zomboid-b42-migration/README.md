# Zomboid B42.15 to B42.16 Server Migration

Tool suite for migrating a running B42.15 Zomboid server to B42.16, preserving player characters, inventory, skills, base structures, and vehicles.

## Overview

Two complementary scripts handle the migration:

- **`migrate.py`** — Primary migration tool. Performs database transplant in three phases: player data, chunk terrain/structures, and vehicles.
- **`gen_rcon.py`** — RCON fallback generator. Creates command files for manual character/inventory restoration if the primary migration fails.

Source data is located at `/docker/game/zomboid/manual-backups/`:
- `player-exports/*.txt` and `*.bin` — 8 player character exports
- `firestation-chunk-backup/chunkdata_*.bin` — 22 chunk files with base structures
- `firestation-chunk-backup/vehicles_base.sql` — 48 vehicle INSERT statements

## Prerequisites

Before running any migration script:

1. **Boot the fresh B42.16 server** and generate initial save files:
   ```bash
   cd /docker/homelab-config/data-host/composed-apps/zomboid
   sudo docker compose up -d
   ```

2. **Wait ~30 seconds** for the server to create initial save directories. Player logins are not required.

3. **Stop the server**:
   ```bash
   sudo docker compose down
   ```

4. **Create a pre-migration snapshot** of the fresh save directory. This is your rollback point:
   ```bash
   cp -r <fresh-save-path> <fresh-save-path>.premigration-bak
   ```

   Replace `<fresh-save-path>` with the actual B42.16 save directory (typically `/docker/game/zomboid/Saves/Flight_Group_Alpha_PZ_Server/` or similar).

## Recommended Execution Order

### Step 1: Generate RCON Fallback Commands (Read-Only)

This step is always safe — it only reads the backup data and generates command files.

```bash
sudo python3 gen_rcon.py \
  --export-dir /docker/game/zomboid/manual-backups/player-exports \
  --vehicles-sql /docker/game/zomboid/manual-backups/firestation-chunk-backup/vehicles_base.sql \
  --output-dir ./rcon-output
```

**Review the output:**
- Check `rcon-output/` for generated `.rcon` files (one per player)
- Verify `rcon-output/vehicles_lost.txt` lists expected fire station vehicle coordinates
- If output looks incorrect, diagnose before proceeding

### Step 2: Dry-Run the Primary Migration

Test the migration without modifying any data:

```bash
sudo python3 migrate.py \
  --backup-dir /docker/game/zomboid/manual-backups \
  --save-dir <fresh-b42-save-path> \
  --dry-run
```

**Review the output:**
- Check console output for warnings about chunk binary format incompatibilities
- Review stdout output for phase-by-phase status
- If any phase shows FAIL, diagnose the issue before proceeding

### Step 3: Execute the Real Migration

Once the dry-run succeeds:

```bash
sudo python3 migrate.py \
  --backup-dir /docker/game/zomboid/manual-backups \
  --save-dir <fresh-b42-save-path>
```

This command will:
1. Migrate all 8 player characters (skills, experience, inventory)
2. Transplant 22 chunk files (base structures, barricades, containers)
3. Restore 48 vehicles with state at the fire station

**Check the report:**
- Review `migration_report.txt` after completion
- All three phases must show PASS status
- Note any warnings about chunk format issues

### Step 4: Boot Server and Validate

Start the server:

```bash
cd /docker/homelab-config/data-host/composed-apps/zomboid
sudo docker compose up -d
```

Verify all migrated data is intact:

- [ ] **Players**: Log in and verify character skills match the B42.15 export
- [ ] **Inventory**: Check that all expected items are present
- [ ] **Base structures**: Navigate to fire station and confirm barricades, containers, and placed items are present
- [ ] **Vehicles**: Verify vehicles appear at fire station with correct state
- [ ] **Server stability**: No crashes on chunk load; normal gameplay in migrated areas

If all checks pass, the migration is complete.

## Rollback Procedure

If migration fails or produces invalid results:

1. **Stop the server**:
   ```bash
   cd /docker/homelab-config/data-host/composed-apps/zomboid
   sudo docker compose down
   ```

2. **Delete the migrated save directory**:
   ```bash
   rm -r <fresh-b42-save-path>
   ```

3. **Restore from pre-migration snapshot**:
   ```bash
   cp -r <fresh-save-path>.premigration-bak <fresh-b42-save-path>
   ```

4. **Diagnose** by reviewing `migration_report.txt` to understand what failed

5. **Address root cause** (missing backup files, permissions, chunk incompatibilities, etc.) before re-running

The B42.15 backup files at `/docker/game/zomboid/manual-backups/` are never modified by either script and remain available for subsequent attempts.

## Fallback: Manual RCON Restoration

If `migrate.py` produces bad results but `gen_rcon.py` succeeded:

1. Roll back using the rollback procedure above
2. Boot a fresh B42.16 server and let players log in normally
3. For each player, obtain their `.rcon` file from `rcon-output/`
4. Paste commands into the server console or pipe through an RCON client:
   ```bash
   # Example: pipe commands to RCON client
   cat rcon-output/Player1.rcon | rcon-client <server> <port> <password>
   ```

**Known RCON fallback limitations:**
- Item quantities default to 1 (manual adjustment required for stacks)
- Item condition defaults to new (damage/wear not restored)
- Vehicles cannot be restored via RCON (see `rcon-output/vehicles_lost.txt` for fire station coordinates to reference for manual rebuilds)

## Known Limitations

- **Item quantities**: RCON fallback only restores quantity=1 per item (condition defaults to new)
- **Vehicles via RCON**: No RCON command exists to spawn vehicles with full saved state
- **Chunk binary format**: If B42.16 changed the chunk binary format, affected chunks will be silently regenerated from vanilla. Any base builds in those chunks will be lost. `migrate.py` warns about detected incompatibilities.
- **Player blob data**: B42.15 player data structures may contain version-specific fields that B42.16 silently rejects. Character appearance or traits may reset even if skills and inventory restore correctly.

## Debugging

If the migration fails:

1. **Check `migration_report.txt`** for phase-specific errors and warnings
2. **Verify source files exist**:
   ```bash
   ls -la /docker/game/zomboid/manual-backups/player-exports/
   ls -la /docker/game/zomboid/manual-backups/firestation-chunk-backup/
   ```
3. **Check file permissions** — both scripts require read access to backup files and write access to the save directory
4. **Review console output** for Python exceptions or diagnostic messages
5. **Examine save directory structure** to ensure B42.16 save directory is correctly specified

For persistent issues, consult the B42.15 backup files and consider using the RCON fallback approach.
