# Zomboid Vehicle Repopulation Design

**Date:** 2026-05-22
**Status:** Draft

## Context

Dev was rebuilt from prod and the KI5 vehicle collection (80 mods) plus `[B42]Project RV Interior` were added. Dev boots cleanly. We now want to promote the same mod set to prod and force the new vehicles to appear in already-explored chunks (Muldraugh, Rosewood, etc.), not just in chunks the survivors have yet to visit.

### Goals

- Promote dev's mod list verbatim to prod (`MOD_NAMES` and `MOD_WORKSHOP_IDS` in `composed-apps/zomboid/docker-compose.yaml`).
- Make new-mod vehicles appear in cells the players have already loaded.
- Preserve player builds, base stashes, and character progression.

### Out of Scope

- World reset (already done 2026-05-08; not redoing it).
- Sandbox changes besides the load-order shuffle (`PROJECTRVInterior42` first).
- Retroactively changing already-spawned zombies or street loot. Some of that may also reset as a side effect of B; that's accepted.

## Approach A: Wipe `vehicles.db`, let the server respawn

B42 stores vehicles in a separate SQLite file (`Saves/Multiplayer/.../vehicles.db` + journal). Builds live in `chunkdata/`; loot lives in `map/`. Deleting `vehicles.db` removes all existing vehicles without touching the rest.

Open question: PZ may also gate vehicle spawn on a per-chunk "vehicles already spawned here" flag stored elsewhere. If A alone doesn't retro-spawn, we'll escalate to deleting the relevant chunk-visited tracker (Approach B).

### Test on dev first

Dev was rebuilt from a recent prod backup, then wiped to a fresh world. To get a meaningful test, we re-clone prod → dev *after* prod has the new mods loaded, then run Approach A on dev. If new mod vehicles appear in already-loaded cells without re-rolling those cells' buildings/loot, we apply the same procedure to prod.

## Sequence

1. **Promote mods to prod compose.** Copy dev's `MOD_NAMES` and `MOD_WORKSHOP_IDS` env values verbatim into `composed-apps/zomboid/docker-compose.yaml`. Same load order (PROJECTRVInterior42 first).
2. **Snapshot prod save.** `sudo cp -a Saves/.../Flight_Group_Alpha_PZ_Server Saves/.../Flight_Group_Alpha_PZ_Server.prevehiclerepop-bak` — rollback point.
3. **Restart prod.** `down`/`up -d`. Workshop downloads (~80 mods, expect 5–10 min). Wait for `*** SERVER STARTED ****`.
4. **Verify mods loaded.** No "required mod ... not found" warnings, no `Exiting due to errors`. Connect with a client briefly to confirm.
5. **Re-clone prod → dev.** Stop dev. Wipe dev `ZomboidConfig/Saves`, `backups`, `Logs`, `messaging`. Extract the most recent prod backup with `--strip-components=1`. Start dev.
6. **Run Approach A on dev.** Stop dev. Delete `vehicles.db` + `vehicles.db-journal` in dev's save dir. Start dev. Walk into a previously explored cell, confirm new mod vehicles appear and player tile mods/loot are intact.
7. **Decide.** If A works on dev, schedule the prod cutover (announce, snapshot, stop, delete, start). If A doesn't retro-spawn, fall back to Approach B (also delete `map_visited_server/` or equivalent and accept that zombies/loot also re-roll).

## Rollback

- Step 2 snapshot is the rollback point for prod. To roll back: `sudo docker compose down`, `sudo rm -rf Saves/.../Flight_Group_Alpha_PZ_Server`, `sudo mv Flight_Group_Alpha_PZ_Server.prevehiclerepop-bak Flight_Group_Alpha_PZ_Server`, `sudo docker compose up -d`.
- Backup tarball at `/docker/game/zomboid/backups/zomboid-2026-05-22T04-00-00.tar.gz` is the secondary fallback.

## Risks

- **Player downtime** during step 3 restart (5–10 min for workshop download). Worth announcing to players.
- **Approach A may not retro-spawn.** If the spawn check is per-chunk, deleting `vehicles.db` may produce a vehicle-less world until players explore new chunks. Mitigation: dev test in step 6 catches this before prod cutover.
- **`vehicles.db-journal` left behind** could cause SQLite to recover stale state. We delete the journal too.
- **Client desync** if a player joins during workshop download. PZ kicks them; harmless.
