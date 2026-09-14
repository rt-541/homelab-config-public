"""Offline unit tests for plex-ops probes.py.

No live APIs, no docker, no sudo: every plexops_lib boundary is mocked.
Queue fixtures model the REAL status messages observed in the 2026-09-10
Sonarr queue snapshot (137 items, 96 stuck warnings).

Run: python3 -m unittest discover -s scripts/plex-ops/tests -v
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import plexops_lib as lib  # noqa: E402
import probes  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures: real observed queue status messages (2026-09-10 snapshot)

MSG_EXE = "Caution: Found executable file with extension: '.exe'"
MSG_SCR = "Caution: Found executable file with extension: '.scr'"
MSG_RAR = "Invalid video file, unsupported extension: '.rar'"
MSG_NOT_UPGRADE = "Not an upgrade for existing episode file(s)"
MSG_TITLE_MISMATCH = "Series title mismatch; automatic import is not possible"
MSG_EP_NOT_FOUND = "Episode 5x06 was not found in the grabbed release"
MSG_INVALID_SEASON = "Invalid season or episode"
MSG_SAMPLE = "Unable to determine if file is a sample"
MSG_STALLED = "The download is stalled with no connections"


def qitem(**overrides):
    """A raw arr queue record with sane defaults; override per test."""
    item = {
        "id": 100,
        "title": "Some.Show.S05E06.1080p.WEB-DL.x264-GRP",
        "downloadId": "ABCDEF0123456789",
        "protocol": "torrent",
        "status": "completed",
        "trackedDownloadStatus": "warning",
        "trackedDownloadState": "importPending",
        "size": 2000000000,
        "sizeleft": 0,
        "outputPath": "/data/downloads/Some.Show.S05E06",
        "seriesId": 10,
        "episodeId": 200,
        "statusMessages": [],
    }
    item.update(overrides)
    return item


def msgs(*messages, **kw):
    """statusMessages block with one entry carrying the given messages."""
    return [{"title": kw.get("title", "Some.Show.S05E06.1080p.WEB-DL.x264-GRP"),
             "messages": list(messages)}]


# One fixture per observed message, mapped to its expected class.
CLASSIFIER_FIXTURES = [
    (MSG_EXE, "malware-ext"),
    (MSG_SCR, "malware-ext"),
    (MSG_RAR, "malware-ext"),
    (MSG_NOT_UPGRADE, "not-upgrade"),
    (MSG_TITLE_MISMATCH, "mapping-mismatch"),
    (MSG_EP_NOT_FOUND, "mapping-mismatch"),
    (MSG_INVALID_SEASON, "mapping-mismatch"),
    (MSG_SAMPLE, "sample-stall"),
]


class TestClassifyQueueItem(unittest.TestCase):

    def classify(self, item):
        return probes.classify_queue_item(item, "sonarr")

    def test_exe_is_malware_ext(self):
        cls, ev = self.classify(qitem(statusMessages=msgs(MSG_EXE)))
        self.assertEqual(cls, "malware-ext")
        self.assertIn(MSG_EXE, ev)

    def test_scr_is_malware_ext(self):
        cls, ev = self.classify(qitem(statusMessages=msgs(MSG_SCR)))
        self.assertEqual(cls, "malware-ext")
        self.assertIn(MSG_SCR, ev)

    def test_rar_is_malware_ext(self):
        cls, ev = self.classify(qitem(statusMessages=msgs(MSG_RAR)))
        self.assertEqual(cls, "malware-ext")
        self.assertIn(MSG_RAR, ev)

    def test_malware_ext_from_output_path(self):
        item = qitem(outputPath="/data/downloads/Fake.Movie.2026/setup.exe")
        cls, ev = self.classify(item)
        self.assertEqual(cls, "malware-ext")
        self.assertTrue(any("setup.exe" in e for e in ev))

    def test_malware_ext_from_queue_title(self):
        item = qitem(title="Some.Movie.2026.1080p.scr")
        cls, ev = self.classify(item)
        self.assertEqual(cls, "malware-ext")
        self.assertTrue(any("Some.Movie.2026.1080p.scr" in e for e in ev))

    def test_scream_title_is_not_malware(self):
        # ".scr" inside "The.Scream" must not trip the extension match.
        item = qitem(title="The.Scream.1996.1080p.BluRay.x264")
        cls, _ev = self.classify(item)
        self.assertEqual(cls, "unknown")

    def test_not_upgrade(self):
        cls, ev = self.classify(qitem(statusMessages=msgs(MSG_NOT_UPGRADE)))
        self.assertEqual(cls, "not-upgrade")
        self.assertIn(MSG_NOT_UPGRADE, ev)

    def test_title_mismatch_is_mapping_mismatch(self):
        cls, ev = self.classify(qitem(statusMessages=msgs(MSG_TITLE_MISMATCH)))
        self.assertEqual(cls, "mapping-mismatch")
        self.assertIn(MSG_TITLE_MISMATCH, ev)

    def test_episode_not_found_is_mapping_mismatch(self):
        cls, ev = self.classify(qitem(statusMessages=msgs(MSG_EP_NOT_FOUND)))
        self.assertEqual(cls, "mapping-mismatch")
        self.assertIn(MSG_EP_NOT_FOUND, ev)

    def test_invalid_season_is_mapping_mismatch(self):
        cls, ev = self.classify(qitem(statusMessages=msgs(MSG_INVALID_SEASON)))
        self.assertEqual(cls, "mapping-mismatch")
        self.assertIn(MSG_INVALID_SEASON, ev)

    def test_sample_is_sample_stall(self):
        cls, ev = self.classify(qitem(statusMessages=msgs(MSG_SAMPLE)))
        self.assertEqual(cls, "sample-stall")
        self.assertIn(MSG_SAMPLE, ev)

    def test_stalled_torrent_is_sample_stall(self):
        item = qitem(sizeleft=500000000, status="warning",
                     trackedDownloadStatus="warning",
                     errorMessage=MSG_STALLED, statusMessages=[])
        cls, ev = self.classify(item)
        self.assertEqual(cls, "sample-stall")
        self.assertIn(MSG_STALLED, ev)

    def test_stall_message_without_warning_status_is_unknown(self):
        # sizeleft > 0 but tracked status ok: not counted as stalled.
        item = qitem(sizeleft=500000000, trackedDownloadStatus="ok",
                     errorMessage=MSG_STALLED, statusMessages=[])
        cls, _ev = self.classify(item)
        self.assertEqual(cls, "unknown")

    def test_healthy_in_progress_is_unknown(self):
        item = qitem(status="downloading", trackedDownloadStatus="ok",
                     trackedDownloadState="downloading", sizeleft=1500000000,
                     statusMessages=[])
        cls, ev = self.classify(item)
        self.assertEqual(cls, "unknown")
        self.assertEqual(ev, [])

    def test_malware_beats_not_upgrade(self):
        cls, ev = self.classify(qitem(statusMessages=msgs(MSG_EXE, MSG_NOT_UPGRADE)))
        self.assertEqual(cls, "malware-ext")
        self.assertIn(MSG_EXE, ev)
        self.assertNotIn(MSG_NOT_UPGRADE, ev)

    def test_not_upgrade_beats_mapping(self):
        cls, _ev = self.classify(
            qitem(statusMessages=msgs(MSG_NOT_UPGRADE, MSG_TITLE_MISMATCH)))
        self.assertEqual(cls, "not-upgrade")

    def test_every_observed_message_maps_to_its_class(self):
        for message, expected in CLASSIFIER_FIXTURES:
            cls, ev = self.classify(qitem(statusMessages=msgs(message)))
            self.assertEqual(cls, expected, "message %r -> %s, expected %s"
                             % (message, cls, expected))
            self.assertIn(message, ev)

    def test_all_five_classes_are_produced(self):
        items = [qitem(statusMessages=msgs(m)) for m, _c in CLASSIFIER_FIXTURES]
        items.append(qitem(sizeleft=1, trackedDownloadStatus="ok",
                           statusMessages=[]))  # healthy -> unknown
        produced = {probes.classify_queue_item(i, "sonarr")[0] for i in items}
        self.assertEqual(produced, set(probes.CLASSES))


class TestHostPath(unittest.TestCase):

    def test_data_maps_to_media(self):
        self.assertEqual(probes.host_path("/data/tv/Show A"),
                         "/docker/plex/media/tv/Show A")

    def test_data2_maps_to_media2(self):
        self.assertEqual(probes.host_path("/data2/movies/M"),
                         "/docker/plex/media2/movies/M")

    def test_data2_not_swallowed_by_data(self):
        self.assertEqual(probes.host_path("/data2"), "/docker/plex/media2")

    def test_other_paths_untouched(self):
        self.assertEqual(probes.host_path("/config/x"), "/config/x")
        self.assertIsNone(probes.host_path(None))


# ---------------------------------------------------------------------------
# Probe: queue-health


def sonarr_queue_fixture():
    """One item of every class, using the observed messages."""
    return [
        qitem(id=1, statusMessages=msgs(MSG_EXE)),
        qitem(id=2, statusMessages=msgs(MSG_RAR)),
        qitem(id=3, statusMessages=msgs(MSG_NOT_UPGRADE)),
        qitem(id=4, statusMessages=msgs(MSG_TITLE_MISMATCH)),
        qitem(id=5, statusMessages=msgs(MSG_SAMPLE)),
        qitem(id=6, status="downloading", trackedDownloadStatus="ok",
              sizeleft=999, statusMessages=[]),
    ]


class TestProbeQueueHealth(unittest.TestCase):

    def arr_get_for(self, queues):
        """arr_get side_effect serving per-app queue fixtures."""
        def _arr_get(app, path, params=None):
            self.assertEqual(path, "/api/v3/queue")
            records = queues[app]
            if isinstance(records, Exception):
                raise records
            return {"records": records, "totalRecords": len(records)}
        return _arr_get

    def test_counts_and_item_shape(self):
        queues = {"sonarr": sonarr_queue_fixture(),
                  "radarr": [qitem(id=50, seriesId=None, episodeId=None,
                                   movieId=77, statusMessages=msgs(MSG_NOT_UPGRADE))]}
        with mock.patch.object(lib, "arr_get", side_effect=self.arr_get_for(queues)):
            out = probes.probe_queue_health({})

        self.assertEqual(out["probe"], "queue-health")
        son = out["apps"]["sonarr"]
        self.assertEqual(son["total"], 6)
        self.assertEqual(set(son["counts"]), set(probes.CLASSES))
        self.assertEqual(son["counts"], {
            "malware-ext": 2, "not-upgrade": 1, "mapping-mismatch": 1,
            "sample-stall": 1, "unknown": 1,
        })
        self.assertEqual(sum(son["counts"].values()), son["total"])

        first = son["items"][0]
        self.assertEqual(first["app"], "sonarr")
        self.assertEqual(first["classification"], "malware-ext")
        self.assertIsNone(first["movie_id"])
        self.assertEqual(first["series_id"], 10)
        self.assertEqual(first["episode_ids"], [200])
        self.assertEqual(first["output_path"],
                         "/docker/plex/media/downloads/Some.Show.S05E06")
        self.assertIn(MSG_EXE, first["evidence"])

        rad = out["apps"]["radarr"]
        self.assertEqual(rad["total"], 1)
        ritem = rad["items"][0]
        self.assertEqual(ritem["movie_id"], 77)
        self.assertIsNone(ritem["series_id"])
        self.assertIsNone(ritem["episode_ids"])
        self.assertEqual(ritem["classification"], "not-upgrade")

        # The whole payload must be JSON-serializable.
        json.dumps(out)

    def test_pagination(self):
        records = [qitem(id=i, statusMessages=msgs(MSG_NOT_UPGRADE)) for i in range(5)]

        def _arr_get(app, path, params=None):
            if app == "radarr":
                return {"records": [], "totalRecords": 0}
            page = params["page"]
            size = params["pageSize"]
            start = (page - 1) * size
            return {"records": records[start:start + size], "totalRecords": len(records)}

        with mock.patch.object(lib, "QUEUE_PAGE_SIZE", 2), \
                mock.patch.object(lib, "arr_get", side_effect=_arr_get):
            out = probes.probe_queue_health({})
        self.assertEqual(out["apps"]["sonarr"]["total"], 5)
        self.assertEqual([i["id"] for i in out["apps"]["sonarr"]["items"]],
                         [0, 1, 2, 3, 4])

    def test_one_arr_down_still_succeeds(self):
        queues = {"sonarr": sonarr_queue_fixture(),
                  "radarr": lib.PlexOpsError("upstream-error", "radarr refused", 502)}
        with mock.patch.object(lib, "arr_get", side_effect=self.arr_get_for(queues)):
            out = probes.probe_queue_health({})
        self.assertEqual(out["apps"]["radarr"], {"error": "radarr refused"})
        self.assertEqual(out["apps"]["sonarr"]["total"], 6)

    def test_both_arrs_down_is_502(self):
        err = lib.PlexOpsError("upstream-error", "connection refused", 502)
        queues = {"sonarr": err, "radarr": err}
        with mock.patch.object(lib, "arr_get", side_effect=self.arr_get_for(queues)):
            with self.assertRaises(lib.PlexOpsError) as ctx:
                probes.probe_queue_health({})
        self.assertEqual(ctx.exception.status, 502)
        self.assertEqual(ctx.exception.code, "upstream-error")


# ---------------------------------------------------------------------------
# Probe: service-health


class TestProbeServiceHealth(unittest.TestCase):

    PS_ROWS = [
        {"name": "gluetun", "state": "running", "status": "Up 2 days (healthy)",
         "stack": "plex-stack", "image": "qmcgaw/gluetun:latest"},
        {"name": "byparr", "state": "running", "status": "Up 2 days (unhealthy)",
         "stack": "plex-stack", "image": "ghcr.io/thephaseless/byparr:latest"},
        {"name": "sonarr", "state": "running", "status": "Up 2 days",
         "stack": "plex-stack", "image": "linuxserver/sonarr:latest"},
        {"name": "radarr", "state": "running", "status": "Up 2 days",
         "stack": "plex-stack", "image": "linuxserver/radarr:latest"},
        {"name": "prowlarr", "state": "running", "status": "Up 2 days",
         "stack": "plex-stack", "image": "lscr.io/linuxserver/prowlarr:latest"},
        # qbittorrent intentionally absent -> "missing"
    ]

    HEALTH = {"gluetun": "healthy", "byparr": "unhealthy"}

    def _container_state(self, name):
        return {"state": "running", "health": self.HEALTH.get(name),
                "exit_code": 0, "status": "running",
                "started_at": "2026-09-08T00:00:00Z", "image_id": "sha256:abc"}

    def run_probe(self, egress_ip="203.0.113.7", stragglers=None):
        with mock.patch.object(lib, "prowlarr_ping",
                               return_value={"ok": True, "ms": 12, "error": None}), \
                mock.patch.object(lib, "docker_stats",
                                  return_value=[{"name": "prowlarr", "cpu_percent": 3.2}]), \
                mock.patch.object(lib, "docker_ps_all", return_value=self.PS_ROWS), \
                mock.patch.object(lib, "container_state",
                                  side_effect=self._container_state), \
                mock.patch.object(lib, "exited_255",
                                  return_value=stragglers or []), \
                mock.patch.object(lib, "gluetun_egress_ip", return_value=egress_ip):
            return probes.probe_service_health({})

    def test_shape_and_health(self):
        straggler = {"name": "byparr", "status": "Exited (255) 2 hours ago",
                     "stack": "plex-stack"}
        out = self.run_probe(stragglers=[straggler])
        self.assertEqual(out["probe"], "service-health")
        self.assertEqual(out["prowlarr"],
                         {"ping_ok": True, "ping_ms": 12, "cpu_percent": 3.2})
        self.assertEqual(set(out["containers"]), set(probes.SERVICE_CONTAINERS))
        self.assertEqual(out["containers"]["gluetun"]["health"], "healthy")
        self.assertEqual(out["containers"]["gluetun"]["status"], "Up 2 days (healthy)")
        self.assertEqual(out["containers"]["byparr"]["health"], "unhealthy")
        self.assertIsNone(out["containers"]["sonarr"]["health"])
        self.assertEqual(out["stragglers"], [straggler])
        self.assertEqual(out["vpn"], {"egress_ok": True, "egress_ip": "203.0.113.7"})
        json.dumps(out)

    def test_missing_container(self):
        out = self.run_probe()
        self.assertEqual(out["containers"]["qbittorrent"],
                         {"state": "missing", "health": None, "status": None})

    def test_vpn_down(self):
        out = self.run_probe(egress_ip=None)
        self.assertEqual(out["vpn"], {"egress_ok": False, "egress_ip": None})


# ---------------------------------------------------------------------------
# Probe: disk


class TestProbeDisk(unittest.TestCase):

    MOUNTS_1 = {
        "/docker/plex/media": {"size_bytes": 1000, "used_bytes": 970,
                               "avail_bytes": 30, "used_percent": 97.0},
        "/docker/plex/media2": {"size_bytes": 1000, "used_bytes": 400,
                                "avail_bytes": 600, "used_percent": 40.0},
    }
    MOUNTS_2 = {
        "/docker/plex/media": {"size_bytes": 1000, "used_bytes": 975,
                               "avail_bytes": 25, "used_percent": 97.5},
        "/docker/plex/media2": {"size_bytes": 1000, "used_bytes": 390,
                                "avail_bytes": 610, "used_percent": 39.0},
    }

    def probe_with(self, mounts, state_path):
        with mock.patch.object(lib, "DISK_STATE", state_path), \
                mock.patch.object(lib, "df_mounts", return_value=mounts), \
                mock.patch.object(lib, "ensure_log_dir"):
            return probes.probe_disk({})

    def test_first_run_trend_null_then_delta(self):
        with tempfile.TemporaryDirectory() as td:
            state = os.path.join(td, "disk-state.json")

            out1 = self.probe_with(self.MOUNTS_1, state)
            self.assertEqual(out1["probe"], "disk")
            self.assertIsNone(out1["trend"])
            self.assertEqual(out1["mounts"], self.MOUNTS_1)
            self.assertTrue(os.path.exists(state))

            out2 = self.probe_with(self.MOUNTS_2, state)
            trend = out2["trend"]
            self.assertIsNotNone(trend)
            self.assertEqual(trend["since"], out1["ts"])
            self.assertEqual(trend["delta_used_bytes"],
                             {"/docker/plex/media": 5, "/docker/plex/media2": -10})
            self.assertIsInstance(trend["hours"], float)
            self.assertGreaterEqual(trend["hours"], 0.0)

            # State was overwritten with the second snapshot.
            with open(state) as fh:
                saved = json.load(fh)
            self.assertEqual(saved["mounts"], self.MOUNTS_2)
            json.dumps(out2)

    def test_corrupt_state_treated_as_first_run(self):
        with tempfile.TemporaryDirectory() as td:
            state = os.path.join(td, "disk-state.json")
            with open(state, "w") as fh:
                fh.write("not json")
            out = self.probe_with(self.MOUNTS_1, state)
            self.assertIsNone(out["trend"])


# ---------------------------------------------------------------------------
# Probe: library-audit


class TestProbeLibraryAuditParams(unittest.TestCase):

    def assert400(self, params):
        with self.assertRaises(lib.PlexOpsError) as ctx:
            probes.probe_library_audit(params)
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, "bad-request")

    def test_bad_app(self):
        self.assert400({"app": "lidarr", "chunk": "0"})

    def test_missing_app(self):
        self.assert400({"chunk": "0"})

    def test_missing_chunk(self):
        self.assert400({"app": "sonarr"})

    def test_non_integer_chunk(self):
        self.assert400({"app": "sonarr", "chunk": "two"})

    def test_chunk_out_of_range(self):
        self.assert400({"app": "sonarr", "chunk": "7", "chunks": "7"})
        self.assert400({"app": "sonarr", "chunk": "-1", "chunks": "7"})

    def test_zero_chunks(self):
        self.assert400({"app": "sonarr", "chunk": "0", "chunks": "0"})


class TestProbeLibraryAuditSonarr(unittest.TestCase):

    SERIES_DIR = "/docker/plex/media/tv/Show A"
    TRACKED_E01 = SERIES_DIR + "/Season 01/Show.A.S01E01.1080p.mkv"   # missing
    TRACKED_E02 = SERIES_DIR + "/Season 01/Show.A.S01E02.1080p.mkv"   # sparse
    ORPHAN_E03 = SERIES_DIR + "/Season 01/Show.A.S01E03.720p.mkv"
    DUP_E04A = SERIES_DIR + "/Season 01/Show.A.S01E04.720p.mkv"
    DUP_E04B = SERIES_DIR + "/Season 01/Show.A.S01E04.1080p.mkv"

    def arr_get(self, app, path, params=None):
        self.assertEqual(app, "sonarr")
        if path == "/api/v3/series":
            return [{"id": 1, "title": "Show A", "path": "/data/tv/Show A"}]
        if path == "/api/v3/episodefile":
            self.assertEqual(params, {"seriesId": 1})
            return [{"path": "/data/tv/Show A/Season 01/Show.A.S01E01.1080p.mkv"},
                    {"path": "/data/tv/Show A/Season 01/Show.A.S01E02.1080p.mkv"}]
        if path == "/api/v3/wanted/missing":
            return {"totalRecords": 12}
        if path == "/api/v3/wanted/cutoff":
            return {"totalRecords": 30}
        raise AssertionError("unexpected arr_get path: %s" % path)

    def stat_file(self, path):
        if path == self.TRACKED_E01:
            return None  # tracked but gone from disk
        if path == self.TRACKED_E02:
            return {"nlink": 1, "size_bytes": 1000000, "blocks512": 100,
                    "mtime": 0, "sparse": True}
        return {"nlink": 1, "size_bytes": 1000000, "blocks512": 2000,
                "mtime": 0, "sparse": False}

    def find_files_blocks(self, roots, extra_args=None):
        self.assertEqual(list(roots), [self.SERIES_DIR])
        for path in (self.TRACKED_E02, self.ORPHAN_E03, self.DUP_E04A, self.DUP_E04B):
            d, f = os.path.split(path)
            yield 1000000, 1, d, f, 2000

    def test_findings_and_counts(self):
        with mock.patch.object(lib, "arr_get", side_effect=self.arr_get), \
                mock.patch.object(lib, "stat_file", side_effect=self.stat_file), \
                mock.patch.object(lib, "find_files_blocks",
                                  side_effect=self.find_files_blocks), \
                mock.patch.object(probes, "_list_subdirs",
                                  return_value=[self.SERIES_DIR + "/Season 01",
                                                self.SERIES_DIR + "/Extras"]):
            out = probes.probe_library_audit(
                {"app": "sonarr", "chunk": "0", "chunks": "1"})

        self.assertEqual(out["probe"], "library-audit")
        self.assertEqual(out["app"], "sonarr")
        self.assertEqual(out["chunk"], 0)
        self.assertEqual(out["chunks"], 1)
        self.assertEqual(out["titles_checked"], 1)
        self.assertEqual(out["counts"], {
            "missing-file": 1,
            "sparse-file": 1,
            "orphan-file": 3,          # E03 + both untracked E04 versions
            "malformed-dir": 1,        # "Extras" is not Season NN / Specials
            "duplicate-versions": 1,   # two S01E04 files
            "missing-monitored": 12,
            "cutoff-unmet": 30,
        })

        by_type = {}
        for f in out["findings"]:
            by_type.setdefault(f["type"], []).append(f)

        self.assertEqual(by_type["missing-file"][0]["path"], self.TRACKED_E01)
        sparse = by_type["sparse-file"][0]
        self.assertEqual(sparse["path"], self.TRACKED_E02)
        self.assertEqual(sparse["apparent_bytes"], 1000000)
        self.assertEqual(sparse["allocated_bytes"], 100 * 512)
        self.assertEqual(by_type["malformed-dir"][0]["path"],
                         self.SERIES_DIR + "/Extras")
        self.assertIn("S01E04", by_type["duplicate-versions"][0]["detail"])
        for f in out["findings"]:
            self.assertEqual(f["title"], "Show A")
            self.assertEqual(f["title_id"], 1)
            if f["type"] != "sparse-file":
                self.assertNotIn("apparent_bytes", f)
        json.dumps(out)


class TestProbeLibraryAuditRadarr(unittest.TestCase):

    MOVIE_DIR = "/docker/plex/media/movies/Movie B (2020)"
    TRACKED = MOVIE_DIR + "/Movie.B.2020.1080p.BluRay.mkv"
    EXTRA = MOVIE_DIR + "/Movie.B.2020.720p.WEBRip.mkv"

    def arr_get(self, app, path, params=None):
        self.assertEqual(app, "radarr")
        if path == "/api/v3/movie":
            return [{"id": 7, "title": "Movie B", "path": "/data/movies/Movie B (2020)",
                     "movieFile": {"path": "/data/movies/Movie B (2020)/Movie.B.2020.1080p.BluRay.mkv"}}]
        if path == "/api/v3/wanted/missing":
            return {"totalRecords": 2}
        if path == "/api/v3/wanted/cutoff":
            return {"totalRecords": 5}
        raise AssertionError("unexpected arr_get path: %s" % path)

    def find_files_blocks(self, roots, extra_args=None):
        for path in (self.TRACKED, self.EXTRA):
            d, f = os.path.split(path)
            yield 1000000, 1, d, f, 2000

    def test_duplicate_versions_and_allowed_extras_dir(self):
        healthy = {"nlink": 1, "size_bytes": 1000000, "blocks512": 2000,
                   "mtime": 0, "sparse": False}
        with mock.patch.object(lib, "arr_get", side_effect=self.arr_get), \
                mock.patch.object(lib, "stat_file", return_value=healthy), \
                mock.patch.object(lib, "find_files_blocks",
                                  side_effect=self.find_files_blocks), \
                mock.patch.object(probes, "_list_subdirs",
                                  return_value=[self.MOVIE_DIR + "/Featurettes"]):
            out = probes.probe_library_audit(
                {"app": "radarr", "chunk": "0", "chunks": "1"})

        self.assertEqual(out["counts"], {
            "missing-file": 0,
            "sparse-file": 0,
            "orphan-file": 1,          # the untracked 720p copy
            "malformed-dir": 0,        # Featurettes is a known extras dir
            "duplicate-versions": 1,   # two videos in the movie dir
            "missing-monitored": 2,
            "cutoff-unmet": 5,
        })
        dup = [f for f in out["findings"] if f["type"] == "duplicate-versions"][0]
        self.assertEqual(dup["path"], self.MOVIE_DIR)
        self.assertEqual(dup["title_id"], 7)

    def test_chunking_selects_by_index_mod_chunks(self):
        movies = [{"id": i, "title": "M%d" % i, "path": None} for i in (1, 2, 3)]

        def arr_get(app, path, params=None):
            if path == "/api/v3/movie":
                return movies
            return {"totalRecords": 0}

        with mock.patch.object(lib, "arr_get", side_effect=arr_get), \
                mock.patch.object(lib, "stat_file", return_value=None), \
                mock.patch.object(lib, "find_files_blocks", return_value=iter(())), \
                mock.patch.object(probes, "_list_subdirs", return_value=[]):
            out0 = probes.probe_library_audit(
                {"app": "radarr", "chunk": "0", "chunks": "2"})
            out1 = probes.probe_library_audit(
                {"app": "radarr", "chunk": "1", "chunks": "2"})

        self.assertEqual(out0["titles_checked"], 2)  # indices 0 and 2
        self.assertEqual(out1["titles_checked"], 1)  # index 1
        self.assertEqual(out0["chunks"], 2)

    def test_default_chunks_is_seven(self):
        def arr_get(app, path, params=None):
            if path == "/api/v3/movie":
                return []
            return {"totalRecords": 0}

        with mock.patch.object(lib, "arr_get", side_effect=arr_get):
            out = probes.probe_library_audit({"app": "radarr", "chunk": "6"})
        self.assertEqual(out["chunks"], 7)
        self.assertEqual(out["titles_checked"], 0)


# ---------------------------------------------------------------------------
# Registry


class TestProbesRegistry(unittest.TestCase):

    def test_contract_probe_names(self):
        self.assertEqual(set(probes.PROBES), {
            "queue-health", "service-health", "disk", "library-audit", "lookup",
            "reclaim-status", "reclaim-plan", "title-stats",
        })
        for fn in probes.PROBES.values():
            self.assertTrue(callable(fn))


if __name__ == "__main__":
    unittest.main()
