"""Pack mixed-size PNG sprites into a padded texture atlas and verify the exported pixels."""

DESCRIPTION = "Pack mixed-size PNG sprites or open layers into a padded atlas, optionally trimming transparent borders; save layered XCF and atlas JSON, and verify exported RGBA pixels"

PARAMS = {
    "input_paths": {"type": "array", "default": None, "description": "PNG sprites; canvas sizes may differ. Give this or input_layer_ids"},
    "input_layer_ids": {"type": "array", "default": None, "description": "Open, non-group layers to pack as sprites, keyed by layer name; source documents are not changed"},
    "output_path": {"type": "string", "required": True, "description": "Destination PNG; JSON and XCF use the same stem"},
    "padding": {"type": "integer", "default": 2, "minimum": 0, "description": "Transparent pixels between sprites and around the atlas edge"},
    "trim": {"type": "boolean", "default": False, "description": "Pack each sprite's measured alpha bounds instead of its full canvas"},
    "max_width": {"type": "integer", "default": 2048, "minimum": 1, "description": "Maximum atlas width in px; height grows as needed"},
    "power_of_two": {"type": "boolean", "default": False, "description": "Round atlas width and height up to powers of two (max_width must then be one)"},
    "keep_open": {"type": "boolean", "default": False, "description": "Keep the layered atlas open after successful verification"},
    "overwrite": {"type": "boolean", "default": False, "description": "Allow replacing existing output PNG, JSON and XCF files"},
}

# Pure Python so it runs inside GIMP and in unit tests alike.
PACKER = r'''
def pack_rects(sizes, max_width, padding):
    """MaxRects, bottom-left rule. sizes: list of (w, h). Returns (positions, width, height).

    Each sprite gets `padding` transparent pixels on every side, shared between neighbours,
    so two sprites are always at least `padding` apart and never touch the atlas edge.
    """
    if any(w < 1 or h < 1 for w, h in sizes):
        raise ValueError("sprite sizes must be positive")
    inner = max_width - padding
    for i, (w, h) in enumerate(sizes):
        if w + 2 * padding > max_width:
            raise ValueError(f"sprite {i} is {w}px wide; max_width {max_width} with padding {padding} fits at most {max_width - 2 * padding}px")
    height_bound = sum(h + padding for _, h in sizes) + padding
    free = [(0, 0, inner, height_bound)]
    order = sorted(range(len(sizes)), key=lambda i: (-max(sizes[i]), -sizes[i][0] * sizes[i][1], i))
    positions = [None] * len(sizes)
    for i in order:
        w, h = sizes[i][0] + padding, sizes[i][1] + padding
        best = None
        for fx, fy, fw, fh in free:
            if w <= fw and h <= fh and (best is None or (fy + h, fx) < best):
                best = (fy + h, fx, fy)
        _, px, py = best
        positions[i] = (px + padding, py + padding)
        placed = (px, py, px + w, py + h)
        split = []
        for fx, fy, fw, fh in free:
            x2, y2 = fx + fw, fy + fh
            if placed[0] >= x2 or placed[2] <= fx or placed[1] >= y2 or placed[3] <= fy:
                split.append((fx, fy, fw, fh))
                continue
            if placed[0] > fx:
                split.append((fx, fy, placed[0] - fx, fh))
            if placed[2] < x2:
                split.append((placed[2], fy, x2 - placed[2], fh))
            if placed[1] > fy:
                split.append((fx, fy, fw, placed[1] - fy))
            if placed[3] < y2:
                split.append((fx, placed[3], fw, y2 - placed[3]))
        free = [r for j, r in enumerate(split) if not any(
            k != j and o[0] <= r[0] and o[1] <= r[1] and o[0] + o[2] >= r[0] + r[2] and o[1] + o[3] >= r[1] + r[3]
            and (o != r or k < j) for k, o in enumerate(split))]
    width = max(x + w for (x, _), (w, _) in zip(positions, sizes)) + padding
    height = max(y + h for (_, y), (_, h) in zip(positions, sizes)) + padding
    return positions, width, height


def next_power_of_two(n):
    p = 1
    while p < n:
        p *= 2
    return p
'''

