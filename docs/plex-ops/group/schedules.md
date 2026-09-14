# plex-ops schedules

Cadences from the approved design (all times America/Detroit, the fleet TZ):

| Duty | Cadence | Cron | Task name | Gate |
|---|---|---|---|---|
| Queue triage | every 2h | `15 */2 * * *` | `plexops-queue-triage` | `gates/triage-gate.sh` |
| Service watchdog | every 30 min | `*/30 * * * *` | `plexops-watchdog` | `gates/watchdog-gate.sh` |
| Library audit, nightly chunk | nightly 03:30 | `30 3 * * *` | `plexops-audit-chunk` | none |
| Library audit, weekly rollup | Sunday 08:00 | `0 8 * * 0` | `plexops-audit-rollup` | none |
| Digest | Sunday 09:00 | `0 9 * * 0` | `plexops-digest` | none |

Offsets are deliberate: triage at :15 so it never lands on a watchdog tick;
the nightly chunk runs at 03:30 (after the runner host's own 04:00 backup
sidecars is fine - the probe is read-only - but 03:30 keeps them apart
anyway); Sunday's final chunk (chunk 6, 03:30) precedes the rollup (08:00),
which precedes the digest (09:00), so the digest sees the finished week.

## Gates (why the two frequent tasks carry a script)

NanoClaw on the devastator checkout refuses any recurrence above 4 fires/day
unless the task has a `--script` gate (or an explicit override). Triage
(12/day) and watchdog (48/day) are therefore gated. A gate is a bash script
the agent-runner executes INSIDE the group's container before the model
wakes (30s cap; the container has bash, curl and node, but no jq or
python); its last stdout line is `{"wakeAgent": <bool>, "data": {...}}`.
`false` marks the run handled at zero model-token cost; `true` wakes the
agent with `data` attached to the prompt.

- `gates/watchdog-gate.sh` polls `/probe/service-health` and wakes on:
  prowlarr ping failed or CPU above 150%, any listed container not running
  or unhealthy or missing, any Exited(255) straggler, VPN egress failed.
  Runner unreachable: wakes once per 6 hours (state file under
  `/workspace/agent/gate-state/`, i.e. `groups/plex-ops/gate-state/` on the
  host), so an outage is one alert, not 48.
- `gates/triage-gate.sh` polls `/probe/queue-health` and wakes when either
  app reports an error or any item classifies as `malware-ext`,
  `not-upgrade`, `mapping-mismatch`, or `sample-stall`. Healthy in-progress
  items (`unknown`) never wake it.

Both read `RUNNER_URL` / `RUNNER_TOKEN` from the container environment
(the group's stored env), falling back to `~/.config/plex-ops/runner.env`
so the deploy script can self-test them on the host. The agent treats gate
data as a hint and re-runs the probe itself.

## Mechanism A (preferred): NanoClaw's native scheduler

`deploy-devastator.sh tasks` runs exactly this, skipping tasks that already
exist (matched by name prefix in `ncl tasks list`). By hand, from
`/docker/nanoclaw` with `<gid>` = the plex-ops agent-group id from
`./bin/ncl groups list` and `ART` = this directory:

```bash
./bin/ncl tasks create --group <gid> --name plexops-queue-triage \
  --recurrence "15 */2 * * *" --script "$(cat $ART/gates/triage-gate.sh)" \
  --prompt "Scheduled run: invoke the plexops-queue-triage skill and execute it now. The data attached to this prompt is the gate's queue-health summary that triggered the run. Post results to #plex-ops."

./bin/ncl tasks create --group <gid> --name plexops-watchdog \
  --recurrence "*/30 * * * *" --script "$(cat $ART/gates/watchdog-gate.sh)" \
  --prompt "Scheduled run: invoke the plexops-service-watchdog skill and execute it now. The data attached to this prompt is the gate's service-health summary that triggered the run. Post to #plex-ops only if something needs action or approval."

./bin/ncl tasks create --group <gid> --name plexops-audit-chunk \
  --recurrence "30 3 * * *" \
  --prompt "Scheduled run: invoke the plexops-library-audit skill and run the nightly chunk for today's weekday. Log to memory; post to #plex-ops only if urgent."

./bin/ncl tasks create --group <gid> --name plexops-audit-rollup \
  --recurrence "0 8 * * 0" \
  --prompt "Scheduled run: invoke the plexops-library-audit skill and run the weekly rollup. Post the summary and approval list to #plex-ops."

./bin/ncl tasks create --group <gid> --name plexops-digest \
  --recurrence "0 9 * * 0" \
  --prompt "Scheduled run: invoke the plexops-digest skill and post the weekly digest to #plex-ops."
```

Cron is interpreted in the group timezone (`America/Detroit`). Test a task
once without touching its schedule: `./bin/ncl tasks run <task-id>` (ids
from `./bin/ncl tasks list`). Every run appends a work-log line under
`groups/plex-ops/tasks/`. Record the five slots in
`/docker/nanoclaw/docs/task-schedule.md` (the fleet's maintenance-window
ledger); the watchdog's `*/30` tick means there is no fully quiet window,
and watchdog noise during maintenance is ignorable.

NanoClaw ships breaking changes often: if a flag above is rejected, check
`./bin/ncl tasks create --help` and adjust both this file and the deploy
script.

## Mechanism B (fallback): systemd timers on devastator + ncl

If the checkout's native recurrence is absent or broken, drive the same
five task prompts from host systemd timers. Create each task WITHOUT a
recurrence (one-off definitions the scheduler will not fire), and have a
system timer trigger it with `ncl tasks run` on the cadence. The gate logic
then moves into the timer's `ExecStart` (run the gate script, and only call
`ncl tasks run` when its last line says `"wakeAgent": true`).

1. Create the five tasks as above but with no `--recurrence` (or
   `--process-after` far in the future if the CLI requires one). Note each
   task id from `./bin/ncl tasks list`.

2. Unit files (system units, not user units, so they survive logout; run as
   the account that owns the checkout). Example for the queue triage,
   `/etc/systemd/system/plexops-queue-triage.service`:

   ```ini
   [Unit]
   Description=plex-ops queue triage trigger (ncl tasks run)
   After=network-online.target

   [Service]
   Type=oneshot
   User=aschneider
   WorkingDirectory=/docker/nanoclaw
   ExecStart=/bin/bash -c 'bash /docker/homelab-config/docs/plex-ops/group/gates/triage-gate.sh | tail -n1 | grep -q "\"wakeAgent\": *true" && /docker/nanoclaw/bin/ncl tasks run TASK_ID_HERE || true'
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

   The ungated units call `ncl tasks run` directly.

4. Enable:

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now plexops-queue-triage.timer plexops-watchdog.timer \
     plexops-audit-chunk.timer plexops-audit-rollup.timer plexops-digest.timer
   systemctl list-timers 'plexops-*'
   ```

5. Verify one end-to-end: `sudo systemctl start plexops-queue-triage.service`
   and watch `#plex-ops` for the triage post (in shadow week: the SHADOW
   lines).
