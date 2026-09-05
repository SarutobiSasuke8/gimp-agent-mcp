"""In-band documentation for agents. Tools are always visible to a client; prompts and resources often are not."""

from __future__ import annotations

TOPICS: dict[str, str] = {}

TOPICS["start"] = """\
HOW TO WORK WITH GIMP THROUGH THIS SERVER

1. gimp_status. If not connected: gimp_launch(mode="gui") to see a window, mode="headless" for batch jobs.
2. Everything is addressed by integer ids. gimp_open / gimp_new_image return an image id and its layers;
   gimp_image_info(image_id) gives the full layer tree with item ids. Never guess ids.
3. Edit, then LOOK: gimp_render(image_id) after each meaningful step. Use region={x,y,width,height} to zoom.
4. Edit, then MEASURE: gimp_measure(kind="bbox"|"color"|"histogram"|"dominant") answers questions a render cannot.
5. Before a risky edit, gimp_snapshot(image_id); afterwards gimp_render_compare(image_id, snapshot_id) shows
   before | after | diff.
6. Prefer a recipe when one exists (gimp_list_recipes): stickers, icon sets, web optimisation, watermark,
   contact sheet, sprite slicing, compose-from-manifest. gimp_batch_recipe runs one over a folder.
7. Filters: gimp_filter_search -> gimp_filter_describe -> gimp_apply_filter. Anything else: gimp_pdb_search ->
   gimp_pdb_describe -> gimp_pdb_call. gimp_run_python for multi-step logic.
8. Export with gimp_export(image_id, path, options). Extension picks the format. Save working files as .xcf.
9. Errors tell you what is valid: unknown argument -> valid list; unknown enum -> choices; refused op -> alternative.

Other help topics: filters, colours, text, masks, paths, layers, measure, recipes, compose, errors.
"""

TOPICS["filters"] = """\
GEGL FILTERS (gimp_apply_filter(layer_id, op, params, mode))

mode="merge" bakes the result into pixels. mode="append" adds a non-destructive layer effect you can edit later
with gimp_layer_effects / gimp_layer_effect. Property names use dashes; underscores are accepted.

Most useful ops and their key properties (check gimp_filter_describe for ranges):
  gegl:gaussian-blur      std-dev-x, std-dev-y (px)
  gegl:dropshadow         x, y, radius (blur), grow-radius (outline!), color, opacity
                          -> a white outline: x=0, y=0, radius=0, grow-radius=8, color="white", opacity=1
  gegl:unsharp-mask       std-dev, scale, threshold
  gegl:brightness-contrast brightness, contrast (-1..1)
  gegl:hue-chroma         hue (degrees), chroma, lightness
  gegl:levels             in-low, in-high, gamma, out-low, out-high (0..1)
  gegl:color-temperature  original-temperature, intended-temperature (Kelvin)
  gegl:saturation         scale (0 = greyscale, 1 = unchanged)
  gegl:desaturate         mode
  gegl:invert-gamma       (Colors > Invert; there is no gegl:invert)
  gegl:threshold          value
  gegl:pixelize           size-x, size-y
  gegl:vignette           color, radius, softness
  gegl:noise-rgb          red, green, blue, gaussian, independent
  gegl:noise-reduction    iterations
  gegl:cartoon            mask-radius, pct-black
  gegl:emboss             azimuth, elevation, depth
  gegl:long-shadow        style, angle, length, color
  gegl:opacity            value
  gegl:grid               x, y, line-width, line-height, line-color

Not filters (GIMP refuses them as layer effects): gegl:color, gegl:linear-gradient and other source/render ops.
Fill or draw instead: gimp_layer(action="new", fill="#hex"), gimp_select + gimp_pdb_call("gimp-drawable-edit-fill"),
or gimp_pdb_call("gimp-drawable-edit-gradient-fill"). gegl:plasma renders only inside an explicit x/y/width/height.
"""

