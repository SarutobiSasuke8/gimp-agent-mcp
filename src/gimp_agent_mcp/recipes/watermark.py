"""Stamp a text or image watermark onto an image."""

DESCRIPTION = "Overlay a text or image watermark in a corner or centre with opacity, then export"

PARAMS = {
    "input_path": {"type": "string", "required": True, "description": "Source image"},
    "output_path": {"type": "string", "required": True, "description": "Destination"},
    "text": {"type": "string", "default": "", "description": "Watermark text; leave empty to use watermark_path"},
    "watermark_path": {"type": "string", "default": "", "description": "PNG to overlay instead of text"},
    "position": {"type": "string", "default": "bottom-right", "description": "top-left, top-right, bottom-left, bottom-right, centre"},
    "opacity": {"type": "number", "default": 55, "description": "Opacity 0..100"},
    "margin": {"type": "integer", "default": 24, "description": "Distance from the edges in px"},
    "scale": {"type": "number", "default": 0.25, "description": "Watermark width as a fraction of the image width"},
    "color": {"type": "string", "default": "#ffffff", "description": "Text colour"},
    "font": {"type": "string", "default": "", "description": "Font name for text watermarks; empty uses the context font"},
}

SOURCE = r'''
import os

src = os.path.abspath(os.path.expanduser(params["input_path"]))
dst = os.path.abspath(os.path.expanduser(params["output_path"]))
image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(src))
if image is None:
    raise RuntimeError(f"could not load {src}")
try:
    W, H = image.get_width(), image.get_height()
    target_w = max(8, int(W * float(params["scale"])))
    if params["text"]:
        font = Gimp.Font.get_by_name(params["font"]) if params["font"] else Gimp.context_get_font()
        if font is None:
            font = Gimp.context_get_font()
        size = max(8.0, target_w / max(1, len(params["text"])) * 1.8)
        mark = Gimp.TextLayer.new(image, params["text"], font, size, Gimp.Unit.pixel())
        image.insert_layer(mark, None, 0)
        mark.set_color(make_color(params["color"]))
    else:
        wm_path = os.path.abspath(os.path.expanduser(params["watermark_path"]))
        mark = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, image, Gio.File.new_for_path(wm_path))
        image.insert_layer(mark, None, 0)
        mw, mh = mark.get_width(), mark.get_height()
        mark.scale(target_w, max(1, int(mh * target_w / float(mw))), False)
    mark.set_opacity(float(params["opacity"]))
    mw, mh = mark.get_width(), mark.get_height()
    m = int(params["margin"])
    pos = params["position"].lower()
    x = {"top-left": m, "bottom-left": m, "top-right": W - mw - m, "bottom-right": W - mw - m}.get(pos, (W - mw) // 2)
    y = {"top-left": m, "top-right": m, "bottom-left": H - mh - m, "bottom-right": H - mh - m}.get(pos, (H - mh) // 2)
    mark.set_offsets(int(x), int(y))
    image.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
    export_with(image, dst, {})
finally:
    image.delete()

result = {"output_path": dst, "bytes": os.path.getsize(dst), "watermark_box": [int(x), int(y), int(mw), int(mh)]}
'''
