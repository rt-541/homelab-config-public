"""Shared plumbing for the plex-ops action-runner (nemesis side).

Python 3.9 stdlib only. All filesystem access to the plexadm-owned media
mounts goes through `sudo -n`; all Radarr/Sonarr/Prowlarr/qBittorrent access
goes through their localhost APIs. Nothing in this module deletes anything:
the only writers here are the audit log and JSON state under LOG_ROOT.

Interface contract: scripts/plex-ops/CONTRACT.md (section 7.1). Adapted from
origin/worktree-media-reclaim:scripts/media-reclaim/reclaim_lib.py.
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.cookiejar import CookieJar

# ---------------------------------------------------------------------------
# Locations and constants

MEDIA = "/docker/plex/media"
MEDIA2 = "/docker/plex/media2"
DOWNLOADS = os.path.join(MEDIA, "downloads")

# Runner-local logs and state (nemesis-local, NOT in the NFS export)
LOG_ROOT = "/docker/plex/logs/plex-ops"
AUDIT_LOG = os.path.join(LOG_ROOT, "audit.jsonl")
DISK_STATE = os.path.join(LOG_ROOT, "disk-state.json")

# Bearer token + optional qbit/plex creds (root:root 0600, KEY=value lines)
ENV_FILE = "/etc/plex-ops/runner.env"
TOKEN_VAR = "PLEXOPS_TOKEN"
# The committed example value; the runner refuses to start on it.
TOKEN_PLACEHOLDER = "CHANGE_ME_openssl_rand_hex_32"
TOKEN_MIN_LEN = 32
RUNNER_PORT = 8377

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

ARR = {
    "radarr": {"url": "http://localhost:7878", "config": "/docker/radarr/config.xml",
               "port": 7878},
    "sonarr": {"url": "http://localhost:8989", "config": "/docker/sonarr/config.xml",
               "port": 8989},
    "prowlarr": {"url": "http://localhost:9696",
                 "config": "/docker/prowlarr/config/config.xml", "port": 9696},
}
# The /arr/<app> GET passthrough serves only these two.
PASSTHROUGH_APPS = ("sonarr", "radarr")
# Passthrough endpoints that expose credentials in their response body and
# are therefore refused outright (the arr's own apiKey lives in config/host).
# Matched against the normalized /api/v3/... path, prefix semantics.
PASSTHROUGH_DENY = ("/api/v3/config/host",)

QBIT_URL = "http://localhost:8080"
# qbit sees /data/downloads == /docker/plex/media/downloads
QBIT_PATH_PREFIX = "/data/downloads"

# Compose stacks the runner may act on (down/up only, never `restart`).
PLEX_STACK = "plex-stack"
STACKS = {
    "plex-stack": "/docker/homelab-config/nemesis/composed-apps/plex-stack",
}

MALWARE_EXT = (".exe", ".scr", ".rar", ".lnk", ".zipx")
VIDEO_EXT = (".mkv", ".mp4", ".avi", ".m2ts", ".ts", ".webm", ".m4v")
SPARSE_RATIO = 0.95


# ---------------------------------------------------------------------------
# Error type shared by probes/actions/runner


class PlexOpsError(Exception):
    """Carries the contract's JSON error envelope (CONTRACT.md section 2)."""

    def __init__(self, code, message, status=500, detail=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.detail = detail

    def envelope(self):
        env = {"ok": False, "error": self.code, "message": self.message}
        if self.detail is not None:
            env["detail"] = self.detail
        return env


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


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def stamp():
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def run(cmd, check=True, capture=True, cwd=None, input_text=None):
    """Run a command list; return stdout as text."""
    res = subprocess.run(
        cmd,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        input=input_text,
    )
    if check and res.returncode != 0:
        raise RuntimeError(
            "command failed (%d): %s\n%s"
            % (res.returncode, " ".join(cmd), (res.stderr or "").strip()[:500])
        )
    return res.stdout if capture else ""


def sudo(cmd, check=True, cwd=None, input_text=None):
    return run(["sudo", "-n"] + cmd, check=check, cwd=cwd, input_text=input_text)


def sudo_ok():
    try:
        run(["sudo", "-n", "true"])
        return True
    except Exception:
        return False


def read_env(path=None):
    """KEY=value env file -> dict. Falls back to `sudo -n cat` for root-owned
    0600 files (the runner env). Missing file -> empty dict."""
    path = path or ENV_FILE
    text = None
    try:
        with open(path) as fh:
            text = fh.read()
    except FileNotFoundError:
        return {}
    except PermissionError:
        try:
            text = sudo(["cat", path])
        except Exception:
            return {}
    env = {}
    for ln in text.splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def runner_token(path=None):
    """The single bearer token every runner call must present. Refuses the
    committed example placeholder and anything shorter than TOKEN_MIN_LEN so
    a skipped/failed `sed` in the install runbook cannot leave the service
    authenticating against a publicly-known value."""
    env = read_env(path)
    token = env.get(TOKEN_VAR) or os.environ.get(TOKEN_VAR)
    if not token:
        raise PlexOpsError(
            "internal", "%s not set in %s or environment" % (TOKEN_VAR, path or ENV_FILE)
        )
    if token == TOKEN_PLACEHOLDER:
        raise PlexOpsError(
            "internal",
            "%s is still the example placeholder; generate a real token "
            "(openssl rand -hex 32) in %s" % (TOKEN_VAR, path or ENV_FILE),
        )
    if len(token) < TOKEN_MIN_LEN:
        raise PlexOpsError(
            "internal",
            "%s is shorter than %d characters; generate a stronger token "
            "(openssl rand -hex 32)" % (TOKEN_VAR, TOKEN_MIN_LEN),
        )
    return token


def load_json(path, default=None):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError):
        return default


