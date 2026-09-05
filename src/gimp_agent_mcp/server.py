"""gimp-agent-mcp: the MCP server. Thin over the bridge; the heavy lifting runs inside GIMP."""

from __future__ import annotations

import base64
import glob
import os
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import Image, MCPServer

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
"""

mcp = MCPServer("gimp-agent-mcp", instructions=INSTRUCTIONS)
_client = BridgeClient()


def _call(op: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
    try:
        return _client.call(op, params, timeout=timeout)
    except BridgeUnavailable as exc:
        raise RuntimeError(str(exc)) from exc
    except BridgeError as exc:
        detail = f"{exc.error_type}: {exc}"
        if exc.trace:
            detail += "\n" + exc.trace[-1500:]
        raise RuntimeError(detail) from exc


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
        raise RuntimeError(str(exc)) from exc


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
def gimp_export(image_id: int, path: str) -> dict[str, Any]:
    """Export an image; the extension chooses the format (.png .webp .jpg .tiff .bmp .gif .xcf). Uses GIMP's defaults; call file-*-export via gimp_pdb_call for fine control."""
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
    """Call any PDB procedure by name with arguments keyed by name. Pass images/items as ids, colours as strings, enums by nick."""
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
    """Apply a GEGL operation to a layer. mode='merge' bakes it in; mode='append' adds a non-destructive layer effect."""
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
        raise RuntimeError(str(exc)) from exc
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
        raise RuntimeError(str(exc)) from exc
    if "input_path" not in module.PARAMS or "output_path" not in module.PARAMS:
        raise RuntimeError(f"recipe {name} does not take input_path/output_path")
    files = sorted(glob.glob(os.path.expanduser(input_glob)))
    if not files:
        raise RuntimeError(f"no files match {input_glob}")
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
