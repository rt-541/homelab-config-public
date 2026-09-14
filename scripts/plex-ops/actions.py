"""Whitelisted actions for the plex-ops action-runner (nemesis side).

Python 3.9 stdlib only. Imports only plexops_lib (+ stdlib) per the module
boundaries in scripts/plex-ops/CONTRACT.md (section 7). Response shapes and
per-action semantics: CONTRACT.md section 5.

Every action:
- accepts "dry_run" (default false). With dry_run true the returned
  "planned" lists exactly what would run, "performed" is [], "after" and
  "verified" are null, and NOTHING is executed - pre-verification still
  runs (read-only) so a dry run refuses the same requests a real run would;
- re-verifies its live target before acting and raises PlexOpsError
  409 "verify-failed" when the world no longer matches the request;
- re-verifies after acting and reports the post state (a post-check
  failure is also a 409, with "performed" showing what ran);
- restarts services as compose down then up -d, never `compose restart`
  (house rule; lib.compose runs `sudo -n docker compose` in the stack dir).
"""

import os
import time

import plexops_lib as lib
from plexops_lib import PlexOpsError

# ---------------------------------------------------------------------------
# Tunables (timeouts from CONTRACT.md section 5)

PROWLARR_PING_TIMEOUT_S = 120
HEALTH_TIMEOUT_S = 180
POLL_INTERVAL_S = 3.0

# pull-recreate: the ONLY services this action may recreate, mapped to the
# set that goes down/up together (qbittorrent rides gluetun's network
# namespace; byparr stands alone). "services" are compose SERVICE names
# (the live plex-stack service is `qbit`) for compose down/up; "containers"
# are container_names for docker inspect and before/after blocks.
PULL_SERVICES = {
    "gluetun": {"services": ("gluetun", "qbit"),
                "containers": ("gluetun", "qbittorrent")},
    "byparr": {"services": ("byparr",), "containers": ("byparr",)},
}

# Indirection so tests can drive the wait loop with a fake clock.
_sleep = time.sleep
_monotonic = time.monotonic


# ---------------------------------------------------------------------------
# Shared helpers


def _bad(message, detail=None):
    raise PlexOpsError("bad-request", message, 400, detail)


def _verify_failed(message, detail=None):
    raise PlexOpsError("verify-failed", message, 409, detail)


def _require_body(body):
    if not isinstance(body, dict):
        _bad("request body must be a JSON object")
    return body


def _get_bool(body, key, default=False):
    val = body.get(key, default)
    if not isinstance(val, bool):
        _bad("%s must be a boolean" % key)
    return val


def _get_id(body, key):
    val = body.get(key)
    if not isinstance(val, int) or isinstance(val, bool):
        _bad("%s must be an integer" % key)
    return val


def _result(action, dry_run, before, planned, performed, after, verified):
    """The CONTRACT.md section-5 success payload (runner adds "ok": true)."""
    return {
        "action": action,
        "dry_run": dry_run,
        "ts": lib.now_iso(),
        "before": before,
        "planned": planned,
        "performed": performed,
        "after": after,
        "verified": verified,
    }


def _dry_result(action, before, planned):
    return _result(action, True, before, planned, [], None, None)


def _wait_until(fn, timeout_s, interval_s=POLL_INTERVAL_S):
    """Poll fn() until truthy or timeout. Returns bool."""
    deadline = _monotonic() + timeout_s
    while True:
        if fn():
            return True
        if _monotonic() >= deadline:
            return False
        _sleep(interval_s)


def _cstate(name):
    """Container state summary for before/after blocks."""
    st = lib.container_state(name)
    if st is None:
        return {"state": "missing", "health": None, "image_id": None}
    return {"state": st["state"], "health": st["health"], "image_id": st["image_id"]}


def _uniq(seq):
    out = []
    for s in seq:
        if s and s not in out:
            out.append(s)
    return out


# ---------------------------------------------------------------------------
# Queue item classification and shaping (CONTRACT.md section 3.1). The single
# implementation lives in plexops_lib and is shared with probes.py, so
# queue-remove's `expect` pre-verification always agrees with the
# queue-health probe.

_queue_item_view = lib.queue_item_view
_fetch_queue = lib.fetch_queue
_host_path = lib.arr_host_path


def _require_arr(body):
    app = body.get("app")
    if app not in lib.PASSTHROUGH_APPS:
        _bad("app must be one of %s" % (list(lib.PASSTHROUGH_APPS),))
    return app


