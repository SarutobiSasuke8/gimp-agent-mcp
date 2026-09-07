# Validation and known boundaries

## Reproduce

Run `uv sync --extra dev`, install the bridge and restart GIMP. Then:

```bash
uv run ruff check .
uv run pytest
uv run gimp-agent-mcp smoke
uv run python scripts/capability_proof.py ./proof-output
```

Set both `GIMP3_DIRECTORY` and `GIMP_AGENT_CONFIG_DIR` to the same disposable profile before installation when testing alongside a user's GIMP. Give that profile its own `GIMP_AGENT_BRIDGE_FILE`. The Linux CI does this automatically. Use a fresh output directory for sprite proofs, which refuse overwrites by default.

The normal smoke covers images, discovery, filters, colour/bounds measurements, snapshots, masks, layers, text, paths, exports and recipes. The capability proof writes `report.json` with the actual GIMP version, each result, timing and measured values. It also renders diagnostic grid/layer/selection/point overlays, reopens the PNG, measures the point marker and confirms the source pixel and layer count did not change. Linux CI uploads this report and the launch log. The optional segmentation check downloads a model and runs only with `smoke --segmentation`.

## GUI undo proof

`scripts/gui_demo.py create OUT_DIR` creates the example via real MCP stdio. `edit` changes three text layers through `gimp_edit_batch`, exports a PNG and saves an XCF. Press Ctrl+Z in that document; `verify-undo` reads the text back through MCP and asserts that all three edits were reverted. Ctrl+Y restores the batch. Run the script from the repository virtualenv with the intended bridge environment.

The README GIF and MP4 are a labelled sequence of captured GIMP window states, with pauses shortened. They are not an uncut recording of model deliberation. Their assets are original procedural GIMP text and shapes.

## Comparison scope

Both this project and maorcc/gimp-mcp support visual feedback and visible editing. Our dedicated operations and generic PDB/GEGL routes overlap many of that project's tools, but a tool count is not a quality measure or a proof of parameter parity.

Proven targeted equivalents include PDB curves with numeric arrays, linear gradients, paintbrush/pencil strokes and image rotation. Tested additional behaviours include grouped edits with partial-failure reporting, cross-document rejection, hidden-parent layer isolation and hidden-top-layer comparison compositing.

Not claimed: complete warp-vector equivalence, named social-platform export presets, open-layer sprite packing, sprite padding, GUI-focused-image detection, programmatic undo/redo, macOS validation, or the correctness of every installed third-party PDB procedure. No competitor runtime results are inferred from their README.
