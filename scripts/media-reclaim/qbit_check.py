#!/usr/bin/env python3
"""Which torrent (if any) owns each given host path?

Usage: qbit_check.py <host-path> [...]
Prints one TSV line per path: path<TAB>result
  result = UNAVAILABLE            (no creds / login failed)
         | NONE                   (no torrent owns this path)
         | <hash>|<name>|<state>  (owning torrent)
A path is "owned" when it equals, contains, or is contained in a torrent's
content path. Exit code 0 always; callers parse the output.
"""

import sys

import reclaim_lib as lib


def main():
    paths = sys.argv[1:]
    if not paths:
        lib.die("usage: qbit_check.py <host-path> [...]")
    qbit = lib.Qbit()
    if not qbit.available:
        for p in paths:
            print("%s\tUNAVAILABLE" % p)
        return
    torrents = qbit.torrents()
    for p in paths:
        p_norm = p.rstrip("/")
        owner = None
        for t in torrents:
            cp = t["host_content_path"].rstrip("/")
            if not cp:
                continue
            if p_norm == cp or p_norm.startswith(cp + "/") or cp.startswith(p_norm + "/"):
                owner = t
                break
        if owner:
            print("%s\t%s|%s|%s" % (p, owner["hash"], owner["name"], owner.get("state", "?")))
        else:
            print("%s\tNONE" % p)


if __name__ == "__main__":
    main()
