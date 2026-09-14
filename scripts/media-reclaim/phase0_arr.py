#!/usr/bin/env python3
"""Phase 0 arr-mediated items.

  phase0_arr.py dune-dupe --report|--execute
      Remove the phantom "Dune" TV series (the 57.6 GiB AI-upscale movie
      misfiled under media/tv/Dune) via Sonarr, with hardlink/torrent checks.

  phase0_arr.py fake4k --report|--execute
      Delete the Cowboys & Aliens fake-4K upscale via Radarr and trigger a
      real-quality regrab. (Alien 3's upscale is keep-list franchise -
      flagged for a manual decision, never touched here.)
"""

import os
import sys

import reclaim_lib as lib

TV_DUNE_HOST = "/docker/plex/media/tv/Dune"
TV_DUNE_ARR = "/data/tv/Dune"


def file_facts(path):
    nlink, size = lib.stat_nlink_size(path)
    links = lib.samefile_hits(path) if nlink and nlink > 1 else []
    qbit = lib.Qbit()
    hits = lib.qbit_hits_under(qbit, os.path.dirname(path))
    return nlink, size, links, hits


def dune_dupe(execute):
    series = [s for s in lib.arr_get("sonarr", "/api/v3/series") if s.get("path") == TV_DUNE_ARR]
    files = list(lib.find_files([TV_DUNE_HOST]))  # empty if the dir is already gone
    vids = [(s, n, os.path.join(d, f)) for s, n, d, f in files if lib.is_video(f)]

    print("Sonarr series at %s: %s" % (TV_DUNE_ARR,
          ", ".join("id=%d %r" % (s["id"], s["title"]) for s in series) or "NOT FOUND"))
    for size, nlink, path in vids:
        links = lib.samefile_hits(path) if nlink > 1 else []
        print("file: %s\n  %.1f GiB, nlink=%d%s" %
              (path, lib.gib(size), nlink,
               (", hardlinked to: " + "; ".join(links)) if links else ""))
    qbit = lib.Qbit()
    hits = lib.qbit_hits_under(qbit, TV_DUNE_HOST)
    if hits is None:
        print("qbit check: UNAVAILABLE (creds missing) - none expected here, dir is in tv/")
    elif hits:
        lib.die("a torrent owns content under %s - resolve first: %s" %
                (TV_DUNE_HOST, ", ".join(t["name"] for t in hits)))
    else:
        print("qbit check: no torrent owns this path")

    if not execute:
        print("\n--report only; nothing changed")
        return

    lib.df_checkpoint("before dune-dupe removal")
    for size, nlink, path in vids:
        links = lib.samefile_hits(path) if nlink > 1 else []
        lib.ledger_append("dune-dupe", "Dune (phantom TV)", path, size, nlink, links,
                          None, "deleted")
    if series:
        sid = series[0]["id"]
        lib.arr_call("sonarr", "DELETE", "/api/v3/series/%d" % sid,
                     params={"deleteFiles": "true", "addImportListExclusion": "true"})
        lib.log("sonarr series %d deleted (files + import-list exclusion)" % sid)
    out = lib.sudo(["find", TV_DUNE_HOST, "-mindepth", "1"], check=False)
    if out.strip():
        lib.log("leftovers remain, removing dir: %s" % TV_DUNE_HOST)
    lib.sudo(["rm", "-rf", TV_DUNE_HOST], check=False)
    lib.df_checkpoint("after dune-dupe removal")
    lib.log("dune-dupe complete; run a Plex TV-section scan + empty trash on devastator")


def fake4k(execute):
    movies = lib.arr_get("radarr", "/api/v3/movie")
    targets = [m for m in movies if "cowboys & aliens" in m.get("title", "").lower()
               or "cowboys and aliens" in m.get("title", "").lower()]
    profiles = {p["id"]: p["name"] for p in lib.arr_get("radarr", "/api/v3/qualityprofile")}
    if not targets:
        lib.die("Cowboys & Aliens not found in Radarr")
    for m in targets:
        mf = m.get("movieFile") or {}
        print("movie id=%d %r\n  path=%s\n  profile=%s\n  file=%s (%.1f GiB)" %
              (m["id"], m["title"], m.get("path"),
               profiles.get(m.get("qualityProfileId"), "?"),
               mf.get("relativePath", "NONE"), lib.gib(mf.get("size", 0))))
        print("  NOTE: profile must allow 1080p for the regrab to succeed.")
    print("Alien 3 fake-4K: keep-list franchise, NOT touched by this script. "
          "Decide separately (honest 1080p regrab vs wait for a real 4K).")

    if not execute:
        print("\n--report only; nothing changed")
        return

    lib.df_checkpoint("before fake4k removal")
    for m in targets:
        mf = m.get("movieFile")
        if not mf:
            lib.log("no file for %r, just searching" % m["title"])
        else:
            host_path = mf["path"].replace("/data2/", "/docker/plex/media2/").replace(
                "/data/", "/docker/plex/media/")
            nlink, size = lib.stat_nlink_size(host_path)
            links = lib.samefile_hits(host_path) if (nlink or 0) > 1 else []
            lib.ledger_append("fake4k", m["title"], host_path, size or 0, nlink or 0,
                              links, None, "deleted-via-radarr")
            lib.arr_call("radarr", "DELETE", "/api/v3/moviefile/%d" % mf["id"])
            lib.log("deleted moviefile %d for %r" % (mf["id"], m["title"]))
        lib.arr_call("radarr", "POST", "/api/v3/command",
                     body={"name": "MoviesSearch", "movieIds": [m["id"]]})
        lib.log("search triggered for %r" % m["title"])
    lib.df_checkpoint("after fake4k removal")


def main():
    if not lib.sudo_ok():
        lib.die("needs passwordless sudo")
    if len(sys.argv) != 3 or sys.argv[2] not in ("--report", "--execute"):
        lib.die(__doc__)
    execute = sys.argv[2] == "--execute"
    if sys.argv[1] == "dune-dupe":
        dune_dupe(execute)
    elif sys.argv[1] == "fake4k":
        fake4k(execute)
    else:
        lib.die(__doc__)


if __name__ == "__main__":
    main()
