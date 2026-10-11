"""Interactive one-undo check against a GUI GIMP bridge.

Run after `gimp-agent-mcp launch --mode gui`. The script creates and closes only
its own test image. Focus that image and press Ctrl+Z when prompted.
"""

from __future__ import annotations

import base64

from gimp_agent_mcp.bridge_client import BridgeClient


def main() -> None:
    client = BridgeClient()
    info = client.call("ping")
    if info["mode"] != "gui":
        raise SystemExit("Start the bridge in GUI mode for the Ctrl+Z check.")
    created = client.call("new_image", {"width": 64, "height": 64, "fill": "transparent"})
    image_id = created["image"]["id"]
    snapshot = client.call("snapshot", {"image_id": image_id})
    snapshot_id = snapshot["snapshot_id"]
    try:
        def pixels(target_id: int) -> bytes:
            rendered = client.call("render", {"image_id": target_id, "max_size": 64})
            return base64.b64decode(rendered["png_base64"])

        before = pixels(snapshot_id)
        client.call("undo_group", {"image_id": image_id, "action": "start", "name": "agent: undo smoke"})
        try:
            layer = client.call("layer", {"action": "new", "image_id": image_id, "name": "red", "fill": "#ff0000"})
            client.call("layer", {"action": "set", "layer_id": layer["id"], "opacity": 50.0})
            client.call("layer", {"action": "duplicate", "layer_id": layer["id"]})
        finally:
            client.call("undo_group", {"image_id": image_id, "action": "end"})
        assert pixels(image_id) != before, "three edits did not alter the image"
        input("Focus the 64x64 test image in GIMP, press Ctrl+Z once, then press Enter here: ")
        assert pixels(image_id) == before, "one undo did not restore the pre-turn snapshot"
        print("One Ctrl+Z restored the pre-turn snapshot.")
    finally:
        client.call("drop_snapshot", {"snapshot_id": snapshot_id})
        client.call("close_image", {"image_id": image_id})
        client.close()


if __name__ == "__main__":
    main()
