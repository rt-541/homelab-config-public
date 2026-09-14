# Devastator B70 Bring-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade devastator in place to RHEL 10, bind the `xe` driver to the Intel Arc Pro B70 (`8086:e223`), and serve Qwen2.5-7B-Instruct via a Plex-safe, resource-capped vLLM composed-app.

**Architecture:** Three Ansible playbooks in `kuat-drive-yards` (preflight / upgrade / gpu) executed from tarkin; a stopped vzdump of VM 103 from incomm is the rollback point; ELRepo `kernel-ml` is the fallback if RHEL 10's kernel lacks the `e223` ID; all GPU userspace lives in containers (`intel/llm-scaler-vllm`), composed at `compute-node/composed-apps/plex-compute/` with Discord/autoheal/Dozzle sidecars and Prometheus queue metrics.

**Tech Stack:** leapp, Ansible, Proxmox vzdump, ELRepo kernel-ml, Docker Compose, Intel llm-scaler vLLM (XPU), Prometheus/Grafana (existing obs pair).

**Spec:** `docs/superpowers/specs/2026-06-12-devastator-b70-bringup-design.md`

**Two repos, two workflows:**
- `kuat-drive-yards` — edit in the nemesis clone `/docker/kuat-drive-yards`, commit, push; then on tarkin (`ssh lo204@192.168.1.11`... actually `ssh tarkin` per nemesis ssh config; root or lo204 per existing config) `cd /opt/kuat-drive-yards && git pull --ff-only`, run playbooks from `ansible/`. pellaeon syncs itself via cron.
- `homelab-config` — edit at `/docker/homelab-config` (this repo), commit; deploy on devastator over SSH (`aschneider@192.168.1.216`) with `git pull` + `docker compose`.