def save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True, default=str)
        fh.write("\n")
    os.replace(tmp, path)


def ensure_log_dir():
    """Create LOG_ROOT owned by the invoking user so plain writes work
    afterwards. Idempotent."""
    me = run(["id", "-un"]).strip()
    sudo(["install", "-d", "-o", me, "-g", me, "-m", "0770", LOG_ROOT])


def audit_append(record):
    """Append ONE compact JSON line to AUDIT_LOG (CONTRACT.md section 6).
    Adds ts when absent. Never raises into the caller's request handling:
    an audit failure is logged to stderr, not surfaced to the client."""
    if "ts" not in record:
        record["ts"] = now_iso()
    line = json.dumps(record, separators=(",", ":"), default=str)
    try:
        with open(AUDIT_LOG, "a") as fh:
            fh.write(line + "\n")
        return
    except (FileNotFoundError, PermissionError):
        pass
    try:
        ensure_log_dir()
        with open(AUDIT_LOG, "a") as fh:
            fh.write(line + "\n")
    except Exception:
        try:
            sudo(["tee", "-a", AUDIT_LOG], input_text=line + "\n")
        except Exception as e:
            log("audit_append failed: %s" % e)


# ---------------------------------------------------------------------------
# Generic HTTP


def http_json(url, method="GET", headers=None, body=None, timeout=60):
    """Return (status, parsed_json_or_None). HTTP error statuses are returned,
    not raised; a connection-level failure raises PlexOpsError 502."""
    data = None
    hdrs = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read()
        status = e.code
    except (urllib.error.URLError, OSError) as e:
        raise PlexOpsError("upstream-error", "%s %s: %s" % (method, url, e), 502)
    if not raw:
        return status, None
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, None


# ---------------------------------------------------------------------------
# Radarr / Sonarr / Prowlarr API


def arr_key(app):
    cfg = ARR[app]["config"]
    out = sudo(["grep", "-oP", "<ApiKey>\\K[^<]+", cfg])
    key = out.strip()
    if not key:
        raise PlexOpsError("upstream-error", "no ApiKey found in %s" % cfg, 502)
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
        raise PlexOpsError(
            "upstream-error",
            "%s %s %s -> HTTP %d: %s" % (app, method, path, e.code, e.read()[:300]),
            502,
        )
    except (urllib.error.URLError, OSError) as e:
        raise PlexOpsError("upstream-error", "%s %s %s: %s" % (app, method, path, e), 502)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        raise PlexOpsError(
            "upstream-error",
            "%s %s %s returned garbage (non-JSON 2xx body, %d bytes)"
            % (app, method, path, len(raw)),
            502,
        )


def arr_get(app, path, params=None):
    return arr_call(app, "GET", path, params=params)


