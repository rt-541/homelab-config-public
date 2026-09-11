# plex-ops runner - Interface Contract

**Status:** BINDING for all plex-ops builders. Derived from the "Runner surfaces"
section of `docs/superpowers/specs/2026-09-10-plex-ops-agents-design.md`.
If this file and another builder's code disagree, this file wins; change the
contract first, then the code.

The runner is a python3 (3.9, stdlib-only) HTTP service on nemesis, bound to
`$BIND:8377` (default `0.0.0.0`), reached by the NanoClaw agent at
`nemesis.rt-541.io:8377`. No TLS; LAN-only exposure is a deploy-time
obligation - a network-layer restriction to 192.168.1.0/24 (host firewall)
or a LAN-address `BIND`, per the README's Firewall step (firewalld is NOT
running on nemesis by default, so the restriction must be verified, not
assumed). All request and response bodies are JSON
(`Content-Type: application/json`).

---

## 1. Authentication

Every endpoint (probes, actions, passthrough) requires:

```
Authorization: Bearer <token>
```

- **Sole exception: `GET /healthz`** - an unauthenticated liveness endpoint
  returning `{"ok": true, "service": "plex-ops-runner", "ts": "..."}`. It
  reveals nothing but process liveness, is GET-only (anything else is a 405),
  and is deliberately NOT audit-logged (it is polled by Kuma every minute and
  would otherwise drown the audit log). Every other endpoint requires the
  bearer token, and every auth rejection is audit-logged.
- The token is the value of `PLEXOPS_TOKEN` in the runner env file
  `/etc/plex-ops/runner.env` (root:root, mode 0600, `KEY=value` lines,
  `#` comments allowed). The same file may carry `QBIT_USER` / `QBIT_PASS`
  (optional, enables qbit ownership checks) and `PLEX_TOKEN` (optional).
- The runner refuses to start when the token is the committed example
  placeholder (`CHANGE_ME_openssl_rand_hex_32`) or shorter than 32
  characters.
- Comparison is constant-time (`hmac.compare_digest` over UTF-8 bytes; a
  non-ASCII header value is simply a failed auth, never an exception).
- Missing/wrong token: HTTP 401 with the error envelope, `error: "unauthorized"`.
  The Authorization header value is NEVER echoed or audit-logged.
- Rotation: edit the env file, restart the runner service.

## 2. JSON error envelope

Every non-2xx response body is exactly:

```json
{"ok": false, "error": "<code>", "message": "<one human-readable line>", "detail": {}}
```

`detail` is optional and, when present, is a JSON object with machine-readable
context (e.g. the failed path, the current queue item state). Codes and their
HTTP statuses:

| HTTP | `error` | Meaning |
|---|---|---|
| 400 | `bad-request` | malformed body/params, unknown enum value, path outside allowed roots |
| 401 | `unauthorized` | bearer auth failed |
| 404 | `not-found` | unknown probe/action name, unknown route |
| 405 | `method-not-allowed` | wrong HTTP method (e.g. POST to a probe, non-GET passthrough) |
| 409 | `verify-failed` | an action's pre- or post- re-verification did not hold; nothing (further) was done |
| 502 | `upstream-error` | arr/qbit/prowlarr/docker unreachable or returned garbage |
| 500 | `internal` | unexpected exception (message is the exception text, no traceback) |

Every 2xx response body is a JSON object with top-level `"ok": true`.

## 3. Probes - `GET /probe/<name>`

Deterministic, read-only, side-effect free (except the audit log and the disk
trend state file). Query params only; POST to a probe is 405.

### 3.1 `GET /probe/queue-health`

Both arrs' full queues, every item classified into exactly one of:
`malware-ext` | `not-upgrade` | `mapping-mismatch` | `sample-stall` | `unknown`.

Classification rules (single implementation `plexops_lib.classify_queue_item`,
re-exported as `probes.classify_queue_item` and used verbatim by
`queue-remove`'s `expect` pre-verification, so probe and action can never
disagree; unit-tested against the 2026-09-10 fixtures):

- `malware-ext` - any status message, output path, or queue title references a
  payload with an extension in `MALWARE_EXT` (`.exe .scr .rar .lnk .zipx`).
