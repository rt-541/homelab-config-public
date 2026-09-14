# HA Uptime Kuma Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A highly-available synthetic monitor: two native Uptime Kuma LXCs pinned to the Proxmox nodes (sienar primary + incomm secondary) behind a keepalived VIP, monitoring the whole estate, with a public status page (LAN-only admin) and single Discord alerting that fails over with the VIP.

**Architecture:** kuat-drive-yards OpenTofu provisions the two privileged Debian-12 LXCs (`monitor_primary`/`monitor_secondary`); an Ansible playbook installs Node + Uptime Kuma (systemd) + keepalived (VIP `.14`) + the notify script on both; a `monitors.py` (uptime-kuma-api) seeds admin/notification/monitors identically on both. homelab-config adds read-only docker-socket-proxies on nemesis+devastator, a Traefik file-provider route for `status.rt-541.io` → VIP, and the DNS record.

**Tech Stack:** OpenTofu + telmate/proxmox, Proxmox LXC (Debian 12), Node.js 20 + Uptime Kuma 1.x (systemd), keepalived (VRRP), uptime-kuma-api (Python), tecnativa/docker-socket-proxy, Traefik v3 file provider, Pi-hole v6 DNS.

**Conventions:** kuat-drive-yards: `~/.local/bin/tofu -chdir=environments/homelab ...` (run a `tofu init` after adding modules); commit to `master`; ssh to LXCs as `root` with `~/.ssh/id_rsa` (`-o IdentitiesOnly=yes`). homelab-config: `sudo docker compose`, "restart"=`down` then `up -d`, commit to `main`. devastator reachable as `aschneider@192.168.1.216` (passwordless sudo). Pi-holes: dns-incomm `.3` MASTER. Auto-classifier may block compound bash — prefer bare commands.

**Concrete values:** kuma-sienar `192.168.1.13` vmid 9301 on sienar; kuma-incomm `192.168.1.15` vmid 9302 on incomm; VIP `192.168.1.14` (VRID 54); Kuma port 3001; repo clone `/opt/uptime-kuma`; admin user `admin`; status page slug `homelab`.

---

## File Structure

**kuat-drive-yards (LXCs + config):**
- Modify `environments/homelab/main.tf` — add `monitor_primary` + `monitor_secondary` modules + outputs
- Create `ansible/inventory/monitors.yml` — the two kuma LXCs
- Create `ansible/playbooks/setup_kuma.yml` — Node + Kuma + systemd + keepalived + notify
- Create `ansible/playbooks/files/kuma.service`, `keepalived-kuma.conf.j2`, `kuma_notify.sh`
- Create `ansible/monitors/monitors.py` + `ansible/monitors/requirements.txt`

**homelab-config (proxies + edge):**
- Create `data-host/composed-apps/docker-socket-proxy/docker-compose.yml`
- Create `compute-node/composed-apps/docker-socket-proxy/docker-compose.yml`
- Create `data-host/composed-apps/traefik/config/status.yml` (file-provider route)
- DNS: `status.rt-541.io` on the Pi-holes

---

## Task 1: Provision the two monitor LXCs (kuat-drive-yards)

**Files:** Modify `environments/homelab/main.tf`

- [ ] **Step 1: Append the two modules + outputs to main.tf**

