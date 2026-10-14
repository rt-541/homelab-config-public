"""Unit tests for llm-jobs: storage, quotas, dispatcher (ncl mocked), MCP and
the HTTP surface. Run: python3 -m unittest discover -s scripts/llm-jobs/tests"""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import jobs_lib as lib  # noqa: E402
import mcp  # noqa: E402
import server  # noqa: E402


class FakeNcl:
    def __init__(self):
        self.created, self.cancelled, self.fail_create = [], [], False

    def group_id(self, folder):
        return "ag-" + folder

    def create_task(self, group_id, name, prompt):
        if self.fail_create:
            raise lib.JobsError("ncl-error", "boom", 502)
        tid = "t-%d" % (len(self.created) + 1)
        self.created.append((group_id, name, prompt, tid))
        return tid

    def cancel_task(self, group_id, task_id):
        self.cancelled.append(task_id)
        return True


def make(tmp, **env):
    e = {"LLMJOBS_DB": os.path.join(tmp, "jobs.db"), "LLMJOBS_POLL_S": "0.05", "LLMJOBS_ARTIFACTS": os.path.join(tmp, "artifacts")}
    e.update(env)
    cfg = lib.Config(e)
    store = lib.Store(cfg.db_path)
    ncl = FakeNcl()
    disp = lib.Dispatcher(cfg, store, ncl, log=lambda m: None)
    return lib.Service(cfg, store, disp), ncl


