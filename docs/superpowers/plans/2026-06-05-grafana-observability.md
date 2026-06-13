# HA Observability Stack (Prometheus + Grafana) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A highly-available observability stack — two baremetal LXCs (sienar/incomm) running Prometheus (30d) + Grafana + clustered Alertmanager, scraping host/PVE/SMART/Kuma metrics, with provisioned dashboards incl. a Canvas topology, behind a keepalived VIP, alerting once to Discord.

**Architecture:** kuat-drive-yards OpenTofu provisions `obs_primary`/`obs_secondary` LXCs (privileged, nameserver `.2`). Ansible installs the stack via Debian packages + the Grafana apt repo, with configs/dashboards/alerts provisioned as files (identical on both). Two Alertmanagers gossip-cluster for dedupe. homelab-config adds host exporters, the Traefik route, and DNS.

**Tech Stack:** OpenTofu + telmate/proxmox, Debian 12 LXC, Prometheus + Alertmanager + node_exporter (Debian pkgs), Grafana (apt repo), prometheus-pve-exporter (pip), smartctl_exporter (binary), keepalived, Traefik v3 file provider, Pi-hole v6.

**Conventions:** kuat-drive-yards → `~/.local/bin/tofu -chdir=environments/homelab` (run `tofu init` after adding modules), commit `master`, ssh LXCs `root@<ip>` w/ `~/.ssh/id_rsa -o IdentitiesOnly=yes`. homelab-config → `sudo docker compose`, commit `main`. PVE hosts: `lo204@192.168.1.5` (sienar), `lo204@192.168.1.6` (incomm), passwordless sudo. docker hosts: nemesis local, devastator `aschneider@192.168.1.216`. Pi-holes: dns-incomm `root@192.168.1.3`. Auto-classifier may block compound bash — prefer bare commands; for native shell loops in Ansible add `args: {executable: /bin/bash}`.

**Concrete values:** obs-sienar `192.168.1.16` vmid 9401 (sienar, MASTER prio 150); obs-incomm `192.168.1.18` vmid 9402 (incomm, BACKUP prio 100); VIP `192.168.1.17` (VRID 55). Ports: prometheus 9090, alertmanager 9093 (+9094 cluster), grafana 3000, node_exporter 9100, pve-exporter 9221, smartctl_exporter 9633. Discord webhook = the nemesis-bot one (`https://discord.com/api/webhooks/CHANGEME`).

---

## File Structure

**kuat-drive-yards:**
- Modify `environments/homelab/main.tf` — `obs_primary` + `obs_secondary` modules (nameserver `.2`) + outputs
- Create `ansible/inventory/observability.yml`
- Create `ansible/playbooks/setup_observability.yml`
- Create `ansible/observability/{prometheus.yml.j2, alert.rules.yml, alertmanager.yml.j2, pve.yml.j2}`
- Create `ansible/observability/grafana/{datasource.yml, dashboards.yml}` + `dashboards/*.json`
- Create `ansible/playbooks/files/{node_exporter@.nothing}` (host exporters are in homelab-config)

**homelab-config:**
- Create `ansible/playbooks/host_exporters.yml` (node_exporter native on sienar/incomm + smartctl_exporter; targets the PVE hosts)
- Create `nemesis/composed-apps/node-exporter/docker-compose.yml` + `devastator/composed-apps/node-exporter/docker-compose.yml`
- Create `nemesis/composed-apps/traefik/config/grafana.yml`
- DNS `grafana.rt-541.io` on the Pi-holes

---

## Task 1: Provision the two obs LXCs (kuat-drive-yards)

**Files:** Modify `environments/homelab/main.tf`

- [ ] **Step 1: Append modules + outputs to main.tf**

