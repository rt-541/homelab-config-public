#!/usr/bin/env python3
"""gpu-arbiter - share devastator's one B70 between vLLM and occasional photo jobs.

vLLM reserves its GPU memory at start and cannot shrink, so the card is shared by
swapping owners, not by resizing:

  llm       normal: vLLM (plex-compute) owns the card
  swapping  vLLM is being stopped or started; the NanoClaw proxy holds requests
  image     vLLM is stopped; ComfyUI runs FLUX.1 Kontext and works the photo queue

A photo request never interrupts anyone. The arbiter swaps to `image` only when:
  - the queue is not empty and the arbiter is enabled (and inside the window, if one is set);
  - vLLM has had no running or waiting request and no finished request for IDLE_S;
  - no other GPU client (Plex Transcoder, the media-transcoder) holds the card,
    per the recorder's snapshot (/run/gpu-usage/latest.json).
It swaps back as soon as the queue is empty or MAX_HOLD_S has passed, and always
confirms vLLM answers /health before declaring `llm`. A failed return is retried
and reported to Discord (scripts/claude-notify/notify.sh, honours NOTIFY_DEBUG).

HTTP on 127.0.0.1:ARBITER_PORT (llm-jobs is the only caller):
  POST /photos  {"src": abs png, "dst": abs png, "prompt"?, "seed"?, "steps"?} -> {"id", "position"}
  GET  /photos/<id>                                                           -> {"status", "error", "seconds"}
  GET  /status                                                                -> mode, queue, last swap, guards
The mode is also written to STATE_DIR/mode (one word) for the proxy, and the
whole state to STATE_DIR/status.json every poll; the root gpu-sample timer turns
that into node_exporter metrics, so the obs pair scrapes and alerts on it.
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import comfy


def env(k, d):
    return os.environ.get(k, d)


class Cfg:
    def __init__(self, e=None):
        e = e if e is not None else os.environ
        g = lambda k, d: e.get(k, d)  # noqa: E731
        self.port = int(g("ARBITER_PORT", "8390"))
        self.state_dir = g("ARBITER_STATE", os.path.expanduser("~/.local/state/gpu-arbiter"))
        self.enabled = g("ARBITER_ENABLED", "true").lower() in ("1", "true", "yes", "on")
        self.idle_s = int(g("ARBITER_IDLE_S", "60"))
        self.max_hold_s = int(g("ARBITER_MAX_HOLD_S", "900"))
        self.window = g("ARBITER_WINDOW", "")               # "" = any time, else "HH:MM-HH:MM" local
        self.vllm_url = g("ARBITER_VLLM_URL", "http://127.0.0.1:8000")
        self.vllm_dir = g("ARBITER_VLLM_DIR", "/docker/homelab-config/compute-node/composed-apps/plex-compute")
        self.vllm_service = g("ARBITER_VLLM_SERVICE", "vllm")
        self.vllm_start_timeout = int(g("ARBITER_VLLM_START_TIMEOUT", "900"))
        self.gpu_snapshot = g("ARBITER_GPU_SNAPSHOT", "/run/gpu-usage/latest.json")
        self.owners = [s.strip() for s in g("ARBITER_OWNERS", "plex-compute-vllm,gpu-arbiter-comfyui").split(",") if s.strip()]
        self.comfy_image = g("ARBITER_COMFY_IMAGE", "intel/llm-scaler-omni:0.2.0-b1")
        self.comfy_root = g("ARBITER_COMFY_ROOT", "/docker/comfyui")
        self.comfy_reserve_gb = g("ARBITER_COMFY_RESERVE_GB", "2")
        self.notify = g("ARBITER_NOTIFY", "/docker/homelab-config/scripts/claude-notify/notify.sh")
        self.poll_s = float(g("ARBITER_POLL_S", "5"))


def now():
    return time.time()


def log(msg):
    sys.stdout.write("%s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), msg))
    sys.stdout.flush()


class Host:
    """Everything that touches the machine, so tests can replace it."""

    def __init__(self, cfg):
        self.cfg = cfg

    def vllm_metrics(self):
        """(running + waiting, finished-requests counter) or None if vLLM does not answer."""
        try:
            with urllib.request.urlopen(self.cfg.vllm_url + "/metrics", timeout=5) as r:
                text = r.read().decode()
        except Exception:  # noqa: BLE001
            return None
        def total(name):
            return sum(float(m) for m in re.findall(r"^%s\{[^}]*\} ([0-9.e+]+)" % re.escape(name), text, re.M))
        busy = total("vllm:num_requests_running") + total("vllm:num_requests_waiting")
        done = total("vllm:request_success_total")
        return busy, done

    def vllm_healthy(self):
        try:
            with urllib.request.urlopen(self.cfg.vllm_url + "/health", timeout=5) as r:
                return r.status == 200
        except Exception:  # noqa: BLE001
            return False

    def other_gpu_clients(self):
        """GPU clients that are not the two owners, from the recorder's snapshot. Stale snapshot -> assume busy."""
        try:
            snap = json.load(open(self.cfg.gpu_snapshot))
        except (OSError, ValueError):
            return ["recorder snapshot unreadable"]
        if now() - snap.get("t", 0) > 180:
            return ["recorder snapshot stale"]
        return sorted(k for k in snap.get("clients", {}) if k not in self.cfg.owners)

    def _compose(self, *args):
        return subprocess.run(["docker", "compose", *args], cwd=self.cfg.vllm_dir, capture_output=True, text=True, timeout=300)

    def stop_vllm(self):
        r = self._compose("stop", self.cfg.vllm_service)
        return r.returncode == 0

    def start_vllm(self):
        r = self._compose("up", "-d", self.cfg.vllm_service)
        return r.returncode == 0

    def start_comfy(self):
        c = self.cfg
        subprocess.run(["docker", "rm", "-f", "gpu-arbiter-comfyui"], capture_output=True)
        r = subprocess.run(["docker", "run", "-d", "--name", "gpu-arbiter-comfyui", "--device=/dev/dri", "--network=host",
                            "--shm-size=16g", "-e", "OMNI_COMFYUI_RESERVE_VRAM_GB=%s" % c.comfy_reserve_gb,
                            "-v", "%s/models:/llm/ComfyUI/models/external:ro" % c.comfy_root,
                            "-v", "%s/input:/llm/ComfyUI/input" % c.comfy_root,
                            "-v", "%s/output:/llm/ComfyUI/output" % c.comfy_root,
                            "-v", "%s/extra_model_paths.yaml:/llm/ComfyUI/extra_model_paths.yaml:ro" % c.comfy_root,
                            c.comfy_image, "bash", "-lc",
                            "cd /llm/ComfyUI && python3 main.py --listen 127.0.0.1 --port 8188 --reserve-vram %s" % c.comfy_reserve_gb],
                           capture_output=True, text=True)
        return r.returncode == 0

    def stop_comfy(self):
        subprocess.run(["docker", "rm", "-f", "gpu-arbiter-comfyui"], capture_output=True)

    def notify(self, title, body):
        if os.path.exists(self.cfg.notify):
            subprocess.run(["bash", self.cfg.notify, title, body], capture_output=True, timeout=30)


