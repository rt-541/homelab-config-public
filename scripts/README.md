# Nemesis Server Scripts

Utility scripts for managing Docker Compose stacks and server operations.

## Docker Compose Manager

**Main script:** `compose-manager.sh` - Unified tool to manage all compose stacks

### Usage

```bash
sudo /docker/homelab-config/scripts/compose-manager.sh {start|stop|restart|status} [app-name]
```

### Commands

#### Start All Stacks
```bash
sudo ./compose-manager.sh start
```
- Auto-discovers all compose files in `composed-apps/`
- Starts each stack with `docker compose up -d`
- Shows: ▶ Starting, ✓ Started/Already running, ✗ Failed
- Excludes `nvidia-test` by default
- Summary: successful/failed/skipped counts

#### Stop All Stacks
```bash
sudo ./compose-manager.sh stop
```
- Gracefully stops all stacks with `docker compose down`
- ⚠️ **Warning**: Includes critical infrastructure (Traefik, Pi-hole, Plex)

#### Restart All Stacks
```bash
sudo ./compose-manager.sh restart
```
- Stops then starts all stacks
- 2-second pause between stop and start

#### Check Status
```bash
sudo ./compose-manager.sh status
```
- Shows: ● Running (green), ◐ Partial (yellow), ○ Stopped (gray)
- Displays container counts per stack (e.g., "2/2 containers")
- Quick overview of entire infrastructure

### Single Stack Operations

You can target a specific app by adding its name:

```bash
# Start only Zomboid
sudo ./compose-manager.sh start zomboid

# Stop only Minecraft
sudo ./compose-manager.sh stop minecraft-atm9-survival

# Restart Plex stack
sudo ./compose-manager.sh restart plex-stack
```

### Example Output

```
========================================
Starting Docker Compose Stacks
========================================

▶ Starting: abiotic-factor ... ✓ Started
▶ Starting: minecraft-atm9-survival ... ✓ Already running
⊘ Skipping: nvidia-test (excluded)
▶ Starting: plex-stack ... ✓ Started
...

========================================
Summary
========================================
Total stacks:    24
Successful:      23
Failed:          0
Skipped:         1

All stacks processed successfully!
```

## Customization

### Excluding Stacks

Edit the `EXCLUDE_DIRS` array in `compose-manager.sh`:

```bash
EXCLUDE_DIRS=("nvidia-test" "traefik" "pihole")
```

This prevents these stacks from being started/stopped during "all" operations.

## Other Existing Scripts

- `backup_minecraft.sh` - Manual Minecraft backup utility
- `docker-clean.sh` - Docker system cleanup
- `move_smallest_50.bash` - Media management script
- `rsync-local-mount.sh` - Local mount synchronization
- `find-and-copy.sh` - File search and copy utility
- `local-scp-copy.sh` - Local SCP operations

## Adding New Scripts

When adding new scripts to this directory:
1. Use clear, descriptive names with `.sh` extension
2. Make executable: `chmod +x script-name.sh`
3. Add shebang: `#!/bin/bash`
4. Document in this README
5. Follow existing patterns for consistency (colors, error handling, etc.)
