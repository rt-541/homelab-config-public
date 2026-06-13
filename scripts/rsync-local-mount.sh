#!/bin/bash

# Default values for variables
SOURCE=""
DESTINATION=""
LOG_FILE="/path/to/logfile.log"
DOCKER_COMPOSE_FILE=""
MAX_JOBS=4  # Default to 4 parallel jobs if not specified

# Function to display usage
usage() {
    echo "Usage: $0 -s <source> -d <destination> [-l <logfile>] [-f <docker-compose-file>] [-j <parallel_jobs>]"
    exit 1
}

# Parse command-line arguments
while getopts "s:d:l:f:j:" opt; do
    case $opt in
        s) SOURCE="$OPTARG" ;;
        d) DESTINATION="$OPTARG" ;;
        l) LOG_FILE="$OPTARG" ;;
        f) DOCKER_COMPOSE_FILE="$OPTARG" ;;
        j) MAX_JOBS="$OPTARG" ;;
        *) usage ;;
    esac
done

# Check if source and destination are provided
if [ -z "$SOURCE" ] || [ -z "$DESTINATION" ]; then
    usage
fi

# Default log file if not provided
if [ -z "$LOG_FILE" ]; then
    LOG_FILE="./rsync_script.log"
fi

# Ensure GNU Parallel is installed
if ! command -v parallel &> /dev/null; then
    echo "GNU Parallel is required but it's not installed. Please install it and try again."
    exit 1
fi

# Function to log to both file and console
log() {
    echo "$1" | tee -a $LOG_FILE
}

# Function to create directory structure with GNU parallel
create_dir_structure() {
    SRC="$1"
    DST="$2"
    JOBS="$3"

    log "Creating directory structure with GNU parallel at $(date)"
    cd "$SRC"
    find . -type d | parallel -j "$JOBS" mkdir -p "$DST/{}" 2>&1 | tee -a $LOG_FILE
    log "Directory structure created with GNU parallel at $(date)"
}

# Function to perform rsync with GNU parallel
rsync_parallel() {
    SRC="$1"
    DST="$2"
    JOBS="$3"

    log "Starting rsync with GNU parallel at $(date)"
    cd "$SRC"
    find . -type f | parallel -j "$JOBS" rsync -avh --progress --stats "{}" "$DST/{}" 2>&1 | tee -a $LOG_FILE
    log "Rsync with GNU parallel completed at $(date)"
}

# Partial sync function
partial_sync() {
    log "Starting partial sync at $(date)"
    create_dir_structure "$SOURCE" "$DESTINATION" "$MAX_JOBS"
    rsync_parallel "$SOURCE" "$DESTINATION" "$MAX_JOBS"
    log "Partial sync completed at $(date)"
}

# Final true-up sync function
final_sync() {
    log "Starting final sync at $(date)"
    rsync_parallel "$SOURCE" "$DESTINATION" "$MAX_JOBS"
    log "Final sync completed at $(date)"
}

# Docker Compose down function
docker_compose_down() {
    if [ -n "$DOCKER_COMPOSE_FILE" ]; then
        log "Shutting down Docker Compose containers at $(date)"
        docker-compose -f "$DOCKER_COMPOSE_FILE" down 2>&1 | tee -a $LOG_FILE
        log "Docker Compose containers shut down at $(date)"
    fi
}

# Main script execution
log "Script started at $(date)"

# Perform partial sync
partial_sync

# Shut down Docker Compose containers if specified
docker_compose_down

# Perform final true-up sync
final_sync

log "Script completed at $(date)"

exit 0
