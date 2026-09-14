# Nemesis Bot — Combined Discord Bot Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** A single Python Discord bot that replaces the shell-based container-monitor entirely — handling outbound alerts (Docker events, daily status, mod updates) AND inbound self-service commands (!status, !restart, !help).

**Architecture:** New composed-app `nemesis-bot` replaces `container-monitor`. Uses discord.py for the bot framework, the `docker` Python SDK for container interaction, and discord.py's built-in task loops for scheduling. Docker events are streamed in an asyncio thread executor to avoid blocking. Webhooks remain the outbound channel (same Discord setup as before). Bot token handles inbound commands.

**Tech Stack:** Python 3.12, discord.py 2.x, docker SDK (Python), aiohttp, PyYAML, Alpine Docker image

---

## What This Replaces

| Old file | New equivalent |
|----------|---------------|
| `container-monitor/monitor.sh` | `nemesis-bot/event_monitor.py` |
| `container-monitor/lib/discord.sh` | `nemesis-bot/notifier.py` |
| `container-monitor/lib/stats.sh` | `nemesis-bot/stats.py` |
| `container-monitor/status-report.sh` | `nemesis-bot/status_report.py` |
| `container-monitor/mod-monitor.sh` | `nemesis-bot/mod_monitor.py` |
| *(new)* | `nemesis-bot/bot_commands.py` |
| `container-monitor/monitor.sh` (main) | `nemesis-bot/main.py` |

---

## Task 1: Scaffold the directory and Dockerfile

**Files:**
- Create: `nemesis-bot/Dockerfile`
- Create: `nemesis-bot/requirements.txt`

**Step 1: Create directory**

```bash
mkdir -p /docker/homelab-config/data-host/composed-apps/nemesis-bot/state
```

**Step 2: Write Dockerfile**

```dockerfile
FROM python:3.12-alpine

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py .
COPY config.yml .

CMD ["python", "main.py"]
```

**Step 3: Write requirements.txt**

```
discord.py==2.3.2
docker==7.1.0
aiohttp==3.9.5
PyYAML==6.0.2
```

**Step 4: Commit**

```bash
git add nemesis-bot/
git commit -m "feat: scaffold nemesis-bot container"
```

---

## Task 2: Write config.yml

Combines container-monitor config + bot config. Copy values from the existing `container-monitor/config.yml`.

**Files:**
- Create: `nemesis-bot/config.yml`

```yaml
bot:
  prefix: "!"
  status_message: "Nemesis Server | !help"

defaults:
  username: "Container Monitor"
  footer: "Nemesis Server"
  notify_on_start: true
  notify_on_stop: true
  notify_on_crash: true
  start_emoji: "🟢"
  stop_emoji: "🔴"
  crash_emoji: "⚠️"
  color_start: 65280
  color_stop: 16711680
  color_crash: 16776960

status_report:
  enabled: true
  schedule_hour: 8       # 8 AM daily
  include_stopped: true
  include_resource_usage: true
  include_uptime: true
  include_health: true

exclude:
  - container-monitor
  - nemesis-bot

# Role-based access control
# Each role has an env var holding the Discord role ID, and a container allowlist.
# "*" in containers means unrestricted (admin).
# Add containers to NF-613 and WB-347 as new game servers come online.
roles:
  QZ-481:
    name: "Admin"
    env: "ROLE_ID_QZ481"
    containers: ["*"]
  VR-156:
    name: "Plex"
    env: "ROLE_ID_VR156"
    containers:
      - plex-nfs
      - qbittorrent
      - overseerr
      - sonarr
      - radarr
  TK-829:
    name: "Zomboid"
    env: "ROLE_ID_TK829"
    containers:
      - zomboid-dedicated-server
      - zomboid-dev-server
  WB-347:
    name: "Minecraft"
    env: "ROLE_ID_WB347"
    containers:
      - mcatm9s
      # add more minecraft containers here as needed
  NF-613:
    name: "Other Games"
    env: "ROLE_ID_NF613"
    containers: []   # scaffold — populate as new game servers are added

mod_monitor:
  servers:
    zomboid-dev:
      enabled: true
      schedule_hour: 0    # every 6 hours — set via schedule_interval_hours below
      schedule_interval_hours: 6
      container_name: zomboid-dev-server
      acf_path: /acf/zomboid-dev/appworkshop_108600.acf
      auto_restart: true
      display_name: "Zomboid Dev Server"
      webhook_env: "ZOMBOID_WEBHOOK_URL"
      username: "ZP-742"
      footer: "Zomboid Dev — Mod Monitor"
    zomboid-prod:
      enabled: true
      schedule_interval_hours: 24
      container_name: zomboid-dedicated-server
      acf_path: /acf/zomboid-prod/appworkshop_108600.acf
      auto_restart: false
      display_name: "Flight Group Alpha PZ Server"
      webhook_env: "ZOMBOID_WEBHOOK_URL"
      username: "ZP-742"
      footer: "Zomboid Prod — Mod Monitor"

overrides:
  zomboid-dedicated-server:
    display_name: "Flight Group Alpha PZ Server"
    username: "ZP-742"
    footer: "Flight Group Alpha PZ Server"
    webhook_env: "ZOMBOID_WEBHOOK_URL"
    start_message: "The zombie apocalypse awaits!"
  mcatm9s:
    display_name: "ATM9 Survival Server"
    username: "ATM9 Survival"
    footer: "ATM9 Survival Server"
    webhook_env: "ATM9S_WEBHOOK_URL"
    start_message: "Connect: minecraft.rt-541.io:25567"
```

