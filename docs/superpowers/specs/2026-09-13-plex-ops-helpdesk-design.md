# plex-ops: help desk + MCP surface - Design addendum

**Date:** 2026-09-13
**Status:** APPROVED in conversation (user: the agent serves a select group of users in one Discord channel; channel membership is the authorization; MCP over the existing runner; minimal personality, no emojis, KISS)
**Amends:** `2026-09-10-plex-ops-agents-design.md`

## Change

The 09-10 design built a maintenance loop reporting to Arthur. The primary
use is a help desk: a user in channel `<channel-id>` says "episode X
is missing" or "this file is bad", the agent verifies and fixes it. The
maintenance duties stay, as a second consumer of the same tools, reporting
to `#plex-ops`.

## Decisions

- **Runner stays the enforcement boundary.** No generic arr MCP (full write
  API, no re-verification, no audit). The runner gains an MCP endpoint
  (`POST /mcp`, JSON-RPC 2.0, stateless streamable HTTP) exposing the
  existing probes/actions/passthrough as typed tools, so the 14B local model
  gets schemas instead of hand-written curl. Same auth, same audit log.
- **Two new item actions, one item each:** `replace-file` (mark the newest
  grab/import history failed so the arr blocklists the release, delete the
  file via the arr, search) and `fill-missing` (monitor if needed, search).
  Both refuse on the wrong file state (409). Whole seasons/series, profile
  changes, and additions are out of scope: the agent answers "Ask Arthur."
- **`lookup` probe** resolves a casual title (plus season/episode) to ids and
  file state; `resolved_id` is set only for an unambiguous match, otherwise
  the agent asks the user which.
- **Authorization = channel membership.** Messaging group policy `public`,
  engage on @mention only. Help desk actions execute immediately (not
  tiered, not shadowed). Maintenance auto-tier remains shadow-first.
- **Follow-up:** after a fix the agent schedules one one-shot task 20 min
  out to re-`lookup` and report downloaded / still searching.
- **Persona:** terse, factual, no emojis, no greetings.

## Not chosen

- Overseerr/Jellyseerr as the request front door: viable, deferred; the
  users are few and already in Discord.
- Routing runtime actions through kuat-drive-yards/tarkin: rejected for
  blast radius (fleet key on tarkin) and latency; deployment of the runner
  should still move to a kuat-drive-yards playbook (open item).
