# plex-ops: Plex-Stack Maintenance Agent Suite - Design

**Date:** 2026-09-10
**Status:** APPROVED (user chose Clanker-fleet substrate, tiered autonomy, all four duties; directed build via ultracode workflow)
**Problem:** The plex-stack degrades in recurring, known ways with no automated response: trash grabs (malware-bait `.exe`/`.scr`/`.rar` releases, fake 4K/AI upscales, hollow files), the Sonarr queue silting up (observed 2026-09-10: 137 items, 96 stuck warnings), Prowlarr livelocks killing all indexers, stale `:latest` images breaking gluetun/byparr, Exited(255) stragglers after crashes, and disk pressure on the media arrays.

## Architecture

Split brain/hands across the two hosts:

- **Brain: NanoClaw group `plex-ops`** (Discord channel `#plex-ops`) on devastator, following the existing vault-group pattern (local vLLM backend via cch proxy, `cli_scope` disabled, `CLAUDE_CODE_MAX_OUTPUT_TOKENS` cap in `container.json`). Scheduled runs plus on-demand chat. Capabilities: a read-only NFS mount of the media export (file inspection; `downloads/` is inside it) and ONE bearer token to the nemesis action-runner. No arr keys, no docker access in the agent.
- **Hands: action-runner on nemesis** - host-level systemd service (python3 stdlib, port 8377, LAN-bound), because its job is `docker compose` and sudo file ops. All calls bearer-authed; every call JSON-audit-logged to `/docker/plex/logs/plex-ops/`.

### Runner surfaces

1. `GET /probe/<name>` - deterministic JSON probes:
   - `queue-health` - both arrs' queues, items classified: `malware-ext` (.exe/.scr/.rar/.lnk/.zipx payloads), `not-upgrade`, `mapping-mismatch` (title mismatch / episode-not-found / invalid-season), `sample-stall`, `unknown`
   - `service-health` - Prowlarr /ping + container CPU, gluetun/byparr health, Exited(255) stragglers, VPN egress check
   - `disk` - df both mounts + trend vs last probe
   - `library-audit?app=<sonarr|radarr>&chunk=N` - per-title: tracked files exist on disk, sparse/hollow check (allocated < 95% apparent), missing-monitored + cutoff-unmet counts, untracked orphan files in library dirs, malformed dirs, duplicate versions
2. `GET /arr/<app>/api/v3/...` - read-only GET passthrough to Sonarr/Radarr for ad-hoc agent queries (GET only, enforced).
3. `POST /action/<name>` - whitelist, each idempotent, each re-verifies its target:
   - `restart-prowlarr` (compose down/up prowlarr, then testall on both arrs)
   - `pull-recreate` (service in {gluetun, byparr}; compose pull + down/up of plex-stack pair)
   - `resurrect-stragglers` (compose up -d for Exited(255) containers in known stacks)
   - `queue-remove` (arr queue item id; flags: blocklist, removeData)
   - `search` (arr, movie/episode ids)
   - `delete-download` (path constrained under /docker/plex/media/downloads, never .Trash, sparse/nlink logged, qbit ownership check when creds present)

Shared plumbing (arr key readers, qbit session, sparse detection, TSV/audit helpers) is adapted from `origin/worktree-media-reclaim`'s `scripts/media-reclaim/reclaim_lib.py` - vendored into `scripts/plex-ops/` (the reclaim branch merge is desirable but NOT a build dependency).

## Duties and schedules

| Duty | Cadence | Auto tier (act + one-line receipt) | Approval tier (numbered list in #plex-ops) |
|---|---|---|---|
| Queue triage | every 2h | malware-ext: remove+blocklist+delete data+re-search; not-upgrade: remove+blocklist | mapping-mismatch, sample-stall, unknown |
| Service watchdog | every 30 min | restart-prowlarr, pull-recreate, resurrect-stragglers per known signatures | anything unrecognized -> report with evidence |
| Library health audit | weekly, chunked nightly | none (report-only findings) | integrity fixes, orphan/dupe deletions, gap searches |
| Digest | weekly | post summary: fixed / waiting / disk trajectory | - |

Approval flow: user replies in-channel ("approve 1,3-5" / "all"); the agent then executes via runner. Auto tier is DISABLED for the first week (shadow mode): the agent posts what it *would* do; the current 96-item Sonarr backlog is the acceptance fixture.

## Prevention

- **Recyclarr** composed-app in `nemesis/composed-apps/recyclarr/` syncing TRaSH-guides custom formats + scores into both arrs (block-listed release-group tiers, upscale/AV1-junk/wrong-language CFs). Config in-repo; secrets via `.env`.
- One-time profile hygiene pass (documented, applied via Recyclarr config): stop below-cutoff re-grabs (the 720p-over-1080p / 1080p-over-2160p queue waste).

## Deployment split

- **nemesis (this repo, buildable now):** `scripts/plex-ops/` (runner + probes + actions + lib + tests), `systemd-unit-files/plex-ops-runner.service`, `nemesis/composed-apps/recyclarr/`, runbook README.
- **devastator (follow-up, manual):** create the NanoClaw group with `ncl` (Discord channel `#plex-ops`), mount NFS read-only into the group container, install the agent prompt/skills. Those artifacts are staged in-repo under `docs/plex-ops/group/` (AGENTS.md-style prompt, per-duty skill files with exact probe/action contracts, schedule definitions) with a deploy runbook. Scheduling mechanism: NanoClaw's native scheduler if present in v2.3, else systemd timers on devastator posting scheduled messages via `ncl` - the runbook covers both.
- **Monitoring:** add runner `/probe/service-health` and Prowlarr /ping to Kuma (`status.rt-541.io`) - documented step, done from tarkin.

## Error handling

- Runner down: agent still reaches Discord, posts the alert. Agent/vLLM down: runner does nothing autonomously (intentionally dumb); Kuma covers detection.
- Auth: single bearer token in runner env file (root-owned, 0600) and in the group's container env on devastator; rotation = edit both, restart both.
- Every action logs before/after state; `delete-download` and `queue-remove removeData=true` refuse paths/items that fail their re-verification.
- LAN-only exposure: runner binds 0.0.0.0:8377 with bearer auth, no Traefik route needed (agent hits `nemesis.rt-541.io:8377`); firewalld allows the port from 192.168.1.0/24 only.

## Testing

- Unit: probe classifiers against captured fixtures (the 2026-09-10 queue snapshot classes: malware-ext, not-upgrade, mapping-mismatch, sample-stall).
- Integration: runner started against live APIs, all probes exercised read-only; every action exercised with `dry_run=true` (each action supports it and returns what it would do).
- Acceptance: shadow-mode week on the live 96-item backlog; auto tier enabled only after the user reviews shadow reports.

## Out of scope

- Plex-server-side checks run FROM the agent via HTTP only (PMS reachable, sessions, library scan freshness via Plex API with token); no runner on devastator in v1.
- The media-reclaim transcode campaign (separate, still pending merge/deploy).
- Music stack, game servers.