- `not-upgrade` - status messages match "not an upgrade", "not a custom format
  upgrade", or "existing file ... of equal or higher quality" family.
- `mapping-mismatch` - title mismatch / "episode ... was not found in the
  grabbed release" / invalid season / "unable to parse" mapping family.
- `sample-stall` - sample-file detection, or a stalled download (torrent with
  no progress: `sizeleft > 0` and tracked status warning with a
  stall/no-connections message).
- `unknown` - everything else, INCLUDING healthy in-progress items; `evidence`
  and the raw status fields let the agent tell them apart.

Response:

```json
{
  "ok": true, "probe": "queue-health", "ts": "<ISO-8601 with offset>",
  "apps": {
    "sonarr": {
      "total": 137,
      "counts": {"malware-ext": 2, "not-upgrade": 90, "mapping-mismatch": 3,
                 "sample-stall": 1, "unknown": 41},
      "items": [
        {
          "id": 12345,
          "app": "sonarr",
          "title": "<queue item title>",
          "download_id": "<client hash or null>",
          "protocol": "torrent",
          "status": "<arr status field>",
          "tracked_download_status": "<ok|warning|error or null>",
          "tracked_download_state": "<importPending|... or null>",
          "size": 123456789,
          "sizeleft": 0,
          "output_path": "<host-visible path or null>",
          "series_id": 10, "episode_ids": [200, 201], "movie_id": null,
          "classification": "malware-ext",
          "evidence": ["<verbatim status message>", "..."]
        }
      ]
    },
    "radarr": { "total": 0, "counts": {"...": 0}, "items": [] }
  }
}
```

`movie_id` is null for sonarr items; `series_id`/`episode_ids` are null for
radarr items. `counts` always carries all five keys. If one arr is
unreachable the probe still returns 200 with that app replaced by
`{"error": "<message>"}` and the other app intact; both down is a 502.

### 3.2 `GET /probe/service-health`

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

- `prowlarr.ping_ok` from `GET http://localhost:9696/ping`; `cpu_percent` from
  one-shot `docker stats`.
- `stragglers` lists containers whose status is `Exited (255)` in any known
  stack (`STACKS`); `stack` is the compose project label.
- `vpn.egress_ip` is the public IP as seen from inside the gluetun container
  (null and `egress_ok: false` when the exec fails).
- A missing container appears with `"state": "missing", "health": null`.

### 3.3 `GET /probe/disk`

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

`trend` is `null` on the first ever run. The previous snapshot is persisted at
`/docker/plex/logs/plex-ops/disk-state.json` and overwritten on every call
(the only state a probe writes, besides the audit log).

### 3.4 `GET /probe/library-audit?app=<sonarr|radarr>&chunk=N[&chunks=M]`

Params: `app` required; `chunk` required, 0-based integer; `chunks` optional
total chunk count, default 7. Titles (series for sonarr, movies for radarr)
are ordered by arr id ascending; title at index `i` belongs to chunk
`i % chunks`. `chunk >= chunks` is a 400.

Per title in the chunk: tracked files exist on disk, sparse/hollow check
(allocated blocks * 512 < 0.95 * apparent size), untracked orphan files in the
title's library dir, malformed dirs, duplicate versions. Library-wide
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

`apparent_bytes`/`allocated_bytes` are present only on `sparse-file` findings.
Findings are report-only; the probe deletes nothing.

## 4. Read-only arr passthrough - `GET /arr/<app>/api/v3/...`

- `app` in `{sonarr, radarr}` (404 otherwise). Path must start `/api/v3/`
  (404 otherwise). Any method except GET is a 405 - enforced in the runner,
  the upstream never sees it.
- Dot segments (`.` / `..`), raw or percent-encoded (decoded repeatedly, so
  double-encoding does not help), are a 404: the upstream server normalizes
  them, which would let a forwarded path escape `/api/v3`.
- **Credential-bearing endpoints are denied** (404): anything at/under the
  prefixes in `plexops_lib.PASSTHROUGH_DENY` (currently
  `/api/v3/config/host`, whose response carries the arr's own `apiKey`).
  As defense-in-depth, the arr's api key is additionally redacted (replaced
  with `REDACTED`) wherever it appears in any relayed response body.
