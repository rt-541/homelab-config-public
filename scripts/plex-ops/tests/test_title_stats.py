"""Offline unit tests for the title-stats probe and the Plex/Seerr helpers.

Run: python3 -m unittest discover -s scripts/plex-ops/tests -v
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import plexops_lib as lib  # noqa: E402
import probes  # noqa: E402

SERIES = {"id": 3, "title": "3 Body Problem", "year": 2024, "monitored": True, "added": "2024-03-21T00:00:00Z",
          "tvdbId": 411959, "tmdbId": 108545, "imdbId": "tt13016388",
          "statistics": {"seasonCount": 1, "episodeFileCount": 8, "episodeCount": 8,
                         "totalEpisodeCount": 16, "sizeOnDisk": 67819332029, "percentOfEpisodes": 100}}
MOVIE = {"id": 742, "title": "Inception", "year": 2010, "monitored": True, "added": "2025-04-18T00:00:00Z",
         "tmdbId": 27205, "imdbId": "tt1375666", "hasFile": True, "sizeOnDisk": 85436578297,
         "movieFile": {"path": "/data/movies/Inception (2010)/x.mkv",
                       "quality": {"quality": {"name": "Remux-2160p"}}}}
SECTIONS = {"Directory": [{"key": "1", "type": "movie", "title": "Movies"},
                          {"key": "2", "type": "show", "title": "TV Shows"}]}
ACCOUNTS = {"Account": [{"id": 1, "name": "rt541"}, {"id": 42, "name": "Grayson"}, {"id": 7, "name": ""}]}
SHOW_ITEMS = {"Metadata": [
    {"ratingKey": "500", "title": "3 Body Problem", "year": 2024, "addedAt": 1711000000,
     "Guid": [{"id": "tvdb://411959"}, {"id": "tmdb://108545"}]},
    {"ratingKey": "501", "title": "3 Body Problem Making Of", "year": 2024, "Guid": [{"id": "tvdb://1"}]}]}
HISTORY_TV = {"totalSize": 5, "Metadata": [
    {"type": "episode", "accountID": 1, "viewedAt": 1789000000, "ratingKey": "510", "grandparentKey": "/library/metadata/500"},
    {"type": "episode", "accountID": 1, "viewedAt": 1789003600, "ratingKey": "511", "grandparentKey": "/library/metadata/500"},
    {"type": "episode", "accountID": 42, "viewedAt": 1789100000, "ratingKey": "510", "grandparentKey": "/library/metadata/500"},
    {"type": "episode", "accountID": 7, "viewedAt": 1789200000, "ratingKey": "600", "grandparentKey": "/library/metadata/501"},
    {"type": "episode", "accountID": 42, "viewedAt": 1789300000, "ratingKey": "512", "grandparentKey": "/library/metadata/500"},
]}
SEERR_TV = {"mediaInfo": {"requests": [
    {"status": 2, "createdAt": "2024-03-20T10:00:00.000Z", "is4k": False,
     "requestedBy": {"displayName": "aschu9", "plexUsername": "aschu9", "email": "a@x"}}]}}


class TitleStatsTests(unittest.TestCase):
    def setUp(self):
        lib._plex_cache.clear()
        self.addCleanup(lib._plex_cache.clear)
        for target in ("plexops_lib.subprocess.run", "plexops_lib.urllib.request.urlopen"):
            p = mock.patch(target, side_effect=AssertionError("network/subprocess in test"))
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(lib, "read_env", return_value={"PLEX_TOKEN": "t", "SEERR_API_KEY": "k"})
        p.start()
        self.addCleanup(p.stop)
        self.arr_get = mock.patch.object(lib, "arr_get", side_effect=self._arr_get).start()
        self.addCleanup(mock.patch.stopall)
        self.http = mock.patch.object(lib, "http_json", side_effect=self._http).start()
        self.seerr_resp = (200, SEERR_TV)

    def _arr_get(self, app, path, params=None):
        if path == "/api/v3/series":
            return [SERIES]
        if path == "/api/v3/series/3":
            return SERIES
        if path == "/api/v3/movie":
            return [MOVIE]
        if path == "/api/v3/movie/742":
            return MOVIE
        raise AssertionError(path)

    def _http(self, url, method="GET", headers=None, body=None, timeout=60):
        if "/library/sections/2/all" in url:
            return 200, {"MediaContainer": SHOW_ITEMS}
        if "/library/sections/1/all" in url:
            return 200, {"MediaContainer": {"Metadata": [
                {"ratingKey": "26610", "title": "Inception", "year": 2010, "Guid": [{"id": "tmdb://27205"}]}]}}
        if url.endswith("/library/sections"):
            return 200, {"MediaContainer": SECTIONS}
        if url.endswith("/accounts"):
            return 200, {"MediaContainer": ACCOUNTS}
        if "/status/sessions/history/all" in url and "librarySectionID=2" in url:
            return 200, {"MediaContainer": HISTORY_TV}
        if "/status/sessions/history/all" in url:
            return 200, {"MediaContainer": {"totalSize": 1, "Metadata": [
                {"type": "movie", "accountID": 1, "viewedAt": 1789000000, "ratingKey": "26610"}]}}
        if "/api/v1/tv/108545" in url or "/api/v1/movie/27205" in url:
            return self.seerr_resp
        raise AssertionError(url)

    def test_show_counts_distinct_watchers_not_episode_plays(self):
        r = probes.probe_title_stats({"app": "sonarr", "q": "3 body problem"})
        self.assertTrue(r["resolved"])
        self.assertEqual(r["ids"]["tvdb"], 411959)
        self.assertEqual(r["size"]["on_disk_gb"], 63.2)
        self.assertEqual(r["size"]["files"], 8)
        px = r["plex"]
        self.assertEqual(px["rating_key"], "500")          # matched by tvdb guid, not the "Making Of"
        self.assertEqual(px["watchers"], 2)                # rt541 + Grayson; account 7 watched another show
        self.assertEqual(px["plays"], 4)
        self.assertEqual([u["name"] for u in px["users"]], ["rt541", "Grayson"])
        self.assertEqual(px["users"][1]["distinct_items"], 2)
        self.assertIsNotNone(px["last_watched"])
        self.assertEqual(r["requests"], [{"by": "aschu9", "email": "a@x", "date": "2024-03-20",
                                          "status": "approved", "is4k": False}])

    def test_movie_by_id_with_no_seerr_record(self):
        self.seerr_resp = (404, None)
        r = probes.probe_title_stats({"app": "radarr", "id": "742"})
        self.assertEqual(r["title"], "Inception")
        self.assertEqual(r["size"]["quality"], "Remux-2160p")
        self.assertEqual(r["plex"]["watchers"], 1)
        self.assertIsNone(r["requests"])
        self.assertTrue(any("no request record" in n for n in r["notes"]))

    def test_ambiguous_title_returns_matches_only(self):
        with mock.patch.object(probes, "probe_lookup",
                               return_value={"resolved_id": None, "matches": [{"id": 1}, {"id": 2}]}):
            r = probes.probe_title_stats({"app": "sonarr", "q": "the"})
        self.assertFalse(r["resolved"])
        self.assertEqual(len(r["matches"]), 2)
        self.arr_get.assert_not_called()

    def test_plex_unavailable_is_a_note_not_an_error(self):
        with mock.patch.object(lib, "read_env", return_value={"SEERR_API_KEY": "k"}):
            r = probes.probe_title_stats({"app": "radarr", "id": "742"})
        self.assertIsNone(r["plex"])
        self.assertTrue(any("plex unavailable" in n for n in r["notes"]))
        self.assertIsNotNone(r["requests"])

    def test_bad_params(self):
        for p in ({"q": "x"}, {"app": "sonarr"}, {"app": "radarr", "id": "x"}):
            with self.assertRaises(lib.PlexOpsError) as cm:
                probes.probe_title_stats(p)
            self.assertEqual(cm.exception.status, 400)

    def test_history_is_paged_and_cached(self):
        calls = {"n": 0}
        orig = self._http

        def paged(url, **kw):
            if "/status/sessions/history/all" in url and "librarySectionID=2" in url:
                calls["n"] += 1
                start = int(url.split("X-Plex-Container-Start=")[1].split("&")[0])
                rows = HISTORY_TV["Metadata"][start:start + 2]
                return 200, {"MediaContainer": {"totalSize": 5, "Metadata": rows}}
            return orig(url, **kw)
        self.http.side_effect = paged
        with mock.patch.object(lib, "PLEX_HISTORY_PAGE", 2):
            rows = lib.plex_history("2")
            rows2 = lib.plex_history("2")
        self.assertEqual(len(rows), 5)
        self.assertIs(rows, rows2)
        self.assertEqual(calls["n"], 3)


if __name__ == "__main__":
    unittest.main()
