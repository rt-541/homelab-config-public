"""Backend selection: transparent rules table + opt-in LLM-assisted path.

``pick()`` is the shared brain used by the worker submit path, the REST API, and
the MCP ``pick_best_backend`` tool. It returns ``(alias, rationale)``. Aliases
are capability names (fast | background | reasoning); the worker resolves the
tier from ``backends.tier_for``.

The LLM-assisted path is gated by SELECTION_LLM_ENABLED (default off). When on,
ambiguous jobs are routed by the ``background`` model using
``prompts/model-selection.md``; any parse/validation failure falls back to the
rules table.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from . import backends

ALIASES = {
    "fast": "fast GPU model (B70 vLLM); interactive code/chat",
    "background": "CPU model (Ollama qwen2.5:7b); cheap batch/summarize",
    "reasoning": "CPU model (Ollama deepseek-r1); step-by-step analysis",
}

DEFAULT_ALIAS = "fast"

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "model-selection.md"


def _llm_enabled() -> bool:
    return os.environ.get("SELECTION_LLM_ENABLED", "false").lower() in ("1", "true", "yes")


def pick(task: str, latency: str = "interactive", est_context: int = 0) -> tuple[str, str]:
    """Rules-table selection. Returns (alias, rationale).

    Priority: batch/low-urgency -> background; reasoning signals -> reasoning;
    large context or code/interactive -> fast; default -> fast.
    """
    t = (task or "").lower()

    if latency == "batch" or any(w in t for w in ("summarize", "bulk", "translate", "extract", "overnight", "batch")):
        return "background", "batch/low-urgency or summarize/translate -> background (CPU) tier"

    if any(w in t for w in ("reason", "step by step", "chain of thought", "proof", "deeply", "think carefully")):
        return "reasoning", "reasoning-heavy task -> reasoning (CPU CoT) tier"

    if est_context > 12000:
        return "fast", "large context -> fast (GPU) tier"

    if any(w in t for w in ("code", "debug", "analyze", "fast", "chat", "refactor", "generate")):
        return "fast", "interactive code/chat -> fast (GPU) tier"

    return DEFAULT_ALIAS, "default -> fast (GPU) tier"


def _load_system_prompt() -> str:
    text = _PROMPT_PATH.read_text(encoding="utf-8")
    # Extract the fenced system prompt block (between the first ``` after
    # "## System Prompt" and its closing fence).
    marker = "## System Prompt"
    idx = text.find(marker)
    if idx == -1:
        return text
    rest = text[idx:]
    start = rest.find("```")
    if start == -1:
        return text
    start += 3
    # skip optional language tag line
    nl = rest.find("\n", start)
    body_start = nl + 1 if nl != -1 else start
    end = rest.find("```", body_start)
    block = rest[body_start:end] if end != -1 else rest[body_start:]
    return block.strip()


def _build_messages(task: str, latency: Optional[str], est_context: int) -> list[dict]:
    system = _load_system_prompt()
    registry_json = json.dumps(backends.registry_for_prompt(), indent=2)
    system = system.replace("{{models}}", registry_json)
    job = {
        "task": task,
        "latency": latency,
        "est_context": est_context or None,
        "output_length": None,
        "cost_sensitive": None,
        "requested_alias": None,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(job)},
    ]


def _parse_decision(text: str) -> Optional[tuple[str, str]]:
    """Parse the strict JSON decision; validate alias exists. None on failure."""
    s = text.strip()
    # Tolerate accidental ```json fences.
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
    # Some models (deepseek) emit <think>...</think>; strip to the JSON object.
    first = s.find("{")
    last = s.rfind("}")
    if first == -1 or last == -1:
        return None
    s = s[first:last + 1]
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        return None
    alias = obj.get("alias")
    if alias not in backends.REGISTRY:
        return None
    rationale = str(obj.get("rationale", "LLM-selected"))[:200]
    conf = obj.get("confidence")
    if conf is not None:
        rationale = f"{rationale} (llm confidence={conf})"
    return alias, rationale


async def pick_llm(task: str, latency: str = "interactive", est_context: int = 0) -> tuple[str, str]:
    """LLM-assisted selection via the background model. Falls back to rules."""
    try:
        messages = _build_messages(task, latency, est_context)
        import httpx
        b = backends.get_backend("background")
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)) as client:
            resp = await client.post(
                f"{b.url}/chat/completions",
                json={"model": b.model, "messages": messages, "temperature": 0},
            )
            resp.raise_for_status()
            content = (resp.json().get("choices") or [{}])[0].get("message", {}).get("content", "")
        parsed = _parse_decision(content)
        if parsed:
            return parsed
    except Exception:
        pass
    return pick(task, latency, est_context)


async def pick_best_backend(task: str, latency: str = "interactive", est_context: int = 0) -> tuple[str, str]:
    """Public selection entrypoint used by the API + MCP.

    Uses the LLM-assisted path when SELECTION_LLM_ENABLED is set, otherwise the
    rules table. Always returns a valid (alias, rationale).
    """
    if _llm_enabled():
        return await pick_llm(task, latency, est_context)
    return pick(task, latency, est_context)
