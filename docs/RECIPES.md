# Writing a recipe

A recipe is a module in `src/gimp_agent_mcp/recipes/`. It is discovered automatically.

```python
"""One-line docstring."""

DESCRIPTION = "What the recipe does, in one sentence"

PARAMS = {
    "input_path": {"type": "string", "required": True, "description": "Source image"},
    "output_path": {"type": "string", "required": True, "description": "Destination"},
    "strength": {"type": "number", "default": 1.0, "description": "How much"},
}

SOURCE = r'''
import os
image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(params["input_path"]))
layer = image.get_layers()[0]
# ... edit ...
Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, image, Gio.File.new_for_path(params["output_path"]), None)
result = {"output_path": params["output_path"]}
image.delete()
'''
```

Rules:

- Every parameter has a `description` and either a `default` or `required: True`. The unit tests enforce this.
- `SOURCE` runs inside GIMP with `params` already resolved. `Gimp`, `Gegl`, `Gio`, `GLib`, `GObject`, `image_by_id`, `item_by_id` and `make_color` are in scope.
- Assign `result`. It is serialised and returned to the agent.
- Wrap edits in `image.undo_group_start()` / `undo_group_end()` when the image may stay open.
- Delete images you created unless a `keep_open` parameter says otherwise.
- Recipes that take `input_path` and `output_path` work with `gimp_batch_recipe` for free.
- No machine-specific paths, no network, no prompts.

Test it with `gimp_run_recipe` from a client, or add a check to `smoke.py` if it is core enough to gate releases.


## Verified sprite-sheet packing

Call `gimp_run_recipe("sprite_sheet_pack", {"input_paths": ["frames/idle-01.png", "frames/idle-02.png"], "output_path": "out/idle.png", "columns": 4})`.

Input order is animation order; frames must be PNGs with identical canvas dimensions and unique basenames. No rescaling, trimming or alignment correction is applied. The recipe produces `idle.png`, `idle.xcf` (one named raster layer per frame plus transparent canvas), and `idle.json` (full-cell atlas entries with measured alpha bounds). Empty frames remain valid cells. Existing outputs are refused unless `overwrite=true`; inputs cannot be output destinations.

The exported PNG is reopened in GIMP and every cell's 8-bit RGBA pixels are compared with its decoded source. Unused cells must remain transparent. JSON is written only after successful verification. A failed export/verification can leave partial output files; inspect these before explicitly overwriting. Exact comparison may reject colour-profile or precision conversions; normalize inputs to a shared 8-bit sRGB workflow if needed.

The result reports source/sheet bytes, bounds, and foot/centre drift. Drift is a diagnostic, not automatic evidence of a defective animation: floating effects and changing silhouettes can legitimately move. `measuredPivot` is diagnostic metadata rather than a loader origin; choose a stable animation origin in your engine.

For Phaser, load the grid with `this.load.spritesheet('idle', 'out/idle.png', { frameWidth: 64, frameHeight: 64, endFrame: 1 });` (replace dimensions/count with the result). Or load named full-cell frames with `this.load.atlas('idle', 'out/idle.png', 'out/idle.json');`.

Run `python scripts/sprite_sheet_proof.py OUTPUT_DIRECTORY` from the development environment for a real MCP stdio proof: procedural GIMP frames, packing, re-open verification, slicing round-trip, and failure cases. No image-generation service or optional imaging library is required.

Recipe parameter types are validated before execution. Integer parameters reject booleans and fractional/string values; declared minimums are enforced. Nullable defaults remain supported and mutable defaults are copied per invocation. Slice margins now apply on all four sides; partial edge cells are excluded.
