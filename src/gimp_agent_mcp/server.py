"""gimp-agent-mcp: the MCP server. Thin over the bridge; the heavy lifting runs inside GIMP."""

from __future__ import annotations

import base64
import glob
import os
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import Image, MCPServer

try:  # mcp >= 2 reports ToolError as a clean tool failure instead of a server traceback
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # pragma: no cover
    ToolError = RuntimeError  # type: ignore[misc,assignment]

from . import recipes
from .bridge_client import BridgeClient, BridgeError, BridgeUnavailable, launch_gimp

ALLOW_PYTHON = os.environ.get("GIMP_AGENT_ALLOW_PYTHON", "1").strip().lower() not in ("0", "false", "no", "off")

INSTRUCTIONS = """\
You are driving a live GIMP 3 instance through gimp-agent-mcp.

Working model:
- Everything is addressed by integer ids: images have image_id, layers/channels/masks/paths have item ids.
  Call gimp_list_images or gimp_image_info to get them; never guess ids.
- After any edit, call gimp_render to see the result before deciding the next step. Renders are downscaled;
  pass a region to inspect detail at full resolution.
- Filters: use gimp_filter_search to find a GEGL operation (blur, dropshadow, levels, unsharp-mask, ...),
  gimp_filter_describe to read its properties, then gimp_apply_filter. mode="merge" bakes the filter into
  the pixels; mode="append" adds it as a non-destructive layer effect.
- Anything else in GIMP is a PDB procedure: gimp_pdb_search -> gimp_pdb_describe -> gimp_pdb_call.
  Arguments are passed by name; images and items are passed as their ids; colours as "#rrggbb", "white" or
  "rgb(255,0,0)"; enums by nick such as "clip-to-image". run-mode defaults to noninteractive.
- gimp_run_python executes Python inside GIMP with Gimp, Gegl, Gio available and a persistent namespace.
  Prefer it for multi-step work; the expression value or a variable named `result` comes back.
- Recipes are tested multi-step jobs (gimp_list_recipes). Prefer a recipe over re-deriving the steps.
- Exports go through gimp_export; the extension selects the format. Save working files as .xcf.
- If nothing responds, gimp_status tells you whether GIMP is running; gimp_launch starts it.
- gimp_help(topic) has worked examples for filters, colours, text, masks, paths, layers, measuring, recipes and
  compose-from-manifest. Call it before improvising.
"""

mcp = MCPServer("gimp-agent-mcp", instructions=INSTRUCTIONS)
_client = BridgeClient()


