---
name: gimp-sprite-sheets
description: Build, diagnose and verify game sprite sheets and texture atlases from loose frames using the gimp MCP server, measuring every rectangle from pixels instead of eyeballing crops. Use when asked to pack frames into a sprite sheet, make a texture atlas, fix a bobbing or sliding animation, align or normalise sprite frames, find a sprite's true bounds or pivot, trim transparent padding, or slice an existing sheet back into frames. Also for "sprite sheet", "spritesheet", "atlas", "frame alignment", "anchor point", "pivot", or auditing a game's art folder for unpacked assets.
---

# Sprite sheets, measured not guessed

Most sprite-sheet tooling asks a human to type crop rectangles. This server can read the pixels
back, so every rectangle can be measured, and the finished sheet can be checked against the file
that was actually written.

**Never write a crop rectangle you have not measured. Never claim a sheet is correct without
re-measuring the exported file.**

## Preconditions

Call `gimp_status` first. If the `gimp_*` tools are not present at all, the MCP server failed to
start: say so rather than working around it. If the tools are present but the bridge is not
connected, `gimp_launch(mode="headless")` for batch work, or ask the user to click
**Filters > Development > Start Agent Bridge** when they already have GIMP open with work in it.

Never launch a second GIMP alongside a user's running instance without saying so.

## 1. Measure every frame

`gimp_open` each frame, then `gimp_measure(kind="bbox")` on it. Threshold 0 is exact; raise it to
around 8 when anti-aliased fringing should be ignored.

Record per frame, and report the set:

| quantity | derived from bbox | what drift in it causes |
|---|---|---|
| content bounds | `x, y, width, height` | the only honest crop rectangle |
| foot line | `y + height` | the character **bobs** as it animates |
| centre line | `x + width / 2` | the character **slides** sideways |
| canvas size | `gimp_open` result | frames cannot share a grid until they share a canvas |

Foot-line drift above 1 px in a walk or run cycle is a defect. Report it before packing. It is
invisible in a contact sheet and obvious as a column of integers.

Two limits worth stating out loud rather than quietly assuming:

- Foot and centre drift only mean something for **grounded frames of the same subject**. Asteroids,
  particles, projectiles and free-floating props legitimately drift, and calling that a defect is
  wrong.
- **Mixed canvas sizes mean this is a loose sprite collection, not an animation.** It wants an atlas
  of trimmed rectangles, not a uniform grid. Say so instead of forcing a grid onto it.

## 2. Pack

Cell size is the shared canvas size. Choose the column count so the sheet stays within 2048 px on
both axes where the frame count allows, since older mobile GPUs cap there.

```python
sheet = Gimp.Image.new(cw * cols, ch * rows, Gimp.ImageBaseType.RGB)
bg = Gimp.Layer.new(sheet, "sheet", cw * cols, ch * rows,
                    Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
sheet.insert_layer(bg, None, 0)
bg.fill(Gimp.FillType.TRANSPARENT)
# ... insert each frame as a layer, then set_offsets(col * cw, row * ch) ...
merged = sheet.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
if not merged.has_alpha():
    merged.add_alpha()
```

**Never use `Gimp.Image.flatten()`.** It removes the alpha channel and composites onto the
background colour. The resulting sheet looks entirely correct as a thumbnail and is fully opaque.
This is the single most likely way to ship a broken sheet from this server.

## 3. Verify, which is the step that earns the tool

Re-open the **exported PNG** and measure the alpha bounds inside each cell rectangle. Compare
against the per-frame bounds from step 1.

Anything other than an exact match is a failure. Report which frames moved; do not paper over it.
Confirm the foot line is identical across every cell.

Do not skip this because the pack obviously worked. The `flatten()` bug above produces a
plausible-looking sheet and is caught **only** here: every cell measures as the full cell rectangle
instead of its real bounds.

## 4. Emit the atlas

Standard atlas JSON, with the trim rectangle and the pivot both measured rather than assumed:

```
frame              = { cell_x + bbox.x, cell_y + bbox.y, bbox.w, bbox.h }
spriteSourceSize   = { bbox.x, bbox.y, bbox.w, bbox.h }
sourceSize         = { cell_w, cell_h }
pivot.x            = centre_x / cell_w
pivot.y            = foot_y   / cell_h
```

A grounded character's origin belongs at its feet, not at `0.5, 0.5`. That pivot is a measured
number, which is the entire point of doing this here rather than by eye.

Finish by telling the user the exact loader call for what you produced. For a uniform grid that is a
spritesheet load with `frameWidth`/`frameHeight`; for trimmed rectangles it is an atlas load against
the JSON.

## Going the other way

`gimp_run_recipe("sprite_sheet_slice", ...)` cuts an existing sheet back into individual frames,
skipping fully transparent cells. Use it to inspect or re-normalise a sheet somebody else built,
then measure the frames and re-pack.

## Reporting

Show the measured table. State drift in pixels. State the verification verdict plainly: either every
frame is byte-identical in place, or name the frames that moved. If the source frames were
misaligned, say the sheet was built from misaligned frames rather than implying the pack fixed them.
