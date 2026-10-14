---
title: "LLM jobs on an agent fleet"
date: 2026-09-19
dek: "The homelab's fire-and-forget LLM job service, first built as a queue in front of a LiteLLM gateway, then rebuilt so every job is a one-shot task for a NanoClaw agent group, with local, Claude and Blender render tiers."
tags: ["homelab", "agents", "llm", "nanoclaw", "mcp"]
---

Some LLM work does not belong in the session that thinks of it: a hundred summaries, a batch of classifications, a long low-stakes draft, anything private that should stay on the LAN. The homelab has a small service for that. A caller submits a prompt and a tier, gets a job id back at once, and collects the result later. It has now been built twice.

## Version one: a queue and a gateway

The June 2026 version ran on nemesis as two stacks. `llm-queue` was a FastAPI app with a web dashboard, a REST API and an MCP endpoint, all over one SQLite database in WAL mode. Callers picked a capability alias (`fast` on the B70's vLLM, `background` and `reasoning` on CPU Ollama), and each alias had its own worker so a slow CPU job never blocked a GPU job.

The second phase put a LiteLLM gateway in front of the models. The gateway issued each user a virtual key, and that key was the login everywhere: web UI, REST and MCP. The queue scoped jobs to a hash of the key, and ran every job through the gateway as that user, so quotas lived in one place. That meant the worker needed the caller's key after the request had returned, so each job row carried the key Fernet-encrypted, and the worker decrypted it, ran the job and scrubbed it once the job was finished or cancelled. LiteLLM would not keep its keys in SQLite, so the gateway also needed a Postgres sidecar.

It worked, and it was a lot of machinery.

## The fleet it moved onto

In September the homelab got a NanoClaw fleet on devastator. NanoClaw runs Claude Code agents in containers, organized as agent groups: each group has its own instructions, its own skills, its own mounts and environment, and wakes for messages from a channel or for scheduled and one-shot tasks. Some groups talk to Anthropic directly. Others run on qwen3-14b, served by vLLM on the local B70 and reached through a small normalizing proxy that makes the local model's API behave enough like Anthropic's for the Claude Code harness (it folds system messages, clamps output tokens and turns off qwen3's thinking mode).

That fleet already did the routing, access control and audit the queue had built for itself. And nothing had used the queue in 30 days.

## Version two: jobs as agent tasks

On 2026-09-19 the queue and the gateway were composed down and removed from the repo. The replacement, `llm-jobs`, is a Python standard-library service running as a systemd user unit on devastator. It owns two things, keys and jobs, both in one SQLite file. Everything else is NanoClaw.

A job goes like this:

1. A caller submits a prompt and a tier.
2. The service creates a one-shot NanoClaw task on that tier's agent group.
3. The group's container wakes with a short worker contract prepended: do exactly the job, deliver once, no channel posts, no questions.
4. The agent calls the service's MCP tool `deliver_result` with the job id and its answer, or with an error sentence if the job cannot be done.
5. The caller polls and fetches.

Claude Code sessions reach it as an MCP server with three tools that matter: `submit_job`, `get_status` and `get_result` (plus `list_tiers`, `list_jobs` and `cancel_job`). A typical call looks like:

```
submit_job(
  tier="local",
  prompt="Summarize the release notes below in five bullets for a homelab operator. <notes...>",
  params={"max_words": 150}
)
```

The prompt must be self-contained; the worker sees nothing else. The `params` hints become lines in the worker contract. Keys are bearer keys, scoped per owner: a caller sees only its own jobs, and results are kept 30 days. One job runs per tier at a time, and a job with no delivery inside its timeout is failed and its task cancelled.

## Three tiers

- **local** runs on the `jobs-local` group: qwen3-14b through the proxy, with Anthropic blocked from the container. Free and private. A trivial job came back in 16 seconds.
- **claude** runs on `jobs-claude`: Sonnet, metered. A trivial job took 50 seconds. NanoClaw has no per-group usage cap, so the service enforces one: per-key daily caps, plus a tier-wide daily ceiling on jobs and output tokens that every key shares. However many keys are out, the metered tier has one ceiling.
- **render**, added on 2026-09-26, runs on `jobs-render`. The prompt is a JSON recipe (a model URL, views, samples, size), the group has a `blender-render` skill and a read-only Blender install, and it renders stills headless with Cycles. A tier can ask for artifacts, and this one does: each job gets its own folder mounted into the container, `get_result` lists the files, and the service serves them to the job's owner. With `"photo": true` in the recipe, the worker also calls `request_photo` for each view and polls `photo_status`. That queues a pass through the GPU arbiter on devastator, which lends the B70 from vLLM to a FLUX Kontext image model when the card is idle, and writes a photo next to each render.

The worker tools (`deliver_result`, `request_photo`, `photo_status`) are visible only to workers.

## What did not work

- **qwen3 cannot drive tool calls through the proxy.** Plain text jobs work on the local tier. Behind the proxy, qwen3-14b fails on tool-call turns with "Content block is not a text block", and a render job is nothing but tool calls. The render tier runs on Sonnet instead, under its own small daily cap; a render job needs only a few of those calls.
- **No GPU in agent containers.** NanoClaw has no device passthrough, so Blender renders on the CPU, about 35 seconds a view at 128 samples. The photo step gets the GPU only because the arbiter runs on the host, outside NanoClaw, and the worker asks it for photos over MCP.

## What carries forward

The second version is smaller because it stopped owning things another system already owned. The job service keeps keys, jobs, caps and artifacts; NanoClaw keeps models, containers, skills and credentials. A new tier is a new agent group with its own instructions and skills, plus one entry in the tier table, which is how a Blender renderer arrived a week later without any change to how callers submit. And the delivery contract is the same for every tier: the worker calls one tool, exactly once, and stops.
