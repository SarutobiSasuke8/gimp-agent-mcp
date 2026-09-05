# Skills

Three skills ship with the server, in `skills/`. They are client-agnostic `SKILL.md` directories:
Claude Code and Codex both read that format, so the same files serve either.

A skill is not a tool. The tools are already visible to any connected client. A skill is the method
for a recognisable job: which tools, in what order, what to check, and what to refuse to claim
without evidence. The three here exist because those are the jobs where an agent with the full GIMP
surface still tends to guess.

| Skill | The job it owns |
|---|---|
| `gimp-sprite-sheets` | Pack, slice and **verify** sprite sheets and atlases. Every crop rectangle measured from pixels; the exported sheet re-measured cell by cell before it is called correct |
| `gimp-layered-assets` | Component-first layered composition. Keep an XCF master, keep text and effects editable, export delivery formats separately |
| `gimp-batch-jobs` | Recipes across a folder. Check the per-file result list; measure a spot-check rather than trusting a thumbnail |

## Install

### Claude Code, as a plugin (server and skills together)

```bash
/plugin marketplace add SarutobiSasuke8/gimp-agent-mcp
/plugin install gimp-agent-mcp
```

The plugin manifest at `.claude-plugin/plugin.json` points at `.mcp.json`, which runs the server via
`uvx gimp-agent-mcp serve`, and Claude Code discovers `skills/` by convention. One install gets both
halves.

### Either client, skills only

```bash
gimp-agent-mcp install-skills              # every client directory that exists
gimp-agent-mcp install-skills --client codex
gimp-agent-mcp install-skills --dir ./.claude/skills   # project scope
```

Targets `~/.claude/skills`, `~/.codex/skills` and `~/.agents/skills`. Existing directories are
**skipped, not overwritten**; pass `--force` to replace them. Start a new client session afterwards.

### By hand

Copy any directory under `skills/` into your client's skills folder. Nothing in them is
path-dependent.

## Codex specifics

Each skill carries `agents/openai.yaml`, which gives Codex a display name, a default prompt, and a
declared dependency on the `gimp` MCP server. Codex will surface the dependency if the server is not
configured, rather than letting the model improvise. Invoke explicitly with `$gimp-sprite-sheets`,
or let the description match.

## Writing your own

Skills read better when they say what not to claim. Each of these carries at least one recorded trap
that actually happened, because a warning with a real failure behind it survives editing:

- `Gimp.Image.flatten()` removes the alpha channel and composites onto the background colour. A
  sprite sheet packed with it looks perfect as a thumbnail and is completely opaque. Only
  re-measuring the exported file catches this.
- A generated PNG is a flattened raster. It has no semantic layers, and no amount of segmentation
  recovers occluded pixels.
- GEGL property names and PDB argument lists change between GIMP versions, so `gimp_filter_describe`
  and `gimp_pdb_describe` are not optional politeness.

Keep the `description` frontmatter concrete about triggers. It is the only part the model sees when
deciding whether the skill applies.

## Relationship to `gimp_help`

`gimp_help(topic)` is in-band reference for tools, filters, colours, masks, paths and errors: facts
an agent looks up mid-task. The skills are the workflow layer above that, loaded when a job starts.
They cite `gimp_help` rather than duplicating it.
