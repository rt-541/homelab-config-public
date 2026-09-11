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
