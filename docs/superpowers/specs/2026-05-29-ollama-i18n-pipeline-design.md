# Auto-translating i18n pipeline (Ollama + DeepSeek-R1)

## Goal

Edit any translatable English string in the about-site, run `npm run build`, and all six language blocks ship up to date. Translations run locally on `nemesis` (CPU-only, no GPU), cached by content hash so unchanged English skips the LLM. No third-party translation API. Hand-pinned translations survive across regens: edit the **cache file** (`.translations-cache.json`), not `ui.ts` directly. The cache value is reused as long as the recorded hash still matches the current English.

## Architecture

Three pieces, each replaceable behind a stable boundary.

### 1. `composed-apps/ollama/` (new Docker Compose app)

- `ollama/ollama:latest` bound to `127.0.0.1:11434` only. No Traefik route, no public exposure.
- Bind-mount `/docker/ollama` to `/root/.ollama` so the ~5GB weights persist across restarts.
- Healthcheck: HTTP GET `/api/tags`, 30s interval.
- Resource caps: 12 CPUs, 8G memory limit; 1G memory reservation. Leaves four threads and headroom for the rest of the host.
- Model pull is a one-time documented setup step: `docker exec ollama ollama pull deepseek-r1:7b`. Not baked into the image, not auto-pulled by entrypoint.

Sidecars (all in the same compose file):
- **`ollama-discord`**: Alpine container, `notify.sh` script copied/adapted from `composed-apps/minecraft-atm9-survival/notify.sh`. Polls the main service via TCP `127.0.0.1:11434`, fires `WEBHOOK_URL` on up/down transition. Webhook URL lives in `composed-apps/ollama/.env` (directory-level gitignored).
- **`ollama-autoheal`**: `willfarrell/autoheal:latest`. Scoped via container label, not the project-default `AUTOHEAL_CONTAINER_LABEL: all`. The `all` setting would have this instance manage every healthcheck-enabled container on the host. Scoping isolates it:
  ```yaml
  ollama:
    labels: ["autoheal=true"]
  ollama-autoheal:
    environment:
      AUTOHEAL_CONTAINER_LABEL: autoheal
  ```
- **`ollama-logs`**: `amir20/dozzle:latest` on host port `9999` (LAN-accessible via `0.0.0.0:9999:8080`, clear of existing assignments: 6969 Pi-hole, 7878 Radarr, 8989 Sonarr, 16261-4 Zomboid, 27015-6 RCON). `DOZZLE_FILTER: "name=ollama*"`. Reachable from the LAN at `http://nemesis:9999/`.

### 2. `composed-apps/about-site/scripts/regen-i18n.ts` (translator)

Reads `t.en` from `src/i18n/ui.ts` (the registry, source of truth for translatable content), consults `src/i18n/.translations-cache.json` (committed to git), calls Ollama for cache misses, rewrites `src/i18n/ui.ts` with all six blocks.

Cache schema:

```json
{
  "ja": {
    "home.eyebrow": { "hash": "<sha256(en_value)>", "value": "..." }
  }
}
```

Cache hit when `cache[lang][key].hash === sha256(t.en[key])`. Any English change invalidates that pair only. Manual edits to the cache file pin a translation: the next regen treats it as cached as long as the recorded hash matches the current English.

**Hand-editing `ui.ts` directly does not survive a regen.** The script rewrites `ui.ts` from `cache` plus fresh Ollama calls on every run. To pin a translation, edit `cache[lang][key].value` (leave the recorded hash matching the current English). This is the documented workflow for any human polish pass.

CLI flags:
- `--dry-run`: print the (lang, key) miss list, do not write files.
- `--force`: ignore cache, retranslate everything.
- `--lang ja`: single language only.
- `--key prefix.`: key prefix filter for debugging.

`OLLAMA_URL` env var defaults to `http://127.0.0.1:11434`. Overrideable for development.

