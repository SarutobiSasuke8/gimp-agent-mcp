"""Pack equal-sized PNG frames and verify the exported pixels."""

DESCRIPTION = "Pack ordered PNG frames into a transparent grid, save layered XCF and atlas JSON, and verify exported RGBA pixels"

PARAMS = {
    "input_paths": {"type": "array", "required": True, "description": "Ordered, non-empty list of PNG frames with equal canvas sizes"},
    "output_path": {"type": "string", "required": True, "description": "Destination PNG; JSON and XCF use the same stem"},
    "columns": {"type": "integer", "default": 4, "minimum": 1, "description": "Maximum cells per row"},
    "keep_open": {"type": "boolean", "default": False, "description": "Keep the layered sheet open after successful verification"},
    "overwrite": {"type": "boolean", "default": False, "description": "Allow replacing existing output PNG, JSON and XCF files"},
}

SOURCE = r'''
import os, json, hashlib

def pack_sheet():
    paths = params["input_paths"]
    if not isinstance(paths, list) or not paths or any(not isinstance(p, str) or not p for p in paths):
        raise ValueError("input_paths must be a non-empty list of PNG paths")
    paths = [os.path.abspath(os.path.expanduser(p)) for p in paths]
    if any(os.path.splitext(p)[1].lower() != ".png" or not os.path.isfile(p) for p in paths):
        raise ValueError("every input must be an existing PNG file")
    names = [os.path.basename(p) for p in paths]
    if len({n.casefold() for n in names}) != len(names):
        raise ValueError("input frame basenames must be unique for atlas keys")
    dst = os.path.abspath(os.path.expanduser(params["output_path"]))
    if os.path.splitext(dst)[1].lower() != ".png":
        raise ValueError("output_path must end in .png")
    stem = os.path.splitext(dst)[0]
    outputs = [dst, stem + ".json", stem + ".xcf"]
    if any(os.path.normcase(p) in {os.path.normcase(s) for s in paths} for p in outputs):
        raise ValueError("outputs must not overwrite input frames")
    if not params["overwrite"] and any(os.path.exists(p) for p in outputs):
        raise ValueError("output already exists; choose a new path or set overwrite=true")
    cols = params["columns"]
    if type(cols) is not int or cols < 1:
        raise ValueError("columns must be a positive integer")
    cols = min(cols, len(paths))
    rows = (len(paths) + cols - 1) // cols
    sheet = None
    verified = None
    success = False
    frames, hashes, bounds = {}, [], []
    def pixels(layer, x, y, w, h):
        return bytes(layer.get_buffer().get(Gegl.Rectangle.new(x, y, w, h), 1.0, "R'G'B'A u8", Gegl.AbyssPolicy.NONE))
    def bbox(data, w, h):
        xs, ys = [], []
        for y in range(h):
            row = data[(y * w * 4 + 3):((y + 1) * w * 4):4]
            occupied = [x for x, a in enumerate(row) if a]
            if occupied:
                xs.extend((occupied[0], occupied[-1]))
                ys.append(y)
        return {"x": min(xs), "y": min(ys), "w": max(xs)-min(xs)+1, "h": max(ys)-min(ys)+1} if xs else None
    try:
        for i, path in enumerate(paths):
            source = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(path))
            if source is None:
                raise RuntimeError(f"could not load {path}")
            try:
                w, h = source.get_width(), source.get_height()
                if sheet is None:
                    cw, ch = w, h
                    sheet = Gimp.Image.new(cw * cols, ch * rows, Gimp.ImageBaseType.RGB)
                    base = Gimp.Layer.new(sheet, "Transparent canvas", cw * cols, ch * rows, Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
                    sheet.insert_layer(base, None, 0)
                    base.fill(Gimp.FillType.TRANSPARENT)
                elif (w, h) != (cw, ch):
                    raise ValueError(f"mixed canvas sizes: {names[i]} is {w}x{h}; expected {cw}x{ch}; use an atlas workflow")
                layer = source.get_layers()[0]
                data = pixels(layer, 0, 0, cw, ch)
                b = bbox(data, cw, ch)
                bounds.append(b)
                hashes.append(hashlib.sha256(data).hexdigest())
                placed = Gimp.Layer.new_from_drawable(layer, sheet)
                sheet.insert_layer(placed, None, 0)
                placed.set_name(names[i])
                x, y = (i % cols) * cw, (i // cols) * ch
                placed.set_offsets(x, y)
                # Full cells work in standard atlas loaders, including empty frames.
                frames[names[i]] = {"frame": {"x": x, "y": y, "w": cw, "h": ch},
                    "rotated": False, "trimmed": False,
                    "spriteSourceSize": {"x": 0, "y": 0, "w": cw, "h": ch},
                    "sourceSize": {"w": cw, "h": ch}, "alphaBounds": b,
                    "measuredPivot": {"x": (b["x"] + b["w"] / 2) / cw, "y": (b["y"] + b["h"]) / ch} if b else None}
            finally:
                source.delete()
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        export_with(sheet, dst, {"compression": 9, "bkgd": False, "phys": False, "time": False, "include-thumbnail": False})
        verified = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(dst))
        if verified is None or (verified.get_width(), verified.get_height()) != (cw * cols, ch * rows):
            raise RuntimeError("export verification failed: sheet dimensions")
        layer = verified.get_layers()[0]
        if not layer.has_alpha():
            raise RuntimeError("export verification failed: missing alpha channel")
        for i, (name, frame) in enumerate(frames.items()):
            r = frame["frame"]
            data = pixels(layer, r["x"], r["y"], cw, ch)
            if hashlib.sha256(data).hexdigest() != hashes[i] or bbox(data, cw, ch) != bounds[i]:
                raise RuntimeError(f"export verification failed: RGBA pixels differ for {name}")
        for i in range(len(paths), rows * cols):
            data = pixels(layer, (i % cols) * cw, (i // cols) * ch, cw, ch)
            if any(data[3::4]):
                raise RuntimeError("export verification failed: unused cell is not transparent")
        export_with(sheet, outputs[2], {})
        feet = [b["y"] + b["h"] for b in bounds if b]
        centres = [b["x"] + b["w"] / 2 for b in bounds if b]
        report = {"frames": frames, "meta": {"image": os.path.basename(dst), "size": {"w": cw * cols, "h": ch * rows},
            "scale": "1", "columns": cols, "rows": rows, "frameWidth": cw, "frameHeight": ch,
            "verification": "exact RGBA match", "sourceBytes": sum(os.path.getsize(p) for p in paths), "sheetBytes": os.path.getsize(dst),
            "footDriftPx": max(feet)-min(feet) if feet else None, "centreDriftPx": max(centres)-min(centres) if centres else None}}
        with open(outputs[1], "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
            fh.write("\n")
        success = True
        return {"output_path": dst, "atlas_path": outputs[1], "xcf_path": outputs[2], "frames": len(frames),
            **report["meta"], "bounds": bounds, "image_id": sheet.get_id() if params["keep_open"] else None}
    finally:
        if verified is not None:
            verified.delete()
        if sheet is not None and not (success and params["keep_open"]):
            sheet.delete()

result = pack_sheet()
'''
