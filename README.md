# AI Management

Write once, deploy everywhere. A framework for managing AI agents, skills, rules, workflows, hooks, and MCP servers across multiple coding assistants — **GitHub Copilot CLI, Claude Code, OpenAI Codex CLI, and Gemini CLI** — from a single source of truth.

You author one Markdown file per item. The build system translates it into each harness's native format (YAML frontmatter for Claude/Copilot/Gemini, TOML for Codex). The sync command deploys the result via symlinks and merged config files — either globally (`~/.claude/`, `~/.copilot/`, etc.) or per-project (`.claude/`, `.github/`, etc.).

## How It Works

```
┌─────────────────────────────────────────────────────────────────────┐
│  Source file (one per item, YAML frontmatter + markdown body)       │
│                                                                     │
│  ---                                                                │
│  name: code-reviewer                                                │
│  description: Reviews code for bugs and security issues             │
│  model: default-large                                               │
│  copilot_model: claude-sonnet-4.6                                   │
│  codex_copilot_description: Extended description for both           │
│  ---                                                                │
│  You are a senior code reviewer...                                  │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
                          wdm ai sync
                     (builds + deploys)
                                   │
       ┌────────────┬──────────────┼───────────────┬────────────┐
       ▼            ▼              ▼               ▼            ▼
  .github/      .claude/       .codex/         .gemini/    ~/.copilot/
  agents/       agents/        agents/         agents/     (global only)
  *.agent.md    *.md           *.toml          *.md
                .mcp.json      config.toml     settings.json
                (project)      (merged)        (merged)
```

You write **one file** per item. The build system generates harness-specific output respecting each tool's documented schema. The sync command deploys:

- **Symlinks** for per-file content (agents, skills, rules, workflows, hooks)
- **Merged config** for shared settings files (`.codex/config.toml`, `.gemini/settings.json`) — your existing user content is preserved
- **Generated files** for tools that expect a single consolidated file (`.github/copilot-instructions.md`)

## Why?

If you use more than one AI coding assistant, you've probably noticed each one wants its own subtly-different config:

- Claude Code reads `.claude/agents/*.md` with a `model` and `effort` field
- Copilot CLI reads `.github/agents/*.agent.md` with `mcp-servers` and `user-invocable`
- Codex CLI reads `~/.codex/agents/*.toml` (TOML, not YAML!) with `model_reasoning_effort` and `sandbox_mode`
- Gemini CLI reads `.gemini/agents/*.md` with `thinkingConfig.thinkingBudget`

Maintaining four parallel sets of config files by hand is error-prone. This repo lets you write one Markdown source file per item, with optional per-harness overrides, and have all four kept in sync.

## Quick Start

### 1. Install

```bash
# npm
npm install -g @wdm/ai-management

# bun
bun install -g @wdm/ai-management

# Homebrew
brew tap WD-Mitchell/wdm
brew install wdm-ai-management
```

All installers expose the `wdm` command. Installation bootstraps `~/.wdm`,
installs the AI Management skill globally, and syncs that skill into enabled
global harness skill locations.

For source checkouts:

```bash
git clone https://github.com/WD-Mitchell/WDM-AI-Management ~/.wdm-dev
cd ~/.wdm-dev
bin/wdm ai bootstrap
```

### 2. Open the Web UI

```bash
wdm ai
```

This launches the local web UI and opens it in your default browser.

### 3. Author your first item

Create `agents/core/code-reviewer.md`:

```markdown
---
name: code-reviewer
description: Reviews code for bugs, security, and style
model: default-large
copilot_description: Code reviewer for GitHub Copilot
---
You are an expert code reviewer. Focus on correctness, security,
and maintainability. Do not comment on style preferences.
```

### 4. Install & deploy

```bash
# Interactive menu
wdm

# Or install everything in the default group
wdm ai --install

# Sync to the current project
wdm ai sync

# Or sync globally (writes to ~/.claude/, ~/.codex/, etc.)
wdm ai sync -g

# Preview without writing
wdm ai sync --dry-run

# Local web GUI
wdm ai --reload
```

## Key Concepts

| Concept | Description |
|---------|-------------|
| **Content types** | `agents`, `skills`, `rules`, `workflows`, `hooks`, `mcp` |
| **Harnesses** | `copilot`, `claude`, `codex`, `gemini` |
| **Harness definitions** | Files in `harnesses/core/*.json` that define schemas, output extensions, and sync layout |
| **Groups** | Named sets of items (`groups/*.group`) for batch install |
| **Templates** | Combine groups + individual items (`templates/*.template`) — apply to a project in one command |
| **Global install** | Deploy to user home (`~/.claude/`, `~/.copilot/`, `~/.codex/`, `~/.gemini/`) |
| **Project install** | Deploy to the current repo (`.claude/`, `.github/`, `.codex/`, `.gemini/`) |

