"""Real-GIMP proof for every gimp_adjust, gimp_canvas and gimp_draw action."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from gimp_agent_mcp import server
from gimp_agent_mcp.bridge_client import BridgeClient, BridgeError, launch_gimp


def run(output: Path) -> int:
    output.mkdir(parents=True, exist_ok=True)
    client = BridgeClient()
    owned = client.ping() is None
    if owned:
        launch_gimp("headless", wait_seconds=120, client=client)
    server._client = client
    report = {"gimp_version": client.call("ping")["gimp_version"], "checks": []}
    created: list[int] = []

    def check(name, fn):
        started = time.monotonic()
        try:
            detail = fn()
            report["checks"].append(
                {"name": name, "passed": True, "detail": detail, "seconds": round(time.monotonic() - started, 3)}
            )
            print("PASS", name, flush=True)
        except Exception as exc:
            report["checks"].append({"name": name, "passed": False, "error": str(exc)})
            print("FAIL", name, str(exc), flush=True)

    def image(width=40, height=30, fill="#804020"):
        made = client.call("new_image", {"width": width, "height": height, "fill": fill})
        created.append(made["image"]["id"])
        return made["image"]["id"], made["layer_id"]

    def pixel(layer_id, x=10, y=10):
        return client.call("pixel_color", {"layer_id": layer_id, "x": x, "y": y})

    def adjustment(action, params=None):
        iid, lid = image()
        result = server.gimp_adjust(lid, action, params or {}, mode="merge")
        measured = pixel(lid)
        assert result["operation"] and result["result"], result
        return {"operation": result["operation"].get("op", result["operation"].get("name")), "pixel": measured}

    adjustment_cases = {
        "brightness_contrast": {"brightness": 0.2, "contrast": 0.1},
        "hue_saturation": {"hue": 25.0, "saturation": 15.0},
        "curves": {"channel": "value", "points": [0.0, 0.0, 1.0, 0.6]},
        "desaturate": {},
        "invert": {},
        "blur": {"radius": 2.0},
        "sharpen": {"radius": 1.5, "amount": 1.0, "threshold": 0.0},
        "noise": {"amount": 0.05, "gaussian": True, "independent": True},
        "pixelate": {"size": 4},
    }
    for action, params in adjustment_cases.items():
        check(f"adjust {action} resolves and yields a measured pixel", lambda a=action, p=params: adjustment(a, p))

    def canvas(action, **params):
        iid, _lid = image(40, 30)
        if action in ("merge_visible", "flatten"):
            client.call("layer", {"action": "new", "image_id": iid, "name": "second", "fill": "#204080"})
        result = server.gimp_canvas(iid, action, **params)
        assert result["operation"]["name"].startswith("gimp-image-")
        return {"width": result["image"]["width"], "height": result["image"]["height"], "layers": result["image"]["layer_count"]}

    canvas_cases = {
        "scale": {"width": 20, "height": 15},
        "crop": {"width": 20, "height": 15, "x": 2, "y": 3},
        "resize": {"width": 50, "height": 35, "x": 2, "y": 3},
        "rotate": {"angle": 90},
        "flip": {"direction": "horizontal"},
        "merge_visible": {},
        "flatten": {},
    }
    for action, params in canvas_cases.items():
        check(f"canvas {action} resolves and reports dimensions", lambda a=action, p=params: canvas(a, **p))

    def drawing(action, **params):
        iid, lid = image(fill="transparent")
        if action == "fill_selection":
            server.gimp_select(iid, mode="rect", x=5, y=5, width=12, height=10)
        foreground_before = server.gimp_context(iid)["foreground"]
        result = server.gimp_draw(iid, lid, action, color="#ff2040", **params)
        assert server.gimp_context(iid)["foreground"] == foreground_before
        assert result["operations"] and all(op.get("name") for op in result["operations"]), result
        bbox = server.gimp_measure("bbox", layer_id=lid)
        probe_x, probe_y = (10, 10)
        if action == "line":
            probe_x, probe_y = 20, 15
        measured = pixel(lid, probe_x, probe_y)
        assert measured["rgba"][3] > 0, (action, measured, bbox)
        return {"operations": [op["name"] for op in result["operations"]], "bbox": bbox, "pixel": measured}

    draw_cases = {
        "fill_layer": {},
        "fill_selection": {},
        "rectangle": {"x": 5, "y": 5, "width": 15, "height": 12},
        "ellipse": {"x": 5, "y": 5, "width": 15, "height": 12},
        "rectangle_outline": {"x": 8, "y": 8, "width": 16, "height": 12, "line_width": 5},
        "ellipse_outline": {"x": 5, "y": 5, "width": 20, "height": 20, "line_width": 8},
        "line": {"x": 5, "y": 15, "x2": 35, "y2": 15, "line_width": 5},
    }
    for action, params in draw_cases.items():
        check(f"draw {action} resolves and yields measured pixels", lambda a=action, p=params: drawing(a, **p))

    try:
        pass
    finally:
        for iid in reversed(created):
            try:
                client.call("close_image", {"image_id": iid})
            except BridgeError:
                pass
        if owned:
            client.call("shutdown", {"quit_gimp": True}, timeout=10)
        client.close()
        report["passed"] = all(item["passed"] for item in report["checks"])
        (output / "everyday-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(run(Path(sys.argv[1])))
