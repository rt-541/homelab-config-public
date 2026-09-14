---
title: "nemesis-configs homelab"
order: 4
status: active
summary: "The self-hosted estate this site runs on. Around 25 services behind Traefik on bare metal."
---

A single git repo that defines the whole estate: Docker Compose for every service, Traefik for routing and TLS, Pi-hole for internal DNS, and a wildcard domain that resolves to the LAN inside and the WAN outside.

Game servers, a media stack, monitoring, and a handful of web apps, all managed the same way. The goal is that anything I run is reproducible from the repo and nothing lives only in my head.
