#!/usr/bin/env bash
# Phase 0 filesystem-level instant reclaim: preflight checks, stale trash
# purge, downloads junk removal. Arr-mediated items (Dune dupe, fake 4K)
# live in phase0_arr.py; multi-version pruning in prune_multiversion.py.
#
# Usage:
#   phase0_instant_reclaim.sh preflight
#   phase0_instant_reclaim.sh trash --report | --execute [--no-qbit-check-ack]
#   phase0_instant_reclaim.sh junk  --report | --execute [--no-qbit-check-ack]
#
# Every --execute requires a prior --report in the same LOG_ROOT and refuses
# to run if the qbit cross-check is unavailable, unless --no-qbit-check-ack.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_ROOT=/docker/plex/logs/media-reclaim
MEDIA=/docker/plex/media
TRASH="$MEDIA/downloads/.Trash-1001"
DOWNLOADS="$MEDIA/downloads"

log() { echo "[$(date +%H:%M:%S)] $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

need_sudo() { sudo -n true 2>/dev/null || die "needs passwordless sudo"; }

ensure_dirs() {
  sudo -n install -d -o "$(id -un)" -g "$(id -gn)" -m 0775 "$LOG_ROOT"
}

df_checkpoint() {
  ensure_dirs
  {
    echo "== $(date -Is) | $1"
    df -B1 --output=target,size,used,avail "$MEDIA" /docker/plex/media2
  } >> "$LOG_ROOT/df-checkpoints.log"
  df -h "$MEDIA" /docker/plex/media2
}

arr_key() { sudo -n grep -oP '<ApiKey>\K[^<]+' "/docker/$1/config.xml"; }

qbit_check() { (cd "$SCRIPT_DIR" && python3 qbit_check.py "$@"); }

# --------------------------------------------------------------------------
preflight() {
  need_sudo
  ensure_dirs
  df_checkpoint "preflight"

  local ts backup_dir
  ts=$(date +%Y-%m-%d_%H%M%S)
  backup_dir="$LOG_ROOT/backups-$ts"
  mkdir -p "$backup_dir"
  sudo -n cp /docker/radarr/config.xml "$backup_dir/radarr-config.xml"
  sudo -n cp /docker/sonarr/config.xml "$backup_dir/sonarr-config.xml"
  sudo -n chown "$(id -un)" "$backup_dir"/*.xml
  log "arr configs backed up to $backup_dir"

  for app in radarr sonarr; do
    local key port
    key=$(arr_key "$app")
    [[ $app == radarr ]] && port=7878 || port=8989
    local ver rbin
    ver=$(curl -sf -H "X-Api-Key: $key" "http://localhost:$port/api/v3/system/status" | jq -r '.version')
    rbin=$(curl -sf -H "X-Api-Key: $key" "http://localhost:$port/api/v3/config/mediamanagement" | jq -r '.recycleBin')
    curl -sf -H "X-Api-Key: $key" "http://localhost:$port/api/v3/qualityprofile" \
      > "$backup_dir/$app-qualityprofiles.json"
    log "$app v$ver reachable; profiles backed up; recycleBin='${rbin}'"
    if [[ -n "$rbin" && "$rbin" != "null" ]]; then
      log "WARNING: $app has a recycle bin at '$rbin' - arr deletes will NOT free space until it is purged. Resolve before executing anything."
    fi
  done

  local qb
  qb=$(qbit_check "$DOWNLOADS/__probe__" | cut -f2)
  if [[ "$qb" == "UNAVAILABLE" ]]; then
    log "WARNING: qbittorrent API unavailable (fill QBIT_USER/QBIT_PASS in $SCRIPT_DIR/.env). Executes will require --no-qbit-check-ack."
  else
    log "qbittorrent API reachable"
  fi
  log "preflight complete"
}

# --------------------------------------------------------------------------
trash_report() {
  need_sudo; ensure_dirs
  sudo -n test -d "$TRASH" || die "$TRASH does not exist"
  local tsv="$LOG_ROOT/trash_report.tsv"
  {
    printf 'size_bytes\tnlink\tmtime\tpath\n'
    sudo -n find "$TRASH" -type f -printf '%s\t%n\t%TY-%Tm-%Td\t%p\n' | sort -rn
  } > "$tsv"
  local total files
  total=$(awk -F'\t' 'NR>1{s+=$1} END{printf "%.1f", s/1024/1024/1024}' "$tsv")
  files=$(( $(wc -l < "$tsv") - 1 ))
  local qhit
  qhit=$(qbit_check "$TRASH" | cut -f2)
  {
    echo "trash report: $files files, ${total} GiB"
    echo "qbit owner check for $TRASH: $qhit"
    echo "newest mtime: $(awk -F'\t' 'NR>1{print $3}' "$tsv" | sort -r | head -1)"
  } | tee "$LOG_ROOT/trash_report.summary"
  log "review: $tsv"
}

trash_execute() {
  need_sudo
  [[ -f "$LOG_ROOT/trash_report.tsv" ]] || die "run 'trash --report' first"
  local qhit
  qhit=$(qbit_check "$TRASH" | cut -f2)
  if [[ "$qhit" == "UNAVAILABLE" && "${1:-}" != "--no-qbit-check-ack" ]]; then
    die "qbit check unavailable; pass --no-qbit-check-ack to proceed without it"
  fi
  if [[ "$qhit" != "NONE" && "$qhit" != "UNAVAILABLE" ]]; then
    die "a torrent owns content under $TRASH: $qhit - resolve via cleanup_seeds.py first"
  fi
  df_checkpoint "before trash purge"
  log "purging $TRASH ..."
  sudo -n rm -rf "$TRASH"
  df_checkpoint "after trash purge"
  log "trash purge complete"
}

# --------------------------------------------------------------------------
junk_report() {
  need_sudo; ensure_dirs
  local tsv="$LOG_ROOT/junk_report.tsv"
  printf 'size_bytes\tnlink\tpath\tqbit\n' > "$tsv"
  while IFS=$'\t' read -r size nlink dir file; do
    local p="$dir/$file"
    local q
    q=$(qbit_check "$p" | cut -f2)
    printf '%s\t%s\t%s\t%s\n' "$size" "$nlink" "$p" "$q" >> "$tsv"
  done < <(sudo -n find "$DOWNLOADS" \( -iname '*.iso' -o -iname '*.exe' \) -type f \
           -not -path "$TRASH/*" -printf '%s\t%n\t%h\t%f\n')
  awk -F'\t' 'NR>1{s+=$1; n++} END{printf "junk report: %d files, %.1f GiB\n", n, s/1024/1024/1024}' "$tsv"
  log "review: $tsv"
}

junk_execute() {
  need_sudo
  local tsv="$LOG_ROOT/junk_report.tsv"
  [[ -f "$tsv" ]] || die "run 'junk --report' first"
  df_checkpoint "before junk removal"
  local removed=0 skipped=0
  while IFS=$'\t' read -r size nlink path q; do
    [[ "$path" == "path" || -z "$path" ]] && continue
    if [[ "$q" == "UNAVAILABLE" && "${1:-}" != "--no-qbit-check-ack" ]]; then
      die "qbit check unavailable; pass --no-qbit-check-ack to proceed without it"
    fi
    if [[ "$q" != "NONE" && "$q" != "UNAVAILABLE" ]]; then
      log "SKIP (torrent-owned, route via cleanup_seeds.py): $path"
      skipped=$((skipped+1))
      continue
    fi
    sudo -n rm -f -- "$path"
    removed=$((removed+1))
  done < <(tail -n +2 "$tsv")
  df_checkpoint "after junk removal"
  log "junk removal complete: $removed removed, $skipped skipped (torrent-owned)"
}

# --------------------------------------------------------------------------
cmd="${1:-}"; shift || true
case "$cmd" in
  preflight) preflight ;;
  trash)
    case "${1:-}" in
      --report) trash_report ;;
      --execute) shift; trash_execute "${1:-}" ;;
      *) die "trash needs --report or --execute" ;;
    esac ;;
  junk)
    case "${1:-}" in
      --report) junk_report ;;
      --execute) shift; junk_execute "${1:-}" ;;
      *) die "junk needs --report or --execute" ;;
    esac ;;
  *) die "usage: $0 {preflight|trash|junk} [--report|--execute] [--no-qbit-check-ack]" ;;
esac
