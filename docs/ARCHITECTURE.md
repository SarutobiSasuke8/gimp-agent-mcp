# Architecture

## Processes

```text
+--------------------+   stdio    +---------------------------+   TCP 127.0.0.1:9877   +------------------------------+
| MCP client         | <--------> | gimp-agent-mcp (server)   | <--------------------> | GIMP 3                       |
| Claude, Codex, ... |            | src/gimp_agent_mcp/       |   newline JSON + token | plug-in: gimp-agent-bridge.py|
+--------------------+            +---------------------------+                        +------------------------------+
```

The server never links to GIMP. It only speaks the bridge protocol, so it runs on whatever Python the MCP client uses. The plug-in runs on GIMP's bundled Python (3.14 in GIMP 3.2) with PyGObject, and is the only place libgimp, GEGL and the PDB are touched.

## Bridge protocol

One JSON object per line, UTF-8, both directions.

Request:

```json
{"id": "hex", "token": "...", "op": "pdb_call", "params": {"name": "gimp-image-scale", "args": {"image": 3, "new-width": 512, "new-height": 512}}}
```

Response:

```json
{"id": "hex", "ok": true, "result": {...}}
{"id": "hex", "ok": false, "error": {"type": "BridgeError", "message": "...", "traceback": "..."}}
```

Ops: `ping`, `shutdown`, `exec`, `list_images`, `image_info`, `new_image`, `open`, `export`, `export_with`, `close_image`, `render`, `layer_png`, `snapshot`, `drop_snapshot`, `render_compare`, `pixel_color`, `alpha_bbox`, `histogram`, `dominant_colors`, `pdb_search`, `pdb_describe`, `pdb_call`, `filter_search`, `filter_describe`, `apply_filter`, `list_filters_on_layer`, `layer_effect`, `select`, `layer_mask`, `set_mask_pixels`, `layer`, `list_fonts`, `text`, `path`.

## Pixels

Measurement ops read pixels straight from the drawable's `GeglBuffer` as `R'G'B'A u8`, optionally at a reduced scale for large layers (`alpha_bbox` caps at four megapixels and reports `approximate: true` when it downsampled). Mask writes go through the drawable's shadow buffer (`get_shadow_buffer` -> `set` -> `merge_shadow` -> `update`), which keeps them undoable.

## Segmentation

`gimp_remove_background` asks the bridge for a full-resolution PNG of one layer (`layer_png`), runs rembg in the server process, and sends the 8-bit mask back as raw bytes (`set_mask_pixels`). The plug-in never imports rembg or PIL, so GIMP's bundled Python stays untouched and the heavy dependency is optional.

There are no threads in the plug-in. The listening socket and every client socket are non-blocking and watched with `GLib.io_add_watch` (`GLib.IOChannel.win32_new_socket` on Windows, `unix_new` elsewhere) on the main loop that the bridge procedure runs. A complete line is decoded and executed immediately on the main thread and the response is written back with a blocking `sendall`. Several clients can stay connected at once; their requests interleave at line granularity and GIMP work is naturally serialised. This replaced an earlier accept-thread design after repeated unexplained plug-in crashes: libgimp and PyGObject inside a plug-in process should only ever be driven from the main thread.

## Discovery

The plug-in writes `agent-bridge.json` into `Gimp.directory()` (the versioned per-user config folder, e.g. `%APPDATA%\GIMP\3.2`) containing host, port, token, pid, GIMP version and mode. The token is reused across restarts if the file already exists, so a client does not need to re-read it after GIMP restarts. `GIMP_AGENT_PORT` and `GIMP_AGENT_TOKEN` override both sides; `GIMP_AGENT_CONFIG_DIR` and `GIMP_AGENT_BRIDGE_FILE` override where the server looks.

## Launch

`gimp_launch` runs GIMP with `--batch-interpreter=python-fu-eval -b "<code>"`. The code looks up `plug-in-gimp-agent-bridge` in the PDB and runs it non-interactively. The bridge procedure blocks in a `GLib.MainLoop` until `shutdown`, which keeps GIMP alive; headless mode uses `gimp-console -i` so there is no window. GUI mode passes `--new-instance` so a second GIMP does not try to hand the command to a running one.

## Coercion

`pdb_call` and `apply_filter` read the target's parameter specs from GIMP at call time and convert JSON values to GObject values by the spec's type name:

| GType | Accepted JSON |
|---|---|
| `GimpImage` | image id |
| `GimpItem`, `GimpLayer`, `GimpDrawable`, `GimpChannel`, `GimpPath`, ... | item id |
| `GimpCoreObjectArray` | list of item ids |
| `GeglColor` | `"#rrggbb[aa]"`, `"white"`, `"rgb(...)"`, `[r,g,b,a]` |
| `GFile` | path string |
| any GEnum | nick (`"clip-to-image"`), value name, or int |
| `GimpRunMode` | omitted = non-interactive |
| `GStrv` | list of strings |
| scalars | as expected; `"true"`/`"1"` accepted for booleans |

Names are matched with dashes and underscores interchangeable. Unknown argument names are rejected with the valid list.

## Render

`render` duplicates the image, optionally isolates one layer by position, crops to a region, merges visible layers, scales to `max_size`, exports PNG to a temp file, reads it back and deletes both. The original image is never modified.

## Recipes

A recipe module declares `PARAMS` and `SOURCE`. The server resolves defaults, validates unknown keys, prepends `params = {...}` and sends the whole thing to `exec`. The bridge namespace already contains `Gimp`, `Gegl`, `Gio`, `GLib`, `GObject`, `image_by_id`, `item_by_id` and `make_color`. The recipe assigns `result`, which comes back serialised.
