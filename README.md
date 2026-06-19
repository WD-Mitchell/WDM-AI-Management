# WDM AI Management

WDM AI Management is a local web UI and CLI for managing AI assistant configuration from one source of truth.

It lets you create, edit, preview, install, and sync agents, skills, MCP servers, rules, workflows, hooks, templates, groups, and harness definitions across multiple AI coding tools.

The source of truth lives in `~/.wdm`. Generated harness files are deployed into each target tool's expected location, globally or per project.

## Highlights

- Lightweight local web UI launched with `wdm-ai`
- File-backed source of truth in `~/.wdm`, with no database
- Form and file editors for agents, skills, MCP servers, rules, workflows, hooks, templates, and harnesses
- Project selector with global and per-project install state
- Harness selector and status-aware add/update controls
- Preview modals with rendered Markdown, HTML, YAML, JSON, and TOML
- External item discovery for project files not yet managed by WDM
- Template system for reusable item structure and field presets
- Custom harness definitions in JSON
- Canonical WDM fields mapped into each harness's native names
- CLI sync with backups, dry runs, restore, groups, and global/project targets

## Supported Harnesses

Harness support is defined by files in `~/.wdm/harnesses/core/*.json`, so users can add or modify harnesses without changing application code.

Default enabled or auto-detected harnesses include:

| Harness | Notes |
| --- | --- |
| GitHub Copilot CLI | Agents, skills, MCP, instructions, hooks |
| Claude Code | Agents, skills, rules, workflows, hooks, project MCP |
| OpenAI Codex CLI | TOML agents, skills, hooks, merged MCP config |
| Gemini CLI | Agents, skills, merged MCP settings |
| Cursor | Rules and AI config where available |
| Pi | Agents, skills, rules, workflows, hooks |

Additional bundled harness definitions include:

`aider`, `cline`, `continue`, `goose`, `opencode`, `qwen`, `roo`, and `windsurf`.

## Install

### npm

```bash
npm install -g @wdm-uk/ai-management
```

### Bun

```bash
bun install -g @wdm-uk/ai-management
```

### Homebrew

```bash
brew tap WD-Mitchell/wdm
brew install wdm-ai-management
```

All installers expose the `wdm-ai` command:

```bash
wdm-ai
```

Install/bootstrap creates `~/.wdm`, installs the AI Management skill, and syncs that skill into detected global harness skill locations.

## Quick Start

Launch the web UI:

```bash
wdm-ai
```

Open the UI without launching a browser:

```bash
wdm-ai --no-open
```

Run with auto-reload while developing the app:

```bash
wdm-ai --reload
```

Bootstrap or refresh bundled defaults:

```bash
wdm-ai bootstrap
wdm-ai bootstrap --force
```

Sync installed items into the current project:

```bash
wdm-ai sync
```

Preview sync changes without writing:

```bash
wdm-ai sync --dry-run
```

Sync globally into your home directory:

```bash
wdm-ai sync --global
```

## Web UI

The web UI is the primary way to manage content.

Start it with:

```bash
wdm-ai
```

The UI includes:

- **Harnesses** in the left rail, with enable/disable controls and editable JSON config
- **Projects** in the left rail, with global as the top option and project-specific install state below
- **Content tabs** in the header for agents, skills, MCP, hooks, rules, workflows, groups, and templates
- **Card selection pages** with search, sorting, group filters, harness filters, project/global status icons, and pagination
- **Create and import actions** for each content type
- **Managed, external, and combined views** for project content
- **Preview modals** that render structured and rich file content
- **Edit modals** with form view and file view
- **Template selection** at the top of editors
- **Save as template** and duplicate flows
- **Harness-aware add/update controls** with multiselect harness targeting

### Form View And File View

Most content types support two editor modes:

| Mode | Purpose |
| --- | --- |
| Form view | Edit common fields, body sections, templates, skills, MCP, model, reasoning, and harness settings |
| File view | Edit the raw source file directly |

The app writes normal files under `~/.wdm`; there is no hidden database.

### Preview

Preview renders content according to the file type:

- Markdown is rendered as Markdown
- HTML is rendered in a sandboxed preview frame
- JSON, YAML, and TOML are rendered as structured metadata
- Codex TOML agents show metadata and rendered instructions separately

### External Items

When viewing a project, the UI can show external items found in that project's harness folders. These are files that exist in a harness such as `.codex`, `.claude`, `.github`, or `.gemini` but are not yet managed by WDM.

External items can be previewed, edited for their source harness, or imported into the WDM source of truth.

## Source Layout

The live source of truth is:

```text
~/.wdm/
├── agents/core/          # Agent definitions
├── skills/core/          # Skill directories
├── mcp/core/             # MCP server definitions
├── rules/core/           # Rule definitions
├── workflows/core/       # Workflow definitions
├── hooks/core/           # Hook scripts
├── groups/               # Install groups
├── templates/core/       # Editor templates
├── harnesses/core/       # Harness definitions
├── installed/            # Installed item state
├── backups/              # Automatic sync backups
├── defaults.conf         # Model and reasoning defaults
└── projects.json         # Web UI project list
```

