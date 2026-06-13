import os
import re
import discord
import yaml
from discord import app_commands
from discord.ext import commands
import docker

from stats import (
    get_container_state,
    get_container_health,
    get_container_uptime,
    start_container,
    stop_container,
    restart_container,
)
from mc_admin import register_mc_commands

_docker_client = docker.from_env()
_role_map: dict[int, dict] = {}

# Roles are discovered from env vars matching ROLE_<KEY>_ID / _NAME / _CONTAINERS.
# Define them in docker-compose.yml environment section — no code changes needed to add a role.
_ROLE_KEY_PATTERN = re.compile(r"^ROLE_(.+)_ID$")


def load_roles():
    """Scan environment for ROLE_*_ID vars and build the role map."""
    global _role_map
    _role_map = {}
    for env_key, raw_id in os.environ.items():
        m = _ROLE_KEY_PATTERN.match(env_key)
        if not m or not raw_id.strip().isdigit():
            continue
        role_key = m.group(1)
        name = os.environ.get(f"ROLE_{role_key}_NAME", role_key)
        containers_raw = os.environ.get(f"ROLE_{role_key}_CONTAINERS", "")
        containers = [c.strip() for c in containers_raw.split(",") if c.strip()]
        _role_map[int(raw_id.strip())] = {
            "key": role_key,
            "name": name,
            "containers": containers,
        }


def get_allowed_containers(member: discord.Member) -> set[str] | None:
    """
    Returns the set of container names this member may act on.
    Returns None if the member has no recognised role (no access).
    Returns a set containing "*" if the member is admin (unrestricted).
    """
    allowed: set[str] = set()
    for discord_role in member.roles:
        role_cfg = _role_map.get(discord_role.id)
        if role_cfg is None:
            continue
        containers = role_cfg.get("containers", [])
        if "*" in containers:
            return {"*"}
        allowed.update(containers)
    return allowed if allowed else None


def can_access(member: discord.Member, container: str) -> bool:
    allowed = get_allowed_containers(member)
    if allowed is None:
        return False
    return "*" in allowed or container in allowed


def get_all_containers() -> list[str]:
    try:
        return sorted(c.name for c in _docker_client.containers.list(all=True))
    except Exception:
        return []


def _load_config() -> dict:
    """Load config.yml (swap_groups, overrides). Returns {} on any error."""
    try:
        with open("config.yml") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _swap_group_for(container: str, swap_groups: dict) -> list[str] | None:
    """Return the container list of the swap group containing `container`, or None."""
    for cfg in swap_groups.values():
        members = cfg.get("containers", [])
        if container in members:
            return members
    return None


