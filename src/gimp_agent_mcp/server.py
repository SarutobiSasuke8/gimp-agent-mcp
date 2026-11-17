"""gimp-agent-mcp: the MCP server. Thin over the bridge; the heavy lifting runs inside GIMP."""

from __future__ import annotations

import base64
import glob
import os
import re
import threading
from pathlib import Path
from typing import Any, Literal

import anyio.from_thread
from mcp.server.mcpserver import Context, Image, MCPServer

try:  # mcp >= 2 reports ToolError as a clean tool failure instead of a server traceback
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # pragma: no cover
    ToolError = RuntimeError  # type: ignore[misc,assignment]

from . import brands, recipes
from .bridge_client import BridgeClient, BridgeError, BridgeUnavailable, launch_gimp

ALLOW_PYTHON = os.environ.get("GIMP_AGENT_ALLOW_PYTHON", "0").strip().lower() not in ("0", "false", "no", "off")

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
- Many other GIMP operations are PDB procedures: gimp_pdb_search -> gimp_pdb_describe -> gimp_pdb_call.
  Arguments are passed by name; images and items are passed as their ids; colours as "#rrggbb", "white" or
  "rgb(255,0,0)"; enums by nick such as "clip-to-image". run-mode defaults to noninteractive.
- gimp_edit_batch groups supported edits into one Ctrl+Z step. Inspect complete/error; failures preserve partial work.
- gimp_undo_group holds one image's edits across calls. Start it before the turn, end it in a finally step,
  and check gimp_status for abandoned groups. A lost connection closes the group automatically.
- gimp_context reports selected layers for an explicit image, never guesses the focused document.
- gimp_run_python executes Python inside GIMP with Gimp, Gegl, Gio available and a persistent namespace.
  Prefer it for multi-step work; the expression value or a variable named `result` comes back. This tool is
  opt-in: set GIMP_AGENT_ALLOW_PYTHON=1 to enable it.
- Recipes are tested multi-step jobs (gimp_list_recipes). Prefer a recipe over re-deriving the steps.
- Exports go through gimp_export; the extension selects the format. Save working files as .xcf.
- If nothing responds, gimp_status tells you whether GIMP is running; gimp_launch starts it.
- gimp_help(topic) has worked examples for filters, colours, text, masks, paths, layers, measuring, recipes and
  compose-from-manifest. Call it before improvising.
