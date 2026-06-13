#!/usr/bin/env bash
#
# Pi-hole DNS Ansible Setup Script
# Helps you get started with DNS management as code
#

set -euo pipefail

echo "========================================="
echo "Pi-hole DNS Ansible Setup"
echo "========================================="
echo

# Check if Ansible is installed
if ! command -v ansible >/dev/null 2>&1; then
    echo "❌ Ansible is not installed"
    echo
    echo "Install Ansible:"
    echo "  RHEL/Rocky/CentOS: sudo dnf install ansible -y"
    echo "  Debian/Ubuntu:     sudo apt install ansible -y"
    echo "  macOS:             brew install ansible"
    echo "  Python pip:        pip install ansible"
    echo
    exit 1
fi

echo "✓ Ansible installed: $(ansible --version | head -1)"
echo

# Check if Pi-hole is running
if systemctl is-active --quiet pihole-FTL 2>/dev/null; then
    echo "✓ Pi-hole is running"
else
    echo "⚠ Pi-hole may not be running (pihole-FTL service not found)"
    echo "  This is OK if Pi-hole is running in Docker or on another server"
fi
echo

# Get server IP
echo "Detecting your server IP..."
SERVER_IP=$(ip -4 addr show | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | grep -v '127.0.0.1' | head -1)

if [[ -n "$SERVER_IP" ]]; then
    echo "✓ Detected IP: $SERVER_IP"
    echo
    echo "Do you want to use this IP for your DNS entries? (y/n)"
    read -r response

    if [[ "$response" =~ ^[Yy]$ ]]; then
        sed -i "s/server_ip: .*/server_ip: \"$SERVER_IP\"/" vars/dns-entries.yml
        echo "✓ Updated vars/dns-entries.yml with IP: $SERVER_IP"
    fi
fi

echo
echo "========================================="
echo "Configuration Files Created:"
echo "========================================="
echo
echo "1. Edit DNS entries:     vars/dns-entries.yml"
echo "2. Edit inventory:       inventory.ini"
echo "3. Main playbook:        pihole-dns.yml"
echo
echo "========================================="
echo "Next Steps:"
echo "========================================="
echo
echo "1. Edit your DNS entries:"
echo "   nano vars/dns-entries.yml"
echo
echo "2. Test the configuration (dry-run):"
echo "   ansible-playbook pihole-dns.yml --check"
echo
echo "3. Apply the configuration:"
echo "   ansible-playbook pihole-dns.yml"
echo
echo "For detailed instructions, see: README.md"
echo
