#!/usr/bin/env python3
"""Add the plex-ops monitors to Uptime Kuma (idempotent). DEPLOY.md Part 2.

Run from the control plane (tarkin, where uptime-kuma-api is installed for
kuat-drive-yards/ansible/monitors/monitors.py):

  PLEXOPS_TOKEN=<token> python3 kuma-monitors.py http://192.168.1.14:3001 <user> <password>

Monitors (all HTTP, 60s interval, 2 retries, accepted 200):
  plex-ops-runner    GET nemesis:8377/probe/service-health with the bearer header
                     (exercises auth + sudo + docker + prowlarr ping, the real signal)
  prowlarr-ping      GET nemesis:9696/ping
  plex-ops-healthz   GET nemesis:8377/healthz (process liveness only, no auth)

The token is passed via the environment, never argv, and Kuma stores it
server-side in the monitor's headers. Attaches the existing "discord"
notification when present. Fold into kuat-drive-yards monitors.py when that
repo next gets a monitors change.
"""
import json
import os
import sys

from uptime_kuma_api import MonitorType, UptimeKumaApi

if len(sys.argv) < 4:
    sys.exit("usage: PLEXOPS_TOKEN=... kuma-monitors.py <url> <user> <password>")
URL, USER, PASSWORD = sys.argv[1:4]
TOKEN = os.environ.get("PLEXOPS_TOKEN", "")
if len(TOKEN) < 32:
    sys.exit("PLEXOPS_TOKEN missing or too short in the environment")

RUNNER = "http://nemesis.rt-541.io:8377"
MONITORS = [
    ("plex-ops-runner", dict(url=f"{RUNNER}/probe/service-health",
                             headers=json.dumps({"Authorization": f"Bearer {TOKEN}"}))),
    ("prowlarr-ping", dict(url="http://nemesis.rt-541.io:9696/ping")),
    ("plex-ops-healthz", dict(url=f"{RUNNER}/healthz")),
]

with UptimeKumaApi(URL) as api:
    api.login(USER, PASSWORD)
    notifs = {n["name"]: n["id"] for n in api.get_notifications()}
    notif_ids = [notifs["discord"]] if "discord" in notifs else []
    existing = {m["name"]: m for m in api.get_monitors()}
    for name, kw in MONITORS:
        kwargs = dict(type=MonitorType.HTTP, name=name, interval=60, maxretries=2,
                      accepted_statuscodes=["200-299"], **kw)
        if notif_ids:
            kwargs["notificationIDList"] = notif_ids
        if name in existing:
            api.edit_monitor(existing[name]["id"], **kwargs)
            print(f"updated {name}")
        else:
            api.add_monitor(**kwargs)
            print(f"added {name}")
print("done")
