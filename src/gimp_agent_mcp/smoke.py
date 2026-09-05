"""End-to-end smoke test against a real GIMP. Used by `gimp-agent-mcp smoke` and tests/test_live.py."""

from __future__ import annotations

import base64
import os
import struct
import tempfile
import time
from pathlib import Path

from . import recipes
from .bridge_client import BridgeClient, BridgeError, launch_gimp


def _png_size(data: bytes) -> tuple[int, int]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError("render is not a PNG")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _recipe_code(name: str, params: dict) -> str:
    module = recipes.get_recipe(name)
    return "params = " + repr(recipes.resolve_params(name, params)) + "\n" + module.SOURCE


def run_smoke(mode: str = "headless", keep: bool = False, verbose: bool = True, segmentation: bool = False) -> int:
    log = print if verbose else (lambda *a, **k: None)
    client = BridgeClient()
    started_here = False
    if client.ping() is None:
        log(f"launching GIMP ({mode})...")
        launch_gimp(mode=mode, wait_seconds=120, client=client)
        started_here = True
    info = client.call("ping")
    log(f"bridge ok: GIMP {info['gimp_version']} python {info['python_version']} mode={info['mode']}")

    tmpdir = Path(tempfile.mkdtemp(prefix="gimp-agent-smoke-"))
    failures: list[str] = []

    def check(label: str, fn):
        t0 = time.time()
        try:
            out = fn()
            log(f"  ok   {label} ({time.time() - t0:.1f}s)")
            return out
        except (BridgeError, AssertionError, KeyError, RuntimeError, TypeError, ValueError) as exc:
            failures.append(f"{label}: {exc}")
            log(f"  FAIL {label}: {exc}")
            return None

    # 1. new image + info
    created = check("new_image", lambda: client.call("new_image", {"width": 300, "height": 200, "fill": "#ff8800"}))
    image_id = created["image"]["id"] if created else None
    layer_id = created["layer_id"] if created else None

    def _info():
        i = client.call("image_info", {"image_id": image_id})
        assert i["width"] == 300 and i["height"] == 200, i
        assert i["layers"][0]["id"] == layer_id
        return i

    check("image_info", _info)

    # 2. PDB search/describe/call with enum by nick
    def _pdb():
        s = client.call("pdb_search", {"query": "image scale", "limit": 5})
        assert any(r["name"] == "gimp-image-scale" for r in s["results"]), s
        d = client.call("pdb_describe", {"name": "gimp-image-rotate"})
        rot = [a for a in d["arguments"] if a["name"] == "rotate-type"][0]
        assert "degrees90" in rot.get("choices", []), rot
        client.call("pdb_call", {"name": "gimp-image-scale", "args": {"image": image_id, "new_width": 150, "new_height": 100}})
        i = client.call("image_info", {"image_id": image_id})
        assert i["width"] == 150, i
        return d

    check("pdb search/describe/call", _pdb)

    # 3. GEGL filter merge + append + effect edit
    def _filter():
        s = client.call("filter_search", {"query": "dropshadow"})
        assert any(r["op"] == "gegl:dropshadow" for r in s["results"]), s
        d = client.call("filter_describe", {"op": "gegl:dropshadow"})
        assert "grow-radius" in [p["name"] for p in d["properties"]]
        client.call("apply_filter", {"layer_id": layer_id, "op": "gegl:gaussian-blur", "params": {"std_dev_x": 3, "std-dev-y": 3}, "mode": "merge"})
        client.call("apply_filter", {"layer_id": layer_id, "op": "gegl:noise-hsv", "params": {"holdness": 2}, "mode": "append"})
        fx = client.call("list_filters_on_layer", {"layer_id": layer_id})
        assert len(fx) == 1 and fx[0]["op"] == "gegl:noise-hsv", fx
        edited = client.call("layer_effect", {"filter_id": fx[0]["id"], "action": "set", "opacity": 0.5, "params": {"hue-distance": 12}})
        assert abs(edited["opacity"] - 0.5) < 1e-6, edited
        client.call("layer_effect", {"filter_id": fx[0]["id"], "action": "delete"})
        assert client.call("list_filters_on_layer", {"layer_id": layer_id}) == []
        return d

    check("filter search/describe/apply/effect edit", _filter)

    # 4. render + measurement
    def _render():
        r = client.call("render", {"image_id": image_id, "max_size": 64})
        w, h = _png_size(base64.b64decode(r["png_base64"]))
        assert max(w, h) == 64, (w, h)
        return r

    check("render", _render)

    def _measure():
        c = client.call("pixel_color", {"layer_id": layer_id, "x": 75, "y": 50})
        assert c["rgba"][3] == 255 and c["rgba"][0] > 200, c
        bb = client.call("alpha_bbox", {"layer_id": layer_id})
        assert not bb["empty"] and bb["width"] == 150 and bb["height"] == 100, bb
        hist = client.call("histogram", {"layer_id": layer_id, "channels": ["value", "red"]})
        assert "mean" in hist["red"], hist
        dom = client.call("dominant_colors", {"layer_id": layer_id, "k": 3})
        assert dom["colors"] and dom["colors"][0]["share"] > 0.5, dom
        return dom

    check("measure (color/bbox/histogram/dominant)", _measure)

    def _big_bbox():
        big = client.call("new_image", {"width": 2600, "height": 1800, "fill": "transparent"})
        bid, blayer = big["image"]["id"], big["layer_id"]
        client.call("select", {"image_id": bid, "mode": "rect", "x": 1900, "y": 1300, "width": 300, "height": 200})
        client.call("exec", {"code": f"Gimp.context_push(); Gimp.context_set_foreground(make_color('#ff0000')); item_by_id({blayer}).edit_fill(Gimp.FillType.FOREGROUND); Gimp.context_pop()"})
        client.call("select", {"image_id": bid, "mode": "none"})
        bb = client.call("alpha_bbox", {"layer_id": blayer})
        client.call("close_image", {"image_id": bid})
        assert (bb["x"], bb["y"], bb["width"], bb["height"]) == (1900, 1300, 300, 200), bb
        return bb

    check("bbox on a 4.7 MP layer is exact", _big_bbox)

    # 5. snapshot + compare render
    def _compare():
        snap = client.call("snapshot", {"image_id": image_id})
        client.call("apply_filter", {"layer_id": layer_id, "op": "gegl:invert-gamma", "params": {}, "mode": "merge"})
        r = client.call("render_compare", {"image_id": image_id, "snapshot_id": snap["snapshot_id"], "panels": "before,after,diff", "max_size": 450})
        w, h = _png_size(base64.b64decode(r["png_base64"]))
        assert w == 450 and r["panels"] == ["before", "after", "diff"], (w, h, r["panels"])
        client.call("drop_snapshot", {"snapshot_id": snap["snapshot_id"]})
        client.call("apply_filter", {"layer_id": layer_id, "op": "gegl:invert-gamma", "params": {}, "mode": "merge"})
        return r

    check("snapshot + render_compare", _compare)

    # 6. selection + mask + layer ops
    def _select_mask():
        b = client.call("select", {"image_id": image_id, "mode": "rect", "x": 10, "y": 10, "width": 50, "height": 30})
        assert b["non_empty"] and b["width"] == 50 and b["height"] == 30, b
        client.call("select", {"image_id": image_id, "mode": "grow", "amount": 5})
        b2 = client.call("select", {"image_id": image_id, "mode": "bounds"})
        assert b2["width"] == 60, b2
        m = client.call("layer_mask", {"layer_id": layer_id, "action": "add", "type": "selection"})
        assert m.get("mask_id"), m
        client.call("layer_mask", {"layer_id": layer_id, "action": "apply"})
        client.call("select", {"image_id": image_id, "mode": "none"})
        bb = client.call("alpha_bbox", {"layer_id": layer_id})
        assert bb["width"] == 60 and bb["height"] == 40, bb
        # mask from raw bytes: right half opaque
        w, h = 150, 100
        gray = bytes(255 if (i % w) >= 75 else 0 for i in range(w * h))
        client.call("set_mask_pixels", {"layer_id": layer_id, "width": w, "height": h, "gray_base64": base64.b64encode(gray).decode(), "apply": True})
        bb = client.call("alpha_bbox", {"layer_id": layer_id})
        assert bb["empty"] or bb["x"] >= 75, bb
        new = client.call("layer", {"action": "new", "image_id": image_id, "name": "fill", "fill": "#2244ff", "position": 1})
        client.call("layer", {"action": "set", "layer_id": new["id"], "opacity": 40.0, "name": "renamed"})
        dup = client.call("layer", {"action": "duplicate", "layer_id": new["id"]})
        client.call("layer", {"action": "delete", "layer_id": dup["id"]})
        info = client.call("image_info", {"image_id": image_id})
        names = [layer["name"] for layer in info["layers"]]
        assert "renamed" in names and len(names) == 2, names
        return info

    check("select / mask / mask pixels / layer ops", _select_mask)

    # 7. text + path
    def _text_path():
        fonts = client.call("list_fonts", {"filter": "", "limit": 5})
        assert fonts["total"] > 0, fonts
        t = client.call("text", {"image_id": image_id, "text": "Hi", "size": 24, "color": "#00ff00", "x": 5, "y": 5})
        assert t["type"] == "GimpTextLayer" and t["text"] == "Hi", t
        t2 = client.call("text", {"layer_id": t["id"], "text": "Hello", "justify": "center"})
        assert t2["text"] == "Hello", t2
        p = client.call("path", {"action": "create", "image_id": image_id, "name": "tri", "strokes": [{"type": "line", "points": [[100, 10], [140, 90], [60, 90]], "closed": True}]})
        assert p["type"] == "GimpPath", p
        client.call("path", {"action": "fill", "path_id": p["id"], "layer_id": layer_id, "color": "#ff00ff"})
        client.call("path", {"action": "stroke", "path_id": p["id"], "layer_id": layer_id, "color": "#000000", "width": 3})
        c = client.call("pixel_color", {"layer_id": layer_id, "x": 100, "y": 70})
        assert c["rgba"][3] > 0, c
        client.call("layer", {"action": "delete", "layer_id": t["id"]})
        return p

    check("text + path", _text_path)

    # 8. python exec with persistent namespace
    def _exec():
        client.call("exec", {"code": f"img = image_by_id({image_id})\nresult = img.get_width()"})
        out = client.call("exec", {"code": "img.get_height()"})
        assert out["result"] == 100, out
        return out

    check("exec (persistent namespace)", _exec)

    # 9. export with options + open
    png_path = str(tmpdir / "smoke.png")
    jpg_path = str(tmpdir / "smoke.jpg")

    def _export():
        r = client.call("export", {"image_id": image_id, "path": png_path})
        assert os.path.getsize(png_path) > 0
        client.call("export_with", {"image_id": image_id, "path": jpg_path, "options": {"quality": 0.5}})
        assert os.path.getsize(jpg_path) > 0
        try:
            client.call("export_with", {"image_id": image_id, "path": jpg_path, "options": {"bogus": 1}})
            raise AssertionError("expected an unknown-option error")
        except BridgeError as exc:
            assert "unknown export option" in str(exc), exc
        opened = client.call("open", {"path": png_path})
        assert opened["width"] == 150
        client.call("close_image", {"image_id": opened["id"]})
        return r

    check("export (+options) / open / close", _export)

    # 10. recipes
    def _recipe_sticker():
        out_path = str(tmpdir / "sticker.png")
        out = client.call("exec", {"code": _recipe_code("telegram_sticker", {"input_path": png_path, "output_path": out_path})}, timeout=300)
        res = out["result"]
        assert res["width"] == 512 and res["height"] == 512, res
        with open(out_path, "rb") as fh:
            assert _png_size(fh.read()) == (512, 512)
        return res

    check("recipe telegram_sticker", _recipe_sticker)

    def _recipe_web():
        out_path = str(tmpdir / "web.webp")
        out = client.call("exec", {"code": _recipe_code("web_optimise", {"input_path": png_path, "output_path": out_path, "max_edge": 120, "budget_kb": 500})}, timeout=300)
        res = out["result"]
        assert res["within_budget"] and os.path.getsize(out_path) > 0, res
        return res

    check("recipe web_optimise", _recipe_web)

    def _recipe_icons():
        out = client.call("exec", {"code": _recipe_code("icon_set", {"input_path": png_path, "output_dir": str(tmpdir / "icons"), "sizes": [16, 64]})}, timeout=300)
        res = out["result"]
        assert [f["size"] for f in res["files"]] == [64, 16], res
        with open(res["files"][1]["path"], "rb") as fh:
            assert _png_size(fh.read()) == (16, 16)
        return res

    check("recipe icon_set", _recipe_icons)

    def _recipe_watermark():
        out_path = str(tmpdir / "wm.png")
        out = client.call("exec", {"code": _recipe_code("watermark", {"input_path": png_path, "output_path": out_path, "text": "demo", "position": "bottom-right"})}, timeout=300)
        assert os.path.getsize(out_path) > 0, out
        return out["result"]

    check("recipe watermark", _recipe_watermark)

    def _recipe_sheet():
        out_path = str(tmpdir / "sheet.png")
        out = client.call("exec", {"code": _recipe_code("contact_sheet", {"input_dir": str(tmpdir), "output_path": out_path, "columns": 2, "thumb": 64})}, timeout=300)
        res = out["result"]
        assert res["images"] >= 2, res
        return res

    check("recipe contact_sheet", _recipe_sheet)

    def _recipe_slice():
        out = client.call("exec", {"code": _recipe_code("sprite_sheet_slice", {"input_path": png_path, "output_dir": str(tmpdir / "tiles"), "tile_width": 75, "tile_height": 50, "skip_empty": False})}, timeout=300)
        res = out["result"]
        assert res["tiles"] == 4, res
        return res

    check("recipe sprite_sheet_slice", _recipe_slice)

    # 11. segmentation (optional, downloads a model on first use)
    if segmentation:

        def _segment():
            from . import segmentation as seg

            assert seg.available(), "segmentation extra not installed"
            src = client.call("layer_png", {"layer_id": layer_id}, timeout=300)
            res = seg.subject_mask(base64.b64decode(src["png_base64"]), model="silueta")
            assert res["width"] == 150 and len(res["gray"]) == 150 * 100, (res["width"], len(res["gray"]))
            client.call("set_mask_pixels", {"layer_id": layer_id, "width": res["width"], "height": res["height"], "gray_base64": base64.b64encode(res["gray"]).decode(), "apply": False})
            return {"bbox": res["bbox"]}

        check("segmentation (silueta)", _segment)

    # 12. error path
    def _err():
        try:
            client.call("apply_filter", {"layer_id": layer_id, "op": "gegl:does-not-exist", "params": {}})
        except BridgeError as exc:
            assert "unknown GEGL operation" in str(exc)
            return str(exc)
        raise AssertionError("expected BridgeError")

    check("error reporting", _err)

    if image_id is not None:
        check("close_image", lambda: client.call("close_image", {"image_id": image_id}))

    if started_here and not keep:
        check("shutdown", lambda: client.call("shutdown", {"quit_gimp": True}, timeout=10))
    client.close()

    log(f"artifacts: {tmpdir}")
    if failures:
        log(f"\n{len(failures)} failure(s):")
        for f in failures:
            log("  - " + f)
        return 1
    log("\nsmoke: all checks passed")
    return 0
