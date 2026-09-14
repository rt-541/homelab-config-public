#!/bin/bash
# deploy-nemesis.sh - idempotent bring-up of the nemesis half of the plex-ops
# suite (runner service, NFS export for the agent, Recyclarr). Codifies the
# README "Install" steps and DEPLOY.md Part 1.1 (nemesis side).
#
#   sudo bash deploy-nemesis.sh runner [--worktree <repo-path>]
#   sudo bash deploy-nemesis.sh nfs
#   sudo bash deploy-nemesis.sh recyclarr [--apply]
#   sudo bash deploy-nemesis.sh all [--worktree <repo-path>] [--apply]
#   bash      deploy-nemesis.sh push-token <host>      # NOT sudo: uses your ssh keys
#   sudo bash deploy-nemesis.sh smoke
#
# --worktree <path>: run the service from a git worktree instead of the main
#   checkout (a systemd drop-in overrides ExecStart/WorkingDirectory). Used
#   while branch worktree-plex-ops is unmerged. Re-run `runner` WITHOUT the
#   flag after the merge to drop the override.
# --apply: after the Recyclarr preview, actually sync and start the cron
#   container. Without it only the preview runs (touches nothing).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"          # scripts/plex-ops
REPO="$(cd "$HERE/../.." && pwd)"                              # repo root
MAIN_REPO=/docker/homelab-config
ENV_FILE=/etc/plex-ops/runner.env
UNIT_SRC="$REPO/systemd-unit-files/plex-ops-runner.service"
UNIT=/etc/systemd/system/plex-ops-runner.service
DROPIN_DIR=/etc/systemd/system/plex-ops-runner.service.d
DROPIN="$DROPIN_DIR/worktree.conf"
LOG_ROOT=/docker/plex/logs/plex-ops
LAN_BIND=192.168.1.214
NFS_CLIENT=192.168.1.216            # devastator (DHCP reservation on the HA Pi-hole pair)
NFS_EXPORT=/docker/plex/media
RECYCLARR_DIR="$REPO/data-host/composed-apps/recyclarr"
RECYCLARR_STATE=/docker/recyclarr

log() { printf '[deploy-nemesis] %s\n' "$*"; }
need_root() { [ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }; }

token() { grep -oP '^PLEXOPS_TOKEN=\K.*' "$ENV_FILE"; }

do_runner() {
  need_root
  local worktree="${1:-}"
  if [ ! -f "$ENV_FILE" ]; then
    install -D -o root -g root -m 0600 "$HERE/plex-ops-runner.env.example" "$ENV_FILE"
    local t; t=$(openssl rand -hex 32)
    sed -i "s/^PLEXOPS_TOKEN=.*/PLEXOPS_TOKEN=$t/" "$ENV_FILE"
    log "created $ENV_FILE with a fresh token"
  else
    log "$ENV_FILE exists, token kept"
  fi
  if grep -q '^PLEXOPS_TOKEN=CHANGE_ME' "$ENV_FILE" || [ "$(token | wc -c)" -lt 33 ]; then
    echo "token in $ENV_FILE is the placeholder or too short" >&2; exit 1
  fi
  # LAN-only exposure (README step 3a): bind the LAN address, never 0.0.0.0.
  if grep -q '^BIND=' "$ENV_FILE"; then
    sed -i "s/^BIND=.*/BIND=$LAN_BIND/" "$ENV_FILE"
  else
    sed -i "s/^#BIND=.*/BIND=$LAN_BIND/" "$ENV_FILE"
    grep -q '^BIND=' "$ENV_FILE" || echo "BIND=$LAN_BIND" >> "$ENV_FILE"
  fi
  log "BIND=$LAN_BIND"

  install -m 0644 "$UNIT_SRC" "$UNIT"
  if [ -n "$worktree" ]; then
    install -d -m 0755 "$DROPIN_DIR"
    cat > "$DROPIN" <<DROP
# TEMPORARY: run from a git worktree until its branch is merged into main.
# Remove by re-running: sudo bash deploy-nemesis.sh runner   (no --worktree)
[Service]
ExecStart=
ExecStart=/usr/bin/python3 $worktree/scripts/plex-ops/runner.py
WorkingDirectory=$worktree/scripts/plex-ops
DROP
    log "worktree drop-in -> $worktree"
  elif [ -f "$DROPIN" ]; then
    rm -f "$DROPIN"; rmdir "$DROPIN_DIR" 2>/dev/null || true
    log "removed worktree drop-in (running from $MAIN_REPO)"
  fi
  install -d -m 0755 "$LOG_ROOT"
  systemctl daemon-reload
  systemctl enable plex-ops-runner.service >/dev/null 2>&1 || true
  systemctl restart plex-ops-runner.service
  sleep 2
  systemctl --no-pager --lines=5 status plex-ops-runner.service || true
  do_smoke
}

