"""Offline unit tests for the help-desk surfaces: the lookup probe and the
replace-file / fill-missing actions. Same offline guard as test_actions.py.

Run: python3 -m unittest discover -s scripts/plex-ops/tests -v
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import plexops_lib as lib  # noqa: E402
import actions  # noqa: E402
import probes  # noqa: E402
from test_actions import OfflineTestCase  # noqa: E402

Q = {"quality": {"name": "WEBDL-1080p"}}
EP = {"id": 200, "seriesId": 10, "seasonNumber": 3, "episodeNumber": 5, "title": "Ep",
      "airDate": "2024-01-01", "hasFile": True, "monitored": True, "episodeFileId": 900,
      "episodeFile": {"id": 900, "path": "/data/tv/Show/S03E05.mkv", "size": 123,
                      "quality": Q}}
EP_NOFILE = dict(EP, hasFile=False, episodeFileId=0, episodeFile=None, monitored=False)
MOVIE = {"id": 7, "title": "A Movie", "year": 2020, "hasFile": True, "monitored": True,
         "movieFile": {"id": 77, "path": "/data/movies/A Movie (2020)/a.mkv", "size": 5,
                       "quality": Q}}
MOVIE_NOFILE = dict(MOVIE, hasFile=False, movieFile=None, monitored=False)
HIST = {"page": 1, "records": [
    {"id": 50, "eventType": "grabbed", "sourceTitle": "Show.S03E05.OLD-GRP", "downloadId": "OLD",
     "date": "2026-01-01T00:00:00Z"},
    {"id": 54, "eventType": "grabbed", "sourceTitle": "Show.S03E05.BAD-GRP", "downloadId": "BAD",
     "date": "2026-08-31T00:00:00Z"},
    {"id": 55, "eventType": "downloadFolderImported", "sourceTitle": "S03E05_file", "downloadId": "BAD",
     "date": "2026-09-01T00:00:00Z"},
    {"id": 56, "eventType": "episodeFileRenamed", "sourceTitle": "x",
     "date": "2026-09-02T00:00:00Z"},
    # A later grab that never imported must NOT be the one blocklisted.
    {"id": 57, "eventType": "grabbed", "sourceTitle": "Show.S03E05.NEVER-IMPORTED", "downloadId": "NEW",
     "date": "2026-09-03T00:00:00Z"},
]}


class ItemActionCase(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.arr_call = self.patch_lib("arr_call")
        self.patch_lib("arr_key", return_value="k")
        self.http_json = self.patch_lib("http_json")
        self.arr_get = self.patch_lib("arr_get")

    def command_ok(self, cid=9):
        def _call(app, method, path, params=None, body=None, timeout=120):
            if method == "POST" and path == "/api/v3/command":
                return {"id": cid, "status": "queued"}
            return None
        self.arr_call.side_effect = _call

    def calls(self):
        return [(c.args[0], c.args[1], c.args[2]) for c in self.arr_call.call_args_list]


# ---------------------------------------------------------------------------
# replace-file


class ReplaceFileTests(ItemActionCase):
    def test_bad_bodies_are_400(self):
        for body in [{"app": "sonarr"}, {"app": "sonarr", "movie_id": 1},
                     {"app": "radarr", "episode_id": 1}, {"app": "sonarr", "episode_id": "x"},
                     {"app": "prowlarr", "episode_id": 1},
                     {"app": "sonarr", "episode_id": 1, "blocklist": "yes"}]:
            body["dry_run"] = True
            self.assertPlexOpsError(400, "bad-request", actions.action_replace_file, body)
        self.http_json.assert_not_called()

    def test_missing_item_is_409(self):
        self.http_json.return_value = (404, None)
        e = self.assertPlexOpsError(409, "verify-failed", actions.action_replace_file,
                                    {"app": "sonarr", "episode_id": 200, "dry_run": True})
        self.assertEqual(e.detail["missing_ids"], [200])

    def test_item_without_file_is_409(self):
        self.http_json.return_value = (200, EP_NOFILE)
        e = self.assertPlexOpsError(409, "verify-failed", actions.action_replace_file,
                                    {"app": "sonarr", "episode_id": 200, "dry_run": True})
        self.assertFalse(e.detail["has_file"])
        self.arr_call.assert_not_called()

    def test_dry_run_sonarr_plans_blocklist_delete_search(self):
        self.http_json.return_value = (200, EP)
        self.arr_get.return_value = HIST
        res = actions.action_replace_file({"app": "sonarr", "episode_id": 200, "dry_run": True})
        self.assertDryShape(res, "replace-file")
        self.assertEqual(res["before"]["file"]["id"], 900)
        self.assertEqual(res["before"]["file"]["path"], "/docker/plex/media/tv/Show/S03E05.mkv")
        # The grab that produced the imported file (downloadId BAD), not the
        # rename, not the older grab, not the later never-imported grab.
        self.assertEqual(res["before"]["history_id"], 54)
        self.assertEqual(res["before"]["source_title"], "Show.S03E05.BAD-GRP")
        self.assertEqual(len(res["planned"]), 3)
        self.assertIn("history/failed/54", res["planned"][0])
        self.assertIn("DELETE sonarr /api/v3/episodefile/900", res["planned"][1])
        self.assertIn("EpisodeSearch", res["planned"][2])
        self.arr_call.assert_not_called()
        self.arr_get.assert_called_once()
        self.assertEqual(self.arr_get.call_args.args[1], "/api/v3/history")

    def test_execute_sonarr(self):
        self.http_json.side_effect = [(200, EP), (200, EP_NOFILE)]
        self.arr_get.return_value = HIST
        self.command_ok(9)
        res = actions.action_replace_file({"app": "sonarr", "episode_id": 200})
        self.assertEqual(self.calls(), [
            ("sonarr", "POST", "/api/v3/history/failed/54"),
            ("sonarr", "DELETE", "/api/v3/episodefile/900"),
            ("sonarr", "POST", "/api/v3/command"),
        ])
        self.assertEqual(res["after"], {"has_file": False, "blocklisted": True,
                                        "command_id": 9, "command_state": "queued"})
        self.assertEqual(res["planned"], res["performed"])
        self.assertTrue(res["verified"])

    def test_execute_radarr_without_history_skips_blocklist(self):
        self.http_json.side_effect = [(200, MOVIE), (200, MOVIE_NOFILE)]
        self.arr_get.return_value = []
        self.command_ok(3)
        res = actions.action_replace_file({"app": "radarr", "movie_id": 7})
        self.assertIn("blocklist skipped", res["planned"][0])
        self.assertEqual(self.calls(), [
            ("radarr", "DELETE", "/api/v3/moviefile/77"),
            ("radarr", "POST", "/api/v3/command"),
        ])
        self.assertEqual(self.arr_call.call_args_list[1].kwargs["body"],
                         {"name": "MoviesSearch", "movieIds": [7]})
        self.assertFalse(res["after"]["blocklisted"])
        self.assertEqual(self.arr_get.call_args.args[1], "/api/v3/history/movie")

    def test_blocklist_false_never_reads_history(self):
        self.http_json.return_value = (200, EP)
        res = actions.action_replace_file(
            {"app": "sonarr", "episode_id": 200, "blocklist": False, "dry_run": True})
        self.assertEqual(len(res["planned"]), 2)
        self.arr_get.assert_not_called()

    def test_file_still_present_after_delete_is_409(self):
        self.http_json.side_effect = [(200, EP), (200, EP)]
        self.arr_get.return_value = HIST
        self.command_ok()
        e = self.assertPlexOpsError(409, "verify-failed", actions.action_replace_file,
                                    {"app": "sonarr", "episode_id": 200})
        self.assertEqual(len(e.detail["performed"]), 2)
        self.assertNotIn(("sonarr", "POST", "/api/v3/command"), self.calls())

    def test_history_fallbacks(self):
        imp_only = {"records": [{"id": 5, "eventType": "downloadFolderImported",
                                 "sourceTitle": "f", "downloadId": "Z", "date": "2026-01-01"}]}
        grab_only = {"records": [{"id": 6, "eventType": "grabbed", "sourceTitle": "g",
                                  "downloadId": "Z", "date": "2026-01-01"}]}
        self.arr_get.return_value = imp_only
        self.assertEqual(actions._latest_grab_history("sonarr", "episode", 1), (5, "f"))
        self.arr_get.return_value = grab_only
        self.assertEqual(actions._latest_grab_history("sonarr", "episode", 1), (6, "g"))
        self.arr_get.return_value = {"records": []}
        self.assertEqual(actions._latest_grab_history("sonarr", "episode", 1), (None, None))

    def test_file_fetched_separately_when_not_embedded(self):
        rec = dict(EP, episodeFile=None)
        self.http_json.side_effect = [(200, rec), (200, {"id": 900, "path": "/data/tv/f.mkv",
                                                         "size": 1, "quality": Q})]
        self.arr_get.return_value = HIST
        res = actions.action_replace_file({"app": "sonarr", "episode_id": 200, "dry_run": True})
        self.assertEqual(res["before"]["file"]["path"], "/docker/plex/media/tv/f.mkv")
        self.assertEqual(self.http_json.call_args.args[0],
                         lib.ARR["sonarr"]["url"] + "/api/v3/episodefile/900")


# ---------------------------------------------------------------------------
# fill-missing


class FillMissingTests(ItemActionCase):
    def test_already_has_file_is_409(self):
        self.http_json.return_value = (200, EP)
        e = self.assertPlexOpsError(409, "verify-failed", actions.action_fill_missing,
                                    {"app": "sonarr", "episode_id": 200, "dry_run": True})
        self.assertTrue(e.detail["has_file"])
        self.assertEqual(e.detail["file"]["id"], 900)

    def test_dry_run_unmonitored_plans_monitor_then_search(self):
        self.http_json.return_value = (200, EP_NOFILE)
        res = actions.action_fill_missing({"app": "sonarr", "episode_id": 200, "dry_run": True})
        self.assertDryShape(res, "fill-missing")
        self.assertFalse(res["before"]["monitored"])
        self.assertEqual(len(res["planned"]), 2)
        self.assertIn("episode/monitor", res["planned"][0])
        self.assertIn("EpisodeSearch", res["planned"][1])

    def test_dry_run_monitored_plans_search_only(self):
        self.http_json.return_value = (200, dict(EP_NOFILE, monitored=True))
        res = actions.action_fill_missing({"app": "sonarr", "episode_id": 200, "dry_run": True})
        self.assertEqual(len(res["planned"]), 1)

    def test_monitor_false_skips_monitoring(self):
        self.http_json.return_value = (200, EP_NOFILE)
        res = actions.action_fill_missing(
            {"app": "sonarr", "episode_id": 200, "monitor": False, "dry_run": True})
        self.assertEqual(len(res["planned"]), 1)

    def test_execute_sonarr_monitor_then_search(self):
        self.http_json.side_effect = [(200, EP_NOFILE), (200, dict(EP_NOFILE, monitored=True))]
        self.command_ok(11)
        res = actions.action_fill_missing({"app": "sonarr", "episode_id": 200})
        self.assertEqual(self.calls(), [("sonarr", "PUT", "/api/v3/episode/monitor"),
                                        ("sonarr", "POST", "/api/v3/command")])
        self.assertEqual(self.arr_call.call_args_list[0].kwargs["body"],
                         {"episodeIds": [200], "monitored": True})
        self.assertEqual(res["after"], {"monitored": True, "command_id": 11,
                                        "command_state": "queued"})

    def test_execute_radarr_puts_full_movie_object(self):
        self.http_json.side_effect = [(200, MOVIE_NOFILE), (200, dict(MOVIE_NOFILE, monitored=True))]
        self.command_ok(12)
        actions.action_fill_missing({"app": "radarr", "movie_id": 7})
        put = self.arr_call.call_args_list[0]
        self.assertEqual((put.args[1], put.args[2]), ("PUT", "/api/v3/movie/7"))
        self.assertTrue(put.kwargs["body"]["monitored"])
        self.assertEqual(put.kwargs["body"]["id"], 7)

    def test_monitor_not_applied_is_409(self):
        self.http_json.side_effect = [(200, EP_NOFILE), (200, EP_NOFILE)]
        self.command_ok()
        self.assertPlexOpsError(409, "verify-failed", actions.action_fill_missing,
                                {"app": "sonarr", "episode_id": 200})
        self.assertNotIn(("sonarr", "POST", "/api/v3/command"), self.calls())


# ---------------------------------------------------------------------------
# lookup probe


SERIES = [
    {"id": 10, "title": "The Show", "year": 2019, "monitored": True, "status": "continuing",
     "path": "/data/tv/The Show", "alternateTitles": [{"title": "Show, The"}],
     "statistics": {"episodeFileCount": 20, "episodeCount": 22},
     "seasons": [{"seasonNumber": 3, "monitored": True,
                  "statistics": {"episodeFileCount": 9, "totalEpisodeCount": 10}}]},
    {"id": 11, "title": "The Show Next Door", "year": 2021, "monitored": False,
     "status": "ended", "path": "/data/tv/The Show Next Door"},
    {"id": 12, "title": "Unrelated Thing", "year": 2000},
]
EPISODES = [
    {"id": 305, "seasonNumber": 3, "episodeNumber": 5, "title": "five", "airDate": "2021-02-01",
     "hasFile": False, "monitored": True},
    {"id": 301, "seasonNumber": 3, "episodeNumber": 1, "title": "one", "airDate": "2021-01-01",
     "hasFile": True, "monitored": True,
     "episodeFile": {"id": 1, "path": "/data/tv/x.mkv", "size": 1,
                     "quality": {"quality": {"name": "HDTV-720p"}}}},
]
MOVIES = [dict(MOVIE, alternateTitles=[]), {"id": 8, "title": "Another Movie", "year": 1999,
                                            "hasFile": False, "monitored": True},
          # Real-world trap: a one-letter foreign alias on an unrelated title.
          {"id": 9, "title": "Wicked", "year": 2024, "hasFile": True, "monitored": True,
           "alternateTitles": [{"title": "I"}, {"title": "A M"}]}]


class LookupProbeTests(unittest.TestCase):
    def setUp(self):
        self.ep_params = None

        def _arr_get(app, path, params=None):
            if path == "/api/v3/series":
                return SERIES
            if path == "/api/v3/movie":
                return MOVIES
            if path == "/api/v3/episode":
                self.ep_params = params
                return EPISODES
            raise AssertionError("unexpected GET %s %s" % (app, path))
        p = mock.patch.object(lib, "arr_get", side_effect=_arr_get)
        p.start()
        self.addCleanup(p.stop)

    def bad(self, params):
        with self.assertRaises(lib.PlexOpsError) as cm:
            probes.probe_lookup(params)
        self.assertEqual(cm.exception.status, 400)

    def test_bad_params(self):
        self.bad({"q": "x"})
        self.bad({"app": "sonarr"})
        self.bad({"app": "sonarr", "q": "x", "episode": "2"})
        self.bad({"app": "radarr", "q": "x", "season": "1"})
        self.bad({"app": "sonarr", "q": "x", "season": "one"})

    def test_exact_match_resolves_and_ranks(self):
        res = probes.probe_lookup({"app": "sonarr", "q": "the show"})
        self.assertEqual([m["id"] for m in res["matches"]], [10, 11])
        self.assertEqual(res["matches"][0]["score"], 100)
        self.assertEqual(res["matches"][1]["score"], 90)
        self.assertEqual(res["resolved_id"], 10)
        self.assertIsNone(res["episodes"])
        self.assertEqual(res["matches"][0]["path"], "/docker/plex/media/tv/The Show")
        self.assertEqual(res["matches"][0]["seasons"][0]["episode_file_count"], 9)

    def test_alternate_title_matches(self):
        res = probes.probe_lookup({"app": "sonarr", "q": "Show, The"})
        self.assertEqual(res["resolved_id"], 10)

    def test_tie_does_not_resolve(self):
        res = probes.probe_lookup({"app": "sonarr", "q": "the"})
        self.assertEqual(len(res["matches"]), 2)
        self.assertIsNone(res["resolved_id"])

    def test_no_match_is_empty(self):
        res = probes.probe_lookup({"app": "sonarr", "q": "zzz qqq"})
        self.assertEqual(res["matches"], [])
        self.assertIsNone(res["resolved_id"])

    def test_season_fetches_episodes_sorted(self):
        res = probes.probe_lookup({"app": "sonarr", "q": "the show", "season": "3"})
        self.assertEqual(self.ep_params, {"seriesId": 10, "seasonNumber": 3,
                                          "includeEpisodeFile": "true"})
        self.assertEqual([e["episode"] for e in res["episodes"]], [1, 5])
        self.assertEqual(res["episodes"][0]["file"]["path"], "/docker/plex/media/tv/x.mkv")
        self.assertIsNone(res["episodes"][1]["file"])

    def test_episode_filters_to_one(self):
        res = probes.probe_lookup({"app": "sonarr", "q": "the show", "season": "3",
                                   "episode": "5"})
        self.assertEqual(len(res["episodes"]), 1)
        self.assertEqual(res["episodes"][0]["id"], 305)
        self.assertFalse(res["episodes"][0]["has_file"])

    def test_unresolved_series_gets_no_episodes(self):
        res = probes.probe_lookup({"app": "sonarr", "q": "the", "season": "3"})
        self.assertIsNone(res["episodes"])
        self.assertIsNone(self.ep_params)

    def test_short_alias_does_not_match(self):
        res = probes.probe_lookup({"app": "radarr", "q": "a movie"})
        self.assertNotIn(9, [m["id"] for m in res["matches"]])
        res = probes.probe_lookup({"app": "radarr", "q": "inception"})
        self.assertEqual(res["matches"], [])

    def test_radarr_match_has_file_view(self):
        res = probes.probe_lookup({"app": "radarr", "q": "a movie"})
        self.assertEqual(res["resolved_id"], 7)
        m = res["matches"][0]
        self.assertTrue(m["has_file"])
        self.assertEqual(m["file"]["quality"], "WEBDL-1080p")
        self.assertEqual(m["file"]["path"], "/docker/plex/media/movies/A Movie (2020)/a.mkv")


if __name__ == "__main__":
    unittest.main()