class Artifacts(unittest.TestCase):
    """Tiers flagged with artifacts: the worker writes files under <artifacts>/<job_id>/, the owner lists and fetches them."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        tiers = json.dumps({"local": {"group": "jobs-local"},
                            "render": {"group": "jobs-render", "artifacts": True, "timeout_s": 3600,
                                       "contract_note": "Write files to /workspace/extra/artifacts/{job_id}/."}})
        self.art = os.path.join(self.tmp, "artifacts")
        self.svc, self.ncl = make(self.tmp, LLMJOBS_TIERS=tiers, LLMJOBS_ARTIFACTS=self.art)
        _, key = self.svc.store.issue_key("arthur", "user", ("local", "render"))
        _, other = self.svc.store.issue_key("dana", "user", ("local", "render"))
        _, wkey = self.svc.store.issue_key("worker", "worker", ())
        self.k, self.o, self.w = (self.svc.store.key_by_token(t) for t in (key, other, wkey))

    def _job_with_files(self):
        jid = self.svc.submit(self.k, '{"views": ["north"]}', "render")["job_id"]
        self.svc.dispatcher.tick()
        d = os.path.join(self.art, jid)
        os.makedirs(d)
        with open(os.path.join(d, "north.png"), "wb") as f:
            f.write(b"\x89PNG fake")
        with open(os.path.join(d, "render.json"), "w") as f:
            f.write("{}")
        self.svc.deliver(self.w, jid, result="rendered north")
        return jid

    def test_contract_note_reaches_the_worker(self):
        jid = self.svc.submit(self.k, "x", "render")["job_id"]
        self.svc.dispatcher.tick()
        prompt = self.ncl.created[0][2]
        self.assertIn("/workspace/extra/artifacts/%s/" % jid, prompt)

    def test_result_lists_artifacts_with_urls(self):
        jid = self._job_with_files()
        res = self.svc.result(self.k, jid)
        names = [a["name"] for a in res["artifacts"]]
        self.assertEqual(names, ["north.png", "render.json"])
        self.assertTrue(res["artifacts"][0]["url"].endswith("/api/jobs/%s/artifacts/north.png" % jid))
        self.assertEqual(res["artifacts"][0]["bytes"], 9)

    def test_plain_tier_result_has_no_artifacts_key(self):
        jid = self.svc.submit(self.k, "x", "local")["job_id"]
        self.svc.dispatcher.tick()
        self.svc.deliver(self.w, jid, result="ok")
        self.assertNotIn("artifacts", self.svc.result(self.k, jid))

    def test_artifact_owner_scoped_and_safe(self):
        jid = self._job_with_files()
        path, ctype = self.svc.artifact(self.k, jid, "north.png")
        self.assertEqual(ctype, "image/png")
        with open(path, "rb") as f:
            self.assertTrue(f.read().startswith(b"\x89PNG"))
        with self.assertRaises(lib.JobsError):
            self.svc.artifact(self.o, jid, "north.png")
        for bad in ("../jobs.db", "..", ".hidden", "a/b.png", "missing.png"):
            with self.assertRaises(lib.JobsError):
                self.svc.artifact(self.k, jid, bad)

    def test_request_photo_forwards_to_arbiter(self):
        calls = []

        class FakeArb:
            def post(self, body):
                calls.append(body)
                return {"id": "p-1", "position": 1}

            def get(self, pid):
                return {"id": pid, "status": "done", "error": None, "seconds": 90.0}
        self.svc.arbiter = FakeArb()
        jid = self.svc.submit(self.k, "x", "render")["job_id"]
        self.svc.dispatcher.tick()
        d = os.path.join(self.art, jid)
        os.makedirs(d)
        open(os.path.join(d, "north.png"), "wb").write(b"png")
        r = self.svc.request_photo(self.w, jid, "north.png", None)
        self.assertEqual(r["photo_id"], "p-1")
        self.assertEqual(calls[0]["src"], os.path.join(d, "north.png"))
        self.assertEqual(calls[0]["dst"], os.path.join(d, "photo-north.png"))
        self.assertEqual(self.svc.photo_status(self.w, "p-1")["status"], "done")
        with self.assertRaises(lib.JobsError):
            self.svc.request_photo(self.k, jid, "north.png", None)        # user keys cannot
        with self.assertRaises(lib.JobsError):
            self.svc.request_photo(self.w, jid, "../x.png", None)          # names are checked
        with self.assertRaises(lib.JobsError):
            self.svc.request_photo(self.w, jid, "missing.png", None)
        self.svc.deliver(self.w, jid, result="done")
        with self.assertRaises(lib.JobsError):
            self.svc.request_photo(self.w, jid, "north.png", None)         # only while the job runs

    def test_sweep_removes_artifacts_of_swept_jobs(self):
        jid = self._job_with_files()
        self.svc.store.conn.execute("update jobs set created_at='2000-01-01T00:00:00Z' where id=?", (jid,))
        self.svc.store.conn.commit()
        self.svc.dispatcher.sweep_now()
        self.assertFalse(os.path.exists(os.path.join(self.art, jid)))


class StoreAndService(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.svc, self.ncl = make(self.tmp)
        self.kid, self.key = self.svc.store.issue_key("arthur", "user", ("local", "claude"), 3, 1000)
        self.k = self.svc.store.key_by_token(self.key)
        self.wid, self.wkey = self.svc.store.issue_key("worker", "worker", ())
        self.w = self.svc.store.key_by_token(self.wkey)

    def test_key_hashing_and_revoke(self):
        self.assertIsNotNone(self.k)
        self.assertIsNone(self.svc.store.key_by_token("nope"))
        self.assertTrue(self.svc.store.revoke_key(self.kid))
        self.assertIsNone(self.svc.store.key_by_token(self.key))

    def test_set_key_tiers(self):
        with self.assertRaises(lib.JobsError):
            self.svc.submit(self.k, "x", "render")
        self.assertTrue(self.svc.store.set_key_tiers(self.kid, ["local", "claude", "render"]))
        self.assertIn("render", self.svc.store.key_by_token(self.key)["tiers"])

    def test_submit_status_dispatch_deliver_result(self):
        r = self.svc.submit(self.k, "Say hello", "local")
        self.assertEqual(r["status"], "queued"); self.assertEqual(r["position"], 1)
        self.svc.dispatcher.tick()
        st = self.svc.status(self.k, r["job_id"])
        self.assertEqual(st["status"], "running"); self.assertIsNone(st["position"])
        gid, name, prompt, tid = self.ncl.created[0]
        self.assertEqual(gid, "ag-jobs-local"); self.assertIn(r["job_id"], name); self.assertIn("deliver_result", prompt)
        self.assertIn("Say hello", prompt)
        d = self.svc.deliver(self.w, r["job_id"], result="hello")
        self.assertTrue(d["accepted"])
        res = self.svc.result(self.k, r["job_id"])
        self.assertEqual(res["status"], "done"); self.assertEqual(res["result"], "hello")
        # second delivery is a no-op
        self.assertFalse(self.svc.deliver(self.w, r["job_id"], result="again")["accepted"])

    def test_one_running_per_tier_and_positions(self):
        a = self.svc.submit(self.k, "a", "local"); b = self.svc.submit(self.k, "b", "local"); c = self.svc.submit(self.k, "c", "claude")
        self.svc.dispatcher.tick()
        self.assertEqual(self.svc.status(self.k, a["job_id"])["status"], "running")
        self.assertEqual(self.svc.status(self.k, b["job_id"])["status"], "queued")
        self.assertEqual(self.svc.status(self.k, b["job_id"])["position"], 1)
        self.assertEqual(self.svc.status(self.k, c["job_id"])["status"], "running")  # other tier runs in parallel
        self.svc.deliver(self.w, a["job_id"], result="done a")
        self.svc.dispatcher.tick()
        self.assertEqual(self.svc.status(self.k, b["job_id"])["status"], "running")

    def test_tier_permission_and_quota(self):
        kid, key = self.svc.store.issue_key("friend", "user", ("local",), 1, 10)
        k = self.svc.store.key_by_token(key)
        with self.assertRaises(lib.JobsError) as cm:
            self.svc.submit(k, "x", "claude")
        self.assertEqual(cm.exception.status, 403)
        self.svc.submit(k, "x", "local")
        with self.assertRaises(lib.JobsError) as cm:
            self.svc.submit(k, "y", "local")
        self.assertEqual(cm.exception.code, "quota")
        with self.assertRaises(lib.JobsError):
            self.svc.submit(k, "", "local")
        with self.assertRaises(lib.JobsError):
            self.svc.submit(k, "x", "nope")

    def test_tier_daily_cap_is_shared_across_keys(self):
        tiers = json.dumps({"local": {"group": "jobs-local", "timeout_s": 60},
                            "claude": {"group": "jobs-claude", "timeout_s": 60, "daily_jobs": 2, "daily_tokens": 50}})
        svc, _ = make(tempfile.mkdtemp(), LLMJOBS_TIERS=tiers)
        _, ka = svc.store.issue_key("a", "user", ("local", "claude"), 100, 10 ** 9)
        _, kb = svc.store.issue_key("b", "user", ("claude",), 100, 10 ** 9)
        ka, kb = svc.store.key_by_token(ka), svc.store.key_by_token(kb)
        svc.submit(ka, "x", "claude")
        svc.submit(kb, "x", "claude")
        with self.assertRaises(lib.JobsError) as cm:  # third job on the tier, whichever key
            svc.submit(ka, "x", "claude")
        self.assertEqual((cm.exception.code, cm.exception.status), ("quota", 429))
        self.assertIn("tier", cm.exception.message)
        svc.submit(ka, "x", "local")  # other tier unaffected
        # the token half counts every key's delivered output on the tier
        svc2, _ = make(tempfile.mkdtemp(), LLMJOBS_TIERS=tiers)
        _, kc = svc2.store.issue_key("c", "user", ("claude",), 100, 10 ** 9)
        kc = svc2.store.key_by_token(kc)
        jid = svc2.submit(kc, "x", "claude")["job_id"]
        svc2.store.finish(jid, result="r" * 400)  # 100 tokens > cap of 50
        with self.assertRaises(lib.JobsError) as cm:
            svc2.submit(kc, "x", "claude")
        self.assertIn("token", cm.exception.message)
        caps = {t["tier"]: t for t in svc.tiers()}
        self.assertEqual(caps["claude"]["daily_jobs"], 2)
        self.assertNotIn("daily_jobs", caps["local"])

    def test_owner_scoping(self):
        r = self.svc.submit(self.k, "secret", "local")
        _, okey = self.svc.store.issue_key("other", "user", ("local",))
        o = self.svc.store.key_by_token(okey)
        with self.assertRaises(lib.JobsError) as cm:
            self.svc.status(o, r["job_id"])
        self.assertEqual(cm.exception.status, 404)
        with self.assertRaises(lib.JobsError):
            self.svc.deliver(self.k, r["job_id"], result="not a worker")

    def test_cancel_running_cancels_task(self):
        r = self.svc.submit(self.k, "slow", "local")
        self.svc.dispatcher.tick()
        c = self.svc.cancel(self.k, r["job_id"])
        self.assertTrue(c["cancelled"]); self.assertEqual(self.ncl.cancelled, ["t-1"])
        self.assertEqual(self.svc.status(self.k, r["job_id"])["status"], "cancelled")
        self.assertFalse(self.svc.cancel(self.k, r["job_id"])["cancelled"])

    def test_timeout_fails_job(self):
        self.svc.cfg.tiers["local"]["timeout_s"] = 0
        r = self.svc.submit(self.k, "slow", "local")
        self.svc.dispatcher.tick()
        import time; time.sleep(1.1)
        self.svc.dispatcher.tick()
        st = self.svc.status(self.k, r["job_id"])
        self.assertEqual(st["status"], "failed"); self.assertIn("timed out", st["error"])
        self.assertEqual(self.ncl.cancelled, ["t-1"])

    def test_dispatch_failure_marks_failed(self):
        self.ncl.fail_create = True
        r = self.svc.submit(self.k, "x", "local")
        self.svc.dispatcher.tick()
        self.assertEqual(self.svc.status(self.k, r["job_id"])["status"], "failed")

    def test_worker_prompt_limits(self):
        r = self.svc.submit(self.k, "x", "local", {"max_words": 40, "format": "json"})
        job = self.svc.store.get_job(r["job_id"])
        p = lib.worker_prompt(job, {})
        self.assertIn("under 40 words", p); self.assertIn("json", p)


class Mcp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.svc, self.ncl = make(self.tmp)
        _, key = self.svc.store.issue_key("arthur", "user", ("local",))
        self.k = self.svc.store.key_by_token(key)
        _, wkey = self.svc.store.issue_key("w", "worker", ())
        self.w = self.svc.store.key_by_token(wkey)

    def rpc(self, key, method, params=None, mid=1):
        st, body = mcp.handle(self.svc, key, {"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})
        return st, body

    def test_initialize_and_tools_by_role(self):
        st, b = self.rpc(self.k, "initialize", {"protocolVersion": "2025-06-18"})
        self.assertEqual(b["result"]["protocolVersion"], "2025-06-18")
        names = {t["name"] for t in self.rpc(self.k, "tools/list")[1]["result"]["tools"]}
        self.assertIn("submit_job", names); self.assertNotIn("deliver_result", names)
        wnames = {t["name"] for t in self.rpc(self.w, "tools/list")[1]["result"]["tools"]}
        self.assertEqual(wnames, {"deliver_result", "request_photo", "photo_status"})

    def test_round_trip(self):
        st, b = self.rpc(self.k, "tools/call", {"name": "submit_job", "arguments": {"prompt": "hi"}})
        jid = b["result"]["structuredContent"]["job_id"]
        self.svc.dispatcher.tick()
        st, b = self.rpc(self.w, "tools/call", {"name": "deliver_result", "arguments": {"job_id": jid, "result": "hey"}})
        self.assertTrue(b["result"]["structuredContent"]["accepted"])
        st, b = self.rpc(self.k, "tools/call", {"name": "get_result", "arguments": {"job_id": jid}})
        self.assertEqual(b["result"]["structuredContent"]["result"], "hey")
        st, b = self.rpc(self.w, "tools/call", {"name": "submit_job", "arguments": {"prompt": "no"}})
        self.assertIn("unknown tool", b["error"]["message"])
        st, b = self.rpc(self.k, "tools/call", {"name": "get_status", "arguments": {"job_id": "j-none"}})
        self.assertTrue(b["result"]["isError"])

    def test_notifications_and_batch(self):
        st, b = mcp.handle(self.svc, self.k, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual(st, 202); self.assertIsNone(b)
        st, b = mcp.handle(self.svc, self.k, [{"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"jsonrpc": "2.0", "id": 2, "method": "nope"}])
        self.assertEqual(len(b), 2); self.assertIn("error", b[1])


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.svc, cls.ncl = make(cls.tmp)
        _, cls.key = cls.svc.store.issue_key("arthur", "user", ("local",))
        _, cls.wkey = cls.svc.store.issue_key("w", "worker", ())
        server.Handler.service = cls.svc
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def req(self, method, path, body=None, key=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), data=data, method=method)
        r.add_header("Content-Type", "application/json")
        if key:
            r.add_header("Authorization", "Bearer " + key)
        try:
            with urllib.request.urlopen(r) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    def test_health_auth_and_rest_flow(self):
        self.assertEqual(self.req("GET", "/healthz")[0], 200)
        self.assertEqual(self.req("GET", "/api/tiers")[0], 401)
        st, b = self.req("GET", "/api/tiers", key=self.key)
        self.assertEqual(st, 200); self.assertEqual([t["tier"] for t in b["tiers"]], ["local", "claude"])
        st, b = self.req("POST", "/api/jobs", {"prompt": "hello", "tier": "local"}, key=self.key)
        self.assertEqual(st, 202); jid = b["job_id"]
        self.svc.dispatcher.tick()
        st, b = self.req("POST", "/internal/deliver", {"job_id": jid, "result": "world"}, key=self.wkey)
        self.assertEqual(st, 200); self.assertTrue(b["accepted"])
        st, b = self.req("GET", "/api/jobs/%s/result" % jid, key=self.key)
        self.assertEqual(b["result"], "world")
        st, b = self.req("GET", "/api/jobs", key=self.key)
        self.assertEqual(len(b["jobs"]), 1)
        st, b = self.req("DELETE", "/api/jobs/%s" % jid, key=self.key)
        self.assertFalse(b["cancelled"])
        st, b = self.req("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "ping"}, key=self.key)
        self.assertEqual(st, 200); self.assertEqual(b["result"], {})
        self.assertEqual(self.req("GET", "/nope", key=self.key)[0], 404)

    def test_artifact_download_route(self):
        _, akey = self.svc.store.issue_key("artifact-tester", "user", ("local",))
        jid = self.svc.submit(self.svc.store.key_by_token(akey), "x", "local")["job_id"]
        d = os.path.join(self.svc.cfg.artifacts_dir, jid)
        os.makedirs(d)
        with open(os.path.join(d, "out.png"), "wb") as f:
            f.write(b"PNGDATA")
        req = urllib.request.Request("http://127.0.0.1:%d/api/jobs/%s/artifacts/out.png" % (self.port, jid), headers={"Authorization": "Bearer " + akey})
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.headers["Content-Type"], "image/png")
            self.assertEqual(resp.read(), b"PNGDATA")
        self.assertEqual(self.req("GET", "/api/jobs/%s/artifacts/out.png" % jid)[0], 401)
        self.assertEqual(self.req("GET", "/api/jobs/%s/artifacts/nope.png" % jid, key=akey)[0], 404)
        self.assertEqual(self.req("GET", "/api/jobs/%s/artifacts/out.png" % jid, key=self.key)[0], 404)


if __name__ == "__main__":
    unittest.main()