```hcl
# ==============================================================================
# HA Observability (Prometheus + Grafana LXC pair, keepalived VIP 192.168.1.17)
# ==============================================================================

module "obs_primary" {
  source = "../../modules/lxc-container"
  hostname    = "obs-sienar"
  vmid        = 9401
  target_node = "sienar"
  cores       = 2
  memory      = 2048
  swap        = 512
  rootfs_size = "20G"
  storage     = var.default_storage
  network_bridge = var.network_bridge
  ip_address     = "192.168.1.16/24"
  gateway        = var.network_gateway
  nameserver     = "192.168.1.2"
  ostemplate   = var.control_lxc_template
  unprivileged = false
  ssh_keys     = [var.ssh_public_key]
  start_on_boot = true
  tags          = ["observability", "prometheus", "grafana", "ha", "primary"]
  description   = "Observability - PRIMARY / keepalived MASTER (VIP 192.168.1.17)"
}

module "obs_secondary" {
  source = "../../modules/lxc-container"
  hostname    = "obs-incomm"
  vmid        = 9402
  target_node = "incomm"
  cores       = 2
  memory      = 2048
  swap        = 512
  rootfs_size = "20G"
  storage     = var.default_storage
  network_bridge = var.network_bridge
  ip_address     = "192.168.1.18/24"
  gateway        = var.network_gateway
  nameserver     = "192.168.1.2"
  ostemplate   = var.control_lxc_template
  unprivileged = false
  ssh_keys     = [var.ssh_public_key]
  start_on_boot = true
  tags          = ["observability", "prometheus", "grafana", "ha", "secondary"]
  description   = "Observability - SECONDARY / keepalived BACKUP (VIP 192.168.1.17)"
}

output "obs_primary_ip" { value = module.obs_primary.ssh_host }
output "obs_secondary_ip" { value = module.obs_secondary.ssh_host }
```

- [ ] **Step 2: init + validate + plan**

```bash
~/.local/bin/tofu -chdir=/docker/kuat-drive-yards/environments/homelab init -input=false
~/.local/bin/tofu -chdir=/docker/kuat-drive-yards/environments/homelab validate
~/.local/bin/tofu -chdir=/docker/kuat-drive-yards/environments/homelab plan -target=module.obs_primary -target=module.obs_secondary
```
Expected: valid; `2 to add`.

- [ ] **Step 3: apply + verify reachable**

```bash
~/.local/bin/tofu -chdir=/docker/kuat-drive-yards/environments/homelab apply -target=module.obs_primary -target=module.obs_secondary -auto-approve
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa -o StrictHostKeyChecking=accept-new root@192.168.1.16 "hostname"
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa -o StrictHostKeyChecking=accept-new root@192.168.1.18 "hostname"
```
Expected: `obs-sienar`, `obs-incomm`.

- [ ] **Step 4: Commit**

```bash
git -C /docker/kuat-drive-yards add environments/homelab/main.tf
git -C /docker/kuat-drive-yards commit -m "feat(tf): HA observability LXC pair (obs-sienar/.16, obs-incomm/.18)"
```

---

## Task 2: Mint a read-only PVE token + host exporters (homelab-config)

**Files:** Create `homelab-config/ansible/playbooks/host_exporters.yml`, `nemesis|devastator/composed-apps/node-exporter/docker-compose.yml`

- [ ] **Step 1: Mint a read-only PVE API token for pve-exporter (cluster-wide)**

```bash
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa lo204@192.168.1.5 "sudo pveum user add monitoring@pve 2>/dev/null; sudo pveum acl modify / -user monitoring@pve -role PVEAuditor; sudo pveum user token add monitoring@pve prom --privsep 0 --output-format json"
```
Expected: JSON with `full-tokenid` (`monitoring@pve!prom`) and a `value` (secret). Record both — used in Task 4's pve.yml (gitignored).

- [ ] **Step 2: node_exporter native on the PVE hosts (sienar, incomm)**

The PVE hosts run Debian; install the packaged exporter (bind to all interfaces, default :9100):
```bash
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa lo204@192.168.1.5 "sudo apt-get install -y prometheus-node-exporter; systemctl is-active prometheus-node-exporter"
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa lo204@192.168.1.6 "sudo apt-get install -y prometheus-node-exporter; systemctl is-active prometheus-node-exporter"
```
Expected: `active` on both. Verify metrics: `curl -s http://192.168.1.5:9100/metrics | head -1` → a `# HELP` line.

- [ ] **Step 3: smartctl_exporter on the PVE hosts (disk SMART)**

```bash
for h in 192.168.1.5 192.168.1.6; do ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa lo204@$h "sudo apt-get install -y prometheus-smartctl-exporter 2>/dev/null && systemctl is-active prometheus-smartctl-exporter || echo 'pkg-missing'"; done
```
If the Debian package is absent (`pkg-missing`), install the binary: download the latest `smartctl_exporter` release for linux-amd64 from https://github.com/prometheus-community/smartctl_exporter/releases to `/usr/local/bin/smartctl_exporter`, create a systemd unit `smartctl_exporter.service` (`ExecStart=/usr/local/bin/smartctl_exporter`, runs as root for smartctl access), enable+start. Verify `curl -s http://192.168.1.5:9633/metrics | grep -c smartctl_device` > 0.

