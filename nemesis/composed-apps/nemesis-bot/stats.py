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
        # Trim nanoseconds to microseconds for fromisoformat compat
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
        cpu_delta = (
            raw["cpu_stats"]["cpu_usage"]["total_usage"]
            - raw["precpu_stats"]["cpu_usage"]["total_usage"]
        )
        system_delta = (
            raw["cpu_stats"]["system_cpu_usage"]
            - raw["precpu_stats"]["system_cpu_usage"]
        )
        num_cpus = raw["cpu_stats"].get("online_cpus") or len(
            raw["cpu_stats"]["cpu_usage"].get("percpu_usage", [1])
        )
        cpu_pct = (
            (cpu_delta / system_delta) * num_cpus * 100.0 if system_delta > 0 else 0.0
        )

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


def start_container(name: str) -> bool:
    try:
        c = _client.containers.get(name)
        c.start()
        return True
    except Exception as e:
        logger.error("start_container(%s): %s", name, e)
        return False


def stop_container(name: str) -> bool:
    try:
        c = _client.containers.get(name)
        c.stop(timeout=30)
        return True
    except Exception as e:
        logger.error("stop_container(%s): %s", name, e)
        return False


def restart_container(name: str) -> bool:
    try:
        c = _client.containers.get(name)
        c.restart(timeout=30)
        return True
    except Exception as e:
        logger.error("restart_container(%s): %s", name, e)
        return False
