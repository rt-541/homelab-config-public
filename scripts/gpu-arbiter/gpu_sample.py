#!/usr/bin/env python3
"""gpu_sample.py - who holds the GPU, once a minute (root, systemd timer on devastator).

Reads every process's DRM fdinfo (the xe driver reports per-client VRAM and
engine busy time there), groups by client, and writes:

  /run/gpu-usage/latest.json          the current snapshot (world-readable; the arbiter reads it)
  /var/log/gpu-usage/YYYY-MM.jsonl    one line per sample, the usage history
  <textfile dir>/gpu.prom             the same snapshot plus the gpu-arbiter's status, as node_exporter
                                      textfile metrics, so the observability pair can graph and alert on it

A client is named by its container (from the cgroup) when it has one, else by
its command name, so "plex" covers every Plex Transcoder process.

  gpu_sample.py            take one sample
  gpu_sample.py --summary  summarize the history (per client: samples seen, peak VRAM, busy minutes)
"""

import glob
import json
import os
import re
import sys
import time

RUN_DIR = os.environ.get("GPU_SAMPLE_RUN", "/run/gpu-usage")
LOG_DIR = os.environ.get("GPU_SAMPLE_LOG", "/var/log/gpu-usage")
PROC = os.environ.get("GPU_SAMPLE_PROC", "/proc")
TEXTFILE_DIR = os.environ.get("GPU_SAMPLE_TEXTFILE", "/var/lib/node_exporter/textfile")
ARBITER_STATUS = os.environ.get("GPU_SAMPLE_ARBITER", "/home/aschneider/.local/state/gpu-arbiter/status.json")
MODES = ("llm", "swapping", "image")
_ids = {}


def container_of(pid):
    """Container name for a pid via its cgroup (docker-<id>.scope), or None."""
    try:
        cg = open(os.path.join(PROC, pid, "cgroup")).read()
    except OSError:
        return None
    m = re.search(r"docker-([0-9a-f]{12,64})\.scope|/docker/([0-9a-f]{12,64})", cg)
    if not m:
        return None
    cid = (m.group(1) or m.group(2))[:12]
    if cid not in _ids:
        name = None
        for d in glob.glob("/var/lib/docker/containers/%s*/config.v2.json" % cid):
            try:
                name = json.load(open(d)).get("Name", "").lstrip("/") or None
            except (OSError, ValueError):
                pass
        _ids[cid] = name or cid
    return _ids[cid]


def parse_fdinfo(text):
    out = {}
    for line in text.splitlines():
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip()
    return out