**Commit:**

```bash
git add nemesis-bot/config.yml
git commit -m "feat: add nemesis-bot config"
```

---

## Task 3: Write notifier.py (Discord webhook sender)

Replaces `lib/discord.sh`.

**Files:**
- Create: `nemesis-bot/notifier.py`

```python
import aiohttp
import logging

logger = logging.getLogger(__name__)


async def send_webhook(
    webhook_url: str,
    title: str,
    color: int,
    description: str = "",
    username: str = "Container Monitor",
    footer: str = "Nemesis Server",
) -> bool:
    """Send an embed to a Discord webhook. Returns True on success."""
    if not webhook_url:
        logger.error("send_webhook called with no URL")
        return False

    embed: dict = {"title": title, "color": color}
    if description:
        embed["description"] = description
    if footer:
        embed["footer"] = {"text": footer}

    payload = {"username": username, "embeds": [embed]}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload) as resp:
                if resp.status in (200, 204):
                    return True
                body = await resp.text()
                logger.error("Webhook failed %s: %s", resp.status, body)
                return False
    except Exception as e:
        logger.error("Webhook error: %s", e)
        return False
```

**Commit:**

```bash
git add nemesis-bot/notifier.py
git commit -m "feat: add Discord webhook notifier"
```

---

## Task 4: Write stats.py (container inspection helpers)

Replaces `lib/stats.sh`.

**Files:**
- Create: `nemesis-bot/stats.py`

