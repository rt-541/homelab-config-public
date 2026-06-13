# homelab-config

A personal homelab Infrastructure-as-Code monorepo, published as a showcase. It holds
the Docker Compose stacks, Ansible playbooks, systemd units, and operational runbooks
that run a two-host homelab plus a small fleet of Proxmox/LXC control-plane services.

This is the real configuration that runs the homelab, with all secrets removed (see
[Secrets](#secrets) below). It is shared to show how the pieces fit together, not as a
turnkey product.

## Structure

This is a per-host monorepo — one directory tree per physical host, plus shared tooling
at the root.

```
nemesis/composed-apps/<app>/      # Docker Compose apps on host "nemesis"
                                  #   game servers (Zomboid, Valheim, Minecraft, Palworld,
                                  #   Core Keeper, Enshrouded, Abiotic Factor), the about-site,
                                  #   Ollama, Umami, Vikunja, Mealie, a Discord bot, etc.
devastator/composed-apps/<app>/   # Docker Compose apps on host "devastator"
                                  #   Plex, Pi-hole, Traefik, and a vLLM compute stack
ansible/                          # Playbooks + inventory for host/LXC provisioning
scripts/                          # Operational scripts (e.g. Zomboid world-reset / RCON tooling)
systemd-unit-files/               # systemd units installed on the hosts
firewall/                         # Firewall configuration
docs/                             # Design docs, plans, and runbooks
```

Each app directory is a self-contained Docker Compose stack. Many use sidecars for
scheduled backups (offen/docker-volume-backup), Discord up/down notifications, autoheal,
and Dozzle log viewing.

## Secrets

**No secrets live in this repository.** Every credential — Discord webhooks, RCON and
server passwords, API tokens, database passwords, WireGuard keys, ACME/Cloudflare
credentials — is supplied at runtime from a gitignored `.env` (or `override.env` /
`default.env`) file that stays on the host.

For every stack that needs secrets there is a committed `.env.example` documenting the
required variable names with empty values. To run a stack: copy the example to the real
filename (`.env`) and fill in your own values.

```
cp .env.example .env   # then edit .env with real values
```

This public copy has been scrubbed: any value that had previously been hardcoded in a
tracked file has been redacted to `CHANGEME`. The site's already-public information (the
`rt-541.io` domain, RFC1918 `192.168.1.x` addresses used internally, and the about-site
bio) is intentionally retained, since none of it is a credential.

## Notes

- `CLAUDE.md` documents conventions for working in this repo (Docker Compose usage, the
  sidecar catalogue, the about-site i18n pipeline). It contains no secrets.
- Paths inside the configs reference on-host locations like `/docker/...` and
  `/docker/game/...`; adapt them to your own layout if you reuse anything here.

## License

No license has been chosen yet. Until one is added, all rights are reserved — please
treat this as reference material rather than something to copy wholesale. (Repository
owner: pick and add a `LICENSE` file before relying on this.)