class Arbiter:
    def __init__(self, cfg, host=None, comfy_client=None):
        self.cfg = cfg
        self.host = host or Host(cfg)
        self.comfy = comfy_client or comfy.Comfy(input_dir=os.path.join(cfg.comfy_root, "input"),
                                                 output_dir=os.path.join(cfg.comfy_root, "output"))
        self.lock = threading.Lock()
        self.jobs = {}
        self.queue = []
        self.mode = "llm"
        self.idle_since = None
        self.last_done = None
        self.last_swap = None
        self.blocked_by = []
        self.mode_since = now()
        self.swaps = 0
        self.swap_failures = 0
        self.stop_event = threading.Event()
        os.makedirs(cfg.state_dir, exist_ok=True)
        self._write_mode("llm")

    # ---- state
    def _write_mode(self, mode):
        if mode != self.mode:
            self.mode_since = now()
        self.mode = mode
        tmp = os.path.join(self.cfg.state_dir, ".mode")
        with open(tmp, "w") as f:
            f.write(mode + "\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, os.path.join(self.cfg.state_dir, "mode"))

    def write_status(self):
        with self.lock:
            done = sum(1 for j in self.jobs.values() if j["status"] == "done")
            failed = sum(1 for j in self.jobs.values() if j["status"] == "failed")
            st = {"t": now(), "mode": self.mode, "mode_since": self.mode_since, "enabled": self.cfg.enabled,
                  "queue": len(self.queue), "blocked_by": self.blocked_by, "photos_done": done, "photos_failed": failed,
                  "swaps": self.swaps, "swap_failures": self.swap_failures, "last_swap": self.last_swap}
        tmp = os.path.join(self.cfg.state_dir, ".status.json")
        with open(tmp, "w") as f:
            json.dump(st, f)
        os.chmod(tmp, 0o644)
        os.replace(tmp, os.path.join(self.cfg.state_dir, "status.json"))

    def submit(self, src, dst, prompt=None, seed=7, steps=24):
        if not (isinstance(src, str) and os.path.isabs(src) and os.path.isfile(src)):
            raise ValueError("src must be an existing absolute path")
        if not (isinstance(dst, str) and os.path.isabs(dst) and os.path.isdir(os.path.dirname(dst))):
            raise ValueError("dst must be an absolute path in an existing directory")
        jid = "p-" + uuid.uuid4().hex[:10]
        with self.lock:
            self.jobs[jid] = {"id": jid, "src": src, "dst": dst, "prompt": prompt, "seed": int(seed), "steps": int(steps),
                              "status": "queued", "error": None, "seconds": None, "created": now()}
            self.queue.append(jid)
            return {"id": jid, "position": len(self.queue)}

    def get(self, jid):
        with self.lock:
            j = self.jobs.get(jid)
            if not j:
                return None
            out = {k: j[k] for k in ("id", "status", "error", "seconds")}
            out["position"] = self.queue.index(jid) + 1 if jid in self.queue else None
            return out

    def status(self):
        with self.lock:
            return {"mode": self.mode, "enabled": self.cfg.enabled, "queue": len(self.queue), "blocked_by": self.blocked_by,
                    "idle_for_s": int(now() - self.idle_since) if self.idle_since else 0, "last_swap": self.last_swap}

    # ---- guards
    def in_window(self, t=None):
        if not self.cfg.window:
            return True
        a, b = self.cfg.window.split("-")
        lt = time.localtime(t or now())
        cur = lt.tm_hour * 60 + lt.tm_min
        s = int(a[:2]) * 60 + int(a[3:])
        e = int(b[:2]) * 60 + int(b[3:])
        return s <= cur < e if s < e else (cur >= s or cur < e)

    def check_idle(self):
        """Update idle tracking from vLLM's metrics; True when idle long enough."""
        m = self.host.vllm_metrics()
        t = now()
        if m is None:
            self.idle_since = None
            return False
        busy, done = m
        if busy > 0 or (self.last_done is not None and done != self.last_done):
            self.idle_since = t
        elif self.idle_since is None:
            self.idle_since = t
        self.last_done = done
        return busy == 0 and t - self.idle_since >= self.cfg.idle_s

    def ready_to_swap(self):
        reasons = []
        if not self.cfg.enabled:
            reasons.append("arbiter disabled")
        if not self.in_window():
            reasons.append("outside window %s" % self.cfg.window)
        idle = self.check_idle()
        if not idle:
            reasons.append("vLLM busy or idle < %ds" % self.cfg.idle_s)
        others = self.host.other_gpu_clients()
        if others:
            reasons.append("GPU in use by " + ", ".join(others))
        self.blocked_by = reasons
        return not reasons

    # ---- swaps
    def to_image(self):
        log("swap -> image")
        self._write_mode("swapping")
        if not self.host.stop_vllm():
            log("could not stop vLLM; staying on llm")
            self.host.start_vllm()
            self._write_mode("llm")
            return False
        if not self.host.start_comfy() or not self.comfy.wait_ready(300):
            log("ComfyUI did not come up; back to llm")
            self.host.stop_comfy()
            self.to_llm()
            return False
        self._write_mode("image")
        self.swaps += 1
        self.last_swap = {"to": "image", "at": now()}
        return True

    def to_llm(self):
        log("swap -> llm")
        self._write_mode("swapping")
        self.host.stop_comfy()
        for attempt in range(3):
            self.host.start_vllm()
            t0 = now()
            while True:
                if self.host.vllm_healthy():
                    self._write_mode("llm")
                    self.last_swap = {"to": "llm", "at": now()}
                    self.idle_since = None
                    self.last_done = None
                    return True
                if now() - t0 >= self.cfg.vllm_start_timeout:
                    break
                time.sleep(self.cfg.poll_s)
            log("vLLM not healthy after %ds (attempt %d)" % (self.cfg.vllm_start_timeout, attempt + 1))
        self.host.notify("gpu-arbiter: vLLM did not come back",
                         "vLLM on devastator failed /health after 3 starts following a photo batch. The proxy stops holding "
                         "requests (mode llm) so callers fail fast; check `docker compose logs vllm` in plex-compute.")
        self._write_mode("llm")
        self.swap_failures += 1
        self.last_swap = {"to": "llm", "at": now(), "failed": True}
        return False

    def run_batch(self):
        t0 = now()
        while True:
            with self.lock:
                if not self.queue:
                    break
                jid = self.queue.pop(0)
                job = self.jobs[jid]
                job["status"] = "running"
            try:
                job["seconds"] = self.comfy.photo(job["src"], job["dst"], job["prompt"], job["seed"], job["steps"])
                job["status"] = "done"
                log("photo %s done in %ss" % (jid, job["seconds"]))
            except Exception as e:  # noqa: BLE001
                job["status"], job["error"] = "failed", str(e)[:500]
                log("photo %s failed: %s" % (jid, e))
            if now() - t0 > self.cfg.max_hold_s:
                log("max hold reached; handing the card back with %d queued" % len(self.queue))
                break

    def tick(self):
        if self.mode != "llm" or not self.queue:
            if self.mode == "llm":
                self.check_idle()
            return
        if not self.ready_to_swap():
            return
        if self.to_image():
            try:
                self.run_batch()
            finally:
                self.to_llm()

    def loop(self):
        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001
                log("tick error: %s" % e)
            try:
                self.write_status()
            except OSError as e:
                log("status write failed: %s" % e)
            self.stop_event.wait(self.cfg.poll_s)


def make_handler(arb):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, obj):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if self.path == "/status":
                return self._send(200, arb.status())
            if self.path.startswith("/photos/"):
                j = arb.get(self.path.split("/")[2])
                return self._send(200, j) if j else self._send(404, {"error": "no such photo job"})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/photos":
                return self._send(404, {"error": "not found"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                b = json.loads(self.rfile.read(n) or b"{}")
                self._send(202, arb.submit(b.get("src"), b.get("dst"), b.get("prompt"), b.get("seed", 7), b.get("steps", 24)))
            except (ValueError, TypeError) as e:
                self._send(400, {"error": str(e)})
    return H


def main():
    cfg = Cfg()
    arb = Arbiter(cfg)
    threading.Thread(target=arb.loop, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", cfg.port), make_handler(arb))
    log("gpu-arbiter on 127.0.0.1:%d, enabled=%s idle=%ds max_hold=%ds window=%s" % (cfg.port, cfg.enabled, cfg.idle_s, cfg.max_hold_s, cfg.window or "any"))
    srv.serve_forever()


if __name__ == "__main__":
    main()