def arr_get_raw(app, path_qs, timeout=120):
    """Read-only passthrough transport: relay the upstream's status,
    content-type, and body. Connection failure raises 502. The arr's own
    api key is redacted from the body wherever it appears so no passthrough
    response can leak it (defense-in-depth on top of PASSTHROUGH_DENY)."""
    url = ARR[app]["url"] + path_qs
    key = arr_key(app)
    req = urllib.request.Request(url, headers={"X-Api-Key": key}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            ctype = resp.headers.get("Content-Type", "application/json")
            body = resp.read()
    except urllib.error.HTTPError as e:
        status = e.code
        ctype = e.headers.get("Content-Type", "application/json")
        body = e.read()
    except (urllib.error.URLError, OSError) as e:
        raise PlexOpsError("upstream-error", "%s GET %s: %s" % (app, path_qs, e), 502)
    if key:
        body = body.replace(key.encode(), b"REDACTED")
    return status, ctype, body


def prowlarr_ping(timeout=10):
    """{"ok": bool, "ms": int|None, "error": str|None} - never raises."""
    t0 = time.time()
    try:
        status, _ = http_json(ARR["prowlarr"]["url"] + "/ping", timeout=timeout)
    except PlexOpsError as e:
        return {"ok": False, "ms": None, "error": e.message}
    ms = int((time.time() - t0) * 1000)
    if status == 200:
        return {"ok": True, "ms": ms, "error": None}
    return {"ok": False, "ms": ms, "error": "HTTP %d" % status}


# ---------------------------------------------------------------------------
# Queue classification + contract item shape (CONTRACT.md 3.1). This is THE
# single implementation: probes.py re-exports it and actions.py calls it, so
# queue-remove's `expect` pre-verification can never drift from the probe.

CLASSES = ("malware-ext", "not-upgrade", "mapping-mismatch", "sample-stall", "unknown")

# A malware extension counts only when followed by end-of-string or a
# non-alphanumeric delimiter, so "The.Scream.1996" does not trip ".scr" but
# "setup.exe" and "extension: '.exe'" do.
MALWARE_RE = re.compile(
    r"(?i)(?:%s)(?=$|[^a-z0-9])" % "|".join(re.escape(e) for e in MALWARE_EXT)
)

# "Not an upgrade for existing episode file(s)" family
NOT_UPGRADE_PATTERNS = (
    "not an upgrade",
    "not a custom format upgrade",
    "of equal or higher quality",
)

# "Series title mismatch; automatic import is not possible" /
# "Episode 5x06 was not found in the grabbed release" / "Invalid season or
# episode" / unparseable-mapping family
MAPPING_PATTERNS = (
    "title mismatch",
    "was not found in the grabbed release",
    "invalid season or episode",
    "unable to parse",
    "does not match the grabbed release",
)

# "Unable to determine if file is a sample" family
SAMPLE_PATTERNS = ("sample",)

# Stalled-torrent messages; only counted for a warning item with bytes left.
STALL_PATTERNS = ("stall", "no connection")

# arr container path -> host path (compose: /data -> MEDIA, /data2 -> MEDIA2)
ARR_PATH_MAP = (("/data2", MEDIA2), ("/data", MEDIA))


def arr_host_path(path):
    """Translate an arr-container path to its host-visible equivalent."""
    if not path:
        return path
    for prefix, root in ARR_PATH_MAP:
        if path == prefix or path.startswith(prefix + "/"):
            return root + path[len(prefix):]
    return path


def _status_texts(item):
    """Every human-readable status string on a queue item, verbatim."""
    texts = []
    for sm in item.get("statusMessages") or []:
        t = sm.get("title")
        if t:
            texts.append(t)
        for m in sm.get("messages") or []:
            if m:
                texts.append(m)
    em = item.get("errorMessage")
    if em:
        texts.append(em)
    return texts


def _match_patterns(texts, patterns):
    """The texts containing any of the (lowercase) substring patterns."""
    return [t for t in texts if any(p in t.lower() for p in patterns)]


def classify_queue_item(item, app=None):
    """Classify one raw arr queue item -> (classification, evidence).

    Exactly one of CLASSES; evidence carries the verbatim status messages
    (or title/outputPath lines) that triggered the classification. Precedence
    is the contract's listing order: malware-ext beats everything, unknown
    catches the rest INCLUDING healthy in-progress items.
    """
    texts = _status_texts(item)

    evidence = [t for t in texts if MALWARE_RE.search(t)]
    for label, val in (("title", item.get("title")), ("outputPath", item.get("outputPath"))):
        if val and MALWARE_RE.search(val):
            evidence.append("%s: %s" % (label, val))
    if evidence:
        return "malware-ext", evidence

    evidence = _match_patterns(texts, NOT_UPGRADE_PATTERNS)
    if evidence:
        return "not-upgrade", evidence

    evidence = _match_patterns(texts, MAPPING_PATTERNS)
    if evidence:
        return "mapping-mismatch", evidence

    evidence = _match_patterns(texts, SAMPLE_PATTERNS)
    if evidence:
        return "sample-stall", evidence
    if (item.get("sizeleft") or 0) > 0 and \
            (item.get("trackedDownloadStatus") or "").lower() == "warning":
        evidence = _match_patterns(texts, STALL_PATTERNS)
        if evidence:
            return "sample-stall", evidence

    return "unknown", texts


QUEUE_PAGE_SIZE = 250
QUEUE_MAX_PAGES = 40


def fetch_queue(app):
    """The arr's full queue as a list of raw records (paged to totalRecords)."""
    include = "includeUnknownSeriesItems" if app == "sonarr" else "includeUnknownMovieItems"
    records = []
    page = 1
    while True:
        data = arr_get(app, "/api/v3/queue", params={
            "page": page, "pageSize": QUEUE_PAGE_SIZE, include: "true",
        })
        if not isinstance(data, dict):
            raise PlexOpsError("upstream-error", "%s queue: unexpected response" % app, 502)
        batch = data.get("records") or []
        records.extend(batch)
        total = data.get("totalRecords", len(records))
        if len(records) >= total or not batch or page >= QUEUE_MAX_PAGES:
            return records
        page += 1


def queue_item_view(raw, app):
    """One CONTRACT.md section-3.1-shaped queue item from a raw arr record
    (host-visible output_path, classification + evidence attached)."""
    classification, evidence = classify_queue_item(raw, app)
    if app == "sonarr":
        series_id = raw.get("seriesId")
        episode_ids = raw.get("episodeIds")
        if episode_ids is None:
            eid = raw.get("episodeId")
            episode_ids = [eid] if eid is not None else []
        movie_id = None
    else:
        series_id = None
        episode_ids = None
        movie_id = raw.get("movieId")
    return {
        "id": raw.get("id"),
        "app": app,
        "title": raw.get("title"),
        "download_id": raw.get("downloadId"),
        "protocol": raw.get("protocol"),
        "status": raw.get("status"),
        "tracked_download_status": raw.get("trackedDownloadStatus"),
        "tracked_download_state": raw.get("trackedDownloadState"),
        "size": raw.get("size"),
        "sizeleft": raw.get("sizeleft"),
        "output_path": arr_host_path(raw.get("outputPath")),
        "series_id": series_id,
        "episode_ids": episode_ids,
        "movie_id": movie_id,
        "classification": classification,
        "evidence": evidence,
    }


# ---------------------------------------------------------------------------
# qBittorrent API (optional -- requires QBIT_USER/QBIT_PASS in ENV_FILE)


class Qbit:
    def __init__(self, env_path=None):
        env = read_env(env_path)
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
            log("qbit login rejected (check QBIT_USER/QBIT_PASS in %s)" % ENV_FILE)
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
    """Torrents that own host_path_prefix, in EITHER direction: the torrent's
    content path is at/under the target, OR the target is inside the torrent's
    content dir (deleting one file of a multi-file torrent is still touching
    an active torrent's payload). None if qbit unavailable."""
    if qbit is None or not qbit.available:
        return None
    target = host_path_prefix.rstrip("/")
    hits = []
    for t in qbit.torrents():
        hcp = (t["host_content_path"] or "").rstrip("/")
        if not hcp:
            continue
        if hcp == target or hcp.startswith(target + "/") or target.startswith(hcp + "/"):
            hits.append(t)
    return hits


# ---------------------------------------------------------------------------
# Docker (all via sudo -n; compose = down/up only, never `restart`)


def _compose_project(labels):
    for part in (labels or "").split(","):
        if part.startswith("com.docker.compose.project="):
            return part.split("=", 1)[1]
    return None


def docker_ps_all():
    """All containers -> [{"name","state","status","stack","image"}]."""
    out = sudo(["docker", "ps", "-a", "--no-trunc", "--format", "{{json .}}"])
    rows = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        rows.append({
            "name": d.get("Names", ""),
            "state": d.get("State", ""),
            "status": d.get("Status", ""),
            "stack": _compose_project(d.get("Labels", "")),
            "image": d.get("Image", ""),
        })
    return rows


def container_state(name):
    """docker inspect one container -> dict, or None when it does not exist."""
    try:
        out = sudo(["docker", "inspect", name])
    except RuntimeError:
        return None
    try:
        info = json.loads(out)[0]
    except (ValueError, IndexError):
        return None
    st = info.get("State", {})
    health = st.get("Health", {}).get("Status") if st.get("Health") else None
    return {
        "state": st.get("Status"),
        "health": health,
        "exit_code": st.get("ExitCode"),
        "status": st.get("Status"),
        "started_at": st.get("StartedAt"),
        "image_id": info.get("Image"),
    }


def docker_stats(names=None):
    """One-shot stats -> [{"name","cpu_percent", ...raw fields}]."""
    cmd = ["docker", "stats", "--no-stream", "--format", "{{json .}}"]
    if names:
        cmd += list(names)
    out = sudo(cmd, check=False)
    rows = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        cpu = None
        try:
            cpu = float(d.get("CPUPerc", "").rstrip("%"))
        except ValueError:
            pass
        d["name"] = d.get("Name", "")
        d["cpu_percent"] = cpu
        rows.append(d)
    return rows


def exited_255(stacks=None):
    """Exited(255) stragglers in the known stacks -> [{"name","status","stack"}].
    unless-stopped does not reliably resurrect these after a host crash."""
    wanted = set(stacks if stacks is not None else STACKS)
    out = []
    for c in docker_ps_all():
        if c["stack"] in wanted and c["status"].startswith("Exited (255)"):
            out.append({"name": c["name"], "status": c["status"], "stack": c["stack"]})
    return out


def compose(stack, args, check=True):
    """Run `sudo -n docker compose <args>` in the stack's compose dir.
    Callers restart services as down then up -d, never `compose restart`."""
    if stack not in STACKS:
        raise PlexOpsError("bad-request", "unknown stack: %s" % stack, 400)
    return sudo(["docker", "compose"] + list(args), check=check, cwd=STACKS[stack])


def gluetun_egress_ip(timeout=20):
    """Public IP as seen from inside the gluetun container, or None."""
    try:
        out = sudo(
            ["docker", "exec", "gluetun", "wget", "-qO-", "-T", str(timeout),
             "https://api.ipify.org"],
            check=False,
        ).strip()
    except Exception:
        return None
    return out if out and len(out) <= 45 and " " not in out else None


# ---------------------------------------------------------------------------
# Filesystem probes (all via sudo; mounts are plexadm 0770). Read-only:
# the only deleter in the suite is actions.py, on contract-verified paths.


def is_sparse(size_bytes, blocks512):
    """True when a file's allocation is well short of its apparent size -
    a hollow/truncated shell (seen in the 2024-10 trash: 737G apparent was
    only ~387G real). Real media files are fully allocated."""
    return size_bytes > 0 and blocks512 * 512 < size_bytes * SPARSE_RATIO


def stat_file(path):
    """{"nlink","size_bytes","blocks512","mtime","sparse"} or None if missing."""
    try:
        out = sudo(["stat", "-c", "%h %s %b %Y", path])
        h, s, b, m = out.split()
        size, blocks = int(s), int(b)
        return {
            "nlink": int(h),
            "size_bytes": size,
            "blocks512": blocks,
            "mtime": int(m),
            "sparse": is_sparse(size, blocks),
        }
    except Exception:
        return None


def find_files_blocks(roots, extra_args=None):
    """Yield (size, nlink, dirname, filename, blocks512) for regular files
    under roots - blocks expose hollow/truncated files whose apparent size
    lies (see is_sparse)."""
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


def samefile_hits(path, root=DOWNLOADS):
    """Paths under root hardlinked to path (excluding path itself)."""
    try:
        out = sudo(["find", root, "-samefile", path], check=False)
    except Exception:
        return []
    return [p for p in out.splitlines() if p and p != path]


def safe_download_path(path):
    """Normalize and validate a delete-download target: must be strictly under
    DOWNLOADS with no .Trash component. Returns the normalized path or raises
    PlexOpsError 400. This is a policy gate, not an existence check."""
    if not isinstance(path, str) or not path.startswith("/") or "\n" in path or "\x00" in path:
        raise PlexOpsError("bad-request", "path must be an absolute path string", 400)
    norm = os.path.normpath(path)
    prefix = DOWNLOADS + os.sep
    if not norm.startswith(prefix) or norm == DOWNLOADS:
        raise PlexOpsError(
            "bad-request", "path must be strictly under %s" % DOWNLOADS, 400,
            detail={"path": norm},
        )
    for part in norm.split(os.sep):
        if part.startswith(".Trash"):
            raise PlexOpsError(
                "bad-request", "refusing .Trash path", 400, detail={"path": norm}
            )
    return norm


def df_mounts():
    """df both media mounts -> {mount: {"size_bytes","used_bytes","avail_bytes",
    "used_percent"}}."""
    out = run(["df", "-B1", "--output=target,size,used,avail", MEDIA, MEDIA2])
    mounts = {}
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) != 4:
            continue
        target, size, used, avail = parts[0], int(parts[1]), int(parts[2]), int(parts[3])
        mounts[target] = {
            "size_bytes": size,
            "used_bytes": used,
            "avail_bytes": avail,
            "used_percent": round(used * 100.0 / size, 1) if size else 0.0,
        }
    return mounts