## Core Concepts

### Content Types

| Type | Purpose |
| --- | --- |
| Agents | Assistant personas or subagents |
| Skills | Reusable task instructions and workflows |
| MCP | MCP server definitions |
| Rules | Reusable project or coding rules |
| Workflows | Command or process definitions |
| Hooks | Scripts that can be installed into harness hook locations |
| Groups | Named install sets |
| Templates | Reusable item editor presets |
| Harnesses | Tool-specific schema, output, and sync contracts |

### Harnesses

A harness defines how WDM maps canonical fields into a target AI tool.

Harness definitions live in:

```text
~/.wdm/harnesses/core/*.json
```

Each harness can define:

- Display label
- Detection rules
- Enable/disable defaults
- Supported schemas per content type
- Field mappings from WDM canonical fields to harness-native names
- Output file extensions and directory behavior
- Project and global sync paths
- Specialized renderers where needed

### Field Mapping Contracts

The app uses canonical WDM fields in forms. Harness files map those fields into each target tool's naming conventions.

Example:

```json
{
  "field_mappings": {
    "agents": {
      "mcp_servers": "mcpServers",
      "reasoning": "effort"
    }
  }
}
```

That lets one source file use `mcp_servers` and `reasoning`, while Claude receives `mcpServers` and `effort`, Copilot receives `mcp-servers`, and Codex receives `model_reasoning_effort` where configured.

For Codex agents, the Markdown body is mapped to `developer_instructions`. `developer_instructions` is not a shared WDM form field.

### Templates

Templates define starter fields and body sections for content types.

They live in:

```text
~/.wdm/templates/core/*.template
```

Templates are for creating or editing items. Groups are for installing sets of items into a project or global scope.

### Groups

Groups define named install sets.

Example:

```ini
[agents]
code-reviewer
api-documenter

[skills]
debugging
testing

[mcp]
github
playwright
```

Install a group:

```bash
wdm-ai --install-group default
```

Sync a group only:

```bash
wdm-ai sync --group default
```

## CLI Reference

### Web UI

```bash
wdm-ai
wdm-ai web
```

Options:

```bash
--host <host>     Host to bind, default 127.0.0.1
--port <port>     Port to bind
--open            Open browser
--no-open         Do not open browser
--reload          Restart when app/source files change
```

Examples:

```bash
wdm-ai
wdm-ai --no-open --port 8770
wdm-ai --reload
wdm-ai --no-open
```

### Bootstrap

```bash
wdm-ai bootstrap
```

Options:

```bash
--force       Overwrite bundled defaults in ~/.wdm
--no-sync     Do not sync the AI Management skill after bootstrap
--quiet       Reduce output
```

Examples:

```bash
wdm-ai bootstrap
wdm-ai bootstrap --force
```

### List And Inspect

```bash
wdm-ai --list
wdm-ai --list-groups
wdm-ai --list-templates
wdm-ai --installed
```

### Install Items

Install the default group:

```bash
wdm-ai --install
```

Install everything:

```bash
wdm-ai --install-all
```

Install all of one type:

```bash
wdm-ai --install-all-agents
wdm-ai --install-all-skills
wdm-ai --install-all-rules
wdm-ai --install-all-workflows
wdm-ai --install-all-hooks
wdm-ai --install-all-mcp
```

Install specific items:

```bash
wdm-ai --install-agent code-reviewer,api-documenter
wdm-ai --install-skill debugging,testing
wdm-ai --install-rule code-style
wdm-ai --install-workflow pull-request
wdm-ai --install-hook post-merge
wdm-ai --install-mcp github,playwright
```

Install groups:

```bash
wdm-ai --install-group default
wdm-ai --install-group-agents default
wdm-ai --install-group-skills default
wdm-ai --install-group-rules default
wdm-ai --install-group-workflows default
wdm-ai --install-group-hooks default
wdm-ai --install-group-mcp default
```

### Uninstall Items

```bash
wdm-ai --uninstall-agent code-reviewer
wdm-ai --uninstall-skill debugging
wdm-ai --uninstall-rule code-style
wdm-ai --uninstall-workflow pull-request
wdm-ai --uninstall-hook post-merge
wdm-ai --uninstall-mcp github
```

### Sync

```bash
wdm-ai sync [targets] [flags]
```

Targets:

```text
copilot claude codex gemini aider cline continue cursor goose opencode pi qwen roo windsurf
```

Default targets:

```text
copilot claude codex gemini cursor pi
```

Flags:

```bash
-g, --global             Sync globally into the user's home directory
    --dry-run            Preview changes without writing
    --refresh            Remove synced symlinks before syncing
    --purge              Remove all managed files from targets without re-syncing
    --no-backup          Skip automatic backup before changes
    --restore [file.zip] Restore interactively or from a backup file
    --restore-latest     Restore the most recent backup
    --pull               Pull latest content from GitHub before syncing
    --group <name>       Sync only items in a named group
-h, --help               Show sync help
```