```hcl
# ==============================================================================
# HA Monitor (Uptime Kuma, baremetal-pinned LXC pair, keepalived VIP .14)
# ==============================================================================

module "monitor_primary" {
  source = "../../modules/lxc-container"

  hostname    = "kuma-sienar"
  vmid        = 9301
  target_node = "sienar"

  cores       = 1
  memory      = 1024
  swap        = 512
  rootfs_size = "8G"
  storage     = var.default_storage

  network_bridge = var.network_bridge
  ip_address     = "192.168.1.13/24"
  gateway        = var.network_gateway
  nameserver     = var.network_nameserver

  ostemplate   = var.control_lxc_template
  unprivileged = false # keepalived VRRP needs privileged
  ssh_keys     = [var.ssh_public_key]

  start_on_boot = true
  tags          = ["monitor", "uptime-kuma", "ha", "primary"]
  description   = "Uptime Kuma - PRIMARY / keepalived MASTER (VIP 192.168.1.14)"
}

module "monitor_secondary" {
  source = "../../modules/lxc-container"

  hostname    = "kuma-incomm"
  vmid        = 9302
  target_node = "incomm"

  cores       = 1
  memory      = 1024
  swap        = 512
  rootfs_size = "8G"
  storage     = var.default_storage

  network_bridge = var.network_bridge
  ip_address     = "192.168.1.15/24"
  gateway        = var.network_gateway
  nameserver     = var.network_nameserver

  ostemplate   = var.control_lxc_template
  unprivileged = false
  ssh_keys     = [var.ssh_public_key]

  start_on_boot = true
  tags          = ["monitor", "uptime-kuma", "ha", "secondary"]
  description   = "Uptime Kuma - SECONDARY / keepalived BACKUP (VIP 192.168.1.14)"
}

output "monitor_primary_ip" {
  value = module.monitor_primary.ssh_host
}
output "monitor_secondary_ip" {
  value = module.monitor_secondary.ssh_host
}
```

- [ ] **Step 2: Init + validate + targeted plan**

```bash
~/.local/bin/tofu -chdir=/docker/kuat-drive-yards/environments/homelab init -input=false
~/.local/bin/tofu -chdir=/docker/kuat-drive-yards/environments/homelab validate
~/.local/bin/tofu -chdir=/docker/kuat-drive-yards/environments/homelab plan -target=module.monitor_primary -target=module.monitor_secondary
```
Expected: `Success!`; plan shows `2 to add, 0 to change, 0 to destroy`.

- [ ] **Step 3: Apply**

```bash
~/.local/bin/tofu -chdir=/docker/kuat-drive-yards/environments/homelab apply -target=module.monitor_primary -target=module.monitor_secondary -auto-approve
```
Expected: `Apply complete! Resources: 2 added.`

- [ ] **Step 4: Verify reachable as root**

```bash
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa -o StrictHostKeyChecking=accept-new root@192.168.1.13 "hostname"
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa -o StrictHostKeyChecking=accept-new root@192.168.1.15 "hostname"
```
Expected: `kuma-sienar`, `kuma-incomm`. (If refused, the LXC may still be booting — wait 15s.)

- [ ] **Step 5: Commit**

```bash
git -C /docker/kuat-drive-yards add environments/homelab/main.tf
git -C /docker/kuat-drive-yards commit -m "feat(tf): HA Uptime Kuma LXC pair (kuma-sienar/.13, kuma-incomm/.15)"
```

---

## Task 2: Inventory + install Node + Uptime Kuma (systemd) on both (kuat-drive-yards)

**Files:** Create `ansible/inventory/monitors.yml`, `ansible/playbooks/files/kuma.service`, `ansible/playbooks/setup_kuma.yml`

- [ ] **Step 1: Write `ansible/inventory/monitors.yml`**

```yaml
---
all:
  children:
    monitors:
      hosts:
        kuma-sienar:
          ansible_host: 192.168.1.13
          monitor_role: primary
          keepalived_priority: 150
          keepalived_state: MASTER
        kuma-incomm:
          ansible_host: 192.168.1.15
          monitor_role: secondary
          keepalived_priority: 100
          keepalived_state: BACKUP
      vars:
        ansible_user: root
        ansible_become: false
        ansible_ssh_private_key_file: ~/.ssh/id_rsa
        ansible_ssh_common_args: '-o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new'
```

- [ ] **Step 2: Write `ansible/playbooks/files/kuma.service`**

