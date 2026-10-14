"""Pure-Python helpers shared by the GIMP plug-in and the MCP server.

This module must not import ``gi``. It is copied next to the plug-in inside
GIMP's plug-in directory and is also imported by the MCP server and the unit
tests, so everything here has to run on a plain Python interpreter.
"""

from __future__ import annotations

import json
import math
import os
import re
import secrets
import time
from typing import Any

BRIDGE_VERSION = "0.5.0"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9877
BRIDGE_FILE_NAME = "agent-bridge.json"
PROCEDURE_NAME = "plug-in-gimp-agent-bridge"

# Default request timeout in seconds. Large images and slow filters can take a while.
DEFAULT_TIMEOUT = 180.0
RENDER_OVERLAYS = {"grid", "layers", "selection", "points"}


class UndoGroupRegistry:
    """Track agent-held undo groups without depending on GIMP or gi."""

    def __init__(self):
        self._held = {}
        self._depth = {}

    def open_groups(self):
        return [{"image_id": image_id, "name": group["name"]}
                for image_id, group in sorted(self._held.items())]

    def start(self, image, owner, name):
        image_id = image.get_id()
        if image_id in self._held:
            raise ValueError(f"image {image_id} already has an open agent undo group")
        if self._depth.get(image_id):
            raise ValueError("cannot open an agent undo group during an edit")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80 or "\n" in name or "\r" in name:
            raise ValueError("name must be 1..80 characters on one line")
        if not image.undo_is_enabled():
            raise ValueError("undo is disabled for this image")
        if not image.undo_group_start():
            raise ValueError("GIMP could not start the undo group")
        self._held[image_id] = {"image": image, "owner": owner, "name": name.strip()}
        return {"image_id": image_id, "name": name.strip(), "open": True}

    def end(self, image_id, owner):
        group = self._held.get(image_id)
        if group is None:
            raise ValueError(f"image {image_id} has no open agent undo group")
        if group["owner"] != owner:
            raise ValueError("only the client that opened this undo group can close it")
        if self._depth.get(image_id):
            raise ValueError("cannot close an agent undo group during an edit")
        if not group["image"].undo_group_end():
            raise ValueError("GIMP could not end the undo group")
        del self._held[image_id]
        return {"image_id": image_id, "name": group["name"], "open": False}

    def begin_op(self, image, owner):
        image_id = image.get_id()
        group = self._held.get(image_id)
        if group is not None and group["owner"] != owner:
            raise ValueError("another client holds this image's undo group")
        depth = self._depth.get(image_id, 0)
        if depth == 0 and group is None and not image.undo_group_start():
            raise ValueError("GIMP could not start the undo group")
        self._depth[image_id] = depth + 1
        return True

    def end_op(self, image):
        image_id = image.get_id()
        depth = self._depth.get(image_id, 0)
        if depth == 0:
            raise ValueError("undo group end without start")
        if depth > 1:
            self._depth[image_id] = depth - 1
        else:
            del self._depth[image_id]
            if image_id not in self._held and not image.undo_group_end():
                raise ValueError("GIMP could not end the undo group")

    def close_owner(self, owner):
        closed = []
        for image_id, group in list(self._held.items()):
            if group["owner"] != owner:
                continue
            try:
                group["image"].undo_group_end()
            except Exception:
                pass  # A closed image has no undo stack left to hold open.
            finally:
                del self._held[image_id]
            closed.append(image_id)
        return closed

def active_image_context(images, active_image_id=None, active_layer_ids=None, selection_bounds=None):
    """Build the JSON-safe user context for the active image from image summaries."""
    active = next((image for image in images if image["id"] == active_image_id), None)
    if active is None:
        return {
            "active_image_id": None,
            "active_layer_ids": [],
            "selection": None,
            "active_image_dirty": None,
        }

    bounds = selection_bounds or (False, 0, 0, 0, 0)
    non_empty, x1, y1, x2, y2 = bounds[-5:]
    return {
        "active_image_id": active["id"],
        "active_layer_ids": list(active_layer_ids or []),
        "selection": {"non_empty": bool(non_empty), "x1": x1, "y1": y1, "x2": x2, "y2": y2},
        "active_image_dirty": bool(active["dirty"]),
    }


