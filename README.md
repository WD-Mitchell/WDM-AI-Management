# AI Management

A framework for managing AI agent definitions, skills, rules, workflows, hooks, and MCP configs from a central source of truth — deployed to all your coding tools (GitHub Copilot, Claude Code, Codex, Gemini CLI).

## What is this?

This repository provides the **infrastructure** for managing AI content across multiple coding assistants. It includes:

- **`sync.sh`** — Builds harness-specific versions of your content and distributes them via symlinks
- **`install.sh`** — Interactive installer for selecting which content to activate
- **`build.py`** — Transforms universal source files into per-harness outputs
- **Groups** — Named collections for installing related content together

You populate the content directories (`agents/`, `skills/`, `rules/`, etc.) with your own definitions.

## Quick Start

### 1. Clone this repo

```bash
git clone <your-repo-url> && cd ai-management
```

### 2. Add your content

Place your content in the appropriate directories:

```
agents/          # Agent definitions (*.md with YAML frontmatter)
skills/          # Skill directories (each with SKILL.md)
rules/           # Rule definitions (*.md)
workflows/       # Workflow definitions (*.md)
hooks/           # Hook scripts
mcp/             # MCP server configs (*.md)
groups/          # Group files (*.group)
```

### 3. Install and sync

```bash
# Install the default group
./install.sh --install

# Sync to your current project
./skills/AI-Management/sync.sh

# Or sync globally
./skills/AI-Management/sync.sh -g
```

## Configuration

Set these environment variables to configure the system:

| Variable               | Description                                          | Default                 |
|------------------------|------------------------------------------------------|-------------------------|
| `AI_MANAGEMENT_REPO`   | GitHub `org/repo` for remote pull                    | *(none — must be set)*  |
| `AI_MANAGEMENT_BRANCH` | Branch to pull from                                  | `main`                  |
| `AI_MANAGEMENT_HOME`   | Override the `~/.ai-management` install location     | `$HOME/.ai-management`  |

## Directory Structure

```
├── agents/              # Agent definitions
├── skills/
│   └── AI-Management/   # This management skill (sync.sh, build.py, SKILL.md)
├── rules/               # Rule definitions
├── workflows/           # Workflow definitions
├── hooks/               # Hook scripts (e.g., post-merge)
├── mcp/                 # MCP server configurations
├── groups/              # Group files for batch installation
├── defaults.conf        # Model tier definitions per harness
├── install.sh           # Interactive content installer
└── .gitignore           # Excludes build artifacts
```

## Supported Harnesses

| Harness | Agent format | Deployment method |
|---------|-------------|-------------------|
| GitHub Copilot | Markdown + limited frontmatter | Symlinks to `.copilot/` |
| Claude Code | Markdown + limited frontmatter | Symlinks to `.claude/` |
| Codex | Markdown + extended frontmatter | Symlinks to `.codex/` |
| Gemini CLI | Concatenated markdown | Single `.gemini/GEMINI.md` |

## Documentation

See [`skills/AI-Management/SKILL.md`](skills/AI-Management/SKILL.md) for comprehensive documentation including:

- All sync.sh flags and combinations
- Group file format
- Build system details (field resolution, overrides, schemas)
- Backup and restore procedures
- Model defaults and tier tokens

## License

MIT
