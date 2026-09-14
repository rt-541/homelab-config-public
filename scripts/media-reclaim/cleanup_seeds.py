#!/usr/bin/env python3
"""Phase 3: reviewed removal of old seed data in downloads/.

Replaced/deleted library files that were hardlinked (nlink=2) still hold
their bytes in the qbittorrent seed copy. This script turns the campaign
ledger into a per-torrent review sheet, and only deletes what the user
explicitly approves - private-tracker ratios are the concern.

  cleanup_seeds.py --report
      Reads /docker/plex/media/.reclaim/ledger.tsv, matches entries to
      qbittorrent torrents (by recorded hash or content-path/samefile
      overlap), writes <LOG_ROOT>/seed_cleanup_report.tsv with tracker host,
      ratio, size, state and an empty APPROVE column.

  cleanup_seeds.py --execute
      Re-reads that TSV; rows with APPROVE=yes get the torrent deleted WITH
      data via the qbit API, then leftover hardlinks/dirs are cleaned up
      (the move_smallest_50.bash pattern). Everything else is untouched.
"""

import os
import sys
import urllib.parse

import reclaim_lib as lib

REPORT = os.path.join(lib.LOG_ROOT, "seed_cleanup_report.tsv")
HEADER = ["hash", "torrent", "tracker_host", "ratio", "size_gb", "state",
          "ledger_titles", "content_path", "APPROVE"]


def report():
    qbit = lib.Qbit()
    if not qbit.available:
        lib.die("qbittorrent API unavailable - fill QBIT_USER/QBIT_PASS in .env")
    if not os.path.exists(lib.LEDGER):
        lib.die("no ledger at %s yet" % lib.LEDGER)
    header, rows = lib.read_tsv(lib.LEDGER)
    idx = {h: i for i, h in enumerate(header)}

    torrents = {t["hash"]: t for t in qbit.torrents()}
    matches = {}  # hash -> set(titles)
    for r in rows:
        title = r[idx["title"]]
        qhash = r[idx["qbit_hash"]]
        samefiles = [] if r[idx["samefile_paths"]] == "-" else r[idx["samefile_paths"]].split(";")
        old_path = r[idx["old_path"]]
        if qhash and qhash != "-" and qhash in torrents:
            matches.setdefault(qhash, set()).add(title)
            continue
        for t in torrents.values():
            cp = t["host_content_path"].rstrip("/")
            if not cp:
                continue
            cands = samefiles + [old_path]
            for p in cands:
                if p == cp or p.startswith(cp + "/") or cp.startswith(p + "/"):
                    matches.setdefault(t["hash"], set()).add(title)
                    break

    out = []
    for qhash, titles in sorted(matches.items(), key=lambda kv: -torrents[kv[0]]["size"]):
        t = torrents[qhash]
        host = ""
        try:
            for tr in qbit.trackers(qhash):
                u = tr.get("url", "")
                if u.startswith(("http", "udp")):
                    host = urllib.parse.urlsplit(u).hostname or ""
                    break
        except Exception:
            host = "?"
        out.append([qhash, t["name"], host, "%.2f" % t.get("ratio", 0),
                    lib.fmt_gib(t.get("size", 0)), t.get("state", "?"),
                    ";".join(sorted(titles)), t["host_content_path"], ""])
    lib.ensure_dirs()
    lib.write_tsv(REPORT, HEADER, out)
    total = sum(float(r[4]) for r in out)
    lib.log("%d torrents matched, %.1f GiB seed data -> %s" % (len(out), total, REPORT))
    lib.log("review tracker_host/ratio, set APPROVE=yes per row, then --execute")


def execute():
    if not os.path.exists(REPORT):
        lib.die("run --report first")
    qbit = lib.Qbit()
    if not qbit.available:
        lib.die("qbittorrent API unavailable")
    header, rows = lib.read_tsv(REPORT)
    idx = {h: i for i, h in enumerate(header)}
    approved = [r for r in rows if r[idx["APPROVE"]].strip().lower() == "yes"]
    if not approved:
        lib.die("no rows with APPROVE=yes in %s" % REPORT)
    lib.df_checkpoint("before seed cleanup (%d torrents)" % len(approved))
    hashes = [r[idx["hash"]] for r in approved]
    qbit.delete(hashes, delete_files=True)
    lib.log("deleted %d torrents with data" % len(hashes))
    # leftover cleanup: paths qbit no longer owns but that still exist
    for r in approved:
        cp = r[idx["content_path"]]
        if cp and cp.startswith(lib.DOWNLOADS + "/"):
            lib.sudo(["rm", "-rf", cp], check=False)
    # prune emptied dirs under downloads (never touches files)
    lib.sudo(["find", lib.DOWNLOADS, "-mindepth", "1", "-type", "d", "-empty",
              "-not", "-path", "*/.Trash-1001*", "-delete"], check=False)
    lib.df_checkpoint("after seed cleanup")
    lib.log("seed cleanup complete")


def main():
    if not lib.sudo_ok():
        lib.die("needs passwordless sudo")
    if len(sys.argv) != 2 or sys.argv[1] not in ("--report", "--execute"):
        lib.die(__doc__)
    (report if sys.argv[1] == "--report" else execute)()


if __name__ == "__main__":
    main()