def validate_render_overlay(overlay, points=None, grid_size=100):
    """Validate and normalise diagnostic-render arguments without importing GIMP."""
    if overlay is None:
        overlay = []
    if not isinstance(overlay, list) or any(not isinstance(value, str) for value in overlay):
        raise ValueError("overlay must be a list of strings")
    overlay = list(dict.fromkeys(value.lower() for value in overlay))
    unknown = sorted(set(overlay) - RENDER_OVERLAYS)
    if unknown:
        allowed = ", ".join(sorted(RENDER_OVERLAYS))
        raise ValueError(f"unknown render overlay(s): {', '.join(unknown)}; use {allowed}")
    grid_size = int(grid_size)
    if not 10 <= grid_size <= 2000:
        raise ValueError("grid_size must be between 10 and 2000 source pixels")
    points = points or []
    if not isinstance(points, list) or len(points) > 100:
        raise ValueError("points must be a list with at most 100 entries")
    clean_points = []
    for point in points:
        if not isinstance(point, dict) or "x" not in point or "y" not in point:
            raise ValueError("each point needs numeric x and y values")
        x, y = float(point["x"]), float(point["y"])
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("point coordinates must be finite")
        label = str(point.get("label", ""))
        if len(label) > 80:
            raise ValueError("point labels must be at most 80 characters")
        clean_points.append({"x": x, "y": y, "label": label})
    if clean_points and "points" not in overlay:
        overlay.append("points")
    return overlay, clean_points, grid_size

_NAMED_COLORS: dict[str, tuple[float, float, float]] = {
    "black": (0.0, 0.0, 0.0),
    "white": (1.0, 1.0, 1.0),
    "red": (1.0, 0.0, 0.0),
    "green": (0.0, 0.5, 0.0),
    "lime": (0.0, 1.0, 0.0),
    "blue": (0.0, 0.0, 1.0),
    "yellow": (1.0, 1.0, 0.0),
    "cyan": (0.0, 1.0, 1.0),
    "magenta": (1.0, 0.0, 1.0),
    "orange": (1.0, 0.647, 0.0),
    "grey": (0.5, 0.5, 0.5),
    "gray": (0.5, 0.5, 0.5),
    "transparent": (0.0, 0.0, 0.0),
}


# --------------------------------------------------------------------------- framing


