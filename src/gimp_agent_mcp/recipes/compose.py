"""Build a card or banner from a layout manifest of images, text and shapes."""

DESCRIPTION = "Compose a card or banner from a manifest: background, images, text, rectangles, ellipses, per-item effects"

PARAMS = {
    "output_path": {"type": "string", "required": True, "description": "Destination image; extension picks the format"},
    "manifest": {"type": "object", "default": None, "description": "Layout manifest (see gimp_help('compose')); or use manifest_path"},
    "manifest_path": {"type": "string", "default": "", "description": "Path to a JSON manifest file instead of inline manifest"},
    "export_options": {"type": "object", "default": {}, "description": "Options for the export procedure, e.g. {\"quality\": 85}"},
    "keep_open": {"type": "boolean", "default": False, "description": "Leave the layered image open in GIMP for hand edits"},
}

SOURCE = r'''
import os, json

manifest = params.get("manifest")
if not manifest and params.get("manifest_path"):
    with open(os.path.abspath(os.path.expanduser(params["manifest_path"])), encoding="utf-8") as fh:
        manifest = json.load(fh)
if not isinstance(manifest, dict):
    raise RuntimeError("compose needs a manifest dict or manifest_path")

W = int(manifest.get("width", 1200))
H = int(manifest.get("height", 630))
dst = os.path.abspath(os.path.expanduser(params["output_path"]))

image = Gimp.Image.new(W, H, Gimp.ImageBaseType.RGB)
placed = []

def _fill_type_name(t):
    return t

def new_layer(name, w=None, h=None):
    l = Gimp.Layer.new(image, name, int(w or W), int(h or H), Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
    image.insert_layer(l, None, 0)
    l.fill(Gimp.FillType.TRANSPARENT)
    return l

def solid(layer, color):
    Gimp.context_push()
    Gimp.context_set_foreground(make_color(color))
    layer.edit_fill(Gimp.FillType.FOREGROUND)
    Gimp.context_pop()

def apply_effects(layer, effects):
    for eff in effects or []:
        op = eff["op"]
        f = Gimp.DrawableFilter.new(layer, op, eff.get("name") or op)
        if f is None:
            raise RuntimeError(f"{op} is not available as a layer effect")
        cfg = f.get_config()
        types = {p.name: p.value_type.name for p in cfg.list_properties()}
        for k, v in (eff.get("params") or {}).items():
            key = k.replace("_", "-")
            if key not in types:
                raise RuntimeError(f"unknown property {k!r} for {op}; valid: {sorted(types)}")
            cfg.set_property(key, make_color(v) if types[key] == "GeglColor" else v)
        f.update()
        if (eff.get("mode") or "merge") == "append":
            layer.append_filter(f)
        else:
            layer.merge_filter(f)

def record(item, layer):
    ok, x, y = layer.get_offsets()
    placed.append({"type": item.get("type"), "name": layer.get_name(), "layer_id": layer.get_id(),
                   "x": x, "y": y, "width": layer.get_width(), "height": layer.get_height()})

bg = manifest.get("background", "transparent")
base = new_layer("background")
if bg and str(bg).lower() not in ("transparent", "none"):
    Gimp.Selection.all(image); solid(base, bg); Gimp.Selection.none(image)

for idx, item in enumerate(manifest.get("items") or []):
    kind = str(item.get("type") or "").lower()
    name = item.get("name") or f"{kind}-{idx}"
    x, y = int(item.get("x", 0)), int(item.get("y", 0))
    anchor = str(item.get("anchor") or "top-left").lower()
    if kind == "image":
        src = os.path.abspath(os.path.expanduser(item["path"]))
        layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, image, Gio.File.new_for_path(src))
        image.insert_layer(layer, None, 0)
        layer.set_name(name)
        lw, lh = layer.get_width(), layer.get_height()
        tw, th = item.get("width"), item.get("height")
        fit = str(item.get("fit") or "contain").lower()
        if tw or th:
            tw = int(tw) if tw else None; th = int(th) if th else None
            if fit == "stretch" and tw and th:
                nw, nh = tw, th
            else:
                sx = (tw / float(lw)) if tw else None
                sy = (th / float(lh)) if th else None
                cands = [s for s in (sx, sy) if s]
                s = (max(cands) if fit == "cover" else min(cands)) if cands else 1.0
                nw, nh = max(1, int(round(lw * s))), max(1, int(round(lh * s)))
            if (nw, nh) != (lw, lh):
                layer.scale(nw, nh, False)
            if fit == "cover" and tw and th:
                ok, ox, oy = layer.get_offsets()
                layer.resize(tw, th, -((nw - tw) // 2), -((nh - th) // 2))
        if item.get("opacity") is not None:
            layer.set_opacity(float(item["opacity"]))
    elif kind == "text":
        font = Gimp.Font.get_by_name(item.get("font", "")) if item.get("font") else None
        if font is None:
            font = Gimp.context_get_font()
        layer = Gimp.TextLayer.new(image, str(item.get("text", "")), font, float(item.get("size", 32)), Gimp.Unit.pixel())
        image.insert_layer(layer, None, 0)
        layer.set_name(name)
        layer.set_color(make_color(item.get("color", "#000000")))
        if item.get("justify"):
            layer.set_justification(getattr(Gimp.TextJustification, str(item["justify"]).upper()))
        if item.get("letter_spacing") is not None:
            layer.set_letter_spacing(float(item["letter_spacing"]))
        if item.get("line_spacing") is not None:
            layer.set_line_spacing(float(item["line_spacing"]))
        if item.get("box_width"):
            layer.resize(float(item["box_width"]), float(item.get("box_height") or layer.get_height()))
        if item.get("opacity") is not None:
            layer.set_opacity(float(item["opacity"]))
    elif kind in ("rect", "ellipse"):
        w, h = int(item.get("width", 100)), int(item.get("height", 100))
        layer = new_layer(name, w, h)
        layer.set_offsets(x, y)
        if kind == "ellipse":
            image.select_ellipse(Gimp.ChannelOps.REPLACE, x, y, w, h)
        else:
            r = float(item.get("radius", 0))
            if r > 0:
                image.select_round_rectangle(Gimp.ChannelOps.REPLACE, x, y, w, h, r, r)
            else:
                image.select_rectangle(Gimp.ChannelOps.REPLACE, x, y, w, h)
        solid(layer, item.get("color", "#000000"))
        Gimp.Selection.none(image)
        if item.get("opacity") is not None:
            layer.set_opacity(float(item["opacity"]))
    else:
        raise RuntimeError(f"unknown item type {kind!r} at index {idx}; use image, text, rect or ellipse")

    if kind in ("image", "text"):
        lw, lh = layer.get_width(), layer.get_height()
        if anchor == "center":
            layer.set_offsets(x - lw // 2, y - lh // 2)
        elif anchor == "top-right":
            layer.set_offsets(x - lw, y)
        elif anchor == "bottom-left":
            layer.set_offsets(x, y - lh)
        elif anchor == "bottom-right":
            layer.set_offsets(x - lw, y - lh)
        else:
            layer.set_offsets(x, y)
    apply_effects(layer, item.get("effects"))
    record(item, layer)

if not params["keep_open"]:
    flat = image.duplicate()
    flat.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
    export_with(flat, dst, params.get("export_options") or {})
    flat.delete()
    image.delete()
    image_id = None
else:
    export_with(image, dst, params.get("export_options") or {})
    image_id = image.get_id()

result = {"output_path": dst, "bytes": os.path.getsize(dst), "width": W, "height": H, "items": placed, "image_id": image_id}
'''