TOPICS["colours"] = """\
COLOURS

Pass colours as "#rrggbb", "#rrggbbaa", "white", "rgb(255,0,0)", "rgba(0,0,255,0.5)" or [r,g,b,a].
They are sRGB, and what you ask for is what lands in the pixels: a "#2b2f5a" fill measures back as #2b2f5a.
Reported colours (gimp_measure, filter defaults) are sRGB hex too.

Fill types for gimp_new_image / gimp_layer(action="new"): "transparent", "white", "black", "foreground",
"background", or any colour. A layer's fill ignores alpha; use "transparent" to clear.
"""

TOPICS["text"] = """\
TEXT

gimp_list_fonts(filter="Bahnschrift|Segoe UI") to confirm names, then
gimp_text(image_id, text, font="Bahnschrift Bold", size=64, color="#ffffff", x=40, y=40, justify="left").
Edit later with gimp_text(layer_id=..., text=..., size=..., color=...). Text layers stay editable after export
to .xcf. Effects on text: gimp_apply_filter(layer_id, "gegl:dropshadow", {...}, mode="append").
Measure the rendered box with gimp_measure(kind="bbox", layer_id=text_layer_id) to keep text inside the canvas.
Letter spacing and line spacing are in px. box_width/box_height make a fixed wrapping box.
"""

TOPICS["masks"] = """\
SELECTIONS AND MASKS

gimp_select(image_id, mode=..., op="replace"|"add"|"subtract"|"intersect"):
  rect / ellipse (x, y, width, height); color (color, threshold 0..1, layer_id); alpha (layer_id: the layer's
  opaque pixels); item (item_id: path or channel); all / none / invert; grow / shrink / feather / border (amount);
  bounds (report only). Returns the selection bounds.

Masks: gimp_layer_mask(layer_id, action="add", type="selection"|"alpha"|"white"|"black"|"copy").
  "apply" bakes the mask in, "remove" discards it, "enable"/"disable" toggles, "show" previews it.

AI cut-out: gimp_remove_background(layer_id, mode="mask") writes a segmentation mask you can refine with
gimp_select(mode="alpha") + shrink/feather + gimp_layer_mask; mode="apply" bakes it. Needs the optional
segmentation extra; the error says so if it is missing.
"""

TOPICS["paths"] = """\
PATHS (vector shapes)

gimp_path(action="create", image_id, name, strokes=[{"type": "line", "points": [[x,y],...], "closed": true}])
Bezier: points after the first come in triples control1, control2, anchor.
Then: gimp_path(action="fill", path_id, layer_id, color="#hex") or action="stroke" with width, or action="select"
to turn it into a selection. Rounded rectangle: gimp_pdb_call("gimp-image-select-round-rectangle",
{"image": id, "operation": "replace", "x":.., "y":.., "width":.., "height":.., "corner-radius-x": 24,
"corner-radius-y": 24}) then fill via gimp_pdb_call("gimp-drawable-edit-fill", {"drawable": layer_id,
"fill-type": "foreground"}) after gimp_pdb_call("gimp-context-set-foreground", {"foreground": "#hex"}).
"""

TOPICS["layers"] = """\
LAYERS

gimp_layer(action=...):
  new (image_id, name, width, height, fill, x, y, position, parent_id)
  set (layer_id; name, visible, opacity 0..100, mode e.g. "multiply"/"screen"/"overlay", x, y, lock)
  move (dx, dy) | reorder (position, parent_id) | duplicate | merge_down | delete
  resize_to_image | scale (width, height) | add_alpha | crop_to_content
Position 0 is the top of the stack. gimp_image_info shows the tree; groups list their children.
Non-destructive effects: gimp_layer_effects(layer_id) lists them; gimp_layer_effect(filter_id, action="set",
params=..., opacity=..., visible=...) edits; action="delete" removes.
"""

TOPICS["measure"] = """\
MEASURING

gimp_measure(kind, image_id or layer_id, ...):
  color     x, y (image coordinates) -> rgba + hex at that pixel
  bbox      -> x, y, width, height of non-transparent pixels (threshold to ignore faint alpha); empty=true if none
  histogram channels=["value","red","green","blue","alpha"] -> mean, std_dev, median, pixels, percentile
  dominant  k -> top colours with share
Use bbox to check text fits, to crop to content, or to centre things: x_centre = bbox.x + bbox.width/2.
gimp_render(region={...}) zooms; gimp_render_compare shows before/after/diff after a gimp_snapshot.
"""

