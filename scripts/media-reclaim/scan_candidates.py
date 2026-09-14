#!/usr/bin/env python3
"""Phase 1: scan both movie libraries and rank reclaim candidates.

Read-only. Emits, under /docker/plex/logs/media-reclaim/<stamp>/:
  candidates_movies.tsv  - one row per movie dir, ranked by est. savings,
                           with an empty SKIP column the user can edit
  orphans_downloads.tsv  - non-hardlinked downloads (review-only info)
  report.md              - human summary

Queue emission (run AFTER the user reviewed/edited the TSV):
  scan_candidates.py --emit-queue <path/to/candidates_movies.tsv>
writes /docker/plex/media/.reclaim/queue/queue.tsv for the devastator
transcoder. Keep-list titles are re-checked and refused here regardless of
what the TSV says.
"""

import os
import sys

import reclaim_lib as lib


def collect_movies(root):
    """Map top-level movie dir -> list of (size, nlink, path, filename, blocks)."""
    movies = {}
    for size, nlink, d, f, blocks in lib.find_files_blocks([root]):
        rel = os.path.relpath(d, root)
        top = rel.split(os.sep)[0] if rel != "." else ""
        if not top:
            continue
        movies.setdefault(top, []).append((size, nlink, os.path.join(d, f), f, blocks))
    return movies


def classify(mount_label, root, movies, keep_pats, pol):
    tmin = float(pol.get("TRANSCODE_MIN_GB", 30)) * 1024 ** 3
    vmin = float(pol.get("MULTIVERSION_MIN_GB", 1)) * 1024 ** 3
    t_min_gb = float(pol.get("TARGET_MIN_GB", 15))
    t_max_gb = float(pol.get("TARGET_MAX_GB", 25))
    ratio = float(pol.get("TARGET_RATIO", 0.28))

    rows = []
    for title, files in sorted(movies.items()):
        vids = [x for x in files if lib.is_video(x[3])]
        if not vids:
            continue
        vids.sort(reverse=True)
        primary = vids[0]
        psize, pnlink, ppath, pname, pblocks = primary
        res, src, codec, flags = lib.parse_tokens(pname)
        if lib.is_sparse(psize, pblocks):
            flags = (flags + ",SPARSE").lstrip("-,")
        large = [v for v in vids if v[0] >= vmin]
        total = sum(v[0] for v in vids)

        if lib.keep_match(keep_pats, title):
            action, est_target, savings = "keep-priority", "", 0
        elif "SPARSE" in flags:
            # hollow/truncated file: apparent size lies, data may be missing
            action, est_target, savings = "sparse-review", "", 0
        elif "FAKE4K" in flags:
            action, est_target, savings = "fake-4k-review", "", 0
        elif len(large) >= 2:
            action = "delete-dupe"
            est_target = ""
            savings = sum(v[0] for v in large[1:])
        elif psize > tmin:
            action = "transcode"
            tgt = min(t_max_gb, max(t_min_gb, lib.gib(psize) * ratio))
            est_target = "%.0f" % tgt
            savings = psize - tgt * 1024 ** 3
        else:
            action, est_target, savings = "ok", "", 0

        then_transcode = "yes" if action == "delete-dupe" and psize > tmin else ""
        rows.append({
            "action": action, "title": title, "mount": mount_label,
            "size_gb": lib.fmt_gib(total), "videos": len(vids),
            "res": res or "?", "src": src or "?", "codec": codec or "?",
            "flags": flags, "nlink": pnlink,
            "est_target_gb": est_target,
            "est_savings_gb": lib.fmt_gib(savings) if savings else "0.0",
            "then_transcode": then_transcode,
            "primary_path": ppath, "SKIP": "",
            "_savings": savings,
        })
    return rows


def orphan_report(outdir):
    """Downloads files with nlink==1 (not hardlinked into the library).
    Reports allocated bytes too - apparent size can be a lie (hollow files)."""
    rows = []
    total = alloc_total = 0
    for size, nlink, d, f, blocks in lib.find_files_blocks([lib.DOWNLOADS]):
        if nlink == 1:
            total += size
            alloc_total += blocks * 512
            rows.append((size, blocks * 512, os.path.join(d, f)))
    rows.sort(reverse=True)
    tsv = os.path.join(outdir, "orphans_downloads.tsv")
    lib.write_tsv(tsv, ["size_gb", "allocated_gb", "path"],
                  [(lib.fmt_gib(s), lib.fmt_gib(a), p) for s, a, p in rows[:100]])
    return total, alloc_total, len(rows), tsv


HEADER = ["action", "title", "mount", "size_gb", "videos", "res", "src", "codec",
          "flags", "nlink", "est_target_gb", "est_savings_gb", "then_transcode",
          "primary_path", "SKIP"]


