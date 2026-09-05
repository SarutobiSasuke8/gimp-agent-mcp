# Contributing

Run `uv run ruff check .` and `uv run pytest` before opening a pull request. Changes to the bridge protocol, coercion rules, or the tool surface need a unit test where one is possible, a `docs/ARCHITECTURE.md` update, and a run of `uv run gimp-agent-mcp smoke` on a machine with GIMP 3 noted in the PR.

Recipes are welcome. A recipe is a module in `src/gimp_agent_mcp/recipes/` with `DESCRIPTION`, `PARAMS` (every parameter has a description and either a default or `required: True`) and `SOURCE` that assigns `result`. Keep them deterministic and free of machine-specific paths. See `docs/RECIPES.md`.

Never add a network-exposed bind option, remove the token check, or add code copied from GPL-licensed projects. This repository is Apache-2.0 and stays clean-room.

Platform reports are valuable: if you run the smoke test on macOS or Linux, open an issue with the output even when it passes.
