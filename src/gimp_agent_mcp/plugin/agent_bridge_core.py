"""Pure-Python helpers shared by the GIMP plug-in and the MCP server.

This module must not import ``gi``. It is copied next to the plug-in inside
GIMP's plug-in directory and is also imported by the MCP server and the unit
tests, so everything here has to run on a plain Python interpreter.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from typing import Any

BRIDGE_VERSION = "0.2.3"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9877
BRIDGE_FILE_NAME = "agent-bridge.json"
PROCEDURE_NAME = "plug-in-gimp-agent-bridge"

# Default request timeout in seconds. Large images and slow filters can take a while.
DEFAULT_TIMEOUT = 180.0

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