```python
import docker
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
_client = docker.from_env()


def get_container_state(name: str) -> str:
    try:
        c = _client.containers.get(name)
        return c.status
    except docker.errors.NotFound:
        return "not-found"
    except Exception as e:
        logger.error("get_container_state(%s): %s", name, e)
        return "error"


def get_container_health(name: str) -> str:
    try:
        c = _client.containers.get(name)
        health = c.attrs.get("State", {}).get("Health", {})
        return health.get("Status", "no-healthcheck") if health else "no-healthcheck"
    except docker.errors.NotFound:
        return "not-found"
    except Exception as e:
        logger.error("get_container_health(%s): %s", name, e)
        return "error"


def get_container_uptime(name: str) -> str:
    try:
        c = _client.containers.get(name)
        started_at = c.attrs.get("State", {}).get("StartedAt", "")
        if not started_at or started_at.startswith("0001"):
            return "N/A"
        # Parse ISO8601 timestamp (trim nanoseconds to microseconds)
        ts = started_at[:26] + "Z"
        started = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        diff = datetime.now(timezone.utc) - started
        total_seconds = int(diff.total_seconds())
        if total_seconds < 0:
            return "N/A"
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60
        if days > 0:
            return f"{days}d {hours}h"
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"
    except Exception as e:
        logger.error("get_container_uptime(%s): %s", name, e)
        return "N/A"


def get_container_stats(name: str) -> dict:
    """Returns dict with cpu_pct and mem_usage strings."""
    try:
        c = _client.containers.get(name)
        raw = c.stats(stream=False)
        cpu_delta = raw["cpu_stats"]["cpu_usage"]["total_usage"] - \
                    raw["precpu_stats"]["cpu_usage"]["total_usage"]
        system_delta = raw["cpu_stats"]["system_cpu_usage"] - \
                       raw["precpu_stats"]["system_cpu_usage"]
        num_cpus = raw["cpu_stats"].get("online_cpus") or \
                   len(raw["cpu_stats"]["cpu_usage"].get("percpu_usage", [1]))
        cpu_pct = (cpu_delta / system_delta) * num_cpus * 100.0 if system_delta > 0 else 0.0

        mem_usage = raw["memory_stats"].get("usage", 0)
        mem_limit = raw["memory_stats"].get("limit", 1)
        mem_mb = mem_usage / (1024 * 1024)
        mem_pct = (mem_usage / mem_limit) * 100.0

        return {
            "cpu_pct": f"{cpu_pct:.1f}%",
            "mem_usage": f"{mem_mb:.0f}MiB ({mem_pct:.1f}%)",
        }
    except Exception as e:
        logger.error("get_container_stats(%s): %s", name, e)
        return {"cpu_pct": "N/A", "mem_usage": "N/A"}


def restart_container(name: str) -> bool:
    try:
        c = _client.containers.get(name)
        c.restart(timeout=30)
        return True
    except Exception as e:
        logger.error("restart_container(%s): %s", name, e)
        return False
```

**Commit:**

```bash
git add nemesis-bot/stats.py
git commit -m "feat: add container stats helpers"
```

---

## Task 5: Write event_monitor.py (Docker event watcher)

Replaces the main event loop in `monitor.sh`. Runs in a thread executor so it doesn't block the asyncio event loop.

**Files:**
- Create: `nemesis-bot/event_monitor.py`

```python
import asyncio
import docker
import logging
import os
import yaml

logger = logging.getLogger(__name__)
_docker_client = docker.from_env()


def _load_config():
    with open("config.yml") as f:
        return yaml.safe_load(f)


def _get_config_value(config: dict, name: str, key: str):
    overrides = config.get("overrides", {})
    if name in overrides and key in overrides[name]:
        return overrides[name][key]
    return config.get("defaults", {}).get(key)


def _get_webhook_url(config: dict, name: str) -> str:
    overrides = config.get("overrides", {})
    env_var = overrides.get(name, {}).get("webhook_env", "")
    if env_var:
        val = os.environ.get(env_var, "")
        if val:
            return val
    webhook = overrides.get(name, {}).get("webhook_url", "")
    if webhook:
        return webhook
    return os.environ.get("DEFAULT_WEBHOOK_URL", "")


def _is_excluded(config: dict, name: str) -> bool:
    return name in config.get("exclude", [])


async def _notify(config: dict, name: str, action: str, notifier_fn):
    """Build and send a Discord notification for a container event."""
    from notifier import send_webhook

    display_name = _get_config_value(config, name, "display_name") or name
    webhook_url = _get_webhook_url(config, name)
    username = _get_config_value(config, name, "username") or "Container Monitor"
    footer = _get_config_value(config, name, "footer") or "Nemesis Server"

    if action == "start":
        emoji = _get_config_value(config, name, "start_emoji") or "🟢"
        color = _get_config_value(config, name, "color_start") or 65280
        title = f"{emoji} {display_name} Started"
        desc = _get_config_value(config, name, "start_message") or ""
    elif action in ("die", "kill"):
        try:
            c = _docker_client.containers.get(name)
            exit_code = c.attrs.get("State", {}).get("ExitCode", -1)
        except Exception:
            exit_code = -1

        if exit_code == 0:
            emoji = _get_config_value(config, name, "stop_emoji") or "🔴"
            color = _get_config_value(config, name, "color_stop") or 16711680
            title = f"{emoji} {display_name} Stopped"
            desc = _get_config_value(config, name, "stop_message") or ""
        else:
            emoji = _get_config_value(config, name, "crash_emoji") or "⚠️"
            color = _get_config_value(config, name, "color_crash") or 16776960
            title = f"{emoji} {display_name} Crashed"
            desc = f"Exit code: {exit_code}"
    else:
        return  # Ignore unhandled events

    logger.info("[event] %s", title)
    await send_webhook(webhook_url, title, color, desc, username, footer)


async def watch_events(loop: asyncio.AbstractEventLoop):
    """Stream Docker events and fire notifications. Runs forever, restarts on error."""
    config = _load_config()

    def _stream():
        for event in _docker_client.events(
            decode=True,
            filters={"type": "container", "event": ["start", "die", "kill"]},
        ):
            name = event.get("Actor", {}).get("Attributes", {}).get("name", "")
            action = event.get("Action", "")
            if not name or not action:
                continue
            if _is_excluded(config, name):
                logger.debug("[event] Skipping excluded: %s (%s)", name, action)
                continue
            asyncio.run_coroutine_threadsafe(_notify(config, name, action, None), loop)

    while True:
        try:
            logger.info("[event] Starting Docker event stream...")
            await loop.run_in_executor(None, _stream)
        except Exception as e:
            logger.error("[event] Stream error, restarting in 5s: %s", e)
            await asyncio.sleep(5)
```

