# Game asset mode

Use this reference when the layered workflow is producing assets for a game.

## Choose the asset contract first

Read the target project's asset manifest, style guide, engine code or existing sprites before
generating anything. Establish:

- runtime dimensions and source-master dimensions;
- camera or view direction, and facing;
- palette, outline, lighting and material rules;
- transparent versus opaque background;
- anchor or pivot, usually bottom-centre for characters and grounded props;
- file naming, texture keys, atlas or cell layout, and export format;
- whether shadows belong in the sprite, or are rendered separately by the engine.

If no project contract exists, choose conservative reversible defaults and label the output a
pipeline test rather than shipping art.

## Static sprites and props

- One isolated subject per transparent source image.
- Leave padding around the subject, and keep one consistent visual scale across a related set.
- Remove accidental scenery, captions, frames, watermarks and baked presentation shadows.
- Preserve the high-resolution layered XCF master; downscale a separate runtime export.
- Validate RGBA output, transparent corners, alpha bounds via `gimp_measure(kind="bbox")`, final
  pixel dimensions, and legibility at actual in-game size.
- For pixel art, downscale with nearest-neighbour behaviour and inspect at 100% zoom. Output that
  merely looks pixelated at high resolution is not production pixel art.

## Animation strips

- Start from one approved seed frame that fixes silhouette, palette, costume, proportions and
  facing.
- Generate the whole strip in one pass where possible. Independently generated frames drift.
- Require an exact frame count, transparent background, stable scale, and a stable bottom-centre
  foot anchor.
- Normalise every cell to the same dimensions and one shared scale.
- **Measure the result rather than trusting it.** Alpha bounds per frame give the foot line
  (`y + height`) and centre line (`x + width / 2`); drift in those is what makes an animation bob or
  slide, and it is invisible in a preview sheet. The `gimp-sprite-sheets` skill covers the full
  measure, pack and verify loop.
- Verify in-engine before promotion.

## Backgrounds and parallax

- Separate far background, midground, foreground, atmosphere and collision art whenever they need
  independent motion or tuning.
- Extend layers past the camera edge far enough to avoid seams during movement.
- Test tiling and parallax joins numerically. A downscaled preview hides a one-pixel seam.

## UI and effects

- Keep labels and changing numbers out of generated pixels. Render them in-engine, or keep them as
  editable GIMP text layers.
- Export effects with clean alpha and enough padding for glow and blur bounds.
- Check the target engine's additive versus alpha blend assumptions before matching a look.

## Promotion gate

Generated output stays incoming material until it passes:

1. visual consistency with the target game;
2. exact dimensions and alpha checks;
3. anchor, cell and atlas validation;
4. licensing and generation provenance capture;
5. in-engine inspection at real gameplay scale.
