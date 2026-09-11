# Skill: digest

Runs weekly (Sunday morning, after the audit rollup). One post to
the chat channel: what got fixed, what is still waiting, and where the disks are
heading. The digest has no approval tier and takes no actions - it is the
week's ledger. All calls go to `$RUNNER_URL` with
`Authorization: Bearer $RUNNER_TOKEN`; every non-2xx response is the
envelope
`{"ok": false, "error": "<code>", "message": "<one line>", "detail": {}}`
(400 bad-request, 401 unauthorized, 404 not-found, 405 method-not-allowed,
409 verify-failed, 502 upstream-error, 500 internal).

## Tier rules (binding)

- **Auto tier**: post the summary (fixed / waiting / disk trajectory). That
  is the whole duty. In SHADOW mode the digest still posts for real - it is
  a report, not an action - but it labels the week's auto-tier lines as
  shadowed ("would have removed", not "removed").
- **Approval tier**: none.

## Procedure

1. **Fixed**: from `memory/pending.md` and the week's receipt lines
   (`memory/watchdog.md`, triage receipts): count executed auto-tier
   actions per kind (queue removals by classification, prowlarr restarts,
   pull-recreates, resurrections) and approved items completed. In SHADOW
   mode these are "would have fixed" counts.
2. **Waiting**: open approval-list items (posted, neither approved nor
   denied), 409-skipped items, and the current queue picture - either from
   the day's triage run or a fresh `GET /probe/queue-health`, reporting the
   `counts` per app (do not re-post per-item detail; the triage lists carry
   that).
3. **Disk trajectory**: `GET /probe/disk`. Append this week's snapshot
   (`ts`, per-mount `used_bytes`, `used_percent`) to
   `memory/disk-history.md`, then report the trajectory from that file:
   week-over-week delta per mount and, if the trend continues, roughly when
   `/docker/plex/media` hits full. The probe's own `trend` field only spans
   back to the previous `/probe/disk` call by anyone, so the multi-week
   view comes from `memory/disk-history.md`, not from `trend`. (For the
   same reason, no other duty calls `/probe/disk` on a schedule.)
4. Post one digest, compact, in this shape:

   ```
   plex-ops digest, week of 2026-09-07 (mode: SHADOW)
   Fixed: 14 queue removals (9 malware-ext, 5 not-upgrade), 1 prowlarr restart, 1 gluetun pull-recreate. [shadowed - none executed]
   Waiting: 6 approval items open (list qt-2026-09-13-1: 4, la-2026-09-13-1: 2), 1 skipped on 409.
   Queue now: sonarr 41 (41 unknown/healthy), radarr 2.
   Disk: media 97.1% (+38 GiB this week, ~5 weeks to full at this rate), media2 40.2% (+2 GiB).
   ```

5. Reset the weekly counters in memory (keep `memory/disk-history.md`
   forever; it is the trajectory).

## HTTP contract: `GET /probe/disk`

```json
{
  "ok": true, "probe": "disk", "ts": "...",
  "mounts": {
    "/docker/plex/media":  {"size_bytes": 1, "used_bytes": 1, "avail_bytes": 1, "used_percent": 97.1},
    "/docker/plex/media2": {"size_bytes": 1, "used_bytes": 1, "avail_bytes": 1, "used_percent": 40.2}
  },
  "trend": {
    "since": "<ts of previous probe>",
    "hours": 26.0,
    "delta_used_bytes": {"/docker/plex/media": 12345, "/docker/plex/media2": -99}
  }
}
```

`trend` is `null` on the first ever run. The previous snapshot is persisted
by the runner at `/docker/plex/logs/plex-ops/disk-state.json` and
overwritten on every call.

## HTTP contract: `GET /probe/queue-health` (counts only)

The digest uses only the per-app `total` and `counts` from the
queue-health response; the full item schema is embedded in the
`queue-triage` skill. Shape of what the digest reads:

```json
{
  "ok": true, "probe": "queue-health", "ts": "...",
  "apps": {
    "sonarr": {"total": 137,
               "counts": {"malware-ext": 2, "not-upgrade": 90,
                          "mapping-mismatch": 3, "sample-stall": 1,
                          "unknown": 41},
               "items": ["..."]},
    "radarr": {"total": 0, "counts": {"...": 0}, "items": []}
  }
}
```

If one arr is unreachable the probe still returns 200 with that app
replaced by `{"error": "<message>"}` and the other app intact; both down is
a 502 - report the outage in the digest instead of the counts.
