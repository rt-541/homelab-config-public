"""Deterministic read-only probes for the plex-ops action-runner.

Python 3.9 stdlib only. Imports only plexops_lib (+ stdlib); no HTTP-server
awareness. Each probe takes the parsed query params as a dict[str, str] and
returns the CONTRACT.md section-3 payload WITHOUT the "ok" key (the runner
adds it), raising plexops_lib.PlexOpsError on bad params or upstream failure.

The only state a probe writes is the disk-trend snapshot under LOG_ROOT
(probe_disk); everything else is read-only via localhost APIs and `sudo -n`.

Interface contract: scripts/plex-ops/CONTRACT.md (sections 3 and 7.2).
"""

import os
import re
from datetime import datetime

import plexops_lib as lib

# ---------------------------------------------------------------------------
# Queue classification (CONTRACT.md 3.1). The single implementation lives in
# plexops_lib (shared with actions.py so queue-remove's `expect` check can
# never drift); re-exported here as the contract-facing names.

CLASSES = lib.CLASSES
classify_queue_item = lib.classify_queue_item

# arr container path -> host path (compose: /data -> MEDIA, /data2 -> MEDIA2)
host_path = lib.arr_host_path


# ---------------------------------------------------------------------------
# Probe: queue-health

_fetch_queue = lib.fetch_queue
_queue_item = lib.queue_item_view


def probe_queue_health(params):
    """Both arrs' queues, every item classified. One arr down -> that app is
    {"error": ...} and the probe still succeeds; both down -> 502."""
    apps = {}
    errors = []
    for app in ("sonarr", "radarr"):
        try:
            raw = _fetch_queue(app)
        except lib.PlexOpsError as e:
            apps[app] = {"error": e.message}
            errors.append(e.message)
            continue
        items = [_queue_item(r, app) for r in raw]
        counts = {c: 0 for c in CLASSES}
        for it in items:
            counts[it["classification"]] += 1
        apps[app] = {"total": len(items), "counts": counts, "items": items}
    if len(errors) == 2:
        raise lib.PlexOpsError(
            "upstream-error", "both arrs unreachable: %s" % "; ".join(errors), 502
        )
    return {"probe": "queue-health", "ts": lib.now_iso(), "apps": apps}


# ---------------------------------------------------------------------------
# Probe: service-health

SERVICE_CONTAINERS = ("gluetun", "byparr", "sonarr", "radarr", "prowlarr", "qbittorrent")


def probe_service_health(params):
    ping = lib.prowlarr_ping()

    cpu_percent = None
    try:
        stats = lib.docker_stats(["prowlarr"])
        if stats:
            cpu_percent = stats[0].get("cpu_percent")
    except Exception:
        pass

    try:
        rows = {r["name"]: r for r in lib.docker_ps_all()}
    except RuntimeError as e:
        raise lib.PlexOpsError("upstream-error", "docker ps failed: %s" % e, 502)

    containers = {}
    for name in SERVICE_CONTAINERS:
        row = rows.get(name)
        if row is None:
            containers[name] = {"state": "missing", "health": None, "status": None}
            continue
        st = lib.container_state(name) or {}
        containers[name] = {
            "state": row.get("state") or st.get("state"),
            "health": st.get("health"),
            "status": row.get("status"),
        }

    stragglers = lib.exited_255()

    egress_ip = lib.gluetun_egress_ip()
    return {
        "probe": "service-health",
        "ts": lib.now_iso(),
        "prowlarr": {"ping_ok": ping["ok"], "ping_ms": ping["ms"], "cpu_percent": cpu_percent},
        "containers": containers,
        "stragglers": stragglers,
        "vpn": {"egress_ok": bool(egress_ip), "egress_ip": egress_ip},
    }


# ---------------------------------------------------------------------------
# Probe: disk