def encode_message(payload: dict[str, Any]) -> bytes:
    """One JSON object per line. Compact separators keep base64 renders small."""
    return (json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def decode_message(line: bytes) -> dict[str, Any]:
    text = line.decode("utf-8").strip()
    if not text:
        raise ValueError("empty message")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("message must be a JSON object")
    return payload


# --------------------------------------------------------------------------- bridge file


def new_token() -> str:
    return secrets.token_urlsafe(32)


def write_bridge_file(path: str, *, port: int, token: str, pid: int, gimp_version: str, mode: str) -> dict[str, Any]:
    data = {
        "bridge_version": BRIDGE_VERSION,
        "host": DEFAULT_HOST,
        "port": int(port),
        "token": token,
        "pid": int(pid),
        "gimp_version": gimp_version,
        "mode": mode,
        "started": time.time(),
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    if os.name == "posix":
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return data


def read_bridge_file(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or "token" not in data or "port" not in data:
        return None
    return data


def load_or_create_token(path: str) -> str:
    """Reuse the token from an existing bridge file so clients survive GIMP restarts."""
    existing = read_bridge_file(path)
    if existing and isinstance(existing.get("token"), str) and len(existing["token"]) >= 16:
        return existing["token"]
    return new_token()


# --------------------------------------------------------------------------- colours


def parse_color(value: Any) -> tuple[float, float, float, float]:
    """Turn agent-friendly colour input into RGBA floats in 0..1.

    Accepts ``#rgb``, ``#rrggbb``, ``#rrggbbaa``, ``rgb(...)``/``rgba(...)`` with
    0..255 ints or 0..1 floats, a small set of CSS names, or a 3/4 element list.
    """
    if isinstance(value, (list, tuple)):
        if len(value) not in (3, 4):
            raise ValueError("colour list must have 3 or 4 components")
        comps = [float(c) for c in value]
        if any(c > 1.0 for c in comps[:3]):
            comps[:3] = [c / 255.0 for c in comps[:3]]
        if len(comps) == 3:
            comps.append(1.0)
        elif comps[3] > 1.0:
            comps[3] = comps[3] / 255.0
        return tuple(max(0.0, min(1.0, c)) for c in comps)  # type: ignore[return-value]

    if isinstance(value, dict):
        return parse_color([value.get("r", 0), value.get("g", 0), value.get("b", 0), value.get("a", 1)])

    if not isinstance(value, str):
        raise ValueError(f"unsupported colour value: {value!r}")

    text = value.strip().lower()
    if text in _NAMED_COLORS:
        r, g, b = _NAMED_COLORS[text]
        return (r, g, b, 0.0 if text == "transparent" else 1.0)

    if text.startswith("#"):
        hexpart = text[1:]
        if len(hexpart) in (3, 4):
            hexpart = "".join(ch * 2 for ch in hexpart)
        if len(hexpart) not in (6, 8):
            raise ValueError(f"bad hex colour: {value!r}")
        r, g, b = (int(hexpart[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
        a = int(hexpart[6:8], 16) / 255.0 if len(hexpart) == 8 else 1.0
        return (r, g, b, a)

    match = re.fullmatch(r"rgba?\(\s*([^)]+)\)", text)
    if match:
        parts = [p.strip() for p in match.group(1).replace("/", ",").split(",") if p.strip()]
        nums: list[float] = []
        for part in parts:
            if part.endswith("%"):
                nums.append(float(part[:-1]) / 100.0)
            else:
                nums.append(float(part))
        return parse_color(nums)

    raise ValueError(f"unrecognised colour: {value!r}")


def linear_to_srgb(c: float) -> float:
    """sRGB transfer function. GEGL reports colours as linear RGB; agents think in sRGB."""
    c = max(0.0, min(1.0, float(c)))
    return c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def srgb_to_linear(c: float) -> float:
    c = max(0.0, min(1.0, float(c)))
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def color_to_hex(rgba: tuple[float, float, float, float]) -> str:
    r, g, b, a = (max(0.0, min(1.0, c)) for c in rgba)
    out = f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"
    if a < 1.0:
        out += f"{round(a * 255):02x}"
    return out


# --------------------------------------------------------------------------- names


def normalise_key(name: str) -> str:
    """GObject property names use dashes; agents type underscores. Treat them as equal."""
    return name.strip().replace("_", "-").lower()


def normalise_enum_nick(value: Any) -> str:
    return str(value).strip().replace("_", "-").lower()


def match_key(wanted: str, candidates: list[str]) -> str | None:
    target = normalise_key(wanted)
    for cand in candidates:
        if normalise_key(cand) == target:
            return cand
    return None


def truncate(text: str, limit: int = 20000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated {len(text) - limit} chars]"


# Bounded batches cannot close documents, run arbitrary code or leave undo groups open.
EDIT_OPS = frozenset({"layer", "text", "select", "path", "layer_mask", "apply_filter"})


def validate_edit_steps(steps):
    if not isinstance(steps, list) or not 1 <= len(steps) <= 100:
        raise ValueError("steps must be a list containing 1 to 100 edits")
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or set(step) != {"op", "params"}:
            raise ValueError(f"step {index} must contain exactly op and params")
        if not isinstance(step["op"], str) or step["op"] not in EDIT_OPS:
            raise ValueError(f"step {index}: op must be one of {sorted(EDIT_OPS)}")
        if not isinstance(step["params"], dict):
            raise ValueError(f"step {index}: params must be an object")


def resolve_edit_refs(value, results):
    """Resolve {"$ref": "0.id"} against earlier step results; never evaluate code."""
    if isinstance(value, dict):
        if "$ref" in value:
            if set(value) != {"$ref"} or not isinstance(value["$ref"], str):
                raise ValueError("a reference must be an object with only a string $ref")
            parts = value["$ref"].split(".")
            if not parts[0].isdigit() or int(parts[0]) >= len(results):
                raise ValueError("reference must address a completed earlier step")
            result = results[int(parts[0])]
            try:
                for key in parts[1:]:
                    result = result[int(key)] if isinstance(result, list) and key.isdigit() else result[key]
            except (KeyError, IndexError, TypeError) as exc:
                raise ValueError(f"invalid reference {value['$ref']!r}") from exc
            return result
        return {k: resolve_edit_refs(v, results) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_edit_refs(v, results) for v in value]
    return value
