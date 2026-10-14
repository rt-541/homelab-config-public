---
name: blender-render
description: Render photoreal still images of a shopcad 3D model (or any GLB) with Blender Cycles from a JSON recipe, writing PNGs into the job's artifact folder. Use for every job on the llm-jobs render tier.
---

# blender-render

The job prompt is a JSON render recipe. Render it with one command and
deliver the summary it prints.

1. Write the recipe exactly as given (the JSON between the job markers) to
   `/tmp/<job_id>.json`.
2. Run, with the Bash tool and a timeout of 3600000 ms:
   `bash ~/.claude/skills/blender-render/run.sh <job_id> /tmp/<job_id>.json`
3. On success it prints one JSON line (device, samples, seconds per view,
   files). If the recipe has no `photo` field, deliver that line as the
   result, preceded by one sentence ("Rendered N views on CPU.").
   If the recipe has `"photo": true` (or `"photo": {"prompt": "..."}`), do
   the photo step (below) first, then deliver the render line plus the
   photo files.
4. On failure (non-zero exit) deliver an error with the last few lines it
   printed. Do not retry more than once, and never change the recipe's
   meaning; fixing a typo in a view name to match the model's list is fine.

Recipe fields (see render.py for the rest): `model_url` (a shopcad
model.json; its `render` block supplies materials, views, sun and ground) or
`glb_url`; `state`; `views` (names or inline {name, from, to, lens});
`samples` (default 64); `width`, `height` (1600 x 1000); `device`
(`auto` tries a GPU, falls back to the CPU); `materials`, `sun` overrides.

## Photo step (recipe `photo`)

A photo pass turns a render into a photograph with FLUX.1 Kontext on the
GPU host. The gpu-arbiter runs it when the GPU's language model is idle, so
a pass can wait in its queue for minutes.

1. For every `<view>.png` the render wrote, call the MCP tool
   `request_photo` (server `llm-jobs`) with `job_id`, `image` =
   `<view>.png` and, when the recipe gives one, `prompt`. Queue them all
   before waiting. Each returns a `photo_id` and the output name
   `photo-<view>.png`.
2. Poll: run `sleep 30` with the Bash tool, then call `photo_status` for
   each id not yet finished. Repeat until every one is `done` or `failed`,
   for at most 45 minutes.
3. Deliver the render JSON line and one more line
   `{"photos": {"<view>": "photo-<view>.png" | "failed: <error>"}}`. A
   failed or timed-out photo does not fail the job: the render images still
   count.
