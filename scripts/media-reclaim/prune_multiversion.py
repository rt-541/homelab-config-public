#!/usr/bin/env python3
"""Phase 0.5: prune redundant versions in media2 movie dirs holding 2+ large
video files (~93 dirs, ~0.5-0.9 TiB redundant).

  prune_multiversion.py --report
      Writes <LOG_ROOT>/prune_report.tsv. Keep rule: keep the Radarr-tracked
      file unless another file is strictly better (higher resolution, then
      better source, then bigger). Malformed dirs (no year) are auto-SKIPped.
      Edit the SKIP column to veto rows, or the keep/delete columns if you
      disagree with a choice.

  prune_multiversion.py --execute
      Re-reads prune_report.tsv and acts on non-SKIP rows: untracked extras
      are rm'd; a tracked file being removed goes through the Radarr API;
      afterwards RefreshMovie realigns Radarr with the surviving file.
      Torrent-owned files are skipped into the ledger for cleanup_seeds.py.
"""

import os
import sys

import reclaim_lib as lib

ROOT = os.path.join(lib.MEDIA2, "movies")
ARR_ROOT = "/data2/movies"
REPORT = os.path.join(lib.LOG_ROOT, "prune_report.tsv")
HEADER = ["dir", "keep_file", "delete_files", "delete_gb", "radarr", "movie_id",
          "qbit", "note", "SKIP"]


def rank_key(entry):
    """Sort key: better first. entry = (size, nlink, path, fname)."""
    res, src, _codec, _flags = lib.parse_tokens(entry[3])
    res_rank = {"2160p": 0, "1080p": 1, "720p": 2, "480p": 3, "": 4}[res]
    return (res_rank, lib.src_rank(src), -entry[0])


def collect():
    pol = lib.read_policy()
    vmin = float(pol.get("MULTIVERSION_MIN_GB", 1)) * 1024 ** 3
    dirs = {}
    for size, nlink, d, f in lib.find_files([ROOT]):
        if not lib.is_video(f):
            continue
        rel = os.path.relpath(d, ROOT)
        top = rel.split(os.sep)[0] if rel != "." else ""
        if top:
            dirs.setdefault(top, []).append((size, nlink, os.path.join(d, f), f))
    return {t: fs for t, fs in dirs.items()
            if len([x for x in fs if x[0] >= vmin]) >= 2}, vmin


def radarr_maps():
    movies = lib.arr_get("radarr", "/api/v3/movie")
    by_dir = {}
    for m in movies:
        p = m.get("path") or ""
        if p.startswith(ARR_ROOT + "/"):
            by_dir[p[len(ARR_ROOT) + 1:]] = m
    return by_dir


def report():
    multi, vmin = collect()
    by_dir = radarr_maps()
    qbit = lib.Qbit()
    if not qbit.available:
        lib.log("WARNING: qbit unavailable - qbit column will be UNAVAILABLE")
    torrents = qbit.torrents() if qbit.available else []

    def qbit_owner(path):
        if not qbit.available:
            return "UNAVAILABLE"
        for t in torrents:
            cp = t["host_content_path"].rstrip("/")
            if cp and (path == cp or path.startswith(cp + "/") or cp.startswith(path + "/")):
                return t["hash"]
        return "NONE"

    rows = []
    total = 0
    for d in sorted(multi):
        files = [x for x in multi[d] if x[0] >= vmin]
        movie = by_dir.get(d)
        tracked_rel = None
        movie_id = ""
        if movie:
            movie_id = str(movie["id"])
            mf = movie.get("movieFile")
            if mf:
                tracked_rel = mf.get("relativePath")
        best = sorted(files, key=rank_key)[0]
        tracked = None
        if tracked_rel:
            for x in files:
                if os.path.relpath(x[2], os.path.join(ROOT, d)) == tracked_rel:
                    tracked = x
        keep = tracked if tracked is not None else best
        if tracked is not None and rank_key(best) < rank_key(tracked):
            keep = best  # untracked file is strictly better
        deletes = [x for x in files if x[2] != keep[2]]
        del_bytes = sum(x[0] for x in deletes)
        total += del_bytes
        note = []
        if not movie:
            note.append("not-in-radarr")
        if "(" not in d or d.endswith("()"):
            note.append("malformed-year")
        if tracked is not None and keep is not tracked:
            note.append("replacing-tracked-file")
        radarr_col = ("tracked-kept" if keep is tracked else
                      "tracked-deleted" if tracked is not None else
                      "untracked" if movie else "no-movie")
        skip = "manual" if "malformed-year" in note else ""
        rows.append([
            d, os.path.basename(keep[2]),
            ";".join(os.path.basename(x[2]) for x in deletes),
            lib.fmt_gib(del_bytes), radarr_col, movie_id,
            ";".join(sorted({qbit_owner(x[2]) for x in deletes})),
            ",".join(note) or "-", skip,
        ])
    lib.ensure_dirs()
    lib.write_tsv(REPORT, HEADER, rows)
    lib.log("%d dirs, %.1f GiB deletable -> %s" % (len(rows), lib.gib(total), REPORT))


