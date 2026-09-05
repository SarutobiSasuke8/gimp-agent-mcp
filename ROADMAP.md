# Roadmap

## 0.2 (shipped 2026-09-05)

Detailed work: measurement, before/after/diff renders, selection and masks, text, paths, effect editing, AI cut-outs, seven recipes, live Windows CI with a real GIMP install.

## 0.3

- Verify macOS and Linux (native, Flatpak, Snap) with real runs; fix `find_gimp` and plug-in install for each.
- Publish to PyPI through trusted publishing and list in the MCP Registry; `uvx gimp-agent-mcp` as the install path.
- Reorder layer effects and move layers between groups.
- Guided masks: refine a segmentation mask with GEGL (feather, shrink, matting) in one call.
- `gimp_render` overlay mode: draw selection bounds, layer boxes and measurement points onto the render so the agent can see coordinates.
- Recipes: colour-grade presets, sticker pack (batch + Telegram/WhatsApp specs), social crops (square, story, banner) from one source.
- Recipe parameters exposed as JSON Schema so clients can render forms.

## Later

- Streamable HTTP transport behind an opt-in flag, still loopback-only by default.
- Script-Fu bridge for the remaining `.scm` procedures with no Python equivalent.
- Optional Windows service / launch agent so the bridge starts with GIMP.
- A short recorded demo and a write-up on the generic-introspection approach versus hand-written tool wrappers.
