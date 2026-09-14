#!/bin/bash

# Log file path
log_file="/var/log/backup_minecraft.log"

# Function to log messages with timestamps
log() {
    echo "$(date +'%Y-%m-%d %H:%M:%S') - $1" | tee -a "$log_file"
}

# Check if the Minecraft container is running
if ! /usr/bin/docker ps --filter name=mcatm10 --filter status=running --format "{{.Names}}" | grep -q "^mcatm10$"; then
    log "Minecraft container 'mcatm10' is not running. Exiting backup."
    exit 1
fi

log "Minecraft container 'mcatm10' is running. Proceeding with backup."

# Stop the Minecraft container
log "Stopping Minecraft container 'mcatm10'."
/usr/bin/docker-compose -f /docker/homelab-config/data-host/composed-apps/minecraft/docker-compose.yml down >> "$log_file" 2>&1
if [ $? -ne 0 ]; then
    log "Failed to stop the Minecraft container. Exiting."
    exit 1
fi

# Create a timestamped backup
backup_dir="/docker/game/minecraft"
timestamp=$(date +%Y%m%d)
backup_file="$backup_dir/minecraft_data_backup_$timestamp.tar.gz"

log "Creating backup at $backup_file."
tar -czvf "$backup_file" -C "$backup_dir" minecraft_data >> "$log_file" 2>&1
if [ $? -ne 0 ]; then
    log "Backup creation failed. Exiting."
    exit 1
fi
log "Backup created successfully."

# Restart the Minecraft container
log "Starting Minecraft container 'mcatm10'."
/usr/bin/docker-compose -f /docker/homelab-config/data-host/composed-apps/minecraft/docker-compose.yml up -d >> "$log_file" 2>&1
if [ $? -ne 0 ]; then
    log "Failed to start the Minecraft container after backup."
    exit 1
fi
log "Minecraft container started successfully."

log "Backup process completed successfully."