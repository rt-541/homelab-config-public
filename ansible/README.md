# Pi-hole DNS Management with Ansible (Docker)

Manage your Pi-hole local DNS entries as code instead of manually adding them through the web interface.

**Note:** This playbook is configured for **containerized Pi-hole** running in Docker.

## Features

- Define all DNS entries in a single YAML file
- Automatic backup before changes
- Syntax validation
- Automatic Pi-hole service restart
- Idempotent - safe to run multiple times
- Dry-run mode for testing

## Prerequisites

### 1. Pi-hole Running in Docker

Ensure Pi-hole is running as a Docker container:
```bash
sudo docker ps | grep pihole
```

If your container has a different name than `pihole`, edit the playbook variable:
```yaml
# In pihole-dns.yml
vars:
  pihole_container_name: "your-container-name"
```

### 2. Install Ansible

```bash
# RHEL/Rocky/CentOS
sudo dnf install ansible -y

# Debian/Ubuntu
sudo apt install ansible -y

# macOS
brew install ansible

# Python pip
pip install ansible
```

## Quick Start

### 1. Configure Your Server IP

Edit `vars/dns-entries.yml` and set your server IP:

```yaml
server_ip: "192.168.1.100"  # Change to your actual IP
```

### 2. Add/Modify DNS Entries

Edit `vars/dns-entries.yml` and add your domains:

```yaml
dns_entries:
  - domain: service.example.com
    ip: "{{ server_ip }}"
    comment: "My service description"

  - domain: another.example.com
    ip: "192.168.1.50"  # Can use different IP
    comment: "Another service"
```

### 3. Configure Inventory

Edit `inventory.ini` to point to your Pi-hole server:

```ini
[pihole]
localhost ansible_connection=local  # For local Pi-hole

# OR for remote Pi-hole:
# 192.168.1.10 ansible_user=pi
```

### 4. Run the Playbook

```bash
cd /docker/homelab-config/ansible

# Test run (dry-run, no changes)
ansible-playbook pihole-dns.yml --check

# Apply changes
ansible-playbook pihole-dns.yml

# Verbose output
ansible-playbook pihole-dns.yml -v
```

## Usage Examples

### Add a New DNS Entry

1. Edit `vars/dns-entries.yml`:
```yaml
dns_entries:
  # ... existing entries ...

  - domain: newapp.rt-541.io
    ip: "{{ server_ip }}"
    comment: "New application"
```

2. Apply changes:
```bash
ansible-playbook pihole-dns.yml
```

### Use Different IPs for Different Services

```yaml
dns_entries:
  - domain: web.example.com
    ip: "192.168.1.100"
    comment: "Web server"

  - domain: db.example.com
    ip: "192.168.1.101"
    comment: "Database server"

  - domain: nas.example.com
    ip: "192.168.1.102"
    comment: "NAS storage"
```

### Bulk Import Existing Entries

If you already have entries in Pi-hole, you can export them:

```bash
# On Pi-hole server
cat /etc/pihole/custom.list
```

Then convert to YAML format in `vars/dns-entries.yml`.

## Advanced Usage

### Multiple Pi-hole Servers

Edit `inventory.ini`:

```ini
[pihole]
pihole-primary.local ansible_user=admin
pihole-secondary.local ansible_user=admin

[pihole:vars]
ansible_python_interpreter=/usr/bin/python3
```

Run for specific host:
```bash
ansible-playbook pihole-dns.yml --limit pihole-primary.local
```

### Custom Variables Per Host

Create `host_vars/pihole-server.yml`:

```yaml
---
server_ip: "192.168.1.100"
```

### Using Ansible Vault for Sensitive Data

```bash
# Encrypt the vars file
ansible-vault encrypt vars/dns-entries.yml

# Run playbook with vault password
ansible-playbook pihole-dns.yml --ask-vault-pass
```

### Scheduled Updates with Cron

```bash
# Add to crontab
0 3 * * * cd /docker/homelab-config/ansible && ansible-playbook pihole-dns.yml >> /var/log/pihole-dns-sync.log 2>&1
```

## File Structure

```
ansible/
├── pihole-dns.yml           # Main playbook
├── inventory.ini            # Ansible inventory (Pi-hole servers)
├── vars/
│   └── dns-entries.yml      # DNS entries configuration
├── templates/
│   └── custom.list.j2       # Template for Pi-hole custom.list
└── README.md                # This file
```

## Backup and Recovery

### Automatic Backups

The playbook automatically creates backups before making changes:
- Location: `/etc/pihole/custom.list.backup.<timestamp>`

### Manual Backup

```bash
# On Pi-hole server
sudo cp /etc/pihole/custom.list /etc/pihole/custom.list.manual-backup
```

### Restore from Backup

```bash
# On Pi-hole server
sudo cp /etc/pihole/custom.list.backup.1234567890 /etc/pihole/custom.list
sudo pihole restartdns
```

## Troubleshooting

### Check Pi-hole Container Status

```bash
sudo docker ps -f name=pihole
sudo docker logs pihole
```

### View Current DNS Entries

```bash
sudo docker exec pihole cat /etc/pihole/custom.list
```

### Test DNS Resolution

```bash
dig service.rt-541.io @localhost
nslookup service.rt-541.io localhost
```

### Verify Ansible Can Connect

```bash
ansible pihole -m ping
ansible pihole -m setup -a "filter=ansible_hostname"
```

### Manual DNS Reload

```bash
sudo docker exec pihole pihole restartdns reload-lists
# or restart entire container
sudo docker restart pihole
```

## Best Practices

1. **Always test with `--check` first** before applying changes
2. **Use comments** for all DNS entries to document their purpose
3. **Version control** this directory with git
4. **Regular backups** - the playbook creates them automatically
5. **Group related entries** in the YAML file for organization

## Git Integration

```bash
cd /docker/homelab-config

# Initialize git (if not already done)
git init

# Add ansible files
git add ansible/

# Commit changes
git commit -m "Add Pi-hole DNS Ansible automation"

# Tag versions
git tag -a v1.0 -m "Initial Pi-hole DNS config"
```

## Example: Full Workflow

```bash
# 1. Edit DNS entries
nano vars/dns-entries.yml

# 2. Check what will change
ansible-playbook pihole-dns.yml --check --diff

# 3. Apply changes
ansible-playbook pihole-dns.yml

# 4. Verify
dig newservice.rt-541.io @localhost

# 5. Commit to git
git add vars/dns-entries.yml
git commit -m "Add newservice DNS entry"
```

## Support

For issues or questions:
- Check Pi-hole logs: `/var/log/pihole.log`
- Check Ansible verbose output: `ansible-playbook pihole-dns.yml -vvv`
- Verify network connectivity to Pi-hole server