def kib(v):
    """'29192864 KiB' -> 29192864; MiB/GiB scaled; a bare number is bytes."""
    m = re.match(r"(\d+)\s*(KiB|MiB|GiB)?", v or "")
    if not m:
        return 0
    n, unit = int(m.group(1)), m.group(2)
    return {"KiB": n, "MiB": n * 1024, "GiB": n * 1024 * 1024}.get(unit, n // 1024)


def sample():
    clients = {}
    seen = set()
    for fd in glob.glob(os.path.join(PROC, "[0-9]*", "fdinfo", "*")):
        try:
            text = open(fd).read()
        except OSError:
            continue
        if "drm-driver" not in text:
            continue
        info = parse_fdinfo(text)
        pid = fd.split(os.sep)[-3]
        key = (pid, info.get("drm-client-id"))
        if key in seen:
            continue
        seen.add(key)
        try:
            comm = open(os.path.join(PROC, pid, "comm")).read().strip()
        except OSError:
            comm = "?"
        who = container_of(pid) or comm
        c = clients.setdefault(who, {"vram_kib": 0, "pids": set(), "comms": set(), "engine_ns": 0})
        c["vram_kib"] += kib(info.get("drm-total-vram0") or info.get("drm-resident-vram0"))
        c["pids"].add(int(pid))
        c["comms"].add(comm)
        for k, v in info.items():
            if k.startswith("drm-cycles-") or k.startswith("drm-engine-"):
                m = re.match(r"\d+", v)
                c["engine_ns"] += int(m.group()) if m else 0
    snap = {"t": int(time.time()), "clients": {k: {"vram_mib": round(v["vram_kib"] / 1024, 1), "pids": sorted(v["pids"]),
                                                   "comms": sorted(v["comms"]), "engine": v["engine_ns"]}
                                               for k, v in sorted(clients.items())}}
    return snap


def write(snap):
    os.makedirs(RUN_DIR, exist_ok=True)
    tmp = os.path.join(RUN_DIR, ".latest.json")
    with open(tmp, "w") as f:
        json.dump(snap, f)
    os.chmod(tmp, 0o644)
    os.replace(tmp, os.path.join(RUN_DIR, "latest.json"))
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(os.path.join(LOG_DIR, time.strftime("%Y-%m.jsonl", time.localtime(snap["t"]))), "a") as f:
        f.write(json.dumps({"t": snap["t"], "c": {k: [v["vram_mib"], v["engine"]] for k, v in snap["clients"].items()}}) + "\n")


def _label(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def prom(snap, arbiter=None, now=None):
    """node_exporter textfile body for a snapshot and the arbiter's status.json (or None)."""
    now = now or time.time()
    out = ["# HELP gpu_client_vram_bytes VRAM held on the GPU per client (container or command).",
           "# TYPE gpu_client_vram_bytes gauge"]
    for who, c in snap["clients"].items():
        out.append('gpu_client_vram_bytes{client="%s"} %d' % (_label(who), int(c["vram_mib"] * 1024 * 1024)))
    out += ["# HELP gpu_client_engine_ns Summed engine busy counter per client (resets when its processes exit).",
            "# TYPE gpu_client_engine_ns gauge"]
    for who, c in snap["clients"].items():
        out.append('gpu_client_engine_ns{client="%s"} %d' % (_label(who), c["engine"]))
    out += ["# HELP gpu_clients Number of GPU clients.", "# TYPE gpu_clients gauge", "gpu_clients %d" % len(snap["clients"])]
    if arbiter is None:
        out += ["# HELP gpu_arbiter_up 1 when the arbiter status file is fresh.", "# TYPE gpu_arbiter_up gauge", "gpu_arbiter_up 0"]
        return "\n".join(out) + "\n"
    fresh = now - float(arbiter.get("t", 0)) < 180
    out += ["# HELP gpu_arbiter_up 1 when the arbiter status file is fresh.", "# TYPE gpu_arbiter_up gauge",
            "gpu_arbiter_up %d" % fresh,
            "# HELP gpu_arbiter_mode Current owner mode of the GPU (1 for the active mode).", "# TYPE gpu_arbiter_mode gauge"]
    for m in MODES:
        out.append('gpu_arbiter_mode{mode="%s"} %d' % (m, arbiter.get("mode") == m))
    out += ["# HELP gpu_arbiter_mode_seconds Seconds the arbiter has held its current mode.", "# TYPE gpu_arbiter_mode_seconds gauge",
            "gpu_arbiter_mode_seconds %d" % max(0, now - float(arbiter.get("mode_since") or now)),
            "# HELP gpu_arbiter_enabled 1 when the arbiter may swap.", "# TYPE gpu_arbiter_enabled gauge",
            "gpu_arbiter_enabled %d" % bool(arbiter.get("enabled")),
            "# HELP gpu_arbiter_queue Photo requests waiting for the GPU.", "# TYPE gpu_arbiter_queue gauge",
            "gpu_arbiter_queue %d" % int(arbiter.get("queue") or 0),
            "# HELP gpu_arbiter_photos_total Photo passes since the arbiter started.", "# TYPE gpu_arbiter_photos_total counter",
            'gpu_arbiter_photos_total{result="done"} %d' % int(arbiter.get("photos_done") or 0),
            'gpu_arbiter_photos_total{result="failed"} %d' % int(arbiter.get("photos_failed") or 0),
            "# HELP gpu_arbiter_swaps_total Swaps to the image model since the arbiter started.", "# TYPE gpu_arbiter_swaps_total counter",
            "gpu_arbiter_swaps_total %d" % int(arbiter.get("swaps") or 0),
            "# HELP gpu_arbiter_swap_failures_total Handbacks where vLLM did not come back healthy.",
            "# TYPE gpu_arbiter_swap_failures_total counter",
            "gpu_arbiter_swap_failures_total %d" % int(arbiter.get("swap_failures") or 0)]
    return "\n".join(out) + "\n"


def write_prom(snap):
    try:
        arbiter = json.load(open(ARBITER_STATUS))
    except (OSError, ValueError):
        arbiter = None
    os.makedirs(TEXTFILE_DIR, exist_ok=True)
    tmp = os.path.join(TEXTFILE_DIR, ".gpu.prom")
    with open(tmp, "w") as f:
        f.write(prom(snap, arbiter))
    os.chmod(tmp, 0o644)
    os.replace(tmp, os.path.join(TEXTFILE_DIR, "gpu.prom"))


def summary():
    stats, last = {}, {}
    for p in sorted(glob.glob(os.path.join(LOG_DIR, "*.jsonl"))):
        for line in open(p):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            for who, (mib, eng) in d["c"].items():
                s = stats.setdefault(who, {"samples": 0, "peak_mib": 0.0, "busy_samples": 0, "first": d["t"], "last": d["t"]})
                s["samples"] += 1
                s["peak_mib"] = max(s["peak_mib"], mib)
                if who in last and eng > last[who]:
                    s["busy_samples"] += 1
                last[who] = eng
                s["last"] = d["t"]
    for who, s in sorted(stats.items()):
        print("%-24s seen %5d min  busy %5d min  peak %8.1f MiB  %s .. %s" % (
            who, s["samples"], s["busy_samples"], s["peak_mib"],
            time.strftime("%m-%d %H:%M", time.localtime(s["first"])), time.strftime("%m-%d %H:%M", time.localtime(s["last"]))))


if __name__ == "__main__":
    if "--summary" in sys.argv:
        summary()
    else:
        snap = sample()
        write(snap)
        write_prom(snap)