```ini
[Unit]
Description=Uptime Kuma
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/uptime-kuma
ExecStart=/usr/bin/node server/server.js --port 3001 --host 0.0.0.0
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: Write `ansible/playbooks/setup_kuma.yml`**

```yaml
---
- name: Install Uptime Kuma (native) on the monitor LXCs
  hosts: monitors
  become: false
  gather_facts: true

  tasks:
    - name: Base packages
      ansible.builtin.apt:
        name: [git, curl, ca-certificates, gnupg, python3, python3-pip, keepalived]
        update_cache: true
        state: present

    - name: Add NodeSource 20.x repo + install Node
      ansible.builtin.shell: |
        set -euo pipefail
        curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
        apt-get install -y nodejs
      args:
        executable: /bin/bash
        creates: /usr/bin/node

    - name: Clone Uptime Kuma
      ansible.builtin.git:
        repo: https://github.com/louislam/uptime-kuma.git
        dest: /opt/uptime-kuma
        version: "1.23.16"
        depth: 1

    - name: Build/setup Uptime Kuma (npm run setup)
      ansible.builtin.command:
        cmd: npm run setup
        chdir: /opt/uptime-kuma
        creates: /opt/uptime-kuma/dist

    - name: Install systemd unit
      ansible.builtin.copy:
        src: files/kuma.service
        dest: /etc/systemd/system/uptime-kuma.service
        mode: "0644"

    - name: Enable + start Uptime Kuma
      ansible.builtin.systemd:
        name: uptime-kuma
        enabled: true
        state: started
        daemon_reload: true
```

- [ ] **Step 4: Syntax-check + run**

```bash
cd /docker/kuat-drive-yards/ansible
ansible-playbook playbooks/setup_kuma.yml -i inventory/monitors.yml --syntax-check
ansible-playbook playbooks/setup_kuma.yml -i inventory/monitors.yml
```
Expected: `failed=0` on both hosts. (If `npm run setup` is slow/heavy, it can take several minutes — that is normal. If the pinned Kuma version tag is unavailable, use the latest `1.x` tag and note it.)

- [ ] **Step 5: Verify Kuma is serving on both**

```bash
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa root@192.168.1.13 "systemctl is-active uptime-kuma; curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:3001"
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa root@192.168.1.15 "systemctl is-active uptime-kuma; curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:3001"
```
Expected: `active` and `200` (or `302` to the setup page) on both.

- [ ] **Step 6: Commit**

```bash
git -C /docker/kuat-drive-yards add ansible/inventory/monitors.yml ansible/playbooks/setup_kuma.yml ansible/playbooks/files/kuma.service
git -C /docker/kuat-drive-yards commit -m "feat(ansible): install native Uptime Kuma + systemd on the monitor LXCs"
```

---

## Task 3: keepalived VIP + alert-follows-VIP notify (kuat-drive-yards)

**Files:** Create `ansible/playbooks/files/keepalived-kuma.conf.j2`, `ansible/playbooks/files/kuma_notify.sh`; extend `setup_kuma.yml`

- [ ] **Step 1: Write `ansible/playbooks/files/keepalived-kuma.conf.j2`**

```jinja
global_defs {
    router_id {{ inventory_hostname }}
    script_user root
    enable_script_security
}

vrrp_script chk_kuma {
    script "/usr/bin/curl -sf -o /dev/null http://127.0.0.1:3001"
    interval 5
    timeout 4
    rise 2
    fall 2
    weight -60
}

vrrp_instance VI_KUMA {
    state {{ keepalived_state }}
    interface eth0
    virtual_router_id 54
    priority {{ keepalived_priority }}
    advert_int 1
    authentication {
        auth_type PASS
        auth_pass KumaHA54
    }
    virtual_ipaddress {
        192.168.1.14/24 dev eth0 label eth0:vip
    }
    track_script {
        chk_kuma
    }
    notify "/usr/local/bin/kuma_notify.sh"
}
```

- [ ] **Step 2: Write `ansible/playbooks/files/kuma_notify.sh`** (toggles the Discord notification so only the VIP holder alerts; idempotent)

```bash
#!/bin/bash
# keepalived notify: $3 = MASTER|BACKUP|FAULT. Enable Discord on MASTER only.
STATE="$3"
WANT=false
[ "$STATE" = "MASTER" ] && WANT=true
# monitors.py exposes a helper; call it to set notification active state.
/usr/bin/python3 /opt/kuma-config/toggle_notification.py "$WANT" >> /var/log/kuma_notify.log 2>&1
```

- [ ] **Step 3: Add keepalived tasks to `setup_kuma.yml`** (append under `tasks:`)

```yaml
    - name: keepalived config
      ansible.builtin.template:
        src: files/keepalived-kuma.conf.j2
        dest: /etc/keepalived/keepalived.conf
        mode: "0644"

    - name: notify script
      ansible.builtin.copy:
        src: files/kuma_notify.sh
        dest: /usr/local/bin/kuma_notify.sh
        mode: "0755"

    - name: Ensure /opt/kuma-config exists (for toggle_notification.py, added in Task 4)
      ansible.builtin.file:
        path: /opt/kuma-config
        state: directory
        mode: "0755"

    - name: Enable + start keepalived
      ansible.builtin.systemd:
        name: keepalived
        enabled: true
        state: started
        daemon_reload: true
