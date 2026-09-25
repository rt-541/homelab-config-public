# workshop plugin

A Claude Code plugin for designing
physical builds (cabinets, carts, workbenches, shop layouts, process jigs,
subpanel circuits) and delivering them as shop drawing sets you can take to
the bench and the lumber yard.

| Skill | What it does |
|---|---|
| `build-plan` | Runs the design dialogue one question at a time, applies engineering checks (humidity, heater limits, swing radii, NEC basics, bulk-material fill rules, tilting trays), and writes a standalone HTML drawing set with SVG drawings generated from dimensions, a cut list, a priced shopping list, a build sequence, and a PDF. |
| `shopcad-model` | Builds a headless 3D model from the same numbers with the bundled `shopcad` framework (CadQuery in Docker): an interactive three.js viewer, STEP per assembly, PNG renders for the sheets, a Fusion 360 script with user parameters, and fit checks that fail the export when a dimension stops working. |

## Install

```
claude plugin marketplace add rt-541/homelab-config-public --sparse .claude-plugin plugins
claude plugin install workshop@workshop-skills
```

Requirements: Python 3, Docker with the `cadquery/cadquery` and
`zenika/alpine-chrome` images (pulled on first use) for models, renders and
PDFs.

## Examples

- `skills/build-plan/examples/rock-screen/`: a tilt-tray
  rock screen that cleans river rock into 50 lb sacks. `python3 mk.py`
  writes the nine-sheet drawing set to `out/index.html`; every drawing is
  computed from the constants at the top of the file.
- `skills/shopcad-model/framework/plans/spool_cabinet.py`:
  a filament spool cabinet with glass doors. Install the framework into a
  project and render it:

  ```
  python3 skills/shopcad-model/scripts/new_plan.py --init ~/myplans
  ~/myplans/cad/run.sh spool-cabinet     # -> ~/myplans/public/plans/spool-cabinet/model/
  ```
