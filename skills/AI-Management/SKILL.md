# AI Management

Manage shared AI agent definitions, skills, rules, workflows, hooks, and MCP configs distributed across all coding tools (GitHub Copilot, Claude Code, Codex, Gemini CLI) from a single source of truth.

## Overview

All content lives in `~/.ai-management/` organised by type:

| Type      | Source location                       | Format                |
|-----------|---------------------------------------|-----------------------|
| Agents    | `~/.ai-management/agents/*.md`        | Markdown with YAML frontmatter |
| Skills    | `~/.ai-management/skills/*/`          | Directory with `SKILL.md`      |
| Rules     | `~/.ai-management/rules/*.md`         | Markdown with YAML frontmatter |
| Workflows | `~/.ai-management/workflows/*.md`     | Markdown with YAML frontmatter |
| Hooks     | `~/.ai-management/hooks/*`            | Scripts or directories         |
| MCP       | `~/.ai-management/mcp/*.md`           | Markdown with YAML frontmatter |

The **`sync.sh`** script builds harness-specific versions and distributes them via symlinks (or concatenation for Gemini). The **`install.sh`** script manages which items are selected for installation.

### Project vs Global mode

By default, `sync.sh` targets the **current project** (git root or cwd). Use `-g` / `--global` to target your home directory instead:

```bash
# Sync to current project (default)
./sync.sh

# Sync globally to ~/
./sync.sh -g
./sync.sh --global
```

The source (`~/.ai-management/`) is always global — only the deployment target changes.

## Script: `sync.sh`

### Targets

The script supports four targets. Specify one or more, or omit to sync all:

| Target  | Command             | Agents                           | Skills                           | Rules                                | MCP                           |
|---------|---------------------|----------------------------------|----------------------------------|--------------------------------------|-------------------------------|
| Copilot | `./sync.sh copilot` | `.copilot/agents/` (symlinks)    | `.copilot/skills/` (symlinks)    | `.copilot/instructions/` (symlinks)  | `.copilot/mcp.json`          |
| Claude  | `./sync.sh claude`  | `.claude/agents/` (symlinks)     | `.claude/skills/` (symlinks)     | `.claude/rules/` (symlinks)          | `.claude/mcp.json`           |
| Codex   | `./sync.sh codex`   | `.codex/agents/` (symlinks)      | `.codex/skills/` (symlinks)      | `.codex/instructions/` (symlinks)    | `.codex/mcp-servers.json`    |
| Gemini  | `./sync.sh gemini`  | `.gemini/GEMINI.md` (concat)     | `.gemini/GEMINI.md` (concat)     | `.gemini/GEMINI.md` (concat)         | `.gemini/mcp-servers.json`   |

Paths are relative to the target root (project root by default, `$HOME` with `-g`).

### Flags

| Flag               | Description                                                        |
|--------------------|--------------------------------------------------------------------|
| *(none)*           | Sync default group to all targets. Backs up first.                 |
| `-g`, `--global`   | Target `$HOME` instead of the current project root.                |
| `--dry-run`        | Preview what would happen without making changes.                  |
| `--refresh`        | Remove existing symlinks before re-syncing (clean slate).          |
| `--purge`          | Remove **all** managed files from targets. Does not re-sync.      |
| `--purge --refresh`| Purge all files, then re-sync fresh.                               |
| `--no-backup`      | Skip the automatic backup step before changes.                     |
| `--restore`        | Interactively list available backups and choose one to restore.    |
| `--restore-latest` | Restore the most recent backup automatically.                      |
| `--restore <file>` | Restore a specific backup zip by filename.                         |
| `--pull`           | Download/update content from GitHub into `~/.ai-management/`.     |
| `--group <name>`   | Use a specific group file (repeatable). Defaults to `default`.     |
| `-h`, `--help`     | Show help text.                                                    |

### Flag combinations

Flags and targets can be freely combined:

```bash
# Purge and re-sync only Claude, no backup
./sync.sh claude --purge --refresh --no-backup

# Dry-run a global sync to see what would change
./sync.sh -g --dry-run

# Restore Claude agents from the latest backup
./sync.sh claude --restore-latest

# Sync a specific group to the current project
./sync.sh --group backend copilot claude

# Combine multiple groups (entries are deduplicated)
./sync.sh --group backend --group testing
```

