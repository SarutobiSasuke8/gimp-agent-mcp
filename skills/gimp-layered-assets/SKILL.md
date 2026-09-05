---
name: gimp-layered-assets
description: Assemble generated or supplied raster components into named editable layers in GIMP through the gimp MCP server, preserve an XCF master, and export production assets. Use for layered artwork, compositing, transparent cutouts, product and marketing images, UI art, banners, key art, and any image-generation-to-GIMP workflow where parts must stay independently editable. Do not use for preview-only image generation that never needs editing.
---

# Layered assets

The goal is a useful editable master, not a flattened picture that happens to be correct once.

## Preconditions

Call `gimp_status` before editing. Prefer a bridge the user already has running in their own GIMP
window over launching a second instance; `gimp_status` reports `mode: "gui"` when you are in their
window, and they can then edit alongside you.

Everything is addressed by integer id. `gimp_open` and `gimp_new_image` return an image id and its
layers; `gimp_image_info(image_id)` gives the full layer tree. **Never guess an id, and never touch
an unrelated open image** — the user may have their own work loaded.

This server is trusted local automation with file access and a Python escape hatch. Keep every
action inside the asset scope you were asked for.

## Decide the components before generating anything

Identify which parts must remain independently editable. The usual split is background, subject,
props, shadows, highlights, effects, text, and graphic shapes.

- Generate independently editable components as **separate files**, transparent PNG for isolated
  subjects and props.
- Keep typography as GIMP text layers (`gimp_text`) and simple geometry as paths (`gimp_path`).
- Keep shadows, glows and colour adjustments separate, or append them as non-destructive GEGL layer
  effects with `gimp_apply_filter(mode="append")`, editable afterwards via `gimp_layer_effect`.

**A generated PNG or WebP is a flattened raster.** It does not contain semantic layers for subject,
background, lighting or text. Never imply otherwise. Segmentation and masks can extract visible
regions, but occluded pixels cannot be recovered, so decomposing a flat image is always a partial
recovery and should be described as one.

For project-bound work, copy final source components into the project before assembling. Do not
leave a deliverable depending on files that only exist in a generator's private cache.

## Assembly

Take the smallest reliable route:

1. **New composition:** the `compose` recipe with a manifest and `keep_open: true`. It creates
   separate image, text, rectangle and ellipse layers in one call.
2. **Existing document:** import files as layers through the file-load-layer PDB procedure, after
   `gimp_pdb_search` then `gimp_pdb_describe` confirm its current arguments. Do not hardcode a
   signature; the describe step exists because GIMP's API moves.
3. **Cutouts:** `gimp_remove_background(mode="mask")` writes the result as an editable layer mask.
   Prefer that over baking alpha, unless the user asked for baked alpha.
4. **Name every meaningful layer by role.** Imported generated art is a raster layer; do not
   describe it as vector or natively editable.
5. Save an XCF working master, then export delivery formats separately with `gimp_export`. Do not
   overwrite an existing asset unless asked.

## Look and measure after each material step

`gimp_render(image_id)` after each meaningful edit, with `region` to zoom into detail. A render
answers "does this look right"; it does not answer "is this correct".

For correctness use `gimp_measure`: `bbox` for alpha bounds and placement, `color` for an exact
pixel, `histogram` and `dominant` for tone and palette checks. Before a risky edit take a
`gimp_snapshot`, then `gimp_render_compare` shows before, after and a pixel diff side by side.

## Completion evidence

Finish with the XCF master path, every exported path, the layer list and which layers remain
editable, the provenance of each generated component, the validation you actually performed
(dimensions, alpha, bounds, anchors where relevant, a final render), and anything still needing
human or in-engine review.

For game art specifically, read [references/game-assets.md](references/game-assets.md) before
generating or assembling, and use the `gimp-sprite-sheets` skill for anything that ends up as an
animation strip or atlas.
