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
                          install.sh sync
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

### 1. Get the repo

```bash
git clone https://github.com/<your-fork>/ai-management ~/ai-management
cd ~/ai-management
```

(Or fork this repo and clone your fork — the `--pull` command later will pull updates from whatever you configure as `AI_MANAGEMENT_REPO`.)

### 2. Author your first item

Create `agents/code-reviewer.md`:

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

### 3. Install & deploy

```bash
# Interactive menu
./install.sh

# Or install everything in the default group
./install.sh --install

# Sync to the current project
./install.sh sync

# Or sync globally (writes to ~/.claude/, ~/.codex/, etc.)
./install.sh sync -g

# Preview without writing
./install.sh sync --dry-run
```

## Key Concepts

| Concept | Description |
|---------|-------------|
| **Content types** | `agents`, `skills`, `rules`, `workflows`, `hooks`, `mcp` |
| **Harnesses** | `copilot`, `claude`, `codex`, `gemini` |
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

Harness prefixes are: `copilot`, `claude`, `codex`, `gemini`, plus `global`.

### Model Tiers

Use tier tokens for portable model references. They resolve per-harness via `defaults.conf`:

| Token | Typical resolution |
|-------|-------------------|
| `default` | Standard model for each harness |
| `default-small` | Fast/cheap model |
| `default-large` | Premium/powerful model |

`defaults.conf` also injects per-tier reasoning fields (`effort` for Claude, `model_reasoning_effort` for Codex, `thinkingBudget` for Gemini).

### Per-Harness Field Schemas

The build system whitelists only fields documented by each tool, so unknown or harness-specific keys don't leak into the wrong output. See `skills/AI-Management/ai_management/build.py` (`AGENT_SCHEMAS`, `SKILL_SCHEMAS`, etc.) for the authoritative lists.

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

Install a group: `./install.sh --install-group default`

## Templates

Templates (`templates/*.template`) combine groups and individual items for a complete project setup:

```ini
# example.template

[groups]
default

[agents]
frontend-developer
api-designer

[skills]
web-coder

[mcp]
browser-tools
```

Apply to current project: `./install.sh --template example`

This writes a `.ai-management` file in the project root, so subsequent `./install.sh sync` runs re-apply the same template automatically.

## CLI Reference

### Install / manage

```
install.sh                          # interactive menu
install.sh --list                   # list available skills
install.sh --list-groups            # list groups
install.sh --list-templates         # list templates
install.sh --installed              # show installed items

install.sh --install                # install the "default" group
install.sh --install-all            # install everything (all types)
install.sh --install-all-<type>     # install all of one type
                                    #   (agents | skills | rules | workflows | hooks | mcp)

install.sh --install-agent     <names>   # comma-separated
install.sh --install-skill     <names>
install.sh --install-rule      <names>
install.sh --install-workflow  <names>
install.sh --install-hook      <names>
install.sh --install-mcp       <names>

install.sh --install-group         <name>
install.sh --install-group-agents  <name>   # restrict to one type
install.sh --install-group-skills  <name>
install.sh --install-group-rules   <name>
install.sh --install-group-workflows <name>
install.sh --install-group-hooks   <name>
install.sh --install-group-mcp     <name>

install.sh --template <name>             # apply template to current project
install.sh --template <name> --global    # apply template globally

install.sh --uninstall-agent    <names>
install.sh --uninstall-skill    <names>
install.sh --uninstall-rule     <names>
install.sh --uninstall-workflow <names>
install.sh --uninstall-hook     <names>
install.sh --uninstall-mcp      <names>
```

### Sync / deploy

```
install.sh sync [targets] [flags]

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
      --template <name> Sync items defined in a template
  -h, --help           Sync-specific help
```

See [`flags.md`](flags.md) for a longer reference with examples.

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
| `AI_MANAGEMENT_HOME` | Directory holding source content & state when running outside the repo checkout | `~/ai-management` |
| `AI_MANAGEMENT_REPO` | GitHub `owner/repo` slug used by `sync --pull` | _unset_ — required to use `--pull` |
| `AI_MANAGEMENT_BRANCH` | Branch to fetch from | `main` |

Set these in your shell profile or per-invocation:

```bash
AI_MANAGEMENT_REPO=your-org/ai-management ./install.sh sync --pull
```

## Directory Structure

```
ai-management/
├── agents/              # Agent definitions (one *.md per agent)
├── skills/              # Skill directories (each contains SKILL.md + assets)
│   └── AI-Management/   # The management tool itself (this skill)
│       ├── install.sh   # Python entrypoint (also symlinked from repo root)
│       ├── build.py     # Standalone CLI for the build engine
│       ├── SKILL.md     # Detailed docs / internal reference
│       └── ai_management/
│           ├── build.py    # Build engine (frontmatter parsing, field resolution, per-harness emitters)
│           ├── cli.py      # CLI argument parsing & routing
│           ├── groups.py   # Group & template resolution
│           ├── install.py  # Install tracking
│           ├── pull.py     # GitHub pull/download (--pull)
│           ├── sync.py     # Sync / deploy to harnesses
│           ├── tui.py      # Interactive TUI menus
│           └── utils.py    # Shared utilities (colors, paths, dataclasses)
├── rules/               # Rule definitions (*.md)
├── workflows/           # Workflow definitions (*.md) — slash-commands for Claude
├── hooks/               # Hook scripts (e.g., post-merge)
├── mcp/                 # MCP server definitions (*.md with frontmatter, or *.json)
├── groups/              # Group files (*.group)
├── templates/           # Template files (*.template)
├── defaults.conf        # Model tier → actual model mapping (per harness)
├── install.sh           # Symlink → skills/AI-Management/install.sh
├── README.md
└── flags.md             # Long-form CLI reference
```

> **Requires:** Python 3.10 or newer (standard library only — no pip dependencies)

## Per-Project Config

When you apply a template or group to a project, a `.ai-management` file is created at the project root:

```
example
```

On subsequent `./install.sh sync` runs (without flags), this file is auto-detected and the same template is re-applied. Add it to `.gitignore` or commit it — your choice.

## Backups

Every sync that modifies files first writes a `.zip` snapshot to `~/ai-management/backups/` (or `$AI_MANAGEMENT_HOME/backups/`). Skip with `--no-backup`. Restore with `--restore` (interactive picker) or `--restore-latest`.

## Contributing

Contributions welcome. Items most useful to share back:

- New agent / skill / rule definitions (`agents/*.md`, `skills/<name>/SKILL.md`, `rules/*.md`)
- New groups and templates (`groups/*.group`, `templates/*.template`)
- MCP server definitions (`mcp/*.md`)
- Bug fixes and additional harness support in `skills/AI-Management/ai_management/`

When adding a new harness or schema field, please cite the upstream documentation in a comment so future maintainers can verify it.

## License

MIT — see [LICENSE](LICENSE).