Failure semantics:
- Per-call retry with backoff (1s, 3s, 10s). After 3 failures on one key, log and keep the prior cached value if any; otherwise leave that key absent (the apply-script's existing `t.en` fallback covers it at render time).
- Ollama unreachable from the first probe: warn, do not touch any files, exit 0. Build proceeds.
- Exit code: **0 on success or transient Ollama failure**; non-zero only on the parity guard failure (corrupt dictionary state) or CLI usage errors.

### 3. Build hook in `composed-apps/about-site/package.json`

```json
"prebuild": "node --experimental-strip-types scripts/regen-i18n.ts",
"regen-i18n": "node --experimental-strip-types scripts/regen-i18n.ts",
"test": "node --experimental-strip-types --test scripts/*.test.ts"
```

`prebuild` runs automatically before `astro build` on every `npm run build`. Warm-cache runs are near-instant. Cold or delta runs hit Ollama. `npm run dev` is untouched: iteration on English copy is not slowed by LLM calls.

Node version: requires Node 22.6+ for `--experimental-strip-types`. The Astro project already runs on Node 22+ (the parity check in the prior i18n plan used the same flag successfully).

## Prompt strategy

Chat-format, system + user.

**System prompt:**

```
You are writing first-person personal-portfolio copy in ${LANG_NAME}, not translating it.

Read the English. Then write what a native ${LANG_NAME}-speaking platform engineer would naturally write to say the same thing on their own personal website. Restructure sentences for natural ${LANG_NAME} flow. Do NOT preserve English word order or sentence boundaries when they would sound awkward. Drop pronouns where the target language normally would. Use idiomatic equivalents, not calques. No translator-speak, no over-formal register, no padding.

Register per language:
  ja: ですます調, natural omission of subjects, 私 only when needed
  ko: 합니다체 (격식체), 저 only when needed, natural ellipsis
  zh: 书面语 but conversational, avoid over-explicit 我/的
  es: tuteo (tú), neutral Spain/LatAm where possible, no usted
  de: du form, no Sie, no needless nominalization

Match the source's tone. Self-deprecating where the source is self-deprecating, technical-precise where it is technical, terse where it is terse. "// section" labels keep the // prefix verbatim.

Output ONLY the rewritten text. No explanation, no preamble, no surrounding quotes.

Preserve these tokens verbatim, untranslated: ${KEEP_VERBATIM.join(', ')}.
```

**User prompt:** the English value, nothing else.

**`KEEP_VERBATIM` const** (in `scripts/translate-prompt.ts`):

Astro, Tailwind, nginx, Traefik, Docker Compose, Discord, Project Zomboid, Minecraft, All the Mods 9, Valheim, Palworld, V Rising, Enshrouded, Factorio, Core Keeper, Abiotic Factor, Valhelsia, Prusa, RCON, XP, AWS Bedrock, Ansible Automation Platform, OpenShift, MCP, Model Context Protocol, RT-541, Pi-hole, Saturn, Magic: The Gathering, Strixhaven, Ravnica, Lorehold, Prismari, Quandrix, Silverquill, Witherbloom, Aelrith Varn, Underdark, Azur, Boros, Severed Maws, Snork, Chromatic Dragonborn, War Mind, Perfect Plan, Analyze, Boros Legionnaire, ADR, OpenNMT, Build 42, Red Hat Satellite, RHEL, kickstart, runbook.

**Response extraction.** DeepSeek-R1 distills emit `<think>...</think>` reasoning before the answer. The script takes everything after the **last** `</think>`, trims, strips wrapping quotes and code fences.

**Decoding.** `temperature: 0`, no seed override, sequential calls. Same English in to same translation out across runs (modulo Ollama version changes). Cache-miss diffs stay reviewable.

**Reserve quality pass (not v1).** If v1 output reads stiff, add a self-critique step: send the candidate back with "rewrite if it sounds like a translation; keep if it sounds native." Doubles latency on misses, cache covers the steady state. Decide after reading v1 output.

## Source-of-truth caveat

`t.en` in `src/i18n/ui.ts` is the canonical English for every translated key. Project `.md` frontmatter `summary` and the `.astro` static-fallback text **should** mirror `t.en['project.<slug>.summary']` (etc.); the apply-script's render fallback already prefers the static markup for the English path. The pipeline does not sync between the two. Drift means English renders from frontmatter / markup, other languages render from the cached translations of `t.en`. Keeping them in sync is a convention, not a feature of this pipeline.

## Failure and operational behavior

- Ollama unreachable: regen warns, leaves files untouched, exit 0, build continues.
- Per-call timeout (default 60s): retry 3x with backoff. Skip on final fail.
- Build never fails on a translator outage.
- Dev workflow (`npm run dev`) does not trigger regen.
- Cache file (`.translations-cache.json`) is committed to git so fresh clones start warm.
- First-time setup:
  1. `cd /docker/nemesis-configs/composed-apps/ollama && sudo docker compose up -d`
  2. `sudo docker exec ollama ollama pull deepseek-r1:7b` (~5GB pull)
  3. From `composed-apps/about-site/`: `npm run regen-i18n` (cold-fills the cache)
  4. Commit `.translations-cache.json` and the regenerated `ui.ts`

## Testing

Node's built-in `node:test` with `--experimental-strip-types`. No new test deps. Tests live next to the script as `scripts/regen-i18n.test.ts`.

**Unit (pure functions):**

1. `extractTranslation(rawResponse)`: strips `<think>...</think>`, trims, dequotes. Fixtures: with reasoning, without reasoning, wrapped in quotes, wrapped in code fence, multiple `<think>` blocks (takes after the last).
2. `hashEn(value)`: `sha256(value)`. One test locks the schema; cache invalidation depends on this being stable.
3. `computeMisses(cache, tEn, langs)`: empty cache (all miss), partial cache (deltas only), English changed under same key (that pair becomes a miss).
4. `emitUiTs({en, ja, ko, zh, es, de})`: emitted string is written to a temp file and loaded via dynamic `import()` (Node strips types natively), the resulting `t` matches the input shape, key order matches `Object.keys(en)`, every value round-trips through `JSON.parse(JSON.stringify(v))`, all six blocks have identical key sets.
5. `buildPrompt(enValue, lang, keepVerbatim)`: KEEP_VERBATIM injected, language-specific register note present, English appears verbatim in the user message.

**Integration (mocked Ollama via in-test `http.createServer`):**

6. Cold cache, mock Ollama responsive: 3-key fixture, canned `<think>r</think>translation` responses. After running: cache file written, all 3 keys x 5 langs filled, `ui.ts` produced, parity holds.
7. Warm cache, mock Ollama hostile (any request fails): zero requests made to the mock, `ui.ts` regenerated from cache alone.
8. Ollama unreachable (no server bound on the test port): script warns, exits 0, existing `ui.ts` and cache file unchanged.
9. Per-call failure under retry budget: mock fails twice then succeeds. Backoff respected, eventual translation captured.

**Build-time guard:**

10. Dictionary parity check (same shape as the prior i18n plan, node `--experimental-strip-types` one-liner over `t`). Runs as the **last** step of `regen-i18n` and is exit-blocking. Catches code paths where partial writes corrupt the dictionary.

**Operational smoke (README, not automated):**

11. `docker compose up -d` then `curl -fsS http://127.0.0.1:11434/api/tags | jq .` returns the model list.
12. `npm run build` from `composed-apps/about-site/` succeeds end-to-end with the prebuild hook in place; `dist/` carries all six languages in the JS bundle.

**Not tested.** Translation *quality* (human review only; the cache pre-warming plus manual polish path is the answer here). Ollama version drift. The cam stream and other prior i18n surfaces (already covered by their own checks).

## Out of scope (YAGNI)

- Auto-running on `npm run dev`.
- A web UI for the translator.
- Auto-committing the regen output.
- Multi-model voting or consensus.
- Public Traefik route for Ollama or Dozzle.
- Backup of model weights (trivially re-pullable from the Ollama registry).
- Syncing `.md` frontmatter and `.astro` static text with `t.en` automatically.
- A pre-commit git hook (the build-time hook covers the trigger).

## Files

**Create:**

- `composed-apps/ollama/docker-compose.yml`
- `composed-apps/ollama/.env.example` (WEBHOOK_URL placeholder)
- `composed-apps/ollama/.gitignore` (`.env`)
- `composed-apps/ollama/notify.sh` (Discord poller, adapted from `composed-apps/minecraft-atm9-survival/notify.sh`)
- `composed-apps/ollama/README.md` (first-time setup, model pull, troubleshooting, where to find logs)
- `composed-apps/about-site/scripts/regen-i18n.ts`
- `composed-apps/about-site/scripts/regen-i18n.test.ts`
- `composed-apps/about-site/scripts/translate-prompt.ts` (prompt builder + `KEEP_VERBATIM` const)
- `composed-apps/about-site/src/i18n/.translations-cache.json` (committed, initial content `{}`)

**Modify:**

- `composed-apps/about-site/package.json` (add `prebuild`, `regen-i18n`, `test` scripts)
- `CLAUDE.md` (add `ollama` to the existing-apps roster; document the `regen-i18n` workflow under the about-site notes)
