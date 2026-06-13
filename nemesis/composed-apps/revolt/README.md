# Revolt - Self-hosted Discord Alternative

A complete self-hosted Discord alternative with text chat, voice/video calls, file sharing, and more.

## Quick Start

### 1. Configure Environment Variables
```bash
cd /docker/homelab-config/nemesis/composed-apps/revolt
cp .env.example .env
nano .env
```

**Important:** Change `MINIO_PASSWORD` to a strong password before deploying.

### 2. Create Required Directories
```bash
sudo mkdir -p /docker/revolt/{mongo,redis,minio}
```

### 3. Start All Services
```bash
sudo docker compose up -d
```

### 4. Initialize MinIO Storage Buckets
After services are running, create the required S3 buckets:
```bash
sudo docker run --rm --network revolt_revolt-internal \
  -e MC_HOST_revolt=http://miniorevolt:YOUR_MINIO_PASSWORD@minio:9000 \
  minio/mc mb revolt/revolt-attachments revolt/revolt-proxy --ignore-existing
```

Replace `YOUR_MINIO_PASSWORD` with the password from your `.env` file.

### 5. Configure DNS

Add these DNS A records pointing to your server's IP:

| Domain | Purpose |
|--------|---------|
| `app.rt-541.io` | Web client interface (main access point) |
| `revolt.rt-541.io` | API server |
| `ws.rt-541.io` | WebSocket server (real-time events) |
| `autumn.rt-541.io` | File attachment server |
| `january.rt-541.io` | External content proxy (embeds/previews) |
| `minio.rt-541.io` | MinIO admin console |
| `s3.rt-541.io` | MinIO S3 API endpoint |

### 6. Access Revolt

Once DNS propagates:
- **Web App**: https://app.rt-541.io
- **MinIO Console**: https://minio.rt-541.io
  - Username: `miniorevolt`
  - Password: (from your `.env` file)

## Architecture

The stack includes:
- **revolt-api** - Main API server (Delta)
- **revolt-web** - Web client interface
- **revolt-autumn** - File attachment handling
- **revolt-january** - External content proxy for link previews
- **revolt-mongo** - MongoDB database
- **revolt-redis** - Redis cache
- **revolt-minio** - S3-compatible object storage

All services are behind Traefik with automatic SSL/TLS certificates.

## Features

- ✅ Text channels and direct messages
- ✅ Voice and video calls
- ✅ File attachments and image uploads
- ✅ Custom emojis and stickers
- ✅ Roles and permissions system
- ✅ Bot support with API
- ✅ Markdown formatting
- ✅ Mobile apps available (iOS/Android)
- ✅ Server and channel management
- ✅ Custom themes

## Management Commands

### View Logs
```bash
cd /docker/homelab-config/nemesis/composed-apps/revolt

# All services
sudo docker compose logs -f

# Specific service
sudo docker compose logs -f revolt-api
sudo docker compose logs -f revolt-web
sudo docker compose logs -f revolt-autumn
```

### Service Status
```bash
sudo docker compose ps
```

### Restart Services
```bash
# Restart all
sudo docker compose restart

# Restart specific service
sudo docker compose restart revolt-api
```

### Update to Latest Versions
```bash
cd /docker/homelab-config/nemesis/composed-apps/revolt
sudo docker compose pull
sudo docker compose up -d
```

### Stop Services
```bash
sudo docker compose down
```

### Stop and Remove All Data
```bash
sudo docker compose down -v
sudo rm -rf /docker/revolt/*
```

## Configuration

### Environment Variables

Edit `.env` file:

```env
# MinIO S3 storage password
MINIO_PASSWORD=<set-in-env>

# Optional: VAPID keys for push notifications
# Generate with: npx web-push generate-vapid-keys
VAPID_PRIVATE_KEY=
VAPID_PUBLIC_KEY=
```

### Resource Limits

Default resource allocations per service:
- **revolt-api**: 2 CPU, 2GB RAM
- **revolt-mongo**: 2 CPU, 2GB RAM
- **revolt-minio**: 2 CPU, 1GB RAM
- **revolt-autumn**: 1 CPU, 512MB RAM
- **revolt-january**: 1 CPU, 512MB RAM
- **revolt-redis**: 1 CPU, 512MB RAM
- **revolt-web**: 1 CPU, 256MB RAM

Adjust in [docker-compose.yml](docker-compose.yml) under `deploy.resources` sections.

## Troubleshooting

### Web client shows connection errors
- Verify all DNS records are configured and propagated
- Check that WebSocket endpoint (`ws.rt-541.io`) is accessible
- View logs: `sudo docker compose logs -f revolt-api`

### File uploads not working
- Ensure MinIO buckets are created (see step 4)
- Check Autumn logs: `sudo docker compose logs -f revolt-autumn`
- Verify MinIO is accessible: https://minio.rt-541.io

### Services keep restarting
- Check logs for specific errors: `sudo docker compose logs -f [service-name]`
- Verify MongoDB and Redis are healthy
- Ensure sufficient system resources

### Reset admin password or create first user
Revolt uses email-based registration. The first user to register becomes the instance owner.

## Backup and Restore

### Backup Data
```bash
# Backup MongoDB database
sudo docker exec revolt-mongo mongodump --out /data/db/backup

# Backup uploaded files
sudo tar -czf revolt-files-backup.tar.gz /docker/revolt/minio

# Backup MongoDB data
sudo tar -czf revolt-db-backup.tar.gz /docker/revolt/mongo
```

### Restore Data
```bash
# Restore MongoDB
sudo docker exec revolt-mongo mongorestore /data/db/backup

# Restore files
sudo tar -xzf revolt-files-backup.tar.gz -C /
```

## Security Notes

- Change the default `MINIO_PASSWORD` immediately
- Ensure Traefik is properly configured with SSL/TLS
- Consider restricting MinIO console access to internal network only
- Keep services updated regularly
- Use strong passwords for admin accounts

## Links

- [Revolt Official Website](https://revolt.chat/)
- [Revolt Documentation](https://developers.revolt.chat/)
- [Revolt GitHub](https://github.com/revoltchat)
- [Community Server](https://rvlt.gg/Testers)

## License

Revolt is licensed under the AGPL-3.0 license.
