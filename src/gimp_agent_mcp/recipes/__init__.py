"""Recipes: repeatable multi-step GIMP jobs, written as plain Python that runs inside GIMP.

Each recipe module defines:

- ``DESCRIPTION``: one sentence.
- ``PARAMS``: dict of ``name -> {"type", "default", "description"}``; ``required: True`` when no default.
- ``SOURCE``: the Python code executed inside GIMP. It receives ``params`` (dict, defaults
  already applied), ``Gimp``, ``Gegl``, ``Gio``, ``GLib``, ``GObject``, ``image_by_id``,
  ``item_by_id`` and ``make_color`` in its namespace, and must assign ``result``.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any

_REGISTRY: dict[str, Any] | None = None


def _load() -> dict[str, Any]:
    global _REGISTRY
    if _REGISTRY is None:
        reg: dict[str, Any] = {}
        for mod in pkgutil.iter_modules(__path__):
            if mod.name.startswith("_"):
                continue
            module = importlib.import_module(f"{__name__}.{mod.name}")
            if hasattr(module, "SOURCE") and hasattr(module, "PARAMS"):
                reg[mod.name] = module
        _REGISTRY = reg
    return _REGISTRY


def list_recipes() -> list[dict[str, Any]]:
    out = []
    for name, module in sorted(_load().items()):
        out.append({"name": name, "description": getattr(module, "DESCRIPTION", ""), "params": module.PARAMS})
    return out


def get_recipe(name: str):
    module = _load().get(name)
    if module is None:
        raise KeyError(f"unknown recipe {name!r}; available: {sorted(_load())}")
    return module


def resolve_params(name: str, given: dict[str, Any] | None) -> dict[str, Any]:
    module = get_recipe(name)
    given = dict(given or {})
    unknown = [k for k in given if k not in module.PARAMS]
    if unknown:
        raise ValueError(f"unknown parameter(s) {unknown} for recipe {name}; valid: {sorted(module.PARAMS)}")
    resolved: dict[str, Any] = {}
    for key, spec in module.PARAMS.items():
        if key in given:
            resolved[key] = given[key]
        elif spec.get("required"):
            raise ValueError(f"recipe {name} requires parameter {key!r}")
        else:
            resolved[key] = spec.get("default")
    return resolved
