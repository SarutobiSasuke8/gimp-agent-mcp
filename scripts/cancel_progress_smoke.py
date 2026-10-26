"""Live check of cancellation and progress against a real GIMP 3 (headless).

Usage, isolated from a user session as in CLAUDE.md:

    GIMP_AGENT_PORT=9911 GIMP_AGENT_BRIDGE_FILE="$TEMP/gimp-agent-test.json" uv run python scripts/cancel_progress_smoke.py

It launches headless GIMP (unless a bridge already answers), then:

1. runs a long exec (repeated blurs on a large image, with checkpoint() between passes) and cancels it from a
   second connection while it runs; the call must fail with OperationCancelled after streaming progress;
2. checks the image is still usable and the bridge answers ordinary requests afterwards;
3. cancels an exec that created new images and checks those images were removed;
4. checks an ordinary request sent mid-operation is answered after the operation, not lost;
5. shuts the bridge down if this script launched it.
"""

from __future__ import annotations

import sys
import threading
import time

from gimp_agent_mcp.bridge_client import BridgeClient, BridgeError, launch_gimp

LONG = """
image = image_by_id(IMAGE_ID)
layer = image.get_layers()[0]
for i in range(PASSES):
    checkpoint(i / PASSES, f"blur pass {i + 1} of {PASSES}")
    f = Gimp.DrawableFilter.new(layer, "gegl:gaussian-blur", "blur")
    cfg = f.get_config()
    cfg.set_property("std-dev-x", 6.0)
    cfg.set_property("std-dev-y", 6.0)
    f.update()
    layer.merge_filter(f)
result = PASSES
"""

SCRATCH = """
made = []
for i in range(PASSES):
    checkpoint(i / PASSES, f"scratch image {i + 1}")
    img = Gimp.Image.new(1500, 1500, Gimp.ImageBaseType.RGB)
    lay = Gimp.Layer.new(img, "x", 1500, 1500, Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
    img.insert_layer(lay, None, 0)
    f = Gimp.DrawableFilter.new(lay, "gegl:noise-rgb", "n")
    f.update()
    lay.merge_filter(f)
    made.append(img.get_id())
result = made
"""


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(': ' + detail) if detail else ''}")
    return ok


def run_long(code: str, image_id: int | None, progress: list, box: dict) -> None:
    worker = BridgeClient()
    try:
        box["result"] = worker.call("exec", {"code": code, "image_id": image_id}, timeout=600, on_progress=progress.append)
    except BridgeError as exc:
        box["error"] = exc
    finally:
        worker.close()


def wait_for_progress(progress: list, seconds: float = 60.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if len(progress) >= 2:
            return True
        time.sleep(0.05)
    return False


def main() -> int:
    control = BridgeClient()
    launched = False
    if control.ping() is None:
        print("launching GIMP (headless)...")
        launch_gimp(mode="headless", wait_seconds=180, client=control)
        launched = True
    info = control.ping() or {}
    print(f"bridge ok: GIMP {info.get('gimp_version')} bridge {info.get('bridge_version')} mode={info.get('mode')}")
    results = []
    try:
        image = control.call("new_image", {"width": 3000, "height": 3000, "fill": "white"})
        image_id = image["image"]["id"]

        # 1. cancel a long, checkpointed exec from a second connection
        progress: list = []
        box: dict = {}
        code = LONG.replace("IMAGE_ID", str(image_id)).replace("PASSES", "60")
        thread = threading.Thread(target=run_long, args=(code, image_id, progress, box), daemon=True)
        started = time.monotonic()
        thread.start()
        results.append(check("progress arrives while the operation runs", wait_for_progress(progress)))
        canceller = BridgeClient()
        jobs = canceller.call("jobs", timeout=15)
        results.append(check("jobs answered mid-operation", (jobs.get("running") or {}).get("op") == "exec", str(jobs.get("running"))))
        answered = time.monotonic()
        answer = canceller.call("cancel", {"image_id": image_id}, timeout=15)
        results.append(check("cancel answered mid-operation", answer.get("cancel_requested") is True,
                             f"{time.monotonic() - answered:.2f}s"))
        canceller.close()
        thread.join(300)
        error = box.get("error")
        results.append(check("long exec fails with OperationCancelled",
                             isinstance(error, BridgeError) and error.error_type == "OperationCancelled",
                             f"{error.error_type if error else box.get('result')} after {time.monotonic() - started:.1f}s"))
        fractions = [p.get("fraction") for p in progress]
        results.append(check("progress fractions increase and stop short of 1.0",
                             fractions == sorted(fractions) and fractions[-1] < 1.0, f"{len(progress)} updates, last {progress[-1]}"))

        # 2. the image and the bridge are fine afterwards
        info_after = control.call("image_info", {"image_id": image_id})
        results.append(check("image still valid after cancel", info_after.get("id") == image_id))
        follow = control.call("exec", {"code": f"len(Gimp.Image.get_by_id({image_id}).get_layers())"})
        results.append(check("bridge answers ordinary requests after cancel", follow.get("result") == 1))
        jobs_after = control.call("jobs")
        results.append(check("no job left running", jobs_after.get("running") is None))

        # 3. images created by a cancelled exec are removed
        before = {img["id"] for img in control.call("list_images")["images"]}
        progress2: list = []
        box2: dict = {}
        thread2 = threading.Thread(target=run_long, args=(SCRATCH.replace("PASSES", "40"), None, progress2, box2), daemon=True)
        thread2.start()
        wait_for_progress(progress2)
        canceller = BridgeClient()
        canceller.call("cancel", timeout=15)
        canceller.close()
        thread2.join(300)
        after = {img["id"] for img in control.call("list_images")["images"]}
        results.append(check("cancelled exec removed the images it created", after == before,
                             f"before {sorted(before)} after {sorted(after)}"))

        # 4. an ordinary request sent mid-operation is answered after it
        progress3: list = []
        box3: dict = {}
        code3 = LONG.replace("IMAGE_ID", str(image_id)).replace("PASSES", "6")
        thread3 = threading.Thread(target=run_long, args=(code3, image_id, progress3, box3), daemon=True)
        thread3.start()
        wait_for_progress(progress3)
        other = BridgeClient()
        echoed = other.call("exec", {"code": "21 * 2"}, timeout=600)
        other.close()
        thread3.join(300)
        results.append(check("queued request answered after the operation",
                             echoed.get("result") == 42 and (box3.get("result") or {}).get("result") == 6, str(box3)))

        control.call("close_image", {"image_id": image_id})
    finally:
        if launched:
            try:
                control.shutdown_and_wait(quit_gimp=True)
            except BridgeError:
                pass
        control.close()
    passed = all(results)
    print(f"\ncancel/progress live check: {sum(results)}/{len(results)} passed")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