def _arr_resource(app, path):
    """GET one arr resource -> parsed JSON, or None on 404. Other upstream
    HTTP errors are a 502; connection failure raises from http_json."""
    status, parsed = lib.http_json(
        lib.ARR[app]["url"] + path,
        headers={"X-Api-Key": lib.arr_key(app)},
        timeout=30,
    )
    if status == 200:
        return parsed if parsed is not None else {}
    if status == 404:
        return None
    raise PlexOpsError(
        "upstream-error", "%s GET %s -> HTTP %d" % (app, path, status), 502
    )


# ---------------------------------------------------------------------------
# 5.1 restart-prowlarr


def action_restart_prowlarr(body):
    body = _require_body(body)
    dry_run = _get_bool(body, "dry_run")

    if lib.container_state("prowlarr") is None:
        _verify_failed("prowlarr container not found")
    ping = lib.prowlarr_ping()
    before = {"ping_ok": ping["ok"], "ping_ms": ping["ms"]}

    planned = [
        "sudo docker compose down prowlarr [%s]" % lib.PLEX_STACK,
        "sudo docker compose up -d prowlarr [%s]" % lib.PLEX_STACK,
        "poll prowlarr /ping until ok (timeout %ds)" % PROWLARR_PING_TIMEOUT_S,
        "POST sonarr /api/v3/indexer/testall",
        "POST radarr /api/v3/indexer/testall",
    ]
    if dry_run:
        return _dry_result("restart-prowlarr", before, planned)

    performed = []
    lib.compose(lib.PLEX_STACK, ["down", "prowlarr"])
    performed.append(planned[0])
    lib.compose(lib.PLEX_STACK, ["up", "-d", "prowlarr"])
    performed.append(planned[1])

    if not _wait_until(lambda: lib.prowlarr_ping(timeout=5)["ok"],
                       PROWLARR_PING_TIMEOUT_S):
        _verify_failed(
            "prowlarr /ping not ok within %ds of restart" % PROWLARR_PING_TIMEOUT_S,
            detail={"performed": performed,
                    "testall": {"sonarr": "skipped", "radarr": "skipped"}},
        )
    performed.append(planned[2])

    testall = {}
    for i, app in enumerate(("sonarr", "radarr")):
        try:
            lib.arr_call(app, "POST", "/api/v3/indexer/testall")
            testall[app] = "ok"
        except PlexOpsError:
            testall[app] = "failed"
        performed.append(planned[3 + i])

    ping = lib.prowlarr_ping()
    after = {"ping_ok": ping["ok"], "ping_ms": ping["ms"], "testall": testall}
    if not ping["ok"]:
        _verify_failed("prowlarr /ping regressed after restart",
                       detail={"performed": performed, "after": after})
    return _result("restart-prowlarr", False, before, planned, performed, after, True)


# ---------------------------------------------------------------------------
# 5.2 pull-recreate


def _service_ready(name):
    st = lib.container_state(name)
    if st is None:
        return False
    if st["health"] is not None:
        return st["health"] == "healthy"
    return st["state"] == "running"


def action_pull_recreate(body):
    body = _require_body(body)
    dry_run = _get_bool(body, "dry_run")
    service = body.get("service")
    if service not in PULL_SERVICES:
        _bad("service must be one of %s" % (sorted(PULL_SERVICES),),
             detail={"service": service})
    services = PULL_SERVICES[service]["services"]      # compose service names
    containers = PULL_SERVICES[service]["containers"]  # container_names (inspect)

    if lib.container_state(service) is None:
        _verify_failed("%s container not found" % service)
    before = {name: _cstate(name) for name in containers}

    joined = " ".join(services)
    planned = [
        "sudo docker compose pull %s [%s]" % (service, lib.PLEX_STACK),
        "sudo docker compose down %s [%s]" % (joined, lib.PLEX_STACK),
        "sudo docker compose up -d %s [%s]" % (joined, lib.PLEX_STACK),
        "wait for %s health ok (timeout %ds)" % (service, HEALTH_TIMEOUT_S),
    ]
    if dry_run:
        return _dry_result("pull-recreate", before, planned)

    performed = []
    lib.compose(lib.PLEX_STACK, ["pull", service])
    performed.append(planned[0])
    lib.compose(lib.PLEX_STACK, ["down"] + list(services))
    performed.append(planned[1])
    lib.compose(lib.PLEX_STACK, ["up", "-d"] + list(services))
    performed.append(planned[2])

    after = None
    if not _wait_until(lambda: _service_ready(service), HEALTH_TIMEOUT_S):
        after = {name: _cstate(name) for name in containers}
        _verify_failed(
            "%s not healthy within %ds of recreate" % (service, HEALTH_TIMEOUT_S),
            detail={"performed": performed, "after": after},
        )
    performed.append(planned[3])
    after = {name: _cstate(name) for name in containers}
    return _result("pull-recreate", False, before, planned, performed, after, True)


