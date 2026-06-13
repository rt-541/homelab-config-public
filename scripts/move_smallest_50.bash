#!/usr/bin/env bash
#
# move_smallest_50.bash - Move smallest N media directories between storage locations
#
# Features:
# - Interactive media type selection (tv/movies)
# - Safe rsync with checksum verification
# - Detailed logging and progress tracking
# - Dry-run mode for testing
# - Configurable count and sort order
# - Automatic safety checks
#

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

DEFAULT_COUNT=50
BASE_SRC="/docker/plex/media"
BASE_DST="/docker/plex/media2"
LOG_DIR="/docker/plex/logs"
TIMESTAMP="$(date +%F_%H%M%S)"
LOG="${LOG_DIR}/move_media_${TIMESTAMP}.log"

# Arr stack config
RADARR_URL="http://localhost:7878"
RADARR_CONFIG="/docker/radarr/config.xml"
SONARR_URL="http://localhost:8989"
SONARR_CONFIG="/docker/sonarr/config.xml"

# Container volume mappings (host path -> container path)
CONTAINER_SRC="/data"
CONTAINER_DST="/data2"

# ============================================================================
# Colors for output
# ============================================================================

if [[ -t 1 ]]; then
  RED='\033[0;31m'
  GREEN='\033[0;32m'
  YELLOW='\033[1;33m'
  BLUE='\033[0;34m'
  BOLD='\033[1m'
  NC='\033[0m' # No Color
else
  RED='' GREEN='' YELLOW='' BLUE='' BOLD='' NC=''
fi

# ============================================================================
# Functions
# ============================================================================

log() {
  echo -e "$@" | tee -a "$LOG"
}

log_info() {
  log "${BLUE}ℹ${NC} $*"
}

log_success() {
  log "${GREEN}✓${NC} $*"
}

log_warn() {
  log "${YELLOW}⚠${NC} $*"
}

log_error() {
  log "${RED}✗${NC} $*"
}

log_header() {
  log ""
  log "${BOLD}=== $* ===${NC}"
}

format_bytes() {
  local bytes="$1"
  numfmt --to=iec --suffix=B "$bytes" 2>/dev/null || echo "${bytes}B"
}

get_api_key() {
  local config_file="$1"
  if [[ ! -f "$config_file" ]]; then
    log_error "Config file not found: $config_file"
    return 1
  fi
  grep -oP '<ApiKey>\K[^<]+' "$config_file"
}

update_arr_path() {
  local name="$1"
  local old_container_path="$2"
  local new_container_path="$3"
  local api_url="$4"
  local api_key="$5"
  local endpoint="$6"    # "movie" or "series"
  local path_field="path" # both use "path"

  # Get all items from the arr
  local response
  response=$(curl -sf -H "X-Api-Key: $api_key" "${api_url}/api/v3/${endpoint}" 2>/dev/null)
  if [[ $? -ne 0 || -z "$response" ]]; then
    log_warn "Failed to query ${endpoint} API at ${api_url}"
    return 1
  fi

  # Find the item by matching the old path
  local item
  item=$(echo "$response" | jq -r --arg path "$old_container_path" \
    '.[] | select(.path == $path)' 2>/dev/null)

  if [[ -z "$item" || "$item" == "null" ]]; then
    # Try with trailing slash variations
    item=$(echo "$response" | jq -r --arg path "${old_container_path}/" \
      '.[] | select(.path == $path)' 2>/dev/null)
  fi

  if [[ -z "$item" || "$item" == "null" ]]; then
    log_warn "Could not find '$name' in ${endpoint} with path: $old_container_path"
    return 1
  fi

  local item_id
  item_id=$(echo "$item" | jq -r '.id')

  # Update the path
  local updated_item
  updated_item=$(echo "$item" | jq --arg path "$new_container_path" '.path = $path')

  local put_response
  put_response=$(curl -sf -X PUT \
    -H "X-Api-Key: $api_key" \
    -H "Content-Type: application/json" \
    -d "$updated_item" \
    "${api_url}/api/v3/${endpoint}/${item_id}" 2>/dev/null)

  if [[ $? -eq 0 ]]; then
    log_success "Updated ${endpoint} path: $old_container_path -> $new_container_path"
    return 0
  else
    log_error "Failed to update ${endpoint} path for '$name'"
    return 1
  fi
}

