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

## GIMP 3.2 API notes

- `Gimp.get_images()`, `image.get_layers()`, `image.get_selected_layers()`; no `gimpfu`.
- Colours are `Gegl.Color`; build with `Gegl.Color.new("black")` then `set_rgba(r, g, b, a)` in 0..1.
- Filters: `Gimp.DrawableFilter.new(drawable, "gegl:op", name)`, set properties on `get_config()`, then `drawable.merge_filter(f)` (destructive) or `drawable.append_filter(f)` (layer effect).
- PDB: `Gimp.get_pdb().lookup_procedure(name)`, `proc.create_config()`, `config.set_property(...)`, `proc.run(config)`; index 0 of the returned `ValueArray` is the status.
- Call `Gimp.displays_flush()` after edits so the GUI repaints.
- The per-user config directory is versioned (`3.0`, `3.2`, ...); plug-ins go in `<config>/plug-ins/<name>/<name>.py`.
- Windows plug-ins need the `#!/usr/bin/env python3` shebang so GIMP maps them to its bundled interpreter.
- Headless: `gimp-console -i --batch-interpreter=python-fu-eval -b "<python>"`; the batch code already has `Gimp` in scope.
