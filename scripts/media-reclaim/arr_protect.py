#!/usr/bin/env python3
"""Radarr guard rails for the transcode campaign.

  arr_protect.py --tag-keeps
      Ensure a 'keep-remux' tag exists and apply it to every keep-list movie.
      Pure protection/bookkeeping; changes no files.

  arr_protect.py --make-profile
      Create quality profile 'Reclaim-NoUpgrade' (clone of the profile used
      by the most movies, with upgradeAllowed=false). Idempotent.

  arr_protect.py --assign-from-ledger
      Move every movie whose file the transcoder replaced (ledger action
      'transcode-replace') onto Reclaim-NoUpgrade so Radarr never "fixes"
      the compressed file back to a remux. Run during/after Phase 2 waves.
"""

import os
import sys
from collections import Counter

import reclaim_lib as lib

PROFILE_NAME = "Reclaim-NoUpgrade"
TAG_LABEL = "keep-remux"


def movie_dir(m):
    return os.path.basename((m.get("path") or "").rstrip("/"))


def tag_keeps():
    keep_pats = lib.read_keep_list()
    tags = lib.arr_get("radarr", "/api/v3/tag")
    tag = next((t for t in tags if t["label"] == TAG_LABEL), None)
    if not tag:
        tag = lib.arr_call("radarr", "POST", "/api/v3/tag", body={"label": TAG_LABEL})
        lib.log("created tag %r id=%d" % (TAG_LABEL, tag["id"]))
    movies = lib.arr_get("radarr", "/api/v3/movie")
    ids = [m["id"] for m in movies if lib.keep_match(keep_pats, movie_dir(m))]
    if not ids:
        lib.die("keep-list matched no Radarr movies - check keep-list.conf")
    lib.arr_call("radarr", "PUT", "/api/v3/movie/editor",
                 body={"movieIds": ids, "tags": [tag["id"]], "applyTags": "add"})
    names = sorted(movie_dir(m) for m in movies if m["id"] in set(ids))
    lib.log("tagged %d movies with %r:" % (len(ids), TAG_LABEL))
    for n in names:
        print("  " + n)


def make_profile():
    profiles = lib.arr_get("radarr", "/api/v3/qualityprofile")
    if any(p["name"] == PROFILE_NAME for p in profiles):
        lib.log("profile %r already exists" % PROFILE_NAME)
        return
    movies = lib.arr_get("radarr", "/api/v3/movie")
    counts = Counter(m.get("qualityProfileId") for m in movies)
    base_id = counts.most_common(1)[0][0]
    base = dict(next(p for p in profiles if p["id"] == base_id))
    base_name = base["name"]
    base.pop("id", None)
    base["name"] = PROFILE_NAME
    base["upgradeAllowed"] = False
    created = lib.arr_call("radarr", "POST", "/api/v3/qualityprofile", body=base)
    lib.log("created profile %r id=%d (clone of %r, upgradeAllowed=false)" %
            (PROFILE_NAME, created["id"], base_name))


def assign_from_ledger():
    if not os.path.exists(lib.LEDGER):
        lib.die("no ledger yet")
    profiles = lib.arr_get("radarr", "/api/v3/qualityprofile")
    prof = next((p for p in profiles if p["name"] == PROFILE_NAME), None)
    if not prof:
        lib.die("run --make-profile first")
    header, rows = lib.read_tsv(lib.LEDGER)
    idx = {h: i for i, h in enumerate(header)}
    replaced_dirs = set()
    for r in rows:
        if r[idx["action"]] == "transcode-replace":
            # old_path = /docker/plex/media*/movies/<dir>/<file>
            parts = r[idx["old_path"]].split("/")
            if "movies" in parts:
                replaced_dirs.add(parts[parts.index("movies") + 1])
    if not replaced_dirs:
        lib.log("no transcode-replace entries in ledger yet")
        return
    movies = lib.arr_get("radarr", "/api/v3/movie")
    ids = [m["id"] for m in movies
           if movie_dir(m) in replaced_dirs and m.get("qualityProfileId") != prof["id"]]
    if not ids:
        lib.log("all %d replaced movies already on %s" % (len(replaced_dirs), PROFILE_NAME))
        return
    lib.arr_call("radarr", "PUT", "/api/v3/movie/editor",
                 body={"movieIds": ids, "qualityProfileId": prof["id"]})
    lib.log("moved %d movies to %r" % (len(ids), PROFILE_NAME))


def main():
    actions = {"--tag-keeps": tag_keeps, "--make-profile": make_profile,
               "--assign-from-ledger": assign_from_ledger}
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        lib.die(__doc__)
    actions[sys.argv[1]]()


if __name__ == "__main__":
    main()
