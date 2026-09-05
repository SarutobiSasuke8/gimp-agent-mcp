# gimp-agent-mcp

An MCP server that hands AI agents the whole of GIMP 3, not a curated slice of it.

Claude, Codex, Cursor and any other Model Context Protocol client can open images, inspect layers, call every one of GIMP's ~1000 Procedure Database functions, apply every GEGL filter destructively or as a non-destructive layer effect, see a render after each step, and run tested multi-step recipes such as "make this PNG a Telegram sticker". It is Windows-first and works on macOS and Linux.

## Why this exists

GIMP 3 has a complete Python API through GObject Introspection. Earlier GIMP MCP servers wrapped twenty or thirty of those calls by hand, used Unix sockets that do not exist on Windows Python, and gave the agent no way to see what it had just done. This server takes the opposite approach:

- **Generic, introspected access.** `gimp_pdb_search` -> `gimp_pdb_describe` -> `gimp_pdb_call` reaches any procedure with typed argument descriptions, enum choices and defaults pulled from GIMP at runtime. No hand-written wrapper goes stale when GIMP updates.
- **Every GEGL filter.** `gimp_filter_search` / `gimp_filter_describe` / `gimp_apply_filter` expose the 200+ GEGL operations behind GIMP's Filters menu, with `mode="append"` for GIMP 3's non-destructive layer effects.
- **Sight.** `gimp_render` returns a PNG of the current image state, downscaled or cropped to a region, so the agent can check its work instead of editing blind.
- **Recipes.** Repeatable jobs written once as Python that runs inside GIMP, with declared parameters, defaults and validation. `gimp_batch_recipe` runs one over a folder.
- **Windows-first transport.** TCP on `127.0.0.1` with a per-install token, because CPython on Windows has no `AF_UNIX`.
- **Escape hatch.** `gimp_run_python` executes Python inside GIMP with a persistent namespace, for anything the structured tools do not cover. It can be disabled with one environment variable.

## Requirements

- GIMP 3.0 or newer (tested on 3.2.4, Windows 11). GIMP 2.10 will not work: it has no Python 3 API.
- Python 3.11+ and [uv](https://docs.astral.sh/uv/) on the machine that runs the MCP client.

## Quick start

```bash
git clone https://github.com/SarutobiSasuke8/gimp-agent-mcp.git
cd gimp-agent-mcp
uv sync
uv run gimp-agent-mcp install-plugin   # copies the bridge plug-in into GIMP's plug-ins folder
uv run gimp-agent-mcp doctor           # shows what was found
uv run gimp-agent-mcp smoke            # launches headless GIMP and exercises every tool
```

Then add the server to your MCP client. For Claude Code, from the repo directory:

```bash
claude mcp add gimp -- uv run --directory "$(pwd)" gimp-agent-mcp serve
```

Or in a `.mcp.json` / `claude_desktop_config.json` (see `.mcp.json.example`):

```json
{
  "mcpServers": {
    "gimp": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/gimp-agent-mcp", "gimp-agent-mcp", "serve"]
    }
  }
}
```

The agent calls `gimp_launch` to start GIMP with the bridge running (`mode="gui"` for the normal window, `mode="headless"` for batch work with no UI). If GIMP is already open, click **Filters > Development > Start Agent Bridge** instead.

## Tools

| Tool | What it does |
|---|---|
| `gimp_status` | Is GIMP reachable? Version, mode, open images. |
| `gimp_launch` | Start GIMP 3 with the bridge (gui or headless) and wait for it. |
| `gimp_shutdown` | Stop the bridge; optionally quit GIMP. |
| `gimp_list_images` | Open images with ids, size, path, layer count. |
| `gimp_image_info` | Layer tree with item ids, channels, paths, selection, resolution. |
| `gimp_new_image` | Create an RGB image with one layer and a fill. |
| `gimp_open` | Open PNG, JPEG, WebP, XCF, PSD, SVG and anything else GIMP loads. |
| `gimp_export` | Export by extension. |
| `gimp_close_image` | Close without saving. |
| `gimp_render` | PNG of the current state; optional single layer or region crop. |
| `gimp_pdb_search` | Find PDB procedures by name words. |
| `gimp_pdb_describe` | Arguments, types, defaults, enum choices, return values. |
| `gimp_pdb_call` | Call any procedure with named arguments. |
| `gimp_filter_search` | Find GEGL operations. |
| `gimp_filter_describe` | A GEGL operation's properties. |
| `gimp_apply_filter` | Apply a GEGL operation to a layer, merged or as a layer effect. |
| `gimp_layer_effects` | List non-destructive filters on a layer. |
| `gimp_run_python` | Python inside GIMP, persistent namespace. Disable with `GIMP_AGENT_ALLOW_PYTHON=0`. |
| `gimp_list_recipes` | Available recipes and their parameters. |
| `gimp_run_recipe` | Run a recipe. |
| `gimp_batch_recipe` | Run a recipe over a glob of files. |

Argument conventions: images and items are integer ids; colours are `"#rrggbb"`, `"white"`, `"rgb(255,0,0)"` or `[r,g,b,a]`; enums are nicks like `"clip-to-image"`; dashes and underscores in names are interchangeable. `run-mode` defaults to non-interactive.

## Recipes

| Recipe | Purpose |
|---|---|
| `telegram_sticker` | Fit artwork into a 512x512 transparent canvas, add a white outline and a soft shadow, export PNG. |
| `fit_and_export` | Scale to a maximum edge length and export by extension. |

Recipes live in `src/gimp_agent_mcp/recipes/`. Each is a module with `DESCRIPTION`, `PARAMS` and `SOURCE`; see `docs/RECIPES.md` to add one.

## How it works

```text
MCP client  --stdio-->  gimp-agent-mcp (server.py)  --TCP 127.0.0.1:9877 + token-->  bridge plug-in inside GIMP 3
                                                                                        |
                                                                    GLib main loop runs each request on the plug-in
                                                                    main thread against libgimp / GEGL / the PDB
```

The plug-in writes `agent-bridge.json` (port, token, pid) into GIMP's per-user config directory. The server reads it to connect. Details in `docs/ARCHITECTURE.md`.

## Security

The bridge listens on loopback only and requires the token on every request. `gimp_run_python` and `gimp_pdb_call` are, by design, arbitrary code execution inside GIMP with the permissions of the user running it: give this server only to clients you trust with your files. See `SECURITY.md`.

## Provenance

Clean-room implementation under Apache-2.0. The author read the existing GPL and MIT GIMP MCP projects for lessons about the GIMP 3.2 API and copied no code from them.

## Status

`0.1.0`, alpha. Verified end to end on Windows 11 with GIMP 3.2.4 via `gimp-agent-mcp smoke`. macOS and Linux paths are implemented but not yet exercised on real machines. See `ROADMAP.md`.
