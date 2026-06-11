# CLI Flags Reference

All available flags for `install.sh`.

---

## General

| Flag | Description |
|------|-------------|
| `-h`, `--help` | Show usage information and exit |
| *(no arguments)* | Launch the interactive TUI menu |

---

## Listing

| Flag | Description |
|------|-------------|
| `--list` | List all available skills |
| `--list-groups` | List all available groups (from `groups/*.group`) |
| `--list-templates` | List all available templates (from `templates/*.template`) |
| `--installed` | Show all currently installed items across all content types |

---

## Individual Install

Install specific items by name. Multiple items can be comma-separated.

| Flag | Description |
|------|-------------|
| `--install-agent <names>` | Install one or more agents |
| `--install-skill <names>` | Install one or more skills |
| `--install-rule <names>` | Install one or more rules |
| `--install-workflow <names>` | Install one or more workflows |
| `--install-hook <names>` | Install one or more hooks |
| `--install-mcp <names>` | Install one or more MCP server configs |

**Example:** `./install.sh --install-agent senior-developer,code-reviewer`

---

## Group Install

Groups are predefined sets of items (defined in `groups/*.group`).

| Flag | Description |
|------|-------------|
| `--install-group <name>` | Install all items defined in a group |
| `--install-group-agents <name>` | Install only the agents section of a group |
| `--install-group-skills <name>` | Install only the skills section of a group |
| `--install-group-rules <name>` | Install only the rules section of a group |
| `--install-group-workflows <name>` | Install only the workflows section of a group |
| `--install-group-hooks <name>` | Install only the hooks section of a group |
| `--install-group-mcp <name>` | Install only the MCP section of a group |

**Example:** `./install.sh --install-group core-development`

---

## Default Install

| Flag | Description |
|------|-------------|
| `--install` | Install the default group (`groups/default.group`) |

---

## Install All

| Flag | Description |
|------|-------------|
| `--install-all` | Install everything across all content types |
| `--install-all-agents` | Install all available agents |
| `--install-all-skills` | Install all available skills |
| `--install-all-rules` | Install all available rules |
| `--install-all-workflows` | Install all available workflows |
| `--install-all-hooks` | Install all available hooks |
| `--install-all-mcp` | Install all available MCP server configs |

---

## Template Install

Templates combine groups and individual items into a reusable configuration (defined in `templates/*.template`).

| Flag | Description |
|------|-------------|
| `--template <name>` | Install a template to the current project |
| `--template <name> --global` | Install a template globally |

When applied to a project, a `.ai-management` file is created so future syncs auto-apply the same template.

**Example:** `./install.sh --template web-development`

---

## Uninstall

Remove specific items from the installed configuration. Multiple items can be comma-separated.

| Flag | Description |
|------|-------------|
| `--uninstall-agent <names>` | Uninstall one or more agents |
| `--uninstall-skill <names>` | Uninstall one or more skills |
| `--uninstall-rule <names>` | Uninstall one or more rules |
| `--uninstall-workflow <names>` | Uninstall one or more workflows |
| `--uninstall-hook <names>` | Uninstall one or more hooks |
| `--uninstall-mcp <names>` | Uninstall one or more MCP server configs |

**Example:** `./install.sh --uninstall-skill debugging,code-review`

---

## Sync / Deploy

The `sync` subcommand builds and deploys content to harness-specific locations.

```
./install.sh sync [targets] [flags]
```

### Targets

Specify which harnesses to sync to. If omitted, syncs to all detected harnesses.

| Target | Deploy method | Location |
|--------|--------------|----------|
| `copilot` | Symlinks + generated | `.github/agents/*.agent.md`, `.github/skills/`, `.github/copilot-instructions.md` (project); `~/.copilot/{agents,skills,instructions,mcp-config.json}` (global) |
| `claude` | Symlinks + generated | `.claude/{agents,skills,rules,commands,hooks}/`; `.mcp.json` at repo root (project only) |
| `codex` | Symlinks + merged TOML | `.codex/agents/*.toml`, `~/.agents/skills/`; merged into `.codex/config.toml` (`[mcp_servers.*]`) |
| `gemini` | Native subagents + merged JSON | `.gemini/agents/`, `.gemini/skills/`; merged into `.gemini/settings.json` (`mcpServers`) |

### Sync Flags

| Flag | Description |
|------|-------------|
| `-g`, `--global` | Sync to `~/` (globally available) instead of the current project |
| `--dry-run` | Show what would happen without making any changes |
| `--refresh` | Remove existing managed symlinks before re-syncing (clean slate) |
| `--purge` | Remove all managed files from targets without re-syncing |
| `--no-backup` | Skip the automatic backup before making changes |
| `--restore [file]` | Restore from a backup — interactive picker or specify a `.zip` file |
| `--restore-latest` | Restore from the most recent backup automatically |
| `--pull` | Download the latest content from GitHub before syncing |
| `--group <name>` | Sync only items defined in the named group (can be repeated) |
| `--template <name>` | Sync items defined in a template |
| `-h`, `--help` | Show sync-specific help |

### Sync Examples

```bash
# Sync to current project (all harnesses)
./install.sh sync

# Sync globally
./install.sh sync -g

# Sync only to Copilot and Claude with dry-run
./install.sh sync copilot claude --dry-run

# Pull latest from remote, then sync
./install.sh sync --pull

# Clean refresh of a specific group
./install.sh sync --group backend --refresh

# Apply a template to the project
./install.sh sync --template web-development

# Purge all managed files from Codex
./install.sh sync codex --purge

# Restore from most recent backup
./install.sh sync --restore-latest
```

---

## Environment Variables

These are not flags but affect script behavior:

| Variable | Description | Default |
|----------|-------------|---------|
| `AI_MANAGEMENT_HOME` | Override the source-of-truth directory | `~/.wdm` |
| `AI_MANAGEMENT_REPO` | GitHub `org/repo` for `--pull` | *(must be set for pull)* |
| `AI_MANAGEMENT_BRANCH` | Remote branch to pull from | `main` |
