#!/bin/bash

SOURCE="/export"
DESTINATION="/export2"
LOG_FILE="/$(pwd)/logfile.log"

# Function to log to both file and console
log() {
    echo "$1" | tee -a $LOG_FILE
}

# Log the start of the operation
log "Starting recursive copy from $SOURCE to $DESTINATION at $(date)"

# Ensure destination directory exists
log "Ensuring destination directory exists..."
mkdir -p $DESTINATION

# Perform the recursive copy
log "Copying directories and files..."
scp -r $SOURCE/* $DESTINATION 2>&1 | tee -a $LOG_FILE

# Log the completion of the operation
log "Recursive copy completed at $(date)"

exit 0