def execute():
    if not os.path.exists(REPORT):
        lib.die("run --report first")
    header, rows = lib.read_tsv(REPORT)
    idx = {h: i for i, h in enumerate(header)}
    qbit = lib.Qbit()
    lib.df_checkpoint("before multiversion prune")
    refresh_ids = []
    freed = 0
    for r in rows:
        if r[idx["SKIP"]].strip():
            lib.log("SKIP: %s" % r[idx["dir"]])
            continue
        d = r[idx["dir"]]
        movie_id = r[idx["movie_id"]]
        dirpath = os.path.join(ROOT, d)
        keep_name = r[idx["keep_file"]]
        del_names = [x for x in r[idx["delete_files"]].split(";") if x]
        # resolve tracked file id fresh (report may be stale)
        tracked_rel, tracked_id = None, None
        if movie_id:
            for mf in lib.arr_get("radarr", "/api/v3/moviefile", {"movieId": movie_id}) or []:
                tracked_rel, tracked_id = mf.get("relativePath"), mf.get("id")
        for name in del_names:
            path = None
            for size, nlink, fdir, fname in lib.find_files([dirpath]):
                if fname == name:
                    path = os.path.join(fdir, fname)
                    nl, sz = nlink, size
                    break
            if not path:
                lib.log("already gone: %s/%s" % (d, name))
                continue
            hits = lib.qbit_hits_under(qbit, path)
            if hits:
                lib.ledger_append("prune-skip-torrent", d, path, sz, nl, [],
                                  hits[0]["hash"], "torrent-owned")
                lib.log("SKIP torrent-owned: %s (route via cleanup_seeds.py)" % path)
                continue
            links = lib.samefile_hits(path) if nl > 1 else []
            lib.ledger_append("prune", d, path, sz, nl, links, None, "deleted")
            rel = os.path.relpath(path, os.path.join(ROOT, d))
            if tracked_rel and rel == tracked_rel and tracked_id:
                lib.arr_call("radarr", "DELETE", "/api/v3/moviefile/%d" % tracked_id)
                lib.log("radarr-deleted %s/%s" % (d, name))
            else:
                lib.sudo(["rm", "-f", path])
                lib.log("rm %s/%s" % (d, name))
            freed += sz
        if movie_id:
            refresh_ids.append(int(movie_id))
        # sanity: keeper must still exist
        found = any(f == keep_name for _s, _n, _d, f in lib.find_files([dirpath]))
        if not found:
            lib.log("WARNING: keeper missing after prune in %s" % d)
    if refresh_ids:
        lib.arr_call("radarr", "POST", "/api/v3/command",
                     body={"name": "RefreshMovie", "movieIds": refresh_ids})
        lib.log("RefreshMovie for %d movies" % len(refresh_ids))
    lib.df_checkpoint("after multiversion prune")
    lib.log("freed %.1f GiB (hardlinked bytes free after seed cleanup)" % lib.gib(freed))


def main():
    if not lib.sudo_ok():
        lib.die("needs passwordless sudo")
    if len(sys.argv) != 2 or sys.argv[1] not in ("--report", "--execute"):
        lib.die(__doc__)
    if sys.argv[1] == "--report":
        report()
    else:
        execute()


if __name__ == "__main__":
    main()
