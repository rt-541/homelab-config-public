# Skill: service-watchdog

Runs every 30 minutes (and on demand). Check service health and apply the
three known-signature fixes; everything unrecognized is reported with
evidence, never guessed at. All calls go to `$RUNNER_URL` with
`Authorization: Bearer $RUNNER_TOKEN`; every non-2xx response is the envelope
`{"ok": false, "error": "<code>", "message": "<one line>", "detail": {}}`
(400 bad-request, 401 unauthorized, 404 not-found, 405 method-not-allowed,
409 verify-failed, 502 upstream-error, 500 internal).

## Tier rules (binding)

- **Auto tier** (LIVE mode: execute + one-line receipt; SHADOW mode:
  `dry_run: true` + `SHADOW:` line). Known signatures only:
  - **Prowlarr livelock**: `prowlarr.ping_ok` false, or ping timing out with
    prowlarr `cpu_percent` pegged (roughly 100% or more sustained) ->
    `restart-prowlarr`.
  - **Stale-image breakage**: `gluetun` health `unhealthy` (Nord wireguard
    i/o timeouts) or `vpn.egress_ok` false -> `pull-recreate` service
    `gluetun`. `byparr` health `unhealthy` (healthcheck 500) ->
    `pull-recreate` service `byparr`.
  - **Post-crash stragglers**: any entry in `stragglers` (Exited (255)) ->
    `resurrect-stragglers`.
- **Approval tier / report**: anything else that looks wrong - a container
  `state` not `running` that is not an Exited(255) straggler, a `missing`
  container, an unhealthy container other than gluetun/byparr, repeated
  flapping (same auto fix fired on consecutive runs) - post the evidence
  (verbatim probe fields) and, when a runner action could plausibly fix it,
  a numbered approval list. Never invent a fix outside the whitelist.

Flap guard: keep the last few watchdog results in `memory/watchdog.md`. If
the same auto fix would fire a third consecutive time, stop auto-firing it
and escalate to a report ("restart-prowlarr fired at 12:00 and 12:30 and it
is down again") - a fix that does not stick is an unrecognized problem.

## Procedure

1. `GET /probe/service-health`.
2. Match signatures in this order: stragglers, gluetun, byparr, prowlarr.
   Act per mode; one receipt (or `SHADOW:`) line each. A 409 `verify-failed`
   means the world changed under you (e.g. container already back) - report
   it as a no-op, do not retry.
3. Unrecognized findings: one report post with verbatim evidence.
4. All healthy: post nothing on scheduled runs (silence is the healthy
   signal every 30 minutes); answer with the summary when run on demand.
5. Append one line to `memory/watchdog.md` (ts, findings, actions taken).

## HTTP contract: `GET /probe/service-health`

```json
{
  "ok": true, "probe": "service-health", "ts": "...",
  "prowlarr": {"ping_ok": true, "ping_ms": 12, "cpu_percent": 3.2},
  "containers": {
    "gluetun":  {"state": "running", "health": "healthy", "status": "Up 2 days (healthy)"},
    "byparr":   {"state": "running", "health": "unhealthy", "status": "..."},
    "sonarr":   {"state": "running", "health": null, "status": "..."},
    "radarr":   {"state": "running", "health": null, "status": "..."},
    "prowlarr": {"state": "running", "health": null, "status": "..."},
    "qbittorrent": {"state": "running", "health": null, "status": "..."}
  },
  "stragglers": [
    {"name": "<container>", "status": "Exited (255) 2 hours ago", "stack": "plex-stack"}
  ],
  "vpn": {"egress_ok": true, "egress_ip": "x.x.x.x"}
}
```

- `prowlarr.ping_ok` from `GET http://localhost:9696/ping`; `cpu_percent`
  from one-shot `docker stats`.
- `stragglers` lists containers whose status is `Exited (255)` in any known
  stack; `stack` is the compose project label.
- `vpn.egress_ip` is the public IP as seen from inside the gluetun container
  (null and `egress_ok: false` when the exec fails).
- A missing container appears with `"state": "missing", "health": null`.

## HTTP contract: actions (shared shape)

`POST /action/<name>` with a JSON object body. Every action accepts
`"dry_run": true|false` (default false), re-verifies its target before
acting (409 `verify-failed` when the world no longer matches), re-verifies
after acting, and is idempotent at the goal level. Success response:

```json
{
  "ok": true, "action": "<name>", "dry_run": false, "ts": "...",
  "before":    { "<action-specific pre-state>": "..." },
  "planned":   ["<step>", "..."],
  "performed": ["<step>", "..."],
  "after":     { "<action-specific post-state>": "..." },
  "verified": true
}
```

With `dry_run: true`: `performed` is `[]`, `after` is `null`, `verified` is
`null`, and `planned` lists exactly what would run.

### `POST /action/restart-prowlarr`

Body: `{"dry_run": false}`

Steps: `docker compose down prowlarr` then `up -d prowlarr` in the
plex-stack dir; poll `GET /ping` until OK (timeout 120s); POST
`indexer/testall` to both arrs. `before`/`after`:
`{"ping_ok": bool, "ping_ms": int|null,
"testall": {"sonarr": "ok|failed|skipped", "radarr": "..."}}` (testall only
in `after`).

### `POST /action/pull-recreate`

Body: `{"service": "gluetun" | "byparr", "dry_run": false}`

Any other service is a 400. Steps: `docker compose pull <service>`; then
down and `up -d` of the affected pair (`gluetun` implies `qbit`, which rides
its network namespace; `byparr` is alone); wait for the service's
healthcheck to report healthy (timeout 180s). `before`/`after`:
`{"<service>": {"state": "...", "health": "...", "image_id": "..."}}` (plus
`qbit` when applicable).

### `POST /action/resurrect-stragglers`

Body: `{"dry_run": false, "stacks": ["plex-stack"]}` - `stacks` optional,
default: all known stacks; unknown stack name is a 400.

Pre-verify: list `Exited (255)` containers in those stacks; none found is a
successful no-op (`before.stragglers: []`, nothing planned). Steps: one
`docker compose up -d` per affected stack. Post-verify: the found
stragglers are running. `before`/`after`:
`{"stragglers": [{"name", "status", "stack"}]}`.
