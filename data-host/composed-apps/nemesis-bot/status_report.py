import logging
import os
import yaml
import docker

from notifier import send_webhook
from stats import (
    get_container_state,
    get_container_health,
    get_container_uptime,
    get_container_stats,
)

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
    username = config.get("defaults", {}).get("username", "Nemesis Mission Systems")
    footer = config.get("defaults", {}).get("footer", "Nemesis Mission Systems")
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
                status = "[WARN]"
            else:
                status = "[UP]"

            line = f"{status} **{display}**"
            if include_uptime:
                line += f": Up {get_container_uptime(name)}"
            if include_resources:
                s = get_container_stats(name)
                line += f" | CPU: {s['cpu_pct']} | Mem: {s['mem_usage']}"
            if include_health and health == "unhealthy":
                line += " | unhealthy"
        else:
            stopped_count += 1
            if not include_stopped:
                continue
            status = {"exited": "[DOWN]", "paused": "[PAUSED]", "dead": "[DEAD]"}.get(state, "[UNKNOWN]")
            line = f"{status} **{display}**: {state.capitalize()}"

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
    await send_webhook(
        webhook_url,
        "Daily Container Status Report",
        color,
        description,
        username,
        footer,
    )
