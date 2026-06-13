# Zomboid World Reset Design

**Date:** 2026-05-08
**Status:** Draft

## Context

The production Zomboid server is being soft-reset to start a new arc. The fiction: the group left Rosewood the night the fire station burned down (leaked generator + gasoline ignition). Two months have passed on the road. The party has now regrouped just south of Muldraugh and is heading toward Louisville's airport. Player characters carry over (looks, traits, skills) but the world is regenerated fresh and the in-game date jumps to September.

### Goals

- Wipe the world entirely and regenerate it with a new seed.
- Preserve five players' character identity (looks, traits, skills) and accounts.
- Force-spawn all players at a single point south of Muldraugh.
- Advance the in-game start date from July to September.
- Apply per-character "boons" and a "bane" derived from a 5d20 roll table set, restored via RCON.

### Out of Scope

- Account whitelist changes (whitelist DB stays as-is).
- Mod list changes (current prod 28-mod set carries over verbatim).
- Sandbox setting changes besides `StartMonth` and `Seed`.
- Restoring inventory at original quantity/condition (RCON `additem` resets both — accepted as fitting the "two months on the road" lore).
- Restoring the other three player backups (Artie1, bleedfuel, KnobleOutlaw) — they remain archived in place for possible future use.

---

## Final Roster

Five characters get restored and rolled for. Display name is the player's handle; backup file is the source of truth for the character; RCON username is what `addxp`/`additem` and trait commands target.

| Display Name        | Backup file                          | RCON username |
|---------------------|--------------------------------------|---------------|
| Step-fist (Stephen) | `Bulbs.bin` / `Bulbs.rcon`           | `Bulbs`       |
| Emma                | `Emma_M7.bin` / `Emma_M7.rcon`       | `Emma_M7`     |
| Vinny               | `Vinny.bin` / `Vinny.rcon`           | `Vinny`       |
| RT-541              | `Artie.bin` / `Artie.rcon`           | `Artie`       |
| Curtis              | `Curtis.bin` / `Curtis.rcon`         | `Curtis`      |

Backup source: `/docker/game/zomboid/manual-backups/player-exports/`

Archived (not touched in this reset): `Artie1.*`, `bleedfuel.*`, `KnobleOutlaw.*`.

---

## World Reset Plan

### Step 1 — Safety snapshot

Before any destructive action, snapshot the live save directory:

```
sudo cp -a /docker/game/zomboid/ZomboidConfig/Saves/Multiplayer/Flight_Group_Alpha_PZ_Server \
           /docker/game/zomboid/ZomboidConfig/Saves/Multiplayer/Flight_Group_Alpha_PZ_Server.preworldreset-bak
```

This is the rollback point. The existing daily backup at `/docker/game/zomboid/backups/zomboid-2026-05-08T04-00-00.tar.gz` is the secondary fallback.

### Step 2 — Stop the server

```
cd /docker/nemesis-configs/composed-apps/zomboid && sudo docker compose down
```

### Step 3 — Update server.ini

Edit `/docker/nemesis-configs/composed-apps/zomboid/server.ini`:

- `SpawnPoint=10776,10947,0` (was `8134,11732,1`) — forces all new spawns to the south-Muldraugh regroup point. Cell 35x36, relative 276x147.
- `Seed=<new random value>` — generate a fresh 16-char seed (current value is `lcGjmaUfvnyjLHTB`). Per the comment in `server.ini`, changing the seed only takes effect when `map_worldgen.bin` is also deleted, which the full save wipe in Step 5 satisfies.

`ResetID` and `ServerPlayerID` should be **left alone** — the server will increment `ResetID` automatically during a soft-reset boot. After the server boots fresh, capture the new `ResetID` and update the project memory entry.

### Step 4 — Update SandboxVars

Edit `/docker/nemesis-configs/composed-apps/zomboid/Flight_Group_Alpha_PZ_Server_SandboxVars.lua`:

- `StartMonth = 9` (was `7`)
- All other values unchanged.

`StartYear`, `StartDay`, `StartTime`, `DayLength`, `Zombies`, `ZombieRespawn`, etc. remain at current values.

### Step 5 — Wipe the save

Delete the entire save directory (the snapshot from Step 1 is the rollback):

```
sudo rm -rf /docker/game/zomboid/ZomboidConfig/Saves/Multiplayer/Flight_Group_Alpha_PZ_Server
```