# ---------------------------------------------------------------------------
# 5.3 resurrect-stragglers


def action_resurrect_stragglers(body):
    body = _require_body(body)
    dry_run = _get_bool(body, "dry_run")
    stacks = body.get("stacks")
    if stacks is None:
        stacks = sorted(lib.STACKS)
    else:
        if (not isinstance(stacks, list) or not stacks
                or not all(isinstance(s, str) for s in stacks)):
            _bad("stacks must be a non-empty list of stack names")
        unknown = [s for s in stacks if s not in lib.STACKS]
        if unknown:
            _bad("unknown stack: %s" % ", ".join(unknown),
                 detail={"known": sorted(lib.STACKS)})

    stragglers = lib.exited_255(stacks)
    before = {"stragglers": stragglers}
    affected = _uniq([s["stack"] for s in stragglers])
    # --no-recreate: start the exited containers WITHOUT recreating running
    # services whose config has diverged from the compose file on disk -
    # a bare `up -d` would restart healthy production containers that were
    # never the verified target.
    planned = ["sudo docker compose up -d --no-recreate [%s]" % s for s in affected]

    if dry_run:
        return _dry_result("resurrect-stragglers", before, planned)
    if not stragglers:
        # Goal already satisfied: successful no-op.
        return _result("resurrect-stragglers", False, before, [], [],
                       {"stragglers": []}, True)

    performed = []
    for i, stack in enumerate(affected):
        lib.compose(stack, ["up", "-d", "--no-recreate"])
        performed.append(planned[i])

    not_running = [
        c for c in stragglers
        if (lib.container_state(c["name"]) or {}).get("state") != "running"
    ]
    after = {"stragglers": lib.exited_255(stacks)}
    if not_running:
        _verify_failed(
            "%d straggler(s) still not running after compose up" % len(not_running),
            detail={"performed": performed, "not_running": not_running,
                    "after": after},
        )
    return _result("resurrect-stragglers", False, before, planned, performed,
                   after, True)


# ---------------------------------------------------------------------------
# 5.4 queue-remove


def action_queue_remove(body):
    body = _require_body(body)
    dry_run = _get_bool(body, "dry_run")
    app = _require_arr(body)
    qid = _get_id(body, "id")
    blocklist = _get_bool(body, "blocklist")
    remove_data = _get_bool(body, "removeData")
    expect = body.get("expect")

    # Pre-verify: the item is still in the queue and still what the caller
    # thinks it is.
    records = _fetch_queue(app)
    item = next((r for r in records if r.get("id") == qid), None)
    if item is None:
        _verify_failed("queue item %d not found in %s queue" % (qid, app),
                       detail={"app": app, "id": qid})
    view = _queue_item_view(item, app)
    if expect is not None and view["classification"] != expect:
        _verify_failed(
            "queue item %d now classifies as %s, expected %s"
            % (qid, view["classification"], expect),
            detail={"item": view},
        )
    # A COMPLETED download that stays in the client is re-tracked by the arr
    # on its next client poll under the SAME queue id (ids derive from the
    # download), so "remove from queue, keep the download" is a no-op that
    # only looks like it worked (observed 2026-09-14: 9 items removed twice,
    # back within a minute). Refuse it; the caller must delete the download.
    if not remove_data and (view.get("sizeleft") or 0) == 0:
        _verify_failed(
            "queue item %d is a completed download still in the client; removing it "
            "without removeData re-tracks it under the same id - pass removeData: true"
            % qid,
            detail={"item": view, "hint": "removeData: true (blocklist keeps it from being grabbed again)"},
        )
    if remove_data and item.get("outputPath"):
        try:
            lib.safe_download_path(_host_path(item["outputPath"]))
        except PlexOpsError as e:
            _verify_failed(
                "refusing removeData: output path fails download-root policy",
                detail={"output_path": item["outputPath"], "reason": e.message},
            )

    params = {
        "removeFromClient": "true" if remove_data else "false",
        "blocklist": "true" if blocklist else "false",
        "skipRedownload": "true",
    }
    planned = [
        "DELETE %s /api/v3/queue/%d?removeFromClient=%s&blocklist=%s&skipRedownload=true"
        % (app, qid, params["removeFromClient"], params["blocklist"])
    ]
    if dry_run:
        return _dry_result("queue-remove", view, planned)

    lib.arr_call(app, "DELETE", "/api/v3/queue/%d" % qid, params=params)
    performed = list(planned)

    still = next((r for r in _fetch_queue(app) if r.get("id") == qid), None)
    if still is not None:
        _verify_failed("queue item %d still present after delete" % qid,
                       detail={"performed": performed,
                               "item": _queue_item_view(still, app)})
    return _result("queue-remove", False, view, planned, performed,
                   {"in_queue": False}, True)