"""

mcp = MCPServer("gimp-agent-mcp", instructions=INSTRUCTIONS)
_client = BridgeClient()
# gimp_batch_recipe loops in this process, so gimp_cancel also stops it between files.
_batch_cancel = threading.Event()
_batch_active = threading.Event()
# gimp_shutdown waits at most this long for the bridge, its bridge file and its plug-in process to go.
SHUTDOWN_WAIT_SECONDS = 30.0


def _progress_reporter(ctx: Context | None, start: float = 0.0, span: float = 1.0):
    """Turn bridge progress lines into MCP progress notifications (0..100) for a sync tool's request.

    Sync tools run in an anyio worker thread, so the async notification is sent through anyio.from_thread.
    Progress only ever increases, as MCP requires. Returns None when there is no request context."""
    if ctx is None:
        return None
    last = [0.0]

    def report(progress: dict[str, Any]) -> None:
        fraction = progress.get("fraction")
        value = last[0] if fraction is None else max(last[0], round(100.0 * (start + span * float(fraction)), 1))
        last[0] = value
        try:
            anyio.from_thread.run(ctx.report_progress, value, 100.0, progress.get("text") or None)
        except Exception:  # noqa: BLE001 - progress is best effort; the reply still arrives
            pass

    return report


def _call(op: str, params: dict[str, Any] | None = None, timeout: float | None = None, progress=None) -> Any:
    try:
        if progress is not None:
            return _client.call(op, params, timeout=timeout, on_progress=progress)
        return _client.call(op, params, timeout=timeout)
    except BridgeUnavailable as exc:
        raise ToolError(str(exc)) from exc
    except BridgeError as exc:
        detail = f"{exc.error_type}: {exc}"
        if exc.error_type == "UnknownOp":
            detail += " The installed GIMP bridge may be older than this server. Run gimp-agent-mcp install-plugin and restart GIMP."
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
    """Check whether GIMP and the bridge are reachable, including the active image, selected layers and selection."""
    info = _client.ping()
    if info is None:
        from . import paths

        exes = paths.find_gimp()
        return {
            "connected": False,
            "gimp_found": str(exes.any) if exes.any else None,
            "plugin_installed": bool(paths.plugin_install_dir() and (paths.plugin_install_dir() / "gimp-agent-bridge.py").is_file()),
            "hint": "Call gimp_launch(mode='gui'|'headless'), or start Filters > Development > Start Agent Bridge inside GIMP.",
            **paths.bridge_freshness(),
        }
    info["connected"] = True
    info["python_tool_enabled"] = ALLOW_PYTHON
    return {**info, **_freshness(info)}


def _freshness(info: dict[str, Any]) -> dict[str, Any]:
    from . import paths

    return paths.bridge_freshness(info.get("bridge_version"))


@mcp.tool()
def gimp_launch(mode: str = "gui", wait_seconds: int = 90) -> dict[str, Any]:
    """Start GIMP 3 with the bridge running. mode='gui' opens the normal window; 'headless' runs gimp-console with no UI."""
    running = _client.ping()
    if running:
        return {"already_running": True, **running, **_freshness(running)}
    try:
        launched = launch_gimp(mode=mode, wait_seconds=float(wait_seconds), client=_client)
        return {**launched, **_freshness(launched.get("ping") or {})}
    except (BridgeUnavailable, FileNotFoundError, ValueError) as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def gimp_shutdown(quit_gimp: bool | None = None) -> dict[str, Any]:
    """Stop the bridge and wait up to 30 s until it is gone. quit_gimp defaults to True for headless sessions and False for the GUI (unsaved work is not prompted for). fully_exited is true once GIMP was asked to quit and the bridge port is closed, its bridge file removed and (on POSIX) its plug-in process ended; it is false on a timeout, with what was still present in detail."""
    try:
        result = _client.shutdown_and_wait(quit_gimp=quit_gimp, wait_seconds=SHUTDOWN_WAIT_SECONDS)
    except BridgeUnavailable as exc:
        raise ToolError(str(exc)) from exc
    except BridgeError as exc:
        if exc.error_type != "ShutdownTimeout":
            raise ToolError(f"{exc.error_type}: {exc}") from exc
        # The bridge accepted the shutdown but did not disappear in time: report that rather than fail the call.
        return {
            "stopping": True,
            "stopped": False,
            "fully_exited": False,
            "timed_out": True,
            "waited": SHUTDOWN_WAIT_SECONDS,
            "detail": str(exc),
        }
    finally:
        _client.close()
    if result.get("already_stopped"):
        # Nothing answered, so there was nothing to wait for; whether a GIMP without a bridge is open is unknown.
        return {**result, "timed_out": False, "fully_exited": None, "detail": "no bridge was running"}
    return {**result, "timed_out": False, "fully_exited": bool(result.get("stopped") and result.get("quit_gimp"))}


@mcp.tool()
def gimp_context(image_id: int | None = None, selected_layer_ids: list[int] | None = None, present: bool = False) -> dict[str, Any]:
    """Read one document's selected layers, selection bounds and bridge colour/brush context. Pass image_id when multiple images are open; use gimp_status for the active user display. Optionally select layers or present a GUI document."""
    return _call("context", {"image_id": image_id, "selected_layer_ids": selected_layer_ids, "present": present})


