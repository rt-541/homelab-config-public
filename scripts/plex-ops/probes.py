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
# Probe: lookup (CONTRACT.md 3.5) - resolve a casual title to arr ids and
# file state, for the help desk. Read-only; the caller (agent) picks the
# match and then addresses replace-file / fill-missing / search by id.

_WORD_RE = re.compile(r"[a-z0-9]+")
LOOKUP_MIN_SCORE = 40
LOOKUP_MAX_MATCHES = 5


def _norm_words(text):
    return _WORD_RE.findall((text or "").lower())


def _title_score(query, title, alternates=()):
    """0-100 similarity of `query` to a title or any alternate title:
    exact 100, prefix 90, substring 80, else 70 x (query words matched)."""
    q_words = _norm_words(query)
    q = " ".join(q_words)
    if not q:
        return 0
    best = 0
    for cand in [title] + list(alternates):
        c_words = _norm_words(cand)
        c = " ".join(c_words)
        if not c:
            continue
        # A candidate may only match as prefix/substring OF the query when it
        # is a substantial part of it: short foreign aliases ("I", "In") on
        # unrelated titles otherwise score 90 against everything.
        substantial = len(c) >= 3 and len(c) >= 0.6 * len(q)
        if c == q:
            score = 100
        elif c.startswith(q) or (substantial and q.startswith(c)):
            score = 90
        elif q in c or (substantial and c in q):
            score = 80
        else:
            common = set(q_words) & set(c_words)
            score = int(70 * len(common) / len(set(q_words))) if common else 0
        best = max(best, score)
    return best


def _alternate_titles(rec):
    return [a.get("title") for a in rec.get("alternateTitles") or []
            if isinstance(a, dict) and a.get("title")]


def _quality_name(f):
    return (((f or {}).get("quality") or {}).get("quality") or {}).get("name")


def _file_view(f):
    if not f or f.get("id") is None:
        return None
    return {"id": f.get("id"), "path": host_path(f.get("path")),
            "size": f.get("size"), "quality": _quality_name(f)}


def _match_view(app, score, rec):
    view = {"id": rec.get("id"), "title": rec.get("title"), "year": rec.get("year"),
            "monitored": rec.get("monitored"), "path": host_path(rec.get("path")),
            "score": score}
    if app == "radarr":
        view["has_file"] = bool(rec.get("hasFile"))
        view["file"] = _file_view(rec.get("movieFile"))
    else:
        stats = rec.get("statistics") or {}
        view["status"] = rec.get("status")
        view["episode_file_count"] = stats.get("episodeFileCount")
        view["episode_count"] = stats.get("episodeCount")
        view["seasons"] = [
            {"season": s.get("seasonNumber"), "monitored": s.get("monitored"),
             "episode_file_count": (s.get("statistics") or {}).get("episodeFileCount"),
             "total_episode_count": (s.get("statistics") or {}).get("totalEpisodeCount")}
            for s in rec.get("seasons") or []
        ]
    return view


def _episode_view(e):
    return {"id": e.get("id"), "season": e.get("seasonNumber"),
            "episode": e.get("episodeNumber"), "title": e.get("title"),
            "air_date": e.get("airDate"), "monitored": e.get("monitored"),
            "has_file": bool(e.get("hasFile")), "file": _file_view(e.get("episodeFile"))}


