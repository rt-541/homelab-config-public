"""MCP (Model Context Protocol) surface for the plex-ops action-runner.

Python 3.9 stdlib only. Exposes every probe, the read-only arr passthrough,
and every whitelisted action as a typed MCP tool over JSON-RPC 2.0, served
by runner.py at `POST /mcp` (streamable HTTP, stateless: plain JSON
responses, no sessions, no server-initiated streams). The agent's Claude
Code harness connects with:

    {"plex-ops": {"type": "http", "url": "http://nemesis.rt-541.io:8377/mcp",
                  "headers": {"Authorization": "Bearer <token>"}}}

This module is a thin adapter: every tool call lands in probes.PROBES /
actions.ACTIONS / lib.arr_get_raw with exactly the same validation,
re-verification, and refusal semantics as the REST surface. Nothing is
reachable through MCP that is not reachable through REST, and vice versa.
Interface contract: scripts/plex-ops/CONTRACT.md (section 8).
"""

import json
import urllib.parse

import plexops_lib as lib
import probes
import actions

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "plex-ops-runner", "version": "1.1"}
INSTRUCTIONS = (
    "plex-ops runner for Arthur's plex stack on nemesis. Read-only tools: "
    "lookup, queue_health, service_health, disk, library_audit, arr_get. "
    "Every action tool accepts dry_run=true, which returns the exact plan and "
    "changes nothing; run it first. Actions re-verify their target and refuse "
    "with error verify-failed when the live state no longer matches. All paths "
    "are nemesis paths under /docker/plex/media."
)

# JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


# ---------------------------------------------------------------------------
# Tool table


def _obj(props, required=()):
    return {"type": "object", "properties": props, "required": list(required),
            "additionalProperties": False}


APP = {"type": "string", "enum": ["sonarr", "radarr"],
       "description": "sonarr for series/episodes, radarr for movies."}
DRY = {"type": "boolean", "default": False,
       "description": "Plan only: returns the exact steps, executes nothing."}
INT = {"type": "integer"}
INT_LIST = {"type": "array", "items": {"type": "integer"}, "minItems": 1}


def _probe(name):
    def _call(args):
        params = {k: (str(v).lower() if isinstance(v, bool) else str(v))
                  for k, v in args.items() if v is not None}
        return probes.PROBES[name](params)
    return _call


def _action(name):
    def _call(args):
        return actions.ACTIONS[name](dict(args))
    return _call


def _arr_get(args):
    """Read-only GET passthrough with the same rules as the REST surface
    (CONTRACT.md section 4): /api/v3 only, no dot segments, credential
    endpoints denied, client api keys stripped, arr api key redacted."""
    app = args.get("app")
    if app not in lib.PASSTHROUGH_APPS:
        raise lib.PlexOpsError("not-found", "unknown app: %s" % app, 404)
    path = args.get("path") or ""
    if not isinstance(path, str) or not path.startswith("/"):
        raise lib.PlexOpsError("bad-request", "path must start with /api/v3/", 400)
    segs = [s for s in path.split("/") if s]
    for seg in segs:
        decoded, prev = seg, None
        while prev != decoded:
            prev, decoded = decoded, urllib.parse.unquote(decoded)
        if decoded in (".", ".."):
            raise lib.PlexOpsError("not-found", "dot segments are not allowed", 404)
    rest = "/" + "/".join(segs)
    if not (rest == "/api/v3" or rest.startswith("/api/v3/")):
        raise lib.PlexOpsError("not-found", "passthrough path must start with /api/v3/", 404)
    for deny in lib.PASSTHROUGH_DENY:
        if rest == deny or rest.startswith(deny + "/"):
            raise lib.PlexOpsError("not-found",
                                   "passthrough endpoint is denied (exposes credentials)", 404)
    params = args.get("params") or {}
    if not isinstance(params, dict):
        raise lib.PlexOpsError("bad-request", "params must be an object", 400)
    pairs = [(k, str(v)) for k, v in params.items()
             if k.lower() not in ("apikey", "api_key", "api-key")]
    path_qs = rest + ("?" + urllib.parse.urlencode(pairs) if pairs else "")
    status, ctype, body = lib.arr_get_raw(app, path_qs)
    text = body.decode("utf-8", "replace")
    if not 200 <= status < 300:
        raise lib.PlexOpsError("upstream-error",
                               "%s GET %s -> HTTP %d" % (app, rest, status), 502,
                               detail={"status": status, "body": text[:2000]})
    try:
        return json.loads(text) if text else None
    except ValueError:
        return {"content_type": ctype, "text": text[:20000]}


