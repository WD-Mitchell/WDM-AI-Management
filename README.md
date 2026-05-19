# AI Management

Write once, deploy everywhere. A framework for managing AI agents, skills, rules, workflows, hooks, and MCP configs across all your coding tools from a single source of truth.

## How It Works

```
┌─────────────────────────────────────────────────────────────────────┐
│  Source file (one per item, YAML frontmatter + markdown body)       │
│                                                                     │
│  ---                                                                │
│  description: Reviews code for bugs and security issues             │
│  model: default-large                                               │
│  copilot_model: claude-sonnet-4                                     │
│  codex_copilot_description: Extended description for both           │
│  ---                                                                │
│  You are a senior code reviewer...                                  │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
                              build.py
                                   │
              ┌────────────┬───────┴───────┬────────────┐
              ▼            ▼               ▼            ▼
         .copilot/     .claude/        .codex/     .gemini/
         (symlink)     (symlink)       (symlink)   (concat)
```

You write **one file** per agent/skill/rule. The build system generates harness-specific versions. The sync script deploys them — globally or per-project — via symlinks (or concatenation for Gemini).

## Key Concepts

| Concept | Description |
|---------|-------------|
| **Content types** | `agents`, `skills`, `rules`, `workflows`, `hooks`, `mcp` |
| **Harnesses** | GitHub Copilot, Claude Code, Codex, Gemini CLI |
| **Groups** | Named sets of items (`.group` files) for batch install |
| **Templates** | Combine groups + individual items — apply to a project in one command |
| **Global install** | Deploy to `~/ai-management/` → available in all projects |
| **Project install** | Deploy to current repo only → committed or gitignored per preference |

## Quick Start

### 1. Clone & configure

```bash
git clone <your-repo-url> ~/ai-management
cd ~/ai-management
```

### 2. Add your content

Create a source file — for example `agents/code-reviewer.md`:

```markdown
---
description: Reviews code for bugs, security, and style
model: default-large
copilot_description: Code reviewer for GitHub Copilot
---
You are an expert code reviewer. Focus on correctness, security,
and maintainability. Do not comment on style preferences.
```

### 3. Install & deploy

```bash
# Install items interactively
./install.sh

# Or install a specific group
./install.sh --install-group core-development

# Or apply a template to the current project
./install.sh --template web-development

# Sync/deploy to current project
./install.sh sync

# Sync globally (available in every project)
./install.sh sync -g
```

## Content Authoring

### Frontmatter Fields

Every source file uses YAML frontmatter. Fields can be overridden per-harness using prefixes:

| Prefix pattern | Priority | Example |
|---------------|----------|---------|
| `<harness>_<field>` | Highest | `copilot_model: gpt-4.1` |
| `<h1>_<h2>_<field>` | Multi-harness | `codex_copilot_description: ...` |
| `global_<field>` | All harnesses | `global_model: claude-sonnet-4` |
| `<field>` | Base fallback | `model: default` |

### Model Tiers

Use tier tokens for portable model references:

| Token | Resolved per harness via `defaults.conf` |
|-------|------------------------------------------|
| `default` | Standard model for each harness |
| `default-small` | Fast/cheap model |
| `default-large` | Premium/powerful model |

## Groups

Group files (`groups/*.group`) bundle related items:

```ini
# core-development.group — Essential development tools
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

Install a group: `./install.sh --install-group core-development`

## Templates

Templates (`templates/*.template`) combine groups and individual items for a complete project setup:

```ini
# web-development.template — Full-stack web setup

[groups]
core-development
testing

[agents]
frontend-developer
api-designer

[skills]
web-coder
premium-frontend-ui

[mcp]
browser-tools
```

Apply to current project: `./install.sh --template web-development`

This creates a `.ai-management` file in the project root, so subsequent `install.sh sync` runs auto-apply the same template.

## CLI Reference

```bash
install.sh [options]

  (no flags)                    Interactive menu
  --install                     Install default group
  --install-agent <names>       Install individual agents
  --install-group <name>        Install all items in a group
  --template <name>             Apply template to project
  --template <name> --global    Apply template globally
  --list                        List available items
  --list-groups                 List groups
  --list-templates              List templates
  --installed                   Show what's installed

install.sh sync [targets] [flags]

  (no flags)        Sync to current project (auto-detect template)
  -g, --global      Sync globally
  -p, --pull        Pull latest from remote before sync
  --group <name>    Sync a specific group
  --template <name> Apply a template
  --dry-run         Show what would happen
  --refresh         Remove existing before re-syncing
  --purge           Remove all managed files (no re-sync)
  --restore         Restore from backup
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `AI_MANAGEMENT_HOME` | Override install location | `~/ai-management` |
| `AI_MANAGEMENT_REPO` | GitHub `org/repo` for `--pull` | *(must set)* |
| `AI_MANAGEMENT_BRANCH` | Remote branch | `main` |

## Directory Structure

```
~/ai-management/
├── agents/              # Agent definitions (*.md)
├── skills/              # Skill directories (SKILL.md + files)
│   └── AI-Management/  # This management tool
│       ├── install.sh  # Entry point (Python)
│       ├── build.py    # Standalone build wrapper
│       ├── ai_management/  # Python package
│       │   ├── build.py    # Build engine (frontmatter, field resolution)
│       │   ├── cli.py      # CLI argument parsing & routing
│       │   ├── groups.py   # Group & template resolution
│       │   ├── install.py  # Install tracking
│       │   ├── pull.py     # GitHub pull/download
│       │   ├── sync.py     # Sync/deploy to harnesses
│       │   ├── tui.py      # Interactive TUI menus
│       │   └── utils.py    # Shared utilities (colors, paths, config)
│       └── SKILL.md    # Detailed docs
├── rules/               # Rule definitions (*.md)
├── workflows/           # Workflow definitions (*.md)
├── hooks/               # Hook scripts (e.g., post-merge)
├── mcp/                 # MCP server configs (*.md)
├── groups/              # Group files (*.group)
├── templates/           # Template files (*.template)
├── defaults.conf        # Model tier → actual model mapping
└── install.sh           # Symlink → skills/AI-Management/install.sh
```

> **Requires:** Python 3.8+ (stdlib only, no pip packages)

## Supported Harnesses

| Harness | Deploy method | Location |
|---------|--------------|----------|
| GitHub Copilot | Symlinks | `.github/copilot-instructions.md`, `.github/agents/` |
| Claude Code | Symlinks | `.claude/agents/`, `.claude/rules/` |
| Codex | Symlinks | `.codex/agents/`, `.codex/rules/` |
| Gemini CLI | Concatenation | `.gemini/GEMINI.md` |

## Per-Project Config

When you apply a template or group to a project, a `.ai-management` file is created:

```
web-development
```

On subsequent `install.sh sync` runs (without flags), this file is auto-detected and the template is re-applied. Add it to `.gitignore` or commit it — your choice.

## Documentation

See [`skills/AI-Management/SKILL.md`](skills/AI-Management/SKILL.md) for full documentation:
- Complete field resolution rules
- Build system internals
- Backup/restore procedures
- All CLI flags and combinations

## License

MIT
