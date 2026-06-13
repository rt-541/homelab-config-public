import json
import os
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands



# ── Paths ──────────────────────────────────────────────────────────────────

def _allowlist_path() -> str:
    return os.environ.get("MC_ALLOWLIST_PATH", "/mc/allowed_users.json")


def _ops_path() -> str:
    return os.environ.get("MC_OPS_PATH", "/mc/ops.json")


# ── UUID utilities ─────────────────────────────────────────────────────────

def normalize_uuid(raw: str) -> str:
    """Return UUID in lowercase dashed format regardless of input format."""
    clean = raw.replace("-", "").lower()
    if len(clean) != 32 or not all(c in "0123456789abcdef" for c in clean):
        raise ValueError(f"Invalid UUID: {raw!r}")
    return f"{clean[0:8]}-{clean[8:12]}-{clean[12:16]}-{clean[16:20]}-{clean[20:32]}"


# ── File I/O ───────────────────────────────────────────────────────────────

def read_json_file(path: str) -> list:
    """Read JSON list from path. Returns [] if file does not exist."""
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def write_json_file(path: str, data: list) -> None:
    """Write data as JSON to path.

    Uses direct in-place write because the files are bind-mounted into the
    container as individual file mounts, which prevents atomic rename (os.replace
    raises EBUSY on bind-mount points). The bot is single-threaded (asyncio) so
    concurrent writes are not a concern.
    """
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ── Mojang API ─────────────────────────────────────────────────────────────

async def lookup_player_name(uuid: str) -> str:
    """Fetch Minecraft player name from Mojang API by UUID.

    Raises ValueError if the player does not exist.
    Raises RuntimeError on unexpected API errors or if unreachable.
    """
    no_dashes = uuid.replace("-", "")
    url = f"https://sessionserver.mojang.com/session/minecraft/profile/{no_dashes}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status in (204, 404):
                raise ValueError(f"UUID {uuid!r} not found on Mojang servers.")
            if resp.status != 200:
                raise RuntimeError(f"Mojang API error: HTTP {resp.status}")
            data = await resp.json()
            return data["name"]


# ── Allowlist operations ───────────────────────────────────────────────────

def allowlist_add(uuid: str, name: str) -> bool:
    """Add player to allowlist. Returns False if already present."""
    path = _allowlist_path()
    entries = read_json_file(path)
    if any(e["uuid"] == uuid for e in entries):
        return False
    entries.append({"uuid": uuid, "name": name})
    write_json_file(path, entries)
    return True


def allowlist_remove(uuid: str) -> Optional[str]:
    """Remove player by UUID. Returns player name if removed, None if not found."""
    path = _allowlist_path()
    entries = read_json_file(path)
    for i, e in enumerate(entries):
        if e["uuid"] == uuid:
            removed = entries.pop(i)
            write_json_file(path, entries)
            return removed["name"]
    return None


def allowlist_list() -> list[dict]:
    """Return all allowlist entries."""
    return read_json_file(_allowlist_path())


# ── Ops operations ─────────────────────────────────────────────────────────

def ops_add(uuid: str, name: str) -> bool:
    """Add player to ops (level 4). Returns False if already present."""
    path = _ops_path()
    entries = read_json_file(path)
    if any(e["uuid"] == uuid for e in entries):
        return False
    entries.append({"uuid": uuid, "name": name, "level": 4, "bypassesPlayerLimit": False})
    write_json_file(path, entries)
    return True


def ops_remove(uuid: str) -> Optional[str]:
    """Remove op by UUID. Returns player name if removed, None if not found."""
    path = _ops_path()
    entries = read_json_file(path)
    for i, e in enumerate(entries):
        if e["uuid"] == uuid:
            removed = entries.pop(i)
            write_json_file(path, entries)
            return removed["name"]
    return None


def ops_list() -> list[dict]:
    """Return all ops entries."""
    return read_json_file(_ops_path())


# ── Slash commands ─────────────────────────────────────────────────────────

