"""Offline unit tests for the compression-wave surfaces: window math,
reclaim-status / reclaim-plan probes, reclaim-schedule and the flag actions.
All filesystem state lives in a temp dir; sudo/subprocess/network are guarded.

Run: python3 -m unittest discover -s scripts/plex-ops/tests -v
"""

import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import plexops_lib as lib  # noqa: E402
import actions  # noqa: E402
import probes  # noqa: E402
from test_actions import OfflineTestCase  # noqa: E402

WINDOWS = "daily 22:30-06:30; Mon-Fri 08:30-16:30"
HEADER = ["action", "title", "mount", "size_gb", "videos", "res", "src", "codec", "flags",
          "nlink", "est_target_gb", "est_savings_gb", "then_transcode", "primary_path", "SKIP"]


def row(title, size_gb, action="transcode", skip="", mount="media"):
    tgt = min(25.0, max(15.0, size_gb * 0.28))
    return [action, title, mount, "%.1f" % size_gb, "1", "2160p", "remux", "hevc", "-", "1",
            "%.0f" % tgt, "%.1f" % (size_gb - tgt), "",
            "/docker/plex/%s/movies/%s/%s.mkv" % (mount, title, title), skip]


CANDIDATES = [
    row("Forrest Gump (1994)", 87.3),
    row("Oppenheimer (2023)", 82.2),
    row("Inception (2010)", 79.6),
    row("Parasite (2019)", 76.2),
    row("Tenet (2020)", 55.0),
    row("Small Film (2001)", 33.0),
    row("Tiny Film (2002)", 31.0),
    row("Dune (2021)", 70.0),                      # keep-list: must never appear
    row("Skipped Film (2003)", 60.0, skip="x"),
    row("Some Dupe (2004)", 60.0, action="delete-dupe"),
]


