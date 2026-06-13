import asyncio
import logging
import os
import yaml

import discord
from discord.ext import commands, tasks

from bot_commands import register_commands
from event_monitor import watch_events
from status_report import send_status_report
from mod_monitor import check_server

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

    await bot.tree.sync()
    logger.info("Slash commands synced")

    docker_event_task.start()
    status_report_task.start()
    mod_monitor_task.start()

    from notifier import send_webhook

    webhook_url = os.environ.get("DEFAULT_WEBHOOK_URL", "")
    username = config.get("defaults", {}).get("username", "Container Monitor")
    footer = config.get("defaults", {}).get("footer", "Nemesis Server")
    await send_webhook(
        webhook_url,
        "Nemesis Mission Systems Online",
        65280,
        "Monitoring all containers for lifecycle events.",
        username,
        footer,
    )


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
    if now.hour == target_hour:
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