def do_scan():
    keep_pats = lib.read_keep_list()
    pol = lib.read_policy()
    lib.ensure_dirs()
    outdir = os.path.join(lib.LOG_ROOT, lib.stamp())
    os.makedirs(outdir, exist_ok=True)

    lib.log("scanning %s/movies ..." % lib.MEDIA)
    m1 = collect_movies(os.path.join(lib.MEDIA, "movies"))
    lib.log("scanning %s/movies ..." % lib.MEDIA2)
    m2 = collect_movies(os.path.join(lib.MEDIA2, "movies"))

    rows = classify("media", os.path.join(lib.MEDIA, "movies"), m1, keep_pats, pol)
    rows += classify("media2", os.path.join(lib.MEDIA2, "movies"), m2, keep_pats, pol)
    rows.sort(key=lambda r: r["_savings"], reverse=True)

    tsv = os.path.join(outdir, "candidates_movies.tsv")
    lib.write_tsv(tsv, HEADER, [[r[h] for h in HEADER] for r in rows])

    lib.log("scanning downloads for orphans ...")
    orphan_total, orphan_alloc, orphan_count, orphan_tsv = orphan_report(outdir)

    # keep-list verification
    keep_lines = []
    for pat in keep_pats:
        matches = [r["title"] for r in rows if pat in r["title"].lower()]
        mark = "OK " if matches else "!! NO MATCH"
        keep_lines.append("- `%s` -> %s %s" % (pat, mark, "; ".join(matches)))

    # summary
    def bucket(action, mount=None):
        sel = [r for r in rows if r["action"] == action and (mount is None or r["mount"] == mount)]
        return len(sel), sum(r["_savings"] for r in sel)

    md = [
        "# Media reclaim candidate report (%s)" % lib.stamp(),
        "",
        "| action | count | est. savings (GiB) |", "|---|---|---|",
    ]
    for action in ("transcode", "delete-dupe", "fake-4k-review", "sparse-review",
                   "keep-priority", "ok"):
        n, sav = bucket(action)
        md.append("| %s | %d | %.0f |" % (action, n, lib.gib(sav)))
    for mount in ("media", "media2"):
        n, sav = bucket("transcode", mount)
        md.append("| transcode on %s | %d | %.0f |" % (mount, n, lib.gib(sav)))
    md += ["", "## Keep-list verification", ""] + keep_lines
    md += ["", "## Top 25 transcode candidates", "",
           "| title | mount | size GiB | target GiB | flags |", "|---|---|---|---|---|"]
    for r in [r for r in rows if r["action"] == "transcode"][:25]:
        md.append("| %s | %s | %s | %s | %s |" %
                  (r["title"], r["mount"], r["size_gb"], r["est_target_gb"], r["flags"]))
    md += ["", "## Downloads orphans (info only, nothing deleted)", "",
           "%d files with nlink=1, %.1f GiB apparent / %.1f GiB actually allocated. Top 100 in `%s`." %
           (orphan_count, lib.gib(orphan_total), lib.gib(orphan_alloc), os.path.basename(orphan_tsv)),
           "May include actively seeding torrents - requires the qbit cross-check before ANY action.",
           "", "## Files", "",
           "- `%s` - edit the SKIP column (any non-empty value = skip) then run `--emit-queue`" % tsv]
    with open(os.path.join(outdir, "report.md"), "w") as fh:
        fh.write("\n".join(md) + "\n")

    print("\n".join(md[:len(md) - 4]))
    print("\nreport dir: %s" % outdir)
    return outdir


def do_emit_queue(tsv_path):
    keep_pats = lib.read_keep_list()
    header, rows = lib.read_tsv(tsv_path)
    idx = {h: i for i, h in enumerate(header)}
    for col in ("action", "title", "primary_path", "SKIP", "est_target_gb"):
        if col not in idx:
            lib.die("column %s missing from %s" % (col, tsv_path))
    out_rows = []
    skipped_keep = 0
    for r in rows:
        if r[idx["action"]] != "transcode" or r[idx["SKIP"]].strip():
            continue
        title = r[idx["title"]]
        if lib.keep_match(keep_pats, title):
            skipped_keep += 1
            continue
        path = r[idx["primary_path"]]
        try:
            out = lib.sudo(["stat", "-c", "%h %s %b", path])
            _nlink, size, blocks = (int(x) for x in out.split())
        except Exception:
            lib.log("gone, skipping: %s" % path)
            continue
        if lib.is_sparse(size, blocks):
            lib.log("SPARSE (hollow/truncated), refusing to queue: %s" % path)
            continue
        rel = os.path.relpath(path, "/docker/plex")
        out_rows.append((rel, size, r[idx["est_target_gb"]], title))
    out_rows.sort(key=lambda x: -x[1])
    lib.ensure_dirs()
    qpath = os.path.join(lib.STATE_ROOT, "queue", "queue.tsv")
    lib.write_tsv(qpath, ["rel_path", "size_bytes", "est_target_gb", "title"], out_rows)
    lib.log("queue written: %s (%d jobs, %.0f GiB source)" %
            (qpath, len(out_rows), lib.gib(sum(r[1] for r in out_rows))))
    if skipped_keep:
        lib.log("refused %d keep-list rows that were marked transcode" % skipped_keep)


def main():
    if not lib.sudo_ok():
        lib.die("needs passwordless sudo (media mounts are plexadm 0770)")
    if len(sys.argv) >= 3 and sys.argv[1] == "--emit-queue":
        do_emit_queue(sys.argv[2])
    elif len(sys.argv) == 1:
        do_scan()
    else:
        lib.die("usage: scan_candidates.py [--emit-queue candidates_movies.tsv]")


if __name__ == "__main__":
    main()
