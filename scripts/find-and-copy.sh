#!/bin/bash

SOURCE="/export"
DESTINATION="/export2"
LOG_FILE="/path/to/logfile.log"
MAX_JOBS=24  # Number of parallel jobs

# Function to log to both file and console
log() {
    echo "$1" | tee -a $LOG_FILE
}

# Ensure destination directory exists
mkdir -p "$DESTINATION"

# Log the start of the operation
log "Starting recursive copy from $SOURCE to $DESTINATION at $(date)"

# Copy directories first
log "Copying directories..."
find "$SOURCE" -type d -exec mkdir -p "$DESTINATION/{}" \; 2>&1 | tee -a $LOG_FILE

# Copy files in parallel
log "Copying files..."
export DESTINATION  # Export DESTINATION so it's available to the subshells
find "$SOURCE" -type f | xargs -n 1 -P $MAX_JOBS -I {} cp --parents -v {} "$DESTINATION" 2>&1 | tee -a $LOG_FILE

# Log the completion of the operation
log "Recursive copy completed at $(date)"

exit 0
