# llm-jobs

Fire-and-forget LLM jobs for the homelab, run by NanoClaw agent groups.
Replaces the 2026-06 `llm-queue` + `llm-gateway` stack on nemesis
(retired 2026-09-19: zero use in 30 days, and NanoClaw already did the
routing, access control and audit the queue duplicated).

```
caller (Claude Code MCP, or REST with a key)
   -> https://jobs.rt-541.io  (Traefik file-provider route, public, ratelimited)
   -> llm-jobs on devastator :8378 (python stdlib, systemd --user unit)
        keys + jobs in SQLite, one job per tier at a time
   -> ncl tasks create --group jobs-<tier> ... (one-shot NanoClaw task)
   -> agent container wakes, does the job, calls MCP deliver_result
   <- result stored; caller polls get_status / get_result
```

## Tiers

| tier | NanoClaw group | model | notes |
|---|---|---|---|
| `local` (default) | `jobs-local` | qwen3-14b, vLLM on the B70 through the `:8788` proxy, Anthropic blocked | free, private, ~8k output tokens per job (`CLAUDE_CODE_MAX_OUTPUT_TOKENS`), 16 s for a trivial job |
| `claude` | `jobs-claude` | claude-sonnet-5 through the OneCLI vault | metered; per-key daily caps plus a tier-wide cap (200 jobs / 2M output tokens per UTC day across all keys); 50 s for a trivial job |
| `render` | `jobs-render` | Blender 4.2 Cycles on the CPU, claude-sonnet-5 drives it | metered but small (a few tool calls per job), tier cap 30 jobs a day; the prompt is a JSON render recipe, the result lists PNG artifacts; about a minute per 1600 x 1000 view at 128 samples; timeout 3600 s |

## Render tier and artifacts

A tier with `"artifacts": true` gets a folder per job, `LLMJOBS_ARTIFACTS/<job_id>/`
(`/docker/llm-jobs/artifacts` on devastator), mounted into its group at
`/workspace/extra/artifacts`. `get_result` then carries `artifacts: [{name, bytes, url}]`
and `GET /api/jobs/<id>/artifacts/<name>` serves each file to the job's owner.
Folders go with their jobs at retention. A tier's `contract_note` (with
`{job_id}`) is appended to the worker contract.

`jobs-render` runs the `blender-render` skill (`render/`: `render.py` for Blender,
`run.sh` wrapper, `SKILL.md`), installed into the group's `.claude-shared/skills`.
Blender lives at `/docker/blender/current` (read-only mount `blender`), its X
libraries come from the group's `packages_apt` (NanoClaw builds a per-group
image on first spawn), and the group env raises the Bash tool timeout to an
hour. Both host paths are roots in `~/.config/nanoclaw/mount-allowlist.json`.
NanoClaw has no device passthrough, so the B70 is not reachable from agent
containers; `render.py` tries a GPU (`device: auto`) and falls back to the CPU.

Recipe: `model_url` (a shopcad `model.json`, whose `render` block supplies
material presets by `Component/part` glob, views, sun and ground) or `glb_url`,
plus `state`, `views`, `samples`, `width`, `height`, `device`, optional `materials`
and `sun` overrides. Presets: grass, foliage, brick, wallstone, shingle, composite,
flagstone, gravel, soil, concrete, mulch, glass, metal, paint, vinyl, fabric, ash, keep.

`bash deploy-devastator.sh render` is idempotent: Blender download (Berkeley
mirror; download.blender.org sits behind a bot challenge), allowlist roots, the
group with its env, mounts and apt packages, the skill, and the tier entry.

Tiers are the `LLMJOBS_TIERS` JSON in `~/.config/llm-jobs/jobs.env`; the
group folders must exist (deploy script creates them). A tier entry may
carry `daily_jobs` / `daily_tokens`: NanoClaw has no per-group usage cap, so
this is what bounds a metered tier's spend however many keys are out. The
service re-reads the env only on restart (`systemctl --user restart llm-jobs`).

## Surfaces (all bearer-keyed except `/healthz`)

- MCP `POST /mcp` (streamable HTTP, stateless): `list_tiers`, `submit_job(prompt, tier, params)`,
  `get_status`, `get_result`, `cancel_job`, `list_jobs`. Worker keys instead see `deliver_result`.
- REST: `GET /api/tiers`, `POST /api/jobs` (202), `GET /api/jobs?limit=`, `GET /api/jobs/<id>`,
  `GET /api/jobs/<id>/result`, `DELETE /api/jobs/<id>`; `POST /internal/deliver` (worker key).
- `params` hints: `max_words` (int), `format` (string). They become lines in the worker contract.

Results are owner-scoped, kept `LLMJOBS_RETENTION_DAYS` (30). A job with no
delivery inside the tier's `timeout_s` (1200) is failed and its task cancelled.

## Keys

```
bash deploy-devastator.sh key --owner dana --tiers local --daily-jobs 50 --daily-tokens 200000
python3 ~/.local/share/llm-jobs/app/admin.py key list | revoke <id> | jobs | job <id>
```

Roles: `user` (submit), `worker` (deliver; the NanoClaw groups), `admin`.
Friends get `local` only; Claude Code sessions get `local,claude`. Register
in Claude Code with
`claude mcp add --transport http -s user llm-jobs https://jobs.rt-541.io/mcp --header "Authorization: Bearer <key>"`.

## Deploy (devastator, as aschneider)

```
tar -cf - scripts/llm-jobs systemd-unit-files/llm-jobs.service | ssh devastator.rt-541.io \
  'mkdir -p ~/llm-jobs-deploy && tar -xf - -C ~/llm-jobs-deploy'
ssh devastator.rt-541.io bash ~/llm-jobs-deploy/scripts/llm-jobs/deploy-devastator.sh all
```

`service` installs the app to `~/.local/share/llm-jobs/app`, the env file,
the user unit and issues the worker key; `groups` creates `jobs-local` and
`jobs-claude` (model, env, prompt `group/instructions.prepend.md`, MCP
registration once `jobs.rt-541.io` answers); `render` adds the render tier (below); `verify` runs a PONG job on
each tier. The Traefik route is `data-host/composed-apps/traefik/config/devastator-llm-jobs.yml`
(hot-reloaded).

Tests: `python3 -m unittest discover -s scripts/llm-jobs/tests` (21, ncl mocked).

## Gotchas

- `LLMJOBS_TIERS` must be single-quoted in the env file (bash sourcing) and must
  not contain an apostrophe (systemd's EnvironmentFile parser ends the value there).
- NanoClaw materializes `container.json` from the DB at spawn; env and blocked
  hosts are written to `container_configs` by the deploy script, not to the file.
- MCP servers on groups must be HTTPS; an unreachable one breaks every turn, so
  the script only registers it once the route answers.
- One job per group at a time is a service decision, not a NanoClaw limit.