**Commit:**

```bash
git add nemesis-bot/event_monitor.py
git commit -m "feat: add Docker event watcher"
```

---

## Task 6: Write status_report.py (daily status report)

Replaces `status-report.sh`.

**Files:**
- Create: `nemesis-bot/status_report.py`

```python
import logging
import os
import yaml
import docker

from notifier import send_webhook
from stats import get_container_state, get_container_health, get_container_uptime, get_container_stats

logger = logging.getLogger(__name__)
_docker_client = docker.from_env()


def _load_config():
    with open("config.yml") as f:
        return yaml.safe_load(f)


def _get_display_name(config: dict, name: str) -> str:
    return config.get("overrides", {}).get(name, {}).get("display_name", name)


async def send_status_report():
    config = _load_config()
    sr = config.get("status_report", {})

    include_stopped = sr.get("include_stopped", True)
    include_resources = sr.get("include_resource_usage", True)
    include_uptime = sr.get("include_uptime", True)
    include_health = sr.get("include_health", True)

    webhook_url = os.environ.get("DEFAULT_WEBHOOK_URL", "")
    username = config.get("defaults", {}).get("username", "Container Monitor")
    footer = config.get("defaults", {}).get("footer", "Nemesis Server")
    exclude = set(config.get("exclude", []))

    try:
        all_containers = sorted(
            [c.name for c in _docker_client.containers.list(all=True)]
        )
    except Exception as e:
        logger.error("[status-report] Failed to list containers: %s", e)
        return

    running_count = stopped_count = unhealthy_count = 0
    lines = []

    for name in all_containers:
        if name in exclude:
            continue

        display = _get_display_name(config, name)
        state = get_container_state(name)

        if state == "running":
            running_count += 1
            health = get_container_health(name)
            if health == "unhealthy":
                unhealthy_count += 1
                emoji = "🟡"
            else:
                emoji = "🟢"

            line = f"{emoji} **{display}**"
            if include_uptime:
                line += f": Up {get_container_uptime(name)}"
            if include_resources:
                s = get_container_stats(name)
                line += f" | CPU: {s['cpu_pct']} | Mem: {s['mem_usage']}"
            if include_health and health == "unhealthy":
                line += " | ⚠️ unhealthy"
        else:
            stopped_count += 1
            if not include_stopped:
                continue
            emoji = {"exited": "🔴", "paused": "⏸️", "dead": "💀"}.get(state, "❓")
            line = f"{emoji} **{display}**: {state.capitalize()}"

        lines.append(line)

    if unhealthy_count > 0:
        color = 16776960   # Yellow
    elif stopped_count > 0:
        color = 16753920   # Orange
    else:
        color = 65280      # Green

    summary = f"Running: {running_count} | Stopped: {stopped_count} | Unhealthy: {unhealthy_count}"
    description = summary + "\n\n" + "\n".join(lines)

    logger.info("[status-report] %s", summary)
    await send_webhook(webhook_url, "📊 Daily Container Status Report", color, description, username, footer)
```

