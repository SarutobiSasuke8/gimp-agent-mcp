"""Crop and export one source to named social profiles around a focus point, then measure the outputs."""

DESCRIPTION = "Export a source image to social crop profiles (Open Graph, X, Instagram, story, YouTube) around a focus point; reopen each file and verify its measured size and pixels"

PARAMS = {
    "input_path": {"type": "string", "default": "", "description": "Source image file. Give this or image_id"},
    "image_id": {"type": "integer", "default": None, "description": "Open image to export from (visible layers); it is read, never changed. Give this or input_path"},
    "output_dir": {"type": "string", "required": True, "description": "Folder for the exports, named <stem>-<profile>.<format>"},
    "profiles": {"type": "array", "default": ["open_graph"], "description": "Profile names (see PROFILES, or 'all'), or custom {name, width, height} objects"},
    "focus": {"type": "object", "default": None, "description": "Point to keep in frame, {x, y} in source pixels; default is the image centre"},
    "fit": {"type": "string", "default": "cover", "description": "'cover' scales the source to cover the profile, then crops around the focus; 'crop' never scales and refuses profiles larger than the source"},
    "allow_upscale": {"type": "boolean", "default": False, "description": "Let 'cover' enlarge a source smaller than the profile (refused by default)"},
    "format": {"type": "string", "default": "png", "description": "png, jpg or webp"},
    "export_options": {"type": "object", "default": {}, "description": "Options for the export procedure, e.g. {\"quality\": 0.85} for JPEG"},
    "overwrite": {"type": "boolean", "default": False, "description": "Allow replacing existing output files"},
}

# Pure Python so the same planning runs inside GIMP and in unit tests.
PLANNER = r'''
import math

SOCIAL_PROFILES = {
    "open_graph": (1200, 630, "Open Graph / link preview, 1.91:1"),
    "x_landscape": (1600, 900, "X landscape post, 16:9"),
    "instagram_square": (1080, 1080, "Instagram square feed, 1:1"),
    "instagram_portrait": (1080, 1350, "Instagram portrait feed, 4:5"),
    "story_reel": (1080, 1920, "Story, reel or vertical short, 9:16"),
    "youtube_thumbnail": (1280, 720, "YouTube thumbnail, 16:9"),
}
MAX_PROFILE_EDGE = 16384


def resolve_profiles(requested):
    """Turn profile names, 'all' and custom {name, width, height} objects into (name, width, height) tuples."""
    if requested == "all" or requested == ["all"]:
        requested = list(SOCIAL_PROFILES)
    if not isinstance(requested, list) or not requested:
        raise ValueError("profiles must be a non-empty list of profile names or {name, width, height} objects")
    out = []
    for entry in requested:
        if isinstance(entry, str):
            if entry not in SOCIAL_PROFILES:
                raise ValueError(f"unknown social profile {entry!r}; available: {sorted(SOCIAL_PROFILES)} or a custom {{name, width, height}}")
            w, h, _use = SOCIAL_PROFILES[entry]
            out.append((entry, w, h))
        elif isinstance(entry, dict):
            name, w, h = entry.get("name"), entry.get("width"), entry.get("height")
            if not isinstance(name, str) or not name or not all(c.isalnum() or c in "-_" for c in name):
                raise ValueError(f"custom profile name {name!r} must be letters, digits, '-' or '_'")
            if type(w) is not int or type(h) is not int or not (1 <= w <= MAX_PROFILE_EDGE and 1 <= h <= MAX_PROFILE_EDGE):
                raise ValueError(f"custom profile {name!r} needs integer width and height in 1..{MAX_PROFILE_EDGE}")
            out.append((name, w, h))
        else:
            raise ValueError(f"profile entries must be names or objects, not {entry!r}")
    names = [n for n, _w, _h in out]
    if len(set(names)) != len(names):
        raise ValueError("profile names must be unique")
    return out


def plan_crop(src_w, src_h, out_w, out_h, focus_x, focus_y, fit="cover", allow_upscale=False):
    """Plan one export. Returns scale, scaled size, crop origin (in scaled pixels) and where the focus lands.

    The crop is centred on the focus and clamped to the scaled image, so the focus is always inside the
    output. 'cover' uses the smallest scale that covers the profile; 'crop' keeps scale 1.
    """
    if src_w < 1 or src_h < 1 or out_w < 1 or out_h < 1:
        raise ValueError("source and profile sizes must be positive")
    if not (0 <= focus_x < src_w and 0 <= focus_y < src_h):
        raise ValueError(f"focus ({focus_x}, {focus_y}) is outside the {src_w}x{src_h} source")
    if fit == "crop":
        if out_w > src_w or out_h > src_h:
            raise ValueError(f"{out_w}x{out_h} does not fit the {src_w}x{src_h} source without scaling; use fit='cover'")
        scale = 1.0
        scaled_w, scaled_h = src_w, src_h
    elif fit == "cover":
        scale = max(out_w / src_w, out_h / src_h)
        if scale > 1.0 and not allow_upscale:
            raise ValueError(f"{out_w}x{out_h} needs the {src_w}x{src_h} source enlarged {scale:.3f}x; pass allow_upscale=true or use a larger source")
        scaled_w = max(out_w, int(round(src_w * scale)))
        scaled_h = max(out_h, int(round(src_h * scale)))
    else:
        raise ValueError("fit must be 'cover' or 'crop'")
    # Focus at the centre of its source pixel, mapped into the scaled image.
    fx = (focus_x + 0.5) * scaled_w / src_w
    fy = (focus_y + 0.5) * scaled_h / src_h

    def origin(centre, size, limit):
        # floor(centre - size / 2) equals focus - size // 2 at scale 1; the two bounds keep the focus
        # pixel inside even for a 1px profile, and clamping to the image cannot push it out.
        start = int(math.floor(centre - size / 2.0))
        start = min(max(start, int(math.floor(centre)) - size + 1), int(math.floor(centre)))
        return min(max(start, 0), limit - size)

    x = origin(fx, out_w, scaled_w)
    y = origin(fy, out_h, scaled_h)
    focus_out = (int(fx - x), int(fy - y))
    return {"scale": scale, "scaled_width": scaled_w, "scaled_height": scaled_h, "x": x, "y": y,
            "width": out_w, "height": out_h, "focus_after": {"x": focus_out[0], "y": focus_out[1]},
            "upscaled": scale > 1.0}
'''