**Decisions locked during brainstorming:** in-place leapp 9.6→10; stock RHEL 10 kernel first, ELRepo same-window fallback; RAM stays 32GB (vLLM hard-capped ~8Gi, `--gpu-memory-utilization 0.92` = reserve ~2.5GB VRAM for 1 concurrent 4K transcode; stream #2+ falls back to CPU); one validation model (Qwen2.5-7B-Instruct FP16, ~15GB of 32GB); multi-model deferred to the queue/MCP sub-project; sidecars = Discord + autoheal + Dozzle (port 9999) + queue monitoring as Prometheus scrape AND Discord threshold alerts.

---

### Task 1: Onboard lo204 on devastator

The docker_hosts inventory says lo204 is not yet present on docker hosts. The upgrade playbooks need it.

**Files:**
- Modify: `/docker/kuat-drive-yards/ansible/inventory/docker_hosts.yml` (comment only)

- [ ] **Step 1: Sync the nemesis clone**

```bash
cd /docker/kuat-drive-yards && git pull --ff-only && git status
```
Expected: clean, up to date.

- [ ] **Step 2: Get the lo204 public key**

On nemesis (the fleet key is nemesis `~/.ssh/id_rsa` per repo docs):
```bash
ssh-keygen -y -f ~/.ssh/id_rsa
```
Save the output line; call it `<LO204_PUB>`.

- [ ] **Step 3: Run the existing onboarding playbook from tarkin, limited to devastator**

On tarkin:
```bash
cd /opt/kuat-drive-yards/ansible
ansible-playbook playbooks/create_lo204_account.yml --limit devastator \
  -u aschneider --ask-become-pass \
  -e '{"lo204_ssh_keys": ["<LO204_PUB>"]}'
```
Expected: PLAY RECAP devastator ok, changed>0, failed=0. (If `aschneider` has passwordless sudo, `--ask-become-pass` accepts an empty password; if SSH as aschneider needs a password too, add `--ask-pass`.)

- [ ] **Step 4: Verify lo204 access**

On tarkin:
```bash
ansible devastator -m ping
ansible devastator -m command -a "id"
```
Expected: `pong`; `uid=...(lo204)` with effective root via become.

- [ ] **Step 5: Update the inventory comment**

In `/docker/kuat-drive-yards/ansible/inventory/docker_hosts.yml`, replace the stale comment lines:
```
# lo204 is not yet present on these hosts (docker-host onboarding is a later
# step); until then connect with an existing admin via -u <user> --ask-become-pass.
```
with:
```
# lo204 onboarded: devastator (2026-06-12). nemesis still pending - connect
# to nemesis with an existing admin via -u <user> --ask-become-pass.
```

- [ ] **Step 6: Commit and push**

```bash
cd /docker/kuat-drive-yards
git add ansible/inventory/docker_hosts.yml
git commit -m "docs(inventory): lo204 onboarded on devastator"
git push
```

---

### Task 2: Preflight playbook

Read-only checks (plus installing the leapp tooling itself). Green preflight is the gate for scheduling the window.

**Files:**
- Create: `/docker/kuat-drive-yards/ansible/playbooks/devastator_b70_preflight.yml`

- [ ] **Step 1: Write the playbook**

```yaml
---
# ==============================================================================
# Devastator B70 bring-up - PREFLIGHT (no downtime, no host mutation beyond
# installing the leapp tooling). Run until green before scheduling the window.
#
# Usage (from tarkin):
#   cd /opt/kuat-drive-yards/ansible
#   ansible-playbook playbooks/devastator_b70_preflight.yml
#
# Spec: homelab-config docs/superpowers/specs/2026-06-12-devastator-b70-bringup-design.md
# ==============================================================================

- name: B70 preflight - devastator OS / leapp readiness
  hosts: devastator
  become: true
  gather_facts: true
  tasks:
    - name: Source must be RHEL 9.6+
      ansible.builtin.assert:
        that:
          - ansible_distribution == 'RedHat'
          - ansible_distribution_version is version('9.6', '>=')
          - ansible_distribution_major_version == '9'
        fail_msg: "Expected RHEL 9.6+, got {{ ansible_distribution }} {{ ansible_distribution_version }}"

    - name: RHSM subscription usable
      ansible.builtin.command: subscription-manager status
      register: rhsm
      changed_when: false
      # 'Current' = classic entitlement; 'Disabled' line appears under Simple
      # Content Access, which is also fine for leapp.
      failed_when: "'Overall Status: Current' not in rhsm.stdout and 'Content Access Mode is set to Simple Content Access' not in rhsm.stdout"

    - name: docker-ce repo for EL10 must exist upstream
      ansible.builtin.uri:
        url: https://download.docker.com/linux/rhel/10/x86_64/stable/repodata/repomd.xml
        status_code: 200

    - name: Free space on /docker for models + new images (need >= 60G)
      ansible.builtin.shell: df --output=avail -BG /docker | tail -1 | tr -dc '0-9'
      register: docker_free
      changed_when: false
    - name: Assert /docker free space
      ansible.builtin.assert:
        that: docker_free.stdout | int >= 60
        fail_msg: "Only {{ docker_free.stdout }}G free on /docker; need >= 60G"

    - name: Install leapp tooling
      ansible.builtin.dnf:
        name: leapp-upgrade
        state: present

    - name: Run leapp preupgrade (takes ~10 min)
      ansible.builtin.command: leapp preupgrade
      register: preupgrade
      changed_when: true
      failed_when: false  # judged via the report below

    - name: Read leapp report
      ansible.builtin.slurp:
        src: /var/log/leapp/leapp-report.txt
      register: leapp_report

    - name: Show report summary lines
      ansible.builtin.debug:
        msg: "{{ (leapp_report.content | b64decode).split('\n') | select('search', 'Risk Factor|inhibitor') | list }}"

    - name: Fail if any inhibitor remains
      ansible.builtin.assert:
        that: "'inhibitor' not in (leapp_report.content | b64decode)"
        fail_msg: "leapp preupgrade reports inhibitors - read /var/log/leapp/leapp-report.txt on devastator, resolve, re-run"

- name: B70 preflight - incomm backup capacity
  hosts: incomm.rt-541.io
  become: true
  gather_facts: false
  vars:
    vzdump_storage: local        # override with -e if the backup target differs
    backup_min_free_gb: 150
  tasks:
    - name: VM 103 disk config (for the record)
      ansible.builtin.command: qm config 103
      register: vmcfg
      changed_when: false
    - name: Show VM 103 disks
      ansible.builtin.debug:
        msg: "{{ vmcfg.stdout_lines | select('search', '^(scsi|sata|virtio|ide)[0-9]') | list }}"

    - name: Storage status
      ansible.builtin.shell: pvesm status | awk '$1=="{{ vzdump_storage }}" {print int($6/1024/1024)}'
      register: store_free
      changed_when: false
    - name: Assert backup storage free space (GB)
      ansible.builtin.assert:
        that: store_free.stdout | int >= backup_min_free_gb
        fail_msg: "Storage {{ vzdump_storage }} has {{ store_free.stdout }}G free; need >= {{ backup_min_free_gb }}G (override vzdump_storage/backup_min_free_gb with -e if using another store)"
```

- [ ] **Step 2: Syntax check (on nemesis)**

```bash
cd /docker/kuat-drive-yards/ansible
ansible-playbook --syntax-check playbooks/devastator_b70_preflight.yml
```
Expected: `playbook: playbooks/devastator_b70_preflight.yml` (no errors).

- [ ] **Step 3: Commit and push**

```bash
cd /docker/kuat-drive-yards
git add ansible/playbooks/devastator_b70_preflight.yml
git commit -m "feat(ansible): devastator B70 preflight playbook (leapp readiness + backup capacity)"
git push
```

- [ ] **Step 4: Run from tarkin; iterate until green**

On tarkin:
```bash
cd /opt/kuat-drive-yards && git pull --ff-only
cd ansible && ansible-playbook playbooks/devastator_b70_preflight.yml
```
Expected: both plays `failed=0`. If inhibitors appear: read `/var/log/leapp/leapp-report.txt` on devastator, fix each (common ones: answerfile questions -> `leapp answer --section <section>.confirm=True --add`; firewalld AllowZoneDrifting -> set `AllowZoneDrifting=no` in `/etc/firewalld/firewalld.conf`; deprecated kernel modules), then re-run. Do not proceed to Task 5 until green.

---

### Task 2.5: Pre-window remediation (user-approved 2026-06-12)

Preflight found three blockers; the user approved these fixes. All run from tarkin as ad-hoc Ansible against devastator (production stays up throughout).

**Files:**
- Modify: `/docker/kuat-drive-yards/ansible/playbooks/devastator_b70_preflight.yml` (backup gate only)

- [ ] **Step 1: Grow devastator's root filesystem online (+55GB unpartitioned on /dev/sda)**

From tarkin, each as a separate ad-hoc command:
```bash
ansible devastator -m dnf -a "name=cloud-utils-growpart state=present"
ansible devastator -m command -a "growpart /dev/sda 3"
ansible devastator -m command -a "pvresize /dev/sda3"
ansible devastator -m command -a "lvextend -r -l +100%FREE /dev/rhel_devastator/root"
ansible devastator -m shell -a "df -BG / | tail -1"
```
Expected: final df shows ~104G+ free on /. (growpart returns rc=0 CHANGED; rc=1 "NOCHANGE" means already grown — fine. The LV/VG names must be verified first with `ansible devastator -m shell -a "lvs; vgs"` — adjust the lvextend path if the VG is named differently.)

- [ ] **Step 2: Remove nordvpn**

```bash
ansible devastator -m dnf -a "name=nordvpn state=absent"
ansible devastator -m file -a "path=/etc/ld.so.conf.d/nordvpn.conf state=absent"
ansible devastator -m command -a "ldconfig"
```
Expected: package removed, linker config gone.

- [ ] **Step 3: Lower the incomm backup gate to 60G**

The 150G gate assumed a full-size 200G image; with discard+fstrim in the window (Task 3) the backup shrinks to roughly the ~28G of real data. In `devastator_b70_preflight.yml`, change `backup_min_free_gb: 150` to `backup_min_free_gb: 60` and update its trailing comment. Commit:
```bash
cd /docker/kuat-drive-yards
git add ansible/playbooks/devastator_b70_preflight.yml
git commit -m "fix(ansible): lower B70 backup gate to 60G (fstrim shrinks the vzdump)"
git push
```
Then pull on tarkin.

- [ ] **Step 4: Re-run preflight**

On tarkin: `ansible-playbook playbooks/devastator_b70_preflight.yml`
Expected: the devastator play now passes every gate EXCEPT the final leapp-inhibitor assert, which fails on exactly one inhibitor: "Use of NFS detected" (the Plex NFS docker volume). That inhibitor is resolved inside the maintenance window (Task 3 unmounts it after stopping the stacks). Any OTHER inhibitor or failed gate = stop and report. The incomm play must be fully green (run `--limit incomm.rt-541.io` separately since the devastator play aborts first).

---

### Task 3: Upgrade playbook (the maintenance window, part 1)

**Files:**
- Create: `/docker/kuat-drive-yards/ansible/playbooks/devastator_b70_upgrade.yml`

- [ ] **Step 1: Write the playbook**

```yaml
---
# ==============================================================================
# Devastator B70 bring-up - UPGRADE WINDOW. Stops every compose stack, takes a
# stopped vzdump of VM 103 from incomm (full rollback point), then leapp
# 9.6 -> 10, dnf update to current 10.x, and brings the stacks back.
#
# REQUIRES: green devastator_b70_preflight.yml run first.
# DOWNTIME: Plex, rollback Pi-hole, devastator Traefik, exporters for the
#           duration (backup ~30-60 min + leapp ~60-90 min).
#
# Usage (from tarkin):
#   ansible-playbook playbooks/devastator_b70_upgrade.yml -e confirm=yes
# ==============================================================================

- name: Gate
  hosts: devastator
  gather_facts: false
  tasks:
    - name: Refuse to run without explicit confirmation
      ansible.builtin.assert:
        that: confirm | default('no') == 'yes'
        fail_msg: "Pass -e confirm=yes to run the upgrade window"

- name: Stop all compose stacks on devastator
  hosts: devastator
  become: true
  gather_facts: false
  vars:
    compose_root: /docker/homelab-config/compute-node/composed-apps
    stacks: [plex, pihole, traefik, node-exporter, docker-socket-proxy]
  tasks:
    - name: docker compose down each stack
      ansible.builtin.command:
        cmd: docker compose down
        chdir: "{{ compose_root }}/{{ item }}"
      loop: "{{ stacks }}"
      register: downs
      changed_when: true
      failed_when: downs is failed and 'no configuration file' not in (downs.stderr | default(''))

    - name: Nothing left running
      ansible.builtin.command: docker ps -q
      register: leftover
      changed_when: false
    - name: Assert no containers
      ansible.builtin.assert:
        that: leftover.stdout == ''
        fail_msg: "Containers still running: re-check before powering off"

    # The Plex NFS docker volume is leapp's one remaining inhibitor; with the
    # stacks down it can be unmounted. Docker only remounts it when a container
    # using it starts, and all containers are gone until the post-upgrade play.
    - name: Unmount any NFS mounts (leapp inhibitor)
      ansible.builtin.shell: |
        for m in $(findmnt -t nfs,nfs4 -n -o TARGET); do umount "$m"; done
        findmnt -t nfs,nfs4 -n -o TARGET | wc -l
      register: nfs_left
      changed_when: true
    - name: Assert no NFS mounts remain
      ansible.builtin.assert:
        that: nfs_left.stdout_lines[-1] == '0'
        fail_msg: "NFS still mounted - leapp will inhibit"

- name: Enable discard on VM 103 disk (so fstrim can shrink the backup)
  hosts: incomm.rt-541.io
  become: true
  gather_facts: false
  tasks:
    - name: Current scsi0 value
      ansible.builtin.shell: qm config 103 | awk '/^scsi0:/ {print $2}'
      register: scsi0
      changed_when: false

    - name: Add discard=on (skip if already set)
      ansible.builtin.command: qm set 103 --scsi0 "{{ scsi0.stdout }},discard=on"
      when: "'discard=on' not in scsi0.stdout"
      changed_when: true

    - name: Stop/start cycle so discard takes effect
      ansible.builtin.command: "{{ item }}"
      loop:
        - qm shutdown 103 --timeout 300
        - qm start 103
      when: "'discard=on' not in scsi0.stdout"
      changed_when: true

- name: Trim the guest filesystems
  hosts: devastator
  become: true
  gather_facts: false
  tasks:
    - name: Wait for devastator
      ansible.builtin.wait_for_connection:
        timeout: 600
    - name: fstrim all filesystems (releases stale thin-pool blocks)
      ansible.builtin.command: fstrim -av
      register: trim
      changed_when: true
    - name: Show trim results
      ansible.builtin.debug:
        var: trim.stdout_lines

- name: Stopped vzdump of VM 103 from incomm
  hosts: incomm.rt-541.io
  become: true
  gather_facts: false
  vars:
    vzdump_storage: local
  tasks:
    - name: Backup (VM restarted by rescue if anything fails)
      block:
        - name: Shut down VM 103
          ansible.builtin.command: qm shutdown 103 --timeout 300
          changed_when: true

        - name: Wait for stopped
          ansible.builtin.command: qm status 103
          register: vmstat
          until: "'stopped' in vmstat.stdout"
          retries: 30
          delay: 10
          changed_when: false

        - name: vzdump VM 103 (stop mode; async up to 2h)
          ansible.builtin.command: >-
            vzdump 103 --mode stop --storage {{ vzdump_storage }}
            --compress zstd --notes-template 'pre-leapp-B70-{{ now(utc=true, fmt="%Y-%m-%d") }}'
          async: 7200
          poll: 60
          changed_when: true
      rescue:
        - name: Backup failed - restart VM 103 so services return, then abort
          ansible.builtin.command: qm start 103
          changed_when: true
        - name: Abort the window
          ansible.builtin.fail:
            msg: "vzdump failed; VM 103 restarted; window aborted with no changes made"

    - name: Start VM 103
      ansible.builtin.command: qm start 103
      changed_when: true

- name: Leapp upgrade on devastator
  hosts: devastator
  become: true
  gather_facts: false
  tasks:
    - name: Wait for devastator to come back
      ansible.builtin.wait_for_connection:
        timeout: 600

    - name: Re-check NFS is not mounted (nothing should have remounted it)
      ansible.builtin.shell: findmnt -t nfs,nfs4 -n -o TARGET | wc -l
      register: nfs_check
      changed_when: false
    - name: Assert no NFS
      ansible.builtin.assert:
        that: nfs_check.stdout == '0'
        fail_msg: "NFS remounted after reboot - unmount before leapp"

    - name: Disable third-party repos during the upgrade
      ansible.builtin.command: dnf config-manager --set-disabled docker-ce-stable
      changed_when: true

    - name: Gather facts (already-upgraded guard, makes re-runs safe)
      ansible.builtin.setup:

    - name: Leapp (skipped if this is a re-run already on RHEL 10)
      when: ansible_distribution_major_version == '9'
      block:
        - name: leapp upgrade (async, up to 2h; no Lightspeed auto-registration)
          ansible.builtin.command: leapp upgrade
          environment:
            LEAPP_NO_INSIGHTS_REGISTER: "1"
          async: 7200
          poll: 60
          register: leapp_run
          changed_when: true

        - name: Reboot into the upgrade initramfs (this phase alone can take ~1h)
          ansible.builtin.reboot:
            reboot_timeout: 7200
            post_reboot_delay: 60

    - name: Re-gather facts
      ansible.builtin.setup:

    - name: Assert RHEL 10
      ansible.builtin.assert:
        that: ansible_distribution_major_version == '10'
        fail_msg: "Still on {{ ansible_distribution_version }} - leapp did not complete; check /var/log/leapp/leapp-upgrade.log"

    - name: Re-enable docker-ce repo ($releasever now resolves to 10)
      ansible.builtin.command: dnf config-manager --set-enabled docker-ce-stable
      changed_when: true

    - name: Update to current RHEL 10.x content (also upgrades docker-ce to el10 builds)
      ansible.builtin.dnf:
        name: '*'
        state: latest
      register: dnf_update

    - name: Reboot onto the newest RHEL 10 kernel
      ansible.builtin.reboot:
        reboot_timeout: 1200

    - name: Docker service up
      ansible.builtin.systemd:
        name: docker
        state: started
        enabled: true

- name: Bring compose stacks back
  hosts: devastator
  become: true
  gather_facts: false
  vars:
    compose_root: /docker/homelab-config/compute-node/composed-apps
    stacks: [docker-socket-proxy, node-exporter, traefik, pihole, plex]
  tasks:
    - name: docker compose up -d each stack
      ansible.builtin.command:
        cmd: docker compose up -d
        chdir: "{{ compose_root }}/{{ item }}"
      loop: "{{ stacks }}"
      changed_when: true

    - name: All expected containers running
      ansible.builtin.command: docker ps --format '{{ "{{" }}.Names{{ "}}" }}'
      register: running
      changed_when: false
    - name: Show running containers
      ansible.builtin.debug:
        var: running.stdout_lines
```

- [ ] **Step 2: Syntax check**

```bash
cd /docker/kuat-drive-yards/ansible
ansible-playbook --syntax-check playbooks/devastator_b70_upgrade.yml
```
Expected: no errors.

- [ ] **Step 3: Commit and push**

```bash
cd /docker/kuat-drive-yards
git add ansible/playbooks/devastator_b70_upgrade.yml
git commit -m "feat(ansible): devastator leapp 9->10 upgrade window playbook"
git push
```

---

### Task 4: GPU playbook (the maintenance window, part 2)

**Files:**
- Create: `/docker/kuat-drive-yards/ansible/playbooks/devastator_b70_gpu.yml`

- [ ] **Step 1: Write the playbook**

```yaml
---
# ==============================================================================
# Devastator B70 bring-up - GPU DRIVER. Checks whether the running kernel binds
# xe to the Arc Pro B70 (8086:e223); if not, installs ELRepo kernel-ml
# (mainline) as the same-window fallback and reboots into it. Ends with a
# containerized sycl-ls smoke test.
#
# Usage (from tarkin, after devastator_b70_upgrade.yml):
#   ansible-playbook playbooks/devastator_b70_gpu.yml
# ==============================================================================

- name: B70 xe driver binding
  hosts: devastator
  become: true
  gather_facts: true
  tasks:
    - name: Current binding state for 8086:e223
      ansible.builtin.command: lspci -nnk -d 8086:e223
      register: b70
      changed_when: false

    - name: Bound already?
      ansible.builtin.set_fact:
        xe_bound: "{{ 'Kernel driver in use: xe' in b70.stdout }}"

    - name: Report
      ansible.builtin.debug:
        msg: "RHEL kernel {{ ansible_kernel }} {{ 'BINDS' if xe_bound else 'does NOT bind' }} the B70"

    - name: ELRepo fallback
      when: not xe_bound
      block:
        # ansible-core 2.14 (tarkin) cannot fetch URLs through RHEL 10's
        # Python 3.12 (urllib cert_file API change), so the key import and
        # URL-install use the target's own rpm/dnf CLI instead of
        # rpm_key/dnf-from-URL modules.
        - name: Import ELRepo key
          ansible.builtin.command: rpm --import https://www.elrepo.org/RPM-GPG-KEY-v2-elrepo.org
          changed_when: true

        - name: Install elrepo-release
          ansible.builtin.command: dnf install -y https://www.elrepo.org/elrepo-release-10.el10.elrepo.noarch.rpm
          register: elrepo_install
          changed_when: "'already installed' not in elrepo_install.stdout"

        - name: Install mainline kernel
          ansible.builtin.dnf:
            name: kernel-ml
            enablerepo: elrepo-kernel
            state: present

        - name: Newest installed kernel path
          ansible.builtin.shell: ls -1v /boot/vmlinuz-*elrepo* | tail -1
          register: mlkernel
          changed_when: false

        - name: Set kernel-ml as default boot entry
          ansible.builtin.command: grubby --set-default "{{ mlkernel.stdout }}"
          changed_when: true

        - name: Reboot into kernel-ml
          ansible.builtin.reboot:
            reboot_timeout: 1200

        - name: Re-check binding
          ansible.builtin.command: lspci -nnk -d 8086:e223
          register: b70_after
          changed_when: false

        - name: Assert xe bound now
          ansible.builtin.assert:
            that: "'Kernel driver in use: xe' in b70_after.stdout"
            fail_msg: >-
              kernel-ml still does not bind xe. Check 'dmesg | grep -iE "xe|firmware"'
              on devastator - if GuC/HuC firmware blobs are missing, fetch the exact
              files dmesg names from
              https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain/xe/
              into /lib/firmware/xe/ and reboot.

    - name: Render node present
      ansible.builtin.find:
        paths: /dev/dri
        patterns: 'renderD*'
        file_type: any
      register: render
    - name: Assert render node
      ansible.builtin.assert:
        that: render.files | length >= 1
        fail_msg: "No /dev/dri/renderD* node - xe bound but no render device; check dmesg"

    - name: Containerized GPU smoke test (sycl-ls)
      ansible.builtin.command: >-
        docker run --rm --device /dev/dri:/dev/dri
        intel/llm-scaler-vllm:0.14.0-b8.3.1 sycl-ls
      register: syclls
      changed_when: false

    - name: Assert Level Zero sees the GPU
      ansible.builtin.assert:
        that: "'level_zero' in syclls.stdout"
        fail_msg: "sycl-ls found no level_zero GPU: {{ syclls.stdout }}"
    - name: Show sycl-ls
      ansible.builtin.debug:
        var: syclls.stdout_lines
```

- [ ] **Step 2: Verify the llm-scaler image tag**

Check https://hub.docker.com/r/intel/llm-scaler-vllm/tags (or https://github.com/intel/llm-scaler) for the current recommended tag. If `latest` is not published or Intel recommends a pinned tag (e.g. a `*-b*` build), update the image reference in this playbook AND in Task 6's compose file to the pinned tag.

- [ ] **Step 3: Syntax check**

```bash
cd /docker/kuat-drive-yards/ansible
ansible-playbook --syntax-check playbooks/devastator_b70_gpu.yml
```
Expected: no errors.

- [ ] **Step 4: Commit and push**

```bash
cd /docker/kuat-drive-yards
git add ansible/playbooks/devastator_b70_gpu.yml
git commit -m "feat(ansible): devastator B70 xe driver playbook with ELRepo kernel-ml fallback"
git push
```

---

### Task 5: Run the maintenance window

Manual gates between phases. User schedules the window (Plex viewers warned).

- [ ] **Step 1: Final preflight**

On tarkin:
```bash
cd /opt/kuat-drive-yards && git pull --ff-only
cd ansible && ansible-playbook playbooks/devastator_b70_preflight.yml
```
Expected: every gate passes except the final leapp-inhibitor assert, which fails on exactly ONE inhibitor: "Use of NFS detected" — the playbook's stop-stacks play unmounts it before leapp runs, so that one is acceptable. Any other inhibitor or failed gate: STOP.

- [ ] **Step 2: Run the upgrade playbook**

```bash
ansible-playbook playbooks/devastator_b70_upgrade.yml -e confirm=yes
```
Expected: all plays `failed=0`; final debug shows the five stack containers running. Budget 2-4 hours. If it fails mid-leapp and the VM is unbootable: restore the vzdump from incomm (`qmrestore <backup> 103 --force true`) - that is the designed rollback.

- [ ] **Step 3: Verify services from the LAN**

From nemesis:
```bash
curl -sf -o /dev/null -w '%{http_code}\n' http://192.168.1.216:32400/identity   # Plex
ssh aschneider@192.168.1.216 'cat /etc/redhat-release && docker ps --format "{{.Names}}"'
```
Expected: `200`; `Red Hat Enterprise Linux release 10.x`; five containers.

- [ ] **Step 4: Run the GPU playbook**

```bash
ansible-playbook playbooks/devastator_b70_gpu.yml
```
Expected: ends with sycl-ls listing a `level_zero` GPU device. Note in the task output whether the stock RHEL kernel bound xe or the ELRepo fallback fired - record that in the final commit message (Task 9).

---

### Task 6: plex-compute composed-app (vLLM + sidecars)

**Files:**
- Create: `/docker/homelab-config/compute-node/composed-apps/plex-compute/docker-compose.yml`
- Create: `/docker/homelab-config/compute-node/composed-apps/plex-compute/notify.sh`
- Create: `/docker/homelab-config/compute-node/composed-apps/plex-compute/.env.example`

- [ ] **Step 1: Check the image entrypoint**

On devastator:
```bash
sudo docker pull intel/llm-scaler-vllm:0.14.0-b8.3.1
sudo docker image inspect intel/llm-scaler-vllm:0.14.0-b8.3.1 --format 'ENTRYPOINT={{.Config.Entrypoint}} CMD={{.Config.Cmd}}'
```
If ENTRYPOINT is empty or a shell, keep the explicit `entrypoint: ["vllm"]` below. If the image defines its own serving entrypoint, drop the `entrypoint:` line and adapt `command:` to that entrypoint's argument convention (check `docker run --rm intel/llm-scaler-vllm:0.14.0-b8.3.1 --help` style output).

- [ ] **Step 2: Write docker-compose.yml**

```yaml
services:
  vllm:
    image: intel/llm-scaler-vllm:0.14.0-b8.3.1
    container_name: plex-compute-vllm
    restart: unless-stopped
    devices:
      - /dev/dri:/dev/dri
    shm_size: 4g
    entrypoint: ["vllm"]
    command:
      - serve
      - Qwen/Qwen2.5-7B-Instruct
      - --host
      - "0.0.0.0"
      - --port
      - "8000"
      - --served-model-name
      - qwen2.5-7b-instruct
      # reserve ~2.5GB (8%) of the 32GB card for Plex: 1 concurrent 4K HDR
      # transcode (~2GB) + driver headroom; additional streams fall back to CPU
      - --gpu-memory-utilization
      - "0.92"
      - --max-model-len
      - "16384"
    environment:
      HF_HOME: /models
    volumes:
      - /docker/llm/models:/models
    ports:
      - "8000:8000"
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:8000/health || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 5
      # first start downloads ~15GB of weights then loads them
      start_period: 30m
    deploy:
      resources:
        limits:
          cpus: '8'
          memory: 8G
        reservations:
          cpus: '2'
          memory: 4G
    labels:
      - "autoheal=true"

  plex-compute-discord:
    image: alpine:latest
    container_name: plex-compute-discord
    restart: unless-stopped
    depends_on:
      - vllm
    environment:
      - WEBHOOK_URL=${WEBHOOK_URL}
      - QUEUE_ALERT_THRESHOLD=${QUEUE_ALERT_THRESHOLD:-5}
    volumes:
      - ./notify.sh:/notify.sh:ro
    entrypoint: /bin/sh
    command: ["/notify.sh"]
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: "128M"
        reservations:
          cpus: '0.25'
          memory: "64M"

  plex-compute-autoheal:
    image: willfarrell/autoheal:latest
    container_name: plex-compute-autoheal
    restart: unless-stopped
    environment:
      AUTOHEAL_CONTAINER_LABEL: autoheal
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock

  plex-compute-logs:
    image: amir20/dozzle:latest
    container_name: plex-compute-logs
    restart: unless-stopped
    ports:
      - "9999:8080"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      DOZZLE_FILTER: "name=plex-compute*"
```

- [ ] **Step 3: Write notify.sh** (up/down + queue-depth alerts in one monitor)

```sh
#!/bin/sh
apk add --no-cache curl >/dev/null 2>&1
command -v curl >/dev/null 2>&1 || { echo "FATAL: curl install failed"; exit 1; }
[ -n "$WEBHOOK_URL" ] || { echo "FATAL: WEBHOOK_URL is empty - set it in .env"; exit 1; }

THRESHOLD="${QUEUE_ALERT_THRESHOLD:-5}"
VLLM=http://vllm:8000

send() {
  TITLE="$1"
  COLOR="$2"
  DESC="$3"
  if [ -n "$DESC" ]; then
    JSON="{\"username\":\"B70 vLLM\",\"embeds\":[{\"title\":\"${TITLE}\",\"description\":\"${DESC}\",\"color\":${COLOR},\"footer\":{\"text\":\"plex-compute on devastator\"}}]}"
  else
    JSON="{\"username\":\"B70 vLLM\",\"embeds\":[{\"title\":\"${TITLE}\",\"color\":${COLOR},\"footer\":{\"text\":\"plex-compute on devastator\"}}]}"
  fi
  curl -sf -X POST "$WEBHOOK_URL" -H 'Content-Type: application/json' -d "$JSON"
}

healthy() {
  curl -sf -m 5 "$VLLM/health" >/dev/null 2>&1
}

queue_depth() {
  curl -sf -m 5 "$VLLM/metrics" 2>/dev/null \
    | grep '^vllm:num_requests_waiting' | tail -1 \
    | awk '{print int($NF)}'
}

echo "Waiting for vLLM to become healthy (model load can take many minutes)..."
while ! healthy; do sleep 30; done
send "vLLM Up" 65280 "Serving qwen2.5-7b-instruct on the B70"

QUEUE_ALERTED=0
while true; do
  sleep 30
  if ! healthy; then
    send "vLLM Down" 16711680
    while ! healthy; do sleep 30; done
    send "vLLM Up" 65280 "Back online"
    QUEUE_ALERTED=0
    continue
  fi
  DEPTH=$(queue_depth)
  [ -z "$DEPTH" ] && DEPTH=0
  if [ "$DEPTH" -gt "$THRESHOLD" ] && [ "$QUEUE_ALERTED" -eq 0 ]; then
    send "vLLM Queue Backlog" 16753920 "${DEPTH} requests waiting (threshold ${THRESHOLD})"
    QUEUE_ALERTED=1
  elif [ "$DEPTH" -le "$THRESHOLD" ] && [ "$QUEUE_ALERTED" -eq 1 ]; then
    send "vLLM Queue Drained" 65280 "${DEPTH} requests waiting"
    QUEUE_ALERTED=0
  fi
done
```

- [ ] **Step 4: Write .env.example**

```
# Copy to .env (gitignored). Webhook: reuse the nemesis-bot one
# (data-host/composed-apps/nemesis-bot/.env on nemesis).
WEBHOOK_URL=https://discord.com/api/webhooks/CHANGEME
QUEUE_ALERT_THRESHOLD=5
```

- [ ] **Step 5: Commit**

```bash
cd /docker/homelab-config
git add compute-node/composed-apps/plex-compute/
git commit -m "feat(plex-compute): B70 vLLM composed-app with discord/autoheal/dozzle sidecars"
git push
```

- [ ] **Step 6: Deploy on devastator**

```bash
ssh aschneider@192.168.1.216
cd /docker/homelab-config && git pull --ff-only
sudo mkdir -p /docker/llm/models
cd compute-node/composed-apps/plex-compute
cp .env.example .env   # then paste the real webhook URL into .env
sudo docker compose up -d
sudo docker logs -f plex-compute-vllm   # watch model download + load
```
Expected: vLLM logs end with the Uvicorn "Application startup complete" / listening on 0.0.0.0:8000; `docker ps` shows plex-compute-vllm healthy after start_period.

- [ ] **Step 7: Inference smoke test from nemesis**

```bash
curl -sf http://192.168.1.216:8000/v1/models | head -c 400; echo
curl -sf http://192.168.1.216:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen2.5-7b-instruct","messages":[{"role":"user","content":"Reply with exactly: B70 ONLINE"}],"max_tokens":20}'
```
Expected: model list includes `qwen2.5-7b-instruct`; completion content contains "B70 ONLINE". Also confirm tokens/s is GPU-like (the response returns within a couple of seconds, vs ~minutes on CPU Ollama for the same).

---

### Task 7: Queue metrics into Prometheus + alert

**Files:**
- Modify: `/docker/kuat-drive-yards/ansible/observability/prometheus.yml.j2` (add scrape job)
- Modify: `/docker/kuat-drive-yards/ansible/observability/alert.rules.yml` (add rule)

- [ ] **Step 1: Read both files first** to match their existing structure, then add, under `scrape_configs:` in `prometheus.yml.j2`:

```yaml
  - job_name: 'vllm'
    static_configs:
      - targets: ['192.168.1.216:8000']
        labels:
          instance: 'devastator-b70'
```

and to the rules group in `alert.rules.yml`:

```yaml
      - alert: VLLMQueueBacklog
        expr: vllm:num_requests_waiting > 5
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "vLLM queue backlog on the B70"
          description: "{{ $value }} requests waiting for >10m - friends are queuing; consider the CPU fallback or capacity."
      - alert: VLLMDown
        expr: up{job="vllm"} == 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "vLLM scrape target down"
```
(If `alert.rules.yml` templates `{{ }}` literally through Ansible's copy module it is fine as-is; it is copied, not templated — verify it uses `ansible.builtin.copy` in `setup_observability.yml`, which it does per the existing playbook.)

- [ ] **Step 2: Commit, push, re-run the observability playbook from tarkin**

```bash
cd /docker/kuat-drive-yards
git add ansible/observability/
git commit -m "feat(obs): scrape vLLM queue metrics + backlog/down alerts"
git push
```
On tarkin:
```bash
cd /opt/kuat-drive-yards && git pull --ff-only
cd ansible && ansible-playbook playbooks/setup_observability.yml
```
Expected: `failed=0`.

- [ ] **Step 3: Verify the target**

```bash
curl -sf 'http://192.168.1.17:9090/api/v1/targets' | grep -o '"job":"vllm"[^}]*"health":"[a-z]*"'
```
Expected: `"health":"up"`. Then eyeball `vllm:num_requests_waiting` in the Grafana Explore view at `grafana.rt-541.io` and add a panel to the existing dashboard (manual UI step, same as the Canvas TODO).

---

### Task 8: Plex hardware transcode on the B70

**Files:**
- Modify: `/docker/homelab-config/compute-node/composed-apps/plex/docker-compose.yml`

- [ ] **Step 1: Check Plex's Battlemage support status**

Search the Plex forums/changelog for current Battlemage (Arc B-series) HW transcode support in Plex Media Server. If unsupported as of today: skip Steps 2-4, leave Plex on CPU transcode (no regression - it was CPU-only before this project), and file the flip as a follow-up. Record the finding in the commit message.

- [ ] **Step 2: Read the current plex compose file**, then add to the plex service:

```yaml
    devices:
      - /dev/dri:/dev/dri
```

- [ ] **Step 3: Redeploy plex**

```bash
ssh aschneider@192.168.1.216
cd /docker/homelab-config && git pull --ff-only
cd compute-node/composed-apps/plex
sudo docker compose down && sudo docker compose up -d
```

- [ ] **Step 4: Enable + verify HW transcode**

In Plex web UI: Settings -> Transcoder -> enable "Use hardware acceleration when available". Play a film that forces transcode (set client quality to 720p 4Mbps). On devastator:
```bash
sudo docker exec plex sh -c 'ls -la /dev/dri'    # nodes visible in the container
sudo cat /sys/class/drm/card1/device/uevent      # confirm card1 is the B70
```
In Plex dashboard the session should show "(hw)" in the transcode badge. If it transcodes but without (hw), Plex's transcoder doesn't handle Battlemage yet - revert the toggle, keep the device mount, done (CPU behavior unchanged).

- [ ] **Step 5: Commit**

```bash
cd /docker/homelab-config
git add compute-node/composed-apps/plex/docker-compose.yml
git commit -m "feat(plex): mount /dev/dri for B70 hardware transcode"
git push
```

---

### Task 9: Contention test + wrap-up

- [ ] **Step 1: Sustained LLM load**

From nemesis, 4 concurrent request loops for ~10 minutes:
```bash
for i in 1 2 3 4; do (
  end=$((SECONDS+600))
  while [ $SECONDS -lt $end ]; do
    curl -sf -o /dev/null http://192.168.1.216:8000/v1/chat/completions \
      -H 'Content-Type: application/json' \
      -d '{"model":"qwen2.5-7b-instruct","messages":[{"role":"user","content":"Write 300 words about shipyards."}],"max_tokens":512}'
  done ) & done; wait
```

- [ ] **Step 2: Concurrent Plex playback**

While Step 1 runs, play a transcoding stream (HW if Task 8 enabled it, else CPU). Watch for stutter/buffering for at least 5 minutes.

- [ ] **Step 3: Check the graphs**

On `grafana.rt-541.io`: devastator RAM stays under its 23Gi allocation with headroom (vLLM container pinned <= 8G), CPU not pegged at 100% across all cores, `vllm:num_requests_waiting` rises and drains. Pass = no transcode stutter, no OOM-kills (`ssh aschneider@192.168.1.216 'dmesg | grep -i oom'` is empty).

- [ ] **Step 4: Final docs commit**

Update the spec status line to `Status: Implemented YYYY-MM-DD` and note which kernel path won (stock RHEL 10 vs ELRepo kernel-ml):
```bash
cd /docker/homelab-config
git add docs/superpowers/specs/2026-06-12-devastator-b70-bringup-design.md
git commit -m "docs: B70 bring-up implemented (kernel path: <stock|elrepo>; plex hw transcode: <yes|deferred>)"
git push
```

---

## Self-review notes

- Spec coverage: preflight checks (Task 2) = spec component 1; upgrade window (Tasks 3, 5) = component 2 backup/leapp; GPU bind + ELRepo fallback + sycl-ls gate (Tasks 4, 5) = component 2 GPU phase; vLLM app + caps (Task 6) = component 3 + resource caps; Plex device mount (Task 8) = component 4; contention test (Task 9) = spec testing section; queue monitoring (Task 7 + notify.sh) covers the sidecar decisions added after the spec (Discord + autoheal + Dozzle + Prometheus).
- Known runtime unknowns are encoded as explicit verify steps, not assumptions: llm-scaler image tag/entrypoint (Task 4 Step 2, Task 6 Step 1), whether stock RHEL 10 binds e223 (Task 4 handles both branches), Plex Battlemage support (Task 8 Step 1 gate), incomm vzdump storage name (`-e vzdump_storage=...` override).
- The `{{ "{{" }}.Names{{ "}}" }}` escaping in the upgrade playbook is required because docker's Go template braces collide with Jinja2.