def probe_disk(params):
    """df both mounts + trend vs the previous snapshot (persisted at
    DISK_STATE, the only state a probe writes). trend is null on first run."""
    ts = lib.now_iso()
    mounts = lib.df_mounts()

    prev = lib.load_json(lib.DISK_STATE)
    trend = None
    if isinstance(prev, dict) and prev.get("ts") and isinstance(prev.get("mounts"), dict):
        hours = None
        try:
            dt = datetime.fromisoformat(ts) - datetime.fromisoformat(prev["ts"])
            hours = round(dt.total_seconds() / 3600.0, 2)
        except ValueError:
            pass
        delta = {}
        for mount, cur in mounts.items():
            old = prev["mounts"].get(mount)
            if isinstance(old, dict) and "used_bytes" in old:
                delta[mount] = cur["used_bytes"] - old["used_bytes"]
        trend = {"since": prev["ts"], "hours": hours, "delta_used_bytes": delta}

    snapshot = {"ts": ts, "mounts": mounts}
    try:
        lib.save_json(lib.DISK_STATE, snapshot)
    except (FileNotFoundError, PermissionError):
        try:
            lib.ensure_log_dir()
            lib.save_json(lib.DISK_STATE, snapshot)
        except Exception as e:
            lib.log("disk-state persist failed: %s" % e)

    return {"probe": "disk", "ts": ts, "mounts": mounts, "trend": trend}


# ---------------------------------------------------------------------------
# Probe: library-audit

FINDING_TYPES = ("missing-file", "sparse-file", "orphan-file", "malformed-dir",
                 "duplicate-versions")
DEFAULT_CHUNKS = 7

SEASON_DIR_RE = re.compile(r"(?i)^(season[ ._-]?\d+|specials)$")
# Plex-conventional extras dirs allowed inside a movie dir (lowercase).
MOVIE_EXTRA_DIRS = {
    "behind the scenes", "deleted scenes", "featurettes", "interviews",
    "scenes", "shorts", "trailers", "other", "extras", "subs", "subtitles",
}
EPISODE_RE = re.compile(r"(?i)\bs(\d{1,2})e(\d{1,3})\b|(?<!\d)(\d{1,2})x(\d{2,3})(?!\d)")


def _param_int(params, key, default=None):
    val = params.get(key)
    if val is None:
        if default is not None:
            return default
        raise lib.PlexOpsError("bad-request", "missing required param: %s" % key, 400)
    try:
        return int(val)
    except (TypeError, ValueError):
        raise lib.PlexOpsError(
            "bad-request", "%s must be an integer, got %r" % (key, val), 400
        )


def _list_subdirs(path):
    """Immediate subdirectories of path (host view, via sudo find)."""
    try:
        out = lib.sudo(
            ["find", path, "-mindepth", "1", "-maxdepth", "1", "-type", "d"],
            check=False,
        )
    except Exception:
        return []
    return [ln for ln in out.splitlines() if ln.strip()]


def _episode_key(filename):
    """(season, episode) parsed from a filename, or None."""
    m = EPISODE_RE.search(filename)
    if not m:
        return None
    if m.group(1) is not None:
        return int(m.group(1)), int(m.group(2))
    return int(m.group(3)), int(m.group(4))


def _wanted_total(app, kind):
    """Cheap arr-side count via /wanted/<kind> totalRecords."""
    data = lib.arr_get(app, "/api/v3/wanted/" + kind, params={
        "page": 1, "pageSize": 1, "monitored": "true",
    })
    if isinstance(data, dict):
        return data.get("totalRecords", 0)
    return 0


def _tracked_paths(app, title):
    """Host paths of the files the arr tracks for this title."""
    if app == "sonarr":
        eps = lib.arr_get("sonarr", "/api/v3/episodefile",
                          params={"seriesId": title.get("id")}) or []
        return [host_path(e["path"]) for e in eps if e.get("path")]
    mf = title.get("movieFile") or {}
    if mf.get("path"):
        return [host_path(mf["path"])]
    return []


