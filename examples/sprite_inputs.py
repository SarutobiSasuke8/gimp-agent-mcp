"""Sprite inputs: file paths, open layers, and atlas placement.

Run from a checkout (no GIMP required):

    python examples/sprite_inputs.py

Expected output
---------------
JSON on stdout, exit code 0. It contains:

- ``sprite_sheet_pack`` parameters resolved by ``recipes.resolve_params`` for
  ordered PNG paths. For six 64 by 64 frames, ``columns`` 4, ``margin`` 1 and
  ``spacing`` 2, the sheet is 264 by 132. That is the same formula the recipe
  uses inside GIMP: ``2 * margin + columns * frame + (columns - 1) * spacing``
  on each axis, with two rows because six frames and four columns leave a
  second row. Cell origins start at ``(margin, margin)``.
- ``sprite_atlas_pack`` parameters for PNG paths, and a second call that uses
  ``input_layer_ids`` instead. Defaults are padding 2, trim false, max_width
  2048. The exclusive choice (paths or layer ids, not both and not neither) is
  enforced by ``resolve_params`` (the recipe's ``VALIDATE``) and again inside GIMP.
- Placements from ``sprite_atlas_pack.pack_rects`` for seven mixed canvases at
  padding 2 and max_width 256. Rectangles do not overlap, stay at least
  ``padding`` pixels apart, and do not touch the atlas edge. The same sizes
  pack to the same coordinates every time. ``trim`` is not applied here: trim
  uses measured alpha bounds, which only GIMP can read.

This script does not write a PNG, XCF or atlas JSON. Those files, and the
exact RGBA check, need GIMP. Use ``python scripts/sprite_sheet_proof.py OUT_DIR``
for that proof.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gimp_agent_mcp import recipes  # noqa: E402

FRAME = 64
FRAMES = 6
COLUMNS = 4
MARGIN = 1
SPACING = 2

# Full canvases from the mixed-size fixture in scripts/sprite_sheet_proof.py.
# trim would shrink these to alpha bounds; this example packs the full canvases.
ATLAS_SIZES = [
    ("ship.png", 96, 48),
    ("rock-big.png", 64, 64),
    ("rock-small.png", 24, 24),
    ("laser.png", 8, 32),
    ("coin.png", 16, 16),
    ("blank.png", 12, 12),
    ("banner.png", 120, 20),
]


def sheet_size(frame: int, count: int, columns: int, margin: int, spacing: int) -> dict[str, int]:
    """Grid size used by sprite_sheet_pack once every frame is known to be `frame` px square."""
    columns = min(columns, count)
    rows = (count + columns - 1) // columns
    width = 2 * margin + columns * frame + (columns - 1) * spacing
    height = 2 * margin + rows * frame + (rows - 1) * spacing
    cells = [
        {
            "index": i,
            "x": margin + (i % columns) * (frame + spacing),
            "y": margin + (i // columns) * (frame + spacing),
            "w": frame,
            "h": frame,
        }
        for i in range(count)
    ]
    return {"columns": columns, "rows": rows, "width": width, "height": height, "cells": cells}


def packing_ok(sizes: list[tuple[int, int]], positions: list[tuple[int, int]], width: int, height: int, padding: int, max_width: int) -> bool:
    if width > max_width or width < 1 or height < 1:
        return False
    rects = [(x, y, w, h) for (x, y), (w, h) in zip(positions, sizes, strict=True)]
    for i, (x, y, w, h) in enumerate(rects):
        if x < padding or y < padding or x + w + padding > width or y + h + padding > height:
            return False
        for x2, y2, w2, h2 in rects[i + 1 :]:
            separated = x + w + padding <= x2 or x2 + w2 + padding <= x or y + h + padding <= y2 or y2 + h2 + padding <= y
            if not separated:
                return False
    return True


def main() -> int:
    pack = recipes.resolve_params(
        "sprite_sheet_pack",
        {
            "input_paths": [f"frames/bot-{i:02}.png" for i in range(1, FRAMES + 1)],
            "output_path": "out/bot-sheet.png",
            "columns": COLUMNS,
            "margin": MARGIN,
            "spacing": SPACING,
        },
    )
    grid = sheet_size(FRAME, len(pack["input_paths"]), pack["columns"], pack["margin"], pack["spacing"])

    atlas_files = recipes.resolve_params(
        "sprite_atlas_pack",
        {
            "input_paths": ["sprites/ship.png", "sprites/rock.png", "sprites/coin.png"],
            "output_path": "out/sprites.png",
            "padding": 2,
            "trim": False,
            "max_width": 256,
        },
    )
    atlas_layers = recipes.resolve_params(
        "sprite_atlas_pack",
        {"input_layer_ids": [7, 8], "output_path": "out/open-layers.png"},
    )

    padding = 2
    max_width = 256
    sizes = [(w, h) for _name, w, h in ATLAS_SIZES]
    positions, width, height = recipes.get_recipe("sprite_atlas_pack").pack_rects(sizes, max_width, padding)
    again, width2, height2 = recipes.get_recipe("sprite_atlas_pack").pack_rects(sizes, max_width, padding)
    if (positions, width, height) != (again, width2, height2):
        raise SystemExit("pack_rects was not deterministic")
    if not packing_ok(sizes, positions, width, height, padding, max_width):
        raise SystemExit("pack_rects broke padding or overlap rules")

    report = {
        "expected_output": (
            "Resolved sprite_sheet_pack and sprite_atlas_pack parameters, a 264x132 grid "
            "for six 64px frames with margin 1 and spacing 2, and deterministic atlas "
            "placements at padding 2. No PNG, XCF or JSON is written."
        ),
        "needs_gimp": False,
        "sprite_sheet_pack": {
            "tool": "gimp_run_recipe",
            "arguments": {"name": "sprite_sheet_pack", "params": pack},
            "frame_px": FRAME,
            "sheet": grid,
            "outputs_when_gimp_runs": ["out/bot-sheet.png", "out/bot-sheet.json", "out/bot-sheet.xcf"],
            "verification_when_gimp_runs": "exact RGBA match; margins, gutters and unused cells transparent",
        },
        "sprite_atlas_pack_files": {
            "tool": "gimp_run_recipe",
            "arguments": {"name": "sprite_atlas_pack", "params": atlas_files},
            "note": "Pass input_paths or input_layer_ids, not both. The recipe body rejects any other combination.",
        },
        "sprite_atlas_pack_open_layers": {
            "tool": "gimp_run_recipe",
            "arguments": {"name": "sprite_atlas_pack", "params": atlas_layers},
            "note": "Layer ids must already be open raster layers. Names become atlas keys and must be unique. Source documents are not modified.",
        },
        "atlas_placements": {
            "padding": padding,
            "max_width": max_width,
            "trim": False,
            "size": {"w": width, "h": height},
            "frames": {
                name: {"x": x, "y": y, "w": w, "h": h}
                for (name, w, h), (x, y) in zip(ATLAS_SIZES, positions, strict=True)
            },
        },
    }
    if grid["width"] != 264 or grid["height"] != 132:
        raise SystemExit(f"unexpected sheet size {grid['width']}x{grid['height']}")
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