class ReclaimFixture(OfflineTestCase):
    """Temp .reclaim/ state + a scan report + policy/keep-list files."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        state = os.path.join(self.tmp, "reclaim")
        os.makedirs(os.path.join(state, "queue"))
        logs = os.path.join(self.tmp, "logs")
        rep = os.path.join(logs, "2026-09-14_001617")
        os.makedirs(rep)
        with open(os.path.join(rep, "candidates_movies.tsv"), "w") as fh:
            fh.write("\t".join(HEADER) + "\n")
            for r in CANDIDATES:
                fh.write("\t".join(r) + "\n")
        pol = os.path.join(self.tmp, "policy.conf")
        with open(pol, "w") as fh:
            fh.write('WINDOWS="%s"\nPILOT_LIMIT=3\n' % WINDOWS)
        keep = os.path.join(self.tmp, "keep-list.conf")
        with open(keep, "w") as fh:
            fh.write("# keep\ndune (2021)\nalien (1979)\n")
        self.paths = {
            "RECLAIM_STATE": state,
            "RECLAIM_QUEUE": os.path.join(state, "queue", "queue.tsv"),
            "RECLAIM_DONE": os.path.join(state, "done.list"),
            "RECLAIM_FAILED": os.path.join(state, "failed.list"),
            "RECLAIM_LEDGER": os.path.join(state, "ledger.tsv"),
            "RECLAIM_STATUS_MD": os.path.join(state, "status.md"),
            "RECLAIM_PAUSE": os.path.join(state, "PAUSE"),
            "RECLAIM_PILOT_ACK": os.path.join(state, "PILOT_ACK"),
            "RECLAIM_LOG": logs,
            "RECLAIM_DF_LOG": os.path.join(logs, "df-checkpoints.log"),
            "RECLAIM_KEEP_LIST": keep,
            "TRANSCODE_POLICY": pol,
        }
        for k, v in self.paths.items():
            p = mock.patch.object(lib, k, v)
            p.start()
            self.addCleanup(p.stop)
        # the flag actions were bound at import time; re-point them at the temp files
        for name, path, want in (("reclaim-pause", self.paths["RECLAIM_PAUSE"], True),
                                 ("reclaim-resume", self.paths["RECLAIM_PAUSE"], False),
                                 ("reclaim-pilot-ack", self.paths["RECLAIM_PILOT_ACK"], True)):
            p = mock.patch.dict(actions.ACTIONS, {name: actions._flag_action(name, path, want)})
            p.start()
            self.addCleanup(p.stop)
        self.now = datetime(2026, 9, 13, 20, 0)  # Sunday 20:00

    def write(self, key, text):
        with open(self.paths[key], "w") as fh:
            fh.write(text)


# ---------------------------------------------------------------------------
# window math


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.wins = lib.reclaim_windows({"WINDOWS": WINDOWS})

    def test_parse(self):
        self.assertEqual([(w["days"], w["start_min"], w["end_min"], w["overnight"]) for w in self.wins],
                         [("daily", 1350, 390, True), ("Mon-Fri", 510, 990, False)])

    def test_state_inside_overnight_window_after_midnight(self):
        st = lib.reclaim_window_state(datetime(2026, 9, 14, 0, 20), self.wins)   # Mon 00:20
        self.assertTrue(st["in_window"])
        self.assertEqual(st["current"]["end"], "2026-09-14T06:30")
        self.assertAlmostEqual(st["current"]["remaining_hours"], 6.17, places=2)
        self.assertEqual(st["next"]["start"], "2026-09-14T08:30")

    def test_state_sunday_evening(self):
        st = lib.reclaim_window_state(datetime(2026, 9, 13, 20, 0), self.wins)   # Sun 20:00
        self.assertFalse(st["in_window"])
        self.assertEqual(st["next"]["start"], "2026-09-13T22:30")
        self.assertEqual(st["next"]["hours"], 8.0)

    def test_no_workday_window_on_weekend(self):
        occ = lib.reclaim_window_occurrences(datetime(2026, 9, 12, 12, 0), self.wins, days=(0,))
        self.assertEqual([o["days"] for o in occ], ["daily"])                      # Saturday

    def test_pick_tonight_and_workday(self):
        o, budget = lib.reclaim_pick_window("tonight", datetime(2026, 9, 13, 20, 0), self.wins)
        self.assertEqual((o["start"].isoformat(timespec="minutes"), budget), ("2026-09-13T22:30", 8.0))
        o, budget = lib.reclaim_pick_window("tonight", datetime(2026, 9, 14, 0, 20), self.wins)
        self.assertEqual(o["start"].isoformat(timespec="minutes"), "2026-09-13T22:30")
        self.assertAlmostEqual(budget, 6.17, places=2)
        o, budget = lib.reclaim_pick_window("workday", datetime(2026, 9, 13, 20, 0), self.wins)
        self.assertEqual((o["start"].isoformat(timespec="minutes"), budget), ("2026-09-14T08:30", 8.0))
        o, _ = lib.reclaim_pick_window("next", datetime(2026, 9, 14, 9, 0), self.wins)
        self.assertEqual(o["days"], "Mon-Fri")

    def test_band(self):
        self.assertEqual([lib.size_band(x) for x in (87.3, 60.0, 59.9, 40.0, 39.9)],
                         ["large", "large", "medium", "medium", "small"])


# ---------------------------------------------------------------------------
# reclaim-plan probe


class PlanTests(ReclaimFixture):
    def plan(self, **kw):
        kw.setdefault("now", self.now)
        return probes.reclaim_plan(kw.pop("window", "tonight"), kw.pop("hours", None),
                                   kw.pop("limit", None), kw.pop("refresh", False), now=kw["now"])

    def test_tonight_fills_eight_hours_largest_gain_first(self):
        p = self.plan()
        # 60 GiB/h -> 87.3 + 82.2 + 79.6 + 76.2 + 55.0 = 380.3 GiB = 6.34 h; + 33 = 6.89 h; + 31 = 7.4 h
        self.assertEqual([s["title"] for s in p["selected"]],
                         ["Forrest Gump (1994)", "Oppenheimer (2023)", "Inception (2010)",
                          "Parasite (2019)", "Tenet (2020)", "Small Film (2001)", "Tiny Film (2002)"])
        self.assertEqual(p["counts"], {"large": 4, "medium": 1, "small": 2, "total": 7})
        self.assertAlmostEqual(p["est_hours"], 7.4, places=1)
        self.assertEqual(p["window"]["budget_hours"], 8.0)
        self.assertEqual(p["window"]["start"], "2026-09-13T22:30")
        self.assertGreater(p["est_gain_gb"], 280)
        self.assertEqual(p["remaining_candidates"], 7)
        self.assertIn("pilot gate", p["notes"][0])

    def test_keep_list_skip_and_non_transcode_rows_are_excluded(self):
        titles = [s["title"] for s in self.plan(hours=100)["selected"]]
        for t in ("Dune (2021)", "Skipped Film (2003)", "Some Dupe (2004)"):
            self.assertNotIn(t, titles)

    def test_hours_override_and_limit(self):
        p = self.plan(hours=2.0)
        # 87 min for Forrest Gump; the next four do not fit, the 33 GiB one does (120 min exactly)
        self.assertEqual([s["title"] for s in p["selected"]],
                         ["Forrest Gump (1994)", "Small Film (2001)"])
        p = self.plan(limit=2)
        self.assertEqual(p["counts"]["total"], 2)

    def test_done_and_failed_are_excluded_and_queued_is_flagged(self):
        self.write("RECLAIM_DONE", "media/movies/Forrest Gump (1994)/Forrest Gump (1994).mkv\n")
        self.write("RECLAIM_FAILED", "media/movies/Oppenheimer (2023)/Oppenheimer (2023).mkv\tffmpeg-rc=1\n")
        self.write("RECLAIM_QUEUE", "rel_path\tsize_bytes\test_target_gb\ttitle\n"
                   "media/movies/Inception (2010)/Inception (2010).mkv\t1\t22\tInception (2010)\n")
        p = self.plan()
        titles = [s["title"] for s in p["selected"]]
        self.assertNotIn("Forrest Gump (1994)", titles)
        self.assertNotIn("Oppenheimer (2023)", titles)
        self.assertEqual(p["already_queued"], 1)
        self.assertTrue(next(s for s in p["selected"] if s["title"] == "Inception (2010)")["queued"])

    def test_paused_note(self):
        self.write("RECLAIM_PAUSE", "")
        self.assertIn("PAUSED", self.plan()["notes"][0])

    def test_bad_params(self):
        for params in ({"window": "someday"}, {"hours": "x"}, {"hours": "0"}, {"limit": "z"}):
            with self.assertRaises(lib.PlexOpsError) as cm:
                probes.probe_reclaim_plan(params)
            self.assertEqual(cm.exception.status, 400)

    def test_refresh_runs_the_scan(self):
        with mock.patch.object(lib, "run") as run:
            probes.probe_reclaim_plan({"refresh": "true"})
        self.assertIn("scan_candidates.py", run.call_args.args[0][1])

    def test_no_report_triggers_scan(self):
        os.rename(os.path.join(self.paths["RECLAIM_LOG"], "2026-09-14_001617"),
                  os.path.join(self.paths["RECLAIM_LOG"], "old"))
        with mock.patch.object(lib, "run") as run:
            with self.assertRaises(lib.PlexOpsError) as cm:    # scan mocked -> still no report
                probes.probe_reclaim_plan({})
        run.assert_called_once()
        self.assertEqual(cm.exception.status, 502)


# ---------------------------------------------------------------------------
# reclaim-status probe


class StatusTests(ReclaimFixture):
    def test_status_shape(self):
        self.write("RECLAIM_QUEUE", "rel_path\tsize_bytes\test_target_gb\ttitle\n"
                   "media/movies/A/A.mkv\t%d\t22\tA\nmedia/movies/B/B.mkv\t%d\t22\tB\n"
                   % (60 * 1024 ** 3, 50 * 1024 ** 3))
        self.write("RECLAIM_DONE", "media/movies/A/A.mkv\n")
        self.write("RECLAIM_LEDGER", "ts\taction\ttitle\told_path\told_size_bytes\tnlink\tsamefile_paths\tqbit_hash\tstatus\n"
                   "t\ttranscode-replace\tA\t/x\t1\t1\t-\t-\tsaved:%d\n" % (40 * 1024 ** 3))
        self.write("RECLAIM_STATUS_MD", "# status\n- state: encoding: media/movies/B/B.mkv\n")
        self.write("RECLAIM_DF_LOG", "2026-09-01 media 96%\n")
        self.write("RECLAIM_PILOT_ACK", "")
        with mock.patch.object(lib, "reclaim_window_state", return_value={"in_window": False}):
            s = probes.probe_reclaim_status({})
        self.assertEqual(s["queue"], {"total": 2, "remaining": 1, "done": 1, "failed": 0,
                                      "next": "B", "remaining_source_gb": 50.0})
        self.assertEqual(s["saved_gb"], 40.0)
        self.assertTrue(s["flags"]["pilot_ack"])
        self.assertFalse(s["flags"]["paused"])
        self.assertEqual(s["pilot_limit"], 3)
        self.assertIn("encoding", s["worker_status"])
        self.assertEqual(s["last_df_checkpoint"], "2026-09-01 media 96%")
        self.assertEqual(s["candidates"]["remaining"], 7)


# ---------------------------------------------------------------------------
# reclaim-schedule + flags


class ScheduleTests(ReclaimFixture):
    def setUp(self):
        super().setUp()
        def _stat(p):
            size = (90 if "Forrest" in p else 50) * 1024 ** 3
            return {"nlink": 1, "size_bytes": size, "blocks512": size // 512,
                    "mtime": 0, "sparse": False}
        self.stat = self.patch_lib("stat_file", side_effect=_stat)
        self.sudo = self.patch_lib("sudo")
        # let the writer land the queue in the temp dir without sudo
        self.sudo.side_effect = lambda cmd, **kw: self._fake_sudo(cmd)
        # pin "now" so the plan targets the fixture's Sunday-evening window
        p = mock.patch.object(probes, "reclaim_plan",
                              side_effect=lambda w, h, l, r, now=None: _real_plan(w, h, l, r, self.now))
        p.start()
        self.addCleanup(p.stop)

    def _fake_sudo(self, cmd):
        if cmd[0] == "install" and cmd[1] == "-m":
            with open(cmd[-2]) as src, open(cmd[-1], "w") as dst:
                dst.write(src.read())
        elif cmd[0] == "touch":
            open(cmd[1], "w").close()
        elif cmd[0] == "rm":
            try:
                os.unlink(cmd[-1])
            except FileNotFoundError:
                pass
        return ""

    def test_dry_run_plans_tonight(self):
        res = actions.action_reclaim_schedule({"dry_run": True})
        self.assertDryShape(res, "reclaim-schedule")
        self.assertEqual(res["before"]["counts"]["total"], 7)
        self.assertIn("7 titles", res["planned"][0])
        self.assertFalse(os.path.exists(self.paths["RECLAIM_QUEUE"]))

    def test_execute_replaces_queue_largest_first(self):
        self.write("RECLAIM_QUEUE", "rel_path\tsize_bytes\test_target_gb\ttitle\nold/x.mkv\t1\t22\tOld\n")
        res = actions.action_reclaim_schedule({"titles": ["Tenet (2020)", "Forrest Gump (1994)"]})
        rows = lib.reclaim_queue_rows()
        self.assertEqual([r["title"] for r in rows], ["Forrest Gump (1994)", "Tenet (2020)"])
        self.assertEqual(res["before"]["queue_rows"], 1)
        self.assertEqual(res["after"]["queue_rows"], 2)
        self.assertEqual(res["after"]["titles"], ["Tenet (2020)", "Forrest Gump (1994)"])
        self.assertTrue(res["verified"])

    def test_unknown_title_is_409(self):
        e = self.assertPlexOpsError(409, "verify-failed", actions.action_reclaim_schedule,
                                    {"titles": ["Nope (1999)"], "dry_run": True})
        self.assertEqual(e.detail["missing_titles"], ["Nope (1999)"])

    def test_keep_list_title_is_409_even_if_listed(self):
        with open(os.path.join(self.paths["RECLAIM_LOG"], "2026-09-14_001617", "candidates_movies.tsv"), "a") as fh:
            fh.write("\t".join(row("Alien (1979)", 70.0)) + "\n")
        self.assertPlexOpsError(409, "verify-failed", actions.action_reclaim_schedule,
                                {"titles": ["Alien (1979)"], "dry_run": True})

    def test_missing_source_is_409(self):
        self.stat.side_effect = lambda p: None
        e = self.assertPlexOpsError(409, "verify-failed", actions.action_reclaim_schedule,
                                    {"titles": ["Tenet (2020)"], "dry_run": True})
        self.assertEqual(e.detail["gone"][0]["reason"], "missing")

    def test_bad_bodies(self):
        for body in ({"titles": []}, {"titles": [1]}, {"window": "x"}, {"hours": -1}, {"limit": 0}):
            body["dry_run"] = True
            self.assertPlexOpsError(400, "bad-request", actions.action_reclaim_schedule, body)

    def test_pause_resume_pilot_ack(self):
        res = actions.ACTIONS["reclaim-pause"]({})
        self.assertTrue(os.path.exists(self.paths["RECLAIM_PAUSE"]))
        self.assertTrue(res["after"]["present"])
        res = actions.ACTIONS["reclaim-pause"]({})            # idempotent no-op
        self.assertEqual(res["planned"], [])
        res = actions.ACTIONS["reclaim-resume"]({"dry_run": True})
        self.assertDryShape(res, "reclaim-resume")
        self.assertTrue(os.path.exists(self.paths["RECLAIM_PAUSE"]))
        actions.ACTIONS["reclaim-resume"]({})
        self.assertFalse(os.path.exists(self.paths["RECLAIM_PAUSE"]))
        actions.ACTIONS["reclaim-pilot-ack"]({})
        self.assertTrue(os.path.exists(self.paths["RECLAIM_PILOT_ACK"]))


_real_plan = probes.reclaim_plan


if __name__ == "__main__":
    unittest.main()