def is_video(name):
    return name.lower().endswith(VIDEO_EXT)


# ---------------------------------------------------------------------------
# Media-reclaim campaign (compression waves). State is the NFS-shared
# /docker/plex/media/.reclaim/ tree written by scripts/media-reclaim/ on
# nemesis and the media-transcoder worker (devastator or wherever the GPU
# is); reports are the stamped dirs under /docker/plex/logs/media-reclaim/.
# CONTRACT.md sections 3.6, 3.7, 5.9-5.12.

RECLAIM_STATE = os.path.join(MEDIA, ".reclaim")
RECLAIM_QUEUE = os.path.join(RECLAIM_STATE, "queue", "queue.tsv")
RECLAIM_DONE = os.path.join(RECLAIM_STATE, "done.list")
RECLAIM_FAILED = os.path.join(RECLAIM_STATE, "failed.list")
RECLAIM_LEDGER = os.path.join(RECLAIM_STATE, "ledger.tsv")
RECLAIM_STATUS_MD = os.path.join(RECLAIM_STATE, "status.md")
RECLAIM_PAUSE = os.path.join(RECLAIM_STATE, "PAUSE")
RECLAIM_PILOT_ACK = os.path.join(RECLAIM_STATE, "PILOT_ACK")
RECLAIM_LOG = "/docker/plex/logs/media-reclaim"
RECLAIM_DF_LOG = os.path.join(RECLAIM_LOG, "df-checkpoints.log")
RECLAIM_SCRIPTS = os.path.join(os.path.dirname(SCRIPT_DIR), "media-reclaim")
RECLAIM_KEEP_LIST = os.path.join(RECLAIM_SCRIPTS, "keep-list.conf")
TRANSCODE_POLICY = os.path.join(os.path.dirname(os.path.dirname(SCRIPT_DIR)),
                                "devastator", "composed-apps", "media-transcoder",
                                "transcode-policy.conf")
