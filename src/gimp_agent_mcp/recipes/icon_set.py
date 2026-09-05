"""Generate a set of square icons from one source image."""

DESCRIPTION = "Export a square source at every size in a list (favicon, app icons, PWA icons)"

PARAMS = {
    "input_path": {"type": "string", "required": True, "description": "Source image, ideally square with transparency"},
    "output_dir": {"type": "string", "required": True, "description": "Folder to write into"},
    "sizes": {"type": "array", "default": [16, 32, 48, 64, 128, 180, 192, 256, 512], "description": "Pixel sizes to export"},
    "prefix": {"type": "string", "default": "icon", "description": "File name prefix; files are <prefix>-<size>.png"},
    "pad_to_square": {"type": "boolean", "default": True, "description": "Centre non-square sources on a transparent square first"},
    "background": {"type": "string", "default": "", "description": "Optional background colour behind the icon, e.g. '#ffffff'"},
}

SOURCE = r'''
import os

src = os.path.abspath(os.path.expanduser(params["input_path"]))
out_dir = os.path.abspath(os.path.expanduser(params["output_dir"]))
os.makedirs(out_dir, exist_ok=True)

base = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(src))
if base is None:
    raise RuntimeError(f"could not load {src}")
files = []
try:
    if len(base.get_layers()) > 1:
        base.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
    layer = base.get_layers()[0]
    if not layer.has_alpha():
        layer.add_alpha()
    w, h = base.get_width(), base.get_height()
    if params["pad_to_square"] and w != h:
        side = max(w, h)
        base.resize(side, side, (side - w) // 2, (side - h) // 2)
        layer.resize_to_image_size()
    if params["background"]:
        bg = Gimp.Layer.new(base, "bg", base.get_width(), base.get_height(), Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
        Gimp.context_push()
        Gimp.context_set_foreground(make_color(params["background"]))
        bg.fill(Gimp.FillType.FOREGROUND)
        Gimp.context_pop()
        base.insert_layer(bg, None, len(base.get_layers()))
        base.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
    for size in sorted({int(s) for s in params["sizes"]}, reverse=True):
        dup = base.duplicate()
        try:
            dup.scale(size, size)
            dst = os.path.join(out_dir, f"{params['prefix']}-{size}.png")
            if not Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, dup, Gio.File.new_for_path(dst), None):
                raise RuntimeError(f"export failed: {dst}")
            files.append({"size": size, "path": dst, "bytes": os.path.getsize(dst)})
        finally:
            dup.delete()
finally:
    base.delete()

result = {"output_dir": out_dir, "files": files}
'''