```

- [ ] **Step 4: Re-run the playbook**

```bash
cd /docker/kuat-drive-yards/ansible
ansible-playbook playbooks/setup_kuma.yml -i inventory/monitors.yml
```
Expected: `failed=0`.

- [ ] **Step 5: Verify the VIP is on the MASTER**

```bash
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa root@192.168.1.13 "ip -4 addr show eth0 | grep -q 192.168.1.14 && echo 'VIP on kuma-sienar'"
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa root@192.168.1.15 "ip -4 addr show eth0 | grep 192.168.1.14 || echo 'no VIP on secondary (correct)'"
curl -sS -o /dev/null -w "VIP kuma: %{http_code}\n" http://192.168.1.14:3001
```
Expected: VIP on kuma-sienar; not on secondary; VIP:3001 answers. (The notify script logs a python error until Task 4 adds `toggle_notification.py` — harmless; it does not affect the VIP.)

- [ ] **Step 6: Commit**

```bash
git -C /docker/kuat-drive-yards add ansible/playbooks/setup_kuma.yml ansible/playbooks/files/keepalived-kuma.conf.j2 ansible/playbooks/files/kuma_notify.sh
git -C /docker/kuat-drive-yards commit -m "feat(ansible): keepalived VIP .14 + alert-follows-VIP for the monitor pair"
```

---

## Task 4: Monitors-as-code + admin + Discord (uptime-kuma-api) (kuat-drive-yards)

**Files:** Create `ansible/monitors/requirements.txt`, `ansible/monitors/monitors.py`, `ansible/monitors/toggle_notification.py`

- [ ] **Step 1: Create the Discord webhook (one-time, you)**

In Discord → the homelab channel → Integrations → Webhooks → New → copy the URL. You will pass it to the script in Step 4.

- [ ] **Step 2: `ansible/monitors/requirements.txt`**

```
uptime-kuma-api==1.2.1
```

- [ ] **Step 3: `ansible/monitors/monitors.py`** (idempotent: setup admin if needed, ensure Discord notification, ensure every monitor)

```python
#!/usr/bin/env python3
"""Apply the homelab monitor set to one Uptime Kuma instance (idempotent)."""
import sys
from uptime_kuma_api import UptimeKumaApi, MonitorType, NotificationType

URL = sys.argv[1]            # e.g. http://192.168.1.13:3001
USER = sys.argv[2]           # admin
PASSWORD = sys.argv[3]
DISCORD_WEBHOOK = sys.argv[4]

MONITORS = [
    # (type, name, kwargs)
    ("http", "about",      dict(url="https://about.rt-541.io/")),
    ("http", "analytics",  dict(url="https://analytics.rt-541.io/script.js")),
    ("http", "logs",       dict(url="https://logs.rt-541.io/")),
    ("http", "plex",       dict(url="https://plex.rt-541.io/")),
    ("http", "traefik",    dict(url="https://proxy.rt-541.io/")),
    ("ping", "sienar",     dict(hostname="192.168.1.5")),
    ("ping", "incomm",     dict(hostname="192.168.1.6")),
    ("ping", "nemesis",    dict(hostname="192.168.1.214")),
    ("ping", "devastator", dict(hostname="192.168.1.216")),
    ("ping", "tarkin",     dict(hostname="192.168.1.11")),
    ("ping", "pellaeon",   dict(hostname="192.168.1.12")),
    ("port", "dns-vip-53", dict(hostname="192.168.1.2", port=53)),
    ("port", "dns-incomm", dict(hostname="192.168.1.3", port=53)),
    ("port", "dns-sienar", dict(hostname="192.168.1.4", port=53)),
]