def register_commands(bot: commands.Bot):
    load_roles()

    async def container_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        allowed = get_allowed_containers(interaction.user)
        if allowed is None:
            return []
        containers = get_all_containers() if "*" in allowed else sorted(allowed)
        return [
            app_commands.Choice(name=c, value=c)
            for c in containers
            if current.lower() in c.lower()
        ][:25]

    async def swap_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Offer the swap-group members this user may act on, with friendly labels."""
        allowed = get_allowed_containers(interaction.user)
        if allowed is None:
            return []
        config = _load_config()
        overrides = config.get("overrides", {})
        members: list[str] = []
        seen: set[str] = set()
        for group in config.get("swap_groups", {}).values():
            for c in group.get("containers", []):
                if c not in seen:
                    seen.add(c)
                    members.append(c)
        if "*" not in allowed:
            members = [c for c in members if c in allowed]
        choices = []
        for c in members:
            label = overrides.get(c, {}).get("display_name", c)
            display = f"{label} ({c})" if label != c else c
            if current.lower() in c.lower() or current.lower() in label.lower():
                choices.append(app_commands.Choice(name=display[:100], value=c))
        return choices[:25]

    @bot.tree.command(name="help", description="Show available commands and your accessible containers")
    async def help_cmd(interaction: discord.Interaction):
        allowed = get_allowed_containers(interaction.user)
        embed = discord.Embed(title="Nemesis Mission Systems — Commands", color=0x5865F2)

        if allowed is None:
            embed.description = "You don't have a recognised role. Contact the admin."
        else:
            if "*" in allowed:
                container_list = "All containers (admin)"
            else:
                container_list = (
                    "\n".join(f"  `{c}`" for c in sorted(allowed)) or "None assigned"
                )
            embed.add_field(name="`/status`", value="Show your containers' current state.", inline=False)
            embed.add_field(name="`/start <container>`", value=f"Start a container:\n{container_list}", inline=False)
            embed.add_field(name="`/stop <container>`", value=f"Stop a container:\n{container_list}", inline=False)
            embed.add_field(name="`/restart <container>`", value=f"Restart a container:\n{container_list}", inline=False)

            # Only advertise /swap if the user can act on a swap group's members.
            config = _load_config()
            overrides = config.get("overrides", {})
            swap_targets = []
            for group in config.get("swap_groups", {}).values():
                for c in group.get("containers", []):
                    if ("*" in allowed or c in allowed) and c not in swap_targets:
                        swap_targets.append(c)
            if swap_targets:
                target_list = "\n".join(
                    f"  `{c}`" + (f" — {overrides.get(c, {}).get('display_name')}"
                                 if overrides.get(c, {}).get("display_name") else "")
                    for c in swap_targets
                )
                embed.add_field(
                    name="`/swap <server>`",
                    value=("Stop the other server in the group and start this one "
                           f"(pick from the list):\n{target_list}"),
                    inline=False,
                )
        embed.set_footer(text="Access is role-restricted.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(name="status", description="Show current state of your containers")
    async def status_cmd(interaction: discord.Interaction):
        allowed = get_allowed_containers(interaction.user)
        if allowed is None:
            await interaction.response.send_message(
                "You don't have permission to use this command.", ephemeral=True
            )
            return

        containers = get_all_containers() if "*" in allowed else sorted(allowed)
        lines = []
        any_bad = False

        for name in containers:
            state = get_container_state(name)
            health = get_container_health(name)
            uptime = get_container_uptime(name)

            if state == "running" and health == "unhealthy":
                status, label = "[WARN]", f"Running — unhealthy | Up {uptime}"
                any_bad = True
            elif state == "running":
                status, label = "[UP]", f"Running | Up {uptime}"
            else:
                status, label = "[DOWN]", state.capitalize()
                any_bad = True

            lines.append(f"{status} **{name}**: {label}")

        embed = discord.Embed(
            title="Container Status",
            description="\n".join(lines) or "No containers found.",
            color=0xED4245 if any_bad else 0x57F287,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(name="start", description="Start a container")
    @app_commands.autocomplete(container=container_autocomplete)
    async def start_cmd(interaction: discord.Interaction, container: str):
        allowed = get_allowed_containers(interaction.user)
        if allowed is None:
            await interaction.response.send_message(
                "You don't have permission to use this command.", ephemeral=True
            )
            return

        if not can_access(interaction.user, container):
            await interaction.response.send_message(
                f"No access to `{container}`.", ephemeral=True
            )
            return

        state = get_container_state(container)
        if state == "running":
            await interaction.response.send_message(
                f"**{container}** is already running.", ephemeral=True
            )
            return

        name = interaction.user.display_name
        await interaction.response.send_message(f"{name} is starting **{container}**...")
        success = start_container(container)
        if success:
            await interaction.edit_original_response(content=f"{name} started **{container}**.")
        else:
            await interaction.edit_original_response(content=f"Failed to start **{container}**. Check logs.")

    @bot.tree.command(name="stop", description="Stop a container")
    @app_commands.autocomplete(container=container_autocomplete)
    async def stop_cmd(interaction: discord.Interaction, container: str):
        allowed = get_allowed_containers(interaction.user)
        if allowed is None:
            await interaction.response.send_message(
                "You don't have permission to use this command.", ephemeral=True
            )
            return

        if not can_access(interaction.user, container):
            await interaction.response.send_message(
                f"No access to `{container}`.", ephemeral=True
            )
            return

        state = get_container_state(container)
        if state != "running":
            await interaction.response.send_message(
                f"**{container}** is not running (state: {state}).", ephemeral=True
            )
            return

        name = interaction.user.display_name
        await interaction.response.send_message(f"{name} is stopping **{container}**...")
        success = stop_container(container)
        if success:
            await interaction.edit_original_response(content=f"{name} stopped **{container}**.")
        else:
            await interaction.edit_original_response(content=f"Failed to stop **{container}**. Check logs.")

    @bot.tree.command(name="restart", description="Restart a container")
    @app_commands.autocomplete(container=container_autocomplete)
    async def restart_cmd(interaction: discord.Interaction, container: str):
        allowed = get_allowed_containers(interaction.user)
        if allowed is None:
            await interaction.response.send_message(
                "You don't have permission to use this command.", ephemeral=True
            )
            return

        if not can_access(interaction.user, container):
            await interaction.response.send_message(
                f"No access to `{container}`.", ephemeral=True
            )
            return

        name = interaction.user.display_name
        await interaction.response.send_message(f"{name} is restarting **{container}**...")
        success = restart_container(container)
        if success:
            await interaction.edit_original_response(content=f"{name} restarted **{container}**.")
        else:
            await interaction.edit_original_response(content=f"Failed to restart **{container}**. Check logs.")

    @bot.tree.command(
        name="swap",
        description="Stop the other server in this group and start the chosen one",
    )
    @app_commands.autocomplete(target=swap_autocomplete)
    async def swap_cmd(interaction: discord.Interaction, target: str):
        allowed = get_allowed_containers(interaction.user)
        if allowed is None:
            await interaction.response.send_message(
                "You don't have permission to use this command.", ephemeral=True
            )
            return

        if not can_access(interaction.user, target):
            await interaction.response.send_message(
                f"No access to `{target}`.", ephemeral=True
            )
            return

        config = _load_config()
        group = _swap_group_for(target, config.get("swap_groups", {}))
        if group is None:
            await interaction.response.send_message(
                f"`{target}` is not part of any swap group.", ephemeral=True
            )
            return

        # Verify the target is a real, startable container BEFORE stopping the
        # other server — otherwise a swap to a missing/already-running target
        # could leave the group with nothing running.
        target_state = get_container_state(target)
        if target_state == "not-found":
            await interaction.response.send_message(
                f"`{target}` doesn't exist yet. Bring its compose stack up once "
                f"(`docker compose up -d`) before swapping to it.",
                ephemeral=True,
            )
            return
        if target_state == "running":
            await interaction.response.send_message(
                f"**{target}** is already running.", ephemeral=True
            )
            return

        name = interaction.user.display_name
        others = [c for c in group if c != target]
        running_others = [c for c in others if get_container_state(c) == "running"]

        await interaction.response.send_message(
            f"{name} is swapping to **{target}**..."
            + (f"\nStopping: {', '.join(running_others)}" if running_others else "")
        )

        failed_stop = [c for c in running_others if not stop_container(c)]
        if failed_stop:
            await interaction.edit_original_response(
                content=f"Failed to stop {', '.join(failed_stop)}. "
                f"Aborting swap — **{target}** not started."
            )
            return

        if start_container(target):
            await interaction.edit_original_response(
                content=f"{name} swapped to **{target}**."
                + (f" (stopped {', '.join(running_others)})" if running_others else "")
            )
        else:
            await interaction.edit_original_response(
                content=f"Failed to start **{target}**. Check logs."
            )

    register_mc_commands(bot)
