# plex-ops action-runner - Runbook

The "hands" half of the plex-ops maintenance suite (design:
`docs/superpowers/specs/2026-09-10-plex-ops-agents-design.md`; binding API:
`CONTRACT.md` in this directory). A python 3.9 stdlib-only HTTP service on
nemesis, port 8377, that serves read-only probes, a GET-only arr passthrough,
and a whitelist of re-verifying actions to the NanoClaw `plex-ops` agent on
devastator. Every authed call is JSON-audit-logged to
`/docker/plex/logs/plex-ops/audit.jsonl`.

Files:

| File | Purpose |
|---|---|
| `runner.py` | HTTP service: routing, bearer auth, error envelope, audit |
| `plexops_lib.py` | shared plumbing (arr/qbit/docker/fs helpers) |
| `probes.py` | read-only probes (`queue-health`, `service-health`, `disk`, `library-audit`) |
| `actions.py` | whitelisted actions (all support `dry_run`) |
| `plex-ops-runner.env.example` | template for `/etc/plex-ops/runner.env` |
| `../../systemd-unit-files/plex-ops-runner.service` | systemd unit |

## Install (on nemesis)

1. **Token + env file** (root:root 0600):

   ```bash
   cd /docker/homelab-config/scripts/plex-ops
   sudo install -D -o root -g root -m 0600 plex-ops-runner.env.example /etc/plex-ops/runner.env
   sudo sed -i "s/^PLEXOPS_TOKEN=.*/PLEXOPS_TOKEN=$(openssl rand -hex 32)/" /etc/plex-ops/runner.env
   sudo grep PLEXOPS_TOKEN /etc/plex-ops/runner.env   # copy for the agent side
   ```

   The runner refuses to start while the token is still the example
   placeholder or shorter than 32 characters, so a skipped/failed `sed`
   fails loudly instead of running on a publicly-known value.

   Optionally add `QBIT_USER`/`QBIT_PASS` (enables the delete-download qbit
   ownership check).

2. **Systemd unit**:

   ```bash
   sudo install -m 0644 /docker/homelab-config/systemd-unit-files/plex-ops-runner.service \
       /etc/systemd/system/plex-ops-runner.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now plex-ops-runner.service
   systemctl status plex-ops-runner.service
   ```

   The unit runs as `aschneider`; the runner does its docker and filesystem
   work through `sudo -n` (same pattern as the other house scripts), so that
   account's passwordless sudo must be in place.

3. **Network restriction** - LAN-only, no Traefik route. The runner has
   bearer auth but no TLS, and by default binds `0.0.0.0:8377` with NO
   network-layer restriction of its own, so this step must actually be
   verified, not assumed.

   **firewalld is NOT running on nemesis** (verified 2026-09-11:
   `systemctl is-active firewalld` -> `inactive`), so the classic
   firewall-cmd recipe fails outright. Pick ONE of:

   a. **Bind to the LAN address (simplest, works today).** In
      `/etc/plex-ops/runner.env` set:

      ```
      BIND=192.168.1.214
      ```

      then restart the service. The runner then never listens on any other
      interface. (This does not distinguish LAN sources, but combined with
      no router port-forward it keeps the port unreachable from outside.)

   b. **nftables rule (no firewalld needed):**

      ```bash
      sudo nft add table inet plexops
      sudo nft add chain inet plexops input '{ type filter hook input priority 0; }'
      sudo nft add rule inet plexops input tcp dport 8377 ip saddr 192.168.1.0/24 accept
      sudo nft add rule inet plexops input tcp dport 8377 drop
      sudo nft list table inet plexops
      # persist: nft list table inet plexops > /etc/nftables.d/plexops.nft (per distro convention)
      ```

   c. **firewalld, if you enable it first** (`sudo systemctl enable --now
      firewalld` - review the impact on the Docker port maps before doing
      this on the live media host). Precondition: the rich rule below only
      RESTRICTS anything if the active zone's target rejects the port by
      default - verify with `sudo firewall-cmd --get-active-zones` and
      `--list-all`. Note that container-originated traffic (docker zone,
      172.x sources) bypasses the source match entirely.

      ```bash
      sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="192.168.1.0/24" port port="8377" protocol="tcp" accept'
      sudo firewall-cmd --reload
      sudo firewall-cmd --list-rich-rules
      ```

   Whichever you pick, verify from a non-LAN vantage (or at minimum confirm
   the router forwards nothing to 8377). Do NOT open 8377 in the router's
   port-forwarding; the agent reaches it as `nemesis.rt-541.io:8377` from
   inside the LAN.

