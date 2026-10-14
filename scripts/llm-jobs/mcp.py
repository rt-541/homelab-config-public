"""MCP surface for llm-jobs: JSON-RPC 2.0 over streamable HTTP, stateless
(plain JSON responses, no sessions). Served by server.py at POST /mcp.

User keys see the caller tools; worker keys (the NanoClaw job groups) see
deliver_result. Every call lands in jobs_lib.Service with the same rules as
the REST surface.
"""

import json

import jobs_lib as lib

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "llm-jobs", "version": "1.0"}
INSTRUCTIONS = (
    "llm-jobs: fire-and-forget LLM jobs run by the homelab NanoClaw fleet. "
    "Call list_tiers once, then submit_job(prompt, tier). Poll get_status every "
    "10 to 30 s (jobs take one to several minutes), then get_result. Results are "
    "kept 30 days and are visible only to the submitting key."
)

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603


def _obj(props, required=()):
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


USER_TOOLS = [
    ("list_tiers", "List the job tiers (model, speed, cost, notes) this service offers.", _obj({})),
    ("submit_job", "Submit a job. Returns job_id, status and queue position immediately; the job runs asynchronously on the tier's NanoClaw agent group.",
     _obj({"prompt": {"type": "string", "description": "The complete task, self-contained: the worker sees nothing else."},
           "tier": {"type": "string", "description": "local (default, free, private), claude (Sonnet 5, metered) or render (Blender photoreal stills; the prompt is a JSON recipe and the result lists PNG artifacts)."},
           "params": {"type": "object", "description": "Optional hints: max_words (integer), format (string)."}}, ("prompt",))),
    ("get_status", "Poll a job: queued (with position), running, done, failed, cancelled.", _obj({"job_id": {"type": "string"}}, ("job_id",))),
    ("get_result", "Fetch the delivered result once status is done (or the error if failed).", _obj({"job_id": {"type": "string"}}, ("job_id",))),
    ("cancel_job", "Cancel a queued or running job.", _obj({"job_id": {"type": "string"}}, ("job_id",))),
    ("list_jobs", "List this key's recent jobs.", _obj({"limit": {"type": "integer", "default": 50}})),
]
WORKER_TOOLS = [
    ("deliver_result", "Worker only: deliver the finished job. Pass result (the complete answer) or error (why it could not be done). Exactly once per job.",
     _obj({"job_id": {"type": "string"}, "result": {"type": "string"}, "error": {"type": "string"}}, ("job_id",))),
    ("request_photo", "Worker only: queue a photoreal pass (FLUX Kontext on the GPU, via the gpu-arbiter) of one PNG in the running job's artifact folder. The photo is written next to it as photo-<name>. Returns photo_id; poll photo_status. It may wait for the GPU to go idle.",
     _obj({"job_id": {"type": "string"}, "image": {"type": "string"}, "prompt": {"type": "string"}}, ("job_id", "image"))),
    ("photo_status", "Worker only: status of a photo pass: queued (with position), running, done, failed.",
     _obj({"photo_id": {"type": "string"}}, ("photo_id",))),
]


def tool_list(role):
    tools = USER_TOOLS if role in ("user", "admin") else []
    if role in ("worker", "admin"):
        tools = tools + WORKER_TOOLS
    return [{"name": n, "description": d, "inputSchema": s} for n, d, s in tools]


def _ok(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid, code, message):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def call_tool(service, key, name, args):
    if name == "list_tiers":
        return {"tiers": service.tiers()}
    if name == "submit_job":
        return service.submit(key, args.get("prompt"), args.get("tier") or "local", args.get("params"))
    if name == "get_status":
        return service.status(key, str(args.get("job_id") or ""))
    if name == "get_result":
        return service.result(key, str(args.get("job_id") or ""))
    if name == "cancel_job":
        return service.cancel(key, str(args.get("job_id") or ""))
    if name == "list_jobs":
        return {"jobs": service.list(key, args.get("limit") or 50)}
    if name == "request_photo":
        return service.request_photo(key, str(args.get("job_id") or ""), str(args.get("image") or ""), args.get("prompt"))
    if name == "photo_status":
        return service.photo_status(key, str(args.get("photo_id") or ""))
    if name == "deliver_result":
        return service.deliver(key, str(args.get("job_id") or ""), args.get("result"), args.get("error"))
    raise lib.JobsError("bad-request", "unknown tool %s" % name, 400)


def dispatch(service, key, msg):
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        return _err(msg.get("id") if isinstance(msg, dict) else None, INVALID_REQUEST, "invalid JSON-RPC request")
    mid, method, params = msg.get("id"), msg["method"], msg.get("params") or {}
    if method.startswith("notifications/"):
        return None
    if "id" not in msg:
        return None
    if method == "initialize":
        req = params.get("protocolVersion") if isinstance(params, dict) else None
        return _ok(mid, {"protocolVersion": req if req in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                         "capabilities": {"tools": {"listChanged": False}},
                         "serverInfo": SERVER_INFO, "instructions": INSTRUCTIONS})
    if method == "ping":
        return _ok(mid, {})
    if method == "tools/list":
        return _ok(mid, {"tools": tool_list(key["role"])})
    if method == "tools/call":
        if not isinstance(params, dict):
            return _err(mid, INVALID_PARAMS, "params must be an object")
        name, args = params.get("name"), params.get("arguments") or {}
        allowed = {t["name"] for t in tool_list(key["role"])}
        if name not in allowed:
            return _err(mid, INVALID_PARAMS, "unknown tool: %s" % name)
        if not isinstance(args, dict):
            return _err(mid, INVALID_PARAMS, "arguments must be an object")
        try:
            result = call_tool(service, key, name, args)
        except lib.JobsError as e:
            return _ok(mid, {"content": [{"type": "text", "text": json.dumps(e.envelope())}], "isError": True})
        except Exception as e:  # noqa: BLE001 - never a traceback to the caller
            return _ok(mid, {"content": [{"type": "text", "text": json.dumps({"error": "internal", "message": str(e)})}], "isError": True})
        return _ok(mid, {"content": [{"type": "text", "text": json.dumps(result, default=str)}],
                         "structuredContent": result if isinstance(result, dict) else None, "isError": False})
    return _err(mid, METHOD_NOT_FOUND, "method not found: %s" % method)


def handle(service, key, payload):
    """Returns (http_status, body_or_None)."""
    if isinstance(payload, list):
        if not payload:
            return 400, _err(None, INVALID_REQUEST, "empty batch")
        out = [r for r in (dispatch(service, key, m) for m in payload) if r is not None]
        return (200, out) if out else (202, None)
    r = dispatch(service, key, payload)
    return (200, r) if r is not None else (202, None)
