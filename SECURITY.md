# Security

## Trust model

This server is a local automation bridge. The person who installs it controls GIMP, the files GIMP can reach, and which MCP clients may connect. MCP clients are trusted to the same degree as the user running GIMP: `gimp_run_python` and `gimp_pdb_call` execute arbitrary code inside the GIMP process with that user's permissions, and file tools read and write wherever that user can.

Do not expose this server to clients you would not let run a script on your machine.

## What is enforced

- The bridge binds to `127.0.0.1` only. There is no option to bind elsewhere.
- Every request must carry the token from `<GIMP config dir>/agent-bridge.json`. The file is created with mode `0600` on POSIX and lives in the user's private profile directory on Windows. Requests without the token are rejected before dispatch.
- `GIMP_AGENT_ALLOW_PYTHON=0` removes the `gimp_run_python` tool from the server. Note that `gimp_pdb_call` can still reach `python-fu-eval` and recipes are Python by design, so this is a guard against casual use, not a sandbox.
- The bridge serves one client at a time and runs every operation on the plug-in main thread; a stuck operation blocks the bridge but not GIMP's UI.
- Errors returned to the client include a traceback tail for debugging. They do not include the token.

## What is not enforced

- No sandboxing of Python or PDB calls.
- No allow-list of file paths. `gimp_open`, `gimp_export` and recipes accept any path the user can access.
- No authentication between the MCP client and the server process beyond what the MCP transport provides (stdio is process-local).

## Reporting

Open a GitHub issue for non-sensitive problems. For anything that could expose a user's files, contact the maintainer privately through the GitHub profile before publishing details.