**Commit:**

```bash
git add nemesis-bot/status_report.py
git commit -m "feat: add daily status report"
```

---

## Task 7: Write mod_monitor.py (Steam Workshop checker)

Replaces `mod-monitor.sh`. Same logic, ported to Python.

**Files:**
- Create: `nemesis-bot/mod_monitor.py`

```python
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
            async with session.post(url, data=data, timeout=aiohttp.ClientTimeout(total=15)) as resp:
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

    stale = {mid: upstream_state[mid] for mid in mod_ids
              if mid in upstream_state and upstream_state[mid] > local_state.get(mid, 0)}

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

    new_stale = {mid: ts for mid, ts in stale.items()
                 if str(notified.get(mid, 0)) != str(ts)}

    # Update notified state
    new_notified = {mid: ts for mid, ts in stale.items()}
    with open(state_file, "w") as f:
        json.dump(new_notified, f)

    if not new_stale:
        logger.info("[mod-monitor] %s: %d stale mod(s), already notified", server, len(stale))
        return

    # Build mod list for notification
    upstream_details = await query_steam_api(mod_ids)  # already fetched, reuse
    mod_lines = []
    for mid, upstream_ts in stale.items():
        local_ts = local_state.get(mid, 0)
        age_hours = (upstream_ts - local_ts) // 3600
        new_marker = " 🆕" if mid in new_stale else ""
        mod_lines.append(
            f"• [{mid}](https://steamcommunity.com/sharedfiles/filedetails/?id={mid})"
            f" — {age_hours}h behind{new_marker}"
        )

    display_name = srv.get("display_name", server)
    auto_restart = srv.get("auto_restart", False)
    container_name = srv.get("container_name", "")
    username = srv.get("username", "Mod Monitor")
    footer = srv.get("footer", "Mod Monitor")

    webhook_env = srv.get("webhook_env", "")
    webhook_url = os.environ.get(webhook_env, "") if webhook_env else ""
    if not webhook_url:
        webhook_url = os.environ.get("DEFAULT_WEBHOOK_URL", "")

    mod_list_str = "\n".join(mod_lines)
    total = len(stale)
    new_count = len(new_stale)

    if auto_restart and container_name:
        title = f"🔄 {display_name} — Stale Mods Detected"
        desc = f"{total} mod(s) behind Steam Workshop ({new_count} new):\n{mod_list_str}\n\n⏳ Server restarting to update..."
        await send_webhook(webhook_url, title, 16753920, desc, username, footer)

        try:
            c = _docker_client.containers.get(container_name)
            c.restart(timeout=30)
            if os.path.exists(state_file):
                os.remove(state_file)
            await send_webhook(webhook_url, f"✅ {display_name} — Restarted", 65280,
                               "Server restarted to pick up mod updates.", username, footer)
        except Exception as e:
            await send_webhook(webhook_url, f"❌ {display_name} — Restart Failed", 16711680,
                               f"Auto-restart failed: {e}", username, footer)
    else:
        title = f"📦 {display_name} — Stale Mods Detected"
        desc = f"{total} mod(s) behind Steam Workshop ({new_count} new):\n{mod_list_str}\n\nManual restart required."
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
```

**Commit:**

```bash
git add nemesis-bot/mod_monitor.py
git commit -m "feat: add mod monitor (Steam Workshop checker)"
```

---

## Task 8: Write bot_commands.py (inbound Discord commands)

**Files:**
- Create: `nemesis-bot/bot_commands.py`