TOOLS = [
    # -- read-only ---------------------------------------------------------
    ("lookup",
     "Resolve a casual show or movie title to arr ids and file state. For "
     "sonarr, pass season (and episode) to get that season's episodes with "
     "has_file and file details; resolved_id is set when one match is clear. "
     "Use the ids it returns with replace_file, fill_missing, or search.",
     _obj({"app": APP,
           "query": {"type": "string", "description": "Title as the user wrote it."},
           "season": dict(INT, description="sonarr only"),
           "episode": dict(INT, description="sonarr only, requires season")},
          ("app", "query")),
     lambda a: _probe("lookup")({"app": a.get("app"), "q": a.get("query"),
                                 "season": a.get("season"), "episode": a.get("episode")})),
    ("title_stats",
     "Everything known about one show or movie: size on disk and file counts "
     "(Sonarr/Radarr), who watched it on Plex (distinct watchers, plays, per-user "
     "detail, first/last watched; for shows a watcher counts once, not per "
     "episode), and who requested it in Seerr (requester, date). Notes explain "
     "gaps: Plex and Seerr history predating a rebuild is gone.",
     _obj({"app": APP, "query": {"type": "string", "description": "title as the user wrote it"},
           "id": dict(INT, description="sonarr series id or radarr movie id (skips lookup)")},
          ("app",)),
     lambda a: _probe("title-stats")({"app": a.get("app"), "q": a.get("query"), "id": a.get("id")})),
    ("queue_health",
     "Both arr download queues with every item classified (malware-ext, "
     "not-upgrade, mapping-mismatch, sample-stall, unknown) plus evidence.",
     _obj({}), _probe("queue-health")),
    ("service_health",
     "Prowlarr ping/CPU, plex-stack container states and health, Exited(255) "
     "stragglers, VPN egress check.",
     _obj({}), _probe("service-health")),
    ("disk",
     "Usage of both media mounts and the trend since the previous call.",
     _obj({}), _probe("disk")),
    ("library_audit",
     "One chunk of the library integrity audit for an app (missing, sparse, "
     "orphan, malformed, duplicate findings; report-only).",
     _obj({"app": APP, "chunk": dict(INT, description="0-based chunk index"),
           "chunks": dict(INT, description="total chunks, default 7")},
          ("app", "chunk")),
     _probe("library-audit")),
    ("arr_get",
     "Read-only GET against the Sonarr or Radarr v3 API (path must start "
     "with /api/v3/). For ad-hoc questions the other tools do not answer.",
     _obj({"app": APP,
           "path": {"type": "string", "description": "e.g. /api/v3/wanted/missing"},
           "params": {"type": "object", "additionalProperties": {"type": "string"},
                      "description": "query parameters"}},
          ("app", "path")),
     _arr_get),
    # -- help-desk actions -------------------------------------------------
    ("replace_file",
     "The current file for ONE episode or movie is bad: blocklist the release "
     "that produced it, delete the file via the arr, and search for a "
     "replacement. Refuses if the item has no file.",
     _obj({"app": APP, "episode_id": dict(INT, description="sonarr episode id"),
           "movie_id": dict(INT, description="radarr movie id"),
           "blocklist": {"type": "boolean", "default": True}, "dry_run": DRY},
          ("app",)),
     _action("replace-file")),
    ("fill_missing",
     "ONE episode or movie is missing: ensure it is monitored, then search. "
     "Refuses if the item already has a file (use replace_file instead).",
     _obj({"app": APP, "episode_id": dict(INT, description="sonarr episode id"),
           "movie_id": dict(INT, description="radarr movie id"),
           "monitor": {"type": "boolean", "default": True}, "dry_run": DRY},
          ("app",)),
     _action("fill-missing")),
    ("search",
     "Trigger an arr search for movies, episodes, or a whole series (existing "
     "items only; no monitoring changes).",
     _obj({"app": APP, "movie_ids": INT_LIST, "episode_ids": INT_LIST,
           "series_id": INT, "dry_run": DRY}, ("app",)),
     _action("search")),
    # -- compression waves (media reclaim) --------------------------------
    ("reclaim_status",
     "Compression campaign state: queue (total/remaining/done/failed, next "
     "title), GiB saved so far, PAUSE and pilot flags, current/next encode "
     "window, worker status line, remaining candidates and their expected gain.",
     _obj({}), _probe("reclaim-status")),
    ("reclaim_plan",
     "What can be compressed in a window: picks candidates (largest expected "
     "gain first) that fit the window's hours at ~1 GiB/min, reports counts "
     "by size band (large >= 60 GiB, medium 40-60, small < 40), expected gain "
     "and hours, and the titles. window: tonight (overnight window), workday, "
     "or next. refresh=true re-scans the libraries (about a minute).",
     _obj({"window": {"type": "string", "enum": ["tonight", "workday", "next"], "default": "tonight"},
           "hours": {"type": "number", "description": "override the window budget"},
           "limit": dict(INT, description="max titles"),
           "refresh": {"type": "boolean", "default": False}}),
     _probe("reclaim-plan")),
    ("reclaim_schedule",
     "Queue a compression wave for the worker: the plan for a window "
     "(default tonight) or an explicit list of titles from reclaim_plan. "
     "REPLACES the queue with that set. Arthur only.",
     _obj({"window": {"type": "string", "enum": ["tonight", "workday", "next"], "default": "tonight"},
           "hours": {"type": "number"}, "limit": INT,
           "titles": {"type": "array", "items": {"type": "string"}, "minItems": 1,
                      "description": "exact titles from reclaim_plan; omit to use the plan"},
           "refresh": {"type": "boolean", "default": False}, "dry_run": DRY}),
     _action("reclaim-schedule")),
    ("reclaim_pause",
     "Pause the transcode worker (PAUSE flag); a running encode finishes. Arthur only.",
     _obj({"dry_run": DRY}), _action("reclaim-pause")),
    ("reclaim_resume",
     "Resume the transcode worker (remove the PAUSE flag). Arthur only.",
     _obj({"dry_run": DRY}), _action("reclaim-resume")),
    ("reclaim_pilot_ack",
     "Release the pilot gate after Arthur verified playback/HDR of the first "
     "encodes (PILOT_ACK flag). Arthur only.",
     _obj({"dry_run": DRY}), _action("reclaim-pilot-ack")),
    # -- maintenance actions ----------------------------------------------
    ("queue_remove",
     "Remove one queue item; optionally blocklist the release and delete its "
     "download data. `expect` (a queue_health class) makes the runner refuse "
     "if the item now classifies differently.",
     _obj({"app": APP, "id": INT, "blocklist": {"type": "boolean", "default": False},
           "removeData": {"type": "boolean", "default": False},
           "expect": {"type": "string", "enum": list(lib.CLASSES)}, "dry_run": DRY},
          ("app", "id")),
     _action("queue-remove")),
    ("delete_download",
     "Delete a path strictly under /docker/plex/media/downloads (never .Trash). "
     "Refuses paths a qBittorrent torrent still owns unless allow_qbit_owned.",
     _obj({"path": {"type": "string"},
           "allow_qbit_owned": {"type": "boolean", "default": False}, "dry_run": DRY},
          ("path",)),
     _action("delete-download")),
    ("restart_prowlarr",
     "Compose down/up prowlarr, wait for /ping, then indexer testall on both arrs.",
     _obj({"dry_run": DRY}), _action("restart-prowlarr")),
    ("pull_recreate",
     "Pull the latest image for gluetun (with qbittorrent) or byparr and "
     "recreate it, waiting for healthy.",
     _obj({"service": {"type": "string", "enum": ["gluetun", "byparr"]}, "dry_run": DRY},
          ("service",)),
     _action("pull-recreate")),
    ("resurrect_stragglers",
     "Start Exited(255) containers in the known stacks with compose up "
     "--no-recreate. No-op when there are none.",
     _obj({"stacks": {"type": "array", "items": {"type": "string"}}, "dry_run": DRY}),
     _action("resurrect-stragglers")),
]