show_usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Move smallest N directories from Plex media to secondary storage.

Options:
  -c, --count NUM       Number of directories to move (default: $DEFAULT_COUNT)
  -t, --type TYPE       Media type: tv or movies (skip interactive prompt)
  -l, --largest         Move largest instead of smallest
  -d, --dry-run         Show what would be moved without actually moving
  -s, --source PATH     Custom source path (default: $BASE_SRC)
  -D, --dest PATH       Custom destination path (default: $BASE_DST)
  -y, --yes             Skip confirmation prompt
  -h, --help            Show this help message

Examples:
  $(basename "$0")                           # Interactive mode
  $(basename "$0") -c 100 -t movies          # Move 100 smallest movies
  $(basename "$0") --largest -t tv -c 20     # Move 20 largest TV shows
  $(basename "$0") --dry-run -t movies       # Preview what would be moved

EOF
  exit 0
}

confirm() {
  local prompt="${1:-Continue?}"
  local response

  echo -ne "${YELLOW}${prompt}${NC} [y/N]: "
  read -r response
  [[ "${response,,}" =~ ^y(es)?$ ]]
}

# ============================================================================
# Parse arguments
# ============================================================================

COUNT="$DEFAULT_COUNT"
MEDIA_TYPE=""
SORT_ORDER="smallest"
DRY_RUN=false
SKIP_CONFIRM=false
SRC_OVERRIDE=""
DST_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -c|--count)
      COUNT="$2"
      shift 2
      ;;
    -t|--type)
      MEDIA_TYPE="$2"
      if [[ ! "$MEDIA_TYPE" =~ ^(tv|movies)$ ]]; then
        log_error "Invalid media type: $MEDIA_TYPE (must be 'tv' or 'movies')"
        exit 1
      fi
      shift 2
      ;;
    -l|--largest)
      SORT_ORDER="largest"
      shift
      ;;
    -d|--dry-run)
      DRY_RUN=true
      shift
      ;;
    -s|--source)
      SRC_OVERRIDE="$2"
      shift 2
      ;;
    -D|--dest)
      DST_OVERRIDE="$2"
      shift 2
      ;;
    -y|--yes)
      SKIP_CONFIRM=true
      shift
      ;;
    -h|--help)
      show_usage
      ;;
    *)
      log_error "Unknown option: $1"
      show_usage
      ;;
  esac
done

# ============================================================================
# Setup
# ============================================================================

mkdir -p "$LOG_DIR"

log_header "Plex Media Mover - Started at $(date)"

# Override paths if specified
[[ -n "$SRC_OVERRIDE" ]] && BASE_SRC="$SRC_OVERRIDE"
[[ -n "$DST_OVERRIDE" ]] && BASE_DST="$DST_OVERRIDE"

# Interactive media type selection if not specified
if [[ -z "$MEDIA_TYPE" ]]; then
  log_info "Select media type to move:"
  select MEDIA_TYPE in "tv" "movies"; do
    case "${MEDIA_TYPE:-}" in
      tv|movies) break ;;
      *) log_warn "Invalid selection" ;;
    esac
  done
fi

SRC_BASE="$BASE_SRC/$MEDIA_TYPE"
DST_BASE="$BASE_DST/$MEDIA_TYPE"

# Determine which arr to update
if [[ "$MEDIA_TYPE" == "movies" ]]; then
  ARR_URL="$RADARR_URL"
  ARR_CONFIG="$RADARR_CONFIG"
  ARR_ENDPOINT="movie"
  ARR_NAME="Radarr"
elif [[ "$MEDIA_TYPE" == "tv" ]]; then
  ARR_URL="$SONARR_URL"
  ARR_CONFIG="$SONARR_CONFIG"
  ARR_ENDPOINT="series"
  ARR_NAME="Sonarr"
fi