The `db/` directory at `/docker/game/zomboid/ZomboidConfig/db/Flight Group Alpha PZ Server.db` is the **whitelist DB** — leave it alone. Account names and passwords persist there.

### Step 6 — First boot (fresh world)

```
cd /docker/nemesis-configs/composed-apps/zomboid && sudo docker compose up -d
```

Wait ~60 seconds for the server to:
- Generate `Saves/Multiplayer/Flight_Group_Alpha_PZ_Server/` with empty `players.db`, `vehicles.db`, `map_worldgen.bin` (using the new seed).
- Increment `ResetID`. Capture the new value from `server.ini` (the container writes back to it) and update memory.

### Step 7 — Stop the server for blob transplant

```
cd /docker/nemesis-configs/composed-apps/zomboid && sudo docker compose down
```

### Step 8 — Player blob transplant

For each of the 5 rostered characters, transplant their `.bin` blob into the fresh `players.db`. This is the same approach as `scripts/zomboid-b42-migration/migrate.py` Phase 1 (player schema-aware INSERT), with one modification: **strip the inventory section from each blob before insert** so `additem` restoration starts from a clean slate.

Inventory stripping requires a `clear_inventory.py`-style script. The companion b42 migration design (`docs/superpowers/specs/2026-04-02-zomboid-b42-migration-design.md`) specifies this script but it has not yet been built. Implementation for this reset must produce it (or a targeted one-off variant for the five named characters) before Step 8 can complete.

The blob preserves: appearance, body type, traits, skill levels and XP, stats, character moodles baseline.

### Step 9 — Second boot (with restored players)

```
cd /docker/nemesis-configs/composed-apps/zomboid && sudo docker compose up -d
```

Players log in. Each lands on their restored character. Spawn position depends on the resolution chosen in Step 11 — either the configured spawn point (if blob position was stripped in Step 8) or wherever the blob's saved position resolves in the new world (and gets teleported afterward).

### Step 10 — Per-player RCON restoration

Once a player is online, an admin runs:

```
./scripts/zomboid-b42-migration/restore_player.sh <RCON_username>
```

This script will be modified (or a sibling script created) to:
- Skip `addxp` lines (skills already restored via blob).
- Run only `additem` lines from `<player>.rcon`.

### Step 11 — Force-position to spawn point (if needed)

The transplanted blob may carry the character's last logged-off position from the previous world. If so, the player will spawn at that old coordinate (now in newly-generated terrain) instead of the configured `SpawnPoint`. Two acceptable resolutions:

- **Pre-login (preferred):** strip position metadata from each blob during the Step 8 transplant, alongside inventory stripping. The character then has no saved position and falls through to `SpawnPoint`.
- **Post-login:** admin runs `teleport "<RCON_username>" 10776,10947,0` after each player logs in.

Implementation should pick one approach and apply it to all five characters consistently.

### Step 12 — Apply rolled boons (per player)

