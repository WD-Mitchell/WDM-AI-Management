# AI Management Skill

Manage AI agents, skills, rules, workflows, hooks, and MCP configs across all coding tools from a single source of truth at `~/ai-management/`.

## Overview

| Type      | Source location                    | Format                         |
|-----------|------------------------------------|---------------------------------|
| Agents    | `~/ai-management/agents/*.md`      | Markdown with YAML frontmatter |
| Skills    | `~/ai-management/skills/*/`        | Directory with `SKILL.md`      |
| Rules     | `~/ai-management/rules/*.md`       | Markdown with YAML frontmatter |
| Workflows | `~/ai-management/workflows/*.md`   | Markdown with YAML frontmatter |
| Hooks     | `~/ai-management/hooks/*`          | Scripts or directories         |
| MCP       | `~/ai-management/mcp/*.md`         | Markdown with YAML frontmatter |

### Deployment modes

| Mode | Command | Where content goes |
|------|---------|-------------------|
| **Project** (default) | `install.sh sync` | Current git repo root |
| **Global** | `install.sh sync -g` | `$HOME` (available everywhere) |
| **Template** | `install.sh sync --template <name>` | Current project + saves config |

## Script: `install.sh sync`

### Targets

Specify one or more, or omit to sync all:

| Target  | Command             | Deploy method |
|---------|---------------------|---------------|
| Copilot | `./install.sh sync copilot` | Symlinks to `.github/copilot/` |
| Claude  | `./install.sh sync claude`  | Symlinks to `.claude/` |
| Codex   | `./install.sh sync codex`   | Symlinks to `.codex/` |
| Gemini  | `./install.sh sync gemini`  | Concatenation to `.gemini/GEMINI.md` |

### Flags

| Flag | Description |
|------|-------------|
| *(none)* | Sync default group to all targets (auto-detects project template) |
| `-g`, `--global` | Target `$HOME` instead of project root |
| `--dry-run` | Preview without changes |
| `--refresh` | Remove existing symlinks before syncing |
| `--purge` | Remove all managed files, don't re-sync |
| `--purge --refresh` | Clean slate + re-sync |
| `--no-backup` | Skip automatic backup |
| `--restore` | Interactive backup restore |
| `--restore-latest` | Restore most recent backup |
| `--restore <file>` | Restore specific backup |
| `--pull` | Download/update from remote repo |
| `--group <name>` | Sync a specific group (repeatable) |
| `--template <name>` | Apply a template to the project |
| `-h`, `--help` | Show help |

### Flag combinations

```bash
# Template: apply web-development preset to this project
./install.sh sync --template web-development

# Group: sync only the backend group to Claude
./install.sh sync claude --group backend

# Purge and re-sync Copilot without backup
./install.sh sync copilot --purge --refresh --no-backup

# Dry-run a global sync
./install.sh sync -g --dry-run

# Combine multiple groups
./install.sh sync --group backend --group testing
```

### Project auto-detection

When run without `--group` or `--template`, install.sh sync checks for a `.ai-management` file in the project root. If found, it re-applies the saved template automatically. This means:

1. Apply template once: `install.sh sync --template web-development`
2. Future syncs auto-apply: `install.sh sync` (reads `.ai-management`)

## Templates

Templates combine groups and individual items into a project preset. Stored in `~/ai-management/templates/*.template`.

### Template file format

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

[rules]
code-style

[mcp]
browser-tools
github
```

### Using templates

```bash
# Apply to current project
./install.sh sync --template web-development
./install.sh --template web-development

# Apply globally
./install.sh --template web-development --global

# List available templates
./install.sh --list-templates
```

## Groups

Groups are named collections in `~/ai-management/groups/*.group`:

```ini
# core-development.group — Essential dev tools
[agents]
senior-developer
code-reviewer

[skills]
debugging
refactor

[rules]
*

[hooks]
post-merge

[mcp]
github
```

Use `*` in any section to include all items of that type.

### Using groups

```bash
./install.sh sync --group core-development
./install.sh sync --group backend --group testing
./install.sh --install-group core-development
```

## Script: `install.sh`

Manages which items are selected. Tracks state in `~/ai-management/installed/{type}.conf`.

### Key commands

```bash
./install.sh                              # Interactive menu
./install.sh --install                    # Install default group
./install.sh --install-agent senior-developer,code-reviewer
./install.sh --install-group testing
./install.sh --template web-development   # Apply template to project
./install.sh --list-templates             # List templates
./install.sh --install-all-skills         # Install all skills
./install.sh --installed                  # Show installed items
```

## Build System

The build step transforms universal source files into per-harness versions before deployment.

### Field resolution priority

1. `{harness}_{field}` — highest (e.g., `codex_model: o3`)
2. `{h1}_{h2}_{field}` — multi-prefix (e.g., `codex_copilot_description: ...`)
3. `global_{field}` — all harnesses (e.g., `global_model: claude-sonnet-4`)
4. `{field}` — base fallback (e.g., `model: default`)

### Model tiers

Use tokens instead of hardcoded model names:

| Token | Meaning |
|-------|---------|
| `default` | Standard model per harness |
| `default-small` | Fast/cheap model |
| `default-large` | Premium model |

Configured in `~/ai-management/defaults.conf`.

### The `__omit__` sentinel

Suppress a field for a specific harness:

```yaml
codex_model: __omit__    # No model field in Codex output
```

### Per-harness schemas

| Harness | Allowed agent fields |
|---------|---------------------|
| Copilot | `name`, `description`, `model`, `reasoning_effort` |
| Claude  | `name`, `description`, `model`, `effort` |
| Codex   | `name`, `description`, `model`, `model_reasoning_effort`, `sandbox_mode`, `mcp_servers`, `nickname_candidates`, `developer_instructions` |
| Gemini  | `name`, `description`, `model`, `thinkingLevel` |

Unrecognized fields are silently dropped.

## First-time Setup

```bash
# Clone the repo
git clone <your-repo-url> ~/ai-management

# Set remote for --pull updates (optional)
export AI_MANAGEMENT_REPO="your-org/your-repo"

# Install default content
cd ~/ai-management && ./install.sh --install

# Sync to your project
cd ~/your-project && ~/ai-management/skills/AI-Management/install.sh sync
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AI_MANAGEMENT_HOME` | Override source location | `~/ai-management` |
| `AI_MANAGEMENT_REPO` | GitHub `org/repo` for `--pull` | *(must set)* |
| `AI_MANAGEMENT_BRANCH` | Remote branch | `main` |

## Backups

Created automatically before every sync/purge/refresh (unless `--no-backup`).

```bash
# Interactive restore
./install.sh sync claude --restore

# Restore latest
./install.sh sync --restore-latest
```

Backup dirs are never removed by `--purge`.

## Important Notes

- Source of truth: `~/ai-management/{type}/*.md` — edit here, then sync
- Built artifacts in `~/ai-management/{type}/{harness}/` are generated — don't edit
- Copilot/Claude/Codex use **symlinks**; Gemini uses **concatenation**
- Use `--dry-run` when unsure what a command will do
- `.ai-management` project file stores the active template for auto-detection