- The runner injects the arr's `X-Api-Key` (read from its config.xml) and
  strips any client-supplied api key header/param. All other query
  parameters are forwarded as sent, including present-but-empty values
  (re-encoded, semantics preserved).
- The upstream's status code, `Content-Type`, and body (post-redaction) are
  relayed as-is (no `ok` wrapper on success). Upstream unreachable is a 502
  envelope.
- Audit-logged like everything else (`kind: "passthrough"`).

## 5. Actions - `POST /action/<name>`

JSON object body, always. Every action:

- accepts `"dry_run": true|false` (default `false`);
- **re-verifies its target before acting** - it re-fetches the live state and
  refuses with 409 `verify-failed` when the world no longer matches the
  request (item gone from queue, path vanished, container already running);
- **re-verifies after acting** (`dry_run: false` only) and reports the post
  state; a post-check failure is also a 409 (with `performed` showing what ran);
- is idempotent at the goal level: re-posting an already-satisfied action
  either no-ops successfully or 409s with the current state in `detail` -
  it never doubles the effect;
- audit-logs `before` and `after` state.

Success response shape (all actions):

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
`null`, and `planned` lists exactly what would run. With `dry_run: false`:
`planned` and `performed` are equal on success.

### 5.1 `restart-prowlarr`

Body: `{"dry_run": false}`

Steps: `docker compose down prowlarr` then `up -d prowlarr` in the plex-stack
dir; poll `GET /ping` until OK (timeout 120s); POST `indexer/testall` to both
arrs. `before`/`after`: `{"ping_ok": bool, "ping_ms": int|null,
"testall": {"sonarr": "ok|failed|skipped", "radarr": "..."}}` (testall only in
`after`).

### 5.2 `pull-recreate`

Body: `{"service": "gluetun" | "byparr", "dry_run": false}`

Any other service is a 400. Steps: `docker compose pull <service>`; then down
and `up -d` of the affected pair (`gluetun` implies the compose service
`qbit` - the container_name is `qbittorrent` - which rides its network
namespace; `byparr` is alone); wait for the service's healthcheck to report
healthy (timeout 180s). Compose commands use compose SERVICE names
(`gluetun qbit`); `docker inspect` and the `before`/`after` blocks use
container_names:
`{"<container>": {"state": "...", "health": "...", "image_id": "..."}}` (plus
`qbittorrent` when applicable).

### 5.3 `resurrect-stragglers`

Body: `{"dry_run": false, "stacks": ["plex-stack"]}` - `stacks` optional,
default: all known stacks; unknown stack name is a 400.

Pre-verify: list `Exited (255)` containers in those stacks; none found is a
successful no-op (`before.stragglers: []`, nothing planned). Steps: one
`docker compose up -d --no-recreate` per affected stack (`--no-recreate` so
starting the exited containers never recreates RUNNING services whose config
has diverged from the compose file on disk - only the verified stragglers may
change state). Post-verify: the found stragglers are running.
`before`/`after`: `{"stragglers": [{"name", "status", "stack"}]}`.

### 5.4 `queue-remove`

Body:

```json
{"app": "sonarr", "id": 12345, "blocklist": true, "removeData": true,
 "expect": "malware-ext", "dry_run": false}
```

`blocklist`/`removeData` default `false`. `expect` (optional) is a
queue-health classification; pre-verify re-fetches the queue, 409s if `id` is
gone, and 409s if `expect` is given and the item now classifies differently
(the current item is in `detail`). When `removeData: true` and the item has an
output path, that path must resolve under `/docker/plex/media/downloads`
(never `.Trash`) or the action 409s. Executes arr
`DELETE /api/v3/queue/{id}?removeFromClient=<removeData>&blocklist=<blocklist>&skipRedownload=true`.
Post-verify: `id` no longer in the queue. `before`: the re-fetched item (with
classification); `after`: `{"in_queue": false}`.

### 5.5 `search`

Body (exactly one target form):

- radarr: `{"app": "radarr", "movie_ids": [1, 2], "dry_run": false}`
- sonarr: `{"app": "sonarr", "episode_ids": [200], "dry_run": false}` or
  `{"app": "sonarr", "series_id": 10, "dry_run": false}`