```python
import os
import discord
from discord.ext import commands
import docker
import yaml

from stats import get_container_state, get_container_health, get_container_uptime, restart_container

_docker_client = docker.from_env()

# Loaded once at startup: {discord_role_id: role_config_dict}
_role_map: dict[int, dict] = {}


def _load_config() -> dict:
    with open("config.yml") as f:
        return yaml.safe_load(f)


def load_roles(config: dict):
    """Read role IDs from env vars and build the role map."""
    global _role_map
    _role_map = {}
    for role_key, role_cfg in config.get("roles", {}).items():
        env_var = role_cfg.get("env", "")
        raw_id = os.environ.get(env_var, "").strip()
        if raw_id.isdigit():
            _role_map[int(raw_id)] = {**role_cfg, "key": role_key}


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
            return {"*"}  # admin — short-circuit
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


def register_commands(bot: commands.Bot):
    config = _load_config()
    load_roles(config)

    @bot.command(name="help")
    async def help_cmd(ctx):
        allowed = get_allowed_containers(ctx.author)
        embed = discord.Embed(title="Nemesis Bot — Commands", color=0x5865F2)

        if allowed is None:
            embed.description = "You don't have a recognised role. Contact the admin."
        else:
            if "*" in allowed:
                container_list = "All containers (admin)"
            else:
                container_list = "\n".join(f"  `{c}`" for c in sorted(allowed)) or "None assigned"

            embed.add_field(name="`!status`", value="Show your containers' current state.", inline=False)
            embed.add_field(
                name="`!restart <container>`",
                value=f"Restart one of your containers:\n{container_list}",
                inline=False,
            )
        embed.set_footer(text="Access is role-restricted.")
        await ctx.send(embed=embed)

    @bot.command(name="status")
    async def status_cmd(ctx):
        allowed = get_allowed_containers(ctx.author)
        if allowed is None:
            await ctx.send("You don't have permission to use this command.")
            return

        containers = get_all_containers() if "*" in allowed else sorted(allowed)
        lines = []
        any_bad = False

        for name in containers:
            state = get_container_state(name)
            health = get_container_health(name)
            uptime = get_container_uptime(name)

            if state == "running" and health == "unhealthy":
                emoji, label = "🟡", f"Running — unhealthy | Up {uptime}"
                any_bad = True
            elif state == "running":
                emoji, label = "🟢", f"Running | Up {uptime}"
            else:
                emoji, label = "🔴", state.capitalize()
                any_bad = True

            lines.append(f"{emoji} **{name}**: {label}")

        embed = discord.Embed(
            title="📊 Container Status",
            description="\n".join(lines) or "No containers found.",
            color=0xED4245 if any_bad else 0x57F287,
        )
        await ctx.send(embed=embed)

    @bot.command(name="restart")
    async def restart_cmd(ctx, container: str = None):
        allowed = get_allowed_containers(ctx.author)
        if allowed is None:
            await ctx.send("You don't have permission to use this command.")
            return

        if not container:
            await ctx.send("Usage: `!restart <container>`\nRun `!help` to see your allowed containers.")
            return

        if not can_access(ctx.author, container):
            await ctx.send(f"❌ You don't have access to `{container}`.")
            return

        msg = await ctx.send(f"🔄 Restarting **{container}**...")
        success = restart_container(container)
        if success:
            await msg.edit(content=f"✅ **{container}** restarted successfully.")
        else:
            await msg.edit(content=f"❌ Failed to restart **{container}**. Check logs.")
```

**Commit:**

```bash
git add nemesis-bot/bot_commands.py
git commit -m "feat: add Discord bot commands (!status, !restart, !help)"
```

---

## Task 9: Write main.py (wires everything together)

**Files:**
- Create: `nemesis-bot/main.py`

