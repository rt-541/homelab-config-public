---
title: "The kernel panic was a bit flip"
date: 2026-09-14
dek: "A Docker host that kept panicking in kswapd looked like it had a kernel bug; a crash dump showed one flipped bit in a page structure, and the next day the same flaky hardware took down the Docker daemon and every container on the box for ten hours."
tags: ["homelab", "linux", "proxmox", "docker", "debugging"]
---

The homelab's main Docker host is nemesis, a RHEL 9 virtual machine on a Proxmox host called sienar. When it panics, every site behind it is down until kdump finishes and the VM reboots, about ten minutes each time. Over the summer it panicked a lot.

## A pattern that pointed at the kernel

In the first two weeks of August there were nine panics on one kernel build, seven of them the same NULL pointer dereference inside `kswapd0`, the kernel's page-reclaim thread. That reads like a kernel bug, and the obvious fix was a kernel update. The update landed on August 24 and the host looked clean for six days.

Then three more events, all on the new kernel:

- **August 30:** a panic, "stack-protector: Kernel stack is corrupted in futex_parse_waitv", on a thread belonging to a headless browser.
- **September 12:** a `refcount_t: underflow; use-after-free` warning while freeing credentials.
- **September 13:** another `kswapd0` Oops, this time a bad page fault in a spinlock slow path, reached from the multi-generational LRU (MGLRU) reclaim code.

Memory pressure was not the trigger: the VM was 22% used with swap idle. kswapd runs constantly only because page cache always fills the VM, so it touches more pages than anything else and is the likeliest code to trip over a damaged one.

Three corruption signatures in unrelated subsystems within two weeks is not what one kernel bug looks like.

## What the vmcore said

With `crash` and the matching `kernel-debuginfo`, the September 13 dump could be walked by hand. Reclaim had taken a lock through `folio->mapping->host`, and that lock address was inside the dentry slab. Walking back from the folio:

```
folio->mapping (observed)   ffff89417d547db0
real i_data of that inode   ffff89417d547df0
difference                  0x40, one bit
```

The observed pointer sits inside a live XFS inode (a 19 GB movie on the media array), and cannot be the `i_data` of any inode in that slab layout, so it is corrupted, not stale. One bit in a `struct page` had flipped.

The August 30 dump agreed: the stack protector had fired, yet the stack, task and per-CPU canaries were all identical at dump time. The comparison had read a wrong value once.

The hardware underneath explains why. sienar is an X299 board with an i7-7820X and non-ECC memory (the kernel log says `EDAC skx: ECC is disabled on imc 0`), and it was running KSM, which merges identical pages across guests. The leading hypothesis became host memory or CPU flakiness, not a RHEL kernel bug.

## The next day

On September 14 the same flakiness showed up in user space. dockerd died with a Go runtime fatal error, `found pointer to free object`, which is the garbage collector noticing heap corruption. The restarted daemon killed every orphaned container: 49 of them across 21 compose projects, including the edge proxy, this site, the media stack and the Discord bot.

`restart: unless-stopped` brought back exactly one of them.

## What it cost

- **About ten hours of a dark host,** from morning until evening.
- **An uptime monitor that could not see it.** The monitor builds its container checks dynamically and drops the ones for containers that are not running, so a mass stop looks like fewer monitors, not red ones. Only five static checks went red.
- **A straggler that had been down for four weeks.** After the September 13 panic, one service was found still `Exited (255)` from a crash in August. Neither the restart policy nor autoheal (which only restarts unhealthy running containers) had noticed.

Recovery was manual: each project brought back with `docker compose up -d` from the directory named in its containers' compose labels.

## What changed

- **Revive stragglers at boot.** `scripts/revive-stragglers.sh` finds containers that are exited with code 255, have a restart policy of `always` or `unless-stopped`, and are compose-managed, then runs `docker compose up -d` for those services from their own directories. Deliberately stopped stacks exit with other codes and are left alone. A systemd unit runs it two minutes after Docker starts.
- **live-restore configured.** Docker's `live-restore` setting keeps containers running across a daemon restart, so the next dockerd crash should not take the containers with it. It is in the daemon config and takes effect at the next daemon reload.
- **KSM off on sienar,** so one flipped page cannot be shared into another guest.
- **MGLRU switch in the repo.** A tmpfiles.d entry disables MGLRU reclaim:

  ```
  w /sys/kernel/mm/lru_gen/enabled - - - - n
  ```

  It is not applied yet, and the RCA marks it optional: it removes the code path that tripped twice, but the next flip would just land somewhere else.
- **vmcore pruning.** Since late July, a tmpfiles.d rule prunes kdump dumps older than 14 days, so a run of panics cannot fill the 20 GB `/var` volume (each dump is about 1 GB).
- **An RCA in the repo,** with the dump tables.

## What is still open

- Move the nemesis VM to a different Proxmox node for a few weeks as an A/B test. If the panics stop there, sienar is the cause.
- Run memtest86+ on sienar in a maintenance window.
- Add a monitor on the running-container count, so a mass stop is visible even when the per-container checks vanish.

## What carries forward

A crash that keeps landing in the same kernel function is not proof of a kernel bug; it can be proof that the function touches the most memory. Different signatures in unrelated code on the same machine point below the software, and a crash dump plus debug symbols can turn that hunch into a one-bit diff. On the Docker side: a restart policy is not a recovery plan after an unclean crash, and a monitor that only watches what is running cannot report what stopped.
