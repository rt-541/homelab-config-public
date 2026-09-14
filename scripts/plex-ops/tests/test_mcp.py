"""Offline unit tests for the MCP surface (mcp.py) and its runner route.

Dispatch tests mock the probe/action registries; the HTTP tests run the real
RunnerHandler on a loopback port with audit_append captured. No live arr,
docker, or sudo is ever touched.

Run: python3 -m unittest discover -s scripts/plex-ops/tests -v
"""

import http.client
import json
import os
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import plexops_lib as lib  # noqa: E402
import actions  # noqa: E402
import mcp  # noqa: E402
import probes  # noqa: E402
import runner  # noqa: E402

EXPECTED_TOOLS = {
    "lookup", "queue_health", "service_health", "disk", "library_audit", "arr_get",
    "replace_file", "fill_missing", "search", "queue_remove", "delete_download",
    "restart_prowlarr", "pull_recreate", "resurrect_stragglers",
    "reclaim_status", "reclaim_plan", "reclaim_schedule", "reclaim_pause", "reclaim_resume",
    "reclaim_pilot_ack", "title_stats",
}


def rpc(method, params=None, msg_id=1):
    msg = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def text_of(resp):
    return json.loads(resp["result"]["content"][0]["text"])


class DispatchTests(unittest.TestCase):
    def test_initialize_negotiates_known_version(self):
        resp, audit = mcp.dispatch(rpc("initialize", {"protocolVersion": "2024-11-05"}))
        self.assertEqual(resp["result"]["protocolVersion"], "2024-11-05")
        self.assertEqual(resp["result"]["serverInfo"]["name"], "plex-ops-runner")
        self.assertIn("tools", resp["result"]["capabilities"])
        self.assertTrue(audit["ok"])

    def test_initialize_unknown_version_falls_back_to_latest(self):
        resp, _ = mcp.dispatch(rpc("initialize", {"protocolVersion": "1999-01-01"}))
        self.assertEqual(resp["result"]["protocolVersion"], mcp.PROTOCOL_VERSIONS[0])

    def test_tools_list_names_and_schemas(self):
        resp, _ = mcp.dispatch(rpc("tools/list"))
        tools = resp["result"]["tools"]
        self.assertEqual({t["name"] for t in tools}, EXPECTED_TOOLS)
        for t in tools:
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertTrue(t["description"])
        # every whitelisted REST action has a tool and vice versa
        self.assertEqual({n.replace("_", "-") for n in EXPECTED_TOOLS
                          if n not in ("lookup", "queue_health", "service_health", "disk",
                                       "library_audit", "arr_get", "reclaim_status",
                                       "reclaim_plan", "title_stats")},
                         set(actions.ACTIONS))

    def test_notification_returns_none(self):
        resp, audit = mcp.dispatch({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertIsNone(resp)
        self.assertTrue(audit["ok"])

    def test_ping(self):
        resp, _ = mcp.dispatch(rpc("ping"))
        self.assertEqual(resp["result"], {})

    def test_unknown_method_is_method_not_found(self):
        resp, audit = mcp.dispatch(rpc("resources/list"))
        self.assertEqual(resp["error"]["code"], mcp.METHOD_NOT_FOUND)
        self.assertFalse(audit["ok"])

    def test_invalid_message_is_invalid_request(self):
        resp, _ = mcp.dispatch({"id": 3, "method": "ping"})
        self.assertEqual(resp["error"]["code"], mcp.INVALID_REQUEST)
        self.assertEqual(resp["id"], 3)

    def test_unknown_tool_is_invalid_params(self):
        resp, _ = mcp.dispatch(rpc("tools/call", {"name": "rm_rf", "arguments": {}}))
        self.assertEqual(resp["error"]["code"], mcp.INVALID_PARAMS)

    def test_probe_tool_converts_arguments_to_string_params(self):
        seen = {}

        def fake(params):
            seen.update(params)
            return {"probe": "library-audit", "titles_checked": 3}
        with mock.patch.dict(probes.PROBES, {"library-audit": fake}):
            resp, audit = mcp.dispatch(rpc("tools/call", {
                "name": "library_audit", "arguments": {"app": "sonarr", "chunk": 2}}))
        self.assertEqual(seen, {"app": "sonarr", "chunk": "2"})
        self.assertFalse(resp["result"]["isError"])
        self.assertEqual(text_of(resp)["titles_checked"], 3)
        self.assertEqual(resp["result"]["structuredContent"]["titles_checked"], 3)
        self.assertEqual(audit["name"], "tools/call library_audit")

    def test_lookup_maps_query_to_q(self):
        seen = {}

        def fake(params):
            seen.update(params)
            return {"probe": "lookup", "matches": [], "resolved_id": None}
        with mock.patch.dict(probes.PROBES, {"lookup": fake}):
            _, audit = mcp.dispatch(rpc("tools/call", {
                "name": "lookup", "arguments": {"app": "sonarr", "query": "The Show", "season": 3}}))
        self.assertEqual(seen, {"app": "sonarr", "q": "The Show", "season": "3"})
        self.assertIn("0 matches", audit["summary"])

    def test_action_tool_passes_body_and_audits_dry_run(self):
        seen = {}

        def fake(body):
            seen.update(body)
            return {"action": "replace-file", "dry_run": True, "before": {"b": 1},
                    "planned": ["DELETE x"], "performed": [], "after": None, "verified": None}
        with mock.patch.dict(actions.ACTIONS, {"replace-file": fake}):
            resp, audit = mcp.dispatch(rpc("tools/call", {
                "name": "replace_file",
                "arguments": {"app": "sonarr", "episode_id": 200, "dry_run": True}}))
        self.assertEqual(seen, {"app": "sonarr", "episode_id": 200, "dry_run": True})
        self.assertTrue(audit["dry_run"])
        self.assertEqual(audit["body"], seen)
        self.assertEqual(audit["before"], {"b": 1})
        self.assertIn("dry-run", audit["summary"])
        self.assertFalse(resp["result"]["isError"])

    def test_tool_refusal_is_isError_not_rpc_error(self):
        def fake(body):
            raise lib.PlexOpsError("verify-failed", "gone", 409, {"missing_ids": [1]})
        with mock.patch.dict(actions.ACTIONS, {"fill-missing": fake}):
            resp, audit = mcp.dispatch(rpc("tools/call", {
                "name": "fill_missing", "arguments": {"app": "radarr", "movie_id": 1}}))
        self.assertNotIn("error", resp)
        self.assertTrue(resp["result"]["isError"])
        env = text_of(resp)
        self.assertEqual(env["error"], "verify-failed")
        self.assertEqual(env["detail"], {"missing_ids": [1]})
        self.assertFalse(audit["ok"])

    def test_unexpected_exception_is_internal_envelope(self):
        def fake(body):
            raise RuntimeError("boom")
        with mock.patch.dict(actions.ACTIONS, {"search": fake}):
            resp, _ = mcp.dispatch(rpc("tools/call", {"name": "search", "arguments": {"app": "sonarr"}}))
        self.assertTrue(resp["result"]["isError"])
        self.assertEqual(text_of(resp)["error"], "internal")
        self.assertEqual(text_of(resp)["message"], "boom")

    def test_arr_get_forwards_and_strips_api_key(self):
        with mock.patch.object(lib, "arr_get_raw",
                               return_value=(200, "application/json", b'{"a": 1}')) as raw:
            resp, _ = mcp.dispatch(rpc("tools/call", {"name": "arr_get", "arguments": {
                "app": "sonarr", "path": "/api/v3/wanted/missing",
                "params": {"pageSize": 5, "apikey": "leak"}}}))
        raw.assert_called_once_with("sonarr", "/api/v3/wanted/missing?pageSize=5")
        self.assertEqual(text_of(resp), {"a": 1})

    def test_arr_get_denies_credential_endpoint_and_dot_segments(self):
        with mock.patch.object(lib, "arr_get_raw") as raw:
            for path in ("/api/v3/config/host", "/api/v3/../config/host",
                         "/api/v3/%2e%2e/x", "/api/v2/system", "api/v3/x"):
                resp, _ = mcp.dispatch(rpc("tools/call", {"name": "arr_get", "arguments": {
                    "app": "radarr", "path": path}}))
                self.assertTrue(resp["result"]["isError"], path)
            raw.assert_not_called()

    def test_arr_get_upstream_error_is_isError(self):
        with mock.patch.object(lib, "arr_get_raw", return_value=(500, "text/plain", b"nope")):
            resp, _ = mcp.dispatch(rpc("tools/call", {"name": "arr_get", "arguments": {
                "app": "radarr", "path": "/api/v3/movie"}}))
        self.assertTrue(resp["result"]["isError"])
        self.assertEqual(text_of(resp)["error"], "upstream-error")

    def test_handle_batch_and_notification_only(self):
        status, body, audits = mcp.handle([rpc("ping", msg_id=1),
                                           {"jsonrpc": "2.0", "method": "notifications/initialized"}])
        self.assertEqual(status, 200)
        self.assertEqual(len(body), 1)
        self.assertEqual(len(audits), 2)
        status, body, _ = mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual((status, body), (202, None))
        status, body, _ = mcp.handle([])
        self.assertEqual(status, 400)


class HttpRouteTests(unittest.TestCase):
    TOKEN = "t" * 40

    def setUp(self):
        self.audit = []
        for target, kwargs in (("audit_append", {"side_effect": self.audit.append}),
                               ("ensure_log_dir", {})):
            p = mock.patch.object(lib, target, **kwargs)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(runner, "_TOKEN", self.TOKEN)
        p.start()
        self.addCleanup(p.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), runner.RunnerHandler)
        self.server.daemon_threads = True
        t = threading.Thread(target=self.server.serve_forever, daemon=True)
        t.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]

    def request(self, method, path, body=None, auth=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = "Bearer " + self.TOKEN
        data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        return resp.status, (json.loads(raw) if raw else None)

    def test_requires_auth(self):
        status, body = self.request("POST", "/mcp", rpc("ping"), auth=False)
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "unauthorized")
        self.assertEqual(self.audit[-1]["kind"], "auth")

    def test_get_is_405(self):
        status, body = self.request("GET", "/mcp")
        self.assertEqual(status, 405)
        self.assertEqual(self.audit[-1]["kind"], "mcp")

    def test_initialize_roundtrip(self):
        status, body = self.request("POST", "/mcp", rpc("initialize", {"protocolVersion": "2025-06-18"}))
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["serverInfo"]["name"], "plex-ops-runner")
        self.assertEqual(self.audit[-1]["name"], "initialize")
        self.assertEqual(self.audit[-1]["status"], 200)

    def test_notification_is_202_with_empty_body(self):
        status, body = self.request("POST", "/mcp",
                                    {"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual((status, body), (202, None))

    def test_bad_json_is_parse_error(self):
        status, body = self.request("POST", "/mcp", b"{not json")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], mcp.PARSE_ERROR)

    def test_tools_call_is_audited_like_an_action(self):
        def fake(body):
            return {"action": "search", "dry_run": False, "before": {}, "planned": ["p"],
                    "performed": ["p"], "after": {"command_id": 1}, "verified": True}
        with mock.patch.dict(actions.ACTIONS, {"search": fake}):
            status, body = self.request("POST", "/mcp", rpc("tools/call", {
                "name": "search", "arguments": {"app": "sonarr", "series_id": 1}}))
        self.assertEqual(status, 200)
        self.assertFalse(body["result"]["isError"])
        rec = self.audit[-1]
        self.assertEqual((rec["kind"], rec["name"], rec["status"], rec["ok"]),
                         ("mcp", "tools/call search", 200, True))
        self.assertEqual(rec["body"], {"app": "sonarr", "series_id": 1})
        self.assertEqual(rec["after"], {"command_id": 1})
        self.assertIn("duration_ms", rec)


if __name__ == "__main__":
    unittest.main()
