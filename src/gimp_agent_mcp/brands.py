"""Brand kits: named colour, font, asset and canvas profiles that compose manifests reference by token.

A profile is a JSON file in the brands directory (see ``brands_dir``). A manifest names it with
``"brand": "<name>"`` and then uses ``"@key"`` tokens wherever a literal colour, font name or asset path
would go, plus ``"canvas": "<canvas key>"`` instead of ``width``/``height``. Resolution happens in the
MCP server before the recipe is sent to GIMP, so the recipe itself only ever sees literal values.

This module is pure Python: no GIMP, no network. Font names are checked against the running GIMP by the
server tool (``gimp_brand(action="set")``), not here.
"""

from __future__ import annotations

import copy
import json
import os
import platform
import re
from pathlib import Path
from typing import Any

from .plugin import agent_bridge_core as core

SECTIONS = ("colors", "fonts", "assets", "canvases")
TOKEN_SECTIONS = ("colors", "fonts", "assets")
ALLOWED_KEYS = {"name", "description", *SECTIONS}
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
MAX_CANVAS_EDGE = 30000
# Free text in a manifest is never treated as a token, so "@handle" in a caption stays literal.
NON_TOKEN_KEYS = frozenset({"text", "name"})
# Manifest keys consumed by resolution and removed from the resolved manifest.
RESOLUTION_KEYS = ("brand", "canvas", "tokens")


class BrandError(ValueError):
    """A profile or manifest token problem. The message lists every problem found."""


# --------------------------------------------------------------------------- storage


def brands_dir() -> Path:
    """Where profiles live: GIMP_AGENT_BRANDS_DIR, else the per-user config directory for gimp-agent-mcp."""
    override = os.environ.get("GIMP_AGENT_BRANDS_DIR")
    if override:
        return Path(os.path.expanduser(override))
    system = platform.system()
    if system == "Windows" and os.environ.get("APPDATA"):
        base = Path(os.environ["APPDATA"])
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "gimp-agent-mcp" / "brands"


def _check_name(name: Any) -> str:
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise BrandError(
            f"brand name {name!r} is invalid: use 1-64 lowercase letters, digits, '-' or '_', starting with a letter or digit"
        )
    return name


def profile_path(name: str, directory: Path | None = None) -> Path:
    return (directory or brands_dir()) / f"{_check_name(name)}.json"


def list_profiles(directory: Path | None = None) -> list[dict[str, Any]]:
    """Summaries of every stored profile. Unreadable or invalid files are reported, not hidden."""
    root = directory or brands_dir()
    out: list[dict[str, Any]] = []
    if not root.is_dir():
        return out
    for path in sorted(root.glob("*.json")):
        entry: dict[str, Any] = {"name": path.stem, "path": str(path)}
        try:
            profile = load_profile(path.stem, root)
        except BrandError as exc:
            entry["error"] = str(exc)
        else:
            entry["description"] = profile.get("description", "")
            for section in SECTIONS:
                entry[section] = sorted(profile.get(section, {}))
        out.append(entry)
    return out


def load_profile(name: str, directory: Path | None = None) -> dict[str, Any]:
    root = directory or brands_dir()
    path = profile_path(name, root)
    if not path.is_file():
        available = [p.stem for p in sorted(root.glob("*.json"))] if root.is_dir() else []
        raise BrandError(f"no brand profile named {name!r} in {root}; available: {available}")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise BrandError(f"brand profile {name!r} could not be read from {path}: {exc}") from exc
    profile = validate_profile(data)
    if profile["name"] != name:
        raise BrandError(f"brand profile file {path.name} declares name {profile['name']!r}; it must match the file name")
    return profile


def save_profile(profile: dict[str, Any], directory: Path | None = None) -> Path:
    clean = validate_profile(profile)
    root = directory or brands_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = profile_path(clean["name"], root)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(clean, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)
    return path


def delete_profile(name: str, directory: Path | None = None) -> Path:
    root = directory or brands_dir()
    path = profile_path(name, root)
    if not path.is_file():
        raise BrandError(f"no brand profile named {name!r} in {root}")
    path.unlink()
    return path


# --------------------------------------------------------------------------- schema


