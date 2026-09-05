# skills/

Client-agnostic `SKILL.md` directories shipped with the server. Claude Code reads this folder by
convention when the repo is installed as a plugin; Codex reads the same format from
`~/.codex/skills`.

Install with `gimp-agent-mcp install-skills`. Full documentation: [../docs/SKILLS.md](../docs/SKILLS.md).

- `gimp-sprite-sheets` — measure, pack and verify sprite sheets and atlases
- `gimp-layered-assets` — component-first layered composition and export
- `gimp-batch-jobs` — recipes across a folder of images

These are shipped as-is under the repository's Apache-2.0 licence. Copy one and edit it for your own
project's conventions rather than adding project-specific paths here.