with UptimeKumaApi(URL) as api:
    # First-run admin setup (no-op if already set up)
    try:
        api.setup(USER, PASSWORD)
    except Exception:
        pass
    api.login(USER, PASSWORD)

    # Ensure Discord notification named 'discord'
    notifs = {n["name"]: n["id"] for n in api.get_notifications()}
    if "discord" not in notifs:
        n = api.add_notification(name="discord", type=NotificationType.DISCORD,
                                 isDefault=True, discordWebhookUrl=DISCORD_WEBHOOK)
        notif_id = n["id"] if isinstance(n, dict) and "id" in n else \
            {x["name"]: x["id"] for x in api.get_notifications()}["discord"]
    else:
        notif_id = notifs["discord"]

    existing = {m["name"]: m for m in api.get_monitors()}
    type_map = {"http": MonitorType.HTTP, "ping": MonitorType.PING, "port": MonitorType.PORT}
    for mtype, name, kw in MONITORS:
        if name in existing:
            print(f"skip {name} (exists)")
            continue
        api.add_monitor(type=type_map[mtype], name=name, retries=2,
                        notificationIDList=[notif_id], **kw)
        print(f"added {name}")
print("done")
```

- [ ] **Step 4: Install deps locally + apply to BOTH instances**

```bash
cd /docker/kuat-drive-yards/ansible/monitors
pip3 install -r requirements.txt --quiet
python3 monitors.py http://192.168.1.13:3001 admin '<STRONG_ADMIN_PW>' '<DISCORD_WEBHOOK_URL>'
python3 monitors.py http://192.168.1.15:3001 admin '<STRONG_ADMIN_PW>' '<DISCORD_WEBHOOK_URL>'
```
Expected: each prints `added ...` then `done`. (Re-running prints `skip ... (exists)` — idempotent. If the uptime-kuma-api version's method names differ, adjust against `help(UptimeKumaApi)` and note it.)

- [ ] **Step 5: `ansible/monitors/toggle_notification.py`** (used by the keepalived notify; enables/disables the discord notification's default/active state)

```python
#!/usr/bin/env python3
"""Enable (true) or disable (false) Discord alerting on the LOCAL Kuma."""
import sys
from uptime_kuma_api import UptimeKumaApi
WANT = sys.argv[1].lower() == "true"
# Credentials read from /opt/kuma-config/creds (URL USER PASS), written by deploy.
with open("/opt/kuma-config/creds") as f:
    url, user, pw = f.read().split()
with UptimeKumaApi(url) as api:
    api.login(user, pw)
    for n in api.get_notifications():
        if n["name"] == "discord":
            api.edit_notification(n["id"], isDefault=WANT, applyExisting=True)
print("ok", WANT)
```

- [ ] **Step 6: Drop the creds file + scripts onto both LXCs (so the notify works)**

```bash
for ip in 192.168.1.13 192.168.1.15; do
  scp -o IdentitiesOnly=yes -i ~/.ssh/id_rsa /docker/kuat-drive-yards/ansible/monitors/toggle_notification.py root@$ip:/opt/kuma-config/toggle_notification.py
  ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa root@$ip "pip3 install uptime-kuma-api==1.2.1 --quiet --break-system-packages; printf 'http://127.0.0.1:3001 admin <STRONG_ADMIN_PW>\n' > /opt/kuma-config/creds; chmod 600 /opt/kuma-config/creds"
done
```
Then re-fire keepalived state so the MASTER enables Discord:
```bash
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa root@192.168.1.13 "systemctl restart keepalived; sleep 3; tail -2 /var/log/kuma_notify.log"
```
Expected: `ok True` in the log on the MASTER.

- [ ] **Step 7: Commit (NO secrets — the webhook/password are passed at runtime, not stored in git)**

```bash
git -C /docker/kuat-drive-yards add ansible/monitors/monitors.py ansible/monitors/toggle_notification.py ansible/monitors/requirements.txt
git -C /docker/kuat-drive-yards commit -m "feat(monitors): monitors-as-code + alert-follows-VIP toggle (uptime-kuma-api)"
```

---

## Task 5: Read-only docker-socket-proxies (homelab-config)

**Files:** Create `data-host/composed-apps/docker-socket-proxy/docker-compose.yml` and `compute-node/composed-apps/docker-socket-proxy/docker-compose.yml`

- [ ] **Step 1: Write the nemesis proxy compose**

`/docker/homelab-config/data-host/composed-apps/docker-socket-proxy/docker-compose.yml`:
```yaml
---
services:
  docker-socket-proxy:
    image: tecnativa/docker-socket-proxy:latest
    container_name: docker-socket-proxy
    restart: unless-stopped
    environment:
      CONTAINERS: "1"
      INFO: "1"
      PING: "1"
      POST: "0"
      IMAGES: "0"
      NETWORKS: "0"
      VOLUMES: "0"
      EXEC: "0"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    ports:
      - "192.168.1.214:2375:2375"   # bind to the LAN IP; read-only API for Kuma