## Content Authoring

### Frontmatter Fields

Every source file uses YAML frontmatter. Fields can be overridden per-harness using prefixes:

| Prefix pattern | Priority | Example |
|---------------|----------|---------|
| `<harness>_<field>` | Highest | `copilot_model: gpt-4.1` |
| `<h1>_<h2>_<field>` | Multi-harness | `codex_copilot_description: ...` |
| `global_<field>` | All harnesses | `global_model: claude-sonnet-4.6` |
| `<field>` | Base fallback | `model: default` |

Harness prefixes come from `harnesses/core/*.json`. The built-in prefixes are `copilot`, `claude`, `codex`, `gemini`, plus `global`.

### Model Tiers

Use tier tokens for portable model references. They resolve per-harness via `defaults.conf`:

| Token | Typical resolution |
|-------|-------------------|
| `default` | Standard model for each harness |
| `default-small` | Fast/cheap model |
| `default-large` | Premium/powerful model |

`defaults.conf` also injects per-tier reasoning fields (`effort` for Claude, `model_reasoning_effort` for Codex, `thinkingBudget` for Gemini).

### Per-Harness Field Schemas

The build system whitelists only fields documented by each tool, so unknown or harness-specific keys don't leak into the wrong output. See `ai_management/build.py` (`AGENT_SCHEMAS`, `SKILL_SCHEMAS`, etc.) for the authoritative lists.

### Custom Harnesses

Harnesses are defined by JSON files in `harnesses/core/`. Each file names the harness, declares per-content schemas, output extensions, and sync destination templates. Add a new `harnesses/core/<name>.json`, then use that harness name as a sync target and frontmatter prefix.

At minimum, a custom Markdown-based harness can define:

```json
{
  "name": "mytool",
  "label": "My Tool",
  "schemas": {
    "agents": ["name", "description", "model"],
    "skills": ["name", "description"]
  },
  "outputs": {
    "agents": {"extension": ".md"},
    "skills": {"directory": true}
  },
  "sync": {
    "paths": {
      "project": {
        "agents": ".mytool/agents/{name}.md",
        "skills": ".mytool/skills/{name}/"
      },
      "global": {
        "agents": ".mytool/agents/{name}.md",
        "skills": ".mytool/skills/{name}/"
      }
    }
  }
}
```

The built-in harnesses are also represented as files there. Codex and MCP still use specialized renderers where their formats require TOML or merged config output.

## Groups

Group files (`groups/*.group`) bundle related items:

```ini
# default.group — Sensible starter set
[agents]
senior-developer
code-reviewer

[skills]
debugging
refactor

[rules]
code-style

[mcp]
github
```

Install a group: `wdm ai --install-group default`

## Templates

Templates are reusable field and body presets for items such as agents, skills, MCP servers, rules, workflows, and hooks. Manage them in the web UI:

```bash
wdm ai
```

Groups now cover install sets. Use `wdm ai --install-group <name>` and `wdm ai sync --group <name>` for repo or project sets.

## CLI Reference

### Install / manage

```
wdm ai                          # interactive menu
wdm ai --list                   # list available skills
wdm ai --list-groups            # list groups
wdm ai --list-templates         # list templates
wdm ai --installed              # show installed items

wdm ai --install                # install the "default" group
wdm ai --install-all            # install everything (all types)
wdm ai --install-all-<type>     # install all of one type
                                    #   (agents | skills | rules | workflows | hooks | mcp)

wdm ai --install-agent     <names>   # comma-separated
wdm ai --install-skill     <names>
wdm ai --install-rule      <names>
wdm ai --install-workflow  <names>
wdm ai --install-hook      <names>
wdm ai --install-mcp       <names>

wdm ai --install-group         <name>
wdm ai --install-group-agents  <name>   # restrict to one type
wdm ai --install-group-skills  <name>
wdm ai --install-group-rules   <name>
wdm ai --install-group-workflows <name>
wdm ai --install-group-hooks   <name>
wdm ai --install-group-mcp     <name>

wdm ai --uninstall-agent    <names>
wdm ai --uninstall-skill    <names>
wdm ai --uninstall-rule     <names>
wdm ai --uninstall-workflow <names>
wdm ai --uninstall-hook     <names>
wdm ai --uninstall-mcp      <names>
```

### Sync / deploy