# ---------------------------------------------------------------------------
# 5.5 search


def _id_list(body, key):
    val = body.get(key)
    if val is None:
        return None
    if (not isinstance(val, list) or not val
            or not all(isinstance(i, int) and not isinstance(i, bool) for i in val)):
        _bad("%s must be a non-empty list of integers" % key)
    return val


def action_search(body):
    body = _require_body(body)
    dry_run = _get_bool(body, "dry_run")
    app = _require_arr(body)

    if app == "radarr":
        if body.get("episode_ids") is not None or body.get("series_id") is not None:
            _bad("radarr search takes movie_ids only")
        movie_ids = _id_list(body, "movie_ids")
        if movie_ids is None:
            _bad("radarr search requires movie_ids")
        episode_ids = series_id = None
    else:
        if body.get("movie_ids") is not None:
            _bad("sonarr search takes episode_ids or series_id, not movie_ids")
        episode_ids = _id_list(body, "episode_ids")
        series_id = body.get("series_id")
        if series_id is not None and (
                not isinstance(series_id, int) or isinstance(series_id, bool)):
            _bad("series_id must be an integer")
        if (episode_ids is None) == (series_id is None):
            _bad("sonarr search requires exactly one of episode_ids or series_id")
        movie_ids = None

    # Pre-verify: every referenced id exists in the arr.
    targets, missing = [], []

    def _check(path, rid):
        res = _arr_resource(app, path)
        if res is None:
            missing.append(rid)
        else:
            targets.append({"id": rid, "title": res.get("title")})

    if movie_ids is not None:
        for mid in movie_ids:
            _check("/api/v3/movie/%d" % mid, mid)
        cmd = {"name": "MoviesSearch", "movieIds": movie_ids}
        planned = ["POST radarr /api/v3/command MoviesSearch movieIds=%s" % movie_ids]
    elif episode_ids is not None:
        for eid in episode_ids:
            _check("/api/v3/episode/%d" % eid, eid)
        cmd = {"name": "EpisodeSearch", "episodeIds": episode_ids}
        planned = ["POST sonarr /api/v3/command EpisodeSearch episodeIds=%s" % episode_ids]
    else:
        _check("/api/v3/series/%d" % series_id, series_id)
        cmd = {"name": "SeriesSearch", "seriesId": series_id}
        planned = ["POST sonarr /api/v3/command SeriesSearch seriesId=%d" % series_id]

    if missing:
        _verify_failed("ids not found in %s: %s" % (app, missing),
                       detail={"missing_ids": missing})
    before = {"app": app, "targets": targets}

    if dry_run:
        return _dry_result("search", before, planned)

    resp = lib.arr_call(app, "POST", "/api/v3/command", body=cmd) or {}
    performed = list(planned)
    command_id = resp.get("id")
    after = {"command_id": command_id,
             "command_state": resp.get("status") or resp.get("state")}
    if command_id is None:
        _verify_failed("%s did not return a command id" % app,
                       detail={"performed": performed, "response": resp})
    return _result("search", False, before, planned, performed, after, True)


# ---------------------------------------------------------------------------
# 5.6 delete-download


# Re-verify + delete in ONE sudo invocation: resolve the path again at
# delete time and refuse unless it still resolves to itself (i.e. no parent
# component was swapped for a symlink between the earlier check and the rm).
# Narrows the delete-download TOCTOU window to a single process.
_RM_REVERIFY_SH = '[ "$(realpath -e -- "$1")" = "$1" ] && exec rm -rf -- "$1"'