Pre-verify: the referenced ids exist in the arr (409 otherwise). Executes the
arr command endpoint (`MoviesSearch` / `EpisodeSearch` / `SeriesSearch`).
`after`: `{"command_id": 987, "command_state": "queued"}`.

### 5.6 `delete-download`

Body: `{"path": "/docker/plex/media/downloads/...", "allow_qbit_owned": false, "dry_run": false}`

- Path is normalized and MUST be strictly under `/docker/plex/media/downloads`
  and contain no `.Trash` component - otherwise 400, nothing touched. The
  symlink-resolved path (`realpath -e`) must satisfy the same policy
  (400 symlink-escape otherwise); every later step - stat, ownership check,
  rm - operates on the RESOLVED path.
- Pre-verify: the path exists (409 if not); its `stat` (nlink, apparent size,
  allocated blocks, sparse verdict) and any hardlink twins under downloads are
  captured into `before` and the audit log.
- qbit ownership check when creds are present: if a torrent owns the target
  in EITHER direction - the torrent's content path is at/under the target,
  OR the target lies inside the torrent's content dir (one file of a
  multi-file torrent) - and `allow_qbit_owned` is false, 409 with the torrent
  hash/name in `detail`. (Removing the torrent itself is `queue-remove`'s
  job.) If creds are configured but qbit is unreachable, the check cannot
  run: the action refuses with 502 `upstream-error` unless
  `allow_qbit_owned` is true. `before.qbit_checked` records whether the
  check actually ran, so `qbit_owner: null` is never ambiguous.
- Executes the delete as ONE `sudo` invocation that re-resolves the path and
  refuses unless it still resolves to itself, then `rm -rf`s it (narrows the
  check-to-delete TOCTOU window to a single process; a delete-time
  re-verification failure is a 409). Post-verify: path gone.
- `before`: `{"path" (resolved), "nlink", "size_bytes", "blocks512", "sparse",
  "samefile_hits": [], "qbit_checked": bool,
  "qbit_owner": {"hash", "name"} | null}`;
  `after`: `{"exists": false}`.

## 6. Audit log

Every call - probe, action, passthrough, every auth failure, and every
authed unknown-route 404 - appends exactly ONE line to
`/docker/plex/logs/plex-ops/audit.jsonl` (the only exception is the
unauthenticated `/healthz` liveness endpoint, section 1): a single compact
JSON object, `\n`-terminated (JSON Lines). Fields:

```json
{
  "ts": "2026-09-10T14:03:22-04:00",
  "remote": "192.168.1.50",
  "kind": "probe | action | passthrough | auth | route",
  "name": "queue-remove",
  "method": "POST",
  "path": "/action/queue-remove",
  "params": {},
  "body": {"app": "sonarr", "id": 12345, "blocklist": true},
  "dry_run": false,
  "status": 200,
  "ok": true,
  "summary": "removed sonarr queue item 12345 (malware-ext), blocklisted, data deleted",
  "duration_ms": 412,
  "before": {},
  "after": {}
}
```

Rules: `ts` is ISO-8601 with UTC offset; `params` is the parsed query string,
`body` the parsed request body (absent when empty); the Authorization header
is never logged; `before`/`after` appear on actions only; `summary` is one
line; probe result payloads are NOT duplicated into the log (the `summary`
carries counts). Writing goes through `plexops_lib.audit_append` only.
`kind: "auth"` is reserved for auth FAILURES; an authed request to an
unknown route logs as `kind: "route"`.

## 7. Python module boundaries

Four files in `scripts/plex-ops/`, python 3.9, stdlib only:

- `plexops_lib.py` - shared plumbing, no HTTP-server awareness. Never imports
  the other three.
- `probes.py` - imports only `plexops_lib` (+ stdlib). Pure functions
  returning the section-3 dicts (without the `"ok"` key - the runner adds it).
- `actions.py` - imports only `plexops_lib` (+ stdlib). Functions take the
  parsed body dict, return the section-5 dict (without `"ok"`), raise
  `plexops_lib.PlexOpsError` for every failure.
- `runner.py` - stdlib `http.server` (ThreadingHTTPServer). Routing, bearer
  auth, JSON (de)serialization, error envelope, audit logging around every
  call, `/arr` passthrough. Imports all three.

### 7.1 `plexops_lib.py` exports (the lib contract)

Constants:

