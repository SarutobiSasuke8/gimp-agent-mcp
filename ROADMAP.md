# Roadmap

## Released through 0.3.0

Live image/region previews, pixel measurements, before/after/diff renders, selections, masks, layers, text, paths, editable effects, optional AI cut-outs, eight recipes, bundled Claude Code/Codex skills, PyPI and MCP Registry distribution. Real Windows GIMP CI.

## 0.4.0

- Grouped edits: a bounded supported batch becomes one Ctrl+Z step. Partial failures are reported and the group always closes. No transaction remains open between calls.
- Explicit document context, selected-layer control and GUI presentation. Multiple documents require an image ID; focus is not guessed.
- Numeric-array PDB arguments for curves and brush strokes, with measured runtime tests.
- Nested-layer and hidden-layer comparison fixes; explicit snapshot release and a retention limit.
- No silent replay after an uncertain network outcome.
- Verified equal-canvas sprite packing, XCF and atlas output, and stricter recipe validation.
- Real Linux GIMP CI, release gates for both platforms, and a launch-environment fix for uv/Python GI interference.
- Demo, examples and release metadata consistency.

## Next useful work

1. [Render overlays](https://github.com/SarutobiSasuke8/gimp-agent-mcp/issues/3): coordinates, layer boxes and selection bounds, without changing source artwork.
2. [Cancellation and progress](https://github.com/SarutobiSasuke8/gimp-agent-mcp/issues/5): cancellable stages for batch jobs; distinguish this from interrupting an in-flight GIMP filter.
3. [Brand kits](https://github.com/SarutobiSasuke8/gimp-agent-mcp/issues/4): named fonts, colours and layout defaults for compose, with missing-token validation.
4. Broader sprite inputs and padding; focus-aware social crops; a separately validated warp workflow.
5. macOS validation and fresh-install reports from users.

These are follow-ups, not claims in the launch copy. Keep runtime checks and editable output ahead of adding convenience wrappers for their own sake. Work items remain in [GitHub issues](https://github.com/SarutobiSasuke8/gimp-agent-mcp/issues).
