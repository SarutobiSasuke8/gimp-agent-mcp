# Asset workflows

Sprite inputs, social crops and warp, using calls that exist today: the `sprite_sheet_pack`, `sprite_atlas_pack` and `social_crop` recipes, plus `gimp_canvas` for a single hand-placed crop.

Runnable checks that do not need GIMP:

```bash
python examples/sprite_inputs.py
python examples/social_crops.py
python examples/validated_warp.py
```

Each script prints JSON, including an `expected_output` string, and exits non-zero if a check fails. Prompts for an agent sit beside them:

- [Equal-size PNG frames](../examples/prompts/sprite-file-inputs.txt)
- [Open layers as atlas sprites](../examples/prompts/sprite-open-layers.txt)
- [Open Graph crop](../examples/prompts/social-crop.txt)
- [Warp left unsupported](../examples/prompts/warp-status.txt)

Pixel verification, layered XCF export and any live filter still need GIMP 3. The sprite proof that does run inside GIMP is `python scripts/sprite_sheet_proof.py OUT_DIR`. These examples were checked without GIMP.

## Sprite inputs

Two recipes. Parameter lists come from `gimp_list_recipes` or [RECIPES.md](RECIPES.md).

`sprite_sheet_pack` takes ordered PNG paths (`input_paths`), `output_path` (must end in `.png`), `columns`, `margin` and `spacing`. Every frame must share one canvas size. The sheet, the `.json` atlas and the layered `.xcf` share one stem. Verification reopens the PNG and compares each cell's RGBA pixels. `margin` and `spacing` match `sprite_sheet_slice`.

`sprite_atlas_pack` is the mixed-size path. Give exactly one input:

- `input_paths`: PNG files, canvases may differ, keys are basenames.
- `input_layer_ids`: integer ids of open raster layers, keys are layer names. Group layers are refused. The source documents are read and not modified or closed.

`padding` (default 2) is the transparent gap between sprites and around the edge. `trim` packs measured alpha bounds instead of the full canvas. `max_width` (default 2048) caps width. `power_of_two` rounds the atlas up and requires a power-of-two `max_width`. Placement is `pack_rects` (MaxRects, bottom-left, no rotation), which `examples/sprite_inputs.py` calls directly. Passing both inputs, or neither, is rejected by `resolve_params` before GIMP is asked (`needs exactly one of input_paths or input_layer_ids`), and again by the recipe body inside GIMP.

[`examples/sprite_inputs.py`](../examples/sprite_inputs.py) resolves both call shapes and places seven full canvases at padding 2. Expected sheet for six 64px frames, four columns, margin 1 and spacing 2: **264 by 132**. It does not write image files.

## Social crops

`social_crop` exports one source to named profiles around a focus point and measures every file it writes:

```text
gimp_run_recipe("social_crop", {"input_path": "photo.jpg", "output_dir": "out/social",
  "profiles": ["open_graph", "instagram_portrait", "youtube_thumbnail"], "focus": {"x": 1680, "y": 420}})
```

| Profile | Pixels | Usual use |
|---|---|---|
| open_graph | 1200 × 630 | Open Graph / link preview |
| x_landscape | 1600 × 900 | X landscape post |
| instagram_square | 1080 × 1080 | Square feed |
| instagram_portrait | 1080 × 1350 | Portrait feed, 4:5 |
| story_reel | 1080 × 1920 | Story, reel or vertical short |
| youtube_thumbnail | 1280 × 720 | YouTube thumbnail |

`profiles` takes these names, `["all"]`, or custom `{"name": "banner", "width": 1500, "height": 500}` objects. Use `image_id` instead of `input_path` to export from an open document; it is duplicated and never changed.

- `fit="cover"` (default) scales the source by the smallest factor that covers the profile, then crops around the focus. A profile that would need the source enlarged is refused unless `allow_upscale=true`.
- `fit="crop"` never scales and refuses profiles larger than the source, like `gimp_canvas` crop.
- `focus` is `{x, y}` in source pixels (default: the centre). The crop is centred on the focus and clamped to the image, so the focus pixel is always inside the output; `focus_after` reports where it landed.
- Every profile is planned before anything is written, so one refused profile leaves no partial output.
- Each file is reopened: `measured` must equal the profile size, and PNG output must match the cropped image pixel for pixel (`pixel_check`). JPEG and WebP report the size only, because they are lossy.

At scale 1 the origin is the same as the hand formula below, so `fit="crop"` on a 2400 × 1800 image with focus `(1680, 420)` puts the Open Graph crop at `x=1080`, `y=105`, focus `(600, 315)`.

### One crop by hand

A single crop is `gimp_canvas`:

```text
gimp_canvas(image_id, action="crop", width=1200, height=630, x=1080, y=105)
```

`width` and `height` are required and must be positive. `x` and `y` default to 0. They are the PDB `offx` and `offy` of `gimp-image-crop`: the top-left of the rectangle that remains. Crop does not scale. To keep a focus pixel `(fx, fy)` inside the crop, centre with integer division and clamp to the source:

```text
x = min(max(fx - width // 2, 0), source_width - width)
y = min(max(fy - height // 2, 0), source_height - height)
```

[`examples/social_crops.py`](../examples/social_crops.py) computes these calls with the recipe's own planner and checks the focus stays in frame. Export with `gimp_export`; JPEG accepts `options={"quality": 0.85}` (0 to 1).

## Warp

Warp and liquify are **unsupported**. [`examples/validated_warp.py`](../examples/validated_warp.py) is the check:

- `recipes.get_recipe("warp")` fails with an unknown-recipe error.
- `gimp_canvas(image_id, "warp")` fails before the bridge is contacted. Valid actions are `scale`, `crop`, `resize`, `rotate`, `flip`, `merge_visible` and `flatten`.
- `gimp_adjust(layer_id, "liquify")` fails the same way. Liquify is not an adjustment.
- The CLI commands are `serve`, `install-plugin`, `install-skills`, `doctor`, `launch`, `shortcut` and `smoke`. None of them warps.

Do not claim vector warp or liquify parity. This repository has no before/after measurement of an installed warp operation. What GIMP 3.2.4 exposes, and why `gegl:warp` cannot be applied as a filter, is in the [warp investigation note](WARP_INVESTIGATION.md). If GIMP is running, `gimp_filter_search` and `gimp_pdb_search` can list installed names for `warp` or `liquify`. A search hit is not a supported workflow. A validated result would record `gimp_snapshot`, the operation name that describe actually returned, and `gimp_render_compare` or `gimp_measure`. Until that proof exists, the status stays unsupported.
