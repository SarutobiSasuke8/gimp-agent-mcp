"""Turn a transparent PNG into a Telegram-ready 512x512 sticker with a white stroke and drop shadow."""

DESCRIPTION = "Fit artwork into a 512x512 transparent canvas, add a white outline and a soft shadow, export PNG"

PARAMS = {
    "input_path": {"type": "string", "required": True, "description": "Source image with transparency"},
    "output_path": {"type": "string", "required": True, "description": "Destination .png (or .webp)"},
    "canvas": {"type": "integer", "default": 512, "description": "Output canvas size in px (Telegram: 512)"},
    "fit": {"type": "integer", "default": 490, "description": "Longest side of the artwork after scaling; leaves room for the stroke"},
    "stroke_px": {"type": "integer", "default": 8, "description": "Outline thickness in px; 0 disables"},
    "stroke_color": {"type": "string", "default": "white", "description": "Outline colour"},
    "shadow_offset_y": {"type": "number", "default": 5, "description": "Shadow vertical offset in px"},
    "shadow_offset_x": {"type": "number", "default": 0, "description": "Shadow horizontal offset in px"},
    "shadow_blur": {"type": "number", "default": 8, "description": "Shadow blur radius; 0 disables the shadow"},
    "shadow_opacity": {"type": "number", "default": 0.4, "description": "Shadow opacity 0..1"},
    "shadow_color": {"type": "string", "default": "black", "description": "Shadow colour"},
    "keep_open": {"type": "boolean", "default": False, "description": "Leave the working image open in GIMP"},
}

SOURCE = r'''
import os

src = os.path.abspath(os.path.expanduser(params["input_path"]))
dst = os.path.abspath(os.path.expanduser(params["output_path"]))
canvas = int(params["canvas"])
fit = int(params["fit"])
if fit > canvas:
    fit = canvas

image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(src))
if image is None:
    raise RuntimeError(f"could not load {src}")
image.undo_group_start()
try:
    # Collapse to one layer with alpha, then fit the artwork inside the canvas.
    layers = image.get_layers()
    if len(layers) > 1:
        layer = image.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
    else:
        layer = layers[0]
    if not layer.has_alpha():
        layer.add_alpha()

    w, h = image.get_width(), image.get_height()
    scale = fit / float(max(w, h))
    if scale < 1.0 or max(w, h) < fit:
        nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
        image.scale(nw, nh)
    w, h = image.get_width(), image.get_height()
    image.resize(canvas, canvas, (canvas - w) // 2, (canvas - h) // 2)
    layer = image.get_layers()[0]
    layer.resize_to_image_size()

    def drop_shadow(drawable, x, y, blur, grow, color, opacity):
        f = Gimp.DrawableFilter.new(drawable, "gegl:dropshadow", "agent-shadow")
        cfg = f.get_config()
        cfg.set_property("x", float(x))
        cfg.set_property("y", float(y))
        cfg.set_property("radius", float(blur))
        cfg.set_property("grow-radius", float(grow))
        cfg.set_property("color", make_color(color))
        cfg.set_property("opacity", float(opacity))
        f.update()
        drawable.merge_filter(f)

    if int(params["stroke_px"]) > 0:
        drop_shadow(layer, 0, 0, 0, int(params["stroke_px"]), params["stroke_color"], 1.0)
    if float(params["shadow_blur"]) > 0 or float(params["shadow_offset_y"]) or float(params["shadow_offset_x"]):
        drop_shadow(
            layer,
            float(params["shadow_offset_x"]),
            float(params["shadow_offset_y"]),
            float(params["shadow_blur"]),
            0,
            params["shadow_color"],
            float(params["shadow_opacity"]),
        )

    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    ok = Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, image, Gio.File.new_for_path(dst), None)
    if not ok:
        raise RuntimeError(f"export failed: {dst}")
finally:
    image.undo_group_end()

result = {
    "output_path": dst,
    "bytes": os.path.getsize(dst),
    "width": image.get_width(),
    "height": image.get_height(),
    "image_id": image.get_id() if params["keep_open"] else None,
}
if not params["keep_open"]:
    image.delete()
'''
