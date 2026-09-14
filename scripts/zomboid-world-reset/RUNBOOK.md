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
cd /docker/homelab-config/data-host/composed-apps/zomboid && sudo docker compose down
```

### 3. Edit server.ini (SpawnPoint, Seed)
Edit `composed-apps/zomboid/server.ini`:
- `SpawnPoint=10776,10947,0`
- `Seed=<new 16-char random>`

Generate new seed: `python3 -c "import random,string; print(''.join(random.choices(string.ascii_letters,k=16)))"`

Commit the edits:
```
cd /docker/homelab-config
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
cd /docker/homelab-config/data-host/composed-apps/zomboid && sudo docker compose up -d
```

Wait ~60 seconds. Confirm via:
```
ls /docker/game/zomboid/ZomboidConfig/Saves/Multiplayer/Flight_Group_Alpha_PZ_Server/
```
(should show `players.db`, `vehicles.db`, `map_worldgen.bin`)

Capture new ResetID:
```
grep '^ResetID=' /docker/homelab-config/data-host/composed-apps/zomboid/server.ini
```
Update memory entry at `/home/aschneider/.claude/projects/-docker-nemesis-configs/memory/<file>.md`
with the new value.

### 6.5. RCON capability probe (replaces dev verification)

With the fresh server up and no players connected, run the probe:
```
sudo /docker/homelab-config/scripts/zomboid-world-reset/verify_rcon_capabilities.sh
```

Capture the output. If `addtrait`/`removetrait` show FAIL (unknown command), the bane traits cannot be applied — the bane portion of the reset becomes RP-only for all five characters. Decide whether to proceed; if yes, mark bane application as RP-only in your operator notes and skip steps in §11/§13 that call `apply_bane.sh`/`remove_bane.sh`.

### 7. Stop for blob transplant
```
cd /docker/homelab-config/data-host/composed-apps/zomboid && sudo docker compose down
```

### 8. Strip inventory from each backup blob, then transplant into fresh players.db

The fresh `players.db` uses the table `networkPlayers`. For each of the five characters
(Bulbs, Emma_M7, Vinny, Artie, Curtis):

a) Insert the backup blob into the fresh `players.db`. Reuse migrate.py's player phase
   logic — see `scripts/zomboid-b42-migration/migrate.py` for the schema-aware INSERT
   pattern. Run a one-off `sqlite3` INSERT (or adapt migrate.py) to load the blob from
   the backup `.bin` export file into the `networkPlayers` table:

```
SAVE_DIR=/docker/game/zomboid/ZomboidConfig/Saves/Multiplayer/Flight_Group_Alpha_PZ_Server
python3 - <<'EOF'
import sqlite3
with open('/docker/game/zomboid/manual-backups/player-exports/<USER>.bin', 'rb') as f:
    blob = f.read()
conn = sqlite3.connect('$SAVE_DIR/players.db')
conn.execute(
    "INSERT OR REPLACE INTO networkPlayers (username, data) VALUES (?, ?)",
    ('<USER>', blob)
)
conn.commit()
conn.close()
EOF
```

b) Strip the inventory section from the inserted blob:
```
sudo python3 /docker/homelab-config/scripts/zomboid-world-reset/clear_inventory.py \
        --save-dir /docker/game/zomboid/ZomboidConfig/Saves/Multiplayer/Flight_Group_Alpha_PZ_Server \
        --players <USER>
```

Repeat for each of the five players.

### 9. Second boot
```
cd /docker/homelab-config/data-host/composed-apps/zomboid && sudo docker compose up -d
```

### 10. Players log in (notify them)

Each player connects. Verify they see their character (looks, traits, skills intact).

### 11. Per player — apply boons + bane (player must be online)

For each connected player:
```
cd /docker/homelab-config/scripts/zomboid-world-reset
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
cd /docker/homelab-config/scripts/zomboid-world-reset
for u in Bulbs Emma_M7 Vinny Artie Curtis; do
    sudo ./remove_bane.sh "$u"
done
```

## Rollback

See [Rollback Plan](../../docs/superpowers/specs/2026-05-08-zomboid-world-reset-design.md#rollback-plan) in the spec.
