# Nemesis Mission Systems — Discord Bot

A self-hosted Discord bot that monitors Docker containers and exposes self-service slash commands. Replaces the shell-based `container-monitor`.

---

## What It Does

- Sends Discord alerts when any container starts, stops, or crashes
- Sends a daily status report at 8 AM UTC
- Checks Steam Workshop for mod updates on configured game servers
- Exposes slash commands (`/status`, `/start`, `/stop`, `/restart`) gated by Discord role

---

## Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show available commands and your accessible containers |
| `/status` | Show current state, health, and uptime of your containers |
| `/start <container>` | Start a stopped container |
| `/stop <container>` | Stop a running container |
| `/restart <container>` | Restart a container |

Commands only show and allow access to containers permitted by the user's Discord role. Admins see everything.

---

## Setup

### 1. Discord Application

1. Go to https://discord.com/developers/applications
2. Create a new application named **Nemesis Mission Systems**
3. Go to **Bot** -> enable **Message Content Intent** under Privileged Gateway Intents
4. Under **Bot** -> disable **Public Bot**
5. Copy the bot token

### 2. Invite the Bot

Use the OAuth2 URL Generator:
- Scope: `bot`
- Permissions: `View Channels`, `Send Messages`, `Embed Links`

Open the generated URL and add the bot to your server.

### 3. Create Discord Roles

Create one role per access group in your server. Right-click each role -> Copy Role ID (requires Developer Mode enabled in Discord settings).

### 4. Configure `.env`

Copy `.env.example` to `.env` and fill in values:

```
DISCORD_TOKEN=your-bot-token

ROLE_ADMIN_ID=
ROLE_PLEX_ID=
ROLE_ZOMBOID_ID=
ROLE_MINECRAFT_ID=

DEFAULT_WEBHOOK_URL=
ZOMBOID_WEBHOOK_URL=
ATM9S_WEBHOOK_URL=
```

Role IDs are secrets and live only in `.env`. Role names and container lists are defined in `docker-compose.yml`.

### 5. Deploy

```bash
cd composed-apps/nemesis-bot
sudo docker compose build
sudo docker compose up -d
sudo docker compose logs -f
```

---

## Managing Roles

Roles are defined entirely in `docker-compose.yml` — no code changes needed.

Each role requires three environment variables:

| Variable | Description |
|----------|-------------|
| `ROLE_<KEY>_ID` | Discord role ID (set in `.env`) |
| `ROLE_<KEY>_NAME` | Display name (set in `docker-compose.yml`) |
| `ROLE_<KEY>_CONTAINERS` | Comma-separated container names, or `*` for admin |

**To add a new role:**

1. Create the role in Discord, copy its ID
2. Add `ROLE_<KEY>_ID=<id>` to `.env`
3. Add to `docker-compose.yml`:
   ```yaml
   ROLE_<KEY>_NAME: "Role Display Name"
   ROLE_<KEY>_CONTAINERS: "container-one,container-two"
   ```
4. Restart the bot:
   ```bash
   sudo docker compose down && sudo docker compose up -d
   ```

**To add a container to an existing role**, edit the `ROLE_<KEY>_CONTAINERS` line in `docker-compose.yml` and restart.

**To assign a role to a user**, assign the Discord role in your server settings. No bot restart needed.

---

## Configuration (`config.yml`)

| Section | Purpose |
|---------|---------|
| `bot` | Status message shown in Discord |
| `defaults` | Webhook username, footer, and embed colors for container events |
| `status_report` | Daily report schedule and what to include |
| `exclude` | Containers to ignore for event monitoring |
| `mod_monitor.servers` | Steam Workshop mod update checker per game server |
| `overrides` | Per-container display name, webhook, and custom messages |

---

## Mod Monitor

Checks Steam Workshop for updates on a schedule and notifies via webhook. Can optionally auto-restart the server to pick up updates.

Configured under `mod_monitor.servers` in `config.yml`. Requires the game's `appworkshop_<appid>.acf` file to be bind-mounted into the container (already set up for Zomboid prod and dev in `docker-compose.yml`).

---

## File Structure

```
nemesis-bot/
  main.py              # Entrypoint — wires bot, event stream, schedules
  bot_commands.py      # Slash commands with role-gated access
  event_monitor.py     # Docker event stream -> Discord alerts
  status_report.py     # Daily container status report
  mod_monitor.py       # Steam Workshop mod staleness checker
  stats.py             # Container inspect, start, stop, restart helpers
  notifier.py          # Discord webhook sender
  config.yml           # Bot and monitor configuration
  docker-compose.yml   # Deployment — roles defined here
  .env                 # Secrets (not committed)
  .env.example         # Template for .env
  state/               # Persistent state for mod monitor dedup
```
