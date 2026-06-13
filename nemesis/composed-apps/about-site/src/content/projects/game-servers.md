---
title: "Game servers for friends & family"
order: 2
status: active
summary: "A rotating fleet of dedicated game servers, run for a small community of friends and family."
more:
  href: "/gaming"
  label: "see the gaming page"
---

Whatever the group is playing that month gets a server. Each one is a Docker Compose service with its own resource limits, scheduled backups, and Discord notifications when it starts or stops. The goal is that a server is up before anyone asks for it and recoverable when something goes wrong, without me having to babysit it.

**Running now**

- Project Zomboid (production, plus a dev instance for testing mods)
- Minecraft: All the Mods 9 Survival

**In the rotation** (configured and ready, spun up on demand)

- Valheim
- Palworld
- V Rising
- Enshrouded
- Factorio
- Core Keeper
- Abiotic Factor
- Minecraft: vanilla, All the Mods 9 Creative, and Valhelsia

The deeper automation lives in companion projects: RCON tooling and world-reset scripts for Zomboid, and a Discord bot for status and remote admin.

See the full roster and how to join on the [gaming page](/gaming).