def action_delete_download(body):
    body = _require_body(body)
    dry_run = _get_bool(body, "dry_run")
    allow_qbit_owned = _get_bool(body, "allow_qbit_owned")

    # Policy gate: normalized, strictly under DOWNLOADS, no .Trash (400).
    norm = lib.safe_download_path(body.get("path"))

    # Symlink-escape gate: the fully resolved path must satisfy the same
    # policy. realpath -e also proves existence. All later steps (stat, qbit
    # check, rm) operate on the RESOLVED path, never the raw request path.
    try:
        real = lib.sudo(["realpath", "-e", norm]).strip()
    except Exception:
        _verify_failed("path does not exist", detail={"path": norm})
    try:
        lib.safe_download_path(real)
    except PlexOpsError:
        raise PlexOpsError(
            "bad-request",
            "path resolves outside %s (symlink escape)" % lib.DOWNLOADS,
            400,
            detail={"path": norm, "realpath": real},
        )

    st = lib.stat_file(real)
    if st is None:
        _verify_failed("path vanished before action", detail={"path": real})

    qbit = lib.Qbit()
    creds_present = bool(qbit.user and qbit.password)
    hits = lib.qbit_hits_under(qbit, real)  # None = check could not run
    if creds_present and hits is None and not allow_qbit_owned:
        # Creds are configured but qbit is down: the ownership gate cannot
        # run, and silently proceeding would delete during exactly the kind
        # of outage the watchdog acts in. Refuse instead of guessing.
        raise PlexOpsError(
            "upstream-error",
            "qbit creds are configured but qbit is unreachable; refusing "
            "delete-download while the ownership check cannot run "
            "(pass allow_qbit_owned to override)",
            502,
            detail={"path": real},
        )
    qbit_owner = None
    if hits:
        t = hits[0]
        qbit_owner = {"hash": t.get("hash"), "name": t.get("name")}
        if not allow_qbit_owned:
            _verify_failed(
                "path is owned by a qbit torrent (pass allow_qbit_owned to "
                "override; removing the torrent itself is queue-remove's job)",
                detail={"path": real, "qbit_owner": qbit_owner,
                        "torrents": len(hits)},
            )

    before = {
        "path": real,
        "nlink": st["nlink"],
        "size_bytes": st["size_bytes"],
        "blocks512": st["blocks512"],
        "sparse": st["sparse"],
        "samefile_hits": lib.samefile_hits(real),
        "qbit_checked": hits is not None,
        "qbit_owner": qbit_owner,
    }
    planned = ["sudo rm -rf %s" % real]
    if dry_run:
        return _dry_result("delete-download", before, planned)

    try:
        lib.sudo(["sh", "-c", _RM_REVERIFY_SH, "plexops-rm", real])
    except RuntimeError as e:
        _verify_failed(
            "delete-time re-verification failed (path no longer resolves to "
            "itself, or rm failed)",
            detail={"path": real, "error": str(e)},
        )
    performed = list(planned)

    if lib.stat_file(real) is not None:
        _verify_failed("path still exists after rm",
                       detail={"performed": performed, "path": real})
    return _result("delete-download", False, before, planned, performed,
                   {"exists": False}, True)


# ---------------------------------------------------------------------------
# Help-desk item actions (CONTRACT.md 5.7 / 5.8). Both address exactly ONE
# episode (sonarr) or movie (radarr) by id - never a season or a series -
# and re-verify that item's file state before and after.


def _quality_name(f):
    return (((f or {}).get("quality") or {}).get("quality") or {}).get("name")


def _file_view(f):
    if not f or f.get("id") is None:
        return None
    return {"id": f.get("id"), "path": lib.arr_host_path(f.get("path")),
            "size": f.get("size"), "quality": _quality_name(f)}


def _item_target(app, body):
    """Resolve the single item an action addresses -> (kind, id, path, record).
    409 when the id no longer exists in the arr."""
    if app == "sonarr":
        if body.get("movie_id") is not None:
            _bad("sonarr takes episode_id, not movie_id")
        rid = _get_id(body, "episode_id")
        kind, path = "episode", "/api/v3/episode/%d" % rid
    else:
        if body.get("episode_id") is not None:
            _bad("radarr takes movie_id, not episode_id")
        rid = _get_id(body, "movie_id")
        kind, path = "movie", "/api/v3/movie/%d" % rid
    rec = _arr_resource(app, path)
    if rec is None:
        _verify_failed("%s %d not found in %s" % (kind, rid, app),
                       detail={"missing_ids": [rid]})
    return kind, rid, path, rec


def _current_file(app, kind, rec):
    """The item's file record, fetched separately when the arr only embeds
    the id. None when the item has no file."""
    f = rec.get("episodeFile" if kind == "episode" else "movieFile")
    if not f and rec.get("hasFile"):
        fid = rec.get("episodeFileId" if kind == "episode" else "movieFileId")
        if fid:
            f = _arr_resource(app, "/api/v3/%sfile/%d" % (kind, fid))
    return f if (f and f.get("id") is not None) else None


