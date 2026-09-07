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

## Path beyond the current competitor

The comparison target is [maorcc/gimp-mcp](https://github.com/maorcc/gimp-mcp). Its strength is broad, approachable named tools and a continuous narrated demo. Our strength is editable output, runtime discovery, measured verification, recovery behaviour and repeatable asset jobs. The roadmap closes the everyday-use gaps while preserving those strengths. Tool count alone is not the target.

### Milestone 1: visual precision and shared context

- [Render overlays](https://github.com/SarutobiSasuke8/gimp-agent-mcp/issues/3): coordinate grid, layer bounds, selection bounds and labelled points on preview copies. No source pixels change.
- [Focused document context](https://github.com/SarutobiSasuke8/gimp-agent-mcp/issues/6): pursue a verified display API route. Keep explicit image selection as the safe fallback when GIMP cannot report focus reliably.
- [Continuous agent demo](https://github.com/SarutobiSasuke8/gimp-agent-mcp/issues/7): show prompt, visible edits, inspection and one-step undo in a single capture.

Exit evidence: overlay geometry agrees with measured bounds, source pixels compare unchanged, and the visible workflow is reproducible.

### Milestone 2: everyday editing ergonomics

- [Everyday editing tools](https://github.com/SarutobiSasuke8/gimp-agent-mcp/issues/8): add a deliberately small `gimp_adjust` surface for the high-frequency operations that are awkward through PDB discovery: brightness/contrast, hue/saturation, curves, desaturate, invert, blur, sharpen, noise and pixelate.
- In the same issue, add `gimp_canvas` for scale, crop, canvas resize, rotate, flip, merge-visible and flatten.
- In the same issue, add `gimp_draw` for fills and simple line/rectangle/ellipse drawing, using the same colour and coordinate conventions throughout.
- Keep generic PDB/GEGL access available for the long tail. Every convenience action must map to a described runtime operation and carry a live regression check.

Exit evidence: a new user can complete the competitor README's common examples without discovering procedure names or writing Python.

### Milestone 3: reusable asset pipelines

- [Brand kits](https://github.com/SarutobiSasuke8/gimp-agent-mcp/issues/4): named colours, fonts, assets and canvases for compose, with validation before rendering.
- [Broader asset workflows](https://github.com/SarutobiSasuke8/gimp-agent-mcp/issues/9): sprite padding, mixed-size packing and direct open-layer inputs. Preserve pixel verification and layered XCF output.
- In the same issue, add social crop/export profiles with focus-aware crops rather than a list of fixed dimensions alone.
- Investigate and validate a warp/liquify workflow separately before claiming parity.

Exit evidence: token and inline manifests render identically, atlas coordinates and padding verify, and every preset produces measured dimensions.

### Milestone 4: long jobs and platform confidence

- [Cancellation and progress](https://github.com/SarutobiSasuke8/gimp-agent-mcp/issues/5): staged job progress first, then cancellation only for operations GIMP can safely interrupt.
- [macOS installation and live GIMP validation](https://github.com/SarutobiSasuke8/gimp-agent-mcp/issues/10): Apple Silicon and Intel workflows are implemented; support claims wait for both live runs to pass.
- Fresh-install reports from users, plus upgrade checks for the plug-in/server version mismatch path.

Exit evidence: long jobs expose honest state, cancellation leaves a consistent document, and the supported-platform table is backed by repeatable runs.

### Decision rules

- Prioritise fewer, reliable operations over matching a headline tool count.
- Preserve the loopback/token boundary and thread-free GIMP plug-in.
- Keep source documents editable; diagnostics operate on duplicates.
- Add public claims only after a real-GIMP proof exists.
- A milestone may ship independently once its exit evidence passes.
