#!/usr/bin/env python3
"""llm-jobs admin: keys and jobs, straight against the SQLite file.

  admin.py key issue --owner dana [--role user|worker|admin] [--tiers local,claude] [--daily-jobs 50] [--daily-tokens 200000]
  admin.py key list
  admin.py key revoke <key-id>
  admin.py key tiers <key-id> --tiers local,claude,render
  admin.py jobs [--limit 20]
  admin.py job <job-id>

Run as the service user on devastator (same LLMJOBS_DB). The key is printed
once at issue time and never stored in clear.
"""

import argparse
import json
import sys

import jobs_lib as lib


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("key"); ks = k.add_subparsers(dest="kcmd", required=True)
    ki = ks.add_parser("issue")
    ki.add_argument("--owner", required=True)
    ki.add_argument("--role", default="user", choices=["user", "worker", "admin"])
    ki.add_argument("--tiers", default="local")
    ki.add_argument("--daily-jobs", type=int, default=50)
    ki.add_argument("--daily-tokens", type=int, default=200000)
    ks.add_parser("list")
    kr = ks.add_parser("revoke"); kr.add_argument("key_id")
    kt = ks.add_parser("tiers"); kt.add_argument("key_id"); kt.add_argument("--tiers", required=True)
    j = sub.add_parser("jobs"); j.add_argument("--limit", type=int, default=20)
    g = sub.add_parser("job"); g.add_argument("job_id")
    a = ap.parse_args()

    store = lib.Store(lib.Config().db_path)
    if a.cmd == "key" and a.kcmd == "issue":
        tiers = [t.strip() for t in a.tiers.split(",") if t.strip()]
        kid, key = store.issue_key(a.owner, a.role, tiers, a.daily_jobs, a.daily_tokens)
        print(json.dumps({"key_id": kid, "key": key, "owner": a.owner, "role": a.role, "tiers": tiers,
                          "daily_jobs": a.daily_jobs, "daily_tokens": a.daily_tokens}, indent=1))
    elif a.cmd == "key" and a.kcmd == "list":
        for r in store.list_keys():
            print(json.dumps(r))
    elif a.cmd == "key" and a.kcmd == "revoke":
        print("revoked" if store.revoke_key(a.key_id) else "no such active key", file=sys.stderr)
    elif a.cmd == "key" and a.kcmd == "tiers":
        tiers = [t.strip() for t in a.tiers.split(",") if t.strip()]
        print("tiers set" if store.set_key_tiers(a.key_id, tiers) else "no such active key", file=sys.stderr)
    elif a.cmd == "jobs":
        for r in store.list_jobs(None, a.limit):
            print(json.dumps({k: r[k] for k in ("id", "owner", "tier", "status", "created_at", "finished_at", "tokens_out", "error")}))
    elif a.cmd == "job":
        r = store.get_job(a.job_id)
        print(json.dumps(r, indent=1) if r else "no such job")


if __name__ == "__main__":
    main()