def register_mc_commands(bot: commands.Bot) -> None:
    """Register /mc-allowlist and /mc-ops command groups on the bot tree."""
    # Lazy import avoids circular import: bot_commands imports mc_admin,
    # mc_admin imports can_access only when register_mc_commands() is called.
    from bot_commands import can_access

    mc_allowlist = app_commands.Group(
        name="mc-allowlist", description="Manage Minecraft server allowlist"
    )
    mc_ops_grp = app_commands.Group(
        name="mc-ops", description="Manage Minecraft server ops"
    )

    # ── /mc-allowlist add ──────────────────────────────────────────────────
    @mc_allowlist.command(name="add", description="Add a player to the allowlist by UUID")
    async def allowlist_add_cmd(interaction: discord.Interaction, uuid: str):
        if not can_access(interaction.user, "mcatm9s"):
            await interaction.response.send_message("You don't have permission.", ephemeral=True)
            return
        try:
            norm = normalize_uuid(uuid)
        except ValueError:
            await interaction.response.send_message(f"`{uuid}` is not a valid UUID.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            name = await lookup_player_name(norm)
        except ValueError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        except RuntimeError as e:
            await interaction.followup.send(f"Mojang API unavailable: {e}", ephemeral=True)
            return
        if not allowlist_add(norm, name):
            await interaction.followup.send(
                f"**{name}** (`{norm}`) is already on the allowlist.", ephemeral=True
            )
            return
        await interaction.followup.send(
            f"{interaction.user.display_name} added **{name}** (`{norm}`) to the allowlist."
        )

    # ── /mc-allowlist remove ───────────────────────────────────────────────
    @mc_allowlist.command(name="remove", description="Remove a player from the allowlist by UUID")
    async def allowlist_remove_cmd(interaction: discord.Interaction, uuid: str):
        if not can_access(interaction.user, "mcatm9s"):
            await interaction.response.send_message("You don't have permission.", ephemeral=True)
            return
        try:
            norm = normalize_uuid(uuid)
        except ValueError:
            await interaction.response.send_message(f"`{uuid}` is not a valid UUID.", ephemeral=True)
            return
        removed_name = allowlist_remove(norm)
        if removed_name is None:
            await interaction.response.send_message(
                f"UUID `{norm}` was not found on the allowlist.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"{interaction.user.display_name} removed **{removed_name}** (`{norm}`) from the allowlist."
        )

    # ── /mc-allowlist list ─────────────────────────────────────────────────
    @mc_allowlist.command(name="list", description="Show all players on the allowlist")
    async def allowlist_list_cmd(interaction: discord.Interaction):
        if not can_access(interaction.user, "mcatm9s"):
            await interaction.response.send_message("You don't have permission.", ephemeral=True)
            return
        entries = allowlist_list()
        if not entries:
            await interaction.response.send_message("The allowlist is empty.", ephemeral=True)
            return
        lines = [f"`{e['uuid']}` — **{e['name']}**" for e in entries]
        embed = discord.Embed(
            title=f"Minecraft Allowlist ({len(entries)} players)",
            description="\n".join(lines),
            color=0x57F287,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /mc-ops add ────────────────────────────────────────────────────────
    @mc_ops_grp.command(name="add", description="Add a player to ops by UUID")
    async def ops_add_cmd(interaction: discord.Interaction, uuid: str):
        if not can_access(interaction.user, "mcatm9s"):
            await interaction.response.send_message("You don't have permission.", ephemeral=True)
            return
        try:
            norm = normalize_uuid(uuid)
        except ValueError:
            await interaction.response.send_message(f"`{uuid}` is not a valid UUID.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            name = await lookup_player_name(norm)
        except ValueError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        except RuntimeError as e:
            await interaction.followup.send(f"Mojang API unavailable: {e}", ephemeral=True)
            return
        if not ops_add(norm, name):
            await interaction.followup.send(
                f"**{name}** (`{norm}`) is already an op.", ephemeral=True
            )
            return
        await interaction.followup.send(
            f"{interaction.user.display_name} added **{name}** (`{norm}`) to ops."
            f"\n> Changes take effect after the server is restarted (`/restart mcatm9s`)."
        )

    # ── /mc-ops remove ─────────────────────────────────────────────────────
    @mc_ops_grp.command(name="remove", description="Remove a player from ops by UUID")
    async def ops_remove_cmd(interaction: discord.Interaction, uuid: str):
        if not can_access(interaction.user, "mcatm9s"):
            await interaction.response.send_message("You don't have permission.", ephemeral=True)
            return
        try:
            norm = normalize_uuid(uuid)
        except ValueError:
            await interaction.response.send_message(f"`{uuid}` is not a valid UUID.", ephemeral=True)
            return
        removed_name = ops_remove(norm)
        if removed_name is None:
            await interaction.response.send_message(
                f"UUID `{norm}` was not found in ops.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"{interaction.user.display_name} removed **{removed_name}** (`{norm}`) from ops."
            f"\n> Changes take effect after the server is restarted (`/restart mcatm9s`)."
        )

    # ── /mc-ops list ───────────────────────────────────────────────────────
    @mc_ops_grp.command(name="list", description="Show all current ops")
    async def ops_list_cmd(interaction: discord.Interaction):
        if not can_access(interaction.user, "mcatm9s"):
            await interaction.response.send_message("You don't have permission.", ephemeral=True)
            return
        entries = ops_list()
        if not entries:
            await interaction.response.send_message("The ops list is empty.", ephemeral=True)
            return
        lines = [f"`{e['uuid']}` — **{e['name']}** (level {e.get('level', 4)})" for e in entries]
        embed = discord.Embed(
            title=f"Minecraft Ops ({len(entries)} operators)",
            description="\n".join(lines),
            color=0xFEE75C,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    bot.tree.add_command(mc_allowlist)
    bot.tree.add_command(mc_ops_grp)