### Backups

Backups are created **automatically** before every sync, purge, or refresh unless `--no-backup` is passed. They are stored **per-target, per-type** inside the target's directory:

| Target  | Backup locations                                                                    |
|---------|-------------------------------------------------------------------------------------|
| Copilot | `.copilot/agents/backups/`, `.copilot/skills/backups/`, `.copilot/instructions/backups/` etc. |
| Claude  | `.claude/agents/backups/`, `.claude/skills/backups/`, `.claude/rules/backups/` etc.  |
| Codex   | `.codex/agents/backups/`, `.codex/skills/backups/` etc.                              |
| Gemini  | `.gemini/backups/`                                                                   |

Backup filenames follow the pattern: `<target>-<type>-<YYYYMMDD>-<HHMMSS>.zip`

Backup directories are **never removed** by `--purge`. The script includes safeguards to protect them.

Restore works for all types — choose the target and the backup selection will show all available backups for that target.

## First-time setup

Use `--pull` to bootstrap `~/.ai-management` directly from your configured repository:

```bash
# Set the source repository (required)
export AI_MANAGEMENT_REPO="your-org/your-repo"

# Run the sync script with --pull to download content
~/.ai-management/skills/AI-Management/sync.sh --pull
```

After the first pull, the script is available at `~/.ai-management/skills/AI-Management/sync.sh`.

To update to the latest version at any time:

```bash
~/.ai-management/skills/AI-Management/sync.sh --pull
```

If a local clone of the content repo exists, the script symlinks into `~/.ai-management` automatically — no `--pull` needed.

### Environment variables

| Variable               | Description                                         | Default               |
|------------------------|-----------------------------------------------------|-----------------------|
| `AI_MANAGEMENT_REPO`   | GitHub `org/repo` for `--pull` (required for pull)  | *(none — must be set)* |
| `AI_MANAGEMENT_BRANCH` | Branch to pull from                                 | `main`                |
| `AI_MANAGEMENT_HOME`   | Override `~/.ai-management` location                | `$HOME/.ai-management` |

## Groups

Groups let you selectively sync subsets of agents, skills, rules, workflows, hooks, and MCP configs. Group files live in `~/.ai-management/groups/` with a `.group` extension.

### Group file format

INI-like sections with bare names (no file extensions). Use `*` to include everything in a section:

```ini
# my-team.group
[agents]
senior-developer
code-reviewer

[skills]
AI-Management

[rules]
*

[workflows]
code-review

[hooks]
post-merge

[mcp]
github
```

Available sections: `[agents]`, `[skills]`, `[rules]`, `[workflows]`, `[hooks]`, `[mcp]`.
Omitted sections resolve to zero items (nothing synced for that type).

### Default group

When no `--group` is specified, the `default` group is used. Create a `default.group` in your content repository to define what ships by default.

Use `--install-all` or an `all` group to install everything.

### Using groups

```bash
# Use the "minimal" group
./sync.sh --group minimal

# Combine multiple groups (entries are deduplicated)
./sync.sh --group backend --group testing

# Groups work with all flags and targets
./sync.sh claude --group minimal --dry-run
./sync.sh --group backend --purge --refresh
```

## Script: `install.sh`

The installer manages which content items are selected for installation. It tracks installed items per-type in `~/.ai-management/installed/{type}.conf`.

Without arguments, it launches an **interactive menu** where you can browse groups or individual items.

### Installer flags