```python
MEDIA = "/docker/plex/media"
MEDIA2 = "/docker/plex/media2"
DOWNLOADS = "/docker/plex/media/downloads"
LOG_ROOT = "/docker/plex/logs/plex-ops"
AUDIT_LOG = LOG_ROOT + "/audit.jsonl"
DISK_STATE = LOG_ROOT + "/disk-state.json"
ENV_FILE = "/etc/plex-ops/runner.env"
TOKEN_VAR = "PLEXOPS_TOKEN"
TOKEN_PLACEHOLDER = "CHANGE_ME_openssl_rand_hex_32"   # refused at startup
TOKEN_MIN_LEN = 32
RUNNER_PORT = 8377
ARR = {"radarr": {"url", "config", "port"},
       "sonarr": {...}, "prowlarr": {...}}   # localhost URLs + config.xml paths
PASSTHROUGH_APPS = ("sonarr", "radarr")
PASSTHROUGH_DENY = ("/api/v3/config/host",)  # credential-bearing endpoints
CLASSES = ("malware-ext", "not-upgrade", "mapping-mismatch", "sample-stall", "unknown")
QUEUE_PAGE_SIZE = 250
QUEUE_MAX_PAGES = 40
QBIT_URL = "http://localhost:8080"
QBIT_PATH_PREFIX = "/data/downloads"
PLEX_STACK = "plex-stack"
STACKS = {"plex-stack": "/docker/homelab-config/nemesis/composed-apps/plex-stack"}
MALWARE_EXT = (".exe", ".scr", ".rar", ".lnk", ".zipx")
VIDEO_EXT = (".mkv", ".mp4", ".avi", ".m2ts", ".ts", ".webm", ".m4v")
SPARSE_RATIO = 0.95
```

Error type:

```python
class PlexOpsError(Exception):
    def __init__(self, code, message, status=500, detail=None): ...
    # .code .message .status .detail ; .envelope() -> the section-2 dict
```

Utilities:

```python
def log(msg): ...                    # timestamped stderr-style progress line
def die(msg, code=1): ...
def gib(nbytes): ...
def fmt_gib(nbytes): ...
def now_iso(): ...                   # ISO-8601 seconds, local offset
def stamp(): ...                     # filesystem-safe timestamp
def run(cmd, check=True, capture=True, cwd=None, input_text=None): ...  # -> stdout str
def sudo(cmd, check=True, cwd=None, input_text=None): ...  # run(["sudo","-n"]+cmd,...)
def sudo_ok(): ...                   # -> bool
def read_env(path=None): ...         # KEY=value file -> dict; sudo-cat fallback; default ENV_FILE
def runner_token(path=None): ...     # -> str; PlexOpsError("internal") when unset,
                                     #    the example placeholder, or < TOKEN_MIN_LEN chars
def load_json(path, default=None): ...
def save_json(path, obj): ...
def ensure_log_dir(): ...            # sudo install -d LOG_ROOT, idempotent
def audit_append(record): ...        # one compact JSON line -> AUDIT_LOG (adds ts if absent)
```

HTTP / arr / qbit:

```python
def http_json(url, method="GET", headers=None, body=None, timeout=60): ...
    # -> (status:int, parsed_json_or_None); URLError -> PlexOpsError("upstream-error", 502)
def arr_key(app): ...                # api key grepped from config.xml (sudo)
def arr_call(app, method, path, params=None, body=None, timeout=120): ...
    # -> parsed JSON | None; HTTP error -> PlexOpsError("upstream-error", 502)
def arr_get(app, path, params=None): ...
def arr_get_raw(app, path_qs, timeout=120): ...
    # passthrough transport -> (status:int, content_type:str, body:bytes);
    # upstream HTTP errors returned as-is, connection failure -> PlexOpsError;
    # the arr's own api key is redacted from the body
def prowlarr_ping(timeout=10): ...   # -> {"ok": bool, "ms": int|None, "error": str|None}

# Queue classification + contract item shape (section 3.1) - THE single
# implementation, shared by probes.py (re-export) and actions.py:
def arr_host_path(path): ...         # /data -> MEDIA, /data2 -> MEDIA2
def classify_queue_item(item, app=None): ...  # -> (classification, evidence)
def fetch_queue(app): ...            # full queue, paged to totalRecords
def queue_item_view(raw, app): ...   # -> the section-3.1 item dict

class Qbit:                          # creds from ENV_FILE / os.environ; .available
    def torrents(self): ...          # + "host_content_path" resolved to DOWNLOADS
    def trackers(self, torrent_hash): ...
    def delete(self, hashes, delete_files): ...
def qbit_hits_under(qbit, host_path_prefix): ...
    # torrents owning the path in either direction (content at/under the
    # target, or target inside the content dir) -> list | None when unavailable
```

