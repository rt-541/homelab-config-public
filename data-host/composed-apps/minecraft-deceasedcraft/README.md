# DeceasedCraft (Urban Zombie Apocalypse)

Minecraft 1.20.1 / Forge 47.4.0 server, modpack **DeceasedCraft** `5.10.16`.

- Container: `mc-deceasedcraft` — Join: `minecraft.rt-541.io:25567`
  (shares host port 25567 with ATM9-Survival — see `/swap` below; only one runs
  at a time, so the kids always use the same address regardless of world)
- Data: `/docker/game/minecraft/deceasedcraft_data` (world lives under `FeedTheBeast/world`)
- Backups: `/docker/game/minecraft/deceasedcraft_backups` (daily 04:00, 7-day retention)
- Whitelist: **shared** with ATM9-Survival via a bind-mount of
  `../minecraft-atm9-survival/allowed_users.json`. Manage with nemesis-bot
  `/mc-allowlist` — changes apply to both servers.

## Why the server pack (not AUTO_CURSEFORGE)

AUTO_CURSEFORGE only consumes the **client** manifest, which pulls client-only
mods (Oculus, Embeddium, Colorwheel(+Patcher), MrCrayfish Framework, ...) that
hard-crash a dedicated server one after another. DeceasedCraft ships a real
**server pack** with those stripped, so we use itzg manual mode:

- `TYPE=CURSEFORGE` + `CF_SERVER_MOD=/modpacks/DeceasedCraft_Server_Beta_5.10.16.zip`
- `USE_MODPACK_START_SCRIPT=true` (modern Forge launches via `run.sh`, not a fat jar)

The zip is mounted from `/docker/game/minecraft/deceasedcraft_modpacks/` (CF file
id `7623218`). To upgrade: download the new `DeceasedCraft_Server_Beta_<ver>.zip`
into that dir, update `CF_SERVER_MOD`, remove the `.curseforge-installed` marker
in the data dir, and `down`/`up`.

## IMPORTANT: settings that live in the data volume, not here

Because the pack runs from `/data/FeedTheBeast/`, itzg's `server.properties` and
memory env vars are **ignored**. These were set by hand and persist in the data
volume (lost only on a full data wipe — re-apply after one):

- `FeedTheBeast/server.properties`: `white-list=true`, `enforce-whitelist=true`,
  `enable-rcon=true`, `rcon.password=CHANGEME`, `spawn-protection=0`, custom `motd`.
  (Pack gameplay defaults kept intentionally: `allow-nether=false`,
  `generate-structures=false`, `max-players=20`.)
- `FeedTheBeast/user_jvm_args.txt`: `-Xmx10G -Xms10G` (pack default was 8G).

The whitelist *list* (`whitelist.json`) IS synced by itzg from the shared file
on every boot; only the enforcement flag above had to be set manually.

## Control

nemesis-bot manages start/stop and notifications:
- `/swap mc-deceasedcraft` — stops the other Minecraft server in the swap group
  and starts this one (the two heavy packs aren't meant to run at once).
- Discord up/down + join message post to the ATM9 webhook (`config.yml` override).

## Optional follow-up

Simple Voice Chat listens on UDP `24454` inside the container. To enable proxy
voice for remote players, add `- "24454:24454/udp"` to the ports list.
