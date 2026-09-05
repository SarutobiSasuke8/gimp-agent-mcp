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