PLEX_ROOT = "/docker/plex"                      # queue rel_paths are relative to this
# Encode throughput used for the plan (source GiB per hour). ~1 movie/hour
# per the campaign design; override with RECLAIM_GB_PER_HOUR in the env.
RECLAIM_GB_PER_HOUR_DEFAULT = 60.0
# Source-size bands the plan reports (GiB): large >= 60, medium >= 40, else small.
RECLAIM_BANDS = (("large", 60.0), ("medium", 40.0))
RECLAIM_PILOT_LIMIT_DEFAULT = 3


def reclaim_gb_per_hour():
    try:
        v = float(os.environ.get("RECLAIM_GB_PER_HOUR") or RECLAIM_GB_PER_HOUR_DEFAULT)
    except ValueError:
        v = RECLAIM_GB_PER_HOUR_DEFAULT
    return v if v > 0 else RECLAIM_GB_PER_HOUR_DEFAULT


def size_band(size_gb):
    for name, floor in RECLAIM_BANDS:
        if size_gb >= floor:
            return name
    return "small"


def read_text(path):
    """File text, `sudo -n cat` fallback for unreadable files; None if missing."""
    try:
        with open(path) as fh:
            return fh.read()
    except FileNotFoundError:
        return None
    except PermissionError:
        try:
            return sudo(["cat", path])
        except Exception:
            return None


def read_lines(path):
    text = read_text(path)
    return [ln for ln in text.splitlines() if ln.strip()] if text else []


def read_tsv_dicts(path):
    """Tab-separated file with a header row -> list of dicts ([] if missing)."""
    lines = read_lines(path)
    if not lines:
        return []
    header = lines[0].split("\t")
    out = []
    for ln in lines[1:]:
        cells = ln.split("\t")
        cells += [""] * (len(header) - len(cells))
        out.append(dict(zip(header, cells)))
    return out


