import json, os, sys, tempfile, time, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import arbiter as A  # noqa: E402


class FakeHost:
    def __init__(self):
        self.metrics = (0.0, 10.0)
        self.others = []
        self.healthy = True
        self.calls = []
        self.stop_ok = True

    def vllm_metrics(self):
        return self.metrics

    def vllm_healthy(self):
        return self.healthy

    def other_gpu_clients(self):
        return list(self.others)

    def stop_vllm(self):
        self.calls.append("stop_vllm"); return self.stop_ok

    def start_vllm(self):
        self.calls.append("start_vllm"); return True

    def start_comfy(self):
        self.calls.append("start_comfy"); return True

    def stop_comfy(self):
        self.calls.append("stop_comfy")

    def notify(self, title, body):
        self.calls.append("notify")


class FakeComfy:
    def __init__(self):
        self.done = []

    def wait_ready(self, t):
        return True

    def photo(self, src, dst, prompt, seed, steps):
        self.done.append(src)
        open(dst, "w").write("photo")
        return 1.0


class ArbiterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = A.Cfg({"ARBITER_STATE": self.tmp, "ARBITER_IDLE_S": "60", "ARBITER_POLL_S": "0",
                          "ARBITER_VLLM_START_TIMEOUT": "0"})
        self.host, self.comfy = FakeHost(), FakeComfy()
        self.arb = A.Arbiter(self.cfg, self.host, self.comfy)
        self.src = os.path.join(self.tmp, "in.png"); open(self.src, "w").write("x")
        self.clock = [1000.0]
        A.now = lambda: self.clock[0]

    def mode(self):
        return open(os.path.join(self.tmp, "mode")).read().strip()

    def test_no_swap_until_idle_long_enough(self):
        self.arb.submit(self.src, os.path.join(self.tmp, "out.png"))
        self.arb.tick()                      # first sight of idle starts the clock
        self.assertNotIn("stop_vllm", self.host.calls)
        self.clock[0] += 30; self.arb.tick()
        self.assertNotIn("stop_vllm", self.host.calls)
        self.clock[0] += 31; self.arb.tick()
        self.assertEqual(self.host.calls[:2], ["stop_vllm", "start_comfy"])
        self.assertEqual(self.host.calls[-1], "start_vllm")
        self.assertEqual(self.mode(), "llm")
        self.assertEqual(self.arb.get(list(self.arb.jobs)[0])["status"], "done")

    def test_new_finished_request_resets_idle(self):
        self.arb.submit(self.src, os.path.join(self.tmp, "out.png"))
        self.arb.tick(); self.clock[0] += 50
        self.host.metrics = (0.0, 11.0)       # a request finished in between
        self.arb.tick(); self.clock[0] += 50
        self.arb.tick()
        self.assertNotIn("stop_vllm", self.host.calls)
        self.clock[0] += 11; self.arb.tick()
        self.assertIn("stop_vllm", self.host.calls)

    def test_running_request_blocks(self):
        self.arb.submit(self.src, os.path.join(self.tmp, "out.png"))
        self.host.metrics = (1.0, 10.0)
        for _ in range(5):
            self.clock[0] += 100; self.arb.tick()
        self.assertNotIn("stop_vllm", self.host.calls)

    def test_plex_on_the_card_blocks(self):
        self.arb.submit(self.src, os.path.join(self.tmp, "out.png"))
        self.host.others = ["plex"]
        for _ in range(3):
            self.clock[0] += 100; self.arb.tick()
        self.assertNotIn("stop_vllm", self.host.calls)
        self.assertIn("GPU in use by plex", self.arb.status()["blocked_by"])
        self.host.others = []
        self.clock[0] += 100; self.arb.tick()
        self.assertIn("stop_vllm", self.host.calls)

    def test_disabled_and_window(self):
        self.arb.submit(self.src, os.path.join(self.tmp, "out.png"))
        self.cfg.enabled = False
        for _ in range(3):
            self.clock[0] += 100; self.arb.tick()
        self.assertNotIn("stop_vllm", self.host.calls)
        self.cfg.enabled = True
        self.cfg.window = "02:00-04:00"
        self.assertTrue(self.arb.in_window(time.mktime((2026, 9, 27, 3, 0, 0, 0, 0, -1))))
        self.assertFalse(self.arb.in_window(time.mktime((2026, 9, 27, 12, 0, 0, 0, 0, -1))))
        self.cfg.window = "23:00-02:00"
        self.assertTrue(self.arb.in_window(time.mktime((2026, 9, 27, 1, 0, 0, 0, 0, -1))))

    def test_vllm_not_coming_back_notifies_and_releases_proxy(self):
        self.arb.submit(self.src, os.path.join(self.tmp, "out.png"))
        self.host.healthy = False
        self.arb.tick(); self.clock[0] += 61; self.arb.tick()
        self.assertEqual(self.host.calls.count("start_vllm"), 3)
        self.assertIn("notify", self.host.calls)
        self.assertEqual(self.mode(), "llm")

    def test_submit_validates_paths(self):
        with self.assertRaises(ValueError):
            self.arb.submit("relative.png", os.path.join(self.tmp, "o.png"))
        with self.assertRaises(ValueError):
            self.arb.submit(self.src, "/no/such/dir/o.png")

    def test_batch_runs_all_queued_then_returns(self):
        for i in range(3):
            self.arb.submit(self.src, os.path.join(self.tmp, "o%d.png" % i))
        self.arb.tick(); self.clock[0] += 61; self.arb.tick()
        self.assertEqual(len(self.comfy.done), 3)
        self.assertEqual(self.host.calls.count("stop_vllm"), 1)

    def test_status_file_tracks_mode_and_counts(self):
        self.arb.submit(self.src, os.path.join(self.tmp, "o.png"))
        self.arb.write_status()
        st = json.load(open(os.path.join(self.tmp, "status.json")))
        self.assertEqual((st["mode"], st["queue"], st["swaps"]), ("llm", 1, 0))
        self.arb.tick(); self.clock[0] += 61; self.arb.tick()
        self.arb.write_status()
        st = json.load(open(os.path.join(self.tmp, "status.json")))
        self.assertEqual((st["mode"], st["queue"], st["swaps"], st["photos_done"]), ("llm", 0, 1, 1))
        self.assertEqual(st["mode_since"], self.clock[0])


if __name__ == "__main__":
    unittest.main()