```

- [ ] **Step 2: Bring up the nemesis proxy + verify (read-only)**

```bash
cd /docker/homelab-config/data-host/composed-apps/docker-socket-proxy
sudo docker compose up -d
curl -sS -o /dev/null -w "containers: %{http_code}\n" http://192.168.1.214:2375/v1.41/containers/json
curl -sS -o /dev/null -w "post-blocked: %{http_code}\n" -X POST http://192.168.1.214:2375/v1.41/containers/create
```
Expected: containers → `200`; the POST → `403` (writes blocked).

- [ ] **Step 3: Write the devastator proxy compose** (identical except the bind IP)

`/docker/homelab-config/compute-node/composed-apps/docker-socket-proxy/docker-compose.yml`: same as Step 1 but the port line is `- "192.168.1.216:2375:2375"`.

- [ ] **Step 4: Deploy on devastator**

```bash
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa aschneider@192.168.1.216 "mkdir -p /docker/homelab-config/compute-node/composed-apps/docker-socket-proxy"
scp -o IdentitiesOnly=yes -i ~/.ssh/id_rsa /docker/homelab-config/compute-node/composed-apps/docker-socket-proxy/docker-compose.yml aschneider@192.168.1.216:/docker/homelab-config/compute-node/composed-apps/docker-socket-proxy/docker-compose.yml
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa aschneider@192.168.1.216 "cd /docker/homelab-config/compute-node/composed-apps/docker-socket-proxy && sudo docker compose up -d && curl -sS -o /dev/null -w 'containers: %{http_code}\n' http://192.168.1.216:2375/v1.41/containers/json"
```
Expected: `200`.

- [ ] **Step 5: Commit**

```bash
git -C /docker/homelab-config add data-host/composed-apps/docker-socket-proxy/docker-compose.yml compute-node/composed-apps/docker-socket-proxy/docker-compose.yml
git -C /docker/homelab-config commit -m "feat(monitor): read-only docker-socket-proxies on nemesis + devastator"
```

- [ ] **Step 6: Add the two Docker-host monitors** (extend `monitors.py` MONITORS or add in the Kuma UI: Docker Container type, Docker Host = `tcp://192.168.1.214:2375` and `tcp://192.168.1.216:2375`). Re-run `monitors.py` against both Kumas if scripted.

---

## Task 6: Traefik route for status.rt-541.io → VIP + DNS (homelab-config)

**Files:** Create `data-host/composed-apps/traefik/config/status.yml`

- [ ] **Step 1: Write the Traefik file-provider config**

`/docker/homelab-config/data-host/composed-apps/traefik/config/status.yml` (the `config` dir is the watched file provider):
```yaml
http:
  middlewares:
    status-lan-only:
      ipAllowList:
        sourceRange:
          - "192.168.1.0/24"
  services:
    kuma:
      loadBalancer:
        servers:
          - url: "http://192.168.1.14:3001"
  routers:
    status-public:
      rule: "Host(`status.rt-541.io`) && (PathPrefix(`/status`) || PathPrefix(`/assets`) || PathPrefix(`/api/status-page`) || PathPrefix(`/api/entry-page`) || PathPrefix(`/upload`) || Path(`/icon.svg`))"
      entryPoints: [secure]
      service: kuma
      priority: 100
      tls:
        certResolver: default
    status-admin:
      rule: "Host(`status.rt-541.io`)"
      entryPoints: [secure]
      service: kuma
      priority: 10
      middlewares: [status-lan-only]
      tls:
        certResolver: default
```
(Traefik file provider auto-reloads — no restart needed.)

