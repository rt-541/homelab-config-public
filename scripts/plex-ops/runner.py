#!/usr/bin/env python3
"""plex-ops action-runner HTTP service (nemesis side).

Python 3.9 stdlib only. Binds $BIND:$PORT (default 0.0.0.0:8377) and serves
the NanoClaw plex-ops agent:

    GET  /healthz                      liveness, NO auth, not audit-logged
    GET  /probe/<name>                 deterministic read-only probes
    GET  /arr/<app>/api/v3/...         GET-only Sonarr/Radarr passthrough
    POST /action/<name>                whitelisted, re-verifying actions

Everything except /healthz requires `Authorization: Bearer <token>`; the
token is PLEXOPS_TOKEN from the env file at $RUNNER_ENV (default
/etc/plex-ops/runner.env). Every authed call - success, failure, and every
auth rejection - is audit-logged via plexops_lib.audit_append.

Interface contract: scripts/plex-ops/CONTRACT.md. The runner itself never
mutates anything; all side effects live in actions.py.
"""

import hmac
import json
import os
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import plexops_lib as lib
import probes
import actions

MAX_BODY_BYTES = 1024 * 1024  # nothing legitimate is close to 1 MiB

# Loaded once in main(); rotation = edit env file + restart the service.
_TOKEN = None


# ---------------------------------------------------------------------------
# Helpers


def _summarize_probe(name, result):
    """One audit line for a probe result - counts, never the full payload."""
    if name == "queue-health":
        parts = []
        for app in ("sonarr", "radarr"):
            info = (result.get("apps") or {}).get(app)
            if not isinstance(info, dict) or "error" in info:
                parts.append("%s: error" % app)
                continue
            counts = info.get("counts") or {}
            flagged = {k: v for k, v in counts.items() if v and k != "unknown"}
            parts.append("%s: %d items, flagged %s" % (app, info.get("total", 0),
                                                       flagged or "none"))
        return "queue-health: " + "; ".join(parts)
    if name == "service-health":
        unhealthy = [n for n, c in (result.get("containers") or {}).items()
                     if c.get("health") == "unhealthy" or c.get("state") != "running"]
        return "service-health: prowlarr_ping=%s, stragglers=%d, unhealthy=%s, vpn=%s" % (
            (result.get("prowlarr") or {}).get("ping_ok"),
            len(result.get("stragglers") or []),
            unhealthy or "none",
            (result.get("vpn") or {}).get("egress_ok"),
        )
    if name == "disk":
        parts = ["%s %.1f%%" % (m, d.get("used_percent", 0.0))
                 for m, d in sorted((result.get("mounts") or {}).items())]
        return "disk: " + ", ".join(parts)
    if name == "library-audit":
        counts = result.get("counts") or {}
        flagged = {k: v for k, v in counts.items() if v}
        return "library-audit %s chunk %s/%s: %d titles, %s" % (
            result.get("app"), result.get("chunk"), result.get("chunks"),
            result.get("titles_checked", 0), flagged or "clean")
    return "probe %s ok" % name


def _summarize_action(name, result):
    performed = result.get("performed")
    if result.get("dry_run"):
        return "%s dry-run: would %s" % (name, "; ".join(result.get("planned") or []) or "no-op")
    return "%s: %s (verified=%s)" % (
        name, "; ".join(performed) if performed else "no-op", result.get("verified"))


# ---------------------------------------------------------------------------
# Request handler


class RunnerHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "plex-ops-runner"
    sys_version = ""

    # -- low-level plumbing -------------------------------------------------

    def log_message(self, fmt, *args):  # audit log replaces stderr noise
        pass

    def _send_json(self, status, obj):
        body = json.dumps(obj, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        # HEAD responses carry headers (incl. the GET Content-Length) but no
        # body - writing one would desynchronize HTTP/1.1 keep-alive clients.
        if self.command == "HEAD":
            return
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_raw(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type or "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _authed(self):
        """Constant-time bearer check. The header value is never logged.
        Compared as UTF-8 bytes: compare_digest raises TypeError on non-ASCII
        str input, and the header value is attacker-controllable."""
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False
        candidate = auth[len("Bearer "):].strip()
        try:
            return hmac.compare_digest(candidate.encode("utf-8"),
                                       _TOKEN.encode("utf-8"))
        except Exception:
            return False

    def _read_body(self):
        """Parsed JSON object body; empty body -> {}. Raises PlexOpsError 400."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY_BYTES:
            raise lib.PlexOpsError("bad-request", "request body too large", 400)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            body = json.loads(raw)
        except ValueError:
            raise lib.PlexOpsError("bad-request", "request body is not valid JSON", 400)
        if not isinstance(body, dict):
            raise lib.PlexOpsError("bad-request", "request body must be a JSON object", 400)
        return body

    def _audit(self, record):
        record.setdefault("remote", self.client_address[0])
        record.setdefault("method", self.command)
        record.setdefault("path", self.path)
        lib.audit_append(record)

    # -- routing ------------------------------------------------------------

    def _route(self):
        """Dispatch one request. Every authed call is timed + audit-logged."""
        parsed = urllib.parse.urlsplit(self.path)
        segs = [s for s in parsed.path.split("/") if s]

        # /healthz: unauthed liveness only - reveals and logs nothing.
        if parsed.path == "/healthz":
            if self.command != "GET":
                self._send_json(405, lib.PlexOpsError(
                    "method-not-allowed", "healthz is GET-only", 405).envelope())
                return
            self._send_json(200, {"ok": True, "service": "plex-ops-runner",
                                  "ts": lib.now_iso()})
            return

        # Everything else: bearer auth first.
        if not self._authed():
            env = lib.PlexOpsError("unauthorized", "bearer auth failed", 401).envelope()
            self._audit({"kind": "auth", "name": None, "status": 401, "ok": False,
                         "summary": "auth failure from %s" % self.client_address[0]})
            self._send_json(401, env)
            return

        params = {k: v[-1] for k, v in urllib.parse.parse_qs(parsed.query).items()}

        if segs and segs[0] == "probe":
            self._handle_probe(segs, params)
        elif segs and segs[0] == "arr":
            self._handle_passthrough(segs, parsed)
        elif segs and segs[0] == "action":
            self._handle_action(segs, params)
        else:
            env = lib.PlexOpsError("not-found", "unknown route: %s" % parsed.path,
                                   404).envelope()
            # kind "route", not "auth": the request PASSED bearer auth and
            # must not pollute auth-failure filters (CONTRACT.md section 6).
            self._audit({"kind": "route", "name": None, "params": params,
                         "status": 404, "ok": False,
                         "summary": "unknown route %s %s" % (self.command, parsed.path)})
            self._send_json(404, env)

    # -- surfaces -----------------------------------------------------------

    def _handle_probe(self, segs, params):
        name = segs[1] if len(segs) == 2 else None
        record = {"kind": "probe", "name": name, "params": params}
        t0 = time.time()
        try:
            if self.command != "GET":
                raise lib.PlexOpsError("method-not-allowed", "probes are GET-only", 405)
            fn = probes.PROBES.get(name) if name else None
            if fn is None:
                raise lib.PlexOpsError("not-found", "unknown probe: %s" % name, 404)
            result = fn(params)
            payload = dict(result)
            payload["ok"] = True
            record.update(status=200, ok=True,
                          summary=_summarize_probe(name, result))
            self._send_json(200, payload)
        except lib.PlexOpsError as e:
            record.update(status=e.status, ok=False, summary=e.message)
            self._send_json(e.status, e.envelope())
        except Exception as e:  # noqa: BLE001 - contract: 500 envelope
            err = lib.PlexOpsError("internal", str(e), 500)
            record.update(status=500, ok=False, summary=str(e))
            self._send_json(500, err.envelope())
        record["duration_ms"] = int((time.time() - t0) * 1000)
        self._audit(record)

    def _handle_passthrough(self, segs, parsed):
        record = {"kind": "passthrough", "name": segs[1] if len(segs) >= 2 else None}
        t0 = time.time()
        try:
            app = segs[1] if len(segs) >= 2 else None
            if app not in lib.PASSTHROUGH_APPS:
                raise lib.PlexOpsError("not-found", "unknown app: %s" % app, 404)
            # Reject dot segments, raw or percent-encoded (unquote until
            # stable so %2e and double-encodings cannot slip through): the
            # upstream Kestrel server normalizes them, which would let a
            # forwarded path escape /api/v3.
            for seg in segs[2:]:
                decoded = seg
                prev = None
                while prev != decoded:
                    prev, decoded = decoded, urllib.parse.unquote(decoded)
                if decoded in (".", ".."):
                    raise lib.PlexOpsError(
                        "not-found", "dot segments are not allowed in the "
                        "passthrough path", 404)
            rest = "/" + "/".join(segs[2:])
            if not (rest == "/api/v3" or rest.startswith("/api/v3/")):
                raise lib.PlexOpsError(
                    "not-found", "passthrough path must start with /api/v3/", 404)
            # Denylist: endpoints whose response body carries credentials
            # (config/host echoes the arr's own apiKey) never leave the box.
            for deny in lib.PASSTHROUGH_DENY:
                if rest == deny or rest.startswith(deny + "/"):
                    raise lib.PlexOpsError(
                        "not-found",
                        "passthrough endpoint is denied (exposes credentials)",
                        404)
            if self.command != "GET":
                raise lib.PlexOpsError(
                    "method-not-allowed", "passthrough is GET-only", 405)
            # Strip any client-supplied api key; the runner injects its own.
            # keep_blank_values: present-but-empty params must survive the
            # round trip (the query is otherwise forwarded as sent).
            pairs = [(k, v) for k, v in urllib.parse.parse_qsl(
                        parsed.query, keep_blank_values=True)
                     if k.lower() not in ("apikey", "api_key", "api-key")]
            path_qs = rest + ("?" + urllib.parse.urlencode(pairs) if pairs else "")
            status, ctype, body = lib.arr_get_raw(app, path_qs)
            record.update(status=status, ok=200 <= status < 300,
                          summary="GET %s %s -> HTTP %d (%d bytes)"
                                  % (app, rest, status, len(body)))
            self._send_raw(status, ctype, body)
        except lib.PlexOpsError as e:
            record.update(status=e.status, ok=False, summary=e.message)
            self._send_json(e.status, e.envelope())
        except Exception as e:  # noqa: BLE001
            err = lib.PlexOpsError("internal", str(e), 500)
            record.update(status=500, ok=False, summary=str(e))
            self._send_json(500, err.envelope())
        record["duration_ms"] = int((time.time() - t0) * 1000)
        self._audit(record)

    def _handle_action(self, segs, params):
        name = segs[1] if len(segs) == 2 else None
        record = {"kind": "action", "name": name, "params": params}
        t0 = time.time()
        try:
            if self.command != "POST":
                raise lib.PlexOpsError("method-not-allowed", "actions are POST-only", 405)
            fn = actions.ACTIONS.get(name) if name else None
            if fn is None:
                raise lib.PlexOpsError("not-found", "unknown action: %s" % name, 404)
            body = self._read_body()
            record["body"] = body
            record["dry_run"] = bool(body.get("dry_run", False))
            result = fn(body)
            payload = dict(result)
            payload["ok"] = True
            record.update(status=200, ok=True,
                          summary=_summarize_action(name, result),
                          before=result.get("before"), after=result.get("after"))
            self._send_json(200, payload)
        except lib.PlexOpsError as e:
            record.update(status=e.status, ok=False, summary=e.message)
            self._send_json(e.status, e.envelope())
        except Exception as e:  # noqa: BLE001
            err = lib.PlexOpsError("internal", str(e), 500)
            record.update(status=500, ok=False, summary=str(e))
            self._send_json(500, err.envelope())
        record["duration_ms"] = int((time.time() - t0) * 1000)
        self._audit(record)

    # -- HTTP verbs all feed one router (405s decided per-surface) ----------

    def do_GET(self):
        self._route()

    def do_POST(self):
        self._route()

    def do_PUT(self):
        self._route()

    def do_DELETE(self):
        self._route()

    def do_PATCH(self):
        self._route()

    def do_HEAD(self):
        self._route()


# ---------------------------------------------------------------------------
# Entrypoint


def main():
    global _TOKEN
    env_path = os.environ.get("RUNNER_ENV") or lib.ENV_FILE
    try:
        _TOKEN = lib.runner_token(env_path)
    except lib.PlexOpsError as e:
        lib.die(e.message)
    try:
        port = int(os.environ.get("PORT") or lib.RUNNER_PORT)
    except ValueError:
        lib.die("PORT must be an integer, got %r" % os.environ.get("PORT"))
    bind = os.environ.get("BIND") or "0.0.0.0"
    lib.ensure_log_dir()

    server = ThreadingHTTPServer((bind, port), RunnerHandler)
    server.daemon_threads = True
    lib.log("plex-ops runner listening on %s:%d (env file: %s)" % (bind, port, env_path))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        lib.log("shutting down")
        server.server_close()


if __name__ == "__main__":
    main()