_namespace: dict = {}
exec(PLANNER, _namespace)
SOCIAL_PROFILES = _namespace["SOCIAL_PROFILES"]
resolve_profiles = _namespace["resolve_profiles"]
plan_crop = _namespace["plan_crop"]


def VALIDATE(params):
    """Checks that need no GIMP, run by the server before the recipe is sent."""
    if bool(params["input_path"]) == (params["image_id"] is not None):
        raise ValueError("recipe social_crop needs exactly one of input_path or image_id")
    resolve_profiles(params["profiles"])
    if params["fit"] not in ("cover", "crop"):
        raise ValueError("recipe social_crop parameter 'fit' must be 'cover' or 'crop'")
    if str(params["format"]).lower().lstrip(".") not in ("png", "jpg", "jpeg", "webp"):
        raise ValueError("recipe social_crop parameter 'format' must be png, jpg or webp")
    focus = params["focus"]
    if focus is not None and (not isinstance(focus, dict) or set(focus) != {"x", "y"}
                              or any(type(focus[k]) is not int or focus[k] < 0 for k in ("x", "y"))):
        raise ValueError("recipe social_crop parameter 'focus' must be {x, y} with non-negative integer pixels")

SOURCE = PLANNER + r'''
import os, hashlib

def social_crop():
    src_path, image_id = params["input_path"], params["image_id"]
    if bool(src_path) == (image_id is not None):
        raise ValueError("give exactly one of input_path or image_id")
    fmt = str(params["format"]).lower().lstrip(".")
    fmt = {"jpeg": "jpg"}.get(fmt, fmt)
    if fmt not in ("png", "jpg", "webp"):
        raise ValueError("format must be png, jpg or webp")
    profiles = resolve_profiles(params["profiles"])
    out_dir = os.path.abspath(os.path.expanduser(params["output_dir"]))
    if src_path:
        src_path = os.path.abspath(os.path.expanduser(src_path))
        if not os.path.isfile(src_path):
            raise ValueError(f"input_path does not exist: {src_path}")
        stem = os.path.splitext(os.path.basename(src_path))[0]
    else:
        stem = f"image-{image_id}"
    targets = [os.path.join(out_dir, f"{stem}-{name}.{fmt}") for name, _w, _h in profiles]
    if src_path and any(os.path.normcase(t) == os.path.normcase(src_path) for t in targets):
        raise ValueError("an output would overwrite the source")
    if not params["overwrite"] and any(os.path.exists(t) for t in targets):
        raise ValueError("output already exists; choose another output_dir or set overwrite=true")

    def pixels(layer, w, h):
        return bytes(layer.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0, "R'G'B'A u8", Gegl.AbyssPolicy.CLAMP))

    base = None
    try:
        if src_path:
            base = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(src_path))
            if base is None:
                raise RuntimeError(f"could not load {src_path}")
        else:
            base = image_by_id(image_id).duplicate()  # the open document is never changed
        if len(base.get_layers()) > 1:
            base.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
        layer = base.get_layers()[0]
        if not layer.has_alpha():
            layer.add_alpha()
        layer.resize_to_image_size()
        src_w, src_h = base.get_width(), base.get_height()
        focus = params["focus"] or {"x": src_w // 2, "y": src_h // 2}
        if not isinstance(focus, dict) or type(focus.get("x")) is not int or type(focus.get("y")) is not int:
            raise ValueError("focus must be {x, y} with integer source pixels")
        # Plan every profile before writing anything, so a refusal leaves no partial output.
        plans = [(name, plan_crop(src_w, src_h, w, h, focus["x"], focus["y"], params["fit"], params["allow_upscale"]))
                 for name, w, h in profiles]
        os.makedirs(out_dir, exist_ok=True)
        outputs = []
        for index, ((name, plan), dst) in enumerate(zip(plans, targets)):
            globals().get("checkpoint", lambda *a, **k: None)(index / len(plans), f"{name} {plan['width']}x{plan['height']}")
            dup = base.duplicate()
            reopened = None
            try:
                if (plan["scaled_width"], plan["scaled_height"]) != (src_w, src_h):
                    dup.scale(plan["scaled_width"], plan["scaled_height"])
                dup.crop(plan["width"], plan["height"], plan["x"], plan["y"])
                dup_layer = dup.get_layers()[0]
                expected = pixels(dup_layer, plan["width"], plan["height"])
                export_with(dup, dst, params["export_options"] or {})
                reopened = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(dst))
                if reopened is None:
                    raise RuntimeError(f"could not reopen {dst}")
                mw, mh = reopened.get_width(), reopened.get_height()
                if (mw, mh) != (plan["width"], plan["height"]):
                    raise RuntimeError(f"{name}: exported {mw}x{mh}, expected {plan['width']}x{plan['height']}")
                if fmt == "png":
                    got_layer = reopened.get_layers()[0]
                    if not got_layer.has_alpha():
                        got_layer.add_alpha()
                    got = pixels(got_layer, mw, mh)
                    if hashlib.sha256(got).hexdigest() != hashlib.sha256(expected).hexdigest():
                        raise RuntimeError(f"{name}: exported pixels differ from the cropped image")
                    pixel_check = "exact RGBA match"
                else:
                    pixel_check = f"skipped: {fmt} is lossy"
                outputs.append({"profile": name, "path": dst, "bytes": os.path.getsize(dst),
                                "measured": {"width": mw, "height": mh}, "pixel_check": pixel_check, **plan})
            finally:
                dup.delete()
                if reopened is not None:
                    reopened.delete()
        return {"source": {"width": src_w, "height": src_h, "focus": focus}, "fit": params["fit"],
                "format": fmt, "outputs": outputs}
    finally:
        if base is not None:
            base.delete()

result = social_crop()
'''