- [ ] **Step 2: Add the DNS record** (dns-incomm `.3`; sync propagates)

```bash
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa root@192.168.1.3 "pihole-FTL --config dns.hosts" | tr ',' '\n' | tail -2
```
Then append (anchor on the current last entry — likely `logs.rt-541.io`; adjust if different):
```bash
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa root@192.168.1.3 "sed -i 's|    \"192.168.1.214 logs.rt-541.io\"|    \"192.168.1.214 logs.rt-541.io\",\n    \"192.168.1.214 status.rt-541.io\"|' /etc/pihole/pihole.toml && pihole reloaddns"
nslookup status.rt-541.io 192.168.1.2
```
Expected: `status.rt-541.io → 192.168.1.214`.

- [ ] **Step 3: Verify routing**

```bash
curl -sS -o /dev/null -w "admin (LAN): %{http_code}\n" --resolve status.rt-541.io:443:192.168.1.214 https://status.rt-541.io/
```
Expected: `200` or a redirect from this LAN host (admin allowed on LAN).

- [ ] **Step 4: Commit**

```bash
git -C /docker/homelab-config add data-host/composed-apps/traefik/config/status.yml
git -C /docker/homelab-config commit -m "feat(traefik): route status.rt-541.io to the Kuma VIP (public status, LAN admin)"
```

---

## Task 7: Status page, alert + HA drill, final verification

- [ ] **Step 1: Build the public status page (one-time, you)** — in Kuma (LAN, `https://status.rt-541.io`, log in `admin`): Status Pages → New → slug `homelab` → add the monitors you want public → Save. Set it as the entry page (Settings) so the public root shows status. Do this on the MASTER; it renders on whichever holds the VIP.

- [ ] **Step 2: Verify public status page loads (paths public)**

```bash
curl -sS -o /dev/null -w "status page: %{http_code}\n" --resolve status.rt-541.io:443:192.168.1.214 https://status.rt-541.io/status/homelab
```
Expected: `200`. (If assets 403, add the blocked PathPrefix to the public router in `status.yml`.)

- [ ] **Step 3: Alert test** — stop a monitored test target (e.g. `sudo docker stop about-site` on nemesis), wait past the retry threshold, confirm **exactly one** Discord message arrives (from the VIP holder). Restart it (`sudo docker start about-site`) → recovery message.

- [ ] **Step 4: HA drill** — on the MASTER (`192.168.1.13`): `systemctl stop keepalived`. Within ~5s confirm the VIP moves to `192.168.1.15` (`ip a` there), `http://192.168.1.14:3001` still answers, and `tail /var/log/kuma_notify.log` on `.15` shows `ok True` (alerting moved). Then `systemctl start keepalived` on `.13` → VIP returns.

- [ ] **Step 5: Confirm container-health monitors are green** (after Task 5 Step 6) on both Kumas.

- [ ] **Step 6: Final commit (ops note)** — append a short "## Monitor" section to `data-host/composed-apps/umami/README.md` or create `kuat-drive-yards/docs/MONITOR.md` documenting: the two LXCs, the VIP, `monitors.py` usage, the alert-follows-VIP mechanism, and the status page URL. Commit in the relevant repo.

---

## Self-Review notes (addressed)

- **Spec coverage:** LXC pair (Task 1), native Kuma+systemd (Task 2), keepalived VIP + alert-follows-VIP (Tasks 3–4), monitors-as-code incl. all four layers (Task 4 + Task 5 Step 6 for docker), socket-proxies both hosts (Task 5), Traefik public/LAN split + DNS (Task 6), status page + alert + **HA drill** (Task 7).
- **No placeholders:** runtime secrets (`<STRONG_ADMIN_PW>`, `<DISCORD_WEBHOOK_URL>`) are explicitly user-supplied at run time, not committed. Version-nuanced steps (Kuma `npm run setup`, uptime-kuma-api method names, public asset prefixes) carry explicit verify-and-adjust instructions.
- **Naming consistency:** `kuma-sienar`/`kuma-incomm`, VIP `.14`/VRID 54, service `kuma`, notification `discord`, status slug `homelab`, used consistently across tasks.