def probe_lookup(params):
    """Title resolution. `app` and `q` required; sonarr also takes `season`
    (and `episode`, which requires `season`). When the query resolves to
    one clear series and `season` is given, the season's episodes (with
    file state) are returned so the agent can address an episode by id."""
    app = params.get("app")
    if app not in lib.PASSTHROUGH_APPS:
        raise lib.PlexOpsError(
            "bad-request", "app must be one of %s" % (list(lib.PASSTHROUGH_APPS),), 400)
    q = (params.get("q") or "").strip()
    if not q:
        raise lib.PlexOpsError("bad-request", "missing required param: q", 400)
    season = _param_int(params, "season") if params.get("season") is not None else None
    episode = _param_int(params, "episode") if params.get("episode") is not None else None
    if episode is not None and season is None:
        raise lib.PlexOpsError("bad-request", "episode requires season", 400)
    if app == "radarr" and season is not None:
        raise lib.PlexOpsError("bad-request", "season/episode apply to sonarr only", 400)

    kind = "series" if app == "sonarr" else "movie"
    records = lib.arr_get(app, "/api/v3/%s" % kind) or []
    scored = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        score = _title_score(q, rec.get("title"), _alternate_titles(rec))
        if score >= LOOKUP_MIN_SCORE:
            scored.append((score, rec))
    scored.sort(key=lambda t: (-t[0], -(t[1].get("year") or 0)))
    top = scored[:LOOKUP_MAX_MATCHES]

    out = {"probe": "lookup", "ts": lib.now_iso(), "app": app, "query": q,
           "season": season, "episode": episode,
           "matches": [_match_view(app, s, r) for s, r in top],
           "resolved_id": None, "episodes": None}
    # One clear winner: a single candidate, or a top score >= 90 that beats
    # the runner-up. Only then is season detail fetched.
    if top and (len(top) == 1 or (top[0][0] >= 90 and top[0][0] > top[1][0])):
        out["resolved_id"] = top[0][1].get("id")
    if app == "sonarr" and season is not None and out["resolved_id"] is not None:
        eps = lib.arr_get("sonarr", "/api/v3/episode",
                          {"seriesId": out["resolved_id"], "seasonNumber": season,
                           "includeEpisodeFile": "true"}) or []
        if episode is not None:
            eps = [e for e in eps if e.get("episodeNumber") == episode]
        out["episodes"] = [_episode_view(e) for e in
                           sorted(eps, key=lambda e: e.get("episodeNumber") or 0)]
    return out


# ---------------------------------------------------------------------------
# Probes: reclaim-status / reclaim-plan (CONTRACT.md 3.6 / 3.7) - the
# compression waves. Read-only; reclaim-plan may run the read-only candidate
# scan (refresh=true or no report yet), which writes a stamped report dir.


def _bool_param(params, key, default=False):
    v = params.get(key)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _candidate_rows(report_tsv):
    """Transcode candidates from a scan report, ranked by est. savings (report
    order), excluding SKIP rows, keep-list titles, done and failed jobs."""
    done, failed = lib.reclaim_done_set(), lib.reclaim_failed_map()
    queued = {r["rel_path"] for r in lib.reclaim_queue_rows()}
    out = []
    for r in lib.read_tsv_dicts(report_tsv):
        if r.get("action") != "transcode" or (r.get("SKIP") or "").strip():
            continue
        if lib.reclaim_keep_match(r.get("title")):
            continue
        rel = lib.reclaim_rel_path(r.get("primary_path") or "")
        if rel in done or rel in failed:
            continue
        try:
            size_gb = float(r.get("size_gb") or 0)
            gain_gb = float(r.get("est_savings_gb") or 0)
        except ValueError:
            continue
        out.append({"title": r.get("title"), "mount": r.get("mount"), "size_gb": size_gb,
                    "est_target_gb": r.get("est_target_gb"), "est_gain_gb": gain_gb,
                    "band": lib.size_band(size_gb), "rel_path": rel,
                    "queued": rel in queued, "flags": r.get("flags")})
    return out


def _plan_minutes(size_gb):
    return int(round(size_gb / lib.reclaim_gb_per_hour() * 60))


