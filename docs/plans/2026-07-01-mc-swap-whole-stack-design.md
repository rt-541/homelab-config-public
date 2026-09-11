# Design: nemesis-bot `/swap` operates on whole compose stacks

**Date:** 2026-07-01
**Status:** Approved
**Scope:** `/swap` only (standalone `/start`, `/stop`, `/restart` unchanged)

## Problem

The Minecraft swap group (`mcatm9s` ATM9-Survival and `mc-deceasedcraft`
DeceasedCraft) shares host port 25567 and only one runs at a time. Switching is
driven by the Discord bot's `/swap` command, which calls the Docker SDK
`container.stop()` / `container.start()` on **only the game container** by name.

Each game's `offen/docker-volume-backup` sidecar (`<game>-backup`) has
`restart: unless-stopped` and is never touched by `/swap`. So a swapped-out
server's backup keeps running and keeps producing a nightly ~26G backup of a
frozen data volume. This filled `/var/lib/docker` (94%) via stranded temp
tarballs before it was cleaned up on 2026-07-01.

## Goal

Make each server's backup (and other sidecars) follow the active server: when a
game is swapped out, its whole stack stops; when swapped in, its whole stack
starts.

## Mechanism (SDK-native, label-based)

Every container created by compose already carries
`com.docker.compose.project` (game + `-backup` + `-autoheal` in a stack all
share it, e.g. `minecraft-deceasedcraft`). The bot already holds a full
`docker.from_env()` client (the docker socket is mounted). So the bot can act on
a whole stack purely through the SDK — no compose CLI, no mounted compose files.

New helpers in `stats.py`:

- `get_compose_project(name) -> str | None` — read the container's
  `com.docker.compose.project` label.
- `stop_stack(name) -> bool` — resolve the project, stop every running
  container with that label. Falls back to `stop_container(name)` if the
  container has no project label.
- `start_stack(name) -> bool` — resolve the project, start every non-running
  container with that label; report success by confirming the **game**
  container ends up running. Falls back to `start_container(name)`.

## Swap logic change (`bot_commands.py` `swap_cmd`)

Only the two operational calls change:

- stopping each running other: `stop_container(c)` -> `stop_stack(c)`
- starting the target: `start_container(target)` -> `start_stack(target)`

Unchanged: permission checks, the "target must exist and not already running"
precheck (read on the game container), and the abort-if-stop-fails safety
(a failed stop aborts the swap before the target is started).

## Out of scope

- `/start`, `/stop`, `/restart` stay single-container (game only). A manual
  `/stop <game>` can still leave the backup running; accepted, since the swap
  is the real dormancy path.
- Retention stays at 7 days. offen temp staging already redirected to the games
  disk (separate commit) so a failed copy can't fill `/var/lib/docker`.

## Deploy & verify

- `cd nemesis/composed-apps/nemesis-bot && docker compose up -d --build nemesis-bot`
- Verify: swap between the two MC servers; confirm the outgoing game **and** its
  `-backup` both stop, and the incoming game + its `-backup` both start.