```
wdm ai sync [targets] [flags]

  targets:  copilot codex claude gemini       (default: all)

  -g, --global         Sync to ~/ (globally available) instead of current project
      --dry-run        Preview without writing
      --refresh        Remove existing managed symlinks before re-syncing
      --purge          Remove all managed files (no re-sync)
      --no-backup      Skip automatic pre-change backup
      --restore [file] Restore from backup — interactive picker or zip path
      --restore-latest Restore the most recent backup
      --pull           Pull latest content from GitHub before syncing
      --group <name>   Sync only items in a group (can be repeated)
  -h, --help           Sync-specific help
```

See [`flags.md`](flags.md) for a longer reference with examples.

### Web GUI

```
wdm ai [--host 127.0.0.1] [--port 8765] [--no-open] [--reload]
```

The web GUI is a lightweight local interface for browsing, selecting, editing, previewing, and dry-running sync for agents, skills, MCP servers, groups, and templates. It uses the same file-backed source of truth and build/sync code as the CLI; there is no database or frontend build step.

## Supported Harnesses

| Harness | Deploy method | Project layout | Global layout |
|---------|--------------|----------------|---------------|
| **GitHub Copilot CLI** | Symlinks + generated `copilot-instructions.md` | `.github/agents/*.agent.md`, `.github/skills/`, `.github/copilot-instructions.md`, `.github/hooks/` | `~/.copilot/{agents,skills,instructions,hooks}/`, `~/.copilot/mcp-config.json` |
| **Claude Code** | Symlinks + project `.mcp.json` | `.claude/{agents,skills,rules,commands,hooks}/`, `.mcp.json` at repo root | `~/.claude/{agents,skills,rules,commands,hooks}/` (MCP via `~/.claude.json` is left untouched) |
| **OpenAI Codex CLI** | Symlinks (`.toml`) + merged `config.toml` | `.codex/agents/*.toml`, `~/.agents/skills/`, MCP merged into `.codex/config.toml` (`[mcp_servers.*]`) | `~/.codex/agents/*.toml`, `~/.agents/skills/`, MCP merged into `~/.codex/config.toml` |
| **Gemini CLI** | Native subagents + merged `settings.json` | `.gemini/{agents,skills}/`, MCP merged into `.gemini/settings.json` (`mcpServers` key) | `~/.gemini/{agents,skills}/`, MCP merged into `~/.gemini/settings.json` |

All formats are sourced from each tool's official documentation. The merged-config writers (Codex `config.toml`, Gemini `settings.json`) preserve unrelated user content and use delimited managed blocks where appropriate.

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `AI_MANAGEMENT_HOME` | Override the source content and state directory | `~/.wdm` |
| `AI_MANAGEMENT_REPO` | GitHub `owner/repo` slug used by `sync --pull` | _unset_ — required to use `--pull` |
| `AI_MANAGEMENT_BRANCH` | Branch to fetch from | `main` |

Set these in your shell profile or per-invocation:

```bash
AI_MANAGEMENT_REPO=your-org/ai-management wdm ai sync --pull
```

## Directory Structure

```
.wdm/
├── agents/core/         # Agent definitions (*.md)
├── skills/core/         # Skill directories; AI-Management is only SKILL.md
├── rules/core/          # Rule definitions (*.md)
├── workflows/core/      # Workflow definitions (*.md)
├── hooks/core/          # Hook scripts
├── mcp/core/            # MCP server definitions (*.md with frontmatter, or *.json)
├── harnesses/core/      # Harness definitions (*.json)
├── groups/              # Group files (*.group)
├── templates/core/      # Item editor templates (*.template)
├── defaults.conf        # Model tier → actual model mapping (per harness)
├── README.md
└── flags.md             # Long-form CLI reference
```

The installed package also includes `ai_management/`, which is the Python runtime behind the `wdm ai` and `wdm-ai` commands. That runtime is not part of the installed AI Management skill.

> **Requires:** Python 3.10 or newer (standard library only — no pip dependencies)

## Backups

Every sync that modifies files first writes a `.zip` snapshot to `~/.wdm/backups/` (or `$AI_MANAGEMENT_HOME/backups/`). Skip with `--no-backup`. Restore with `--restore` (interactive picker) or `--restore-latest`.

## Contributing

Contributions welcome. Items most useful to share back:

- New agent / skill / rule definitions (`agents/core/*.md`, `skills/core/<name>/SKILL.md`, `rules/core/*.md`)
- New groups and templates (`groups/*.group`, `templates/*.template`)
- MCP server definitions (`mcp/core/*.md`)
- Harness definitions (`harnesses/core/*.json`)
- Bug fixes and additional harness support in `ai_management/`

When adding a new harness or schema field, please cite the upstream documentation in a comment so future maintainers can verify it.

## License

MIT — see [LICENSE](LICENSE).