def reclaim_plan(window="tonight", hours=None, limit=None, refresh=False, now=None):
    """Shared by the probe and the schedule action: pick the titles that fit
    the window budget, largest expected gain first."""
    rep = lib.latest_reclaim_report()
    if refresh or rep is None:
        rep = lib.run_reclaim_scan()
    report_dir, tsv, age = rep
    occ, budget = lib.reclaim_pick_window(window, now=now)
    if hours is not None:
        budget = float(hours)
    if occ is None and hours is None:
        raise lib.PlexOpsError("bad-request", "no %s window is configured" % window, 400)
    cands = _candidate_rows(tsv)
    selected, used = [], 0.0
    for c in cands:
        if limit is not None and len(selected) >= limit:
            break
        mins = _plan_minutes(c["size_gb"])
        if used + mins > budget * 60 + 1e-9:
            continue
        used += mins
        selected.append(dict(c, est_minutes=mins))
    counts = {"large": 0, "medium": 0, "small": 0}
    for s in selected:
        counts[s["band"]] += 1
    counts["total"] = len(selected)
    flags = lib.reclaim_flags()
    done_n = len(lib.reclaim_done_set())
    pilot_limit = int(lib.reclaim_policy().get("PILOT_LIMIT") or lib.RECLAIM_PILOT_LIMIT_DEFAULT)
    notes = []
    if flags["paused"]:
        notes.append("worker is PAUSED; nothing runs until reclaim-resume")
    if not flags["pilot_ack"] and done_n < pilot_limit:
        notes.append("pilot gate: the worker stops after %d encodes until reclaim-pilot-ack"
                     % pilot_limit)
    return {
        "probe": "reclaim-plan", "ts": lib.now_iso(),
        "window": {"kind": window, "label": occ["label"] if occ else None,
                   "start": occ["start"].isoformat(timespec="minutes") if occ else None,
                   "end": occ["end"].isoformat(timespec="minutes") if occ else None,
                   "budget_hours": round(budget, 2)},
        "gb_per_hour": lib.reclaim_gb_per_hour(),
        "counts": counts,
        "est_gain_gb": round(sum(s["est_gain_gb"] for s in selected), 1),
        "est_hours": round(used / 60.0, 2),
        "selected": selected,
        "remaining_candidates": len(cands),
        "remaining_est_gain_gb": round(sum(c["est_gain_gb"] for c in cands), 1),
        "already_queued": sum(1 for c in cands if c["queued"]),
        "report": {"dir": report_dir, "age_minutes": int(age // 60)},
        "flags": flags, "notes": notes,
    }


def probe_reclaim_plan(params):
    window = (params.get("window") or "tonight").strip().lower()
    if window not in ("tonight", "workday", "next"):
        raise lib.PlexOpsError("bad-request", "window must be tonight, workday, or next", 400)
    hours = None
    if params.get("hours") is not None:
        try:
            hours = float(params["hours"])
        except ValueError:
            raise lib.PlexOpsError("bad-request", "hours must be a number", 400)
        if hours <= 0:
            raise lib.PlexOpsError("bad-request", "hours must be positive", 400)
    limit = _param_int(params, "limit") if params.get("limit") is not None else None
    return reclaim_plan(window, hours, limit, _bool_param(params, "refresh"))


def probe_reclaim_status(params):
    queue = lib.reclaim_queue_rows()
    done, failed = lib.reclaim_done_set(), lib.reclaim_failed_map()
    remaining = [q for q in queue if q["rel_path"] not in done and q["rel_path"] not in failed]
    rep = lib.latest_reclaim_report()
    cands = _candidate_rows(rep[1]) if rep else []
    status_md = lib.read_text(lib.RECLAIM_STATUS_MD) or ""
    df_lines = lib.read_lines(lib.RECLAIM_DF_LOG)
    pol = lib.reclaim_policy()
    return {
        "probe": "reclaim-status", "ts": lib.now_iso(),
        "queue": {"total": len(queue), "remaining": len(remaining), "done": len(done),
                  "failed": len(failed),
                  "next": remaining[0]["title"] if remaining else None,
                  "remaining_source_gb": round(sum(int(q["size_bytes"]) for q in remaining) / 1024 ** 3, 1)},
        "saved_gb": round(lib.reclaim_saved_bytes() / 1024 ** 3, 1),
        "failed_recent": [{"rel_path": k, "reason": v} for k, v in list(failed.items())[-5:]],
        "flags": lib.reclaim_flags(),
        "pilot_limit": int(pol.get("PILOT_LIMIT") or lib.RECLAIM_PILOT_LIMIT_DEFAULT),
        "window": lib.reclaim_window_state(),
        "worker_status": status_md.strip()[-600:] or None,
        "last_df_checkpoint": df_lines[-1] if df_lines else None,
        "candidates": {"remaining": len(cands),
                       "est_gain_gb": round(sum(c["est_gain_gb"] for c in cands), 1),
                       "report_age_minutes": int(rep[2] // 60) if rep else None},
    }


# ---------------------------------------------------------------------------
# Probe: title-stats (CONTRACT.md 3.8) - everything known about one show or
# movie: size on disk (arr), who watched it (Plex history: distinct watchers,
# not episode plays), who requested it (Seerr). Read-only.


def probe_title_stats(params):
    app = params.get("app")
    if app not in lib.PASSTHROUGH_APPS:
        raise lib.PlexOpsError(
            "bad-request", "app must be one of %s" % (list(lib.PASSTHROUGH_APPS),), 400)
    kind = "series" if app == "sonarr" else "movie"
    section_type = "show" if app == "sonarr" else "movie"
    notes = []
    rid = _param_int(params, "id") if params.get("id") is not None else None
    if rid is None:
        q = (params.get("q") or "").strip()
        if not q:
            raise lib.PlexOpsError("bad-request", "q or id is required", 400)
        res = probe_lookup({"app": app, "q": q})
        rid = res.get("resolved_id")
        if rid is None:
            return {"probe": "title-stats", "ts": lib.now_iso(), "app": app, "query": q,
                    "resolved": False, "matches": res["matches"], "notes": ["ambiguous or no match"]}
    rec = lib.arr_get(app, "/api/v3/%s/%d" % (kind, rid))
    if not isinstance(rec, dict) or rec.get("id") is None:
        raise lib.PlexOpsError("verify-failed", "%s %d not found in %s" % (kind, rid, app), 409)
    ids = {"tvdb": rec.get("tvdbId"), "tmdb": rec.get("tmdbId"), "imdb": rec.get("imdbId")}
    if app == "sonarr":
        st = rec.get("statistics") or {}
        size = {"on_disk_gb": round((st.get("sizeOnDisk") or 0) / 1024 ** 3, 1),
                "files": st.get("episodeFileCount"), "episodes_aired": st.get("episodeCount"),
                "episodes_total": st.get("totalEpisodeCount"), "seasons": st.get("seasonCount"),
                "percent_on_disk": st.get("percentOfEpisodes")}
    else:
        f = rec.get("movieFile") or {}
        size = {"on_disk_gb": round((rec.get("sizeOnDisk") or 0) / 1024 ** 3, 1),
                "files": 1 if rec.get("hasFile") else 0,
                "quality": ((f.get("quality") or {}).get("quality") or {}).get("name"),
                "path": host_path(f.get("path")) if f else None}
    out = {"probe": "title-stats", "ts": lib.now_iso(), "app": app, "resolved": True,
           "id": rid, "title": rec.get("title"), "year": rec.get("year"),
           "monitored": rec.get("monitored"), "added": (rec.get("added") or "")[:10],
           "ids": ids, "size": size, "plex": None, "requests": None, "notes": notes}
    try:
        item = lib.plex_find_item(section_type, rec.get("title"), rec.get("year"), ids)
        if item is None:
            notes.append("not found in the Plex library (no watch data)")
        else:
            ws = lib.plex_watch_stats(section_type, item["rating_key"])
            out["plex"] = dict(ws or {}, rating_key=item["rating_key"],
                               added_at=lib._ts(item.get("added_at")))
            notes.append("Plex history only covers this server's database; watches before a "
                         "rebuild are not counted")
    except lib.PlexOpsError as e:
        notes.append("plex unavailable: %s" % e.message)
    try:
        reqs = lib.seerr_requests_for(section_type, ids.get("tmdb"))
        out["requests"] = reqs
        if reqs is None:
            notes.append("no request record in Seerr (never requested there, or lost to a rebuild)")
        elif not reqs:
            notes.append("Seerr knows the title but holds no request for it")
    except lib.PlexOpsError as e:
        notes.append("seerr unavailable: %s" % e.message)
    return out


# ---------------------------------------------------------------------------

PROBES = {
    "title-stats": probe_title_stats,
    "queue-health": probe_queue_health,
    "service-health": probe_service_health,
    "disk": probe_disk,
    "library-audit": probe_library_audit,
    "lookup": probe_lookup,
    "reclaim-status": probe_reclaim_status,
    "reclaim-plan": probe_reclaim_plan,
}