def _latest_grab_history(app, kind, rid):
    """(history_id, source_title) of the newest grab/import record for the
    item - the record to mark failed so the arr blocklists that release.
    (None, None) when there is no such history."""
    if kind == "episode":
        resp = lib.arr_get("sonarr", "/api/v3/history",
                           {"episodeId": rid, "pageSize": 50,
                            "sortKey": "date", "sortDirection": "descending"})
        recs = (resp or {}).get("records") or []
    else:
        recs = lib.arr_get("radarr", "/api/v3/history/movie", {"movieId": rid}) or []
    recs = sorted([r for r in recs if isinstance(r, dict) and r.get("id") is not None],
                  key=lambda r: r.get("date") or "", reverse=True)
    grabs = [r for r in recs if r.get("eventType") == "grabbed"]
    imports = [r for r in recs if r.get("eventType") == "downloadFolderImported"]
    # The file on disk came from the newest import; blocklist the grab that
    # produced THAT download (matched by downloadId), not a later grab that
    # never imported. Fall back to the import record, then any grab.
    if imports:
        did = imports[0].get("downloadId")
        for g in grabs:
            if not did or g.get("downloadId") == did:
                return g["id"], g.get("sourceTitle")
        return imports[0]["id"], imports[0].get("sourceTitle")
    if grabs:
        return grabs[0]["id"], grabs[0].get("sourceTitle")
    return None, None


def _search_command(app, kind, rid):
    if app == "radarr":
        return ({"name": "MoviesSearch", "movieIds": [rid]},
                "POST radarr /api/v3/command MoviesSearch movieIds=[%d]" % rid)
    return ({"name": "EpisodeSearch", "episodeIds": [rid]},
            "POST sonarr /api/v3/command EpisodeSearch episodeIds=[%d]" % rid)


def _run_search(app, cmd, performed, step):
    resp = lib.arr_call(app, "POST", "/api/v3/command", body=cmd) or {}
    performed.append(step)
    command_id = resp.get("id")
    if command_id is None:
        _verify_failed("%s did not return a command id" % app,
                       detail={"performed": performed, "response": resp})
    return command_id, resp.get("status") or resp.get("state")


def action_replace_file(body):
    """A user reported the current file as bad: blocklist the release that
    produced it (newest grab/import history marked failed), delete the file
    through the arr, and search for a replacement."""
    body = _require_body(body)
    dry_run = _get_bool(body, "dry_run")
    app = _require_arr(body)
    blocklist = _get_bool(body, "blocklist", True)
    kind, rid, path, rec = _item_target(app, body)

    f = _current_file(app, kind, rec)
    if f is None:
        _verify_failed("%s %d has no file to replace" % (kind, rid),
                       detail={"has_file": False, "title": rec.get("title")})
    hist_id, source_title = _latest_grab_history(app, kind, rid) if blocklist else (None, None)

    before = {"app": app, "%s_id" % kind: rid, "title": rec.get("title"),
              "series_id": rec.get("seriesId") if kind == "episode" else None,
              "file": _file_view(f), "history_id": hist_id, "source_title": source_title}
    planned = []
    if blocklist:
        if hist_id is not None:
            planned.append("POST %s /api/v3/history/failed/%d (blocklist %r)"
                           % (app, hist_id, source_title))
        else:
            planned.append("blocklist skipped: no grab/import history for %s %d"
                           % (kind, rid))
    planned.append("DELETE %s /api/v3/%sfile/%d (%s)"
                   % (app, kind, f["id"], lib.arr_host_path(f.get("path"))))
    cmd, search_step = _search_command(app, kind, rid)
    planned.append(search_step)
    if dry_run:
        return _dry_result("replace-file", before, planned)

    performed = []
    if blocklist:
        if hist_id is not None:
            lib.arr_call(app, "POST", "/api/v3/history/failed/%d" % hist_id)
        performed.append(planned[0])
    lib.arr_call(app, "DELETE", "/api/v3/%sfile/%d" % (kind, f["id"]))
    performed.append(planned[-2])
    rec2 = _arr_resource(app, path)
    if rec2 is None or rec2.get("hasFile"):
        _verify_failed("%s %d still has a file after delete" % (kind, rid),
                       detail={"performed": performed, "has_file": bool(rec2 and rec2.get("hasFile"))})
    command_id, state = _run_search(app, cmd, performed, search_step)
    after = {"has_file": False, "blocklisted": bool(blocklist and hist_id is not None),
             "command_id": command_id, "command_state": state}
    return _result("replace-file", False, before, planned, performed, after, True)


