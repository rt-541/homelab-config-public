# llm-gateway

LAN-only LiteLLM proxy that owns per-user API keys and quotas for the LLM fleet.
Fronts the B70 vLLM (GPU) and nemesis CPU Ollama. The `llm-queue` app validates
caller keys against this gateway and routes jobs through it; this gateway is
never exposed to the internet.

- Aliases (model groups): `fast` (vLLM), `background` / `reasoning` (Ollama).
- Reachable at `https://llm-gateway.rt-541.io` from any LAN host (subject to the
  lan-only allowlist), including the nemesis host itself (.214 is on the LAN).
  The bare name `llm-gateway` only resolves inside the proxy Docker network.
- Keys and quotas live in the Postgres sidecar `llm-gateway-db` (data at
  `/docker/llm-gateway/data/postgres`). LiteLLM requires Postgres — its bundled
  Prisma schema rejects sqlite.

## Run
    cd /docker/homelab-config/nemesis/composed-apps/llm-gateway
    sudo docker compose down && sudo docker compose up -d   # restart = down+up

## Issue / revoke a key

Run from any LAN host (curl is on the host; it is NOT in the LiteLLM image, so do
not `docker exec ... curl`). Reach the gateway through Traefik:

    source .env   # provides LITELLM_MASTER_KEY
    # issue (returns {"key":"sk-..."}):
    curl -s https://llm-gateway.rt-541.io/key/generate \
      -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H 'Content-Type: application/json' \
      -d '{"models":["fast","background","reasoning"],"max_budget":5,"rpm_limit":20,"tpm_limit":40000,"max_parallel_requests":2,"duration":"30d"}'
    # revoke:
    curl -s https://llm-gateway.rt-541.io/key/delete \
      -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H 'Content-Type: application/json' \
      -d '{"keys":["sk-..."]}'