- [ ] **Step 4: node_exporter container on the docker hosts (nemesis, devastator)**

`nemesis/composed-apps/node-exporter/docker-compose.yml`:
```yaml
---
services:
  node-exporter:
    image: prom/node-exporter:latest
    container_name: node-exporter
    restart: unless-stopped
    command:
      - '--path.rootfs=/host'
    pid: host
    network_mode: host
    volumes:
      - /:/host:ro,rslave
```
Up it: `cd /docker/homelab-config/nemesis/composed-apps/node-exporter && sudo docker compose up -d`. Verify `curl -s http://192.168.1.214:9100/metrics | head -1`. Repeat for devastator (same file; deploy + `up -d` on `aschneider@192.168.1.216`; verify `http://192.168.1.216:9100`).

- [ ] **Step 5: Commit (homelab-config)**

```bash
git -C /docker/homelab-config add nemesis/composed-apps/node-exporter/docker-compose.yml devastator/composed-apps/node-exporter/docker-compose.yml
git -C /docker/homelab-config commit -m "feat(obs): node_exporter on docker hosts; (PVE-host exporters installed via apt)"
```

---

## Task 3: Prometheus + Alertmanager (cluster) on both LXCs (kuat-drive-yards)

**Files:** Create `ansible/inventory/observability.yml`, `ansible/observability/{prometheus.yml.j2, alert.rules.yml, alertmanager.yml.j2}`, `ansible/playbooks/setup_observability.yml`

- [ ] **Step 1: `ansible/inventory/observability.yml`**

```yaml
---
all:
  children:
    observability:
      hosts:
        obs-sienar: {ansible_host: 192.168.1.16, role: primary, keepalived_state: MASTER, keepalived_priority: 150, peer_ip: 192.168.1.18}
        obs-incomm: {ansible_host: 192.168.1.18, role: secondary, keepalived_state: BACKUP, keepalived_priority: 100, peer_ip: 192.168.1.16}
      vars:
        ansible_user: root
        ansible_become: false
        ansible_ssh_private_key_file: ~/.ssh/id_rsa
        ansible_ssh_common_args: '-o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new'
```

- [ ] **Step 2: `ansible/observability/prometheus.yml.j2`**

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
alerting:
  alertmanagers:
    - static_configs:
        - targets: ['127.0.0.1:9093']
rule_files:
  - /etc/prometheus/alert.rules.yml
scrape_configs:
  - job_name: node
    static_configs:
      - targets: ['192.168.1.5:9100','192.168.1.6:9100','192.168.1.214:9100','192.168.1.216:9100']
  - job_name: smartctl
    static_configs:
      - targets: ['192.168.1.5:9633','192.168.1.6:9633']
  - job_name: pve
    static_configs:
      - targets: ['192.168.1.5','192.168.1.6']   # the PVE nodes (queried via pve-exporter below)
    metrics_path: /pve
    params: {module: [default]}
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: 127.0.0.1:9221    # local pve-exporter does the API call
  - job_name: kuma
    metrics_path: /metrics
    static_configs:
      - targets: ['192.168.1.14:3001']
```

- [ ] **Step 3: `ansible/observability/alert.rules.yml`**

```yaml
groups:
  - name: host
    rules:
      - alert: ExporterDown
        expr: up == 0
        for: 5m
        labels: {severity: critical}
        annotations: {summary: "{{ $labels.job }} target {{ $labels.instance }} is DOWN"}
      - alert: DiskFull
        expr: (1 - node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes) > 0.85
        for: 10m
        labels: {severity: warning}
        annotations: {summary: "Disk >85% on {{ $labels.instance }} {{ $labels.mountpoint }}"}
      - alert: MemoryHigh
        expr: (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) > 0.90
        for: 10m
        labels: {severity: warning}
        annotations: {summary: "RAM >90% on {{ $labels.instance }}"}
      - alert: SmartFailing
        expr: smartctl_device_smart_status == 0
        for: 5m
        labels: {severity: critical}
        annotations: {summary: "SMART health FAIL on {{ $labels.instance }} {{ $labels.device }}"}
      - alert: PveStorageHigh
        expr: (pve_disk_usage_bytes / pve_disk_size_bytes) > 0.90
        for: 10m
        labels: {severity: warning}
        annotations: {summary: "PVE storage >90% {{ $labels.id }} on {{ $labels.instance }}"}