def reclaim_keep_patterns():
    return [ln.strip().lower() for ln in read_lines(RECLAIM_KEEP_LIST)
            if not ln.strip().startswith("#")]


def reclaim_keep_match(title):
    t = (title or "").lower()
    return any(p and p in t for p in reclaim_keep_patterns())


def reclaim_flags():
    return {"paused": os.path.exists(RECLAIM_PAUSE),
            "pilot_ack": os.path.exists(RECLAIM_PILOT_ACK),
            "pilot_notified": os.path.exists(os.path.join(RECLAIM_STATE, ".pilot-notified")),
            "complete_notified": os.path.exists(os.path.join(RECLAIM_STATE, ".complete-notified"))}


def reclaim_policy():
    """KEY=value pairs from the transcoder policy (WINDOWS, PILOT_LIMIT, ...)."""
    pol = {}
    for ln in read_lines(TRANSCODE_POLICY):
        ln = ln.strip()
        if ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        pol[k.strip()] = v.strip().strip('"').strip("'")
    return pol


def reclaim_windows(policy=None):
    """Parse WINDOWS="daily 22:30-06:30; Mon-Fri 08:30-16:30" ->
    [{"days", "start_min", "end_min", "label", "overnight"}]. Mirrors the
    worker's in_window(); overnight spans (end <= start) wrap past midnight."""
    pol = policy if policy is not None else reclaim_policy()
    spec = pol.get("WINDOWS") or "daily 22:30-06:30"
    out = []
    for w in spec.split(";"):
        w = w.strip()
        if not w or " " not in w:
            continue
        days, times = w.split(None, 1)
        try:
            s, e = times.strip().split("-")
            sh, sm = (int(x) for x in s.split(":"))
            eh, em = (int(x) for x in e.split(":"))
        except ValueError:
            continue
        start_min, end_min = sh * 60 + sm, eh * 60 + em
        out.append({"days": days, "start_min": start_min, "end_min": end_min,
                    "label": w, "overnight": end_min <= start_min})
    return out


_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _day_ok(days, weekday):
    d = days.lower()
    if d == "daily":
        return True
    if "-" in d:
        a, b = d.split("-", 1)
        if a[:3] in _DAYS and b[:3] in _DAYS:
            ia, ib = _DAYS.index(a[:3]), _DAYS.index(b[:3])
            return ia <= weekday <= ib if ia <= ib else (weekday >= ia or weekday <= ib)
    return d[:3] in _DAYS and _DAYS.index(d[:3]) == weekday


def reclaim_window_occurrences(now=None, windows=None, days=(-1, 0, 1)):
    """Concrete window occurrences around `now` (naive local datetimes):
    [{"label", "days", "start", "end", "hours", "overnight"}] sorted by start."""
    from datetime import timedelta
    now = now or datetime.now()
    wins = windows if windows is not None else reclaim_windows()
    occ = []
    for off in days:
        day = (now + timedelta(days=off)).replace(hour=0, minute=0, second=0, microsecond=0)
        for w in wins:
            if not _day_ok(w["days"], day.weekday()):
                continue
            start = day + timedelta(minutes=w["start_min"])
            span = w["end_min"] - w["start_min"]
            if span <= 0:
                span += 1440
            end = start + timedelta(minutes=span)
            occ.append({"label": w["label"], "days": w["days"], "start": start, "end": end,
                        "hours": round(span / 60.0, 2), "overnight": w["overnight"]})
    occ.sort(key=lambda o: o["start"])
    return occ


def reclaim_window_state(now=None, windows=None):
    """{"in_window", "current": {...,"remaining_hours"}|None, "next": {...}|None}"""
    now = now or datetime.now()
    occ = reclaim_window_occurrences(now, windows)
    current = next((o for o in occ if o["start"] <= now < o["end"]), None)
    upcoming = next((o for o in occ if o["start"] > now), None)

    def view(o, remaining=False):
        if not o:
            return None
        v = {"label": o["label"], "start": o["start"].isoformat(timespec="minutes"),
             "end": o["end"].isoformat(timespec="minutes"), "hours": o["hours"],
             "overnight": o["overnight"]}
        if remaining:
            v["remaining_hours"] = round((o["end"] - now).total_seconds() / 3600.0, 2)
        return v
    return {"in_window": current is not None, "current": view(current, True),
            "next": view(upcoming)}


def reclaim_pick_window(kind, now=None, windows=None):
    """The occurrence a plan targets: "tonight" = the current or next
    overnight window; "workday" = the next daytime window; "next" = the
    current window else the soonest. Returns (occurrence|None, budget_hours)."""
    now = now or datetime.now()
    occ = reclaim_window_occurrences(now, windows)
    live = [o for o in occ if o["end"] > now]
    if kind == "tonight":
        cands = [o for o in live if o["overnight"]]
    elif kind == "workday":
        cands = [o for o in live if not o["overnight"]]
    else:
        cands = live
    if not cands:
        return None, 0.0
    o = cands[0]
    budget = (o["end"] - max(now, o["start"])).total_seconds() / 3600.0
    return o, round(budget, 2)


