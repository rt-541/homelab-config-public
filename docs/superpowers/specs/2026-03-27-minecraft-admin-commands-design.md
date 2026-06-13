# Minecraft Admin Commands — Design Spec

**Date:** 2026-03-27
**Status:** Approved

---

## Summary

Add slash commands to the Nemesis Discord bot allowing users with the `Minecraft Admin` role (or existing `Admin` role) to add and remove player UUIDs from two Minecraft server files: the allowlist (`allowed_users.json`) and the ops list (`ops.json`).

---

## Context

The Minecraft ATM9 Survival server (`mcatm9s`) uses two JSON files to control player access and permissions:

- `allowed_users.json` — who is allowed to connect (format: `[{"uuid": "...", "name": "..."}]`)
- `ops.json` — who has operator privileges (format: `[{"uuid": "...", "name": "...", "level": 4, "bypassesPlayerLimit": false}]`)

Currently these files must be edited manually on disk. The bot will expose Discord slash commands to manage them.

---

## Access Control

A new Discord role `Minecraft Admin` is created in the server. Two environment variables are added:

- `ROLE_MCADMIN_ID` in `.env` — the Discord role ID
- `ROLE_MCADMIN_NAME: "Minecraft Admin"` in `docker-compose.yml`
- `ROLE_MCADMIN_CONTAINERS: "mcatm9s"` in `docker-compose.yml` (grants existing `/start`, `/stop`, `/restart` access to the Minecraft container)

The MC admin commands check that the caller has either the `ROLE_ADMIN` or `ROLE_MCADMIN` role using the existing `_role_map` system.

---

## Commands

Six new slash commands in a new module `mc_admin.py`, registered alongside existing commands in `bot_commands.py`:

| Command | Description |
|---|---|
| `/mc-allowlist add <uuid>` | Add player to `allowed_users.json`. Name auto-fetched from Mojang API. |
| `/mc-allowlist remove <uuid>` | Remove player by UUID from `allowed_users.json`. |
| `/mc-allowlist list` | Display all players on the allowlist. |
| `/mc-ops add <uuid>` | Add player to `ops.json` (level 4, bypassesPlayerLimit false). Name auto-fetched from Mojang API. |
| `/mc-ops remove <uuid>` | Remove player by UUID from `ops.json`. |
| `/mc-ops list` | Display all current ops. |

**Response visibility:**
- `add` and `remove` commands: public response (visible to channel) so changes are auditable
- `list` commands: ephemeral (only visible to caller)

**Ops note:** A reminder is included in `add`/`remove` ops responses that changes take effect after server restart.

---

## Mojang API Integration

Player names are resolved from UUIDs via:

```
GET https://sessionserver.mojang.com/session/minecraft/profile/<uuid-no-dashes>
```

Response: `{"id": "...", "name": "PlayerName"}`

- If the UUID is invalid or the player does not exist: command fails with a clear error message, no file is written.
- If Mojang API is unreachable: command fails rather than writing a nameless entry.
- UUID formatting: dashes are stripped before calling the API; the UUID is stored with dashes in the JSON files.
- UUID input normalization: regardless of whether the user provides the UUID with or without dashes, it is normalized to the standard dashed format (`xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`) before being written to disk.

---

## File Access

Two files are mounted into the bot container (read-write) via `docker-compose.yml`:

```yaml
- /docker/nemesis-configs/composed-apps/minecraft-atm9-survival/allowed_users.json:/mc/allowed_users.json
- /docker/game/minecraft/minecraftatm9s_data/ops.json:/mc/ops.json
```

Inside the bot, paths are configured via environment variables:

```
MC_ALLOWLIST_PATH=/mc/allowed_users.json
MC_OPS_PATH=/mc/ops.json
```

**Write safety:** All writes use an atomic pattern — write to a temp file in the same directory (`/mc/`), then `os.replace()` to swap it in. This prevents corrupt JSON if the process crashes mid-write. Temp files must stay in `/mc/` (same mount) to satisfy the same-filesystem requirement for atomic rename.

**Missing file handling:** If a file does not exist on first read (e.g. `ops.json` is absent), treat it as an empty list `[]` and create the file on first write.

---

## New Files

- `composed-apps/nemesis-bot/mc_admin.py` — command handlers and file I/O logic

## Modified Files

- `composed-apps/nemesis-bot/bot_commands.py` — import and register `mc_admin` commands
- `composed-apps/nemesis-bot/docker-compose.yml` — add volume mounts and `ROLE_MCADMIN_*` env vars; add `MC_ALLOWLIST_PATH` and `MC_OPS_PATH`
- `composed-apps/nemesis-bot/.env.example` — add `ROLE_MCADMIN_ID`
- `composed-apps/minecraft-atm9-survival/allowed_users.json` — no structural changes, managed at runtime

---

## Out of Scope

- RCON integration (live reload without restart)
- Configurable op level (always level 4)
- Ban list management
- Whitelist enable/disable toggle