```

- [ ] **Step 4: `ansible/observability/alertmanager.yml.j2`** (Discord receiver via webhook; v0.25+ has native discord)

```yaml
route:
  receiver: discord
  group_by: ['alertname','instance']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 3h
receivers:
  - name: discord
    discord_configs:
      - webhook_url: '{{ discord_webhook }}'
```

- [ ] **Step 5: `ansible/playbooks/setup_observability.yml`** (Prometheus + Alertmanager; Grafana/pve/keepalived added in Tasks 4-5)

```yaml
---
- name: Observability stack (Prometheus + Alertmanager)
  hosts: observability
  become: false
  gather_facts: true
  vars:
    discord_webhook: "{{ lookup('env','OBS_DISCORD_WEBHOOK') }}"
  tasks:
    - name: Packages
      ansible.builtin.apt:
        name: [prometheus, prometheus-alertmanager, keepalived, python3-pip, curl, gnupg, apt-transport-https, software-properties-common]
        update_cache: true
        state: present
    - name: prometheus.yml
      ansible.builtin.template: {src: ../observability/prometheus.yml.j2, dest: /etc/prometheus/prometheus.yml, mode: '0644'}
    - name: alert rules
      ansible.builtin.copy: {src: ../observability/alert.rules.yml, dest: /etc/prometheus/alert.rules.yml, mode: '0644'}
    - name: 30-day retention (override the default args)
      ansible.builtin.copy:
        dest: /etc/default/prometheus
        mode: '0644'
        content: |
          ARGS="--storage.tsdb.retention.time=30d --web.listen-address=0.0.0.0:9090"
    - name: alertmanager.yml
      ansible.builtin.template: {src: ../observability/alertmanager.yml.j2, dest: /etc/prometheus/alertmanager.yml, mode: '0644'}
    - name: alertmanager cluster args
      ansible.builtin.copy:
        dest: /etc/default/prometheus-alertmanager
        mode: '0644'
        content: |
          ARGS="--cluster.listen-address=0.0.0.0:9094 --cluster.peer={{ peer_ip }}:9094 --web.listen-address=0.0.0.0:9093"
    - name: Restart services
      ansible.builtin.systemd: {name: "{{ item }}", state: restarted, enabled: true, daemon_reload: true}
      loop: [prometheus, prometheus-alertmanager]
```

- [ ] **Step 6: Run it (pass the webhook via env, NOT committed)**

```bash
cd /docker/kuat-drive-yards/ansible
OBS_DISCORD_WEBHOOK='https://discord.com/api/webhooks/CHANGEME' ansible-playbook playbooks/setup_observability.yml -i inventory/observability.yml
```
Expected: `failed=0`. (Adjust paths/arg-file names if the Debian package uses a different default-args file — check `systemctl cat prometheus` and align.) Verify Prometheus healthy:
```bash
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa root@192.168.1.16 "curl -s http://localhost:9090/-/healthy"
```
Expected: `Prometheus is Healthy.` (pve job will be DOWN until Task 4 adds pve-exporter — fine.)

- [ ] **Step 7: Commit**

```bash
git -C /docker/kuat-drive-yards add ansible/inventory/observability.yml ansible/playbooks/setup_observability.yml ansible/observability/prometheus.yml.j2 ansible/observability/alert.rules.yml ansible/observability/alertmanager.yml.j2
git -C /docker/kuat-drive-yards commit -m "feat(obs): Prometheus + clustered Alertmanager on the obs pair"
```

---

## Task 4: pve-exporter + keepalived VIP (kuat-drive-yards)

**Files:** Create `ansible/observability/pve.yml.j2`, `ansible/playbooks/files/keepalived-obs.conf.j2`; extend `setup_observability.yml`

- [ ] **Step 1: `ansible/observability/pve.yml.j2`** (pve-exporter config; token from env, gitignored)

```yaml
default:
  user: monitoring@pve
  token_name: prom
  token_value: '{{ pve_token }}'
  verify_ssl: false
