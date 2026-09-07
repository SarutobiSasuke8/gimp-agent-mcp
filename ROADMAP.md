# Roadmap

Work items live as [GitHub issues](https://github.com/SarutobiSasuke8/gimp-agent-mcp/issues). This file is the shape of the thing; the issues are the detail.

## Shipped

**0.2** Detailed work: measurement, before/after/diff renders, selection and masks, text, paths, effect editing, AI cut-outs, recipes, live Windows CI against a real GIMP install. sRGB colour correctness. A thread-free bridge on GLib IO watches, so several clients can hold connections and the plug-in stops crashing under load. Working inside the user's own GIMP window, with a desktop launcher.

**0.3** `gimp_help` so an agent can learn the tool from inside it. `compose`, a layout-manifest recipe for cards and banners. Sprite-sheet packing and slicing with measured bounds. Bundled Claude Code and Codex skills, a plugin marketplace entry, PyPI and the official MCP Registry.

## Next

- [#1](https://github.com/SarutobiSasuke8/gimp-agent-mcp/issues/1) Undo grouping, so one Ctrl+Z reverts a whole agent turn. The biggest quality-of-life gap when the agent works in a window you are also using.
- [#2](https://github.com/SarutobiSasuke8/gimp-agent-mcp/issues/2) Linux live CI with a real GIMP 3, so cross-platform support is a tested claim rather than written code.

## After that

- [#3](https://github.com/SarutobiSasuke8/gimp-agent-mcp/issues/3) Render overlay mode: selection, layer boxes and coordinates drawn on the render, so the agent sees positions instead of computing them.
- [#6](https://github.com/SarutobiSasuke8/gimp-agent-mcp/issues/6) Report the user's active image, layer and selection, so "this layer" works.
- [#4](https://github.com/SarutobiSasuke8/gimp-agent-mcp/issues/4) Brand kits: named colour, font and canvas profiles referenced from a `compose` manifest.
- [#5](https://github.com/SarutobiSasuke8/gimp-agent-mcp/issues/5) Cancellation and progress for long operations.
- [#7](https://github.com/SarutobiSasuke8/gimp-agent-mcp/issues/7) A demo recording of an agent editing a live GIMP window.
- macOS verification. `macos-latest` runners carry no GIMP and the cask install is slow, so this is likely a manual report rather than CI.
- Reorder layer effects; move layers between groups.
- Guided masks: refine a segmentation mask with GEGL feather, shrink and matting in one call.
- More recipes: colour-grade presets, sticker packs against Telegram and WhatsApp specs, social crops from one source.
- Recipe parameters exposed as JSON Schema so clients can render forms.

## Later

- Streamable HTTP transport behind an opt-in flag, still loopback-only by default.
- Script-Fu bridge for the remaining `.scm` procedures with no Python equivalent.
- Optional Windows service or launch agent so the bridge starts with GIMP.
- A write-up on generic runtime introspection versus hand-written tool wrappers.