@mcp.tool()
def gimp_edit_batch(image_id: int, steps: list[dict[str, Any]], ctx: Context | None = None) -> dict[str, Any]:
    """Run 1..100 edits on one image in ONE undo group. steps=[{op:'layer'|'text'|'select'|'path'|'layer_mask'|'apply_filter', params:{...}}]. Params use the corresponding tool arguments; image_id is injected. Reference an earlier result with {'$ref':'0.id'}. Check complete/error: failure stops later steps, preserves partial work, and always closes the undo group. One Ctrl+Z in GIMP reverts it; this is not automatic rollback or programmatic undo. No edits by another bridge request interleave within the batch. Reports progress per step; gimp_cancel stops it before the next step (cancelled=true)."""
    return _call("edit_batch", {"image_id": image_id, "steps": steps}, progress=_progress_reporter(ctx))


@mcp.tool()
def gimp_undo_group(image_id: int, action: Literal["start", "end"], name: str | None = None) -> dict[str, Any]:
    """Hold one image's edits across tool calls as one GIMP undo step. Start with a short name, then always end it. A lost bridge connection closes the group; gimp_status lists open groups. GIMP's public API does not show the custom name in Undo History."""
    return _call("undo_group", {"image_id": image_id, "action": action, "name": name})


# --------------------------------------------------------------------------- images


@mcp.tool()
def gimp_list_images() -> dict[str, Any]:
    """List open images and report the active image, selected layers, selection bounds and dirty state."""
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
    overlay: list[str] | None = None,
    points: list[dict[str, Any]] | None = None,
    grid_size: int = 100,
) -> Image:
    """Render an image as PNG. layer_id isolates a layer; region crops. Diagnostic overlays may include grid, layers, selection and points. points=[{"x": 100, "y": 80, "label": "target"}]. Overlays affect only the returned preview."""
    result = _call("render", {"image_id": image_id, "layer_id": layer_id, "max_size": max_size,
                              "region": region, "overlay": overlay, "points": points, "grid_size": grid_size})
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
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Apply a GEGL operation to a layer. mode='merge' bakes it in; mode='append' adds a non-destructive layer effect. Examples: white outline = op="gegl:dropshadow", params={"x":0,"y":0,"radius":0,"grow-radius":8,"color":"white"}; soft shadow = {"x":0,"y":6,"radius":12,"opacity":0.4}; blur = op="gegl:gaussian-blur", params={"std-dev-x":4,"std-dev-y":4}. gimp_help("filters") lists the useful ops. A merge already in progress cannot be interrupted; for heavy work on large images prefer a recipe."""
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
        progress=_progress_reporter(ctx),
    )


_ADJUST_FILTERS: dict[str, tuple[str, dict[str, Any]]] = {
    "brightness_contrast": ("gegl:brightness-contrast", {}),
    "hue_saturation": ("gegl:hue-chroma", {}),
    "desaturate": ("gegl:saturation", {"scale": 0.0}),
    "invert": ("gegl:invert-gamma", {}),
    "blur": ("gegl:gaussian-blur", {}),
    "sharpen": ("gegl:unsharp-mask", {}),
    "noise": ("gegl:noise-rgb", {}),
    "pixelate": ("gegl:pixelize", {}),
}


def _normalise_adjust_params(action: str, params: dict[str, Any]) -> dict[str, Any]:
    out = dict(params)
    if action == "hue_saturation" and "saturation" in out and "chroma" not in out:
        out["chroma"] = out.pop("saturation")
    if action == "blur" and "radius" in out:
        radius = out.pop("radius")
        out.setdefault("std-dev-x", radius)
        out.setdefault("std-dev-y", radius)
    if action == "sharpen":
        if "radius" in out and "std-dev" not in out:
            out["std-dev"] = out.pop("radius")
        if "amount" in out and "scale" not in out:
            out["scale"] = out.pop("amount")
    if action == "noise" and "amount" in out:
        amount = out.pop("amount")
        for channel in ("red", "green", "blue"):
            out.setdefault(channel, amount)
    if action == "pixelate" and "size" in out:
        # truncated for brevity in this example; full file would continue as original