def _audit_title(app, title):
    """Report-only findings for one series/movie. Deletes nothing."""
    findings = []
    tid = title.get("id")
    tname = title.get("title")
    tdir = host_path(title.get("path"))

    def finding(ftype, path, detail, **extra):
        f = {"type": ftype, "title": tname, "title_id": tid,
             "path": path, "detail": detail}
        f.update(extra)
        findings.append(f)

    # Tracked files: exist on disk, and not hollow/sparse shells.
    tracked = _tracked_paths(app, title)
    for path in tracked:
        st = lib.stat_file(path)
        if st is None:
            finding("missing-file", path, "tracked file missing on disk")
        elif st["sparse"]:
            allocated = st["blocks512"] * 512
            finding(
                "sparse-file", path,
                "allocated %d of %d apparent bytes" % (allocated, st["size_bytes"]),
                apparent_bytes=st["size_bytes"], allocated_bytes=allocated,
            )

    if not tdir:
        return findings

    # Disk scan of the title's library dir: orphans + duplicate versions.
    tracked_set = set(tracked)
    disk_videos = []
    for _size, _nlink, d, f, _blocks in lib.find_files_blocks([tdir]):
        path = os.path.join(d, f)
        if not lib.is_video(f):
            continue
        disk_videos.append(path)
        if path not in tracked_set:
            finding("orphan-file", path, "video file not tracked by %s" % app)

    # Malformed dirs: unexpected immediate subdirectories.
    for sub in _list_subdirs(tdir):
        base = os.path.basename(sub)
        if app == "sonarr":
            ok = bool(SEASON_DIR_RE.match(base))
        else:
            ok = base.lower() in MOVIE_EXTRA_DIRS
        if not ok:
            finding("malformed-dir", sub, "unexpected directory %r in title dir" % base)

    # Duplicate versions.
    if app == "radarr":
        if len(disk_videos) > 1:
            finding(
                "duplicate-versions", tdir,
                "%d video files in movie dir: %s"
                % (len(disk_videos), ", ".join(sorted(os.path.basename(p) for p in disk_videos))),
            )
    else:
        groups = {}
        for path in disk_videos:
            key = _episode_key(os.path.basename(path))
            if key:
                groups.setdefault(key, []).append(path)
        for (season, episode), paths in sorted(groups.items()):
            if len(paths) > 1:
                finding(
                    "duplicate-versions", sorted(paths)[0],
                    "S%02dE%02d has %d files: %s"
                    % (season, episode, len(paths),
                       ", ".join(sorted(os.path.basename(p) for p in paths))),
                )
    return findings


def probe_library_audit(params):
    app = params.get("app")
    if app not in ("sonarr", "radarr"):
        raise lib.PlexOpsError(
            "bad-request", "app must be one of: sonarr, radarr", 400,
            detail={"app": app},
        )
    chunk = _param_int(params, "chunk")
    chunks = _param_int(params, "chunks", default=DEFAULT_CHUNKS)
    if chunks < 1:
        raise lib.PlexOpsError("bad-request", "chunks must be >= 1", 400)
    if chunk < 0 or chunk >= chunks:
        raise lib.PlexOpsError(
            "bad-request", "chunk must be in [0, %d)" % chunks, 400,
            detail={"chunk": chunk, "chunks": chunks},
        )

    endpoint = "/api/v3/series" if app == "sonarr" else "/api/v3/movie"
    titles = lib.arr_get(app, endpoint) or []
    titles = sorted(titles, key=lambda t: t.get("id", 0))
    mine = [t for i, t in enumerate(titles) if i % chunks == chunk]

    findings = []
    for title in mine:
        findings.extend(_audit_title(app, title))

    counts = {k: 0 for k in FINDING_TYPES}
    for f in findings:
        counts[f["type"]] += 1
    counts["missing-monitored"] = _wanted_total(app, "missing")
    counts["cutoff-unmet"] = _wanted_total(app, "cutoff")

    return {
        "probe": "library-audit",
        "ts": lib.now_iso(),
        "app": app,
        "chunk": chunk,
        "chunks": chunks,
        "titles_checked": len(mine),
        "counts": counts,
        "findings": findings,
    }


# ---------------------------------------------------------------------------

PROBES = {
    "queue-health": probe_queue_health,
    "service-health": probe_service_health,
    "disk": probe_disk,
    "library-audit": probe_library_audit,
}
