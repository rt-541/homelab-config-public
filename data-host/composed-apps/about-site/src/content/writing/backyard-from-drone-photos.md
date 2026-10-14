---
title: "A backyard, drawn from drone photos, rendered by the homelab"
date: 2026-09-26
dek: "Five revisions of a deck, a stone patio and a fire ring in one day, with every drawing, check and quantity coming from one Python module, and photo-style views from a Blender worker on the NanoClaw fleet plus FLUX Kontext on a shared GPU."
tags: ["build-plan", "cad", "agents", "homelab", "blender"]
---

The brief arrived as a sentence and a folder of eight drone photos: a composite deck with a stair at one corner and another down to a stone patio, a line of evergreens along the back fence, a French drain where the yard floods, and somewhere to grow vegetables. No tape measurements. The deliverable was the same shape as the other plans on this site: a drawing set someone could hand to contractors, a PDF, a 3D model, and a price list where every line is a listing that was actually read.

## Reading the site from the air

Drone photos carry more than pictures. The flight heading in each frame's metadata settled which way the house faces (the camera's own gimbal yaw on this drone is not trustworthy; the flight yaw is), and a known width in frame gave a scale: the house came out about 52 ft across, the yard about 50 ft deep. Everything in revision A is marked as an estimate, and the first sheet lists the six measurements that turn it into revision B.

The photos also carry GPS coordinates. Those never leave the working copy; nothing published here says where the house is.

## One module, many outputs

The plan lives in one Python file. Its `DEFAULTS` hold every number a person might change: lot, house, bay, chimney, deck, stair, patio, fire ring, trees, drain. Everything else derives from them, including the grade, which is a plane falling toward the back fence and toward the corner drain.

From that one module come:

- the 3D model, exported to GLB, STEP and a Fusion 360 script;
- the fifteen SVG drawings on the sheets (site plan, section, framing, elevations, stairs, patio, ring, seat wall, herb bed, AC screen, trees, drain);
- the quantities the bids should match (boards, guard, piers, tons of flagstone, cubic yards of base, wall stone);
- about forty checks that fail the export when a number stops working: stair risers over 7.75 in, a joist cantilever over a quarter of its span, a fire ring too close to the arborvitae, chairs that no longer fit on the stone.

That matters most when the design moves, and it moved a lot.

## Five revisions in a day

Revision A put a garden terrace north of a wide deck, a fire circle to the west and nine staggered Green Giants along the fence. Then the owner looked at it.

- **A2.** The deck shrank to the sliding door, the patio became a 16 ft square of dry-laid buff flagstone, the trees became five American Pillar arborvitae in one row, and the garden went away.
- **A3.** The fire ring moved to the patio's northwest corner, the herb bed became a stone raised bed standing off the brick, and the AC got a screen. The "door" I had drawn a landing for turned out to be a living-room window.
- **A4.** One stair instead of two, the slider drawn as the angled bay it really is, the deck's outer corners cut at 45 degrees, and a Blackstone griddle and a smoker along the east rail.
- **A5.** A stone seat wall around the fire, the sofa set moved onto the patio, a vented skirt under the deck, and the AC screen opened on its west side. The owner asked whether a three-sided solid screen would hurt the condenser. It would: the unit pulls air in through its sides and pushes it out the top, and a box around it feeds it its own exhaust.

Every revision regenerated the model, the sheets, the quantities, the budget and a PDF, and republished the page. A change like "cut the corners" touched the deck outline, the joists, the guards, the fascia, the skirt and the stone walkway around the deck, and none of it was redrawn by hand.

Some of what the checks caught along the way: a fire pit that fit the yard only as a listed portable unit (the published code distance for an open wood fire is 25 ft; the owner set their own distances, and the plan records both), a deck that could not hang on the brick (a ledger may not go on veneer, so it stands on its own two beams), and a patio that stood higher than the lawn on its low side, which the seat wall now holds back.

## Making the model look like a yard

The first renders were honest and ugly: stepped grass tiles, trees stacked like cakes, furniture as boxes. The CAD framework only knew boxes and cylinders, so it learned four more shapes: extruded polygons (irregular flagstones, curved seat walls, stair stringers), a slab with a sloped top (one smooth ground), cones (trees, umbrellas) and a hip roof. The flagstones come from a jittered grid clipped to the patio square and the round apron, so no two stones overlap.

Then photoreal. The first attempt was a one-off Blender install on the machine running the session, which is the wrong place for it. The better place is the NanoClaw fleet, which already runs job workers behind a small job service. So there is now a render tier:

- a caller submits a JSON recipe (the model's URL and the views) to the job service;
- a NanoClaw agent group, `jobs-render`, wakes up with a `blender-render` skill, runs Blender headless, and writes the images to a per-job artifact folder;
- the job service lists those files in the result and serves them to whoever submitted the job.

The plan module carries its own render recipe: which parts are brick, shingle, composite, flagstone, wall stone, grass or foliage, three camera views, the sun (low from the west-northwest, so the north faces are lit) and an endless ground plane that follows the grade. Materials are procedural, tinted by each part's own colour, so no texture files travel with the model.

![The backyard from the north, rendered in Blender by the render tier](/plans/backyard/model/cycles-north.png)

Correct, lit, and still obviously a model. Better materials would only have made it a better model, so the last step hands the render to a tool that makes photographs: FLUX.1 Kontext, an image-editing model that takes a picture plus an instruction ("turn this 3D render into a real photograph; keep every object where it is") and redraws the surfaces while keeping the layout and the camera.

It runs on the render host's Intel B70, which normally holds the fleet's language model (vLLM) and backs Plex. The two cannot share the card's memory, so a small arbiter lends it out. Photo requests queue with it; when vLLM has been idle for a minute and nothing else is on the card, it stops vLLM, starts ComfyUI with Kontext, runs the whole queue, and hands the card back. Requests to the language model during a swap wait at its proxy instead of failing. A photo takes about 55 seconds, the swap back about a minute, and the render worker simply asks for a photo of each view and waits.

![The same view as a photograph](/plans/backyard/model/photo-north.png)

![From the northeast](/plans/backyard/model/photo-ne.png)

![From the west](/plans/backyard/model/photo-west.png)

The deck, the cut corners, the fire ring and seat wall, the screened AC and the five pillars are where the plan puts them. The woods and fields past the fence are the model's invention.

## What did not work

- **The local model could not drive it.** The free tier's qwen3-14b, behind its proxy, failed on the first tool-call turn ("Content block is not a text block"). Plain text jobs work; a job that has to write a file and run a command does not yet. The render worker runs on Sonnet instead, capped at 30 jobs a day, since each job is only three tool calls.
- **Blender cannot reach the GPU.** NanoClaw's container runner has no device passthrough, so the Blender step runs on the CPU (about 35 seconds a view at 128 samples). The photo step gets the GPU only because the arbiter runs outside NanoClaw, on the host.
- **The official Blender download sits behind a bot check.** A university mirror serves the same archive.

## What carries forward

The next physical plan gets photo-style views for the cost of a `RENDER` block in its module and one job with `"photo": true`. The render tier does not know anything about backyards; it takes any GLB and a recipe. And the lesson from the revisions is the same one as on the garage and the spool cabinet: when the drawings, the model, the checks and the shopping list all come from the same numbers, the owner can change their mind five times in a day and the plan keeps up.

The drawing set is at [/plans/backyard/](/plans/backyard/), and the project page at [/projects/backyard](/projects/backyard).
