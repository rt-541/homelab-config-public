"""Shared helpers for the media-reclaim campaign (nemesis side).

Python 3.9 stdlib only. All filesystem access to the plexadm-owned media
mounts goes through `sudo -n`; all Radarr/Sonarr/qBittorrent access goes
through their localhost APIs. Nothing in this module deletes anything.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.cookiejar import CookieJar

# ---------------------------------------------------------------------------
# Locations

MEDIA = "/docker/plex/media"
MEDIA2 = "/docker/plex/media2"
DOWNLOADS = os.path.join(MEDIA, "downloads")

# Human-review reports and logs (nemesis-local, NOT in the NFS export)
LOG_ROOT = "/docker/plex/logs/media-reclaim"
# Machine state shared with the devastator transcoder over the NFS export
# (media/ and media2/ are the only exported trees, so state lives here).
STATE_ROOT = os.path.join(MEDIA, ".reclaim")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

ARR = {
    "radarr": {"url": "http://localhost:7878", "config": "/docker/radarr/config.xml"},
    "sonarr": {"url": "http://localhost:8989", "config": "/docker/sonarr/config.xml"},
}
QBIT_URL = "http://localhost:8080"
# qbit sees /data/downloads == /docker/plex/media/downloads
QBIT_PATH_PREFIX = "/data/downloads"

VIDEO_EXT = (".mkv", ".mp4", ".avi", ".m2ts", ".ts", ".webm", ".m4v")

# ---------------------------------------------------------------------------
# Small utilities


def die(msg, code=1):
    print("ERROR: %s" % msg, file=sys.stderr)
    sys.exit(code)


def log(msg):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg), flush=True)


def gib(nbytes):
    return nbytes / (1024.0 ** 3)


def fmt_gib(nbytes):
    return "%.1f" % gib(nbytes)


def run(cmd, check=True, capture=True):
    """Run a command list; return stdout as text."""
    res = subprocess.run(
        cmd,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE,
        text=True,
    )
    if check and res.returncode != 0:
        raise RuntimeError(
            "command failed (%d): %s\n%s" % (res.returncode, " ".join(cmd), res.stderr.strip()[:500])
        )
    return res.stdout if capture else ""


def sudo(cmd, check=True):
    return run(["sudo", "-n"] + cmd, check=check)


def sudo_ok():
    try:
        run(["sudo", "-n", "true"])
        return True
    except Exception:
        return False


def ensure_dirs():
    """Create LOG_ROOT and STATE_ROOT, owned by the invoking user so plain
    writes work afterwards. Idempotent."""
    me = run(["id", "-un"]).strip()
    for d in (LOG_ROOT, STATE_ROOT, os.path.join(STATE_ROOT, "queue"),
              os.path.join(STATE_ROOT, "holding")):
        sudo(["install", "-d", "-o", me, "-g", me, "-m", "0775", d])


def stamp():
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


# ---------------------------------------------------------------------------
# Filesystem probes (all via sudo; mounts are plexadm 0770)


def stat_nlink_size(path):
    """Return (nlink, size_bytes) or (None, None) if missing."""
    try:
        out = sudo(["stat", "-c", "%h %s", path])
        h, s = out.split()
        return int(h), int(s)
    except Exception:
        return None, None


def is_sparse(size_bytes, blocks512):
    """True when a file's allocation is well short of its apparent size -
    a hollow/truncated shell (seen in the 2024-10 trash: 737G apparent was
    only ~387G real). Real media files are fully allocated."""
    return size_bytes > 0 and blocks512 * 512 < size_bytes * 0.95


def samefile_hits(path, root=DOWNLOADS):
    """Paths under root hardlinked to path (excluding path itself)."""
    try:
        out = sudo(["find", root, "-samefile", path], check=False)
    except Exception:
        return []
    return [p for p in out.splitlines() if p and p != path]


def find_files(roots, extra_args=None):
    """Yield (size, nlink, dirname, filename) for regular files under roots."""
    for size, nlink, d, f, _blocks in find_files_blocks(roots, extra_args):
        yield size, nlink, d, f


def find_files_blocks(roots, extra_args=None):
    """Yield (size, nlink, dirname, filename, blocks512) - blocks expose
    hollow/truncated files whose apparent size lies (see is_sparse)."""
    cmd = ["find"] + list(roots) + ["-type", "f"]
    if extra_args:
        cmd += extra_args
    cmd += ["-printf", "%s\\t%n\\t%b\\t%h\\t%f\\n"]
    out = sudo(cmd, check=False)
    for line in out.splitlines():
        parts = line.split("\t", 4)
        if len(parts) != 5:
            continue
        size, nlink, blocks, d, f = parts
        yield int(size), int(nlink), d, f, int(blocks)


def df_checkpoint(label):
    """Append a df snapshot for both mounts to the checkpoint log."""
    ensure_dirs()
    out = run(["df", "-B1", "--output=target,size,used,avail", MEDIA, MEDIA2])
    line = "== %s | %s\n%s" % (datetime.now().isoformat(timespec="seconds"), label, out)
    with open(os.path.join(LOG_ROOT, "df-checkpoints.log"), "a") as fh:
        fh.write(line + "\n")
    return out


# ---------------------------------------------------------------------------
# TSV helpers


def write_tsv(path, header, rows):
    with open(path, "w") as fh:
        fh.write("\t".join(header) + "\n")
        for r in rows:
            fh.write("\t".join(str(c) for c in r) + "\n")
    return path


def read_tsv(path):
    """Return (header, rows) from a TSV file."""
    with open(path) as fh:
        lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
    if not lines:
        return [], []
    header = lines[0].split("\t")
    rows = [ln.split("\t") for ln in lines[1:]]
    return header, rows


# ---------------------------------------------------------------------------
# Config files


def read_keep_list(path=None):
    """keep-list.conf: one case-insensitive substring pattern per line."""
    path = path or os.path.join(SCRIPT_DIR, "keep-list.conf")
    pats = []
    with open(path) as fh:
        for ln in fh:
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                pats.append(ln.lower())
    return pats


def read_policy(path=None):
    path = path or os.path.join(SCRIPT_DIR, "policy.conf")
    pol = {}
    with open(path) as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            pol[k.strip()] = v.strip()
    return pol


def read_env(path=None):
    """Optional .env next to the scripts (QBIT_USER/QBIT_PASS/PLEX_TOKEN)."""
    path = path or os.path.join(SCRIPT_DIR, ".env")
    env = {}
    if os.path.exists(path):
        with open(path) as fh:
            for ln in fh:
                ln = ln.strip()
                if ln and not ln.startswith("#") and "=" in ln:
                    k, v = ln.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env


# ---------------------------------------------------------------------------
# Radarr / Sonarr API


def arr_key(app):
    cfg = ARR[app]["config"]
    out = sudo(["grep", "-oP", "<ApiKey>\\K[^<]+", cfg])
    key = out.strip()
    if not key:
        raise RuntimeError("no ApiKey found in %s" % cfg)
    return key


def arr_call(app, method, path, params=None, body=None, timeout=120):
    url = ARR[app]["url"] + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = None
    headers = {"X-Api-Key": arr_key(app)}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError("%s %s -> HTTP %d: %s" % (method, path, e.code, e.read()[:300]))
    if not raw:
        return None
    return json.loads(raw)


def arr_get(app, path, params=None):
    return arr_call(app, "GET", path, params=params)


# ---------------------------------------------------------------------------
# qBittorrent API (optional -- requires creds in .env)


class Qbit:
    def __init__(self):
        env = read_env()
        self.user = env.get("QBIT_USER") or os.environ.get("QBIT_USER")
        self.password = env.get("QBIT_PASS") or os.environ.get("QBIT_PASS")
        cj = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        self.available = False
        if self.user and self.password:
            self.available = self._login()

    def _login(self):
        data = urllib.parse.urlencode({"username": self.user, "password": self.password}).encode()
        req = urllib.request.Request(QBIT_URL + "/api/v2/auth/login", data=data)
        try:
            with self.opener.open(req, timeout=30) as resp:
                ok = resp.read().decode().strip() == "Ok."
        except Exception as e:
            log("qbit login failed: %s" % e)
            return False
        if not ok:
            log("qbit login rejected (check QBIT_USER/QBIT_PASS in .env)")
        return ok

    def _get(self, path, params=None):
        url = QBIT_URL + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        with self.opener.open(url, timeout=60) as resp:
            return json.loads(resp.read())

    def _post(self, path, params):
        data = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(QBIT_URL + path, data=data)
        with self.opener.open(req, timeout=60) as resp:
            return resp.read().decode()

    def torrents(self):
        """All torrents with host-resolved content paths."""
        items = self._get("/api/v2/torrents/info")
        for t in items:
            cp = t.get("content_path", "")
            if cp.startswith(QBIT_PATH_PREFIX):
                t["host_content_path"] = DOWNLOADS + cp[len(QBIT_PATH_PREFIX):]
            else:
                t["host_content_path"] = cp
        return items

    def trackers(self, torrent_hash):
        return self._get("/api/v2/torrents/trackers", {"hash": torrent_hash})

    def delete(self, hashes, delete_files):
        return self._post(
            "/api/v2/torrents/delete",
            {"hashes": "|".join(hashes), "deleteFiles": "true" if delete_files else "false"},
        )


def qbit_hits_under(qbit, host_path_prefix):
    """Torrents whose content lives under host_path_prefix. None if qbit unavailable."""
    if qbit is None or not qbit.available:
        return None
    hits = []
    for t in qbit.torrents():
        hcp = t["host_content_path"]
        if hcp.startswith(host_path_prefix.rstrip("/") + "/") or hcp == host_path_prefix:
            hits.append(t)
    return hits


# ---------------------------------------------------------------------------
# Ledger (shared state consumed by cleanup_seeds.py)

LEDGER = os.path.join(STATE_ROOT, "ledger.tsv")
LEDGER_HEADER = [
    "ts", "action", "title", "old_path", "old_size_bytes", "nlink",
    "samefile_paths", "qbit_hash", "status",
]


def ledger_append(action, title, old_path, old_size, nlink, samefiles, qbit_hash, status):
    ensure_dirs()
    new = not os.path.exists(LEDGER)
    with open(LEDGER, "a") as fh:
        if new:
            fh.write("\t".join(LEDGER_HEADER) + "\n")
        fh.write("\t".join([
            datetime.now().isoformat(timespec="seconds"), action, title, old_path,
            str(old_size), str(nlink), ";".join(samefiles) if samefiles else "-",
            qbit_hash or "-", status,
        ]) + "\n")


# ---------------------------------------------------------------------------
# Filename token parsing (shared by scanner and prune)

RES_TOKENS = [("2160p", "2160p"), ("uhd", "2160p"), ("4k", "2160p"),
              ("1080p", "1080p"), ("720p", "720p"), ("480p", "480p")]
SRC_RANK = ["remux", "bdremux", "bluray", "blu-ray", "web-dl", "webdl", "webrip", "hdtv", "yts"]


def parse_tokens(filename):
    f = filename.lower()
    res = ""
    for tok, val in RES_TOKENS:
        if tok in f:
            res = val
            break
    src = ""
    for s in SRC_RANK:
        if s in f:
            src = "remux" if s == "bdremux" else s
            break
    codec = ""
    for c, val in [("x265", "hevc"), ("h265", "hevc"), ("hevc", "hevc"), ("h 265", "hevc"),
                   ("av1", "av1"), ("x264", "avc"), ("h264", "avc"), ("avc", "avc")]:
        if c in f:
            codec = val
            break
    flags = []
    if "upscaled" in f or "ai.enhanced" in f or "ai enhanced" in f:
        flags.append("FAKE4K")
    for lang in ("nahom", ".ita.", " ita ", "multi", ".rus.", "vostfr"):
        if lang in f:
            flags.append("MULTILANG")
            break
    if ".dv." in f or " dv " in f or "dovi" in f or "dolby.vision" in f:
        flags.append("DV")
    if "hdr" in f:
        flags.append("HDR")
    return res, src, codec, ",".join(sorted(set(flags))) or "-"


def src_rank(src):
    order = {"remux": 0, "bluray": 1, "blu-ray": 1, "web-dl": 2, "webdl": 2,
             "webrip": 3, "hdtv": 4, "yts": 5, "": 6}
    return order.get(src, 6)


def is_video(name):
    return name.lower().endswith(VIDEO_EXT)


def keep_match(keep_pats, dirname):
    d = dirname.lower()
    return any(p in d for p in keep_pats)
