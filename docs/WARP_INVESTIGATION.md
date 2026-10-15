# Warp and liquify: investigation note

Status: **unsupported**. This note records what an installed GIMP exposes, so a later change can start from facts. It adds no tool, recipe or parameter, and it does not change the answer in [Asset workflows](ASSET_WORKFLOWS.md#warp).

## What was checked

Probed on 2026-10-15 against GIMP 3.2.4 on Windows (headless, `gimp-console-3.2.exe`, GEGL as bundled), through the bridge's own `filter_search`, `filter_describe`, `pdb_search` and `exec` ops. Nothing was applied to a user image; the only image was a 64 × 64 scratch document that was deleted.

| Query | What the installed GIMP returned |
|---|---|
| `gimp_filter_search("warp")` | `gegl:warp` (Warp, category transform, "Compute a relative displacement mapping from a stroke") and `gegl:color-warp` (a colour mapping, not a geometric warp) |
| `gimp_filter_search("liquify")`, `("iwarp")` | nothing |
| `gimp_pdb_search("warp")` | `plug-in-warp` ("Twist or smear image in many different ways"), the classic displacement-map Warp plug-in |
| Related GEGL distortions | `gegl:spherize`, `gegl:ripple`, `gegl:waves`, `gegl:displace`, `gegl:apply-lens`, `gegl:lens-distortion` |

`gimp_filter_describe("gegl:warp")` lists `strength` (0..100, default 50), `size` (1..10000, default 40), `hardness` (0..1), `spacing` (0..100), `stroke` (a `GeglPath`, default none) and `behavior` (`move`, `grow`, `shrink`, `swirl-cw`, `swirl-ccw`, `erase`, `smooth`).

`Gimp.DrawableFilter.new(layer, "gegl:warp", "warp")` returned NULL ("constructor returned NULL"). GIMP does not offer `gegl:warp` as a drawable filter, so `gimp_apply_filter` cannot use it, in the same way it refuses source and render ops.

## What this means

- GIMP's interactive Warp Transform tool (the liquify equivalent) drives `gegl:warp` internally from brush strokes. That path is not reachable as a filter from a plug-in in 3.2.4, so there is no direct "apply this liquify stroke" call to wrap.
- `plug-in-warp` is a different effect: it displaces pixels along the gradient of a displacement map over a number of iterations. It is reachable through `gimp_pdb_call`, but it is not stroke-based liquify, and its arguments (maps, iterations, step size) would need their own validated recipe.
- The fixed distortions (`gegl:spherize`, `gegl:ripple`, `gegl:waves`, `gegl:displace`) are ordinary drawable filters and already work through `gimp_apply_filter`. They are useful effects, not a warp workflow.

## What a supported workflow would need

1. A route that actually runs on the installed GIMP. Candidates, in order of promise: building a small GEGL graph inside `exec` (`gegl:warp` feeding `gegl:map-relative`, the pair the Warp Transform tool uses) and writing the result through the drawable's shadow buffer; or a recipe around `plug-in-warp` with a generated displacement map.
2. A reproducible before/after measurement on that route: `gimp_snapshot`, the operation names that describe returned, a fixed stroke or map, and `gimp_render_compare` plus `gimp_measure` showing the expected displacement (for example the centroid of a marker moving by a known distance) within a stated tolerance.
3. The same measurement on Windows, Linux and macOS in the live CI jobs before the docs say "supported".

Until all three exist, the answer to "warp or liquify this" stays: unsupported, and no parity claim.
