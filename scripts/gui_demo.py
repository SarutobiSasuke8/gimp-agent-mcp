"""Reproducible GUI example through actual MCP stdio. No direct GIMP calls."""

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run(stage, folder):
    folder.mkdir(parents=True, exist_ok=True)
    state_path = folder / "demo-state.json"
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "gimp_agent_mcp.cli", "serve"], env=dict(os.environ)
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(name, args):
                res = await session.call_tool(name, args, read_timeout_seconds=300)
                if res.is_error:
                    raise RuntimeError(str(res))
                data = res.structured_content
                if data is None:
                    data = json.loads(next(c.text for c in res.content if c.type == "text"))
                return data

            if stage == "create":
                new = await call("gimp_new_image", {"width": 1000, "height": 640, "fill": "#102d35"})
                iid = new["image"]["id"]
                steps = [
                    {
                        "op": "text",
                        "params": {
                            "text": "GIMP / AGENT MCP",
                            "name": "Eyebrow",
                            "font": "Sans-serif",
                            "size": 17,
                            "color": "#b6d8d0",
                            "x": 64,
                            "y": 54,
                        },
                    },
                    {
                        "op": "text",
                        "params": {
                            "text": "Make room\nfor the next idea.",
                            "name": "Headline",
                            "font": "Sans-serif Bold",
                            "size": 49,
                            "color": "#f4eddf",
                            "x": 60,
                            "y": 158,
                        },
                    },
                    {
                        "op": "text",
                        "params": {
                            "text": "A working file. Room to change your mind.",
                            "name": "Subhead",
                            "font": "Sans-serif",
                            "size": 18,
                            "color": "#b6d8d0",
                            "x": 64,
                            "y": 324,
                        },
                    },
                    {
                        "op": "text",
                        "params": {
                            "text": "01   /   START WITH SOMETHING EDITABLE",
                            "name": "Footer",
                            "font": "Sans-serif",
                            "size": 14,
                            "color": "#b6d8d0",
                            "x": 64,
                            "y": 566,
                        },
                    },
                    {
                        "op": "layer",
                        "params": {"action": "new", "name": "Shape study", "fill": "transparent"},
                    },
                    {
                        "op": "path",
                        "params": {
                            "action": "create",
                            "name": "Folded paper",
                            "strokes": [
                                {
                                    "type": "line",
                                    "points": [[660, 140], [902, 215], [823, 482], [583, 409]],
                                    "closed": True,
                                }
                            ],
                        },
                    },
                    {
                        "op": "path",
                        "params": {
                            "action": "fill",
                            "path_id": {"$ref": "5.id"},
                            "layer_id": {"$ref": "4.id"},
                            "color": "#ee9467",
                        },
                    },
                    {
                        "op": "path",
                        "params": {
                            "action": "create",
                            "name": "Fold",
                            "strokes": [
                                {
                                    "type": "line",
                                    "points": [[660, 140], [742, 322], [583, 409]],
                                    "closed": False,
                                }
                            ],
                        },
                    },
                    {
                        "op": "path",
                        "params": {
                            "action": "stroke",
                            "path_id": {"$ref": "7.id"},
                            "layer_id": {"$ref": "4.id"},
                            "color": "#102d35",
                            "width": 3,
                        },
                    },
                ]
                result = await call("gimp_edit_batch", {"image_id": iid, "steps": steps})
                assert result["complete"], result
                state = {
                    "image_id": iid,
                    "headline_id": result["results"][1]["id"],
                    "subhead_id": result["results"][2]["id"],
                    "footer_id": result["results"][3]["id"],
                    "shape_id": result["results"][4]["id"],
                }
                state_path.write_text(json.dumps(state, indent=2))
                await call(
                    "gimp_context",
                    {"image_id": iid, "present": True, "selected_layer_ids": [state["headline_id"]]},
                )
                await call("gimp_export", {"image_id": iid, "path": str(folder / "before.png")})
                print(json.dumps(state))
            else:
                state = json.loads(state_path.read_text())
                iid = state["image_id"]
                if stage == "edit":
                    result = await call(
                        "gimp_edit_batch",
                        {
                            "image_id": iid,
                            "steps": [
                                {
                                    "op": "text",
                                    "params": {
                                        "layer_id": state["headline_id"],
                                        "text": "Keep the layers.\nChange the plan.",
                                    },
                                },
                                {
                                    "op": "text",
                                    "params": {
                                        "layer_id": state["subhead_id"],
                                        "text": "Ask. Inspect. Refine. Keep the editable original.",
                                    },
                                },
                                {
                                    "op": "text",
                                    "params": {
                                        "layer_id": state["footer_id"],
                                        "text": "02   /   THREE TEXT EDITS. ONE UNDO STEP.",
                                    },
                                },
                            ],
                        },
                    )
                    assert result["complete"], result
                    await call("gimp_export", {"image_id": iid, "path": str(folder / "after.png")})
                    await call("gimp_export", {"image_id": iid, "path": str(folder / "layered-demo.xcf")})
                    print(json.dumps(result))
                elif stage == "inspect":
                    print(json.dumps(await call("gimp_image_info", {"image_id": iid})))
                elif stage == "verify-undo":
                    info = await call("gimp_image_info", {"image_id": iid})
                    result = await call(
                        "gimp_run_python",
                        {
                            "code": f"result = {{'headline': Gimp.Item.get_by_id({state['headline_id']}).get_text(), 'subhead': Gimp.Item.get_by_id({state['subhead_id']}).get_text(), 'footer': Gimp.Item.get_by_id({state['footer_id']}).get_text()}}"
                        },
                    )
                    texts = result["result"]
                    assert texts["headline"] == "Make room\nfor the next idea.", texts
                    assert texts["subhead"] == "A working file. Room to change your mind."
                    assert texts["footer"] == "01   /   START WITH SOMETHING EDITABLE"
                    (folder / "undo-proof.json").write_text(
                        json.dumps(
                            {
                                "one_ctrl_z_restored_all_three_text_edits": True,
                                "layer_count": len(info["layers"]),
                            },
                            indent=2,
                        )
                    )
                    print("One Ctrl+Z restored all three text edits; verified through MCP.")


asyncio.run(run(sys.argv[1], Path(sys.argv[2])))