def action_fill_missing(body):
    """A user reported an item missing: make sure it is monitored, then
    search. Refuses (409) when the item already has a file - that is a
    replace-file request, not a fill."""
    body = _require_body(body)
    dry_run = _get_bool(body, "dry_run")
    app = _require_arr(body)
    monitor = _get_bool(body, "monitor", True)
    kind, rid, path, rec = _item_target(app, body)

    if rec.get("hasFile"):
        _verify_failed("%s %d already has a file" % (kind, rid),
                       detail={"has_file": True, "title": rec.get("title"),
                               "file": _file_view(_current_file(app, kind, rec))})
    need_monitor = monitor and not rec.get("monitored")
    before = {"app": app, "%s_id" % kind: rid, "title": rec.get("title"),
              "series_id": rec.get("seriesId") if kind == "episode" else None,
              "monitored": bool(rec.get("monitored")), "has_file": False,
              "air_date": rec.get("airDate") if kind == "episode" else rec.get("year")}
    planned = []
    if need_monitor:
        if kind == "episode":
            planned.append("PUT sonarr /api/v3/episode/monitor episodeIds=[%d] monitored=true" % rid)
        else:
            planned.append("PUT radarr /api/v3/movie/%d monitored=true" % rid)
    cmd, search_step = _search_command(app, kind, rid)
    planned.append(search_step)
    if dry_run:
        return _dry_result("fill-missing", before, planned)

    performed = []
    if need_monitor:
        if kind == "episode":
            lib.arr_call("sonarr", "PUT", "/api/v3/episode/monitor",
                         body={"episodeIds": [rid], "monitored": True})
        else:
            obj = dict(rec)
            obj["monitored"] = True
            lib.arr_call("radarr", "PUT", "/api/v3/movie/%d" % rid, body=obj)
        performed.append(planned[0])
        rec2 = _arr_resource(app, path)
        if rec2 is None or not rec2.get("monitored"):
            _verify_failed("%s %d is still unmonitored after update" % (kind, rid),
                           detail={"performed": performed})
    command_id, state = _run_search(app, cmd, performed, search_step)
    after = {"monitored": True if need_monitor else bool(rec.get("monitored")),
             "command_id": command_id, "command_state": state}
    return _result("fill-missing", False, before, planned, performed, after, True)


# ---------------------------------------------------------------------------
# Compression-wave actions (CONTRACT.md 5.9-5.12). reclaim-schedule REPLACES
# the worker queue with the chosen set (the plan for one window); the flag
# actions touch/remove the worker's PAUSE / PILOT_ACK files. The worker
# itself (media-transcoder) is never started or stopped from here.

import probes as _probes  # noqa: E402  (plan logic is shared with the probe)


def _reclaim_plan_from_body(body):
    window = body.get("window", "tonight")
    if window not in ("tonight", "workday", "next"):
        _bad("window must be tonight, workday, or next")
    hours = body.get("hours")
    if hours is not None and (isinstance(hours, bool) or not isinstance(hours, (int, float))
                              or hours <= 0):
        _bad("hours must be a positive number")
    limit = body.get("limit")
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0):
        _bad("limit must be a positive integer")
    return _probes.reclaim_plan(window, hours, limit, _get_bool(body, "refresh"))


