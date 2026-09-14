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


async def _notify(config: dict, name: str, action: str):
    """Build and send a Discord notification for a container event."""
    from notifier import send_webhook

    display_name = _get_config_value(config, name, "display_name") or name
    webhook_url = _get_webhook_url(config, name)
    username = _get_config_value(config, name, "username") or "Nemesis Mission Systems"
    footer = _get_config_value(config, name, "footer") or "Nemesis Mission Systems"

    if action == "start":
        color = _get_config_value(config, name, "color_start") or 65280
        title = f"{display_name} Started"
        desc = _get_config_value(config, name, "start_message") or ""
    elif action in ("die", "kill"):
        try:
            c = _docker_client.containers.get(name)
            exit_code = c.attrs.get("State", {}).get("ExitCode", -1)
        except Exception:
            exit_code = -1

        if exit_code == 0:
            color = _get_config_value(config, name, "color_stop") or 16711680
            title = f"{display_name} Stopped"
            desc = _get_config_value(config, name, "stop_message") or ""
        else:
            color = _get_config_value(config, name, "color_crash") or 16776960
            title = f"{display_name} Crashed"
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
            asyncio.run_coroutine_threadsafe(_notify(config, name, action), loop)

    while True:
        try:
            logger.info("[event] Starting Docker event stream...")
            await loop.run_in_executor(None, _stream)
        except Exception as e:
            logger.error("[event] Stream error, restarting in 5s: %s", e)
            await asyncio.sleep(5)