def latest_reclaim_report():
    """(report_dir, candidates_tsv, age_seconds) for the newest scan, or None."""
    try:
        dirs = sorted(d for d in os.listdir(RECLAIM_LOG)
                      if re.match(r"^\d{4}-\d{2}-\d{2}_\d{6}$", d)
                      and os.path.exists(os.path.join(RECLAIM_LOG, d, "candidates_movies.tsv")))
    except FileNotFoundError:
        return None
    if not dirs:
        return None
    d = os.path.join(RECLAIM_LOG, dirs[-1])
    tsv = os.path.join(d, "candidates_movies.tsv")
    return d, tsv, max(0.0, time.time() - os.path.getmtime(tsv))


def run_reclaim_scan():
    """`scan_candidates.py` (read-only; writes a stamped report). -> report tuple."""
    run(["python3", os.path.join(RECLAIM_SCRIPTS, "scan_candidates.py")],
        cwd=RECLAIM_SCRIPTS)
    rep = latest_reclaim_report()
    if rep is None:
        raise PlexOpsError("upstream-error", "scan produced no candidates report", 502)
    return rep


def reclaim_queue_rows():
    """queue.tsv rows: [{"rel_path","size_bytes","est_target_gb","title"}]."""
    return read_tsv_dicts(RECLAIM_QUEUE)


def reclaim_done_set():
    return set(read_lines(RECLAIM_DONE))


def reclaim_failed_map():
    out = {}
    for ln in read_lines(RECLAIM_FAILED):
        rel, _, reason = ln.partition("\t")
        out[rel] = reason
    return out


def reclaim_saved_bytes():
    """Sum of `saved:N` from ledger transcode-replace rows."""
    total = 0
    for r in read_tsv_dicts(RECLAIM_LEDGER):
        if r.get("action") == "transcode-replace" and (r.get("status") or "").startswith("saved:"):
            try:
                total += int(r["status"][6:])
            except ValueError:
                pass
    return total


def reclaim_rel_path(primary_path):
    return os.path.relpath(primary_path, PLEX_ROOT)


def write_reclaim_queue(rows):
    """Write queue.tsv (rows of (rel_path, size_bytes, est_target_gb, title)),
    largest first, via a temp file + `sudo install` so the worker never sees a
    half-written queue. The keep-list is re-checked here regardless of input."""
    import tempfile
    for r in rows:
        if reclaim_keep_match(r[3]) or reclaim_keep_match(os.path.basename(os.path.dirname(r[0]))):
            raise PlexOpsError("verify-failed", "keep-list title refused: %s" % r[3], 409,
                               {"title": r[3]})
    rows = sorted(rows, key=lambda r: -int(r[1]))
    fd, tmp = tempfile.mkstemp(prefix="queue.", suffix=".tsv")
    with os.fdopen(fd, "w") as fh:
        fh.write("rel_path\tsize_bytes\test_target_gb\ttitle\n")
        for rel, size, tgt, title in rows:
            fh.write("%s\t%d\t%s\t%s\n" % (rel, int(size), tgt, title))
    try:
        sudo(["install", "-d", "-m", "0775", os.path.dirname(RECLAIM_QUEUE)])
        sudo(["install", "-m", "0664", tmp, RECLAIM_QUEUE])
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Plex (watch history) and Seerr (requests) - read-only, for the title-stats
# probe (CONTRACT.md 3.8). Plex runs on devastator; the admin token comes
# from PLEX_TOKEN in the runner env file. Seerr runs in plex-stack on this
# host; its api key is read from its settings file (or SEERR_API_KEY).

PLEX_URL_DEFAULT = "http://devastator.rt-541.io:32400"
SEERR_URL_DEFAULT = "http://localhost:5055"
SEERR_SETTINGS = "/docker/seerr/settings.json"
PLEX_HISTORY_PAGE = 1000
PLEX_CACHE_TTL_S = 600
_plex_cache = {}


def plex_config():
    env = read_env()
    url = (os.environ.get("PLEX_URL") or env.get("PLEX_URL") or PLEX_URL_DEFAULT).rstrip("/")
    token = os.environ.get("PLEX_TOKEN") or env.get("PLEX_TOKEN") or ""
    return url, token


def plex_get(path, params=None, timeout=30):
    """GET a Plex endpoint as JSON -> the MediaContainer dict."""
    url, token = plex_config()
    if not token:
        raise PlexOpsError("upstream-error", "PLEX_TOKEN is not configured in the runner env", 502)
    q = dict(params or {})
    full = url + path + (("&" if "?" in path else "?") + urllib.parse.urlencode(q) if q else "")
    status, parsed = http_json(full, headers={"X-Plex-Token": token, "Accept": "application/json"},
                               timeout=timeout)
    if status != 200 or not isinstance(parsed, dict):
        raise PlexOpsError("upstream-error", "plex GET %s -> HTTP %d" % (path, status), 502)
    return parsed.get("MediaContainer") or {}


def _cached(key, ttl, fn):
    hit = _plex_cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _plex_cache[key] = (time.time(), val)
    return val


def plex_sections():
    """[{"key", "type", "title"}]"""
    return _cached("sections", PLEX_CACHE_TTL_S, lambda: [
        {"key": str(d.get("key")), "type": d.get("type"), "title": d.get("title")}
        for d in plex_get("/library/sections").get("Directory", [])])


def plex_accounts():
    """accountID -> display name (Plex home/friends as the server knows them)."""
    def _load():
        out = {}
        for a in plex_get("/accounts").get("Account", []):
            out[int(a.get("id"))] = a.get("name") or ("account %s" % a.get("id"))
        return out
    return _cached("accounts", PLEX_CACHE_TTL_S, _load)


