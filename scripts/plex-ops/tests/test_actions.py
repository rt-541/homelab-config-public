"""Offline unit tests for scripts/plex-ops/actions.py.

No test touches the network, docker, sudo, or the live arr stack: a hard
guard in the base class fails any test that reaches subprocess.run or
urllib.request.urlopen, and every lib call an action makes is mocked at the
plexops_lib boundary. Run from anywhere:

    python3 -m unittest discover -s scripts/plex-ops/tests -v
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import plexops_lib as lib  # noqa: E402
import actions  # noqa: E402


def _no_subprocess(*args, **kwargs):
    raise AssertionError("test attempted a real subprocess call: %r" % (args,))


def _no_network(*args, **kwargs):
    raise AssertionError("test attempted a real network call: %r" % (args,))


RUNNING = {"state": "running", "health": None, "exit_code": 0,
           "status": "running", "started_at": "now", "image_id": "sha256:aaa"}
HEALTHY = dict(RUNNING, health="healthy")
PING_OK = {"ok": True, "ms": 7, "error": None}
PING_BAD = {"ok": False, "ms": None, "error": "connection refused"}


class OfflineTestCase(unittest.TestCase):
    """Base: hard offline guard + fake clock for the wait loop."""

    def setUp(self):
        for target, effect in (
            ("plexops_lib.subprocess.run", _no_subprocess),
            ("plexops_lib.urllib.request.urlopen", _no_network),
        ):
            p = mock.patch(target, side_effect=effect)
            p.start()
            self.addCleanup(p.stop)
        # Fake clock: _sleep advances _monotonic so timeout loops terminate
        # instantly instead of spinning for real seconds.
        self._t = [0.0]
        for name, fn in (("_monotonic", lambda: self._t[0]),
                         ("_sleep", lambda s: self._t.__setitem__(0, self._t[0] + s))):
            p = mock.patch.object(actions, name, fn)
            p.start()
            self.addCleanup(p.stop)

    def patch_lib(self, name, **kwargs):
        p = mock.patch.object(actions.lib, name, **kwargs)
        m = p.start()
        self.addCleanup(p.stop)
        return m

    def assertPlexOpsError(self, status, code, fn, *args):
        with self.assertRaises(lib.PlexOpsError) as cm:
            fn(*args)
        self.assertEqual(cm.exception.status, status)
        self.assertEqual(cm.exception.code, code)
        return cm.exception

    def assertDryShape(self, res, action):
        self.assertEqual(res["action"], action)
        self.assertTrue(res["dry_run"])
        self.assertEqual(res["performed"], [])
        self.assertIsNone(res["after"])
        self.assertIsNone(res["verified"])
        self.assertIsInstance(res["planned"], list)


# ---------------------------------------------------------------------------
# restart-prowlarr


class RestartProwlarrTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.compose = self.patch_lib("compose")
        self.arr_call = self.patch_lib("arr_call")

    def test_dry_run_plans_without_side_effects(self):
        self.patch_lib("container_state", return_value=dict(RUNNING))
        self.patch_lib("prowlarr_ping", return_value=dict(PING_OK))
        res = actions.action_restart_prowlarr({"dry_run": True})
        self.assertDryShape(res, "restart-prowlarr")
        self.assertEqual(res["before"], {"ping_ok": True, "ping_ms": 7})
        joined = " | ".join(res["planned"])
        self.assertIn("down prowlarr", joined)
        self.assertIn("up -d prowlarr", joined)
        self.assertIn("testall", joined)
        self.assertLess(joined.index("down prowlarr"), joined.index("up -d prowlarr"))
        self.compose.assert_not_called()
        self.arr_call.assert_not_called()

    def test_missing_container_is_409(self):
        self.patch_lib("container_state", return_value=None)
        self.assertPlexOpsError(409, "verify-failed",
                                actions.action_restart_prowlarr, {"dry_run": True})
        self.compose.assert_not_called()

    def test_execute_down_then_up_then_testall(self):
        self.patch_lib("container_state", return_value=dict(RUNNING))
        self.patch_lib("prowlarr_ping", return_value=dict(PING_OK))
        self.arr_call.return_value = []
        res = actions.action_restart_prowlarr({"dry_run": False})
        self.assertEqual(self.compose.call_args_list, [
            mock.call(lib.PLEX_STACK, ["down", "prowlarr"]),
            mock.call(lib.PLEX_STACK, ["up", "-d", "prowlarr"]),
        ])
        self.assertEqual(res["performed"], res["planned"])
        self.assertTrue(res["verified"])
        self.assertEqual(res["after"]["testall"], {"sonarr": "ok", "radarr": "ok"})
        self.assertTrue(res["after"]["ping_ok"])

    def test_ping_never_recovers_is_409_with_performed(self):
        self.patch_lib("container_state", return_value=dict(RUNNING))
        self.patch_lib("prowlarr_ping", return_value=dict(PING_BAD))
        e = self.assertPlexOpsError(409, "verify-failed",
                                    actions.action_restart_prowlarr, {})
        self.assertEqual(len(e.detail["performed"]), 2)
        self.assertEqual(e.detail["testall"],
                         {"sonarr": "skipped", "radarr": "skipped"})
        self.arr_call.assert_not_called()

    def test_testall_failure_reported_not_fatal(self):
        self.patch_lib("container_state", return_value=dict(RUNNING))
        self.patch_lib("prowlarr_ping", return_value=dict(PING_OK))
        self.arr_call.side_effect = [
            lib.PlexOpsError("upstream-error", "boom", 502), [],
        ]
        res = actions.action_restart_prowlarr({})
        self.assertEqual(res["after"]["testall"],
                         {"sonarr": "failed", "radarr": "ok"})
        self.assertTrue(res["verified"])


# ---------------------------------------------------------------------------
# pull-recreate


class PullRecreateTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.compose = self.patch_lib("compose")

    def test_unknown_service_is_400(self):
        for service in ("sonarr", "plex", "", None):
            self.assertPlexOpsError(400, "bad-request",
                                    actions.action_pull_recreate,
                                    {"service": service, "dry_run": True})
        self.compose.assert_not_called()

    def test_dry_run_gluetun_includes_qbit_pair(self):
        # Compose SERVICE names in the plan (`qbit` is the live plex-stack
        # service name); container_names in before/after (docker inspect).
        self.patch_lib("container_state", return_value=dict(HEALTHY))
        res = actions.action_pull_recreate({"service": "gluetun", "dry_run": True})
        self.assertDryShape(res, "pull-recreate")
        joined = " | ".join(res["planned"])
        self.assertIn("pull gluetun", joined)
        self.assertIn("down gluetun qbit", joined)
        self.assertIn("up -d gluetun qbit", joined)
        self.assertNotIn("qbittorrent", joined)
        self.assertEqual(sorted(res["before"]), ["gluetun", "qbittorrent"])
        self.compose.assert_not_called()

    def test_dry_run_byparr_is_alone(self):
        self.patch_lib("container_state", return_value=dict(RUNNING))
        res = actions.action_pull_recreate({"service": "byparr", "dry_run": True})
        joined = " | ".join(res["planned"])
        self.assertIn("down byparr", joined)
        self.assertNotIn("qbit", joined)
        self.assertEqual(list(res["before"]), ["byparr"])

    def test_missing_container_is_409(self):
        self.patch_lib("container_state", return_value=None)
        self.assertPlexOpsError(409, "verify-failed",
                                actions.action_pull_recreate,
                                {"service": "byparr", "dry_run": True})

    def test_execute_pull_down_up_and_health_wait(self):
        self.patch_lib("container_state", return_value=dict(HEALTHY))
        res = actions.action_pull_recreate({"service": "gluetun"})
        self.assertEqual(self.compose.call_args_list, [
            mock.call(lib.PLEX_STACK, ["pull", "gluetun"]),
            mock.call(lib.PLEX_STACK, ["down", "gluetun", "qbit"]),
            mock.call(lib.PLEX_STACK, ["up", "-d", "gluetun", "qbit"]),
        ])
        self.assertEqual(res["performed"], res["planned"])
        self.assertTrue(res["verified"])
        self.assertEqual(res["after"]["gluetun"]["health"], "healthy")

    def test_never_healthy_is_409_with_performed(self):
        self.patch_lib("container_state",
                       return_value=dict(RUNNING, health="unhealthy"))
        e = self.assertPlexOpsError(409, "verify-failed",
                                    actions.action_pull_recreate,
                                    {"service": "byparr"})
        self.assertEqual(len(e.detail["performed"]), 3)


# ---------------------------------------------------------------------------
# resurrect-stragglers


STRAGGLER = {"name": "sonarr", "status": "Exited (255) 2 hours ago",
             "stack": "plex-stack"}


class ResurrectStragglersTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.compose = self.patch_lib("compose")

    def test_unknown_stack_is_400(self):
        self.assertPlexOpsError(400, "bad-request",
                                actions.action_resurrect_stragglers,
                                {"stacks": ["nope"], "dry_run": True})
        self.assertPlexOpsError(400, "bad-request",
                                actions.action_resurrect_stragglers,
                                {"stacks": [], "dry_run": True})
        self.compose.assert_not_called()

    def test_no_stragglers_is_successful_noop(self):
        self.patch_lib("exited_255", return_value=[])
        res = actions.action_resurrect_stragglers({"dry_run": False})
        self.assertEqual(res["before"], {"stragglers": []})
        self.assertEqual(res["planned"], [])
        self.assertEqual(res["performed"], [])
        self.assertEqual(res["after"], {"stragglers": []})
        self.assertTrue(res["verified"])
        self.compose.assert_not_called()

    def test_dry_run_plans_one_up_per_stack(self):
        self.patch_lib("exited_255", return_value=[dict(STRAGGLER)])
        res = actions.action_resurrect_stragglers({"dry_run": True})
        self.assertDryShape(res, "resurrect-stragglers")
        self.assertEqual(res["planned"],
                         ["sudo docker compose up -d --no-recreate [plex-stack]"])
        self.assertEqual(res["before"]["stragglers"][0]["name"], "sonarr")
        self.compose.assert_not_called()

    def test_execute_ups_stack_and_verifies_running(self):
        exited = self.patch_lib("exited_255",
                                side_effect=[[dict(STRAGGLER)], []])
        self.patch_lib("container_state", return_value=dict(RUNNING))
        res = actions.action_resurrect_stragglers({})
        self.compose.assert_called_once_with(
            "plex-stack", ["up", "-d", "--no-recreate"])
        self.assertEqual(res["performed"], res["planned"])
        self.assertEqual(res["after"], {"stragglers": []})
        self.assertTrue(res["verified"])
        self.assertEqual(exited.call_count, 2)

    def test_still_exited_after_up_is_409(self):
        self.patch_lib("exited_255",
                       side_effect=[[dict(STRAGGLER)], [dict(STRAGGLER)]])
        self.patch_lib("container_state",
                       return_value=dict(RUNNING, state="exited"))
        e = self.assertPlexOpsError(409, "verify-failed",
                                    actions.action_resurrect_stragglers, {})
        self.assertEqual(e.detail["not_running"][0]["name"], "sonarr")


# ---------------------------------------------------------------------------
# queue-remove


def queue_item(**over):
    item = {
        "id": 12345,
        "title": "Totally.Legit.Movie.2026.1080p.WEB-DL.exe",
        "downloadId": "ABCDEF",
        "protocol": "torrent",
        "status": "completed",
        "trackedDownloadStatus": "warning",
        "trackedDownloadState": "importPending",
        "size": 1000,
        "sizeleft": 0,
        "outputPath": "/data/downloads/Totally.Legit.Movie.2026.1080p.WEB-DL",
        "seriesId": 10,
        "episodeId": 200,
        "statusMessages": [
            {"title": "Totally.Legit.Movie.2026.1080p.WEB-DL.exe",
             "messages": ["No files found are eligible for import"]},
        ],
    }
    item.update(over)
    return item


class QueueRemoveTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.arr_get = self.patch_lib("arr_get")
        self.arr_call = self.patch_lib("arr_call")

    def test_bad_app_and_bad_id_are_400(self):
        self.assertPlexOpsError(400, "bad-request", actions.action_queue_remove,
                                {"app": "plex", "id": 1})
        self.assertPlexOpsError(400, "bad-request", actions.action_queue_remove,
                                {"app": "sonarr"})
        self.assertPlexOpsError(400, "bad-request", actions.action_queue_remove,
                                {"app": "sonarr", "id": "12345"})
        self.arr_get.assert_not_called()

    def test_item_gone_is_409(self):
        self.arr_get.return_value = {"records": []}
        self.assertPlexOpsError(409, "verify-failed", actions.action_queue_remove,
                                {"app": "sonarr", "id": 12345, "dry_run": True})

    def test_expect_mismatch_is_409_with_current_item(self):
        self.arr_get.return_value = {"records": [queue_item()]}
        e = self.assertPlexOpsError(
            409, "verify-failed", actions.action_queue_remove,
            {"app": "sonarr", "id": 12345, "expect": "not-upgrade",
             "dry_run": True})
        self.assertEqual(e.detail["item"]["classification"], "malware-ext")

    def test_remove_data_refuses_trash_output_path(self):
        self.arr_get.return_value = {"records": [queue_item(
            outputPath="/data/downloads/.Trash-1000/files/x")]}
        self.assertPlexOpsError(
            409, "verify-failed", actions.action_queue_remove,
            {"app": "sonarr", "id": 12345, "removeData": True, "dry_run": True})
        self.arr_call.assert_not_called()

    def test_remove_data_refuses_path_outside_downloads(self):
        self.arr_get.return_value = {"records": [queue_item(
            outputPath="/data/media/tv/Show/Season 1")]}
        self.assertPlexOpsError(
            409, "verify-failed", actions.action_queue_remove,
            {"app": "sonarr", "id": 12345, "removeData": True, "dry_run": True})
        self.arr_call.assert_not_called()

    def test_dry_run_classifies_and_plans_delete(self):
        self.arr_get.return_value = {"records": [queue_item()]}
        res = actions.action_queue_remove(
            {"app": "sonarr", "id": 12345, "blocklist": True,
             "removeData": True, "expect": "malware-ext", "dry_run": True})
        self.assertDryShape(res, "queue-remove")
        self.assertEqual(res["before"]["classification"], "malware-ext")
        self.assertEqual(res["before"]["episode_ids"], [200])
        self.assertIsNone(res["before"]["movie_id"])
        # output_path is host-translated, matching the queue-health probe.
        self.assertEqual(
            res["before"]["output_path"],
            "/docker/plex/media/downloads/Totally.Legit.Movie.2026.1080p.WEB-DL")
        self.assertEqual(res["planned"], [
            "DELETE sonarr /api/v3/queue/12345?removeFromClient=true"
            "&blocklist=true&skipRedownload=true"])
        self.arr_call.assert_not_called()

    def test_execute_deletes_and_verifies_gone(self):
        self.arr_get.side_effect = [{"records": [queue_item()]},
                                    {"records": []}]
        self.arr_call.return_value = None
        res = actions.action_queue_remove(
            {"app": "sonarr", "id": 12345, "blocklist": True,
             "removeData": True})
        self.arr_call.assert_called_once_with(
            "sonarr", "DELETE", "/api/v3/queue/12345",
            params={"removeFromClient": "true", "blocklist": "true",
                    "skipRedownload": "true"})
        self.assertEqual(res["performed"], res["planned"])
        self.assertEqual(res["after"], {"in_queue": False})
        self.assertTrue(res["verified"])

    def test_still_in_queue_after_delete_is_409(self):
        self.arr_get.side_effect = [{"records": [queue_item()]},
                                    {"records": [queue_item()]}]
        e = self.assertPlexOpsError(409, "verify-failed", actions.action_queue_remove,
                                    {"app": "sonarr", "id": 12345, "removeData": True})
        self.assertIn("still present", e.message)

    def test_completed_download_without_remove_data_is_refused(self):
        # Sonarr re-tracks a completed download that stays in the client under
        # the same queue id, so remove-without-data is a no-op: refuse it.
        self.arr_get.return_value = {"records": [queue_item(sizeleft=0)]}
        e = self.assertPlexOpsError(409, "verify-failed", actions.action_queue_remove,
                                    {"app": "sonarr", "id": 12345, "blocklist": True,
                                     "dry_run": True})
        self.assertIn("removeData", e.message)
        self.arr_call.assert_not_called()
        # an in-progress download (sizeleft > 0) may still be removed without data
        self.arr_get.return_value = {"records": [queue_item(sizeleft=500)]}
        res = actions.action_queue_remove({"app": "sonarr", "id": 12345, "dry_run": True})
        self.assertDryShape(res, "queue-remove")

    def test_classifier_not_upgrade(self):
        item = queue_item(
            title="Show.S01E01.1080p.WEB-DL",
            outputPath="/data/downloads/Show.S01E01",
            statusMessages=[{"title": "Show.S01E01", "messages": [
                "Not an upgrade for existing episode file(s)"]}])
        self.arr_get.return_value = {"records": [item]}
        res = actions.action_queue_remove(
            {"app": "sonarr", "id": 12345, "expect": "not-upgrade",
             "removeData": True, "dry_run": True})
        self.assertEqual(res["before"]["classification"], "not-upgrade")
        self.assertIn("Not an upgrade for existing episode file(s)",
                      res["before"]["evidence"])


# ---------------------------------------------------------------------------
# search


class SearchTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.arr_call = self.patch_lib("arr_call")
        self.patch_lib("arr_key", return_value="k")
        self.http_json = self.patch_lib("http_json")

    def test_bad_bodies_are_400(self):
        bad = [
            {"app": "prowlarr", "movie_ids": [1]},
            {"app": "radarr"},
            {"app": "radarr", "movie_ids": []},
            {"app": "radarr", "movie_ids": ["1"]},
            {"app": "radarr", "movie_ids": [1], "series_id": 2},
            {"app": "sonarr"},
            {"app": "sonarr", "episode_ids": [1], "series_id": 2},
            {"app": "sonarr", "movie_ids": [1]},
            {"app": "sonarr", "series_id": "10"},
        ]
        for body in bad:
            body["dry_run"] = True
            self.assertPlexOpsError(400, "bad-request", actions.action_search, body)
        self.http_json.assert_not_called()
        self.arr_call.assert_not_called()

    def test_missing_id_is_409(self):
        self.http_json.return_value = (404, None)
        e = self.assertPlexOpsError(
            409, "verify-failed", actions.action_search,
            {"app": "radarr", "movie_ids": [7], "dry_run": True})
        self.assertEqual(e.detail["missing_ids"], [7])
        self.arr_call.assert_not_called()

    def test_dry_run_radarr_plans_movies_search(self):
        self.http_json.return_value = (200, {"title": "A Movie"})
        res = actions.action_search(
            {"app": "radarr", "movie_ids": [1, 2], "dry_run": True})
        self.assertDryShape(res, "search")
        self.assertEqual(res["before"]["targets"],
                         [{"id": 1, "title": "A Movie"},
                          {"id": 2, "title": "A Movie"}])
        self.assertIn("MoviesSearch", res["planned"][0])
        self.arr_call.assert_not_called()

    def test_execute_sonarr_series_search(self):
        self.http_json.return_value = (200, {"title": "A Show"})
        self.arr_call.return_value = {"id": 987, "status": "queued"}
        res = actions.action_search({"app": "sonarr", "series_id": 10})
        self.arr_call.assert_called_once_with(
            "sonarr", "POST", "/api/v3/command",
            body={"name": "SeriesSearch", "seriesId": 10})
        self.assertEqual(res["after"],
                         {"command_id": 987, "command_state": "queued"})
        self.assertTrue(res["verified"])

    def test_execute_sonarr_episode_search(self):
        self.http_json.return_value = (200, {"title": "Ep"})
        self.arr_call.return_value = {"id": 5, "status": "queued"}
        actions.action_search({"app": "sonarr", "episode_ids": [200, 201]})
        self.arr_call.assert_called_once_with(
            "sonarr", "POST", "/api/v3/command",
            body={"name": "EpisodeSearch", "episodeIds": [200, 201]})


# ---------------------------------------------------------------------------
# delete-download


DL = lib.DOWNLOADS  # /docker/plex/media/downloads
TARGET = DL + "/Some.Release.2026"
STAT = {"nlink": 1, "size_bytes": 1000, "blocks512": 2, "mtime": 1,
        "sparse": True}


class FakeQbitUnavailable(object):
    """No creds configured -> ownership check silently skipped."""
    available = False
    user = None
    password = None

    def __init__(self, *args, **kwargs):
        pass


class FakeQbitDown(FakeQbitUnavailable):
    """Creds configured but login failed -> the action must refuse."""
    user = "admin"
    password = "secret"


def _is_rm_cmd(cmd):
    """The delete invocation: one sudo sh -c that re-verifies realpath and
    rms in the same process (TOCTOU narrowing)."""
    return cmd[:2] == ["sh", "-c"] and "rm -rf" in cmd[2]


class DeleteDownloadTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.sudo = self.patch_lib("sudo")
        self.patch_lib("Qbit", new=FakeQbitUnavailable)
        self.qbit_hits = self.patch_lib("qbit_hits_under", return_value=None)
        self.stat_file = self.patch_lib("stat_file", return_value=dict(STAT))
        self.samefile = self.patch_lib("samefile_hits", return_value=[])

    def sudo_realpath(self, real, allow_rm=False):
        calls = []

        def fake(cmd, **kwargs):
            calls.append(cmd)
            if cmd[:2] == ["realpath", "-e"]:
                return real + "\n"
            if _is_rm_cmd(cmd):
                if not allow_rm:
                    raise AssertionError("rm executed when it must not be: %r" % cmd)
                self.assertEqual(cmd[4], real)  # deletes the RESOLVED path
                return ""
            raise AssertionError("unexpected sudo command: %r" % cmd)

        self.sudo.side_effect = fake
        return calls

    # --- policy rejections (400, nothing runs at all) ---

    def test_rejects_non_absolute_and_non_string(self):
        for path in ("relative/path", "", None, 42):
            self.assertPlexOpsError(400, "bad-request",
                                    actions.action_delete_download,
                                    {"path": path, "dry_run": True})
        self.sudo.assert_not_called()

    def test_rejects_path_outside_downloads(self):
        for path in ("/docker/plex/media/tv/Show",
                     "/docker/plex/media/downloads-evil/x",
                     "/tmp/x"):
            self.assertPlexOpsError(400, "bad-request",
                                    actions.action_delete_download,
                                    {"path": path, "dry_run": True})
        self.sudo.assert_not_called()

    def test_rejects_downloads_root_itself(self):
        for path in (DL, DL + "/", DL + "/sub/.."):
            self.assertPlexOpsError(400, "bad-request",
                                    actions.action_delete_download,
                                    {"path": path, "dry_run": True})
        self.sudo.assert_not_called()

    def test_rejects_dotdot_traversal_out_of_downloads(self):
        self.assertPlexOpsError(
            400, "bad-request", actions.action_delete_download,
            {"path": DL + "/../tv/Show", "dry_run": True})
        self.sudo.assert_not_called()

    def test_rejects_trash_component(self):
        for path in (DL + "/.Trash-1000/files/x", DL + "/sub/.Trash/x"):
            self.assertPlexOpsError(400, "bad-request",
                                    actions.action_delete_download,
                                    {"path": path, "dry_run": True})
        self.sudo.assert_not_called()

    def test_rejects_symlink_escape_via_realpath(self):
        self.sudo_realpath("/docker/plex/media/tv/Real.Target")
        e = self.assertPlexOpsError(400, "bad-request",
                                    actions.action_delete_download,
                                    {"path": TARGET, "dry_run": False})
        self.assertIn("symlink", e.message)
        self.assertEqual(e.detail["realpath"], "/docker/plex/media/tv/Real.Target")

    def test_rejects_symlink_into_trash_via_realpath(self):
        self.sudo_realpath(DL + "/.Trash-1000/files/x")
        self.assertPlexOpsError(400, "bad-request",
                                actions.action_delete_download,
                                {"path": TARGET, "dry_run": False})

    # --- existence / ownership re-verification (409) ---

    def test_missing_path_is_409(self):
        self.sudo.side_effect = RuntimeError("realpath: no such file")
        self.assertPlexOpsError(409, "verify-failed",
                                actions.action_delete_download,
                                {"path": TARGET, "dry_run": True})

    def test_qbit_owned_without_override_is_409(self):
        self.sudo_realpath(TARGET)
        self.qbit_hits.return_value = [{"hash": "abc123", "name": "torrent-x"}]
        e = self.assertPlexOpsError(409, "verify-failed",
                                    actions.action_delete_download,
                                    {"path": TARGET, "dry_run": True})
        self.assertEqual(e.detail["qbit_owner"],
                         {"hash": "abc123", "name": "torrent-x"})

    # --- dry_run and execute ---

    def test_dry_run_captures_state_and_deletes_nothing(self):
        calls = self.sudo_realpath(TARGET)
        self.samefile.return_value = [DL + "/twin.mkv"]
        res = actions.action_delete_download({"path": TARGET, "dry_run": True})
        self.assertDryShape(res, "delete-download")
        self.assertEqual(res["planned"], ["sudo rm -rf %s" % TARGET])
        self.assertEqual(res["before"], {
            "path": TARGET, "nlink": 1, "size_bytes": 1000, "blocks512": 2,
            "sparse": True, "samefile_hits": [DL + "/twin.mkv"],
            "qbit_checked": False, "qbit_owner": None,
        })
        self.assertEqual(calls, [["realpath", "-e", TARGET]])

    def test_dry_run_normalizes_trailing_slash(self):
        self.sudo_realpath(TARGET)
        res = actions.action_delete_download({"path": TARGET + "/",
                                              "dry_run": True})
        self.assertEqual(res["before"]["path"], TARGET)

    def test_execute_removes_and_verifies_gone(self):
        calls = self.sudo_realpath(TARGET, allow_rm=True)
        self.stat_file.side_effect = [dict(STAT), None]  # pre, post
        res = actions.action_delete_download({"path": TARGET,
                                              "allow_qbit_owned": False})
        self.assertTrue(any(_is_rm_cmd(c) for c in calls))
        self.assertEqual(res["performed"], res["planned"])
        self.assertEqual(res["after"], {"exists": False})
        self.assertTrue(res["verified"])

    def test_qbit_down_with_creds_refuses(self):
        # Creds configured but qbit unreachable: the ownership gate cannot
        # run, so the delete must refuse instead of proceeding gate-off.
        self.sudo_realpath(TARGET)
        self.patch_lib("Qbit", new=FakeQbitDown)
        self.qbit_hits.return_value = None
        e = self.assertPlexOpsError(502, "upstream-error",
                                    actions.action_delete_download,
                                    {"path": TARGET, "dry_run": True})
        self.assertEqual(e.detail["path"], TARGET)

    def test_qbit_down_with_creds_and_override_proceeds(self):
        self.sudo_realpath(TARGET, allow_rm=True)
        self.patch_lib("Qbit", new=FakeQbitDown)
        self.qbit_hits.return_value = None
        self.stat_file.side_effect = [dict(STAT), None]
        res = actions.action_delete_download({"path": TARGET,
                                              "allow_qbit_owned": True})
        self.assertFalse(res["before"]["qbit_checked"])
        self.assertTrue(res["verified"])

    def test_rm_reverify_failure_is_409(self):
        # The combined re-verify+rm invocation failing (e.g. a parent turned
        # into a symlink between check and delete) must 409, not 500.
        def fake(cmd, **kwargs):
            if cmd[:2] == ["realpath", "-e"]:
                return TARGET + "\n"
            if _is_rm_cmd(cmd):
                raise RuntimeError("command failed (1): sudo sh -c ...")
            raise AssertionError("unexpected sudo command: %r" % cmd)

        self.sudo.side_effect = fake
        self.assertPlexOpsError(409, "verify-failed",
                                actions.action_delete_download,
                                {"path": TARGET})

    def test_execute_qbit_owned_with_override_proceeds(self):
        self.sudo_realpath(TARGET, allow_rm=True)
        self.qbit_hits.return_value = [{"hash": "abc123", "name": "torrent-x"}]
        self.stat_file.side_effect = [dict(STAT), None]
        res = actions.action_delete_download({"path": TARGET,
                                              "allow_qbit_owned": True})
        self.assertEqual(res["before"]["qbit_owner"],
                         {"hash": "abc123", "name": "torrent-x"})
        self.assertTrue(res["verified"])

    def test_path_survives_rm_is_409(self):
        self.sudo_realpath(TARGET, allow_rm=True)
        self.stat_file.side_effect = [dict(STAT), dict(STAT)]
        self.assertPlexOpsError(409, "verify-failed",
                                actions.action_delete_download,
                                {"path": TARGET})


# ---------------------------------------------------------------------------
# shared plumbing invariants


class SharedHelperTests(unittest.TestCase):
    def test_queue_helpers_are_the_probe_implementations(self):
        # Guard against classifier/shape/pagination drift: actions must use
        # the exact plexops_lib objects the probes use (CONTRACT.md 3.1).
        self.assertIs(actions._queue_item_view, lib.queue_item_view)
        self.assertIs(actions._fetch_queue, lib.fetch_queue)
        self.assertIs(actions._host_path, lib.arr_host_path)

    def test_qbit_hits_under_both_directions(self):
        class FakeQbit(object):
            available = True

            def torrents(self):
                return [{"hash": "h1", "name": "TorrentX",
                         "host_content_path": lib.DOWNLOADS + "/TorrentX"}]

        qbit = FakeQbit()
        # Torrent content under the target (delete a parent dir).
        self.assertEqual(len(lib.qbit_hits_under(qbit, lib.DOWNLOADS + "/TorrentX")), 1)
        # Target INSIDE the torrent's content dir (delete one payload file).
        self.assertEqual(
            len(lib.qbit_hits_under(qbit, lib.DOWNLOADS + "/TorrentX/file.mkv")), 1)
        # Unrelated sibling: no hit.
        self.assertEqual(lib.qbit_hits_under(qbit, lib.DOWNLOADS + "/Other"), [])
        # Prefix-not-component: /TorrentXY is not owned by /TorrentX.
        self.assertEqual(lib.qbit_hits_under(qbit, lib.DOWNLOADS + "/TorrentXY"), [])


# ---------------------------------------------------------------------------
# whitelist surface


class WhitelistTests(OfflineTestCase):
    def test_actions_whitelist_matches_contract(self):
        self.assertEqual(sorted(actions.ACTIONS), [
            "delete-download", "fill-missing", "pull-recreate", "queue-remove",
            "reclaim-pause", "reclaim-pilot-ack", "reclaim-resume", "reclaim-schedule",
            "replace-file", "restart-prowlarr", "resurrect-stragglers", "search",
        ])
        for fn in actions.ACTIONS.values():
            self.assertTrue(callable(fn))

    def test_non_dict_body_is_400(self):
        for fn in actions.ACTIONS.values():
            self.assertPlexOpsError(400, "bad-request", fn, ["not", "a", "dict"])

    def test_dry_run_must_be_boolean(self):
        self.assertPlexOpsError(400, "bad-request",
                                actions.action_restart_prowlarr,
                                {"dry_run": "yes"})


if __name__ == "__main__":
    unittest.main()
