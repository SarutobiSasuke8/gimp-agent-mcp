# Roadmap

## 0.1 (now)

Prove the generic surface works end to end on Windows with GIMP 3.2, and that an agent can complete a real job (the Telegram sticker recipe) from a fresh clone.

## 0.2

- Verify macOS and Linux (native, Flatpak, Snap) paths with real runs; fix `find_gimp` and plug-in install for each.
- Non-destructive editing: edit, reorder, toggle and remove layer effects, not only list them.
- Text layers and paths as first-class tools; both are awkward through raw PDB calls.
- Selection helpers (by colour, by alpha, grow/shrink/feather) as one tool with a `mode` argument.
- `gimp_render` diff mode: return a side-by-side of before/after for the last operation.
- Publish to PyPI and the MCP Registry; `uvx gimp-agent-mcp` as the install path.

## 0.3

- More recipes: background removal with review, batch watermark, sprite-sheet slice and pack, favicon and app-icon sets, web image optimisation with size budgets.
- Recipe parameters exposed as JSON Schema so clients can render forms.
- Streamable HTTP transport behind an opt-in flag, still loopback-only by default.
- Optional Windows service / launch agent so the bridge starts with GIMP.

## Later

- Script-Fu bridge for the remaining `.scm` procedures that have no Python equivalent.
- A short recorded demo and a write-up on the generic-introspection approach versus hand-written tool wrappers.
