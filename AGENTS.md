# Repository instructions

This repository is the public, Apache-2.0 GIMP Agent MCP server.

- Two processes, one contract: `src/gimp_agent_mcp/plugin/gimp-agent-bridge.py` runs inside GIMP; everything else runs in the MCP server. The bridge may only depend on the Python standard library, `gi`, and `agent_bridge_core.py`, because it is copied into GIMP's plug-in folder on its own.
- `agent_bridge_core.py` must never import `gi`. It is shared with the server and the unit tests.
- Every GIMP-side operation runs on the plug-in main thread through `GLib.idle_add`. Do not call libgimp from the socket thread.
- Prefer generic, introspected access (PDB and GEGL property descriptions read from GIMP at runtime) over hand-written wrappers. Add a dedicated tool only when the generic path is genuinely awkward for an agent.
- Recipes are Python source strings executed inside GIMP with `params` injected. They declare `DESCRIPTION`, `PARAMS`, `SOURCE`, and assign `result`.
- Keep the bridge on loopback with a required token. Never add a network-exposed mode.
- Keep real identities, machine paths, tokens and private material out of this repository.
- Run `uv run ruff check .` and `uv run pytest` before committing. Run `uv run gimp-agent-mcp smoke` on a machine with GIMP 3 before tagging a release.
- Update `docs/ARCHITECTURE.md`, `CHANGELOG.md` and the tool table in `README.md` when the tool surface or protocol changes.