_TOOLS = {name: (desc, schema, fn) for name, desc, schema, fn in TOOLS}


def tool_list():
    return [{"name": n, "description": d, "inputSchema": s} for n, d, s, _ in TOOLS]


# ---------------------------------------------------------------------------
# JSON-RPC dispatch


def _ok(msg_id, result):
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _err(msg_id, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": msg_id, "error": err}


def dispatch(msg):
    """Handle one JSON-RPC message. Returns (response|None, audit) where
    response is None for notifications and audit is the runner's audit
    record fragment (kind/name/body/dry_run/ok/summary)."""
    audit = {"kind": "mcp", "name": None, "ok": True, "summary": ""}
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" \
            or not isinstance(msg.get("method"), str):
        audit.update(name="invalid", ok=False, summary="invalid JSON-RPC message")
        return _err(msg.get("id") if isinstance(msg, dict) else None,
                    INVALID_REQUEST, "invalid JSON-RPC 2.0 request"), audit
    method = msg["method"]
    msg_id = msg.get("id")
    params = msg.get("params") or {}
    is_notification = "id" not in msg
    audit["name"] = method

    if method == "notifications/initialized" or method.startswith("notifications/"):
        audit["summary"] = method
        return None, audit
    if is_notification:
        audit.update(ok=False, summary="notification for non-notification method %s" % method)
        return None, audit

    if method == "initialize":
        requested = params.get("protocolVersion") if isinstance(params, dict) else None
        version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        audit["summary"] = "initialize (protocol %s)" % version
        return _ok(msg_id, {"protocolVersion": version,
                            "capabilities": {"tools": {"listChanged": False}},
                            "serverInfo": SERVER_INFO,
                            "instructions": INSTRUCTIONS}), audit
    if method == "ping":
        audit["summary"] = "ping"
        return _ok(msg_id, {}), audit
    if method == "tools/list":
        audit["summary"] = "tools/list (%d tools)" % len(TOOLS)
        return _ok(msg_id, {"tools": tool_list()}), audit
    if method == "tools/call":
        if not isinstance(params, dict):
            audit.update(ok=False, summary="tools/call params not an object")
            return _err(msg_id, INVALID_PARAMS, "params must be an object"), audit
        name = params.get("name")
        args = params.get("arguments") or {}
        audit["name"] = "tools/call %s" % name
        if name not in _TOOLS:
            audit.update(ok=False, summary="unknown tool %s" % name)
            return _err(msg_id, INVALID_PARAMS, "unknown tool: %s" % name), audit
        if not isinstance(args, dict):
            audit.update(ok=False, summary="arguments not an object")
            return _err(msg_id, INVALID_PARAMS, "arguments must be an object"), audit
        audit["body"] = args
        audit["dry_run"] = bool(args.get("dry_run", False))
        _, _, fn = _TOOLS[name]
        try:
            result = fn(args)
        except lib.PlexOpsError as e:
            audit.update(ok=False, summary="%s: %s" % (e.code, e.message))
            return _ok(msg_id, {"content": [{"type": "text",
                                             "text": json.dumps(e.envelope(), default=str)}],
                                "isError": True}), audit
        except Exception as e:  # noqa: BLE001 - contract: never a traceback
            env = lib.PlexOpsError("internal", str(e), 500).envelope()
            audit.update(ok=False, summary="internal: %s" % e)
            return _ok(msg_id, {"content": [{"type": "text",
                                             "text": json.dumps(env, default=str)}],
                                "isError": True}), audit
        audit["summary"] = _summarize(name, args, result)
        if isinstance(result, dict):
            audit["before"] = result.get("before")
            audit["after"] = result.get("after")
        payload = result if result is not None else {}
        return _ok(msg_id, {"content": [{"type": "text",
                                         "text": json.dumps(payload, default=str)}],
                            "structuredContent": payload if isinstance(payload, dict) else None,
                            "isError": False}), audit

    audit.update(ok=False, summary="method not found: %s" % method)
    return _err(msg_id, METHOD_NOT_FOUND, "method not found: %s" % method), audit


def _summarize(name, args, result):
    if isinstance(result, dict) and "planned" in result:
        if result.get("dry_run"):
            return "%s dry-run: would %s" % (name, "; ".join(result.get("planned") or []) or "no-op")
        performed = result.get("performed") or []
        return "%s: %s (verified=%s)" % (name, "; ".join(performed) or "no-op",
                                         result.get("verified"))
    if name == "lookup" and isinstance(result, dict):
        return "lookup %s %r: %d matches, resolved=%s" % (
            args.get("app"), args.get("query"), len(result.get("matches") or []),
            result.get("resolved_id"))
    if name == "arr_get":
        return "arr_get %s %s" % (args.get("app"), args.get("path"))
    return "%s ok" % name


def handle(payload):
    """Handle a decoded request body (one message or a batch). Returns
    (http_status, response_body_or_None, audit_records)."""
    if isinstance(payload, list):
        if not payload:
            return 400, _err(None, INVALID_REQUEST, "empty batch"), [
                {"kind": "mcp", "name": "invalid", "ok": False, "summary": "empty batch"}]
        responses, audits = [], []
        for msg in payload:
            resp, audit = dispatch(msg)
            audits.append(audit)
            if resp is not None:
                responses.append(resp)
        if not responses:
            return 202, None, audits
        return 200, responses, audits
    resp, audit = dispatch(payload)
    if resp is None:
        return 202, None, [audit]
    return 200, resp, [audit]