do_smoke() {
  need_root
  local base="http://$LAN_BIND:8377" t; t=$(token)
  log "healthz:      $(curl -s -m 5 "$base/healthz")"
  log "no-auth:      $(curl -s -m 5 -o /dev/null -w '%{http_code}' "$base/probe/disk") (expect 401)"
  log "probe/disk:   $(curl -s -m 20 -H "Authorization: Bearer $t" "$base/probe/disk" | head -c 160)"
  log "service-health ok: $(curl -s -m 60 -H "Authorization: Bearer $t" "$base/probe/service-health" | grep -o '"ok": *true' | head -1)"
  log "dry-run resurrect: $(curl -s -m 60 -X POST -H "Authorization: Bearer $t" -H 'Content-Type: application/json' -d '{"dry_run": true}' "$base/action/resurrect-stragglers" | head -c 160)"
  log "listening on: $(ss -ltn | grep ':8377' | awk '{print $4}' | tr '\n' ' ') (must be $LAN_BIND only)"
  log "audit tail:"; tail -n 3 "$LOG_ROOT/audit.jsonl" 2>/dev/null | cut -c1-160 || true
}

do_nfs() {
  need_root
  # nemesis already serves the media tree over NFSv4 from the plex-stack
  # `nfs` service (container plex-nfs, erichough/nfs-server, port 2049):
  #   NFS_EXPORT_0: /nfs 192.168.1.0/24(rw,fsid=0,crossmnt,...)  with
  #   /docker/plex/media -> /nfs/media, /docker/plex/media2 -> /nfs/media2
  # so the client mounts `nemesis.rt-541.io:/media`. A kernel nfs-server
  # cannot bind 2049 next to it; do not enable one. Read-only is enforced
  # on the client (fstab `ro` + the agent container's read-only mount);
  # a server-side ro entry for $NFS_CLIENT is an open hardening item in
  # plex-stack's compose (NFS_EXPORT_1).
  if systemctl is-enabled --quiet nfs-server 2>/dev/null || systemctl is-active --quiet nfs-server; then
    systemctl disable --now nfs-server
    log "disabled the kernel nfs-server (conflicts with plex-nfs on 2049)"
  fi
  if docker ps --format '{{.Names}}' | grep -qx plex-nfs; then
    log "plex-nfs container is running; export root /nfs (media at :/media)"
  else
    echo "plex-nfs container is not running - bring up plex-stack's nfs service first" >&2; exit 1
  fi
  ss -ltn | grep -q ':2049 ' && log "port 2049 listening" || { echo "nothing listens on 2049" >&2; exit 1; }
}

do_recyclarr() {
  need_root
  local apply="${1:-}"
  install -d -o 1001 -g 1001 "$RECYCLARR_STATE"
  if [ ! -f "$RECYCLARR_DIR/.env" ]; then
    local sk rk
    sk=$(grep -oP '<ApiKey>\K[^<]+' /docker/sonarr/config.xml)
    rk=$(grep -oP '<ApiKey>\K[^<]+' /docker/radarr/config.xml)
    [ -n "$sk" ] && [ -n "$rk" ] || { echo "could not read arr api keys" >&2; exit 1; }
    ( umask 077; printf 'SONARR_API_KEY=%s\nRADARR_API_KEY=%s\n' "$sk" "$rk" > "$RECYCLARR_DIR/.env" )
    chown "${SUDO_UID:-0}:${SUDO_GID:-0}" "$RECYCLARR_DIR/.env"
    log "wrote $RECYCLARR_DIR/.env (gitignored)"
  fi
  cd "$RECYCLARR_DIR"
  log "recyclarr preview (no changes applied):"
  docker compose run --rm recyclarr sync --preview
  if [ "$apply" = "--apply" ]; then
    log "applying recyclarr sync to the live arrs"
    docker compose run --rm recyclarr sync
    docker compose up -d
    docker compose ps
  else
    log "preview only; re-run with --apply to sync and start the cron container"
  fi
}

do_push_token() {
  local host="${1:?usage: push-token <host>}"
  [ "$(id -u)" != 0 ] || { echo "run push-token WITHOUT sudo (uses your ssh keys)" >&2; exit 1; }
  local t; t=$(sudo -n grep -oP '^PLEXOPS_TOKEN=\K.*' "$ENV_FILE")
  [ -n "$t" ] || { echo "no token in $ENV_FILE" >&2; exit 1; }
  # Lands in the account that runs NanoClaw and its scheduled-task gate scripts.
  printf 'RUNNER_URL=http://nemesis.rt-541.io:8377\nRUNNER_TOKEN=%s\n' "$t" \
    | ssh "$host" 'umask 077; mkdir -p ~/.config/plex-ops && cat > ~/.config/plex-ops/runner.env && chmod 600 ~/.config/plex-ops/runner.env && echo "token installed at ~/.config/plex-ops/runner.env on $(hostname)"'
}

cmd="${1:-}"; shift || true
worktree=""; apply=""; host=""
while [ $# -gt 0 ]; do
  case "$1" in
    --worktree) worktree="$2"; shift 2 ;;
    --apply) apply="--apply"; shift ;;
    *) host="$1"; shift ;;
  esac
done
case "$cmd" in
  runner) do_runner "$worktree" ;;
  smoke) do_smoke ;;
  nfs) do_nfs ;;
  recyclarr) do_recyclarr "$apply" ;;
  push-token) do_push_token "$host" ;;
  all) do_runner "$worktree"; do_nfs; do_recyclarr "$apply" ;;
  *) sed -n 2,20p "$0"; exit 1 ;;
esac