| Flag                              | Description                                           |
|-----------------------------------|-------------------------------------------------------|
| `--list`                          | List all available skills                             |
| `--list-groups`                   | List all groups                                       |
| `--installed`                     | Show installed items (all types)                      |
| **Default install**               |                                                       |
| `--install`                       | Install the default group (core agents, skills, etc.) |
| **Individual install**            |                                                       |
| `--install-agent <names>`         | Install agents (comma-separated)                      |
| `--install-skill <names>`         | Install skills (comma-separated)                      |
| `--install-rule <names>`          | Install rules (comma-separated)                       |
| `--install-workflow <names>`      | Install workflows (comma-separated)                   |
| `--install-hook <names>`          | Install hooks (comma-separated)                       |
| `--install-mcp <names>`           | Install MCP servers (comma-separated)                 |
| **Group install**                 |                                                       |
| `--install-group <name>`          | Install everything in a group                         |
| `--install-group-agents <name>`   | Install only agents from a group                      |
| `--install-group-skills <name>`   | Install only skills from a group                      |
| `--install-group-rules <name>`    | Install only rules from a group                       |
| `--install-group-workflows <name>`| Install only workflows from a group                   |
| `--install-group-hooks <name>`    | Install only hooks from a group                       |
| `--install-group-mcp <name>`      | Install only MCP servers from a group                 |
| **Install all**                   |                                                       |
| `--install-all`                   | Install everything (all types)                        |
| `--install-all-agents`            | Install all agents                                    |
| `--install-all-skills`            | Install all skills                                    |
| `--install-all-rules`             | Install all rules                                     |
| `--install-all-workflows`         | Install all workflows                                 |
| `--install-all-hooks`             | Install all hooks                                     |
| `--install-all-mcp`               | Install all MCP servers                               |
| **Uninstall**                     |                                                       |
| `--uninstall-agent <names>`       | Uninstall agents (comma-separated)                    |
| `--uninstall-skill <names>`       | Uninstall skills (comma-separated)                    |
| `--uninstall-rule <names>`        | Uninstall rules (comma-separated)                     |
| `--uninstall-workflow <names>`    | Uninstall workflows (comma-separated)                 |
| `--uninstall-hook <names>`        | Uninstall hooks (comma-separated)                     |
| `--uninstall-mcp <names>`         | Uninstall MCP servers (comma-separated)               |

### Installer examples

```bash
# Install defaults (core group)
./install.sh --install

# Install specific skills
./install.sh --install-skill code-review,debugging,testing

# Install all agents from the testing group
./install.sh --install-group-agents testing

# Install everything
./install.sh --install-all

# See what's installed
./install.sh --installed
```

## Common tasks

All examples use the script path `~/.ai-management/skills/AI-Management/sync.sh`. A shell alias is recommended for convenience.

### Sync to the current project (default)
```bash
~/.ai-management/skills/AI-Management/sync.sh
```

### Sync globally to all tools
```bash
~/.ai-management/skills/AI-Management/sync.sh -g
```

### Sync only to a specific tool
```bash
# Replace <target> with: copilot, claude, codex, or gemini
~/.ai-management/skills/AI-Management/sync.sh <target>
```

### Full reset — purge everything and re-sync from source
```bash
~/.ai-management/skills/AI-Management/sync.sh --purge --refresh
```

### Restore after a bad sync
```bash
# Interactive — see all backups and pick one
~/.ai-management/skills/AI-Management/sync.sh <target> --restore

# Quick — roll back to the last known good state
~/.ai-management/skills/AI-Management/sync.sh <target> --restore-latest
```

### Check what a sync would do before running it
```bash
~/.ai-management/skills/AI-Management/sync.sh --dry-run
```

## Build System (Universal Harness-Specific Builds)

The sync script includes a build step that generates harness-specific versions of **all content types** (agents, skills, rules, workflows, MCP, hooks). Source files are transformed into per-harness outputs in `~/.ai-management/{type}/{harness}/` before being symlinked to their final locations.

### Why?

Each coding tool has its own schema and requirements. Codex supports `model_reasoning_effort` and `sandbox_mode`, while Copilot and Claude only accept `name`, `description`, and `model`. MCP configs might differ per tool. The build system ensures each tool gets exactly what it needs from a single source of truth.

### Supported content types

| Type      | Source location                      | Build output                         | Notes                                    |
|-----------|--------------------------------------|--------------------------------------|------------------------------------------|
| Agents    | `~/.ai-management/agents/*.md`       | `agents/{harness}/*.md`              | Full schema-based field filtering        |
| Skills    | `~/.ai-management/skills/*/`         | `skills/{harness}/*/`                | Transforms .md files, copies others      |
| Rules     | `~/.ai-management/rules/*.md`        | `rules/{harness}/*.md`               | Schema-based filtering                   |
| Workflows | `~/.ai-management/workflows/*.md`    | `workflows/{harness}/*.md`           | Schema-based filtering                   |
| MCP       | `~/.ai-management/mcp/*.md`          | `mcp/{harness}/*.json`               | Frontmatter → JSON with env map support  |
| Hooks     | `~/.ai-management/hooks/*`           | `hooks/{harness}/*`                  | Comment-based frontmatter or passthrough |