```python
import asyncio
import logging
import os
import yaml

import discord
from discord.ext import commands, tasks

from bot_commands import register_commands
from event_monitor import watch_events
from status_report import send_status_report
from mod_monitor import run_all_servers, check_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def load_config():
    with open("config.yml") as f:
        return yaml.safe_load(f)


def make_bot() -> commands.Bot:
    config = load_config()
    prefix = config.get("bot", {}).get("prefix", "!")
    intents = discord.Intents.default()
    intents.message_content = True
    return commands.Bot(command_prefix=prefix, intents=intents, help_command=None)


bot = make_bot()
config = load_config()


@bot.event
async def on_ready():
    status_msg = config.get("bot", {}).get("status_message", "Nemesis Server")
    await bot.change_presence(activity=discord.Game(name=status_msg))
    logger.info("Bot online as %s", bot.user)

    # Start background tasks
    docker_event_task.start()
    status_report_task.start()
    mod_monitor_task.start()

    # Send startup notification
    from notifier import send_webhook
    webhook_url = os.environ.get("DEFAULT_WEBHOOK_URL", "")
    username = config.get("defaults", {}).get("username", "Container Monitor")
    footer = config.get("defaults", {}).get("footer", "Nemesis Server")
    await send_webhook(webhook_url, "🤖 Nemesis Bot Online", 65280,
                       "Monitoring all containers for lifecycle events.", username, footer)


@tasks.loop(count=1)
async def docker_event_task():
    await watch_events(asyncio.get_event_loop())


@tasks.loop(hours=1)
async def status_report_task():
    """Check every hour if it's time to send the daily report."""
    from datetime import datetime, timezone
    sr = config.get("status_report", {})
    if not sr.get("enabled", True):
        return
    target_hour = sr.get("schedule_hour", 8)
    now = datetime.now(timezone.utc)
    if now.hour == target_hour and now.minute < 60:
        await send_status_report()


@tasks.loop(hours=1)
async def mod_monitor_task():
    """Check each server on its configured interval."""
    from datetime import datetime, timezone
    servers = config.get("mod_monitor", {}).get("servers", {})
    now_hour = datetime.now(timezone.utc).hour
    for server, srv in servers.items():
        if not srv.get("enabled", True):
            continue
        interval = srv.get("schedule_interval_hours", 24)
        if interval > 0 and now_hour % interval == 0:
            try:
                await check_server(server, config)
            except Exception as e:
                logger.error("[main] mod_monitor error for %s: %s", server, e)


register_commands(bot)

if __name__ == "__main__":
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is not set")
    bot.run(token)
```

**Commit:**

```bash
git add nemesis-bot/main.py
git commit -m "feat: add main.py — wires bot, events, schedule, and commands"
```

---

## Task 10: Write docker-compose.yml

Includes all volume mounts from the old container-monitor compose.

**Files:**
- Create: `nemesis-bot/docker-compose.yml`
- Create: `nemesis-bot/.env.example`

**Step 1: Write docker-compose.yml**

```yaml
---
services:
  nemesis-bot:
    build: .
    container_name: nemesis-bot
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./state:/state
      - /docker/game/zomboid-dev/ZomboidDedicatedServer/steamapps/workshop:/acf/zomboid-dev:ro
      - /docker/game/zomboid/ZomboidDedicatedServer/steamapps/workshop:/acf/zomboid-prod:ro
    environment:
      DISCORD_TOKEN: "${DISCORD_TOKEN}"
      # Role IDs — AA-### naming, one env var per role
      ROLE_ID_QZ481: "${ROLE_ID_QZ481}"   # Admin
      ROLE_ID_VR156: "${ROLE_ID_VR156}"   # Plex
      ROLE_ID_TK829: "${ROLE_ID_TK829}"   # Zomboid
      ROLE_ID_WB347: "${ROLE_ID_WB347}"   # Minecraft
      ROLE_ID_NF613: "${ROLE_ID_NF613}"   # Other games
      DEFAULT_WEBHOOK_URL: "${DEFAULT_WEBHOOK_URL}"
      ZOMBOID_WEBHOOK_URL: "${ZOMBOID_WEBHOOK_URL}"
      ATM9S_WEBHOOK_URL: "${ATM9S_WEBHOOK_URL}"
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
        reservations:
          cpus: '0.25'
          memory: 256M
```

**Step 2: Write .env.example**

```env
DISCORD_TOKEN=your-bot-token-here

# Discord role IDs — one per role (get from Discord Developer Mode, right-click role)
ROLE_ID_QZ481=        # Admin (you)
ROLE_ID_VR156=        # Plex stack
ROLE_ID_TK829=        # Zomboid
ROLE_ID_WB347=        # Minecraft
ROLE_ID_NF613=        # Other games (scaffold)

DEFAULT_WEBHOOK_URL=https://discord.com/api/webhooks/...
ZOMBOID_WEBHOOK_URL=https://discord.com/api/webhooks/...
ATM9S_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

**Step 3: Copy .env values from container-monitor**

```bash
cp /docker/homelab-config/data-host/composed-apps/container-monitor/.env \
   /docker/homelab-config/data-host/composed-apps/nemesis-bot/.env
