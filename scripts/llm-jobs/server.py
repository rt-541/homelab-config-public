"""llm-jobs HTTP server: REST + MCP over one stdlib ThreadingHTTPServer.

  GET  /healthz                      no auth
  GET  /api/tiers                    bearer
  POST /api/jobs                     bearer   {"prompt": ..., "tier": "local", "params": {}}
  GET  /api/jobs                     bearer   ?limit=50
  GET  /api/jobs/<id>                bearer   status
  GET  /api/jobs/<id>/result         bearer
  GET  /api/jobs/<id>/artifacts      bearer   files the worker left for the job
  GET  /api/jobs/<id>/artifacts/<n>  bearer   one file, raw bytes
  DELETE /api/jobs/<id>              bearer   cancel
  POST /internal/deliver             bearer (worker key)  {"job_id", "result"|"error"}
  POST /mcp                          bearer   JSON-RPC (tools depend on key role)

Every request except /healthz needs `Authorization: Bearer <key>`. One JSON
audit line per request on stdout (journald under systemd).
"""

import json
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jobs_lib as lib
import mcp

MAX_BODY = 2 * 1024 * 1024


def log(msg):
    sys.stdout.write("%s %s\n" % (lib.utcnow(), msg))
    sys.stdout.flush()


class Handler(BaseHTTPRequestHandler):
    server_version = "llm-jobs/1.0"
    service = None  # set by main()

    def log_message(self, fmt, *args):
        pass

    def _send(self, status, obj):
        body = json.dumps(obj, default=str).encode("utf-8") if obj is not None else b""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _send_file(self, path, ctype):
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    def _key(self):
        auth = self.headers.get("Authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        return self.service.store.key_by_token(token)

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n > MAX_BODY:
            raise lib.JobsError("bad-request", "request body too large", 413)
        raw = self.rfile.read(n) if n else b""
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            raise lib.JobsError("bad-request", "body is not valid JSON", 400)

    def _route(self):
        t0 = time.time()
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = urllib.parse.parse_qs(parsed.query)
        status, out, who = 200, None, "-"
        try:
            if path == "/healthz" and self.command == "GET":
                out = {"ok": True, "tiers": list(self.service.cfg.tiers), "time": lib.utcnow()}
            else:
                key = self._key()
                if not key:
                    raise lib.JobsError("unauthorized", "missing or invalid bearer key", 401)
                who = key["owner"]
                segs = [s for s in path.split("/") if s]
                if path == "/mcp" and self.command == "POST":
                    payload = self._body()
                    if payload is None:
                        raise lib.JobsError("bad-request", "empty MCP body", 400)
                    status, out = mcp.handle(self.service, key, payload)
                elif path == "/api/tiers" and self.command == "GET":
                    out = {"tiers": self.service.tiers()}
                elif path == "/api/jobs" and self.command == "POST":
                    b = self._body() or {}
                    if not isinstance(b, dict):
                        raise lib.JobsError("bad-request", "body must be an object", 400)
                    out = self.service.submit(key, b.get("prompt"), b.get("tier") or "local", b.get("params"))
                    status = 202
                elif path == "/api/jobs" and self.command == "GET":
                    out = {"jobs": self.service.list(key, (qs.get("limit") or ["50"])[0])}
                elif len(segs) >= 3 and segs[0] == "api" and segs[1] == "jobs":
                    jid = segs[2]
                    if len(segs) == 3 and self.command == "GET":
                        out = self.service.status(key, jid)
                    elif len(segs) == 3 and self.command == "DELETE":
                        out = self.service.cancel(key, jid)
                    elif len(segs) == 4 and segs[3] == "result" and self.command == "GET":
                        out = self.service.result(key, jid)
                    elif len(segs) == 4 and segs[3] == "artifacts" and self.command == "GET":
                        job = self.service._own(key, jid)
                        out = {"job_id": jid, "artifacts": self.service.artifacts(job) or []}
                    elif len(segs) == 5 and segs[3] == "artifacts" and self.command == "GET":
                        fpath, ctype = self.service.artifact(key, jid, segs[4])
                        log(json.dumps({"who": who, "method": "GET", "path": path, "status": 200, "ms": int((time.time() - t0) * 1000)}))
                        self._send_file(fpath, ctype)
                        return
                    else:
                        raise lib.JobsError("not-found", "no such route", 404)
                elif path == "/internal/deliver" and self.command == "POST":
                    b = self._body() or {}
                    out = self.service.deliver(key, str(b.get("job_id") or ""), b.get("result"), b.get("error"))
                else:
                    raise lib.JobsError("not-found", "no such route", 404)
        except lib.JobsError as e:
            status, out = e.status, e.envelope()
        except Exception as e:  # noqa: BLE001
            status, out = 500, {"error": "internal", "message": str(e)}
        log(json.dumps({"who": who, "method": self.command, "path": path, "status": status,
                        "ms": int((time.time() - t0) * 1000)}))
        self._send(status, out)

    def do_GET(self):
        self._route()

    def do_POST(self):
        self._route()

    def do_DELETE(self):
        self._route()


def build(cfg, ncl=None, log_fn=log):
    store = lib.Store(cfg.db_path)
    ncl = ncl or lib.Ncl(cfg.ncl)
    dispatcher = lib.Dispatcher(cfg, store, ncl, log=log_fn)
    return lib.Service(cfg, store, dispatcher)


def main():
    cfg = lib.Config()
    service = build(cfg)
    Handler.service = service
    service.dispatcher.start()
    srv = ThreadingHTTPServer((cfg.bind, cfg.port), Handler)
    log("llm-jobs listening on %s:%d tiers=%s db=%s" % (cfg.bind, cfg.port, ",".join(cfg.tiers), cfg.db_path))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.dispatcher.stop_event.set()


if __name__ == "__main__":
    main()