def plex_find_item(section_type, title, year=None, ids=None):
    """Locate a library item by external id (tmdb/tvdb/imdb, most reliable)
    with a title+year fallback. -> {"rating_key","title","year","added_at",
    "guids"} or None."""
    ids = {k: str(v) for k, v in (ids or {}).items() if v}
    hits = []
    for sec in plex_sections():
        if sec["type"] != section_type:
            continue
        # a broad title search first (Plex matches substrings), then exact ids
        for m in plex_get("/library/sections/%s/all" % sec["key"],
                          {"includeGuids": 1, "title": title,
                           "X-Plex-Container-Size": 50}).get("Metadata", []):
            guids = [g.get("id") for g in m.get("Guid", []) if g.get("id")]
            hits.append({"rating_key": str(m.get("ratingKey")), "title": m.get("title"),
                         "year": m.get("year"), "added_at": m.get("addedAt"), "guids": guids})
    for h in hits:
        for provider, val in ids.items():
            if "%s://%s" % (provider, val) in h["guids"]:
                return h
    low = (title or "").lower()
    exact = [h for h in hits if (h["title"] or "").lower() == low
             and (year is None or h["year"] == year)]
    return exact[0] if exact else None


def plex_history(section_id):
    """Every history row of a library section (cached 10 min)."""
    def _load():
        rows, start = [], 0
        while True:
            mc = plex_get("/status/sessions/history/all",
                          {"librarySectionID": section_id, "sort": "viewedAt:desc",
                           "X-Plex-Container-Start": start,
                           "X-Plex-Container-Size": PLEX_HISTORY_PAGE})
            page = mc.get("Metadata", [])
            rows.extend(page)
            start += len(page)
            if not page or start >= int(mc.get("totalSize") or 0):
                break
        return rows
    return _cached("history:%s" % section_id, PLEX_CACHE_TTL_S, _load)


def plex_watch_stats(section_type, rating_key):
    """Watch stats for a movie (its own rating key) or a show (its episodes'
    grandparentKey): distinct watchers, plays, per-user detail, first/last."""
    section = next((s for s in plex_sections() if s["type"] == section_type), None)
    if section is None:
        return None
    rows = plex_history(section["key"])
    want_key = "/library/metadata/%s" % rating_key
    if section_type == "show":
        mine = [r for r in rows if r.get("grandparentKey") == want_key]
    else:
        mine = [r for r in rows if str(r.get("ratingKey")) == str(rating_key)]
    names = plex_accounts()
    per = {}
    for r in mine:
        acct = r.get("accountID")
        p = per.setdefault(acct, {"account_id": acct, "name": names.get(acct, "account %s" % acct),
                                  "plays": 0, "items": set(), "last": 0})
        p["plays"] += 1
        p["items"].add(str(r.get("ratingKey")))
        p["last"] = max(p["last"], int(r.get("viewedAt") or 0))
    users = sorted(({"account_id": p["account_id"], "name": p["name"], "plays": p["plays"],
                     "distinct_items": len(p["items"]), "last_watched": _ts(p["last"])}
                    for p in per.values()), key=lambda u: -u["plays"])
    times = [int(r.get("viewedAt") or 0) for r in mine if r.get("viewedAt")]
    return {"watchers": len(per), "plays": len(mine), "users": users,
            "first_watched": _ts(min(times)) if times else None,
            "last_watched": _ts(max(times)) if times else None}


def _ts(epoch):
    if not epoch:
        return None
    return datetime.fromtimestamp(int(epoch)).astimezone().isoformat(timespec="minutes")


def seerr_config():
    env = read_env()
    url = (os.environ.get("SEERR_URL") or env.get("SEERR_URL") or SEERR_URL_DEFAULT).rstrip("/")
    key = os.environ.get("SEERR_API_KEY") or env.get("SEERR_API_KEY")
    if not key:
        try:
            key = (json.loads(read_text(SEERR_SETTINGS) or "{}").get("main") or {}).get("apiKey")
        except ValueError:
            key = None
    return url, key or ""


def seerr_requests_for(kind, tmdb_id):
    """Requests Seerr holds for a movie/tv tmdb id -> [{"by","email","date",
    "status","is4k"}]; [] when Seerr knows the title but nobody requested it;
    None when Seerr has no record of the title at all (or is unreachable)."""
    if not tmdb_id:
        return None
    url, key = seerr_config()
    if not key:
        return None
    status, parsed = http_json("%s/api/v1/%s/%d" % (url, "tv" if kind == "show" else "movie", int(tmdb_id)),
                               headers={"X-Api-Key": key}, timeout=30)
    if status == 404 or not isinstance(parsed, dict):
        return None
    if status != 200:
        raise PlexOpsError("upstream-error", "seerr -> HTTP %d" % status, 502)
    info = parsed.get("mediaInfo") or {}
    out = []
    for r in info.get("requests") or []:
        by = r.get("requestedBy") or {}
        out.append({"by": by.get("displayName") or by.get("plexUsername") or by.get("email"),
                    "email": by.get("email"), "date": (r.get("createdAt") or "")[:10],
                    "status": {1: "pending", 2: "approved", 3: "declined"}.get(r.get("status"), r.get("status")),
                    "is4k": bool(r.get("is4k"))})
    return sorted(out, key=lambda x: x["date"])
