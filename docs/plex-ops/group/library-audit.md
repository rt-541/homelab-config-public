# Skill: library-audit

Nightly chunk plus a weekly rollup. The audit itself is **report-only**:
the probe deletes nothing and you fix nothing automatically - every fix is
approval tier, always, in both SHADOW and LIVE modes. All calls go to
`$RUNNER_URL` with `Authorization: Bearer $RUNNER_TOKEN`; every non-2xx
response is the envelope
`{"ok": false, "error": "<code>", "message": "<one line>", "detail": {}}`
(400 bad-request, 401 unauthorized, 404 not-found, 405 method-not-allowed,
409 verify-failed, 502 upstream-error, 500 internal).

## Tier rules (binding)

- **Auto tier**: none. Findings are reported, never acted on unprompted.
- **Approval tier**: integrity fixes, orphan/dupe deletions, gap searches.
  Concretely:
  - `orphan-file` / `duplicate-versions` under
    `/docker/plex/media/downloads` -> propose `delete-download`. Findings
    outside the downloads root cannot be deleted by the runner (the action
    only accepts paths under `/docker/plex/media/downloads`); report them
    for the operator to handle by hand, with the exact path.
  - `missing-file` / `sparse-file` -> propose a `search` re-grab for the
    affected title (plus, for a hollow file in downloads, a
    `delete-download` of the husk).
  - `missing-monitored` / `cutoff-unmet` gaps -> propose targeted `search`
    only when the operator asks or in the weekly rollup, batched, never
    per-chunk (a blanket search storm is exactly the queue silt the triage
    duty cleans up).

## Procedure

### Nightly chunk (one per night, 03:30)

1. Chunk index = weekday number, Monday 0 .. Sunday 6 (`chunks` stays at the
   default 7, so one full pass per app per week).
2. `GET /probe/library-audit?app=sonarr&chunk=<N>` then
   `GET /probe/library-audit?app=radarr&chunk=<N>`.
3. Append the counts and findings to `memory/audit-week.md` (one section per
   night, ts + app + counts + finding lines). File paths in findings are
   nemesis paths; when the path is under `/docker/plex/media`, you may
   inspect it read-only at the `/data/...` translation to add evidence
   (e.g. confirm a directory's contents before calling something a dupe).
4. Post nothing on a clean chunk. Post a one-line note only for something
   urgent (e.g. a sparse-file count suddenly jumping), not routine findings
   - those wait for the rollup.

### Weekly rollup (Sunday morning, after the last chunk)

1. Aggregate `memory/audit-week.md`: totals per finding type per app, plus
   the latest library-wide `missing-monitored` / `cutoff-unmet` counts.
2. Post the rollup summary to the chat channel, then one numbered approval list
   (id `la-<date>-<n>`) covering the proposed fixes, each with type, title,
   path, and one line of evidence (`apparent_bytes`/`allocated_bytes` for
   sparse files). Persist number -> action body in `memory/pending.md`.
3. On `approve`/`deny` from `rt-541`, execute approved items (409
   `verify-failed` = "state changed, skipped"), post one receipt line each,
   record outcomes, then reset `memory/audit-week.md` for the next cycle.

## HTTP contract: `GET /probe/library-audit?app=<sonarr|radarr>&chunk=N[&chunks=M]`

Params: `app` required; `chunk` required, 0-based integer; `chunks` optional
total chunk count, default 7. Titles (series for sonarr, movies for radarr)
are ordered by arr id ascending; title at index `i` belongs to chunk
`i % chunks`. `chunk >= chunks` is a 400.

Per title in the chunk: tracked files exist on disk, sparse/hollow check
(allocated blocks * 512 < 0.95 * apparent size), untracked orphan files in
the title's library dir, malformed dirs, duplicate versions. Library-wide
missing-monitored and cutoff-unmet are cheap arr-side counts, reported on
every chunk.

```json
{
  "ok": true, "probe": "library-audit", "ts": "...",
  "app": "sonarr", "chunk": 2, "chunks": 7,
  "titles_checked": 40,
  "counts": {
    "missing-file": 1, "sparse-file": 0, "orphan-file": 3,
    "malformed-dir": 0, "duplicate-versions": 2,
    "missing-monitored": 12, "cutoff-unmet": 30
  },
  "findings": [
    {
      "type": "missing-file | sparse-file | orphan-file | malformed-dir | duplicate-versions",
      "title": "<series/movie title>",
      "title_id": 10,
      "path": "<absolute host path>",
      "detail": "<one line>",
      "apparent_bytes": 123, "allocated_bytes": 45
    }
  ]
}
```

`apparent_bytes`/`allocated_bytes` are present only on `sparse-file`
findings. Findings are report-only; the probe deletes nothing.

## HTTP contract: approval-tier actions

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

### `POST /action/delete-download`

```json
{"path": "/docker/plex/media/downloads/...", "allow_qbit_owned": false, "dry_run": false}
```

- Path is normalized and MUST be strictly under
  `/docker/plex/media/downloads` and contain no `.Trash` component -
  otherwise 400, nothing touched.
- Pre-verify: the path exists (409 if not); its stat (nlink, apparent size,
  allocated blocks, sparse verdict) and any hardlink twins under downloads
  are captured into `before`.
- qbit ownership check: if a torrent's content path is at/under the target
  and `allow_qbit_owned` is false, 409 with the torrent hash/name in
  `detail`. (Removing the torrent itself is `queue-remove`'s job.)
- Executes `sudo rm -rf` on the verified path only. Post-verify: path gone.
- `before`: `{"path", "nlink", "size_bytes", "blocks512", "sparse",
  "samefile_hits": [], "qbit_owner": {"hash", "name"} | null}`;
  `after`: `{"exists": false}`.

### `POST /action/search`

Exactly one target form:

- radarr: `{"app": "radarr", "movie_ids": [1, 2], "dry_run": false}`
- sonarr: `{"app": "sonarr", "episode_ids": [200], "dry_run": false}` or
  `{"app": "sonarr", "series_id": 10, "dry_run": false}`

Pre-verify: the referenced ids exist in the arr (409 otherwise). Executes
the arr command endpoint (`MoviesSearch` / `EpisodeSearch` /
`SeriesSearch`). `after`: `{"command_id": 987, "command_state": "queued"}`.

## Ad-hoc lookups

To resolve a finding's `title_id` into arr detail (episode ids for a
targeted search, monitored flags), use the read-only passthrough:
`GET /arr/<app>/api/v3/...` - `app` in `{sonarr, radarr}`, path must start
`/api/v3/`, GET only (anything else is a 405; the runner enforces it). The
runner injects the api key; the upstream's status, content type, and body
are relayed verbatim. Example:
`GET $RUNNER_URL/arr/sonarr/api/v3/episode?seriesId=10`.
