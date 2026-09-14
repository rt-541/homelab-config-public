import aiohttp
import logging

logger = logging.getLogger(__name__)


async def send_webhook(
    webhook_url: str,
    title: str,
    color: int,
    description: str = "",
    username: str = "Nemesis Mission Systems",
    footer: str = "Nemesis Mission Systems",
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
