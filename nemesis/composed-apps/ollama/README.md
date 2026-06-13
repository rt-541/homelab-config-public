# Ollama (local LLM)

Local Ollama running `qwen2.5:7b` for the about-site i18n auto-translation pipeline. CPU-only, no GPU on this host.

## First-time setup

```bash
cp .env.example .env
# edit .env, set WEBHOOK_URL to a Discord webhook
sudo docker compose up -d
sleep 30
sudo docker exec ollama ollama pull qwen2.5:7b   # ~5GB pull
```

## Smoke test

```bash
curl -sS http://127.0.0.1:11434/api/tags | jq .
```

## Where things live

- Model weights: `/docker/ollama/` (host bind mount)
- Logs: Dozzle at `http://nemesis:9999/` (or `docker logs ollama`)
- Discord alerts: fires `WEBHOOK_URL` on up/down transitions (gitignored .env)
- Autoheal: restarts the main container if the healthcheck fails (scoped via `autoheal=true` label, NOT the project-default `AUTOHEAL_CONTAINER_LABEL: all`)

## Restart

```bash
cd /docker/homelab-config/nemesis/composed-apps/ollama
sudo docker compose down
sudo docker compose up -d
```

## Used by

- `composed-apps/about-site` runs `npm run regen-i18n` (and `prebuild`) against this service to populate `src/i18n/ui.ts` from `t.en`. Cache lives at `composed-apps/about-site/src/i18n/.translations-cache.json` (committed to git, content-hash keyed).

### Translation quality gate (GPU runs)

For a high-quality cache fill, the translator runs on the RTX 5080 on host
Rocinante with a two-layer gate (see `composed-apps/about-site/scripts/validate-translation.ts`
and the `OLLAMA_GATE_ENABLED` flag). The local CPU Ollama here is the
fallback/default; the gate is opt-in and not used by the warm-cache prebuild.