TOPICS["recipes"] = """\
RECIPES (gimp_list_recipes for parameters; gimp_run_recipe(name, params); gimp_batch_recipe(name, glob, out_dir))

telegram_sticker    input_path, output_path; crops padding, fits 470px into 512x512, white stroke, soft shadow
web_optimise        input_path, output_path (.webp/.jpg/.png), max_edge, budget_kb, quality
icon_set            input_path, output_dir, sizes=[16,32,...,512], prefix, background
watermark           input_path, output_path, text or watermark_path, position, opacity, scale
contact_sheet       input_dir, output_path, columns, thumb, labels
sprite_sheet_slice  input_path, output_dir, tile_width, tile_height, margin, spacing
fit_and_export      input_path, output_path, max_edge
compose             manifest (dict) or manifest_path, output_path: build a card/banner from components (see compose)
"""

TOPICS["compose"] = """\
COMPOSE: build a card or banner from a layout manifest

gimp_run_recipe("compose", {"output_path": "out/card.png", "manifest": {
  "width": 1200, "height": 675, "background": "#0f1117",
  "items": [
    {"type": "image", "path": "brand/logo.png", "x": 40, "y": 40, "width": 160, "fit": "contain"},
    {"type": "rect", "x": 0, "y": 560, "width": 1200, "height": 115, "color": "#1f3a8a", "radius": 0, "opacity": 60},
    {"type": "text", "text": "Headline", "font": "Bahnschrift Bold", "size": 72, "color": "#ffffff", "x": 40, "y": 240},
    {"type": "text", "text": "Sub-line", "font": "Segoe UI Semibold", "size": 30, "color": "#b3bccc", "x": 42, "y": 330},
    {"type": "rect", "x": 40, "y": 590, "width": 420, "height": 56, "color": "#ffffff", "radius": 28,
     "effects": [{"op": "gegl:dropshadow", "params": {"x": 0, "y": 4, "radius": 8, "opacity": 0.4}}]},
    {"type": "text", "text": "github.com/you/repo", "font": "Segoe UI Semibold", "size": 22, "color": "#0f1117",
     "x": 64, "y": 604}
  ]}})

Items draw bottom to top in order. Types: image (path, x, y, width and/or height, fit "contain"|"cover"|"stretch",
opacity), text (text, font, size, color, x, y, justify, letter_spacing, box_width), rect (x, y, width, height,
color, radius, opacity), ellipse (x, y, width, height, color, opacity). Any item takes "effects": a list of
{"op": "gegl:...", "params": {...}, "mode": "merge"|"append"}, and "name".
"anchor": "center" on text or image centres it on x, y. Returns each item's final bounding box so you can check
alignment with gimp_measure or adjust and re-run. "keep_open": true leaves the layered image in GIMP for hand edits.
"""

TOPICS["errors"] = """\
READING ERRORS

"unknown argument(s) [...]; valid: [...]"      -> use a name from the valid list (dashes or underscores both fine)
"'x' is not one of [...] for GimpFoo"          -> use one of the listed enum nicks
"GIMP does not expose 'gegl:...' as a drawable filter" -> it is a source op; fill or draw instead (help filters)
"no open image with id N"                      -> ids change when images close; call gimp_list_images
"GIMP Agent Bridge is not reachable"           -> gimp_launch, or Filters > Development > Start Agent Bridge in GIMP
"segmentation is not installed"                -> uv sync --extra segmentation in the server directory
Long operations: pass a bigger timeout by splitting work, or use recipes which run inside GIMP in one call.
"""


def topics() -> list[str]:
    return list(TOPICS)


def get(topic: str | None) -> str:
    key = (topic or "start").strip().lower()
    if key in ("all", "*"):
        return "\n\n".join(TOPICS[k] for k in TOPICS)
    if key not in TOPICS:
        return f"Unknown help topic {topic!r}. Topics: {', '.join(TOPICS)}.\n\n" + TOPICS["start"]
    return TOPICS[key]