# Then add DISCORD_TOKEN and all ROLE_ID_* values to the .env
```

**Step 4: Add .env to .gitignore**

```bash
echo "nemesis-bot/.env" >> /docker/homelab-config/.gitignore
```

**Step 5: Commit**

```bash
git add nemesis-bot/docker-compose.yml nemesis-bot/.env.example
git commit -m "feat: add nemesis-bot docker-compose"
```

---

## Task 11: Discord bot setup (one-time manual steps)

**Step 1: Create a Discord application**
1. Go to https://discord.com/developers/applications
2. Click **New Application** → name it "Nemesis Bot"
3. Go to **Bot** → click **Add Bot**
4. Enable **Message Content Intent** under Privileged Gateway Intents
5. Copy the **Token** → add to `.env` as `DISCORD_TOKEN`

**Step 2: Invite the bot to your server**
1. Go to **OAuth2 → URL Generator**
2. Scopes: `bot` | Bot permissions: `Send Messages`, `Read Messages/View Channels`, `Embed Links`
3. Open the URL and add the bot to your server

**Step 3: Create the roles in your Discord server**

In your server settings → Roles, create these five roles:

| Role name | Env var | Who gets it |
|-----------|---------|-------------|
| `QZ-481` | `ROLE_ID_QZ481` | You (admin) |
| `VR-156` | `ROLE_ID_VR156` | Brother / Plex users |
| `TK-829` | `ROLE_ID_TK829` | Zomboid players |
| `WB-347` | `ROLE_ID_WB347` | Minecraft players |
| `NF-613` | `ROLE_ID_NF613` | Other game server users |

**Step 4: Get each role ID**
1. Discord: User Settings → Advanced → enable **Developer Mode**
2. In server settings → Roles, right-click each role → **Copy Role ID**
3. Paste each into `.env` against the matching `ROLE_ID_*` var

---

## Task 12: Build, deploy, and decommission container-monitor

**Step 1: Build the new image**

```bash
sudo docker compose -f /docker/homelab-config/data-host/composed-apps/nemesis-bot/docker-compose.yml build
```

Expected: no errors.

**Step 2: Stop the old container-monitor**

```bash
sudo docker compose -f /docker/homelab-config/data-host/composed-apps/container-monitor/docker-compose.yml down
```

**Step 3: Start nemesis-bot**

```bash
sudo docker compose -f /docker/homelab-config/data-host/composed-apps/nemesis-bot/docker-compose.yml up -d
```

**Step 4: Check logs**

```bash
sudo docker logs nemesis-bot --tail 30
```

Expected: `Bot online as Nemesis Bot#XXXX` + startup webhook fires in Discord.

**Step 5: Smoke test**
- Stop a container manually → confirm Discord alert fires
- Send `!help` in Discord → confirm embed response
- Send `!status` → confirm green/red for each plex container
- Send `!restart qbittorrent` → confirm restart + Discord confirmation

**Step 6: Final commit**

```bash
git add .
git commit -m "feat: deploy nemesis-bot, replaces container-monitor"
```

---

## Notes

- Old `container-monitor/` dir can be archived or deleted after nemesis-bot is stable for a few days
- State files in `/state/` carry over from the old monitor — copy them to preserve mod-monitor dedup state

**Adding someone to a role:**
1. Assign the Discord role to them in your server
2. No bot restart needed — role IDs are checked at command time

**Adding containers to a role:**
1. Edit `config.yml` under the relevant role's `containers` list
2. Restart the bot: `sudo docker restart nemesis-bot`
3. No code change needed

**Adding a new role entirely:**
1. Create the role in Discord, copy its ID
2. Add a new entry to `roles:` in `config.yml` with a new `AA-###` key and `env` var
3. Add the env var to `docker-compose.yml` and `.env`
4. Restart the bot

**Role access summary:**

| Role | `!status` shows | `!restart` allows |
|------|----------------|-------------------|
| QZ-481 (Admin) | All containers | All containers |
| VR-156 (Plex) | plex-nfs, qbit, overseerr, sonarr, radarr | Same |
| TK-829 (Zomboid) | zomboid-dedicated-server, zomboid-dev-server | Same |
| WB-347 (Minecraft) | mcatm9s | Same |
| NF-613 (Other) | *(empty until populated)* | Same |
