import json, os, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))


def fake_proc(root, procs):
    for pid, comm, fds in procs:
        d = os.path.join(root, str(pid))
        os.makedirs(os.path.join(d, "fdinfo"))
        open(os.path.join(d, "comm"), "w").write(comm + "\n")
        open(os.path.join(d, "cgroup"), "w").write("0::/user.slice\n")
        for i, text in enumerate(fds):
            open(os.path.join(d, "fdinfo", str(i)), "w").write(text)


class Sample(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["GPU_SAMPLE_PROC"] = os.path.join(self.tmp, "proc")
        os.environ["GPU_SAMPLE_RUN"] = os.path.join(self.tmp, "run")
        os.environ["GPU_SAMPLE_LOG"] = os.path.join(self.tmp, "log")
        os.environ["GPU_SAMPLE_TEXTFILE"] = os.path.join(self.tmp, "textfile")
        os.environ["GPU_SAMPLE_ARBITER"] = os.path.join(self.tmp, "status.json")
        import importlib, gpu_sample
        self.g = importlib.reload(gpu_sample)

    def test_groups_clients_and_skips_non_drm(self):
        drm = "pos:\t0\ndrm-driver:\txe\ndrm-client-id:\t%d\ndrm-total-vram0:\t%s\ndrm-cycles-vcs:\t%d\n"
        fake_proc(os.environ["GPU_SAMPLE_PROC"], [
            (100, "Plex Transcoder", [drm % (1, "300 MiB", 50), drm % (1, "300 MiB", 50)]),   # same client twice: counted once
            (101, "Plex Transcoder", [drm % (2, "204800 KiB", 10)]),
            (200, "vllm", [drm % (3, "29192864 KiB", 999), "pos:\t0\nflags:\t02\n"]),
        ])
        snap = self.g.sample()
        c = snap["clients"]
        self.assertEqual(c["Plex Transcoder"]["vram_mib"], 500.0)
        self.assertEqual(c["Plex Transcoder"]["pids"], [100, 101])
        self.assertEqual(c["Plex Transcoder"]["engine"], 60)
        self.assertAlmostEqual(c["vllm"]["vram_mib"], 28508.7, places=1)

    def test_textfile_with_and_without_arbiter(self):
        snap = {"t": 0, "clients": {'odd"name': {"vram_mib": 1.0, "pids": [1], "comms": ["x"], "engine": 7}}}
        self.g.write_prom(snap)
        body = open(os.path.join(self.tmp, "textfile", "gpu.prom")).read()
        self.assertIn('gpu_client_vram_bytes{client="odd\\"name"} 1048576', body)
        self.assertIn("gpu_arbiter_up 0", body)
        json.dump({"t": 9e12, "mode": "swapping", "mode_since": 9e12, "enabled": True, "queue": 1}, open(os.environ["GPU_SAMPLE_ARBITER"], "w"))
        self.g.write_prom(snap)
        body = open(os.path.join(self.tmp, "textfile", "gpu.prom")).read()
        self.assertIn('gpu_arbiter_mode{mode="swapping"} 1', body)
        self.assertIn("gpu_arbiter_queue 1", body)
        stale = self.g.prom(snap, {"t": 0, "mode": "llm"}, now=1000)
        self.assertIn("gpu_arbiter_up 0", stale)

    def test_write_and_summary(self):
        self.g.write({"t": 1000, "clients": {"plex": {"vram_mib": 300.0, "pids": [1], "comms": ["x"], "engine": 5}}})
        self.g.write({"t": 1060, "clients": {"plex": {"vram_mib": 500.0, "pids": [1], "comms": ["x"], "engine": 9}}})
        latest = json.load(open(os.path.join(os.environ["GPU_SAMPLE_RUN"], "latest.json")))
        self.assertEqual(latest["t"], 1060)
        from io import StringIO
        import contextlib
        buf = StringIO()
        with contextlib.redirect_stdout(buf):
            self.g.summary()
        self.assertIn("seen     2 min  busy     1 min  peak    500.0 MiB", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
