"""Cut a sprite sheet into individual tiles."""

DESCRIPTION = "Slice a sprite sheet into fixed-size tiles, skipping fully transparent ones, and export each as PNG"

PARAMS = {
    "input_path": {"type": "string", "required": True, "description": "Sprite sheet image"},
    "output_dir": {"type": "string", "required": True, "description": "Folder for the tiles"},
    "tile_width": {"type": "integer", "required": True, "description": "Tile width in px"},
    "tile_height": {"type": "integer", "required": True, "description": "Tile height in px"},
    "margin": {"type": "integer", "default": 0, "description": "Outer margin before the first tile"},
    "spacing": {"type": "integer", "default": 0, "description": "Gap between tiles"},
    "prefix": {"type": "string", "default": "tile", "description": "File name prefix; files are <prefix>-<row>-<col>.png"},
    "skip_empty": {"type": "boolean", "default": True, "description": "Skip tiles that are fully transparent"},
}

SOURCE = r'''
import os

src = os.path.abspath(os.path.expanduser(params["input_path"]))
out_dir = os.path.abspath(os.path.expanduser(params["output_dir"]))
os.makedirs(out_dir, exist_ok=True)
tw, th = int(params["tile_width"]), int(params["tile_height"])
margin, spacing = int(params["margin"]), int(params["spacing"])

sheet = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(src))
if sheet is None:
    raise RuntimeError(f"could not load {src}")
tiles = []
try:
    if len(sheet.get_layers()) > 1:
        sheet.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
    layer = sheet.get_layers()[0]
    if not layer.has_alpha():
        layer.add_alpha()
    W, H = sheet.get_width(), sheet.get_height()
    cols = (W - margin + spacing) // (tw + spacing)
    rows = (H - margin + spacing) // (th + spacing)
    buf = layer.get_buffer()
    for r in range(rows):
        for c in range(cols):
            x = margin + c * (tw + spacing)
            y = margin + r * (th + spacing)
            if params["skip_empty"]:
                data = bytes(buf.get(Gegl.Rectangle.new(x, y, tw, th), 1.0, "R'G'B'A u8", Gegl.AbyssPolicy.CLAMP))
                if not any(data[3::4]):
                    continue
            dup = sheet.duplicate()
            try:
                dup.crop(tw, th, x, y)
                dst = os.path.join(out_dir, f"{params['prefix']}-{r}-{c}.png")
                if not Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, dup, Gio.File.new_for_path(dst), None):
                    raise RuntimeError(f"export failed: {dst}")
                tiles.append({"row": r, "col": c, "path": dst})
            finally:
                dup.delete()
finally:
    sheet.delete()

result = {"output_dir": out_dir, "rows": rows, "cols": cols, "tiles": len(tiles), "files": [t["path"] for t in tiles]}
'''