For each character, apply the boon set from their resolved roll (see [Per-Character Resolved Outcomes](#per-character-resolved-outcomes) below):
- `additem "<RCON_username>" "<melee_item_id>" 1` — Table 1
- `additem "<RCON_username>" "<clothing_item_id>" 1` — Table 2
- `additem "<RCON_username>" "<gun_item_id>" <count>` plus matching ammo — Table 3 (counts vary per row; e.g., row 13 = `additem ... .38_revolver 1` then `additem ... .38_round 30`)
- `addxp "<RCON_username>" <Skill>=<XP>` (per skill listed) — Table 4
- Bane application — see [Bane Enforcement Strategy](#bane-enforcement-strategy)

A `apply_boons.sh` wrapper script per character is the cleanest way to deliver this — one script per player, callable when that player is online.

### Step 13 — Bane removal at session end

When the session wraps, admin removes any traits applied as banes:
```
removetrait "<RCON_username>" "<TraitID>"
```

If `removetrait` is not exposed via vanilla RCON in B42, the fallback is to live with the trait until the next session start (acceptable — the player has rolled for it). See [RCON Trait Verification](#rcon-trait-verification).

---

## Server Configuration Changes

| File | Field | Old value | New value |
|---|---|---|---|
| `composed-apps/zomboid/server.ini` | `SpawnPoint` | `8134,11732,1` | `10776,10947,0` |
| `composed-apps/zomboid/server.ini` | `Seed` | `lcGjmaUfvnyjLHTB` | (new random 16-char) |
| `composed-apps/zomboid/Flight_Group_Alpha_PZ_Server_SandboxVars.lua` | `StartMonth` | `7` | `9` |

`ResetID` and `ServerPlayerID` will mutate during the boot cycle — capture post-boot and update memory.

---

## Boon Roll System

Each player rolls 5d20. Roll order = table order (1st roll → Table 1, 2nd → Table 2, etc.). Rolls are independent — Table 5 (banes) does NOT reference outcomes from Tables 1-3.

### Table 1 — Melee Weapon

| # | Item |
|---|---|
| 1 | Crowbar |
| 2 | Hand Axe |
| 3 | Wood Axe |
| 4 | Sledgehammer |
| 5 | Machete |
| 6 | Katana (cloth-wrapped, no sheath) |
| 7 | Aluminum Baseball Bat |
| 8 | Wooden Baseball Bat |
| 9 | Pipe Wrench |
| 10 | Hunting Knife |
| 11 | Kitchen Knife |
| 12 | Meat Cleaver |
| 13 | Long-Handle Shovel |
| 14 | Pickaxe |
| 15 | Pitchfork |
| 16 | Pool Cue |
| 17 | Golf Club (9-iron) |
| 18 | Cast Iron Frying Pan |
| 19 | Improvised Spear (sharpened broom handle) |
| 20 | Police Nightstick |

### Table 2 — Unique Clothing

| # | Item |
|---|---|
| 1 | Long fireman's coat, char marks on the back |
| 2 | Child-sized denim jacket with band patches sewn on |
| 3 | Wedding dress, hem cut off at the knee |
| 4 | Police bulletproof vest, name tag scratched off |
| 5 | UK Wildcats hoodie, dried bloodstain on the hem |
| 6 | Leather biker jacket, two sizes too big |
| 7 | Clergy collar shirt, button missing |
| 8 | Nurse's scrub top, name "M. Patel" embroidered |
| 9 | Welder's overalls, one knee patched with duct tape |
| 10 | Military fatigue jacket with sergeant's stripes |
| 11 | Halloween witch hat, surprisingly intact |
| 12 | Cheerleader skirt and jacket — Rosewood Wildcats |
| 13 | Bartender's apron, bottle openers in every pocket |
| 14 | Graduation gown, no cap |
| 15 | Tin princess crown with one fake jewel left |
| 16 | Postal worker's parka with USPS reflective stripes |
| 17 | Sweat-stained wide-brim cowboy hat |
| 18 | Full-color clown wig, somehow not gross |
| 19 | Judge's black robe, hemmed for walking |
| 20 | Mauve bridesmaid's dress, badly torn at the back |

A few entries (wedding dress, princess crown, clown wig, cheerleader uniform) may not have direct vanilla B42 item IDs. Implementation should map each to the closest available vanilla item or a mod-provided equivalent. Where no plausible mapping exists, substitute the nearest analogue and note the substitution in the per-character outcome.

### Table 3 — Gun + Ammo

| # | Item |
|---|---|
| 1 | M9 Beretta + 1 full mag (15× 9mm) |
| 2 | M1911 + 1 full mag (7× .45) |
| 3 | .38 Revolver + 6 loose rounds |
| 4 | .357 Revolver + 6 loose rounds |
| 5 | .44 Magnum + 6 loose rounds |
| 6 | Hunting Rifle (.308) + 5 rounds |
| 7 | Varmint Rifle (.22) + 30 rounds |
| 8 | M14 + 1 full mag (.308, 20 rounds) |
| 9 | M16 + 1 full mag (5.56, 30 rounds) |
| 10 | Pump Shotgun + 6 shells |
| 11 | Double-Barrel Shotgun + 4 shells |
| 12 | Sawed-Off Double-Barrel + 4 shells |
| 13 | .38 Revolver + 30 spare rounds |
| 14 | .44 Magnum + exactly 1 round |
| 15 | M9 with 2 rounds left in the mag, no spares |
| 16 | Hunting Rifle + scope + 2 rounds |
| 17 | M1911 + 3 mags, gun is rusted (low condition) |
| 18 | Pump Shotgun + 1 birdshot shell |
| 19 | .22 Pistol + 50 rounds |
| 20 | M9 + 2 full mags + leg holster |

For #17 (rusted M1911), implementation should `additem` the gun and immediately follow with an RCON command (or admin action) that reduces its durability if RCON exposes it; otherwise note in the per-character outcome that the player should treat the weapon as low-condition.

### Table 4 — XP Boost

| # | Award |
|---|---|
| 1 | +2000 Carpentry |
| 2 | +2000 Cooking, +1000 Farming |
| 3 | +2000 First Aid, +1000 Tailoring |
| 4 | +2000 Mechanics, +1000 Electrical |
| 5 | +2500 Aiming |
| 6 | +2500 Reloading |
| 7 | +2000 Sprinting, +1000 Fitness |
| 8 | +2000 Lightfoot, +1000 Sneak |
| 9 | +2500 Strength |
| 10 | +2500 Foraging (B42: PlantScavenging) |
| 11 | +2000 Trapping, +1000 Tracking |
| 12 | +2000 Fishing, +1000 Cooking |
| 13 | +2500 Long Blade |
| 14 | +2500 Long Blunt |
| 15 | +2500 Short Blade |
| 16 | +2500 Axe |
| 17 | +2500 Spear |
| 18 | +2000 Tailoring, +1000 Maintenance |
| 19 | +2000 Husbandry |
| 20 | +2000 Electrical, +1000 Metalworking |

### Table 5 — Bane

Banes are character drawbacks that follow the player into the new arc. Primary mechanism: apply a temporary negative trait via RCON `addtrait` at session start; admin removes via `removetrait` at session end. See [Bane Enforcement Strategy](#bane-enforcement-strategy) for the fallback path.

| # | Bane | Trait (primary) | Notes |
|---|---|---|---|
| 1 | Smoke inhalation — persistent cough, low fitness | Asthmatic | |
| 2 | Burn scar across the face — strangers recoil | Conspicuous | RP: NPCs/strangers recoil |
| 3 | Shoes are gone | (none) | Spawn barefoot — strip footwear via RCON `removeitem` if available |
| 4 | Chronic cough — went back for someone | Asthmatic | |
| 5 | Hands shake when raising a weapon | Cowardly | |
| 6 | Left ring finger broken in escape | Slow Healer | RP: visible splint |
| 7 | Restless sleeper — can't sleep through the night | Restless Sleeper | Replaces former referential entry (weapon melted) |
| 8 | Glass shard through the shin | Out of Shape | |
| 9 | Weak stomach — gut hates stress now | Weak Stomach | Replaces former referential entry (gun unloaded) |
| 10 | Lost hearing in one ear | Hard of Hearing | |
| 11 | All hair burned off | (none) | RP only — wear a hat (or don't) |
| 12 | Coughing blood for a week | Slow Healer + Prone to Illness | |
| 13 | Saved a stranger's child who didn't make it | (none) | RP: silent for first session, text-only |
| 14 | Bandaged feet — no shoes, pain moodle until healed | Out of Shape | Spawn barefoot |
| 15 | Memory gap — last 3 days before the fire are blank | Slow Reader | RP: can't recall any pre-fire group decision |
| 16 | Burn hole in your Table-2 clothing | (none) | Cosmetic only |
| 17 | Lost a tooth pulling yourself out | (none) | RP: pronounced lisp |
| 18 | Hidden injuries — light pain moodle, recovers | Slow Healer | |
| 19 | Came out with somebody else's blood on you | (none) | RP only |
| 20 | Whatever you brought from before is burned | (none) | RP only |

---

## Per-Character Resolved Outcomes

| Field | Step-fist (Bulbs) | Emma (Emma_M7) | Vinny | RT-541 (Artie) | Curtis |
|---|---|---|---|---|---|
| Rolls (d20×5) | 10, 9, 8, 19, 15 | 5, 16, 2, 19, 15 | 13, 5, 12, 6, 10 | 14, 17, 8, 17, 12 | 5, 7, 16, 20, 11 |
| Melee | Hunting Knife | Machete | Long-Handle Shovel | Pickaxe | Machete |
| Clothing | Welder's overalls (patched knee) | USPS postal parka | UK Wildcats hoodie (bloodstain) | Sweat-stained cowboy hat | Clergy collar shirt (button missing) |
| Gun + Ammo | M14 + 1 mag (.308×20) | M1911 + 1 mag (.45×7) | Sawed-Off DB + 4 shells | M14 + 1 mag (.308×20) | Hunting Rifle + scope + 2 rounds |
| XP | +2000 Husbandry | +2000 Husbandry | +2500 Reloading | +2500 Spear | +2000 Electrical, +1000 Metalworking |
| Bane | Memory gap | Memory gap | Hard of Hearing | Coughing blood | Hair burned off |
| Bane trait | Slow Reader | Slow Reader | Hard of Hearing | Slow Healer + Prone to Illness | (none — RP only) |

### Shared lore notes

- **Emma + Step-fist** rolled identical Table 4 (Husbandry) and identical Table 5 (memory gap). Implied shared episode: an animal they cared for together, head injuries during the same incident. Worth a brief shared scene at session opening.
- **Step-fist + RT-541** both pulled M14 rifles. Same supply cache, same hands-out moment.
- **Emma + Curtis** both rolled Machetes on Table 1. The party found a machete cache somewhere on the road.

### Shared story

**Rosewood, mid-July.** The fire station's backup generator had been leaking for a week. Nobody noticed until someone set a jerrycan down two feet too close. By the time anyone smelled it, the building was already taking the breath out of the lot.

**Step-fist** and **Emma** were out back with the animals the station kept, two goats and a coop of chickens, when the first wall came down. The blast caught both of them sideways. They woke up in a ditch a quarter-mile out with their ears ringing and a goat lead still wrapped around Step-fist's wrist. Neither remembers the next ten minutes. Step-fist had blown a knee out of his welder's overalls; someone patched it with duct tape before they were clear of town. Emma woke up under a postal parka she didn't recognize. The hunting knife on Step-fist's belt and the M1911 in Emma's coat pocket came from the same kitchen drawer at the rally point, last quick grab on the way out.

**Vinny** had been digging the generator drain pit when the gas caught. He was the closest to the tank when it lit; he came up the slope with the shovel still in his hand and one ear that hasn't worked right since. The hoodie isn't his blood. He's done a lot of the shooting since then, and a lot of the loading.

**RT-541** went back in. Twice. The second time was for somebody who didn't make it out. He's been coughing wet ever since. Two months on the road and it's still wet. The cowboy hat and pickaxe came off the same wrecked lot west of Rosewood. Somewhere north of there he and Step-fist cracked open a Guard armory and split what was left: two M14s, one mag each. He's taken to carrying a sharpened broom handle on his off-shoulder for anything that gets close.

**Curtis** was at the front of the station when the tank lit. Hair burned off clean, eyebrows, beard, all of it, and a button missing from his collar where somebody yanked him back by the throat. He's been the one keeping a field radio alive on hand-rewound parts. The hunting rifle and scope came off a hunter's blind two weeks back; two rounds for it.

On a side road off 31, south of Muldraugh, the group cracked open a footlocker in a wrecked truck and found three machetes wrapped in oilcloth. Emma took one. Curtis took one. The third went in the cart.

It's September now. They've regrouped. The plan is Louisville, the airport, and whatever's left there.

---

## Bane Enforcement Strategy

### Primary path — temporary RCON traits

PZ B42's vanilla RCON exposes (or is documented to expose) `addtrait <player> <TraitID>` and `removetrait <player> <TraitID>`. The intent is:

1. After Step 12 (boon application), run `addtrait` for each rostered character that rolled a bane with a trait mapping.
2. At session end (Step 13), the admin runs `removetrait` for the same trait.

This makes the bane felt during the session without permanently scarring the character.

### RCON Trait Verification

Before relying on this path, the implementation phase must verify with a single character on the dev server:

```
sudo docker exec zomboid-dev-server rcon -a 127.0.0.1:27016 -p <devpass> "addtrait TestUser Asthmatic"
sudo docker exec zomboid-dev-server rcon -a 127.0.0.1:27016 -p <devpass> "removetrait TestUser Asthmatic"
```

(Or whichever RCON client the dev server uses — `restore_player.sh` uses a `rcon` binary at `127.0.0.1:27015` for prod; the dev equivalent is on `:27016`.)

If both commands succeed and the trait is observable in-game, primary path is green. If either fails, fall back.

### Fallback path — mixed enforcement

If `addtrait`/`removetrait` are not exposed:
- For banes whose mechanical effect is approximated via XP, apply `addxp` with a negative value (verify negative XP works as well — if not, use a fixed `setskill` to lower the skill level, with the original level captured beforehand for end-of-session restoration).
- For "shoes gone" / "feet bandaged", `removeitem` the footwear if RCON exposes it; otherwise the player honor-removes it.
- For RP-only banes (lisp, mute, recoil, memory gap, hair, blood), no mechanical enforcement — pure player honor.

If neither path is available, document the rolled bane in the player's character notes and rely on RP only for that character's session.

---

## Validation Checklist

After Step 12 (and before Step 13's session-end cleanup), verify:

- [ ] Server is up and responsive on UDP 16261/16262 and RCON 27015.
- [ ] All five characters logged in successfully and spawned at south-Muldraugh point.
- [ ] Each character's appearance + traits + skill levels match their pre-reset state (within blob fidelity).
- [ ] Each character's inventory contains: their RCON-restored items + Table 1 melee + Table 2 clothing + Table 3 gun + Table 3 ammo.
- [ ] Each character's relevant skill received the Table 4 XP boost (visible in-game in the skill panel).
- [ ] Each character's bane trait is applied (where applicable) and visible in-game.
- [ ] In-game date reads September, year 1.
- [ ] World terrain is visibly different from the pre-reset world (new seed took effect).
- [ ] `server.ini` `ResetID` is captured and project memory updated.
- [ ] No crash logs in `docker logs zomboid-dedicated-server` since first boot.

---

## Rollback Plan

If any phase fails before Step 12 completes successfully (Step 13 is reversible since it only removes traits):

1. Stop the server: `cd /docker/nemesis-configs/composed-apps/zomboid && sudo docker compose down`
2. Delete the post-reset save dir: `sudo rm -rf /docker/game/zomboid/ZomboidConfig/Saves/Multiplayer/Flight_Group_Alpha_PZ_Server`
3. Restore from snapshot: `sudo cp -a /docker/game/zomboid/ZomboidConfig/Saves/Multiplayer/Flight_Group_Alpha_PZ_Server.preworldreset-bak /docker/game/zomboid/ZomboidConfig/Saves/Multiplayer/Flight_Group_Alpha_PZ_Server`
4. Revert `server.ini` and `Flight_Group_Alpha_PZ_Server_SandboxVars.lua` via `git checkout`.
5. Boot: `sudo docker compose up -d`

The daily backup at `/docker/game/zomboid/backups/zomboid-2026-05-08T04-00-00.tar.gz` is the secondary fallback if the snapshot is corrupted.

---

## Open Questions / Implementation Notes

- **RCON trait commands** — `addtrait`/`removetrait` availability in B42 vanilla RCON is unverified. Verification step is part of the implementation phase ([RCON Trait Verification](#rcon-trait-verification)).
- **Negative XP** — whether `addxp Skill=-N` is accepted by the B42 RCON parser is unverified. Needed for the fallback bane path.
- **Item ID resolution** — exotic clothing items (princess crown, clown wig, cheerleader uniform, wedding dress, bridesmaid dress) may not have vanilla B42 IDs. Implementation must produce the final ID mapping table before applying boons.
- **Item condition control** — Table 3 row 17 (rusted M1911) requires reducing item condition. If RCON has no condition control, the player accepts the gun as-is and treats it as low-condition by RP.
- **`removeitem` availability** — needed for the "shoes gone" / "feet bandaged" banes to strip footwear added by the blob restore. If unavailable, players honor-remove.
- **`clear_inventory.py` build** — the b42 migration design specifies this script but it does not yet exist on disk. Implementation must build it (or a targeted variant) before Step 8.
- **Position metadata stripping** — same blob-editing capability needs to either strip the saved last-position from the blob, OR the implementation chooses the post-login `teleport` fallback in Step 11. Pick one approach and document.
- **`restore_player.sh` modification** — currently runs both `addxp` and `additem`. For this reset we need an `additem`-only mode (or a sibling script). One-line edit acceptable.
- **Spawn point sanity check** — coords `10776,10947,0` (cell 35,36) should be visually verified on map.projectzomboid.com against the new seed before the player session to confirm the spawn area is on walkable terrain in the regenerated world.
