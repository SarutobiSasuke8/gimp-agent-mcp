"""Runtime regression proof on disposable GIMP documents; writes a JSON report.

Use an isolated profile (GIMP3_DIRECTORY/GIMP_AGENT_CONFIG_DIR) in CI.
No claim of exhaustive competitor parity. Run: python scripts/capability_proof.py OUT_DIR
"""
from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

from gimp_agent_mcp.bridge_client import BridgeClient, BridgeError, launch_gimp


def run(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    c = BridgeClient()
    owned = c.ping() is None
    if owned:
        launch_gimp("headless", wait_seconds=120, client=c)
    report = {"gimp_version": c.call("ping")["gimp_version"], "checks": []}
    created, snapshots = [], []

    def call(op, **params):
        return c.call(op, params)

    def check(name, fn):
        started = time.monotonic()
        try:
            detail = fn()
            report["checks"].append({"name": name, "passed": True, "detail": detail, "seconds": round(time.monotonic()-started, 3)})
            print("PASS", name, flush=True)
        except Exception as exc:
            report["checks"].append({"name": name, "passed": False, "error": str(exc)})
            print("FAIL", name, str(exc), flush=True)

    def image(w=64, h=48, fill="#808080"):
        res = call("new_image", width=w, height=h, fill=fill)
        created.append(res["image"]["id"])
        return res["image"]["id"], res["layer_id"]

    def pixel(layer, x=20, y=20):
        return call("pixel_color", layer_id=layer, x=x, y=y)["hex"]

    def pdb(name, **args):
        call("pdb_describe", name=name)
        return call("pdb_call", name=name, args=args)

    try:
        iid, lid = image()

        def curves():
            before = pixel(lid)
            pdb("gimp-drawable-curves-spline", drawable=lid, channel="value", points=[0., 0., 1., .5])
            after = pixel(lid)
            assert int(after[1:3], 16) < int(before[1:3], 16), (before, after)
            return {"before": before, "after": after, "route": "PDB JSON double array"}
        check("curves change measured pixels", curves)

        def gradient():
            pdb("gimp-context-set-foreground", foreground="#000000")
            pdb("gimp-context-set-background", background="#ffffff")
            pdb("gimp-context-set-gradient-fg-bg-rgb")
            pdb("gimp-drawable-edit-gradient-fill", drawable=lid, **{"gradient-type": "linear", "x1": 0., "y1": 0., "x2": 63., "y2": 0.})
            left, right = pixel(lid, 1, 24), pixel(lid, 62, 24)
            assert int(right[1:3], 16) > int(left[1:3], 16) + 100, (left, right)
            return {"left": left, "right": right}
        check("gradient fill through PDB", gradient)

        def drawing(name, y):
            pdb("gimp-context-set-foreground", foreground="#ff0000")
            pdb("gimp-context-set-brush-size", size=9.)
            pdb(name, drawable=lid, strokes=[5., float(y), 55., float(y)])
            measured = pixel(lid, 30, y)
            assert int(measured[1:3], 16) > int(measured[3:5], 16), measured
            return {"pixel": measured}
        check("paintbrush with JSON stroke array", lambda: drawing("gimp-paintbrush-default", 12))
        check("pencil with JSON stroke array", lambda: drawing("gimp-pencil", 36))

        def rotate():
            pdb("gimp-image-rotate", image=iid, **{"rotate-type": "degrees90"})
            info = call("image_info", image_id=iid)
            assert (info["width"], info["height"]) == (48, 64)
            return {"width": info["width"], "height": info["height"]}
        check("rotation by enum nick", rotate)

        def batch():
            result = call("edit_batch", image_id=iid, steps=[
                {"op": "layer", "params": {"action": "new", "name": "Batch layer", "fill": "#123456"}},
                {"op": "layer", "params": {"action": "set", "layer_id": {"$ref": "0.id"}, "name": "Renamed in same group"}},
            ])
            assert result["complete"] and result["completed_steps"] == 2 and result["undo_group_closed"], result
            layer = result["results"][0]["id"]
            assert call("layer", action="info", layer_id=layer)["name"] == "Renamed in same group"
            return {"completed_steps": 2, "undo_group_closed": True, "gui_undo": "verified separately; this check asserts batch execution"}
        check("grouped batch and result references", batch)

        def failing_batch():
            result = call("edit_batch", image_id=iid, steps=[
                {"op": "layer", "params": {"action": "new", "name": "Preserved partial work"}},
                {"op": "layer", "params": {"action": "not-an-action", "layer_id": lid}},
                {"op": "layer", "params": {"action": "delete", "layer_id": lid}},
            ])
            assert not result["complete"] and result["error"]["step"] == 1 and result["completed_steps"] == 1 and result["undo_group_closed"], result
            assert call("layer", action="info", layer_id=lid)["id"] == lid
            # A subsequent batch must still execute, so the failed batch has not poisoned grouping.
            next_result = call("edit_batch", image_id=iid, steps=[{"op": "layer", "params": {"action": "set", "layer_id": lid, "name": "Still editable"}}])
            assert next_result["complete"]
            return {"stopped_at": 1, "later_step_skipped": True, "next_batch_complete": True}
        check("failed batch preserves work and closes group", failing_batch)

        other, other_layer = image()
        def cross_document():
            result = call("edit_batch", image_id=iid, steps=[{"op": "layer", "params": {"action": "delete", "layer_id": other_layer}}])
            assert not result["complete"] and result["completed_steps"] == 0
            assert call("layer", action="info", layer_id=other_layer)["id"] == other_layer
            return "foreign document preserved"
        check("batch rejects cross-document mutation", cross_document)

        def context():
            res = call("context", image_id=iid, selected_layer_ids=[lid])
            assert res["selected_layer_ids"] == [lid]
            assert call("context")["requires_image_id"]
            return {"selected_layer_ids_verified": True, "ambiguous_focus_not_guessed": True}
        check("document context and ambiguity", context)

        def render_group():
            fixture = call("exec", code="""img=Gimp.Image.new(32,32,Gimp.ImageBaseType.RGB)
group=Gimp.GroupLayer.new(img,'Hidden parent');img.insert_layer(group,None,0)
layer=Gimp.Layer.new(img,'Nested red',32,32,Gimp.ImageType.RGBA_IMAGE,100.,Gimp.LayerMode.NORMAL)
img.insert_layer(layer,group,0)
Gimp.context_push()
try:
 Gimp.context_set_foreground(make_color('#ff0000'));layer.fill(Gimp.FillType.FOREGROUND)
finally:
 Gimp.context_pop()
group.set_visible(False)
result={'image_id':img.get_id(),'layer_id':layer.get_id()}
""")["result"]
            created.append(fixture["image_id"])
            rendered = call("render", layer_id=fixture["layer_id"])
            assert rendered["image_id"] == fixture["image_id"]
            path = output / "nested-layer.png"
            path.write_bytes(base64.b64decode(rendered["png_base64"]))
            opened = call("open", path=str(path))
            created.append(opened["id"])
            color = pixel(opened["layers"][0]["id"], 16, 16)
            assert color == "#ff0000", color
            try:
                call("render", image_id=fixture["image_id"], layer_id=other_layer)
            except BridgeError:
                pass
            else:
                raise AssertionError("foreign layer render was accepted")
            return {"nested_pixel": color, "foreign_layer_rejected": True}
        check("nested layer isolation", render_group)

        def hidden_composite():
            # Comparison must not accidentally select a hidden top layer.
            code = """img=Gimp.Image.new(32,32,Gimp.ImageBaseType.RGB)
for name,color,visible in [('Visible','#00ff00',True),('Hidden','#ff0000',False)]:
 layer=Gimp.Layer.new(img,name,32,32,Gimp.ImageType.RGBA_IMAGE,100.,Gimp.LayerMode.NORMAL)
 img.insert_layer(layer,None,0);Gimp.context_set_foreground(make_color(color));layer.fill(Gimp.FillType.FOREGROUND);layer.set_visible(visible)
dup,merged=bridge._flat_copy(img)
try:
 result={'image_id':img.get_id(),'pixel':bridge.op_pixel_color({'layer_id':merged.get_id(),'x':16,'y':16})['hex']}
finally:
 dup.delete()
"""
            result = call("exec", code=code)["result"]
            created.append(result["image_id"])
            assert result["pixel"] == "#00ff00", result
            return {"composite_pixel": result["pixel"]}
        check("comparison composites ignore hidden top layers", hidden_composite)

        def snapshot_cleanup():
            sid = call("snapshot", image_id=iid)["snapshot_id"]
            snapshots.append(sid)
            assert sid not in [i["id"] for i in call("ping")["images"]]
            assert sid not in [i["id"] for i in call("list_images")]
            assert call("drop_snapshot", snapshot_id=sid)["dropped"] == sid
            snapshots.remove(sid)
            return "snapshot released and excluded from status documents"
        check("snapshot cleanup", snapshot_cleanup)
    finally:
        for sid in snapshots:
            try:
                call("drop_snapshot", snapshot_id=sid)
            except BridgeError:
                pass
        for iid in reversed(created):
            try:
                call("close_image", image_id=iid)
            except BridgeError:
                pass
        if owned:
            call("shutdown", quit_gimp=True)
        c.close()
        report["passed"] = all(item["passed"] for item in report["checks"])
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(run(Path(sys.argv[1])))