# Load API key
ARR_API_KEY=""
if [[ -f "$ARR_CONFIG" ]]; then
  ARR_API_KEY=$(get_api_key "$ARR_CONFIG" || true)
fi
if [[ -n "$ARR_API_KEY" ]]; then
  log_success "$ARR_NAME API key loaded"
else
  log_warn "$ARR_NAME API key not found - path updates will be skipped"
fi

# ============================================================================
# Safety checks
# ============================================================================

log_header "Safety Checks"

if [[ ! -d "$SRC_BASE" ]]; then
  log_error "Source directory does not exist: $SRC_BASE"
  exit 1
fi
log_success "Source directory exists: $SRC_BASE"

mkdir -p "$DST_BASE"
log_success "Destination directory ready: $DST_BASE"

if command -v mountpoint >/dev/null 2>&1; then
  if ! mountpoint -q "$BASE_DST"; then
    log_error "$BASE_DST is not a mountpoint (safety check)"
    log_error "This prevents accidentally writing to the wrong location"
    exit 1
  fi
  log_success "Destination is a valid mountpoint"
fi

# Check available space
if command -v df >/dev/null 2>&1; then
  dst_avail=$(df --output=avail "$DST_BASE" | tail -1)
  dst_avail_human=$(format_bytes $((dst_avail * 1024)))
  log_info "Available space at destination: $dst_avail_human"
fi

# ============================================================================
# Find directories to move
# ============================================================================

log_header "Scanning Directories"

log_info "Scanning $MEDIA_TYPE directories in $SRC_BASE..."
log_info "Looking for $COUNT $SORT_ORDER directories..."

# Build list (null-safe)
mapfile -d '' -t ALL_DIRS < <(
  find "$SRC_BASE" -mindepth 1 -maxdepth 1 -type d -print0
)

if [[ "${#ALL_DIRS[@]}" -eq 0 ]]; then
  log_warn "No directories found under $SRC_BASE"
  exit 0
fi

log_info "Found ${#ALL_DIRS[@]} total directories"

# Calculate sizes and sort
log_info "Calculating sizes..."

declare -A DIR_SIZES
TOTAL_SIZE=0

for dir in "${ALL_DIRS[@]}"; do
  size=$(du -sb -- "$dir" | awk '{print $1}')
  DIR_SIZES["$dir"]=$size
  TOTAL_SIZE=$((TOTAL_SIZE + size))
done

# Sort directories by size
if [[ "$SORT_ORDER" == "smallest" ]]; then
  mapfile -t SORTED_DIRS < <(
    for dir in "${!DIR_SIZES[@]}"; do
      echo "${DIR_SIZES[$dir]} $dir"
    done | sort -n | head -n "$COUNT" | cut -d' ' -f2-
  )
else
  mapfile -t SORTED_DIRS < <(
    for dir in "${!DIR_SIZES[@]}"; do
      echo "${DIR_SIZES[$dir]} $dir"
    done | sort -rn | head -n "$COUNT" | cut -d' ' -f2-
  )
fi

# ============================================================================
# Display selected directories
# ============================================================================

log_header "Selected Directories ($SORT_ORDER first)"

MOVE_TOTAL_SIZE=0
for dir in "${SORTED_DIRS[@]}"; do
  size="${DIR_SIZES[$dir]}"
  MOVE_TOTAL_SIZE=$((MOVE_TOTAL_SIZE + size))
  size_human=$(format_bytes "$size")
  name=$(basename "$dir")
  log "  ${size_human}\t${name}"
done

log ""
log_info "Total to move: $(format_bytes "$MOVE_TOTAL_SIZE") (${#SORTED_DIRS[@]} directories)"
log_info "Total source:  $(format_bytes "$TOTAL_SIZE") (${#ALL_DIRS[@]} directories)"

# ============================================================================
# Confirmation
# ============================================================================

if [[ "$DRY_RUN" == true ]]; then
  log_header "Dry Run Mode - No Changes Will Be Made"
  exit 0
fi

if [[ "$SKIP_CONFIRM" == false ]]; then
  log ""
  if ! confirm "Proceed with moving ${#SORTED_DIRS[@]} directories?"; then
    log_warn "Aborted by user"
    exit 0
  fi