```

- [ ] **Step 2: `ansible/playbooks/files/keepalived-obs.conf.j2`**

```jinja
global_defs { router_id {{ inventory_hostname }}; script_user root; enable_script_security }
vrrp_script chk_grafana {
    script "/usr/bin/curl -sf -o /dev/null http://127.0.0.1:3000/api/health"
    interval 5
    timeout 4
    rise 2
    fall 2
    weight -60
}
vrrp_instance VI_OBS {
    state {{ keepalived_state }}
    interface eth0
    virtual_router_id 55
    priority {{ keepalived_priority }}
    advert_int 1
    authentication { auth_type PASS; auth_pass ObsHA55 }
    virtual_ipaddress { 192.168.1.17/24 dev eth0 label eth0:vip }
    track_script { chk_grafana }
}
```

- [ ] **Step 3: Append to `setup_observability.yml`**

```yaml
    - name: pve-exporter via pip
      ansible.builtin.pip: {name: prometheus-pve-exporter, state: present, extra_args: --break-system-packages}
    - name: pve-exporter config dir
      ansible.builtin.file: {path: /etc/prometheus, state: directory, mode: '0755'}
    - name: pve.yml
      ansible.builtin.template: {src: ../observability/pve.yml.j2, dest: /etc/prometheus/pve.yml, mode: '0600'}
    - name: pve-exporter systemd unit
      ansible.builtin.copy:
        dest: /etc/systemd/system/pve-exporter.service
        mode: '0644'
        content: |
          [Unit]
          Description=Prometheus PVE Exporter
          After=network.target
          [Service]
          ExecStart=/usr/local/bin/pve_exporter --config.file /etc/prometheus/pve.yml --web.listen-address 127.0.0.1:9221
          Restart=on-failure
          [Install]
          WantedBy=multi-user.target
    - name: keepalived config
      ansible.builtin.template: {src: files/keepalived-obs.conf.j2, dest: /etc/keepalived/keepalived.conf, mode: '0644'}
    - name: Enable services
      ansible.builtin.systemd: {name: "{{ item }}", state: restarted, enabled: true, daemon_reload: true}
      loop: [pve-exporter, keepalived]
