# Skill: reclaim (compression waves)

The 4K remux movie library is being compressed in waves on a GPU worker
(`media-transcoder`) that only encodes inside its windows (nightly
22:30-06:30, work-day 08:30-16:30 Mon-Fri). The worker reads a queue on the
media share; you decide what goes in the queue. Tools: `reclaim_status`,
`reclaim_plan`, `reclaim_schedule`, `reclaim_pause`, `reclaim_resume`,
`reclaim_pilot_ack`. Only Arthur (`rt-541`) may call the last four; anyone
may ask for status or a plan.

## "What can we compress tonight?"

1. `reclaim_plan` with `window: "tonight"` (or `"workday"` / `"next"`, or
   `hours` when Arthur names a duration). It picks the largest expected
   gains that fit the window at the configured throughput and groups them
   by source size: large >= 60 GiB, medium 40-60, small < 40.
2. Reply in this shape, nothing more:

   ```
   Tonight 22:30-06:30 (8.0 h): 4 large, 2 medium, 1 small. Est. gain 310 GiB, 7.4 h.
   Forrest Gump (1994) 87 GiB -> ~24 · Oppenheimer (2023) 82 -> ~23 · ... (one line, all titles)
   Say "run it" to queue this wave.
   ```

   Append the plan's `notes` (paused, pilot gate) as one line each when present.
3. When Arthur says run it (any clear wording): `reclaim_schedule` with the
   same `window` (or the exact `titles` if he changed the list). Reply with
   the receipt: `Queued N titles, est. gain X GiB. Worker starts at <start>.`
   If the reply names a subset ("just the large ones", "skip Tenet"), pass
   `titles` with exactly the remaining titles from the plan.
4. `reclaim_schedule` REPLACES the queue. Say so if the status showed
   remaining queued titles that will drop out.

## Status questions

`reclaim_status` for "how is the compression going", "how much have we
saved", "is the worker running". Reply with: done / remaining / failed
counts, GiB saved, current or next window, worker status line, and the
flags (paused, pilot gate) when set. One or two lines.

## Pilot gate and pause

- The worker stops after `pilot_limit` encodes until `reclaim_pilot_ack`.
  When status shows the gate, tell Arthur: verify playback and HDR of the
  first encodes on a real client, then say "pilot ack".
- "pause compression" -> `reclaim_pause`; "resume" -> `reclaim_resume`.
  A running encode finishes first.

## Rules

- Keep-list titles (Dune, the Alien franchise, LOTR extended) never appear;
  if Arthur asks for one, say it is on the keep list.
- Never schedule for a user other than Arthur; answer their plan or status
  question and stop.
- Estimates are estimates: quote `est_` numbers as "about".
- `refresh: true` re-scans the libraries (about a minute); use it when the
  report is older than a day or Arthur says the library changed.