Docker (all via `sudo -n docker`; compose via `sudo -n docker compose` with
`cwd=STACKS[stack]`; down/up, never `restart`):

```python
def docker_ps_all(): ...             # -> [{"name","state","status","stack","image"}]
def container_state(name): ...       # inspect -> {"state","health","exit_code",
                                     #   "status","started_at","image_id"} | None
def docker_stats(names=None): ...    # one-shot -> [{"name","cpu_percent",...raw}]
def exited_255(stacks=None): ...     # -> [{"name","status","stack"}] (known stacks only)
def compose(stack, args, check=True): ...  # e.g. compose("plex-stack", ["up","-d","prowlarr"])
def gluetun_egress_ip(timeout=20): ...     # public IP from inside gluetun | None
```

Filesystem (read-only via sudo; the ONLY writers are `audit_append`,
`save_json` under LOG_ROOT, and actions calling `sudo rm` on contract-verified
paths):

```python
def is_sparse(size_bytes, blocks512): ...  # blocks512*512 < SPARSE_RATIO*size
def stat_file(path): ...             # -> {"nlink","size_bytes","blocks512",
                                     #     "mtime","sparse"} | None
def find_files_blocks(roots, extra_args=None): ...
    # yields (size, nlink, dirname, filename, blocks512)
def samefile_hits(path, root=DOWNLOADS): ...  # hardlink twins, excluding path
def safe_download_path(path): ...    # normalized path strictly under DOWNLOADS,
                                     # no .Trash component; else PlexOpsError 400
def df_mounts(): ...                 # -> {mount: {"size_bytes","used_bytes",
                                     #     "avail_bytes","used_percent"}}
def is_video(name): ...
```

### 7.2 `probes.py` exports

```python
def classify_queue_item(item, app): ...   # re-export of plexops_lib's (section 3.1)
def probe_queue_health(params): ...       # params: parsed query dict (unused)
def probe_service_health(params): ...
def probe_disk(params): ...
def probe_library_audit(params): ...      # reads params["app"], ["chunk"], ["chunks"]
PROBES = {"queue-health": probe_queue_health, "service-health": probe_service_health,
          "disk": probe_disk, "library-audit": probe_library_audit}
```

Each probe takes the parsed query params as a `dict[str, str]`, returns the
section-3 payload (runner adds `"ok": true`), raises `PlexOpsError` on bad
params or upstream failure.

### 7.3 `actions.py` exports

```python
def action_restart_prowlarr(body): ...
def action_pull_recreate(body): ...
def action_resurrect_stragglers(body): ...
def action_queue_remove(body): ...
def action_search(body): ...
def action_delete_download(body): ...
ACTIONS = {"restart-prowlarr": action_restart_prowlarr,
           "pull-recreate": action_pull_recreate,
           "resurrect-stragglers": action_resurrect_stragglers,
           "queue-remove": action_queue_remove,
           "search": action_search,
           "delete-download": action_delete_download}
```

Each takes the parsed JSON body `dict`, returns the section-5 payload
(runner adds `"ok": true`), raises `PlexOpsError` (409 `verify-failed` for
re-verification failures) on any refusal.

### 7.4 `runner.py`

`def main():` - binds `$BIND:RUNNER_PORT` (default `0.0.0.0`), dispatches:
`GET /healthz` (unauthenticated liveness, section 1),
`GET /probe/<name>` -> `PROBES`, `POST /action/<name>` -> `ACTIONS`,
`GET /arr/<app>/api/v3/...` -> `arr_get_raw`. Wraps every authed call in
timing + `audit_append`, converts `PlexOpsError` to its envelope and any
other exception to the 500 envelope. Runner never mutates anything itself.
