"""Social crops at common sizes, using gimp_canvas crop arguments.

There is no social-profile recipe and no focus flag. This script builds the
real ``gimp_canvas`` arguments: action ``crop``, plus integer ``width``,
``height``, ``x`` and ``y``. Those become the PDB procedure ``gimp-image-crop``
(``new-width``, ``new-height``, ``offx``, ``offy``).

Run from a checkout (no GIMP required):

    python examples/social_crops.py

Expected output
---------------
JSON on stdout, exit code 0. For a 2400 by 1800 source and focus pixel
(1680, 420):

- Each common size that fits the source has one ``gimp_canvas`` crop call.
  ``x`` and ``y`` are the top-left of the kept rectangle. The focus pixel lies
  inside that rectangle. The crop is centred on the focus with integer
  division, then clamped so it stays inside the source. Clamping still leaves
  the focus inside the crop.
- A size taller or wider than the source is listed under ``refused`` and has
  no call. ``gimp_canvas`` crop does not scale.
- When GIMP accepts a call, the returned image width and height equal the
  requested width and height. This script does not launch GIMP, so it does not
  return an image id or pixel colours.

The sizes below are conventional pixel targets used by this example. They are
not stored presets.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gimp_agent_mcp.server import gimp_canvas  # noqa: E402

# Conventional export sizes. Names are labels in this example, not tool arguments.
COMMON_SIZES = (
    {"name": "open_graph", "width": 1200, "height": 630, "use": "Open Graph / link preview, 1.91:1"},
    {"name": "x_landscape", "width": 1600, "height": 900, "use": "X landscape post, 16:9"},
    {"name": "instagram_square", "width": 1080, "height": 1080, "use": "Instagram square feed"},
    {"name": "instagram_portrait", "width": 1080, "height": 1350, "use": "Instagram portrait feed, 4:5"},
    {"name": "story_reel", "width": 1080, "height": 1920, "use": "Story, reel or short vertical video, 9:16"},
    {"name": "youtube_thumbnail", "width": 1280, "height": 720, "use": "YouTube thumbnail, 16:9"},
)

SOURCE_W = 2400
SOURCE_H = 1800
FOCUS_X = 1680
FOCUS_Y = 420


def crop_origin(src_w: int, src_h: int, width: int, height: int, focus_x: int, focus_y: int) -> tuple[int, int]:
    """Top-left for gimp_canvas crop so the focus pixel stays inside the source."""
    if width < 1 or height < 1:
        raise ValueError("width and height must be positive")
    if width > src_w or height > src_h:
        raise ValueError(f"crop {width}x{height} does not fit {src_w}x{src_h}; gimp_canvas crop does not scale")
    if not (0 <= focus_x < src_w and 0 <= focus_y < src_h):
        raise ValueError("focus point is outside the source image")
    x = min(max(focus_x - width // 2, 0), src_w - width)
    y = min(max(focus_y - height // 2, 0), src_h - height)
    return x, y


def focus_inside(x: int, y: int, width: int, height: int, focus_x: int, focus_y: int) -> bool:
    return x <= focus_x < x + width and y <= focus_y < y + height


def canvas_call(width: int, height: int, x: int, y: int) -> dict[str, object]:
    arguments = {
        "image_id": "<image id from gimp_open or gimp_list_images>",
        "action": "crop",
        "width": width,
        "height": height,
        "x": x,
        "y": y,
    }
    allowed = set(inspect.signature(gimp_canvas).parameters)
    unknown = set(arguments) - allowed
    if unknown:
        raise SystemExit(f"invented gimp_canvas arguments: {sorted(unknown)}")
    return {"tool": "gimp_canvas", "arguments": arguments}


def main() -> int:
    crops = []
    refused = []
    for spec in COMMON_SIZES:
        width, height = spec["width"], spec["height"]
        try:
            x, y = crop_origin(SOURCE_W, SOURCE_H, width, height, FOCUS_X, FOCUS_Y)
        except ValueError as exc:
            refused.append({**spec, "reason": str(exc)})
            continue
        if not focus_inside(x, y, width, height, FOCUS_X, FOCUS_Y):
            raise SystemExit(f"focus left the {spec['name']} crop")
        crops.append(
            {
                **spec,
                "call": canvas_call(width, height, x, y),
                "focus_in_source": {"x": FOCUS_X, "y": FOCUS_Y},
                "focus_after_crop": {"x": FOCUS_X - x, "y": FOCUS_Y - y},
                "expected_image_size_when_gimp_accepts": {"width": width, "height": height},
            }
        )

    # A corner focus must clamp and still remain inside the open_graph crop.
    corner_x, corner_y = crop_origin(SOURCE_W, SOURCE_H, 1200, 630, 10, 10)
    if (corner_x, corner_y) != (0, 0) or not focus_inside(corner_x, corner_y, 1200, 630, 10, 10):
        raise SystemExit("corner focus was not kept in frame")

    fitted = {item["name"] for item in crops}
    if "story_reel" in fitted or "open_graph" not in fitted:
        raise SystemExit(f"unexpected fit set: {sorted(fitted)}")

    report = {
        "expected_output": (
            "Crop calls for every common size that fits 2400x1800, each keeping "
            "focus (1680, 420) inside the rectangle. story_reel 1080x1920 is refused "
            "because 1920 is taller than 1800. No image is opened."
        ),
        "needs_gimp": False,
        "source": {"width": SOURCE_W, "height": SOURCE_H, "focus": {"x": FOCUS_X, "y": FOCUS_Y}},
        "procedure": "gimp-image-crop",
        "crops": crops,
        "refused": refused,
        "corner_focus_open_graph": {"focus": {"x": 10, "y": 10}, "x": corner_x, "y": corner_y},
        "after_gimp_accepts": (
            "gimp_image_info width and height match the requested crop. "
            "gimp_measure(kind='color', x=focus_after_crop.x, y=focus_after_crop.y) "
            "reads the focus pixel on the cropped image. Export with gimp_export; "
            "the path extension selects the format."
        ),
    }
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