4. **Agent side (devastator, follow-up)**: put the same token into the
   NanoClaw `plex-ops` group's container env. See the deploy runbook under
   `docs/plex-ops/group/`.

## Token rotation

The token lives in exactly two places: `/etc/plex-ops/runner.env` on nemesis
and the plex-ops group container env on devastator.

```bash
sudo sed -i "s/^PLEXOPS_TOKEN=.*/PLEXOPS_TOKEN=$(openssl rand -hex 32)/" /etc/plex-ops/runner.env
sudo systemctl restart plex-ops-runner.service
# then update the group env on devastator and restart that container
```

The runner loads the token once at startup, so a restart is required.

## Smoke tests

```bash
TOKEN=$(sudo grep -oP '^PLEXOPS_TOKEN=\K.*' /etc/plex-ops/runner.env)

# liveness (no auth)
curl -s http://localhost:8377/healthz

# auth is enforced (expect 401 envelope)
curl -s http://localhost:8377/probe/disk

# probes (read-only)
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8377/probe/disk
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8377/probe/service-health
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8377/probe/queue-health
curl -s -H "Authorization: Bearer $TOKEN" \
    "http://localhost:8377/probe/library-audit?app=radarr&chunk=0&chunks=7"

# GET-only arr passthrough (runner injects the api key)
curl -s -H "Authorization: Bearer $TOKEN" \
    http://localhost:8377/arr/sonarr/api/v3/system/status
# non-GET must 405 without touching the arr:
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
    http://localhost:8377/arr/sonarr/api/v3/command

# actions: ALWAYS dry_run first - it returns the exact plan and touches nothing
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"dry_run": true}' http://localhost:8377/action/resurrect-stragglers
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"app": "sonarr", "id": 12345, "blocklist": true, "removeData": true,
         "expect": "malware-ext", "dry_run": true}' \
    http://localhost:8377/action/queue-remove

# every call above (except /healthz) appended one line here:
tail -n 5 /docker/plex/logs/plex-ops/audit.jsonl
```

From the LAN (e.g. devastator): same commands with
`http://nemesis.rt-541.io:8377`.

## Shadow mode

Per the approved design, the agent's auto tier is DISABLED for the first
week: the agent runs probes and posts to the chat channel what it *would* do, but
issues no non-dry-run actions. The runner needs no configuration for this -
shadow mode is enforced on the agent side (its skills call actions with
`"dry_run": true` only). The current 96-item Sonarr backlog is the acceptance
fixture; enable the auto tier only after the user reviews a week of shadow
reports. During shadow week, `audit.jsonl` should show `"dry_run":true` on
every action line - a non-dry-run action there means the agent is
misconfigured.

## Operational notes

- The runner never restarts services on its own and never writes to
  arr/qbit/Plex outside the whitelisted actions; probes are read-only
  (`sudo -n` for filesystem stats). The only files it writes live under
  `/docker/plex/logs/plex-ops/`.
- "Restart" inside actions is always `docker compose down` then `up -d`,
  never `docker compose restart` (compose file / env changes must be
  re-read).
- Runner down: the agent still reaches Discord and reports it. Independent
  detection is Kuma at `status.rt-541.io` (done from tarkin), per the spec
  and `docs/plex-ops/group/DEPLOY.md` Part 2: monitor
  `GET /probe/service-health` with the bearer token as an
  `Authorization: Bearer` custom header (stored server-side in Kuma), plus
  Prowlarr `/ping`. The unauthenticated `GET /healthz` is available as an
  extra cheap liveness monitor but detects process liveness only, not
  sudo/docker/probe-layer breakage.
- Errors: every non-2xx body is the envelope
  `{"ok": false, "error": "<code>", "message": "...", "detail": {}}` -
  codes in `CONTRACT.md` section 2. A 409 `verify-failed` means an action's
  pre/post re-verification refused; the live state is in `detail`.