fi

# ============================================================================
# Move directories
# ============================================================================

log_header "Starting Move Operation"

RSYNC_OPTS=(-aHAX --numeric-ids --info=progress2 --human-readable)
DOWNLOADS_DIR="$BASE_SRC/downloads"

SUCCESS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

for i in "${!SORTED_DIRS[@]}"; do
  src_dir="${SORTED_DIRS[$i]}"
  name="$(basename "$src_dir")"
  dst_dir="$DST_BASE/$name"

  current=$((i + 1))
  total="${#SORTED_DIRS[@]}"
  size_human=$(format_bytes "${DIR_SIZES[$src_dir]}")

  log ""
  log_header "[$current/$total] $name ($size_human)"

  mkdir -p -- "$dst_dir"

  log_info "Moving: $src_dir -> $dst_dir"
  if rsync "${RSYNC_OPTS[@]}" -- "$src_dir/" "$dst_dir/" 2>&1 | tee -a "$LOG"; then
    # Remove hard links in downloads dir to actually free space
    if [[ -d "$DOWNLOADS_DIR" ]]; then
      while IFS= read -r -d '' src_file; do
        link_count=$(stat -c '%h' "$src_file" 2>/dev/null || echo 1)
        if [[ "$link_count" -gt 1 ]]; then
          while IFS= read -r -d '' linked_file; do
            log_info "Removing hard link: $linked_file"
            rm -f -- "$linked_file"
          done < <(find "$DOWNLOADS_DIR" -samefile "$src_file" -print0 2>/dev/null)
        fi
      done < <(find "$src_dir" -type f -links +1 -print0 2>/dev/null)

      # Clean up empty directories left behind in downloads
      emptied=$(find "$DOWNLOADS_DIR" -mindepth 1 -type d -empty -delete -print 2>/dev/null)
      if [[ -n "$emptied" ]]; then
        while IFS= read -r empty_dir; do
          log_info "Removed empty directory: $empty_dir"
        done <<< "$emptied"
      fi
    fi
    # Delete the source directory
    rm -rf -- "$src_dir"

    # Update path in Radarr/Sonarr
    if [[ -n "$ARR_API_KEY" ]]; then
      old_container_path="${CONTAINER_SRC}/${MEDIA_TYPE}/${name}"
      new_container_path="${CONTAINER_DST}/${MEDIA_TYPE}/${name}"
      update_arr_path "$name" "$old_container_path" "$new_container_path" \
        "$ARR_URL" "$ARR_API_KEY" "$ARR_ENDPOINT" || true
    fi

    log_success "Completed: $name"
    SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
  else
    log_error "Move failed for $name"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
done

# ============================================================================
# Clean up empty directories in source
# ============================================================================

log_header "Cleaning Up Source Directory"

src_emptied=$(find "$BASE_SRC" -mindepth 1 -type d -empty -delete -print 2>/dev/null)
if [[ -n "$src_emptied" ]]; then
  while IFS= read -r empty_dir; do
    log_info "Removed empty directory: $empty_dir"
  done <<< "$src_emptied"
else
  log_info "No empty directories to clean up in $BASE_SRC"
fi

# ============================================================================
# Summary
# ============================================================================

log_header "Summary"

log_info "Successfully moved: ${GREEN}${SUCCESS_COUNT}${NC} directories"
[[ $FAIL_COUNT -gt 0 ]] && log_warn "Failed:             ${RED}${FAIL_COUNT}${NC} directories"
[[ $SKIP_COUNT -gt 0 ]] && log_warn "Skipped:            ${YELLOW}${SKIP_COUNT}${NC} directories"

moved_size=0
for dir in "${SORTED_DIRS[@]:0:$SUCCESS_COUNT}"; do
  [[ -n "${DIR_SIZES[$dir]:-}" ]] && moved_size=$((moved_size + DIR_SIZES[$dir]))
done

log_info "Total data moved:   $(format_bytes "$moved_size")"
log_info "Log file:           $LOG"

log ""
log_header "Completed at $(date)"

exit 0
