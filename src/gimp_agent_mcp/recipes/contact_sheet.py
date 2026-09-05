"""Lay out a folder of images as a labelled grid."""

DESCRIPTION = "Build a contact sheet: thumbnails of every image in a folder on a grid with file-name labels"

PARAMS = {
    "input_dir": {"type": "string", "required": True, "description": "Folder of images"},
    "output_path": {"type": "string", "required": True, "description": "Destination .png or .jpg"},
    "pattern": {"type": "string", "default": ".png,.jpg,.jpeg,.webp", "description": "Comma list of extensions to include"},
    "columns": {"type": "integer", "default": 4, "description": "Thumbnails per row"},
    "thumb": {"type": "integer", "default": 256, "description": "Thumbnail cell size in px"},
    "gap": {"type": "integer", "default": 16, "description": "Gap between cells in px"},
    "labels": {"type": "boolean", "default": True, "description": "Write the file name under each thumbnail"},
    "background": {"type": "string", "default": "#202020", "description": "Sheet background colour"},
    "label_color": {"type": "string", "default": "#dddddd", "description": "Label text colour"},
}

SOURCE = r'''
import os, math

in_dir = os.path.abspath(os.path.expanduser(params["input_dir"]))
dst = os.path.abspath(os.path.expanduser(params["output_path"]))
exts = tuple(e.strip().lower() for e in params["pattern"].split(",") if e.strip())
files = sorted(f for f in os.listdir(in_dir) if f.lower().endswith(exts))
if not files:
    raise RuntimeError(f"no images matching {exts} in {in_dir}")
cols = max(1, int(params["columns"]))
thumb, gap = int(params["thumb"]), int(params["gap"])
label_h = 22 if params["labels"] else 0
rows = math.ceil(len(files) / cols)
W = cols * thumb + (cols + 1) * gap
H = rows * (thumb + label_h) + (rows + 1) * gap

sheet = Gimp.Image.new(W, H, Gimp.ImageBaseType.RGB)
bg = Gimp.Layer.new(sheet, "background", W, H, Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
sheet.insert_layer(bg, None, 0)
Gimp.context_push()
Gimp.context_set_foreground(make_color(params["background"]))
bg.fill(Gimp.FillType.FOREGROUND)
Gimp.context_pop()
placed = []
try:
    for idx, name in enumerate(files):
        r, c = divmod(idx, cols)
        cx = gap + c * (thumb + gap)
        cy = gap + r * (thumb + label_h + gap)
        try:
            layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, sheet, Gio.File.new_for_path(os.path.join(in_dir, name)))
        except Exception:
            continue
        sheet.insert_layer(layer, None, 0)
        lw, lh = layer.get_width(), layer.get_height()
        s = min(thumb / float(lw), thumb / float(lh), 1.0)
        nw, nh = max(1, int(lw * s)), max(1, int(lh * s))
        if (nw, nh) != (lw, lh):
            layer.scale(nw, nh, False)
        layer.set_offsets(cx + (thumb - nw) // 2, cy + (thumb - nh) // 2)
        if params["labels"]:
            text = Gimp.TextLayer.new(sheet, name, Gimp.context_get_font(), 12.0, Gimp.Unit.pixel())
            sheet.insert_layer(text, None, 0)
            text.set_color(make_color(params["label_color"]))
            tw = text.get_width()
            text.set_offsets(cx + max(0, (thumb - tw) // 2), cy + thumb + 4)
        placed.append(name)
    sheet.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
    export_with(sheet, dst, {})
finally:
    sheet.delete()

result = {"output_path": dst, "bytes": os.path.getsize(dst), "images": len(placed), "columns": cols, "rows": rows, "size": [W, H]}
'''
