---
name: gimp-batch-jobs
description: Run repeatable image jobs over a whole folder with the gimp MCP server's recipes - sticker packs, icon sets, web optimisation, watermarking, contact sheets, fit-and-export resizing. Use when asked to process many images the same way, resize or convert a folder, add a watermark or outline to a batch, build an icon set or favicon set, prepare Telegram or messaging stickers, optimise images for the web, or make a contact sheet. Also use before hand-rolling a loop, to check whether a tested recipe already exists.
---

# Batch jobs

Before writing a bespoke loop, call `gimp_list_recipes`. A recipe is a tested multi-step job with
declared parameters, defaults and validation, executed inside GIMP. Using one is faster than
scripting the same thing and far less likely to be subtly wrong.

## Preconditions

`gimp_status` first. For batch work over many files, `gimp_launch(mode="headless")` — there is no
reason to paint a window for a hundred images, and it avoids disturbing a GIMP the user has open
with their own work.

## Route

1. `gimp_list_recipes` shows each recipe with its parameters.
2. `gimp_run_recipe(name, params)` runs one job.
3. `gimp_batch_recipe(name, input_glob, output_dir, params)` runs one recipe across a glob. It
   requires the recipe to accept `input_path` and `output_path`.
4. Only if no recipe fits: `gimp_run_python` with your own loop. Say that you are doing this and
   why, so the gap is visible and can become a recipe later.

## Before running across a folder

Run the recipe on **one representative file first** and look at the result with `gimp_render`.
A batch that is wrong is wrong many times, and the outputs may overwrite something.

Check explicitly:

- How many files does the glob actually match? Report the count before processing.
- Does `output_dir` differ from the input directory? If not, say so and confirm, because several
  recipes write the same filename.
- Are the inputs uniform? Mixed aspect ratios, mixed colour profiles or an unexpected CMYK file will
  produce a batch that succeeds and looks wrong.

`gimp_batch_recipe` returns a per-file result list with an `ok` flag. **Read it.** Report the
succeeded and failed counts, and name the failures with their errors. Never report a batch as done
without checking that list.

## Verifying the output

A batch of thumbnails all looking plausible is not evidence. Spot-check with measurement rather than
eyes:

- `gimp_measure(kind="bbox")` confirms a trim or a padding rule actually applied.
- `gimp_measure(kind="dominant")` catches a colour shift from a profile conversion.
- `gimp_snapshot` plus `gimp_render_compare` shows before, after and a pixel diff when a pass is
  meant to leave the silhouette untouched.

The `contact_sheet` recipe is a good final step for a human review pass: one image showing
everything the batch produced.

## Filters across a batch

For a filter pass rather than a recipe: `gimp_filter_search` to find the operation,
`gimp_filter_describe` to get its exact property names and ranges, then `gimp_apply_filter`.
`mode="merge"` bakes the effect into pixels; `mode="append"` leaves it as an editable layer effect,
which is the better default when an XCF master is being kept.

Do not guess a GEGL property name. The describe step exists because the argument lists change
between GIMP versions, and a wrong name fails loudly on one file but silently mid-batch.

## Reporting

State the glob, the matched file count, the output directory, the succeeded and failed counts, the
named failures with their reasons, and what you measured to confirm the result rather than what it
looked like.