### Source file format with overrides

Add harness-specific fields using the `{harness}_` prefix. Multiple harness names can be combined:

```yaml
---
name: Senior Developer
description: Premium implementation specialist
model: claude-opus-4.6

# Display-only fields (never exported)
color: green
emoji: 💎
vibe: Premium craftsperson

# Global override (applied to ALL harnesses, overrides base)
global_model: claude-sonnet-4-20250514

# Harness-specific overrides (highest priority for that harness)
codex_model: o3
codex_model_reasoning_effort: high
codex_sandbox_mode: full
copilot_description: Senior dev for Laravel and Livewire projects

# Multi-prefix: applies to BOTH codex and copilot (not claude/gemini)
codex_copilot_developer_instructions: Always use TypeScript
---
[agent instructions markdown]
```

### Field resolution priority

For each harness, fields resolve in this order:

1. `{harness}_{field}` — single harness, highest priority (e.g., `codex_model: o3`)
2. `{h1}_{h2}_{field}` — multi-prefix, applies to listed harnesses (e.g., `codex_copilot_model: gpt-4.1`)
3. `global_{field}` — applies to all harnesses (e.g., `global_model: claude-sonnet-4-20250514`)
4. `{field}` — base fallback (e.g., `model: claude-opus-4.6`)

Multi-prefix keys list harness names before the field name. The parser greedily matches known harness names from left to right.

### The `__omit__` sentinel

To intentionally suppress a field for a specific harness:

```yaml
codex_model: __omit__
```

This prevents the `model` field from appearing in the Codex output, even if a base or global value exists. Works at all priority levels including multi-prefix.

### Per-harness field schemas

Only fields in a harness's schema are included in its output:

| Harness | Allowed agent fields |
|---------|---------------|
| Copilot | `name`, `description`, `model`, `reasoning_effort` |
| Claude  | `name`, `description`, `model`, `effort` |
| Codex   | `name`, `description`, `model`, `model_reasoning_effort`, `sandbox_mode`, `mcp_servers`, `nickname_candidates`, `developer_instructions` |
| Gemini  | `name`, `description`, `model`, `thinkingLevel` |

Fields not in the schema (e.g., `color`, `emoji`, `vibe`) are silently dropped.

### Model defaults

The `defaults.conf` file (at `~/.ai-management/defaults.conf`) defines model presets per harness. Instead of hardcoding model names, use tier tokens:

```yaml
model: default          # Each harness uses its own default model
model: default-small    # Lightweight/fast model per harness
model: default-large    # Most capable model per harness
```

Defaults work with all prefix types:

```yaml
model: default                    # All harnesses use their own default
codex_model: default-large        # Codex uses large, others use base value
copilot_model: gpt-5.2-codex      # Exact model strings still work
```

When a tier is resolved, the harness-specific reasoning field is auto-injected (unless explicitly set in the agent file). Edit `defaults.conf` to change model mappings or reasoning levels.

### Build output locations

All types follow the pattern `~/.ai-management/{type}/{harness}/`:

```
~/.ai-management/agents/copilot/    → symlinked to ~/.copilot/agents/
~/.ai-management/agents/claude/     → symlinked to ~/.claude/agents/
~/.ai-management/skills/copilot/    → symlinked to ~/.copilot/skills/
~/.ai-management/mcp/codex/         → symlinked to ~/.codex/mcp/
```

## Important notes

- The source of truth is `~/.ai-management/{type}/*.md` (or `*/` for skills). Edits should be made there, then synced.
- The build step generates harness-specific versions in `~/.ai-management/{type}/{harness}/`. These are **generated artifacts** — do not edit them directly.
- For Copilot, Claude, and Codex, the script creates **symlinks** from `~/.{harness}/{type}/` to the built files.
- For Gemini, the script **concatenates** all built content into a single `~/.gemini/GEMINI.md` file.
- Always use `--dry-run` first if you are unsure what a command will do.
- The `--no-backup` flag is available but should only be used when you are confident in what you are doing. Backups are cheap and fast.
