---
title: "Moving DNS off the crashing host"
date: 2026-09-16
dek: "DNS and DHCP left a Docker host with a panic habit for a pair of Pi-hole containers on two Proxmox nodes, and the same pattern now carries the control plane, the uptime monitor and the metrics stack."
tags: ["homelab", "dns", "proxmox", "high-availability", "pi-hole", "keepalived", "prometheus"]
---

DNS and DHCP used to run as a Pi-hole in Docker on nemesis, the main Docker host, with a second Pi-hole on devastator answering DNS only. When the host holding that container went away, nothing on the network could resolve a name until it came back.

## Why the host was the problem

nemesis is a virtual machine on the Proxmox node sienar, and it has a crash history. Through August and September it logged a run of kernel panics with different signatures. A crash dump showed a page's mapping pointer exactly one bit away from the real value. The verdict was flaky memory on a host without ECC, not a kernel bug. Each panic costs eight to ten minutes of reboot.

The move itself was forced earlier, in June, by a different failure. A cluster link flap split the two Proxmox nodes, one lost quorum and wedged, and it had to be power-cycled. While it was down there was no DNS anywhere.

## The pair

DNS and DHCP now run on two small containers, one on each Proxmox node: `dns-incomm` and `dns-sienar`. Each is a privileged Debian 12 LXC running Pi-hole v6 natively, not in Docker. keepalived holds a virtual address between them. The incomm member is the master; if its Pi-hole stops answering, the address moves to sienar.

DHCP follows the same address. keepalived's notify script turns DHCP on for whichever member holds the address and off on the other, and it only acts on a real state change, so the two never hand out leases at the same time. The router's own DHCP is off. Clients get the shared address as their DNS server, so a failover changes nothing on their side.

Records and reservations are edited on the primary only. nebula-sync copies them to the secondary.

The old Docker Pi-holes stayed up for a soak period as a rollback, then were decommissioned.

## One record for every service

Internal DNS now carries a single wildcard: every name under the homelab's domain resolves to the reverse proxy host. A new web service needs a routing rule on the proxy and nothing else: no per-service record to add, forget or leave behind. Outside the network the same names resolve through the public DNS provider.

Pi-hole v6 also registers the hostnames of machines that take a lease, so every host gets a name without anyone writing it down.

## The mechanism that still looked alive

The Docker-host repository still holds an Ansible playbook that writes DNS entries to `custom.list`, the Pi-hole v5 way to add local records. Pi-hole v6 keeps them in `pihole.toml` under `dns.hosts`, and the old container it targeted no longer exists. The playbook is a no-op. It does not fail; it just publishes nothing.

A record was once added there, looked finished, and had to be reverted when it turned out to reach no resolver. When a service moves, the old way of changing it has to be deleted or loudly marked, because a mechanism that runs clean and does nothing looks exactly like one that works.

## Names, not addresses

The desktop that holds the note vaults has a DHCP reservation, so its address should never change. Twice it did. In June an SSH connection to the reserved address returned "No route to host" while the same connection by name went straight through; the name followed the machine's real lease and the pinned address was stale. In September it happened again, and vault syncs that used the address directly failed silently. The cause is still open.

The rule: reach hosts by name. A hardcoded address is only as good as the reservation behind it, and nothing warns when that goes stale.

## The control plane

The DNS pair became the template. There are now four pairs of LXCs, each pinned to physical nodes rather than living inside a VM that can crash:

- **Control:** tarkin on incomm (primary) and pellaeon on sienar (failover), carrying OpenTofu, Ansible and a clone of the infrastructure repo. pellaeon pulls the repo every ten minutes.
- **DNS:** the Pi-hole pair above.
- **Uptime monitor:** Uptime Kuma on both nodes. Only the member holding the shared address sends alerts, and its container monitors are reconciled every two minutes against what is actually running.
- **Observability:** Prometheus with 30 days of retention, Grafana, and a two-member Alertmanager cluster that gossips so each alert arrives in Discord once. Exporters cover hosts, disk SMART data and the Proxmox API.

The monitor and observability masters sit on sienar, the node with the redundant power supply; a watcher should not share fate with what it watches. Fleet changes run from tarkin out of the infrastructure repo, not as ad-hoc SSH from wherever the session happens to be, so every change stays written down.

## What did not work

- **The first temperature alert.** It fired on the sensor's own "high" threshold. The label varies per chip: the i7-12700K in incomm reports 80 C as "high", which is its normal running temperature, so it paged constantly. The rule now uses absolute thresholds on the hottest core, warning at 95 C and critical at 98 C.
- **Then the alert was right.** incomm hard-crashed on a thermal fault in July, and later ran at 92 to 100 C at about 11 percent CPU load. That is cooling, not load, and it still needs a hardware fix.
- **Packaged services in LXC.** Pi-hole FTL, Prometheus and Grafana ship hardened systemd units that need a drop-in before they start in a container.
- **The Pi-hole configuration is still imperative.** The wildcard and the keepalived setup were applied by hand on both members and are not yet in Ansible.

## What carries forward

Every new core service gets the same shape: two LXCs on two nodes, one shared address, one writer syncing to the other, and alerts from whichever member holds the address. Names over addresses, one wildcard over many records, and a replaced mechanism gets removed so it cannot pretend to work.
