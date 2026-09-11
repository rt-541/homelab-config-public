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
# Whitelist (CONTRACT.md section 7.3)

ACTIONS = {
    "restart-prowlarr": action_restart_prowlarr,
    "pull-recreate": action_pull_recreate,
    "resurrect-stragglers": action_resurrect_stragglers,
    "queue-remove": action_queue_remove,
    "search": action_search,
    "delete-download": action_delete_download,
}
