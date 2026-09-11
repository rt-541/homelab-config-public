"""Backend registry + LiteLLM gateway client (Phase B).

Capability aliases (fast|background|reasoning) map to a (url, model, tier) Backend
for selection/tier purposes.  ``run()`` now posts to the single LiteLLM gateway
using the caller's virtual key as the Bearer and the alias as the model-group name;
the gateway maps alias->concrete model and enforces per-key quota.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

import httpx

# Long timeout: CPU Ollama jobs can take minutes. Connect quickly, read slowly.
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=900.0, write=30.0, pool=10.0)

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://llm-gateway:4000")


@dataclass(frozen=True)
class Backend:
    alias: str
    url: str        # OpenAI-compatible base, ends in /v1
    model: str
    tier: str       # gpu | cpu
    speed: str      # fast | medium | slow
    strengths: tuple[str, ...]
    max_context_tokens: int
    backend_name: str  # human label, e.g. gpu-b70-vllm
    notes: str = ""


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def build_registry() -> dict[str, Backend]:
    """Build the alias->Backend registry from environment variables."""
    return {
        "fast": Backend(
            alias="fast",
            url=_env("FAST_BACKEND_URL", "http://192.168.1.216:8000/v1"),
            model=_env("FAST_MODEL", "qwen2.5-7b-instruct"),
            tier="gpu",
            speed="fast",
            strengths=("chat", "code", "fast-inference", "instruction-following"),
            max_context_tokens=16384,
            backend_name="gpu-b70-vllm",
            notes="Arc Pro B70 GPU; OpenAI-compatible at 192.168.1.216:8000/v1",
        ),
        "background": Backend(
            alias="background",
            url=_env("BACKGROUND_BACKEND_URL", "http://host.docker.internal:11434/v1"),
            model=_env("BACKGROUND_MODEL", "qwen2.5:7b"),
            tier="cpu",
            speed="slow",
            strengths=("summarize", "translate", "extract", "batch"),
            max_context_tokens=8192,
            backend_name="cpu-ollama",
            notes="nemesis CPU; fine for overnight/batch; slower but always available",
        ),
        "reasoning": Backend(
            alias="reasoning",
            url=_env("REASONING_BACKEND_URL", "http://host.docker.internal:11434/v1"),
            model=_env("REASONING_MODEL", "deepseek-r1:7b"),
            tier="cpu",
            speed="slow",
            strengths=("reasoning", "step-by-step", "analysis", "math"),
            max_context_tokens=8192,
            backend_name="cpu-ollama",
            notes="nemesis CPU; CoT specialist; do not use for interactive latency",
        ),
    }


# Module-level registry (rebuilt at import; env is set before import in the app).
REGISTRY: dict[str, Backend] = build_registry()


def get_backend(alias: str) -> Backend:
    if alias not in REGISTRY:
        raise KeyError(f"unknown alias: {alias!r}")
    return REGISTRY[alias]


def tier_for(alias: str) -> str:
    return get_backend(alias).tier


def known_aliases() -> list[str]:
    return list(REGISTRY.keys())


def registry_for_prompt() -> list[dict[str, Any]]:
    """Registry shaped for the model-selection prompt's {{models}} injection."""
    out = []
    for b in REGISTRY.values():
        out.append({
            "alias": b.alias,
            "name": b.model,
            "backend": b.backend_name,
            "strengths": list(b.strengths),
            "speed": b.speed,
            "max_context_tokens": b.max_context_tokens,
            "notes": b.notes,
        })
    return out


async def run(
    alias: str,
    prompt: str,
    params: Optional[dict[str, Any]] = None,
    *,
    api_key: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    """POST a chat completion to the LiteLLM gateway as the caller, return text.

    The alias IS the gateway model-group name (fast|background|reasoning), so the
    alias->concrete-model mapping lives in the gateway, not here. ``api_key`` is
    the caller's virtual key; the gateway enforces that key's quota. Raises on
    transport errors or non-2xx so the worker records a real failure.
    """
    if alias not in REGISTRY:
        raise KeyError(f"unknown alias: {alias!r}")
    if not api_key:
        raise RuntimeError("backends.run requires the caller's api_key in Phase B")
    params = dict(params or {})
    body: dict[str, Any] = {
        "model": alias,
        "messages": [{"role": "user", "content": prompt}],
    }
    for k in ("temperature", "top_p", "max_tokens", "stop", "seed"):
        if k in params:
            body[k] = params[k]
    headers = {"Authorization": f"Bearer {api_key}"}

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
    try:
        resp = await client.post(
            f"{GATEWAY_URL}/v1/chat/completions", json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"gateway returned no choices for {alias}: {data!r}")
        content = (choices[0].get("message") or {}).get("content")
        if content is None:
            raise RuntimeError(f"gateway returned no content for {alias}: {data!r}")
        return content
    finally:
        if own_client:
            await client.aclose()
