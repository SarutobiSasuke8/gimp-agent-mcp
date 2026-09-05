# CLAUDE.md

Read `AGENTS.md` first; it is the contract for this repository.

## Layout

- `src/gimp_agent_mcp/server.py`: FastMCP tools, prompts, resources. Thin; delegates to the bridge.
- `src/gimp_agent_mcp/bridge_client.py`: TCP client and GIMP process launcher.
- `src/gimp_agent_mcp/paths.py`: where GIMP and its config directory live per platform.
- `src/gimp_agent_mcp/plugin/gimp-agent-bridge.py`: the GIMP 3 plug-in. All libgimp/GEGL work is here.
- `src/gimp_agent_mcp/plugin/agent_bridge_core.py`: pure helpers shared by both sides.
- `src/gimp_agent_mcp/recipes/`: multi-step jobs as Python source executed inside GIMP.
- `src/gimp_agent_mcp/smoke.py`: the live end-to-end test.

## Commands

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest                         # unit tests, no GIMP needed
uv run gimp-agent-mcp install-plugin  # after editing the plug-in
uv run gimp-agent-mcp smoke           # live test, needs GIMP 3
GIMP_AGENT_LIVE=1 uv run pytest tests/test_live.py
```

After changing the plug-in you must reinstall it and restart any running bridge; GIMP loads plug-in code at start.

## Testing alongside a live session

The bridge is one port and one token file. If a user session is running, isolate your test run:

```bash
GIMP_AGENT_PORT=9911 GIMP_AGENT_BRIDGE_FILE="$TEMP/gimp-agent-test.json" uv run gimp-agent-mcp smoke
```

Both the launcher (which passes its environment to GIMP) and the plug-in honour these variables.

## GIMP 3.2 API notes

- `Gimp.get_images()`, `image.get_layers()`, `image.get_selected_layers()`; no `gimpfu`.
- Colours are `Gegl.Color`. `set_rgba`/`get_rgba` are *linear* RGB; agents mean sRGB. Build from a hex string (`Gegl.Color.new("#rrggbbaa")`, parsed as sRGB) and convert `get_rgba` through `linear_to_srgb` before showing it. The smoke test asserts a `#2b2f5a` fill reads back as `#2b2f5a`.
- `layer.fill(FOREGROUND)` ignores the colour's alpha; use `FillType.TRANSPARENT` to clear a layer.
- Filters: `Gimp.DrawableFilter.new(drawable, "gegl:op", name)`, set properties on `get_config()`, then `drawable.merge_filter(f)` (destructive) or `drawable.append_filter(f)` (layer effect).
- PDB: `Gimp.get_pdb().lookup_procedure(name)`, `proc.create_config()`, `config.set_property(...)`, `proc.run(config)`; index 0 of the returned `ValueArray` is the status.
- Call `Gimp.displays_flush()` after edits so the GUI repaints.
- The per-user config directory is versioned (`3.0`, `3.2`, ...); plug-ins go in `<config>/plug-ins/<name>/<name>.py`.
- Windows plug-ins need the `#!/usr/bin/env python3` shebang so GIMP maps them to its bundled interpreter.
- Headless: `gimp-console -i --batch-interpreter=python-fu-eval -b "<python>"`; the batch code already has `Gimp` in scope.
- GIMP's Colors > Invert is `gegl:invert-gamma`; there is no `gegl:invert`.
- `Gimp.DrawableFilter.new` returns NULL for GEGL source/render ops (`gegl:color`, `gegl:linear-gradient`, ...). Fill with `edit_fill` / `edit_gradient_fill` instead. `gegl:plasma` renders only inside an explicit x/y/width/height.
- `Gimp.Path` is an `Item` but not a `Drawable`: no offsets, width or height. Guard `_item_info` accordingly.
- Enum classes are created lazily by PyGObject; resolve through the namespace, then `gi._gi.enum_add(gtype)` for GEGL's dynamic enums.
- Read pixels with `drawable.get_buffer().get(Gegl.Rectangle, scale, "R'G'B'A u8", Gegl.AbyssPolicy.CLAMP)`; write masks through `get_shadow_buffer` + `merge_shadow` + `update`.
- Export procedures are `file-<ext>-export`; JPEG quality is 0..1, WebP quality is 0..100, PNG has `compression`.
- If the plug-in process dies mid-session GIMP logs `gimp_wire_read(): unexpected EOF` and every later call fails to connect; check `gimp-agent-launch.log` in the config dir. Both instances append to that log, so sections interleave when two GIMPs run.
- Never add threads to the plug-in. The 0.1 to 0.2.2 accept-thread design crashed intermittently; GLib IO watches on the main loop fixed it.