def _call(op: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
    try:
        return _client.call(op, params, timeout=timeout)
    except BridgeUnavailable as exc:
        raise ToolError(str(exc)) from exc
    except BridgeError as exc:
        detail = f"{exc.error_type}: {exc}"
        # Deliberate validation errors are self-explanatory; only unexpected exceptions carry a trace tail.
        if exc.trace and exc.error_type != "BridgeError":
            detail += "\n" + exc.trace[-1500:]
        raise ToolError(detail) from exc


# --------------------------------------------------------------------------- help


@mcp.tool()
def gimp_help(topic: str = "start") -> str:
    """Read this first. How to work with GIMP through this server, by topic: start, filters, colours, text, masks, paths, layers, measure, recipes, compose, errors, or all."""
    from . import help as helpdoc

    return helpdoc.get(topic)


# --------------------------------------------------------------------------- session


@mcp.tool()
def gimp_status() -> dict[str, Any]:
    """Check whether GIMP and the agent bridge are reachable. Returns GIMP version, mode, and open images."""
    info = _client.ping()
    if info is None:
        from . import paths

        exes = paths.find_gimp()
        return {
            "connected": False,
            "gimp_found": str(exes.any) if exes.any else None,
            "plugin_installed": bool(paths.plugin_install_dir() and (paths.plugin_install_dir() / "gimp-agent-bridge.py").is_file()),
            "hint": "Call gimp_launch(mode='gui'|'headless'), or start Filters > Development > Start Agent Bridge inside GIMP.",
        }
    info["connected"] = True
    info["python_tool_enabled"] = ALLOW_PYTHON
    return info


@mcp.tool()
def gimp_launch(mode: str = "gui", wait_seconds: int = 90) -> dict[str, Any]:
    """Start GIMP 3 with the bridge running. mode='gui' opens the normal window; 'headless' runs gimp-console with no UI."""
    if _client.ping():
        return {"already_running": True, **(_client.ping() or {})}
    try:
        return launch_gimp(mode=mode, wait_seconds=float(wait_seconds), client=_client)
    except (BridgeUnavailable, FileNotFoundError, ValueError) as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def gimp_shutdown(quit_gimp: bool | None = None) -> dict[str, Any]:
    """Stop the bridge. quit_gimp defaults to True for headless sessions and False for the GUI (unsaved work is not prompted for)."""
    params: dict[str, Any] = {}
    if quit_gimp is not None:
        params["quit_gimp"] = bool(quit_gimp)
    result = _call("shutdown", params, timeout=10.0)
    _client.close()
    return result


# --------------------------------------------------------------------------- images


@mcp.tool()
def gimp_list_images() -> list[dict[str, Any]]:
    """List open images with ids, dimensions, file path, and layer count."""
    return _call("list_images")


@mcp.tool()
def gimp_image_info(image_id: int) -> dict[str, Any]:
    """Full structure of one image: layer tree with item ids, channels, paths, selection bounds, resolution."""
    return _call("image_info", {"image_id": image_id})


@mcp.tool()
def gimp_new_image(width: int = 512, height: int = 512, fill: str = "transparent") -> dict[str, Any]:
    """Create an RGB image with one layer. fill: 'transparent', 'white', 'black', 'foreground', 'background' or any colour."""
    return _call("new_image", {"width": width, "height": height, "fill": fill})


@mcp.tool()
def gimp_open(path: str) -> dict[str, Any]:
    """Open an image file (PNG, JPEG, WebP, XCF, PSD, SVG, ...) and return its structure."""
    return _call("open", {"path": path})


@mcp.tool()
def gimp_export(image_id: int, path: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Export an image; the extension chooses the format (.png .webp .jpg .tiff .bmp .gif .xcf). options are passed to the format's export procedure, e.g. {"quality": 0.85} for JPEG (0..1), {"quality": 80, "lossless": false} for WebP, {"compression": 9} for PNG. Unknown option names return the valid list."""
    if options:
        return _call("export_with", {"image_id": image_id, "path": path, "options": options})
    return _call("export", {"image_id": image_id, "path": path})


@mcp.tool()
def gimp_close_image(image_id: int) -> dict[str, Any]:
    """Close an image without saving."""
    return _call("close_image", {"image_id": image_id})


@mcp.tool()
def gimp_render(
    image_id: int | None = None,
    layer_id: int | None = None,
    max_size: int = 1024,
    region: dict[str, int] | None = None,
) -> Image:
    """Render the current state of an image as a PNG you can see. Optional layer_id isolates one layer; region={x,y,width,height} crops before scaling."""
    result = _call("render", {"image_id": image_id, "layer_id": layer_id, "max_size": max_size, "region": region})
    data = base64.b64decode(result["png_base64"])
    return Image(data=data, format="png")


# --------------------------------------------------------------------------- PDB


@mcp.tool()
def gimp_pdb_search(query: str = "", limit: int = 25) -> dict[str, Any]:
    """Search GIMP's Procedure Database by words in the procedure name (e.g. 'image scale', 'layer text', 'file png')."""
    return _call("pdb_search", {"query": query, "limit": limit})


@mcp.tool()
def gimp_pdb_describe(name: str) -> dict[str, Any]:
    """Describe a PDB procedure: arguments with types, defaults and enum choices, plus return values."""
    return _call("pdb_describe", {"name": name})


@mcp.tool()
def gimp_pdb_call(name: str, args: dict[str, Any] | None = None, undo_group: bool = True) -> dict[str, Any]:
    """Call any PDB procedure by name with arguments keyed by name. Pass images/items as ids, colours as strings, enums by nick. Example: name="gimp-image-scale", args={"image": 3, "new-width": 800, "new-height": 600}; name="gimp-image-select-round-rectangle", args={"image": 3, "operation": "replace", "x": 10, "y": 10, "width": 200, "height": 80, "corner-radius-x": 20, "corner-radius-y": 20}. Use gimp_pdb_describe first when unsure."""
    return _call("pdb_call", {"name": name, "args": args or {}, "undo_group": undo_group})


# --------------------------------------------------------------------------- GEGL filters


@mcp.tool()
def gimp_filter_search(query: str = "", limit: int = 25) -> dict[str, Any]:
    """Search the GEGL operations available as filters (e.g. 'blur', 'shadow', 'levels', 'noise')."""
    return _call("filter_search", {"query": query, "limit": limit})


@mcp.tool()
def gimp_filter_describe(op: str) -> dict[str, Any]:
    """Describe a GEGL operation's properties (names, types, ranges, defaults)."""
    return _call("filter_describe", {"op": op})


@mcp.tool()
def gimp_apply_filter(
    layer_id: int,
    op: str,
    params: dict[str, Any] | None = None,
    mode: str = "merge",
    opacity: float | None = None,
    blend_mode: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    """Apply a GEGL operation to a layer. mode='merge' bakes it in; mode='append' adds a non-destructive layer effect. Examples: white outline = op="gegl:dropshadow", params={"x":0,"y":0,"radius":0,"grow-radius":8,"color":"white"}; soft shadow = {"x":0,"y":6,"radius":12,"opacity":0.4}; blur = op="gegl:gaussian-blur", params={"std-dev-x":4,"std-dev-y":4}. gimp_help("filters") lists the useful ops."""
    return _call(
        "apply_filter",
        {
            "layer_id": layer_id,
            "op": op,
            "params": params or {},
            "mode": mode,
            "opacity": opacity,
            "blend_mode": blend_mode,
            "name": name,
        },
    )


@mcp.tool()
def gimp_layer_effects(layer_id: int) -> list[dict[str, Any]]:
    """List the non-destructive filters currently attached to a layer."""
    return _call("list_filters_on_layer", {"layer_id": layer_id})


# --------------------------------------------------------------------------- measurement + comparison


@mcp.tool()
def gimp_measure(
    kind: str,
    image_id: int | None = None,
    layer_id: int | None = None,
    x: int | None = None,
    y: int | None = None,
    threshold: int = 0,
    channels: list[str] | None = None,
    k: int = 6,
) -> dict[str, Any]:
    """Measure pixels instead of guessing from a render. kind='color' (rgba at image x,y), 'bbox' (bounding box of non-transparent pixels), 'histogram' (mean/median/std per channel), 'dominant' (top k colours). Defaults to the selected layer."""
    base = {"image_id": image_id, "layer_id": layer_id}
    if kind == "color":
        if x is None or y is None:
            raise ToolError("kind='color' needs x and y")
        return _call("pixel_color", {**base, "x": x, "y": y})
    if kind == "bbox":
        return _call("alpha_bbox", {**base, "threshold": threshold})
    if kind == "histogram":
        return _call("histogram", {**base, "channels": channels})
    if kind == "dominant":
        return _call("dominant_colors", {**base, "k": k})
    raise ToolError("kind must be color, bbox, histogram or dominant")


@mcp.tool()
def gimp_snapshot(image_id: int) -> dict[str, Any]:
    """Take a hidden snapshot of an image's current state so gimp_render_compare can show before/after later."""
    return _call("snapshot", {"image_id": image_id})


@mcp.tool()
def gimp_render_compare(image_id: int, snapshot_id: int, panels: str = "before,after,diff", max_size: int = 1024, drop_snapshot: bool = False) -> Image:
    """Side-by-side render of a snapshot and the current image. panels is a comma list of before, after, diff (diff = pixel difference, black means identical)."""
    result = _call("render_compare", {"image_id": image_id, "snapshot_id": snapshot_id, "panels": panels, "max_size": max_size})
    if drop_snapshot:
        _call("drop_snapshot", {"snapshot_id": snapshot_id})
    return Image(data=base64.b64decode(result["png_base64"]), format="png")


# --------------------------------------------------------------------------- selection, masks, layers


@mcp.tool()
def gimp_select(
    image_id: int,
    mode: str = "bounds",
    op: str = "replace",
    x: float | None = None,
    y: float | None = None,
    width: float | None = None,
    height: float | None = None,
    color: str | None = None,
    threshold: float = 0.15,
    sample_merged: bool = False,
    layer_id: int | None = None,
    item_id: int | None = None,
    amount: float | None = None,
) -> dict[str, Any]:
    """Selection in one tool. mode: rect, ellipse (x,y,width,height), color (color, threshold 0..1, layer_id), alpha (layer_id: select the layer's opaque pixels), item (item_id: path or channel), all, none, invert, grow/shrink/feather/border (amount), bounds (just report). op: replace, add, subtract, intersect. Returns the selection bounds."""
    return _call(
        "select",
        {
            "image_id": image_id,
            "mode": mode,
            "op": op,
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "color": color,
            "threshold": threshold,
            "sample_merged": sample_merged,
            "layer_id": layer_id,
            "item_id": item_id,
            "amount": amount,
        },
    )


@mcp.tool()
def gimp_layer_mask(layer_id: int, action: str = "add", type: str = "selection") -> dict[str, Any]:
    """Layer masks. action='add' with type selection|alpha|alpha-transfer|white|black|copy; 'apply' bakes the mask in; 'remove' discards it; 'enable'/'disable' toggle it; 'show'/'hide' preview it."""
    return _call("layer_mask", {"layer_id": layer_id, "action": action, "type": type})


@mcp.tool()
def gimp_layer(
    action: str,
    layer_id: int | None = None,
    image_id: int | None = None,
    name: str | None = None,
    width: int | None = None,
    height: int | None = None,
    fill: str | None = None,
    x: int | None = None,
    y: int | None = None,
    dx: float | None = None,
    dy: float | None = None,
    opacity: float | None = None,
    mode: str | None = None,
    visible: bool | None = None,
    lock: bool | None = None,
    position: int | None = None,
    parent_id: int | None = None,
    merge_type: str | None = None,
    local_origin: bool = False,
) -> dict[str, Any]:
    """Layer operations. action: new (image_id, name, width, height, fill, x, y, position), set (name, visible, opacity, mode, x, y, lock), move (dx, dy), reorder (position, parent_id), duplicate, merge_down, delete, resize_to_image, scale (width, height), add_alpha, crop_to_content, info."""
    params = {k: v for k, v in locals().items() if v is not None}
    return _call("layer", params)


@mcp.tool()
def gimp_layer_effect(
    filter_id: int,
    action: str = "set",
    params: dict[str, Any] | None = None,
    visible: bool | None = None,
    opacity: float | None = None,
    blend_mode: str | None = None,
) -> dict[str, Any]:
    """Edit or delete a non-destructive layer effect (ids from gimp_layer_effects). action='set' updates params/visible/opacity/blend_mode; 'delete' removes it."""
    return _call("layer_effect", {"filter_id": filter_id, "action": action, "params": params or {}, "visible": visible, "opacity": opacity, "blend_mode": blend_mode})


# --------------------------------------------------------------------------- text + paths


@mcp.tool()
def gimp_list_fonts(filter: str = "", limit: int = 200) -> dict[str, Any]:
    """List installed font names, optionally filtered by a regex."""
    return _call("list_fonts", {"filter": filter, "limit": limit})


@mcp.tool()
def gimp_text(
    image_id: int | None = None,
    layer_id: int | None = None,
    text: str | None = None,
    x: int | None = None,
    y: int | None = None,
    size: float | None = None,
    font: str | None = None,
    color: str | None = None,
    justify: str | None = None,
    letter_spacing: float | None = None,
    line_spacing: float | None = None,
    box_width: float | None = None,
    box_height: float | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    """Create a text layer (image_id + text) or edit one (layer_id). size in px, font by name (gimp_list_fonts), colour, justify left|center|right|fill, spacing, optional fixed box."""
    params = {k: v for k, v in locals().items() if v is not None}
    return _call("text", params)


@mcp.tool()
def gimp_path(
    action: str = "create",
    image_id: int | None = None,
    path_id: int | None = None,
    name: str | None = None,
    strokes: list[dict[str, Any]] | None = None,
    layer_id: int | None = None,
    color: str | None = None,
    width: float = 2.0,
    op: str = "replace",
) -> dict[str, Any]:
    """Vector paths. action='create' (image_id, strokes=[{type:'line'|'bezier', points:[[x,y],...], closed:bool}]; bezier points after the first are control1, control2, anchor triples), 'select' (path to selection), 'stroke' (draw it on layer_id with color and width), 'fill' (fill it on layer_id), 'delete'."""
    params = {k: v for k, v in locals().items() if v is not None}
    return _call("path", params)


# --------------------------------------------------------------------------- segmentation


@mcp.tool()
def gimp_remove_background(layer_id: int, mode: str = "mask", model: str = "u2net", alpha_matting: bool = False) -> dict[str, Any]:
    """AI subject cut-out. Runs a segmentation model on the layer and writes the result as an editable layer mask (mode='mask') or bakes it into the alpha channel (mode='apply'). Needs the optional segmentation extra. Models: u2net (default), isnet-general-use, u2net_human_seg, isnet-anime, silueta."""
    from . import segmentation

    if not segmentation.available():
        raise ToolError("segmentation is not installed: run `uv sync --extra segmentation` in the gimp-agent-mcp directory")
    src = _call("layer_png", {"layer_id": layer_id}, timeout=300.0)
    try:
        result = segmentation.subject_mask(base64.b64decode(src["png_base64"]), model=model, alpha_matting=alpha_matting)
    except (RuntimeError, ValueError) as exc:
        raise ToolError(str(exc)) from exc
    layer = _call(
        "set_mask_pixels",
        {
            "layer_id": layer_id,
            "width": result["width"],
            "height": result["height"],
            "gray_base64": base64.b64encode(result["gray"]).decode("ascii"),
            "apply": mode == "apply",
        },
        timeout=300.0,
    )
    return {"layer": layer, "model": result["model"], "subject_bbox": result["bbox"], "mode": mode}


# --------------------------------------------------------------------------- python + recipes


if ALLOW_PYTHON:

    @mcp.tool()
    def gimp_run_python(code: str, image_id: int | None = None) -> dict[str, Any]:
        """Run Python inside GIMP. Gimp, Gegl, Gio, GLib and helpers image_by_id/item_by_id/make_color are available; the namespace persists between calls. Returns stdout plus the expression value or `result`. Pass image_id to wrap the call in one undo step."""
        return _call("exec", {"code": code, "image_id": image_id}, timeout=600.0)


@mcp.tool()
def gimp_list_recipes() -> list[dict[str, Any]]:
    """List tested multi-step recipes and their parameters."""
    return recipes.list_recipes()


@mcp.tool()
def gimp_run_recipe(name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run a recipe by name with parameters. Recipes are Python jobs executed inside GIMP with defaults applied."""
    try:
        module = recipes.get_recipe(name)
        resolved = recipes.resolve_params(name, params)
    except (KeyError, ValueError) as exc:
        raise ToolError(str(exc)) from exc
    code = "params = " + repr(resolved) + "\n" + module.SOURCE
    out = _call("exec", {"code": code}, timeout=600.0)
    return {"recipe": name, "params": resolved, "result": out.get("result"), "stdout": out.get("stdout", "")}


@mcp.tool()
def gimp_batch_recipe(
    name: str,
    input_glob: str,
    output_dir: str,
    params: dict[str, Any] | None = None,
    output_ext: str | None = None,
) -> dict[str, Any]:
    """Run a recipe over every file matching input_glob, writing to output_dir. Recipes must accept input_path and output_path."""
    try:
        module = recipes.get_recipe(name)
    except KeyError as exc:
        raise ToolError(str(exc)) from exc
    if "input_path" not in module.PARAMS or "output_path" not in module.PARAMS:
        raise ToolError(f"recipe {name} does not take input_path/output_path")
    files = sorted(glob.glob(os.path.expanduser(input_glob)))
    if not files:
        raise ToolError(f"no files match {input_glob}")
    out_dir = Path(os.path.expanduser(output_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for src in files:
        stem = Path(src).stem
        ext = output_ext or Path(src).suffix or ".png"
        if not ext.startswith("."):
            ext = "." + ext
        dst = str(out_dir / f"{stem}{ext}")
        try:
            resolved = recipes.resolve_params(name, {**(params or {}), "input_path": src, "output_path": dst})
            code = "params = " + repr(resolved) + "\n" + module.SOURCE
            out = _call("exec", {"code": code}, timeout=600.0)
            results.append({"input": src, "ok": True, "result": out.get("result")})
        except (RuntimeError, ValueError) as exc:
            results.append({"input": src, "ok": False, "error": str(exc)})
    return {"recipe": name, "count": len(results), "succeeded": sum(1 for r in results if r["ok"]), "results": results}


# --------------------------------------------------------------------------- prompts + resources


@mcp.prompt()
def gimp_workflow_guide() -> str:
    """How to work with GIMP effectively through this server."""
    return INSTRUCTIONS


@mcp.resource("gimp://recipes")
def recipes_resource() -> str:
    import json

    return json.dumps(recipes.list_recipes(), indent=2)


def run() -> None:
    mcp.run()