_namespace: dict = {}
exec(PACKER, _namespace)
pack_rects = _namespace["pack_rects"]
next_power_of_two = _namespace["next_power_of_two"]

SOURCE = PACKER + r'''
import os, json, hashlib

def pack_atlas():
    paths, layer_ids = params["input_paths"], params["input_layer_ids"]
    if (paths is None) == (layer_ids is None):
        raise ValueError("give exactly one of input_paths or input_layer_ids")
    if paths is not None:
        if not isinstance(paths, list) or not paths or any(not isinstance(p, str) or not p for p in paths):
            raise ValueError("input_paths must be a non-empty list of PNG paths")
        paths = [os.path.abspath(os.path.expanduser(p)) for p in paths]
        if any(os.path.splitext(p)[1].lower() != ".png" or not os.path.isfile(p) for p in paths):
            raise ValueError("every input must be an existing PNG file")
        names = [os.path.basename(p) for p in paths]
    else:
        if not isinstance(layer_ids, list) or not layer_ids or any(type(i) is not int for i in layer_ids):
            raise ValueError("input_layer_ids must be a non-empty list of layer ids")
        open_layers = []
        for i in layer_ids:
            item = item_by_id(i)
            if not isinstance(item, Gimp.Layer) or item.is_group():
                raise ValueError(f"item {i} is not a raster layer")
            open_layers.append(item)
        names = [layer.get_name() for layer in open_layers]
        paths = []
    if len({n.casefold() for n in names}) != len(names):
        raise ValueError("sprite names (file basenames or layer names) must be unique for atlas keys")
    dst = os.path.abspath(os.path.expanduser(params["output_path"]))
    if os.path.splitext(dst)[1].lower() != ".png":
        raise ValueError("output_path must end in .png")
    stem = os.path.splitext(dst)[0]
    outputs = [dst, stem + ".json", stem + ".xcf"]
    if any(os.path.normcase(p) in {os.path.normcase(s) for s in paths} for p in outputs):
        raise ValueError("outputs must not overwrite input sprites")
    if not params["overwrite"] and any(os.path.exists(p) for p in outputs):
        raise ValueError("output already exists; choose a new path or set overwrite=true")
    pad, max_w, trim = params["padding"], params["max_width"], params["trim"]
    if type(pad) is not int or pad < 0 or type(max_w) is not int or max_w < 1:
        raise ValueError("padding must be a non-negative integer and max_width a positive integer")
    if params["power_of_two"] and next_power_of_two(max_w) != max_w:
        raise ValueError("power_of_two requires max_width to be a power of two")

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

    # Measure every sprite before placing any, so packing sees the real rectangles.
    sources, sprites = [], []
    atlas = verified = None
    success = False
    try:
        inputs = []
        for path in paths:
            source = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(path))
            if source is None:
                raise RuntimeError(f"could not load {path}")
            sources.append(source)
            inputs.append(source.get_layers()[0])
        if not paths:
            # Open layers are read in place; their documents are never modified or closed.
            inputs = open_layers
        for i, layer in enumerate(inputs):
            w, h = layer.get_width(), layer.get_height()
            full = pixels(layer, 0, 0, w, h)
            b = bbox(full, w, h)
            # A fully transparent sprite trims to one transparent pixel, as standard packers do.
            rect = (b["x"], b["y"], b["w"], b["h"]) if trim and b else ((0, 0, 1, 1) if trim else (0, 0, w, h))
            data = pixels(layer, *rect)
            sprites.append({"name": names[i], "layer": layer, "source": (w, h), "rect": rect, "bounds": b,
                "hash": hashlib.sha256(data).hexdigest()})
        positions, aw, ah = pack_rects([(s["rect"][2], s["rect"][3]) for s in sprites], max_w, pad)
        if params["power_of_two"]:
            aw, ah = next_power_of_two(aw), next_power_of_two(ah)
        atlas = Gimp.Image.new(aw, ah, Gimp.ImageBaseType.RGB)
        base = Gimp.Layer.new(atlas, "Transparent canvas", aw, ah, Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
        atlas.insert_layer(base, None, 0)
        base.fill(Gimp.FillType.TRANSPARENT)
        frames = {}
        for s, (x, y) in zip(sprites, positions):
            rx, ry, rw, rh = s["rect"]
            placed = Gimp.Layer.new_from_drawable(s["layer"], atlas)
            atlas.insert_layer(placed, None, 0)
            placed.set_name(s["name"])
            if not placed.has_alpha():
                placed.add_alpha()
            placed.resize(rw, rh, -rx, -ry)
            placed.set_offsets(x, y)
            sw, sh = s["source"]
            b = s["bounds"]
            frames[s["name"]] = {"frame": {"x": x, "y": y, "w": rw, "h": rh},
                "rotated": False, "trimmed": (rw, rh) != (sw, sh),
                "spriteSourceSize": {"x": rx, "y": ry, "w": rw, "h": rh},
                "sourceSize": {"w": sw, "h": sh}, "alphaBounds": b,
                "measuredPivot": {"x": (b["x"] + b["w"] / 2) / sw, "y": (b["y"] + b["h"]) / sh} if b else None}
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        export_with(atlas, dst, {"compression": 9, "bkgd": False, "phys": False, "time": False, "include-thumbnail": False})
        verified = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(dst))
        if verified is None or (verified.get_width(), verified.get_height()) != (aw, ah):
            raise RuntimeError("export verification failed: atlas dimensions")
        layer = verified.get_layers()[0]
        if not layer.has_alpha():
            raise RuntimeError("export verification failed: missing alpha channel")
        whole = pixels(layer, 0, 0, aw, ah)
        alpha = bytearray(whole[3::4])
        for s, (x, y) in zip(sprites, positions):
            rw, rh = s["rect"][2], s["rect"][3]
            region = b"".join(whole[((y + r) * aw + x) * 4:((y + r) * aw + x + rw) * 4] for r in range(rh))
            if hashlib.sha256(region).hexdigest() != s["hash"]:
                raise RuntimeError(f"export verification failed: RGBA pixels differ for {s['name']}")
            for r in range(rh):
                start = (y + r) * aw + x
                alpha[start:start + rw] = bytes(rw)
        if any(alpha):
            raise RuntimeError("export verification failed: padding or unused area is not transparent")
        export_with(atlas, outputs[2], {})
        used = sum(s["rect"][2] * s["rect"][3] for s in sprites)
        report = {"frames": frames, "meta": {"image": os.path.basename(dst), "size": {"w": aw, "h": ah}, "scale": "1",
            "padding": pad, "trimmed": trim, "powerOfTwo": params["power_of_two"],
            "verification": "exact RGBA match, transparent padding", "occupancy": round(used / (aw * ah), 4),
            "sourceBytes": sum(os.path.getsize(p) for p in paths) if paths else None, "atlasBytes": os.path.getsize(dst)}}
        with open(outputs[1], "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
            fh.write("\n")
        success = True
        return {"output_path": dst, "atlas_path": outputs[1], "xcf_path": outputs[2], "frames": len(frames),
            **report["meta"], "placements": {n: f["frame"] for n, f in frames.items()},
            "image_id": atlas.get_id() if params["keep_open"] else None}
    finally:
        for source in sources:
            source.delete()
        if verified is not None:
            verified.delete()
        if atlas is not None and not (success and params["keep_open"]):
            atlas.delete()

result = pack_atlas()
'''
