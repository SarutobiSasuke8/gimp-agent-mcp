"""Resize an image so its longest side fits a limit, then export in the format implied by the extension."""

DESCRIPTION = "Open an image, scale it to a maximum edge length, export as PNG/WebP/JPEG by extension"

PARAMS = {
    "input_path": {"type": "string", "required": True, "description": "Source image"},
    "output_path": {"type": "string", "required": True, "description": "Destination; extension picks the format"},
    "max_edge": {"type": "integer", "default": 1920, "description": "Longest side after scaling; never upscales"},
    "flatten": {"type": "boolean", "default": False, "description": "Merge visible layers before export"},
    "keep_open": {"type": "boolean", "default": False, "description": "Leave the image open in GIMP"},
}

SOURCE = r'''
import os

src = os.path.abspath(os.path.expanduser(params["input_path"]))
dst = os.path.abspath(os.path.expanduser(params["output_path"]))
max_edge = int(params["max_edge"])

image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(src))
if image is None:
    raise RuntimeError(f"could not load {src}")
image.undo_group_start()
try:
    if params["flatten"] and len(image.get_layers()) > 1:
        image.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
    w, h = image.get_width(), image.get_height()
    if max(w, h) > max_edge:
        scale = max_edge / float(max(w, h))
        image.scale(max(1, int(round(w * scale))), max(1, int(round(h * scale))))
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    if not Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, image, Gio.File.new_for_path(dst), None):
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
