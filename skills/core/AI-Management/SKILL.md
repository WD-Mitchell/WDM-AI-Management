---
name: AI-Management
description: Use the WDM AI Management CLI and web UI to manage shared agents, skills, MCP servers, rules, workflows, hooks, templates, and harness configs.
---

# AI Management

Use the `wdm` CLI to manage AI assistant configuration from the shared source of truth in `~/.wdm`.

## When To Use

Use this skill when the user wants to:

- Create, edit, import, duplicate, or preview agents, skills, MCP servers, rules, workflows, hooks, templates, or harness configs.
- Install or remove shared items from the global set or a project.
- Sync installed items into harnesses such as Codex, Claude, Copilot, Gemini, Cursor, or other configured harnesses.
- Launch the local AI Management web UI.
- Inspect or adjust the `~/.wdm` source files.

## Primary Commands

```bash
wdm ai
```

Launches the local web UI and opens it in the default browser.

```bash
wdm ai --reload
```

Launches the web UI with auto-reload while editing the app/source files.

```bash
wdm ai sync
```

Builds and syncs installed content into the current project for enabled harnesses.

```bash
wdm ai sync -g
wdm ai sync --global
```

Builds and syncs installed content globally into the user's home directory.

```bash
wdm ai bootstrap
```

Copies bundled source files into `~/.wdm`, installs this AI Management skill, and syncs it into enabled global harness skill locations.

## Common Workflows

### Launch The UI

Run:

```bash
wdm ai
```

Use the UI for day-to-day management. Prefer the form view for normal editing and file view when exact raw file control is needed.

### Sync A Project

From the target project directory:

```bash
wdm ai sync
```

Use `--dry-run` first when checking what will change:

```bash
wdm ai sync --dry-run
```

### Sync Globally

```bash
wdm ai sync -g
```

This deploys globally installed items into global harness locations.

### Install Content

```bash
wdm ai --installed
wdm ai --install-group default
wdm ai --install-agent api-designer,code-reviewer
wdm ai --install-skill AI-Management
```

Then sync:

```bash
wdm ai sync
```

### Import Or Duplicate Items

Use the web UI:

```bash
wdm ai
```

The list pages include Create and Import actions. Preview an item to duplicate it.

## Source Layout

The source of truth is `~/.wdm`:

| Type | Location |
| --- | --- |
| Agents | `~/.wdm/agents/core/*.md` |
| Skills | `~/.wdm/skills/core/*/SKILL.md` |
| MCP | `~/.wdm/mcp/core/*` |
| Rules | `~/.wdm/rules/core/*.md` |
| Workflows | `~/.wdm/workflows/core/*.md` |
| Hooks | `~/.wdm/hooks/core/*` |
| Groups | `~/.wdm/groups/*.group` |
| Templates | `~/.wdm/templates/core/*.template` |
| Harnesses | `~/.wdm/harnesses/core/*.json` |

## Notes

- Use `wdm ai sync --help` for sync flags.
- Use `wdm ai --help` for install/list commands.
- Prefer editing through `wdm ai` unless the user explicitly asks for direct file changes.
- Do not hand-edit generated harness output when the source item exists in `~/.wdm`; edit the source and sync again.
