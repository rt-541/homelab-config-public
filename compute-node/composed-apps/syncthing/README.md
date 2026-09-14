# syncthing (devastator)

Replicates the Obsidian vault `projects/` folders from rocinante to devastator
so an internal agent fleet can mount them read-write. Rocinante stays the
source of truth; devastator is a live replica that agents append to.

| Rocinante (source)                | Devastator (replica)                |
|------------------------------------|--------------------------------------|
| `C:\obsidian\<vault>\projects`    | `/docker/obsidian/<vault>/projects` |

Only the `projects/` subtrees are shared. `.obsidian/`, attachments, and the
rest of each vault never leave rocinante.

## Sidecars

- `syncthing-autoheal`: restarts the container on a failed healthcheck.
- `syncthing-backup`: nightly 04:00 tarball of `/docker/syncthing/config`
  (device keys and folder config) into `/docker/syncthing/backups`, 21-day
  retention. Vault data is not backed up here; rocinante holds it.
- `syncthing-discord`: posts up/down to the webhook in `.env`.
- `syncthing-logs`: Dozzle on port 9998, filtered to `syncthing*`.

## One-time setup

### 1. Devastator

```
sudo mkdir -p /docker/syncthing/config /docker/syncthing/backups \
  /docker/obsidian/<vault-a>/projects /docker/obsidian/<vault-b>/projects
sudo chown -R 1000:1000 /docker/syncthing /docker/obsidian
cd /docker/homelab-config/compute-node/composed-apps/syncthing
cp .env.example .env   # then paste the webhook URL
sudo docker compose up -d
```

Get devastator's device ID and API key:

```
sudo docker exec syncthing syncthing --device-id
sudo docker exec syncthing sh -c 'grep -o "<apikey>[^<]*" /var/syncthing/config/config.xml'
```

The web UI is `http://devastator.rt-541.io:8384`, LAN only, and the
container binds to all interfaces, so it has GUI auth. Set a GUI username
and password from Settings > GUI at first bring-up.

### 2. Rocinante (Windows)

Install with Chocolatey from an elevated shell:

```
choco install syncthing -y
```

The package installs the binary only (v2.1.3 as of 2026-09-02, exposed via
the Chocolatey shim). Run it as a logon task so it survives reboot (Task
Scheduler is what Syncthing's own docs recommend on Windows):

```
schtasks /Create /TN "Syncthing" /SC ONLOGON /RL LIMITED /F ^
  /TR "\"C:\ProgramData\chocolatey\bin\syncthing.exe\" serve --no-console --no-browser"
schtasks /Run /TN "Syncthing"
```

Config lives in `%LOCALAPPDATA%\Syncthing`. The GUI at `http://127.0.0.1:8384`
binds to loopback only; set a GUI password there anyway. Device ID is under
Actions > Show ID, or from PowerShell:

```
[xml]$c = Get-Content $env:LOCALAPPDATA\Syncthing\config.xml
(Invoke-RestMethod http://127.0.0.1:8384/rest/system/status -Headers @{"X-API-Key"=$c.configuration.gui.apikey}).myID
```

Note the version split: devastator runs the `syncthing/syncthing:1` image
(v1.30) and roci runs v2.1. The sync protocol is the same and they pair fine;
bump the container to `:2` when convenient so both sides match.

### 3. Pair and share (either side's UI, or the REST API)

On devastator's UI: Add Remote Device, paste rocinante's ID, name it
`rocinante`, and under Advanced set the address to
`tcp://rocinante.rt-541.io:22000` (local discovery is not published from the
container). On rocinante's UI accept the incoming device request from
`devastator`.

On rocinante, add two folders and share each with `devastator`:

| Folder ID          | Path on rocinante                    |
|--------------------|----------------------------------------|
| `vault-a-projects` | `C:\obsidian\<vault-a>\projects`      |
| `vault-b-projects` | `C:\obsidian\<vault-b>\projects`      |

Set ignore patterns on each (Edit > Ignore Patterns):

```
.obsidian
.trash
*.sync-conflict-*   // keep conflicts on the side that made them
```

On devastator, accept both folder offers and set their paths to
`/var/syncthing/obsidian/<vault-a>/projects` and
`/var/syncthing/obsidian/<vault-b>/projects`. Folder type is
Send & Receive on both ends; agents append on devastator and you edit on
rocinante.

### 4. Verify

Create a file in `C:\obsidian\<vault-a>\projects\example\` on rocinante and
confirm it appears under `/docker/obsidian/<vault-a>/projects/example/`
within a minute, then append a line from devastator and confirm it lands on
rocinante. Both folders should show "Up to Date" in both UIs.

## Restart

Always down then up from this directory, never `docker restart`:

```
cd /docker/homelab-config/compute-node/composed-apps/syncthing
sudo docker compose down
sudo docker compose up -d
```

## Failure modes the agents are told about

- A `*.sync-conflict-<date>-<id>.md` file beside a note means both sides
  changed it before sync. Agents stop writing that note and report it; you
  resolve it on rocinante.
- If rocinante is asleep or the task is not running, devastator keeps
  accepting agent writes and pushes them when the peer returns. Nothing is
  lost, but the vault on rocinante is stale until then.
