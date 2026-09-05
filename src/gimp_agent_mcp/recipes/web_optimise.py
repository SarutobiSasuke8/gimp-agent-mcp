"""Scale an image for the web and export within a file-size budget."""

DESCRIPTION = "Scale to a maximum edge and export as WebP/JPEG/PNG, lowering quality until the file fits a size budget"

PARAMS = {
    "input_path": {"type": "string", "required": True, "description": "Source image"},
    "output_path": {"type": "string", "required": True, "description": "Destination; .webp, .jpg or .png"},
    "max_edge": {"type": "integer", "default": 1600, "description": "Longest side after scaling; never upscales"},
    "budget_kb": {"type": "integer", "default": 0, "description": "Target maximum size in KB; 0 = no budget"},
    "quality": {"type": "integer", "default": 85, "description": "Starting quality 1..100 for WebP/JPEG"},
    "min_quality": {"type": "integer", "default": 40, "description": "Lowest quality tried when chasing the budget"},
    "strip_metadata": {"type": "boolean", "default": True, "description": "Drop EXIF/XMP where the exporter supports it"},
}

SOURCE = r'''
import os

src = os.path.abspath(os.path.expanduser(params["input_path"]))
dst = os.path.abspath(os.path.expanduser(params["output_path"]))
ext = os.path.splitext(dst)[1].lower()
max_edge = int(params["max_edge"])
budget = int(params["budget_kb"]) * 1024

image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(src))
if image is None:
    raise RuntimeError(f"could not load {src}")
try:
    if len(image.get_layers()) > 1:
        image.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
    w, h = image.get_width(), image.get_height()
    if max(w, h) > max_edge:
        s = max_edge / float(max(w, h))
        image.scale(max(1, int(round(w * s))), max(1, int(round(h * s))))

    def options_for(q):
        if ext == ".webp":
            o = {"quality": float(q), "lossless": False}
        elif ext in (".jpg", ".jpeg"):
            o = {"quality": q / 100.0}
        else:
            o = {"compression": 9}
        return o

    def try_export(q):
        try:
            export_with(image, dst, options_for(q))
        except Exception as exc:
            # Fall back to GIMP defaults if an option name is unknown on this GIMP build.
            if "unknown export option" not in str(exc):
                raise
            export_with(image, dst, {})
        return os.path.getsize(dst)

    q = int(params["quality"])
    size = try_export(q)
    tried = [(q, size)]
    while budget and size > budget and q > int(params["min_quality"]) and ext != ".png":
        q = max(int(params["min_quality"]), q - 10)
        size = try_export(q)
        tried.append((q, size))
finally:
    image.delete()

result = {
    "output_path": dst,
    "bytes": size,
    "kb": round(size / 1024, 1),
    "within_budget": (not budget) or size <= budget,
    "attempts": tried,
}
'''
