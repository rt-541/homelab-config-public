# Remote Admin Problem Statement & Roadmap

## Problem Statement

Managing a self-hosted media stack as a remote admin creates three compounding problems:

1. **Invisible failures** — containers go down silently. The first signal is usually a text from someone who can't watch anything, not a proactive alert.

2. **High manual intervention cost** — simple fixes (restart a container, check a VPN tunnel, grab a specific release) require SSH access, context-switching, and time — often at inconvenient hours.

3. **Support burden** — others using the stack (family/friends) have no way to help themselves beyond basic Overseerr requests. Anything outside that requires you.

These three issues compound: a silent failure becomes a support request, which requires manual intervention. The current stack has good automation at the download layer (Sonarr/Radarr/qBittorrent) but lacks automation at the *operational* layer.

---

## Current State

The alerting and monitoring layer is already largely built:

- Custom container monitor handles container up/down detection
- gluetun VPN tunnel health is monitored specifically
- Disk fullness monitoring is in place
- All alerts route to Discord via webhook

Phase 1 is effectively done. The gap is at the **self-service layer**.

---

## Phase 1: Automation & Self-Healing ✅ (largely complete)

**Goal:** Eliminate "I found out it was broken because someone texted me."

| Component | Status |
|-----------|--------|
| Container health monitoring | Done |
| gluetun / VPN tunnel monitoring | Done |
| Disk fullness alerts | Done |
| Discord alert channel | Done |

**Remaining gap:** Alerts fire when things break, but there's no automated *recovery* — restarts are still manual.

---

## Phase 2: Self-Service (Next)

**Goal:** Brother can resolve common issues himself without texting me.

### Primary — Discord Bot for Self-Service Actions

Extend the existing Discord setup with a bot that exposes safe, role-gated commands:

| Command | Action |
|---------|--------|
| `!status` | Show health of all services |
| `!restart qbittorrent` | Unstick a hung download |
| `!restart plex` | Bounce Plex if streams are broken |

- Commands are **role-gated** — only approved users (brother, etc.) can trigger actions
- No commands that touch config, data, or cause destructive changes
- Bot lives in the existing Discord server alongside alerts

### Secondary — Status Page

A read-only page showing green/red per service so brother can self-diagnose before reaching out. Low priority — Discord `!status` covers most of this.

**Success criteria:** Brother can self-diagnose and fix the top 3 common issues without involving me.

---

## Out of Scope

- Full dashboard UI
- Anything that could cause data loss or config changes
- Exposing admin-level controls to external users

---

## Sharing This With Your Brother

This doc is written as a personal roadmap. When Phase 2 is built, the relevant section (what commands he can use and how) can be pulled into its own document for him alongside the existing README.
