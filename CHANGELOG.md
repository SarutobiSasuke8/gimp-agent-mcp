# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.1] - 2026-09-05

### Fixed

- Colours were interpreted as linear RGB, so every `#rrggbb` an agent passed rendered lighter than asked (`#2b2f5a` came out `#7277a0`). Colours now go through GEGL's sRGB string parser and reported colours are converted back to sRGB. The smoke test asserts an exact round-trip.
- `gimp_apply_filter` now explains that GEGL source/render operations (`gegl:color`, `gegl:linear-gradient`) are not drawable filters and points at fill/gradient procedures, instead of "constructor returned NULL".
- `gimp_launch` kills a GIMP that started without a bridge and retries once, instead of leaving an orphan on the port.

### Added

- `docs/banner.png`, built through the bridge itself.

## [0.2.0] - 2026-09-05

The detailed-work release: measurement, comparison renders, selection and masks, text, paths, effect editing, AI cut-outs and a recipe library. 32 tools, 7 recipes, 22 live checks including the AI cut-out.

### Added

- `gimp_measure`: colour at a point, bounding box of visible pixels, per-channel histogram, dominant colours.
- `gimp_snapshot` and `gimp_render_compare`: before / after / pixel-diff renders.
- `gimp_select`: rect, ellipse, by colour, by alpha, from item, all/none/invert, grow/shrink/feather/border, bounds.
- `gimp_layer_mask` (add from selection/alpha/white/black/copy, apply, remove, enable/disable, show/hide) and raw mask pixel writes via the bridge.
- `gimp_layer`: new, set, move, reorder, duplicate, merge_down, delete, resize_to_image, scale, add_alpha, crop_to_content.
- `gimp_layer_effect`: edit params, opacity, blend mode and visibility of non-destructive effects, or delete them.
- `gimp_text` and `gimp_list_fonts`: create and edit text layers with font, size, colour, justification, spacing and fixed boxes.
- `gimp_path`: create line/bezier paths, select, stroke, fill, delete.
- `gimp_remove_background`: rembg-based subject segmentation into an editable layer mask or baked alpha. Optional `segmentation` extra.
- `gimp_export` gained `options` passed to the format's export procedure (JPEG quality, WebP quality/lossless, PNG compression).
- Recipes: `web_optimise`, `icon_set`, `watermark`, `contact_sheet`, `sprite_sheet_slice`.
- `export_with` helper available to recipes and `gimp_run_python`.
- Live Windows CI: installs GIMP 3.2.4 on a runner and runs the smoke test on every push.
- Release workflow for PyPI trusted publishing on `v*` tags; `server.json` for the MCP Registry.

### Changed

- Enum coercion resolves lazily-created and dynamically registered GEnum types (PyGObject + GEGL).
- Tool failures surface as `ToolError`; bridge tracebacks are attached only for unexpected exception types.
- Headless sessions quit GIMP through the `gimp-quit` PDB procedure after the bridge returns.

### Fixed

- `Image.set_name`, `Gimp.display_present` and `Gimp.Selection.bounds` arity mismatches against GIMP 3.2.
- GUI-mode `gimp_shutdown(quit_gimp=True)` left GIMP running.

## [0.1.0] - 2026-09-05

First release.

### Added

- GIMP 3 bridge plug-in: loopback TCP, token-checked, GLib main-thread dispatch, persistent Python namespace.
- MCP server with 21 tools: session, images, render, PDB search/describe/call, GEGL filter search/describe/apply, `run_python`, recipes.
- Runtime introspection of PDB arguments and GEGL properties, with JSON coercion for images, items, item arrays, colours, files, enums and scalars.
- Recipes: `telegram_sticker`, `fit_and_export`.
- CLI: `serve`, `install-plugin`, `doctor`, `launch`, `smoke`.
- Live smoke test, GIMP-free unit tests, CI on Ubuntu and Windows.
