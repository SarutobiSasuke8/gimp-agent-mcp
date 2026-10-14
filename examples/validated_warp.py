"""Warp and liquify: explicitly unsupported.

Run from a checkout (no GIMP required):

    python examples/validated_warp.py

Expected output
---------------
JSON on stdout, exit code 0, with ``status`` ``unsupported``.

The script calls the real surfaces and records their refusals:

- ``recipes.get_recipe("warp")`` raises KeyError. There is no warp recipe.
- ``gimp_canvas(image_id, "warp")`` raises ToolError before any bridge call.
  Valid canvas actions are scale, crop, resize, rotate, flip, merge_visible
  and flatten.
- ``gimp_adjust(layer_id, "liquify")`` raises ToolError before any bridge call.
  Liquify is not an adjustment.
- CLI commands parsed from ``gimp_agent_mcp.cli`` do not include a warp command.

No before/after pixel measurement of a warp exists in this repository. Do not
claim vector warp or liquify parity. Searching with ``gimp_filter_search`` or
``gimp_pdb_search`` (query ``warp`` or ``liquify``) only lists what the
installed GIMP exposes. A search hit is not a supported workflow. Applying one
and calling it validated needs a recorded before/after measurement on that
installed operation. This script does not apply one, because that would need
GIMP and would still not be a supported recipe.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gimp_agent_mcp import cli, recipes  # noqa: E402
from gimp_agent_mcp.server import ToolError, gimp_adjust, gimp_canvas  # noqa: E402


def cli_commands() -> list[str]:
    """Command names accepted by gimp_agent_mcp.cli.main."""
    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "main":
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Dict):
                continue
            keys = [key.value for key in child.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)]
            if "doctor" in keys and "smoke" in keys:
                return keys
    raise RuntimeError("could not read CLI commands from gimp_agent_mcp.cli")


def refusal(label: str, func, *args) -> str:
    try:
        func(*args)
    except (ToolError, KeyError, ValueError) as exc:
        return f"{type(exc).__name__}: {exc}"
    raise SystemExit(f"{label} did not fail")


def main() -> int:
    recipe_names = sorted(item["name"] for item in recipes.list_recipes())
    commands = cli_commands()
    warp_recipe = refusal("warp recipe", recipes.get_recipe, "warp")
    warp_canvas = refusal("warp canvas", gimp_canvas, 1, "warp")
    liquify_adjust = refusal("liquify adjust", gimp_adjust, 1, "liquify")

    for text, needle in (
        (warp_recipe, "unknown recipe 'warp'"),
        (warp_canvas, "unknown canvas action 'warp'"),
        (liquify_adjust, "unknown adjustment 'liquify'"),
    ):
        if needle not in text:
            raise SystemExit(f"unexpected refusal {text!r}")
    banned = ("warp", "liquify")
    if any(any(word in name for word in banned) for name in [*recipe_names, *commands]):
        raise SystemExit("a recipe or CLI command is named like a warp tool")

    report = {
        "expected_output": (
            "status unsupported. get_recipe('warp'), gimp_canvas(..., 'warp') and "
            "gimp_adjust(..., 'liquify') fail with the messages below. No pixels change."
        ),
        "needs_gimp": False,
        "status": "unsupported",
        "claim": "Vector warp/liquify parity is not claimed. There is no validated before/after measurement.",
        "recipes": recipe_names,
        "cli_commands": commands,
        "refusals": {
            "gimp_run_recipe": warp_recipe,
            "gimp_canvas": warp_canvas,
            "gimp_adjust": liquify_adjust,
        },
        "investigation_if_gimp_is_running": {
            "tools": ["gimp_filter_search", "gimp_pdb_search", "gimp_filter_describe", "gimp_pdb_describe"],
            "queries": ["warp", "liquify"],
            "do_not": "Do not invent an action, recipe name or CLI flag. Do not treat a search hit as supported.",
            "validated_would_mean": (
                "A saved before/after measurement of one installed operation: gimp_snapshot, "
                "the real procedure or GEGL name returned by describe, then gimp_measure or "
                "gimp_render_compare. That proof is not in this repository."
            ),
        },
    }
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
