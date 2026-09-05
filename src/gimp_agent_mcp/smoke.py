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


def run_smoke(mode: str = "headless", keep: bool = False, verbose: bool = True) -> int:
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
        except (BridgeError, AssertionError, KeyError, RuntimeError) as exc:
            failures.append(f"{label}: {exc}")
            log(f"  FAIL {label}: {exc}")
            return None

    # 1. new image + info
    created = check("new_image", lambda: client.call("new_image", {"width": 300, "height": 200, "fill": "#ff8800", "name": "smoke"}))
    image_id = created["image"]["id"] if created else None
    layer_id = created["layer_id"] if created else None

    def _info():
        i = client.call("image_info", {"image_id": image_id})
        assert i["width"] == 300 and i["height"] == 200, i
        assert i["layers"][0]["id"] == layer_id
        return i

    check("image_info", _info)

    # 2. PDB search/describe/call
    def _pdb():
        s = client.call("pdb_search", {"query": "image scale", "limit": 5})
        assert any(r["name"] == "gimp-image-scale" for r in s["results"]), s
        d = client.call("pdb_describe", {"name": "gimp-image-scale"})
        names = [a["name"] for a in d["arguments"]]
        assert "new-width" in names, names
        client.call("pdb_call", {"name": "gimp-image-scale", "args": {"image": image_id, "new_width": 150, "new_height": 100}})
        i = client.call("image_info", {"image_id": image_id})
        assert i["width"] == 150, i
        return d

    check("pdb search/describe/call", _pdb)

    # 3. GEGL filter
    def _filter():
        s = client.call("filter_search", {"query": "dropshadow"})
        assert any(r["op"] == "gegl:dropshadow" for r in s["results"]), s
        d = client.call("filter_describe", {"op": "gegl:dropshadow"})
        props = [p["name"] for p in d["properties"]]
        assert "grow-radius" in props, props
        client.call(
            "apply_filter",
            {"layer_id": layer_id, "op": "gegl:gaussian-blur", "params": {"std_dev_x": 3, "std-dev-y": 3}, "mode": "merge"},
        )
        return d

    check("filter search/describe/apply", _filter)

    # 4. render
    def _render():
        r = client.call("render", {"image_id": image_id, "max_size": 64})
        w, h = _png_size(base64.b64decode(r["png_base64"]))
        assert max(w, h) == 64, (w, h)
        return r

    check("render", _render)

    # 5. python exec with persistent namespace
    def _exec():
        client.call("exec", {"code": f"img = image_by_id({image_id})\nresult = img.get_width()"})
        out = client.call("exec", {"code": "img.get_height()"})
        assert out["result"] == 100, out
        return out

    check("exec (persistent namespace)", _exec)

    # 6. export + open
    png_path = str(tmpdir / "smoke.png")

    def _export():
        r = client.call("export", {"image_id": image_id, "path": png_path})
        assert os.path.getsize(png_path) > 0
        opened = client.call("open", {"path": png_path})
        assert opened["width"] == 150
        client.call("close_image", {"image_id": opened["id"]})
        return r

    check("export/open/close", _export)

    # 7. recipe: telegram sticker end to end
    def _recipe():
        module = recipes.get_recipe("telegram_sticker")
        out_path = str(tmpdir / "sticker.png")
        resolved = recipes.resolve_params("telegram_sticker", {"input_path": png_path, "output_path": out_path})
        out = client.call("exec", {"code": "params = " + repr(resolved) + "\n" + module.SOURCE}, timeout=300)
        res = out["result"]
        assert res["width"] == 512 and res["height"] == 512, res
        with open(out_path, "rb") as fh:
            w, h = _png_size(fh.read())
        assert (w, h) == (512, 512)
        return res

    check("recipe telegram_sticker", _recipe)

    # 8. error path: bad op name reports cleanly
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
