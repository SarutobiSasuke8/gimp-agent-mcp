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

Ops: `context`, `edit_batch`, `ping`, `shutdown`, `exec`, `list_images`, `image_info`, `new_image`, `open`, `export`, `export_with`, `close_image`, `render`, `layer_png`, `snapshot`, `drop_snapshot`, `render_compare`, `pixel_color`, `alpha_bbox`, `histogram`, `dominant_colors`, `pdb_search`, `pdb_describe`, `pdb_call`, `filter_search`, `filter_describe`, `apply_filter`, `list_filters_on_layer`, `layer_effect`, `select`, `layer_mask`, `set_mask_pixels`, `layer`, `list_fonts`, `text`, `path`.

## Pixels

Measurement ops read pixels straight from the drawable's `GeglBuffer`. Colour reads use `R'G'B'A u8`; alpha bounds scan full-resolution `A u8` data in bounded horizontal bands, so large-layer bounds remain exact. Mask writes go through the drawable's shadow buffer (`get_shadow_buffer` -> `set` -> `merge_shadow` -> `update`), which keeps them undoable.

## Segmentation

`gimp_remove_background` asks the bridge for a full-resolution PNG of one layer (`layer_png`), runs rembg in the server process, and sends the 8-bit mask back as raw bytes (`set_mask_pixels`). The plug-in never imports rembg or PIL, so GIMP's bundled Python stays untouched and the heavy dependency is optional.

There are no threads in the plug-in. The listening socket and every client socket are non-blocking and watched with `GLib.io_add_watch` (`GLib.IOChannel.win32_new_socket` on Windows, `unix_new` elsewhere) on the main loop that the bridge procedure runs. A complete line is decoded and executed immediately on the main thread and the response is written back with a non-blocking send loop and a bounded back-pressure wait. Several clients can stay connected at once; their requests interleave at line granularity and GIMP work is naturally serialised. This replaced an earlier accept-thread design after repeated unexplained plug-in crashes: libgimp and PyGObject inside a plug-in process should only ever be driven from the main thread.

## Discovery

The plug-in writes `agent-bridge.json` into `Gimp.directory()` (the versioned per-user config folder, e.g. `%APPDATA%\GIMP\3.2`) containing host, port, token, pid, GIMP version and mode. The token is reused across restarts if the file already exists, so a client does not need to re-read it after GIMP restarts. `GIMP_AGENT_PORT` and `GIMP_AGENT_TOKEN` override both sides; `GIMP_AGENT_CONFIG_DIR` and `GIMP_AGENT_BRIDGE_FILE` override where the server looks.

## Launch

`gimp_launch` runs GIMP with `--batch-interpreter=python-fu-eval -b "<code>"`. The code looks up `plug-in-gimp-agent-bridge` in the PDB and runs it non-interactively. The bridge procedure blocks in a `GLib.MainLoop` until `shutdown`, which keeps GIMP alive; headless mode uses `gimp-console -i` so there is no window. Both launch modes pass `--new-instance` so a test or batch does not hand its command to an existing GIMP window.

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


### Verified grid-packing recipe

`sprite_sheet_pack` uses the existing recipe/exec contract; it adds no MCP tool or bridge protocol. The server validates declared parameter types and numeric minimums, then GIMP imports ordered equal-size PNG frames, measures decoded RGBA pixels, places named layers, exports and reopens the PNG for exact comparison. Only a successful comparison proceeds to the layered XCF and atlas JSON. The recipe deletes temporary images on success and failure, retaining the sheet only for a successful `keep_open` request. Source paths stay out of the atlas JSON.


## 0.4 grouped editing and recovery

`edit_batch` accepts only the shared `EDIT_OPS` allowlist and 1..100 steps. Each step uses an existing bridge operation; `image_id` is fixed for the batch and all referenced items must belong to it. `{ "$ref": "0.id" }` resolves an earlier result without evaluating code. A single outer undo group surrounds the work and closes in `finally`. Failed steps stop execution and return the completed results plus an error index; partial edits remain for inspection and one GUI undo. No group stays open between requests. File operations, arbitrary Python and generic PDB dispatch are excluded from the bounded batch.

The client never automatically replays a request after dispatch. A missing or mismatched response means the outcome is unknown, not that the edit failed to happen. It closes the connection and tells the caller to reconnect and inspect before retrying.

`context` reports selected layers and bounds for an explicit image; it can select layers or present a GUI document. It reports ambiguity for multiple documents rather than pretending to know keyboard focus. Colour/brush values describe the plug-in's context, which is not a continuous mirror of the user's toolbox.

GimpDoubleArray and GimpInt32Array use a GObject.Value and the appropriate GIMP boxed-array setter. GEGL paths accept a path string. Availability of these conversions does not mean every procedure or graph topology is supported.

Snapshots are private comparison images: excluded from document lists, limited to 16, explicitly releasable and deleted when the bridge closes. Layer rendering preserves required group ancestors. Comparison flattening merges visible content onto a transparent full-canvas layer, avoiding selection of a hidden top layer.

For POSIX launches, the GIMP executable's directory precedes uv's virtualenv on PATH; PYTHONHOME/PYTHONPATH/VIRTUAL_ENV are removed from the child environment. GIMP's own plug-ins can therefore use the Python GI runtime that belongs to its installation. Windows uses the packaged GIMP runtime unchanged. Headless launches also use --new-instance.

The server-side BridgeClient uses a reentrant lock to serialize parallel MCP calls over its single socket, including reconnects. This does not introduce any threads in the GIMP plug-in. A zero-byte send closes a dead peer rather than spinning forever.
