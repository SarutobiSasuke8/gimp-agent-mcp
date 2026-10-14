# Asset workflows

Sprite inputs, social crops and warp, using only calls that exist today. Nothing on this page adds a tool, a recipe parameter or a CLI flag.

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

`padding` (default 2) is the transparent gap between sprites and around the edge. `trim` packs measured alpha bounds instead of the full canvas. `max_width` (default 2048) caps width. `power_of_two` rounds the atlas up and requires a power-of-two `max_width`. Placement is `pack_rects` (MaxRects, bottom-left, no rotation), which `examples/sprite_inputs.py` calls directly. Passing both inputs, or neither, is rejected when the recipe runs inside GIMP (`give exactly one of input_paths or input_layer_ids`). `resolve_params` only checks types.

[`examples/sprite_inputs.py`](../examples/sprite_inputs.py) resolves both call shapes and places seven full canvases at padding 2. Expected sheet for six 64px frames, four columns, margin 1 and spacing 2: **264 by 132**. It does not write image files.

## Social crops

There is no named social profile and no focus parameter. A crop is `gimp_canvas`:

```text
gimp_canvas(image_id, action="crop", width=1200, height=630, x=1080, y=105)
```

`width` and `height` are required and must be positive. `x` and `y` default to 0. They are the PDB `offx` and `offy` of `gimp-image-crop`: the top-left of the rectangle that remains. The call returns `editable: false` and the installed procedure description. After GIMP accepts it, `image.width` and `image.height` are the requested size.

Crop does not scale. If the target is wider or taller than the source, do not emit the call. `gimp_canvas` `scale` is a different action and does not take a focus point.

Common sizes used by [`examples/social_crops.py`](../examples/social_crops.py) (labels, not server presets):

| Label | Pixels | Usual use |
|---|---|---|
| open_graph | 1200 × 630 | Open Graph / link preview |
| x_landscape | 1600 × 900 | X landscape post |
| instagram_square | 1080 × 1080 | Square feed |
| instagram_portrait | 1080 × 1350 | Portrait feed, 4:5 |
| story_reel | 1080 × 1920 | Story, reel or vertical short |
| youtube_thumbnail | 1280 × 720 | YouTube thumbnail |

To keep a focus pixel `(fx, fy)` inside the crop, centre with integer division and clamp to the source:

```text
x = min(max(fx - width // 2, 0), source_width - width)
y = min(max(fy - height // 2, 0), source_height - height)
```

On a 2400 × 1800 image with focus `(1680, 420)`, the Open Graph crop is `x=1080`, `y=105`. The focus is then at `(600, 315)` on the cropped image, which `gimp_measure(kind="color", x=600, y=315)` can read. A focus at `(10, 10)` clamps that same crop to `(0, 0)` and stays in frame. `story_reel` is refused for this source because 1920 is taller than 1800.

Export with `gimp_export`. The path extension selects the format. JPEG accepts `options={"quality": 0.85}` (0 to 1). Unknown option names return the valid list.

## Warp

Warp and liquify are **unsupported**. [`examples/validated_warp.py`](../examples/validated_warp.py) is the check:

- `recipes.get_recipe("warp")` fails with an unknown-recipe error.
- `gimp_canvas(image_id, "warp")` fails before the bridge is contacted. Valid actions are `scale`, `crop`, `resize`, `rotate`, `flip`, `merge_visible` and `flatten`.
- `gimp_adjust(layer_id, "liquify")` fails the same way. Liquify is not an adjustment.
- The CLI commands are `serve`, `install-plugin`, `install-skills`, `doctor`, `launch`, `shortcut` and `smoke`. None of them warps.

Do not claim vector warp or liquify parity. This repository has no before/after measurement of an installed warp operation. If GIMP is running, `gimp_filter_search` and `gimp_pdb_search` can list installed names for `warp` or `liquify`. A search hit is not a supported workflow. A validated result would record `gimp_snapshot`, the operation name that describe actually returned, and `gimp_render_compare` or `gimp_measure`. Until that proof exists, the status stays unsupported.