def action_reclaim_schedule(body):
    """Queue a compression wave: either the given titles or the plan for a
    window. The queue file is replaced wholesale, so what is queued is
    exactly the wave; the worker picks it up inside its windows."""
    body = _require_body(body)
    dry_run = _get_bool(body, "dry_run")
    titles = body.get("titles")
    if titles is not None and (not isinstance(titles, list) or not titles
                               or not all(isinstance(t, str) and t.strip() for t in titles)):
        _bad("titles must be a non-empty list of strings")
    plan = _reclaim_plan_from_body(body)
    rep = lib.latest_reclaim_report()
    cands = {c["title"]: c for c in _probes._candidate_rows(rep[1])} if rep else {}
    if titles is None:
        chosen = plan["selected"]
    else:
        missing = [t for t in titles if t not in cands]
        if missing:
            _verify_failed("titles not among the current transcode candidates: %s" % missing,
                           detail={"missing_titles": missing,
                                   "hint": "titles must match the scan report exactly"})
        chosen = [dict(cands[t], est_minutes=_probes._plan_minutes(cands[t]["size_gb"]))
                  for t in titles]
    for c in chosen:
        if lib.reclaim_keep_match(c["title"]):
            _verify_failed("keep-list title refused: %s" % c["title"], detail={"title": c["title"]})
    if not chosen:
        _verify_failed("nothing fits the window budget", detail={"window": plan["window"]})
    # Re-verify every source file is still there and not hollow.
    rows, gone = [], []
    for c in chosen:
        path = os.path.join(lib.PLEX_ROOT, c["rel_path"])
        st = lib.stat_file(path)
        if st is None or st["sparse"]:
            gone.append({"title": c["title"], "reason": "missing" if st is None else "sparse"})
            continue
        rows.append((c["rel_path"], st["size_bytes"], c["est_target_gb"], c["title"]))
    if gone:
        _verify_failed("source files missing or hollow: %s" % [g["title"] for g in gone],
                       detail={"gone": gone})
    before = {"queue_rows": len(lib.reclaim_queue_rows()), "window": plan["window"],
              "flags": plan["flags"], "counts": plan["counts"] if titles is None else None}
    planned = ["write %s with %d titles (%s, est. gain %.0f GiB, est. %.1f h)"
               % (lib.RECLAIM_QUEUE, len(rows), plan["window"]["label"] or "manual",
                  sum(c["est_gain_gb"] for c in chosen),
                  sum(c["est_minutes"] for c in chosen) / 60.0)]
    planned += ["  %s [%s, %.0f GiB -> ~%s GiB]" % (c["title"], c["band"], c["size_gb"],
                                                   c["est_target_gb"]) for c in chosen]
    if dry_run:
        return _dry_result("reclaim-schedule", before, planned)
    lib.write_reclaim_queue(rows)
    performed = list(planned)
    now_rows = lib.reclaim_queue_rows()
    if {r["rel_path"] for r in now_rows} != {r[0] for r in rows}:
        _verify_failed("queue does not match the scheduled set after write",
                       detail={"performed": performed, "queue_rows": len(now_rows)})
    after = {"queue_rows": len(now_rows), "est_gain_gb": round(sum(c["est_gain_gb"] for c in chosen), 1),
             "est_hours": round(sum(c["est_minutes"] for c in chosen) / 60.0, 2),
             "titles": [c["title"] for c in chosen]}
    return _result("reclaim-schedule", False, before, planned, performed, after, True)


def _flag_action(name, path, want_present):
    def _run(body):
        body = _require_body(body)
        dry_run = _get_bool(body, "dry_run")
        present = os.path.exists(path)
        before = {"flag": os.path.basename(path), "present": present,
                  "flags": lib.reclaim_flags()}
        if present == want_present:
            return _result(name, dry_run, before, [], [], None if dry_run else before, None if dry_run else True)
        planned = [("sudo touch %s" if want_present else "sudo rm -f %s") % path]
        if dry_run:
            return _dry_result(name, before, planned)
        lib.sudo(["touch", path] if want_present else ["rm", "-f", path])
        if os.path.exists(path) != want_present:
            _verify_failed("%s still %s" % (path, "absent" if want_present else "present"),
                           detail={"performed": planned})
        after = {"flag": os.path.basename(path), "present": want_present,
                 "flags": lib.reclaim_flags()}
        return _result(name, False, before, planned, list(planned), after, True)
    return _run


action_reclaim_pause = _flag_action("reclaim-pause", lib.RECLAIM_PAUSE, True)
action_reclaim_resume = _flag_action("reclaim-resume", lib.RECLAIM_PAUSE, False)
action_reclaim_pilot_ack = _flag_action("reclaim-pilot-ack", lib.RECLAIM_PILOT_ACK, True)


# ---------------------------------------------------------------------------
# Whitelist (CONTRACT.md section 7.3)

ACTIONS = {
    "reclaim-schedule": action_reclaim_schedule,
    "reclaim-pause": action_reclaim_pause,
    "reclaim-resume": action_reclaim_resume,
    "reclaim-pilot-ack": action_reclaim_pilot_ack,
    "restart-prowlarr": action_restart_prowlarr,
    "pull-recreate": action_pull_recreate,
    "resurrect-stragglers": action_resurrect_stragglers,
    "queue-remove": action_queue_remove,
    "search": action_search,
    "delete-download": action_delete_download,
    "replace-file": action_replace_file,
    "fill-missing": action_fill_missing,
}
