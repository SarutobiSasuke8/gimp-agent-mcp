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


# --------------------------------------------------------------------------- cancellation and progress

# Ops a running operation answers between its own steps. Every other request waits its turn.
CONTROL_OPS = frozenset({"cancel", "jobs"})
# Error type and message a bridge returns once a shutdown has been requested. Clients treat it as "no bridge".
STOPPING_ERROR = "BridgeStopping"
STOPPING_MESSAGE = "this bridge is shutting down; launch GIMP again or start the bridge from the Filters menu"
PROGRESS_INTERVAL = 0.25


class OperationCancelled(Exception):
    """Raised at a checkpoint after gimp_cancel asked the running operation to stop."""


class Job:
    """The one operation the bridge is running. Long paths call ``checkpoint`` between steps."""

    def __init__(self, tracker, request_id, op, image_id=None, send_progress=None):
        self.tracker = tracker
        self.request_id = request_id
        self.op = op
        self.image_id = image_id
        self.send_progress = send_progress
        self.started = tracker.clock()
        self.fraction = None
        self.text = ""
        self.cancel_requested = False
        self.checkpoints = 0
        self._last_sent = None

    def summary(self):
        return {
            "request_id": self.request_id,
            "op": self.op,
            "image_id": self.image_id,
            "elapsed_seconds": round(self.tracker.clock() - self.started, 3),
            "fraction": self.fraction,
            "text": self.text,
            "cancel_requested": self.cancel_requested,
        }

    def checkpoint(self, fraction=None, text=None, cancellable=True):
        """Record progress, answer pending control requests and stop here if a cancel arrived."""
        self.checkpoints += 1
        if fraction is not None:
            fraction = float(fraction)
            self.fraction = max(0.0, min(1.0, fraction)) if math.isfinite(fraction) else None
        if text is not None:
            self.text = str(text)[:200]
        now = self.tracker.clock()
        if self.send_progress is not None and (
            self._last_sent is None or now - self._last_sent >= PROGRESS_INTERVAL or self.fraction == 1.0
        ):
            self._last_sent = now
            try:
                self.send_progress({"fraction": self.fraction, "text": self.text,
                                    "elapsed_seconds": round(now - self.started, 3)})
            except OSError:
                self.send_progress = None  # the client went away; keep working, the final send will fail cleanly
        if self.tracker.poll is not None:
            self.tracker.poll()
        if cancellable and self.cancel_requested:
            raise OperationCancelled(
                f"{self.op} was cancelled at a checkpoint"
                + (f" ({self.text})" if self.text else "")
                + "; work done before the checkpoint is kept, see the operation's recovery notes"
            )


class JobTracker:
    """Tracks the running operation. The plug-in has no threads, so there is at most one."""

    def __init__(self, poll=None, clock=time.monotonic):
        self.poll = poll
        self.clock = clock
        self.current = None

    def start(self, request_id, op, image_id=None, send_progress=None):
        job = Job(self, request_id, op, image_id=image_id, send_progress=send_progress)
        self.current = job
        return job

    def finish(self, job):
        if self.current is job:
            self.current = None

    def checkpoint(self, fraction=None, text=None, cancellable=True):
        """Checkpoint the running job; a no-op outside one, so recipes can call it unconditionally."""
        if self.current is not None:
            self.current.checkpoint(fraction, text, cancellable)

    def cancel(self, image_id=None, request_id=None):
        job = self.current
        if job is None:
            return {"cancel_requested": False, "reason": "no operation is running", "running": None}
        if request_id is not None and request_id != job.request_id:
            return {"cancel_requested": False, "reason": "the running operation has another request id", "running": job.summary()}
        if image_id is not None and job.image_id is not None and int(image_id) != int(job.image_id):
            return {"cancel_requested": False, "reason": f"the running operation targets image {job.image_id}", "running": job.summary()}
        job.cancel_requested = True
        return {"cancel_requested": True, "running": job.summary(),
                "note": "the operation stops at its next checkpoint; a single GEGL merge in progress cannot be interrupted"}

    def status(self):
        return {"running": self.current.summary() if self.current is not None else None}


def split_control_requests(buffer, token):
    """Pull authorised control requests (cancel, jobs) out of a connection's receive buffer.

    Returns ``(remaining, controls)``. Complete lines that are not control requests, and any trailing partial
    line, stay in ``remaining`` in their original order, so ordinary requests run after the current operation
    exactly as if they had never been looked at. Malformed lines and bad tokens are left for the normal handler
    to reject.
    """
    controls = []
    kept = []
    *lines, tail = buffer.split(b"\n")
    for line in lines:
        if line.strip():
            try:
                message = decode_message(line)
            except (ValueError, UnicodeDecodeError):
                message = None
            if message is not None and message.get("op") in CONTROL_OPS and message.get("token") == token:
                controls.append(message)
                continue
        kept.append(line + b"\n")
    return b"".join(kept) + tail, controls