def validate_profile(data: Any) -> dict[str, Any]:
    """Return a normalised copy of a profile or raise BrandError listing every problem."""
    if not isinstance(data, dict):
        raise BrandError("a brand profile must be a JSON object")
    problems: list[str] = []
    unknown = sorted(set(data) - ALLOWED_KEYS)
    if unknown:
        problems.append(f"unknown top-level key(s) {unknown}; allowed: {sorted(ALLOWED_KEYS)}")
    try:
        name = _check_name(data.get("name"))
    except BrandError as exc:
        problems.append(str(exc))
        name = None
    description = data.get("description", "")
    if not isinstance(description, str):
        problems.append("description must be a string")
    clean: dict[str, Any] = {"name": name}
    if description:
        clean["description"] = description

    for section in SECTIONS:
        values = data.get(section, {})
        if not isinstance(values, dict):
            problems.append(f"{section} must be an object of key -> value")
            continue
        out: dict[str, Any] = {}
        for key, value in values.items():
            where = f"{section}.{key}"
            if not isinstance(key, str) or not KEY_RE.match(key):
                problems.append(f"{where}: key must be 1-64 letters, digits, '-' or '_'")
                continue
            if section == "colors":
                if not isinstance(value, str):
                    problems.append(f"{where}: colour must be a string such as '#0f1117'")
                    continue
                try:
                    core.parse_color(value)
                except ValueError as exc:
                    problems.append(f"{where}: {exc}")
                    continue
                out[key] = value
            elif section in ("fonts", "assets"):
                if not isinstance(value, str) or not value.strip():
                    problems.append(f"{where}: must be a non-empty string")
                    continue
                out[key] = value
            else:  # canvases
                if (
                    not isinstance(value, (list, tuple))
                    or len(value) != 2
                    or any(type(v) is not int or not 1 <= v <= MAX_CANVAS_EDGE for v in value)
                ):
                    problems.append(f"{where}: canvas must be [width, height] with integers 1..{MAX_CANVAS_EDGE}")
                    continue
                out[key] = [int(value[0]), int(value[1])]
        if out:
            clean[section] = out

    seen: dict[str, str] = {}
    for section in TOKEN_SECTIONS:
        for key in clean.get(section, {}):
            if key in seen:
                problems.append(f"token key {key!r} is defined in both {seen[key]} and {section}; token keys must be unique")
            seen[key] = section

    if problems:
        label = f"brand profile {name!r}" if name else "brand profile"
        raise BrandError(f"{label} is invalid: " + "; ".join(problems))
    return clean


def token_table(profile: dict[str, Any]) -> dict[str, Any]:
    """Flat key -> value table of the token sections."""
    table: dict[str, Any] = {}
    for section in TOKEN_SECTIONS:
        table.update(profile.get(section, {}))
    return table


# --------------------------------------------------------------------------- resolution


def manifest_uses_brand(manifest: Any) -> bool:
    return isinstance(manifest, dict) and any(key in manifest for key in RESOLUTION_KEYS)


def resolve_manifest(
    manifest: dict[str, Any],
    brand: str | None = None,
    directory: Path | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a copy of ``manifest`` with brand tokens replaced by literal values.

    Precedence, highest first: a literal value in the manifest (it is never touched); the manifest's own
    ``tokens`` object; the profile. ``width``/``height`` in the manifest win over ``canvas``. ``brand``
    (the argument) is used when the manifest has no ``brand`` key. ``@@`` escapes a literal leading ``@``.
    """
    if not isinstance(manifest, dict):
        raise BrandError("manifest must be an object")
    out = copy.deepcopy(manifest)
    name = out.pop("brand", None) or brand or None
    canvas = out.pop("canvas", None)
    local = out.pop("tokens", None) or {}
    if not isinstance(local, dict):
        raise BrandError("manifest 'tokens' must be an object of key -> value")

    if profile is None and name:
        profile = load_profile(str(name), directory)
    profile = profile or {"name": None}
    label = f"brand profile {profile['name']!r}" if profile.get("name") else "the manifest (no brand profile named)"
    table = {**token_table(profile), **local}

    if canvas is not None:
        canvases = profile.get("canvases", {})
        if not isinstance(canvas, str) or canvas not in canvases:
            raise BrandError(f"unknown canvas {canvas!r} in {label}; available canvases: {sorted(canvases)}")
        width, height = canvases[canvas]
        out.setdefault("width", width)
        out.setdefault("height", height)

    def lookup(token: str, where: str) -> Any:
        key = token[1:]
        if key not in table:
            raise BrandError(f"unknown token {token!r} at {where} in {label}; available keys: {sorted(table)}")
        return table[key]

    def walk(value: Any, where: str, key: str | None) -> Any:
        if isinstance(value, dict):
            return {k: walk(v, f"{where}.{k}", k) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v, f"{where}[{i}]", key) for i, v in enumerate(value)]
        if isinstance(value, str) and key not in NON_TOKEN_KEYS:
            if value.startswith("@@"):
                return value[1:]
            if value.startswith("@"):
                return lookup(value, where)
        return value

    return walk(out, "manifest", None)


def prepare_compose_params(params: dict[str, Any], directory: Path | None = None) -> dict[str, Any]:
    """Resolve brand tokens in compose recipe params. Returns params unchanged when no brand is involved.

    A ``manifest_path`` manifest is read here only when it is needed (``brand`` param set, or the file names
    a brand, canvas or tokens), then passed inline so GIMP never sees an unresolved token.
    """
    brand = params.get("brand") or None
    manifest = params.get("manifest")
    from_file = False
    if not manifest and params.get("manifest_path"):
        path = Path(os.path.expanduser(str(params["manifest_path"])))
        try:
            with open(path, encoding="utf-8") as fh:
                manifest = json.load(fh)
        except (OSError, ValueError) as exc:
            if brand:
                raise BrandError(f"could not read manifest_path {path} to apply brand {brand!r}: {exc}") from exc
            return params
        from_file = True
    if not isinstance(manifest, dict) or not (brand or manifest_uses_brand(manifest)):
        return params
    resolved = resolve_manifest(manifest, brand=brand, directory=directory)
    out = dict(params)
    out["manifest"] = resolved
    if from_file:
        out["manifest_path"] = ""
    return out
