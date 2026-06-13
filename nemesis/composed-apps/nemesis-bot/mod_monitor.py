import asyncio
import json
import logging
import os
import re
import aiohttp
import yaml
import docker

from notifier import send_webhook

logger = logging.getLogger(__name__)
_docker_client = docker.from_env()
STATE_DIR = "/state"


def _load_config():
    with open("config.yml") as f:
        return yaml.safe_load(f)


def parse_acf_timestamps(acf_path: str) -> dict:
    """Parse WorkshopItemsInstalled from a Valve ACF file. Returns {mod_id: timeupdated}."""
    result = {}
    try:
        with open(acf_path) as f:
            content = f.read()
    except FileNotFoundError:
        return result

    in_section = False
    depth = 0
    current_id = None

    for line in content.splitlines():
        stripped = line.strip()
        if not in_section:
            if '"WorkshopItemsInstalled"' in stripped:
                in_section = True
            continue
        if stripped == "{":
            depth += 1
        elif stripped == "}":
            depth -= 1
            if depth <= 0:
                break
        elif depth == 1:
            m = re.match(r'^"(\d+)"$', stripped)
            if m:
                current_id = m.group(1)
        elif depth == 2 and current_id:
            m = re.match(r'^"timeupdated"\s+"(\d+)"$', stripped)
            if m:
                result[current_id] = int(m.group(1))

    return result


async def query_steam_api(mod_ids: list) -> dict:
    """Query Steam Workshop API. Returns {publishedfileid: time_updated}."""
    if not mod_ids:
        return {}
    data = {"itemcount": len(mod_ids)}
    for i, mid in enumerate(mod_ids):
        data[f"publishedfileids[{i}]"] = mid

    url = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, data=data, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    return {}
                body = await resp.json(content_type=None)
                details = body.get("response", {}).get("publishedfiledetails", [])
                return {d["publishedfileid"]: d.get("time_updated", 0) for d in details}
    except Exception as e:
        logger.error("[mod-monitor] Steam API error: %s", e)
        return {}


async def check_server(server: str, config: dict):
    srv = config.get("mod_monitor", {}).get("servers", {}).get(server, {})
    acf_path = srv.get("acf_path", "")
    if not acf_path or not os.path.isfile(acf_path):
        logger.error("[mod-monitor] ACF not found for %s: %s", server, acf_path)
        return

    local_state = parse_acf_timestamps(acf_path)
    mod_ids = list(local_state.keys())
    if not mod_ids:
        logger.info("[mod-monitor] %s: No mods found", server)
        return

    logger.info("[mod-monitor] %s: Checking %d mods", server, len(mod_ids))
    upstream_state = await query_steam_api(mod_ids)
    if not upstream_state:
        logger.error("[mod-monitor] %s: Steam API returned nothing", server)
        return

    stale = {
        mid: upstream_state[mid]
        for mid in mod_ids
        if mid in upstream_state and upstream_state[mid] > local_state.get(mid, 0)
    }

    if not stale:
        logger.info("[mod-monitor] %s: All mods up to date", server)
        state_file = os.path.join(STATE_DIR, f"{server}-stale.json")
        if os.path.exists(state_file):
            os.remove(state_file)
        return

    # Load notification state to avoid duplicate alerts
    state_file = os.path.join(STATE_DIR, f"{server}-stale.json")
    os.makedirs(STATE_DIR, exist_ok=True)
    notified = {}
    if os.path.exists(state_file):
        with open(state_file) as f:
            notified = json.load(f)

    new_stale = {
        mid: ts
        for mid, ts in stale.items()
        if str(notified.get(mid, 0)) != str(ts)
    }

    new_notified = {mid: ts for mid, ts in stale.items()}
    with open(state_file, "w") as f:
        json.dump(new_notified, f)

    if not new_stale:
        logger.info(
            "[mod-monitor] %s: %d stale mod(s), already notified", server, len(stale)
        )
        return

    display_name = srv.get("display_name", server)
    auto_restart = srv.get("auto_restart", False)
    container_name = srv.get("container_name", "")
    username = srv.get("username", "Mod Monitor")
    footer = srv.get("footer", "Mod Monitor")

    webhook_env = srv.get("webhook_env", "")
    webhook_url = os.environ.get(webhook_env, "") if webhook_env else ""
    if not webhook_url:
        webhook_url = os.environ.get("DEFAULT_WEBHOOK_URL", "")

    mod_lines = []
    for mid, upstream_ts in stale.items():
        local_ts = local_state.get(mid, 0)
        age_hours = (upstream_ts - local_ts) // 3600
        new_marker = " (new)" if mid in new_stale else ""
        mod_lines.append(
            f"• [{mid}](https://steamcommunity.com/sharedfiles/filedetails/?id={mid})"
            f" — {age_hours}h behind{new_marker}"
        )

    mod_list_str = "\n".join(mod_lines)
    total = len(stale)
    new_count = len(new_stale)

    if auto_restart and container_name:
        title = f"{display_name} — Stale Mods Detected"
        desc = (
            f"{total} mod(s) behind Steam Workshop ({new_count} new):\n{mod_list_str}"
            "\n\nServer restarting to update..."
        )
        await send_webhook(webhook_url, title, 16753920, desc, username, footer)

        try:
            c = _docker_client.containers.get(container_name)
            c.restart(timeout=30)
            if os.path.exists(state_file):
                os.remove(state_file)
            await send_webhook(
                webhook_url,
                f"{display_name} — Restarted",
                65280,
                "Server restarted to pick up mod updates.",
                username,
                footer,
            )
        except Exception as e:
            await send_webhook(
                webhook_url,
                f"{display_name} — Restart Failed",
                16711680,
                f"Auto-restart failed: {e}",
                username,
                footer,
            )
    else:
        title = f"{display_name} — Stale Mods Detected"
        desc = (
            f"{total} mod(s) behind Steam Workshop ({new_count} new):\n{mod_list_str}"
            "\n\nManual restart required."
        )
        await send_webhook(webhook_url, title, 16753920, desc, username, footer)


async def run_all_servers():
    config = _load_config()
    servers = config.get("mod_monitor", {}).get("servers", {})
    for server, srv_config in servers.items():
        if srv_config.get("enabled", True):
            try:
                await check_server(server, config)
            except Exception as e:
                logger.error("[mod-monitor] Error checking %s: %s", server, e)
