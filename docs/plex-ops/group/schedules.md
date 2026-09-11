# plex-ops schedules

Cadences from the approved design (all times America/Detroit, the fleet TZ):

| Duty | Cadence | Cron | Task name |
|---|---|---|---|
| Queue triage | every 2h | `15 */2 * * *` | `plexops-queue-triage` |
| Service watchdog | every 30 min | `*/30 * * * *` | `plexops-watchdog` |
| Library audit, nightly chunk | nightly 03:30 | `30 3 * * *` | `plexops-audit-chunk` |
| Library audit, weekly rollup | Sunday 08:00 | `0 8 * * 0` | `plexops-audit-rollup` |
| Digest | Sunday 09:00 | `0 9 * * 0` | `plexops-digest` |

Offsets are deliberate: triage at :15 so it never lands on a watchdog tick;
the nightly chunk runs at 03:30 (after the runner host's own 04:00 backup
sidecars is fine - the probe is read-only - but 03:30 keeps them apart
anyway); Sunday's final chunk (chunk 6, 03:30) precedes the rollup (08:00),
which precedes the digest (09:00), so the digest sees the finished week.

Task prompts (used verbatim by both mechanisms below - the prompt must name
the duty and the destination):

- `plexops-queue-triage`: "Scheduled run: execute the queue-triage skill now
  and post results to the chat channel."
- `plexops-watchdog`: "Scheduled run: execute the service-watchdog skill now.
  Post to the chat channel only if something needs action or approval."
- `plexops-audit-chunk`: "Scheduled run: execute the library-audit nightly
  chunk for today's weekday. Log to memory; post to the chat channel only if
  urgent."
- `plexops-audit-rollup`: "Scheduled run: execute the library-audit weekly
  rollup and post the summary and approval list to the chat channel."
- `plexops-digest`: "Scheduled run: execute the digest skill and post the
  weekly digest to the chat channel."

## Mechanism A (preferred): NanoClaw's native scheduler

The checkout on devastator (`/docker/nanoclaw`, main at `5c3082a1`,
v2.3-era) has a native scheduler: `ncl tasks` - already in production use by
the vault groups (nightly catchers, stale sweeps). If `./bin/ncl tasks
--help` works, use it; only fall back to Mechanism B if this checkout ever
loses it.

From `/docker/nanoclaw`, with `<gid>` = the plex-ops agent-group id from
`./bin/ncl groups list`:

```bash
./bin/ncl tasks create --group <gid> --name plexops-queue-triage \
  --recurrence "15 */2 * * *" \
  --prompt "Scheduled run: execute the queue-triage skill now and post results to the chat channel."

./bin/ncl tasks create --group <gid> --name plexops-watchdog \
  --recurrence "*/30 * * * *" \
  --prompt "Scheduled run: execute the service-watchdog skill now. Post to the chat channel only if something needs action or approval."

./bin/ncl tasks create --group <gid> --name plexops-audit-chunk \
  --recurrence "30 3 * * *" \
  --prompt "Scheduled run: execute the library-audit nightly chunk for today's weekday. Log to memory; post to the chat channel only if urgent."

./bin/ncl tasks create --group <gid> --name plexops-audit-rollup \
  --recurrence "0 8 * * 0" \
  --prompt "Scheduled run: execute the library-audit weekly rollup and post the summary and approval list to the chat channel."

./bin/ncl tasks create --group <gid> --name plexops-digest \
  --recurrence "0 9 * * 0" \
  --prompt "Scheduled run: execute the digest skill and post the weekly digest to the chat channel."
```

Cron is interpreted in the fleet TZ (`TZ=America/Detroit` was set by the
installer). Per fleet convention, every run appends a work-log line to
`groups/plex-ops/tasks/<name>-<id>.md`.

Test each task once without touching its schedule:

```bash
./bin/ncl tasks run <task-id>     # ids from: ./bin/ncl tasks list
```

Also record the five slots in `/docker/nanoclaw/docs/task-schedule.md` (the
fleet's maintenance-window ledger). The watchdog's `*/30` tick means there
is no fully quiet window; the runbook treats watchdog noise as ignorable
during maintenance.

NanoClaw ships breaking changes often: verify flag names against
`./bin/ncl tasks create --help` in the actual checkout before running the
block above, and adjust in place if a flag was renamed.

## Mechanism B (fallback): systemd timers on devastator + ncl

If the checkout's native recurrence is absent or broken, drive the same
five task prompts from host systemd timers. The pattern: create each task
WITHOUT a recurrence (one-off definitions the scheduler will not fire), and
have a system timer trigger it with `ncl tasks run` on the cadence.

1. Create the five tasks as above but with no `--recurrence` (or
   `--process-after` far in the future if the CLI requires one). Note each
   task id from `./bin/ncl tasks list`.

2. Unit files (system units, not user units, so they survive logout; run as
   the account that owns the checkout). One pair per duty - example for the
   queue triage, `/etc/systemd/system/plexops-queue-triage.service`:

   ```ini
   [Unit]
   Description=plex-ops queue triage trigger (ncl tasks run)
   After=network-online.target

   [Service]
   Type=oneshot
   User=aschneider
   WorkingDirectory=/docker/nanoclaw
   ExecStart=/docker/nanoclaw/bin/ncl tasks run TASK_ID_HERE
   ```

   `/etc/systemd/system/plexops-queue-triage.timer`:

   ```ini
   [Unit]
   Description=plex-ops queue triage every 2h at :15

   [Timer]
   OnCalendar=0/2:15
   Persistent=false

   [Install]
   WantedBy=timers.target
   ```

   `Persistent=false` on every timer: a missed maintenance window must not
   fire a burst of stale runs at boot.

3. OnCalendar values for the other four (systemd calendar syntax, host TZ is
   already America/Detroit):

   | Timer | OnCalendar |
   |---|---|
   | `plexops-watchdog.timer` | `*:00/30` |
   | `plexops-audit-chunk.timer` | `*-*-* 03:30` |
   | `plexops-audit-rollup.timer` | `Sun *-*-* 08:00` |
   | `plexops-digest.timer` | `Sun *-*-* 09:00` |

   The service units are identical apart from `Description` and the task id.

4. Enable:

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now plexops-queue-triage.timer plexops-watchdog.timer \
     plexops-audit-chunk.timer plexops-audit-rollup.timer plexops-digest.timer
   systemctl list-timers 'plexops-*'
   ```

5. Verify one end-to-end: `sudo systemctl start plexops-queue-triage.service`
   and watch the chat channel for the triage post (in shadow week: the SHADOW
   lines).

If `ncl tasks run` does not exist on the checkout either, the last-resort
trigger is whatever message-injection subcommand the checkout provides
(check `./bin/ncl --help`); the timer/unit skeleton above stays the same,
only `ExecStart` changes.