Examples:

```bash
wdm-ai sync
wdm-ai sync -g
wdm-ai sync copilot codex --dry-run
wdm-ai sync --group default --refresh
```

## Sync Output

Sync writes managed content into harness-specific locations.

Common project locations:

| Harness | Project output |
| --- | --- |
| Copilot | `.github/agents`, `.github/skills`, `.github/copilot-instructions.md`, `.github/mcp.json` or configured MCP path |
| Claude | `.claude/agents`, `.claude/skills`, `.claude/rules`, `.claude/commands`, `.claude/hooks`, project `.mcp.json` |
| Codex | `.codex/agents/*.toml`, `.codex/config.toml`, `.agents/skills` |
| Gemini | `.gemini/agents`, `.gemini/skills`, `.gemini/settings.json` |

Global sync uses the same harness definitions but targets home-directory equivalents such as `~/.codex`, `~/.claude`, `~/.gemini`, `~/.copilot`, or harness-specific global roots.

WDM preserves unrelated user content in merged config files where supported.

## Backups And Restore

Sync creates backups before modifying files unless `--no-backup` is used.

Backups live in:

```text
~/.wdm/backups/
```

Restore interactively:

```bash
wdm-ai sync --restore
```

Restore the latest backup:

```bash
wdm-ai sync --restore-latest
```

Restore a specific backup:

```bash
wdm-ai sync --restore ~/.wdm/backups/<backup>.zip
```

## Configuration

Environment variables:

| Variable | Purpose | Default |
| --- | --- | --- |
| `AI_MANAGEMENT_HOME` | Source root and state directory | `~/.wdm` |
| `AI_MANAGEMENT_REPO` | GitHub `owner/repo` used by `sync --pull` | unset |
| `AI_MANAGEMENT_BRANCH` | Branch used by `sync --pull` | `main` |
| `AI_MANAGEMENT_WEB_RELOAD` | Internal reload flag for web development | unset |

Example:

```bash
AI_MANAGEMENT_HOME=~/my-wdm wdm-ai
AI_MANAGEMENT_REPO=your-org/ai-config wdm-ai sync --pull
```

## Authoring Content

Most source files are Markdown with YAML frontmatter.

Example agent:

```markdown
---
name: code-reviewer
description: Reviews code for correctness, maintainability, and security.
model: default-high
reasoning: high
mcp_servers:
  - github
  - playwright
skills:
  - debugging
  - testing
---

You are a senior code reviewer. Focus on correctness, security, test coverage,
and maintainability. Be concise and specific.
```

The web UI is the recommended editor for normal use. File view is available when exact raw control is needed.

## Models And Reasoning

Model defaults are configured in:

```text
~/.wdm/defaults.conf
```

Portable model tiers:

| Tier | Purpose |
| --- | --- |
| `default-low` | Faster or cheaper model |
| `default` | Standard model |
| `default-high` | More capable model |

Agent edit forms show model controls per harness. Harnesses that support reasoning show a reasoning select; unsupported harnesses show a disabled control.

Codex reasoning is represented as:

```text
Low
Default (Medium)
High
```

## Custom Harnesses

Create or edit harnesses in the web UI, or place JSON files in:

```text
~/.wdm/harnesses/core/
```

Minimal example:

```json
{
  "name": "mytool",
  "label": "My Tool",
  "default_enabled": false,
  "schemas": {
    "agents": ["name", "description", "model", "prompt"]
  },
  "field_mappings": {
    "agents": {
      "body": "prompt",
      "reasoning": "effort"
    }
  },
  "outputs": {
    "agents": {"extension": ".md"}
  },
  "sync": {
    "paths": {
      "project": {
        "agents": ".mytool/agents/{name}.md"
      },
      "global": {
        "agents": ".mytool/agents/{name}.md"
      }
    }
  }
}
```

The important part is the mapping contract: WDM forms stay canonical, and the harness file says how to output those fields for that tool.

## Troubleshooting

### Which command should I use?

Use `wdm-ai`. Published npm and Homebrew installs expose `wdm-ai` as the public command.

### The web UI does not auto-update

Run with reload while developing:

```bash
wdm-ai --reload
```

### A harness is missing

Open the Harnesses section in the web UI. Installed/detected harnesses are shown first. Use "show others" to see disabled or not-detected bundled harnesses.

You can enable a harness manually from its harness editor.

### A generated file is wrong for a harness

Check that harness's `field_mappings` and `schemas` in `~/.wdm/harnesses/core/<harness>.json`. WDM source fields should stay canonical; harness files should map them into target-specific names.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for local setup, validation commands, packaging notes, and contribution guidelines.

## License

MIT. See [LICENSE](LICENSE).
