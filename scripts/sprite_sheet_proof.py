"""Real GIMP MCP stdio proof. Usage: python scripts/sprite_sheet_proof.py OUT_DIR."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

FIXTURE = r'''
import os
paths = []
for frame in range(6):
    image = Gimp.Image.new(64, 64, Gimp.ImageBaseType.RGB)
    layer = Gimp.Layer.new(image, "Clockwork bot", 64, 64, Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
    image.insert_layer(layer, None, 0)
    layer.fill(Gimp.FillType.TRANSPARENT)
    def rect(x, y, w, h, color):
        image.select_rectangle(Gimp.ChannelOps.REPLACE, x, y, w, h)
        Gimp.context_set_foreground(make_color(color))
        layer.edit_fill(Gimp.FillType.FOREGROUND)
    Gimp.context_push()
    Gimp.context_set_antialias(False)
    try:
        rect(29, 8, 6, 8, "#18344a")
        rect(29, 8, 6, 4, ["#fbbf24", "#f97316", "#ef4444", "#f97316", "#fbbf24", "#a3e635"][frame])
        rect(16, 16, 32, 22, "#18344a")
        rect(19, 19, 26, 16, "#67e8f9")
        rect(22, 24 if frame != 3 else 27, 6, 6 if frame != 3 else 2, "#18344a")
        rect(36, 24 if frame != 3 else 27, 6, 6 if frame != 3 else 2, "#18344a")
        rect(20, 38, 24, 14, "#18344a")
        rect(23, 40, 18, 9, "#14b8a6")
        rect(12, 40, 8, 10, "#18344a")
        rect(44, 40, 8, 10, "#18344a")
        rect(20, 52, 10, 6, "#18344a")
        rect(34, 52, 10, 6, "#18344a")
        # Composite a translucent status light over the body colour.
        rect(31, 43, 2, 2, "rgba(255,255,255,0.5)")
        Gimp.Selection.none(image)
        path = os.path.join(out_dir, f"bot-{frame+1:02}.png")
        export_with(image, path, {"compression": 9, "bkgd": False, "phys": False, "time": False, "include-thumbnail": False})
        paths.append(path)
    finally:
        Gimp.context_pop()
        image.delete()
result = {"paths": paths}
'''

# Mixed canvases with transparent borders: the case a grid cannot pack.
ATLAS_FIXTURE = r'''
import os
specs = [("ship", 96, 48, (8, 6, 80, 36), "#38bdf8"), ("rock-big", 64, 64, (4, 4, 56, 56), "#a8a29e"),
         ("rock-small", 24, 24, (2, 2, 20, 20), "#78716c"), ("laser", 8, 32, (2, 0, 4, 32), "#f43f5e"),
         ("coin", 16, 16, (0, 0, 16, 16), "#facc15"), ("blank", 12, 12, None, "#000000"),
         ("banner", 120, 20, (0, 4, 120, 12), "#a3e635")]
paths = []
for name, w, h, box, color in specs:
    image = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
    layer = Gimp.Layer.new(image, name, w, h, Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
    image.insert_layer(layer, None, 0)
    layer.fill(Gimp.FillType.TRANSPARENT)
    Gimp.context_push()
    Gimp.context_set_antialias(False)
    try:
        if box:
            image.select_rectangle(Gimp.ChannelOps.REPLACE, *box)
            Gimp.context_set_foreground(make_color(color))
            layer.edit_fill(Gimp.FillType.FOREGROUND)
            image.select_rectangle(Gimp.ChannelOps.REPLACE, box[0], box[1], 1, 1)
            Gimp.context_set_foreground(make_color("rgba(255,255,255,0.5)"))
            layer.edit_fill(Gimp.FillType.FOREGROUND)
        Gimp.Selection.none(image)
        path = os.path.join(out_dir, name + ".png")
        export_with(image, path, {"compression": 9, "bkgd": False, "phys": False, "time": False, "include-thumbnail": False})
        paths.append(path)
    finally:
        Gimp.context_pop()
        image.delete()
result = {"paths": paths}
'''


def _separated(frames, padding):
    rects = [(f["frame"]["x"], f["frame"]["y"], f["frame"]["w"], f["frame"]["h"]) for f in frames.values()]
    for i, (x, y, w, h) in enumerate(rects):
        for x2, y2, w2, h2 in rects[i + 1:]:
            if not (x + w + padding <= x2 or x2 + w2 + padding <= x or y + h + padding <= y2 or y2 + h2 + padding <= y):
                return False
    return True


async def run(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    repo = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(repo / "src"))
    server = StdioServerParameters(command=sys.executable, args=["-m", "gimp_agent_mcp.cli", "serve"], cwd=str(repo), env=env)
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(name, args, error=False):
                response = await session.call_tool(name, args, read_timeout_seconds=600)
                assert bool(response.is_error) == error, response
                if error:
                    return " ".join(c.text for c in response.content if c.type == "text").splitlines()[0]
                data = response.structured_content
                if data is None:
                    data = json.loads(next(c.text for c in response.content if c.type == "text"))
                return data

            status = await call("gimp_status", {})
            if not status.get("connected"):
                await call("gimp_launch", {"mode": "headless"})
            catalogue = await session.call_tool("gimp_list_recipes", {})
            assert "sprite_sheet_pack" in str(catalogue)
            fixtures = await call("gimp_run_python", {"code": "out_dir = " + repr(str(output)) + "\n" + FIXTURE})
            paths = fixtures["result"]["paths"]
            params = {"input_paths": paths, "output_path": str(output / "bot-sheet.png"), "columns": 4, "keep_open": True}
            result = (await call("gimp_run_recipe", {"name": "sprite_sheet_pack", "params": params}))["result"]
            assert result["verification"] == "exact RGBA match" and result["frames"] == 6, result
            assert result["size"] == {"w": 256, "h": 128} and result["footDriftPx"] == 0, result
            rendered = await session.call_tool("gimp_render", {"image_id": result["image_id"], "max_size": 1024})
            assert not rendered.is_error, rendered
            for content in rendered.content:
                if content.type == "image":
                    (output / "preview.png").write_bytes(base64.b64decode(content.data))
            # Slice then repack in returned row-major order: identical visible cells.
            sliced = (await call("gimp_run_recipe", {"name": "sprite_sheet_slice", "params": {
                "input_path": result["output_path"], "output_dir": str(output / "sliced"), "tile_width": 64, "tile_height": 64}}))["result"]
            assert sliced["tiles"] == 6 and sliced["rows"] == 2 and sliced["cols"] == 4, sliced
            repacked = (await call("gimp_run_recipe", {"name": "sprite_sheet_pack", "params": {
                "input_paths": sliced["files"], "output_path": str(output / "roundtrip.png"), "columns": 4}}))["result"]
            assert repacked["bounds"] == result["bounds"], repacked
            # Compare decoded exported sheet bytes through GIMP, not compressed PNG bytes.
            compare = await call("gimp_run_python", {"code": "compare_paths = " + repr([result["output_path"], repacked["output_path"]]) + r'''
import hashlib
hashes = []
for path in compare_paths:
    im = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(path))
    try:
        data = bytes(im.get_layers()[0].get_buffer().get(Gegl.Rectangle.new(0,0,256,128), 1.0, "R'G'B'A u8", Gegl.AbyssPolicy.NONE))
        hashes.append(hashlib.sha256(data).hexdigest())
    finally:
        im.delete()
result = {"hashes": hashes, "equal": hashes[0] == hashes[1]}
'''})
            assert compare["result"]["equal"], compare
            failures = {}
            for label, patch in [("zero columns", {"columns": 0}), ("empty inputs", {"input_paths": []}),
                                 ("mixed canvases", {"input_paths": [paths[0], result["output_path"]]}),
                                 ("duplicate basenames", {"input_paths": [paths[0], paths[0]]})]:
                failures[label] = await call("gimp_run_recipe", {"name": "sprite_sheet_pack", "params": {
                    **params, "output_path": str(output / (label.replace(" ", "-") + ".png")), **patch}}, error=True)
            failures["overwrite refused"] = await call("gimp_run_recipe", {"name": "sprite_sheet_pack", "params": params}, error=True)
            # Four-sided margins: 256x128 with 64px cells and a 1px border fits only 3x1.
            margin = (await call("gimp_run_recipe", {"name": "sprite_sheet_slice", "params": {
                "input_path": result["output_path"], "output_dir": str(output / "margin"), "tile_width": 64, "tile_height": 64, "margin": 1, "skip_empty": False}}))["result"]
            assert (margin["cols"], margin["rows"], margin["tiles"]) == (3, 1, 3), margin
            # Margin and spacing on the packer round-trip through the slicer's matching parameters.
            spaced = (await call("gimp_run_recipe", {"name": "sprite_sheet_pack", "params": {
                **params, "output_path": str(output / "bot-spaced.png"), "margin": 1, "spacing": 2, "keep_open": False}}))["result"]
            assert spaced["size"] == {"w": 2 + 4 * 64 + 3 * 2, "h": 2 + 2 * 64 + 2}, spaced
            assert spaced["bounds"] == result["bounds"], spaced
            unspaced = (await call("gimp_run_recipe", {"name": "sprite_sheet_slice", "params": {
                "input_path": spaced["output_path"], "output_dir": str(output / "spaced"), "tile_width": 64, "tile_height": 64,
                "margin": 1, "spacing": 2}}))["result"]
            assert unspaced["tiles"] == 6, unspaced
            respaced = (await call("gimp_run_recipe", {"name": "sprite_sheet_pack", "params": {
                "input_paths": unspaced["files"], "output_path": str(output / "spaced-roundtrip.png"), "columns": 4}}))["result"]
            assert respaced["bounds"] == result["bounds"], respaced

            # Mixed-size atlas: trimmed, padded, verified, and loadable as standard atlas JSON.
            atlas_dir = output / "atlas-src"
            atlas_dir.mkdir(exist_ok=True)
            sprites = (await call("gimp_run_python", {"code": "out_dir = " + repr(str(atlas_dir)) + "\n" + ATLAS_FIXTURE}))["result"]["paths"]
            atlas = (await call("gimp_run_recipe", {"name": "sprite_atlas_pack", "params": {
                "input_paths": sprites, "output_path": str(output / "atlas.png"), "padding": 2, "trim": True, "max_width": 256}}))["result"]
            assert atlas["verification"] == "exact RGBA match, transparent padding" and atlas["frames"] == 7, atlas
            data = json.loads(Path(atlas["atlas_path"]).read_text(encoding="utf-8"))
            frames = data["frames"]
            assert frames["ship.png"]["spriteSourceSize"] == {"x": 8, "y": 6, "w": 80, "h": 36}, frames["ship.png"]
            assert frames["ship.png"]["trimmed"] and not frames["coin.png"]["trimmed"], frames
            assert frames["blank.png"]["frame"]["w"] == 1 and frames["blank.png"]["alphaBounds"] is None, frames["blank.png"]
            assert frames["banner.png"]["sourceSize"] == {"w": 120, "h": 20}, frames["banner.png"]
            assert _separated(frames, 2) and data["meta"]["size"]["w"] <= 256, data["meta"]
            untrimmed = (await call("gimp_run_recipe", {"name": "sprite_atlas_pack", "params": {
                "input_paths": sprites, "output_path": str(output / "atlas-pot.png"), "padding": 1, "max_width": 256, "power_of_two": True}}))["result"]
            w, h = untrimmed["size"]["w"], untrimmed["size"]["h"]
            assert w & (w - 1) == 0 and h & (h - 1) == 0, untrimmed
            assert all(not f["trimmed"] for f in json.loads(Path(untrimmed["atlas_path"]).read_text(encoding="utf-8"))["frames"].values())
            atlas_base = {"input_paths": sprites, "output_path": str(output / "atlas-err.png")}
            for label, patch in [("too wide for max_width", {"max_width": 64}), ("non power-of-two max_width", {"max_width": 300, "power_of_two": True}),
                                 ("atlas overwrite refused", {"output_path": atlas["output_path"]})]:
                failures[label] = await call("gimp_run_recipe", {"name": "sprite_atlas_pack", "params": {**atlas_base, **patch}}, error=True)
            report = {"transport": "MCP stdio", "pack": result, "roundtrip": compare["result"], "expected_errors": failures, "margin_grid": [3, 1],
                      "spaced_pack": {k: spaced[k] for k in ("size", "margin", "spacing", "sheetBytes")},
                      "atlas": {k: atlas[k] for k in ("size", "occupancy", "sourceBytes", "atlasBytes", "placements")},
                      "atlas_power_of_two": {k: untrimmed[k] for k in ("size", "occupancy", "atlasBytes")}}
            (output / "proof.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/sprite_sheet_proof.py OUTPUT_DIRECTORY")
    asyncio.run(run(Path(sys.argv[1]).resolve()))