```

- [ ] **Step 4: Re-run with the PVE token (from Task 2 Step 1) + webhook**

```bash
cd /docker/kuat-drive-yards/ansible
OBS_DISCORD_WEBHOOK='<webhook>' ansible-playbook playbooks/setup_observability.yml -i inventory/observability.yml -e "pve_token=<PVE_TOKEN_VALUE>"
```
Expected: `failed=0`. (`pve_exporter` binary path may be `/usr/local/bin/pve_exporter` or `~/.local/bin` — adjust the unit ExecStart to `which pve_exporter` if it fails.)

- [ ] **Step 5: Verify VIP + pve metrics + all targets UP**

```bash
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa root@192.168.1.16 "ip -4 addr show eth0 | grep -q 192.168.1.17 && echo 'VIP on MASTER'; curl -s 'http://127.0.0.1:9221/pve?target=192.168.1.5' | grep -c pve_up"
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa root@192.168.1.16 "curl -s 'http://localhost:9090/api/v1/targets' | grep -o '\"health\":\"[a-z]*\"' | sort | uniq -c"
```
Expected: VIP on master; pve metrics present; targets mostly `"health":"up"`.

- [ ] **Step 6: Commit**

```bash
git -C /docker/kuat-drive-yards add ansible/playbooks/setup_observability.yml ansible/observability/pve.yml.j2 ansible/playbooks/files/keepalived-obs.conf.j2
git -C /docker/kuat-drive-yards commit -m "feat(obs): pve-exporter + keepalived VIP .17 for the obs pair"
```

---

## Task 5: Grafana + provisioned datasource/dashboards (kuat-drive-yards)

**Files:** Create `ansible/observability/grafana/{datasource.yml, dashboards.yml}` + `dashboards/*.json`; extend `setup_observability.yml`

- [ ] **Step 1: `ansible/observability/grafana/datasource.yml`**

```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://127.0.0.1:9090
    isDefault: true
```

- [ ] **Step 2: `ansible/observability/grafana/dashboards.yml`**

```yaml
apiVersion: 1
providers:
  - name: homelab
    folder: Homelab
    type: file
    options: {path: /var/lib/grafana/dashboards}
```

- [ ] **Step 3: Fetch the community dashboards (Node Exporter Full 1860, pve-exporter, smartctl)**

```bash
mkdir -p /docker/kuat-drive-yards/ansible/observability/grafana/dashboards
cd /docker/kuat-drive-yards/ansible/observability/grafana/dashboards
curl -sSL "https://grafana.com/api/dashboards/1860/revisions/latest/download" -o node-exporter-full.json
curl -sSL "https://grafana.com/api/dashboards/10347/revisions/latest/download" -o proxmox-pve.json
curl -sSL "https://grafana.com/api/dashboards/22604/revisions/latest/download" -o smartctl.json
ls -l
```
Expected: three non-empty JSON files. (If a dashboard id 404s, find an equivalent on grafana.com and substitute; note it. The dashboards reference a `${DS_PROMETHEUS}` input — Grafana's file provisioning binds it to the default datasource automatically since we set `isDefault: true`.)

- [ ] **Step 4: Append Grafana install + provisioning to `setup_observability.yml`**

```yaml
    - name: Grafana apt key
      ansible.builtin.get_url: {url: https://apt.grafana.com/gpg.key, dest: /usr/share/keyrings/grafana.key, mode: '0644'}
    - name: Grafana repo
      ansible.builtin.apt_repository:
        repo: "deb [signed-by=/usr/share/keyrings/grafana.key] https://apt.grafana.com stable main"
        filename: grafana
        state: present
    - name: Install Grafana
      ansible.builtin.apt: {name: grafana, update_cache: true, state: present}
    - name: Grafana datasource provisioning
      ansible.builtin.copy: {src: ../observability/grafana/datasource.yml, dest: /etc/grafana/provisioning/datasources/prometheus.yml, mode: '0644'}
    - name: Grafana dashboard provider
      ansible.builtin.copy: {src: ../observability/grafana/dashboards.yml, dest: /etc/grafana/provisioning/dashboards/homelab.yml, mode: '0644'}
    - name: Dashboards dir
      ansible.builtin.file: {path: /var/lib/grafana/dashboards, state: directory, owner: grafana, group: grafana, mode: '0755'}
    - name: Copy dashboards
      ansible.builtin.copy: {src: "{{ item }}", dest: /var/lib/grafana/dashboards/, owner: grafana, group: grafana, mode: '0644'}
      with_fileglob: ["../observability/grafana/dashboards/*.json"]
    - name: Bind Grafana to LAN + set admin pw via env
      ansible.builtin.copy:
        dest: /etc/default/grafana-server
        mode: '0644'
        content: |
          GF_SERVER_HTTP_ADDR=0.0.0.0
          GF_SECURITY_ADMIN_PASSWORD={{ grafana_admin_pw }}
    - name: Enable + start Grafana
      ansible.builtin.systemd: {name: grafana-server, state: restarted, enabled: true, daemon_reload: true}
```

- [ ] **Step 5: Re-run (with admin pw)**

```bash
cd /docker/kuat-drive-yards/ansible
OBS_DISCORD_WEBHOOK='<webhook>' ansible-playbook playbooks/setup_observability.yml -i inventory/observability.yml -e "pve_token=<token> grafana_admin_pw=<STRONG_PW>"
```
Expected: `failed=0`. Verify Grafana + datasource + dashboards on both:
```bash
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa root@192.168.1.16 "curl -s http://localhost:3000/api/health"
```
Expected: JSON `{"database":"ok",...}`. (The Canvas topology dashboard is built in the UI in Task 6 Step 4 — Canvas can't be cleanly hand-authored as JSON here.)

- [ ] **Step 6: Commit**

```bash
git -C /docker/kuat-drive-yards add ansible/observability/grafana ansible/playbooks/setup_observability.yml
git -C /docker/kuat-drive-yards commit -m "feat(obs): Grafana + provisioned datasource/dashboards"
```

---

## Task 6: Traefik route + DNS + status verification (homelab-config)

**Files:** Create `nemesis/composed-apps/traefik/config/grafana.yml`

- [ ] **Step 1: `nemesis/composed-apps/traefik/config/grafana.yml`** (route → VIP, LAN-only)

```yaml
http:
  services:
    grafana:
      loadBalancer:
        servers:
          - url: "http://192.168.1.17:3000"
  routers:
    grafana:
      rule: "Host(`grafana.rt-541.io`)"
      entryPoints: [secure]
      service: grafana
      middlewares: [lan-only@docker]
      tls: {certResolver: default}
```
(Reuses the `lan-only@docker` middleware from the umami compose. Traefik file provider auto-reloads.)

- [ ] **Step 2: DNS `grafana.rt-541.io → 192.168.1.214`**

```bash
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa root@192.168.1.3 "pihole-FTL --config dns.hosts" | tr ',' '\n' | tail -2
```
Append after the current last entry (likely `status.rt-541.io` — adjust anchor to what you see):
```bash
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa root@192.168.1.3 "sed -i 's|    \"192.168.1.214 status.rt-541.io\"|    \"192.168.1.214 status.rt-541.io\",\n    \"192.168.1.214 grafana.rt-541.io\"|' /etc/pihole/pihole.toml && pihole reloaddns"
nslookup grafana.rt-541.io 192.168.1.2
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa root@192.168.1.3 "systemctl start pihole-sync.service"
```
Expected: `grafana.rt-541.io → 192.168.1.214`.

- [ ] **Step 3: Verify the route (LAN)**

```bash
curl -sS -o /dev/null -w "grafana (LAN): %{http_code}\n" --resolve grafana.rt-541.io:443:192.168.1.214 https://grafana.rt-541.io/api/health
```
Expected: `200`.

- [ ] **Step 4: Build the Canvas topology dashboard (one-time, you, in the UI)** — `https://grafana.rt-541.io` (LAN, admin / `<STRONG_PW>`) → New dashboard → Canvas panel → add elements for the nodes/guests/services, bind each element's color/threshold to `up{instance="..."}` (or the relevant metric). Save to the Homelab folder.

- [ ] **Step 5: Commit**

```bash
git -C /docker/homelab-config add nemesis/composed-apps/traefik/config/grafana.yml
git -C /docker/homelab-config commit -m "feat(obs): route grafana.rt-541.io to the obs VIP (LAN-only)"
```

---

## Task 7: Alert dedupe test + HA drill + docs

- [ ] **Step 1: All targets up**

```bash
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_rsa root@192.168.1.16 "curl -s http://localhost:9090/api/v1/targets | grep -o '\"health\":\"[a-z]*\"' | sort | uniq -c"
```
Expected: all (or nearly all) `"health":"up"` — node×4, smartctl×2, pve×2, kuma×1.

- [ ] **Step 2: Alert dedupe test** — stop a node_exporter (e.g. `ssh lo204@192.168.1.6 "sudo systemctl stop prometheus-node-exporter"`), wait ~6 min (5m `for` + group_wait), confirm **exactly one** `ExporterDown` Discord message arrives (both Alertmanagers, deduped). Restart it (`...start...`) → resolved message. 

- [ ] **Step 3: HA drill** — `ssh root@192.168.1.16 "systemctl stop keepalived"`; within ~5s confirm VIP `.17` on `192.168.1.18` (`ip a`) and `curl http://192.168.1.17:3000/api/health` still ok; `grafana.rt-541.io` still serves. Restart keepalived on `.16` → VIP returns.

- [ ] **Step 4: SMART check** — `ssh root@192.168.1.16 "curl -s 'http://localhost:9090/api/v1/query?query=smartctl_device_smart_status' | grep -c metric"` > 0; confirm the sienar disks (incl. the `data_lvm_raid` array members) appear in the SMART dashboard.

- [ ] **Step 5: Docs** — create `kuat-drive-yards/docs/OBSERVABILITY.md`: the two LXCs + VIP, the exporters + ports, where configs/dashboards live, how to re-run `setup_observability.yml`, the Alertmanager-dedupe note, the grafana.rt-541.io URL. Commit.

---

## Self-Review notes (addressed)

- **Spec coverage:** obs LXC pair (T1), host+SMART+pve exporters (T2,T4), Prometheus+Alertmanager-cluster (T3), Grafana+dashboards (T5), Traefik LAN route + DNS (T6), Canvas topology (T6 S4), alert rules + dedupe test + HA drill (T3,T7), 30d retention (T3 S5). Kuma /metrics scrape (T3 S2).
- **No placeholders:** runtime secrets (`<PVE_TOKEN_VALUE>`, `<STRONG_PW>`, the webhook via `OBS_DISCORD_WEBHOOK` env) are user-supplied at run time, never committed. Version-nuanced bits (Debian default-args filenames, pve_exporter binary path, dashboard ids, Canvas authoring) carry explicit verify-and-adjust steps.
- **Naming consistency:** `obs-sienar`/`obs-incomm`, VIP `.17`/VRID 55, datasource `Prometheus`, jobs `node`/`smartctl`/`pve`/`kuma`, used consistently.
```

