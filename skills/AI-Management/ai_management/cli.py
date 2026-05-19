from __future__ import annotations

import sys
from typing import Sequence

from .groups import get_all_type, group_description, parse_group, template_description
from .install import install_all, install_group, install_template, install_type, show_installed, uninstall_type
from .sync import sync_command, sync_usage
from .tui import main_menu
from .utils import CLIError, CONTENT_TYPES, GROUPS_DIR, TEMPLATES_DIR, err


def install_usage() -> None:
    print("Usage: install.sh [options]")
    print("       install.sh sync [targets] [flags]")
    print()
    print("Interactive installer for AI Management content.")
    print()
    print("Options:")
    print("  --list                       List all available skills")
    print("  --list-groups                List all groups")
    print("  --list-templates             List all templates")
    print("  --installed                  Show installed items (all types)")
    print()
    print("  Default install:")
    print("  --install                    Install the default group (core agents, skills, etc.)")
    print()
    print("  Individual install:")
    print("  --install-agent <names>      Install agents (comma-separated)")
    print("  --install-skill <names>      Install skills (comma-separated)")
    print("  --install-rule <names>       Install rules (comma-separated)")
    print("  --install-workflow <names>   Install workflows (comma-separated)")
    print("  --install-hook <names>       Install hooks (comma-separated)")
    print("  --install-mcp <names>        Install MCP servers (comma-separated)")
    print()
    print("  Group install:")
    print("  --install-group <name>         Install everything in a group")
    print("  --install-group-agents <name>  Install only agents from a group")
    print("  --install-group-skills <name>  Install only skills from a group")
    print("  --install-group-rules <name>   Install only rules from a group")
    print("  --install-group-workflows <name>")
    print("  --install-group-hooks <name>")
    print("  --install-group-mcp <name>")
    print()
    print("  Template install:")
    print("  --template <name>            Install a template (groups + items) to current project")
    print("  --template <name> --global   Install a template globally")
    print()
    print("  Install all:")
    print("  --install-all                Install everything (all types)")
    print("  --install-all-agents         Install all agents")
    print("  --install-all-skills         Install all skills")
    print("  --install-all-rules          Install all rules")
    print("  --install-all-workflows      Install all workflows")
    print("  --install-all-hooks          Install all hooks")
    print("  --install-all-mcp            Install all MCP servers")
    print()
    print("  Uninstall:")
    print("  --uninstall-agent <names>    Uninstall agents (comma-separated)")
    print("  --uninstall-skill <names>    Uninstall skills (comma-separated)")
    print("  --uninstall-rule <names>     Uninstall rules (comma-separated)")
    print("  --uninstall-workflow <names> Uninstall workflows (comma-separated)")
    print("  --uninstall-hook <names>     Uninstall hooks (comma-separated)")
    print("  --uninstall-mcp <names>      Uninstall MCP servers (comma-separated)")
    print()
    print("  Sync / deploy:")
    print("  sync [targets] [flags]       Deploy installed/template/group content to harnesses")
    print("    targets: copilot codex claude gemini")
    print("    flags:   -g/--global, --dry-run, --refresh, --purge, --no-backup,")
    print("             --restore [file], --restore-latest, --pull, --group, --template")
    print()
    print("  -h, --help                   Show this help")
    print()
    print("Examples:")
    print("  install.sh --install                           # install defaults")
    print("  install.sh --install-skill AI-Management")
    print("  install.sh --install-group default")
    print("  install.sh --template example                  # apply template to project")
    print("  install.sh --install-all-skills")
    print("  install.sh sync --template example")
    print()
    print("Without arguments, launches the interactive menu.")


def list_groups() -> None:
    for file_path in sorted(GROUPS_DIR.glob("*.group")):
        skills = parse_group(file_path)
        if not skills:
            continue
        print(f"{file_path.stem:<25} ({len(skills)} skills)  {group_description(file_path)}")


def list_templates() -> None:
    for file_path in sorted(TEMPLATES_DIR.glob("*.template")):
        print(f"{file_path.stem:<25} {template_description(file_path)}")


def install_cli(argv: Sequence[str]) -> int:
    if not argv:
        main_menu(get_all_type("skills"))
        return 0
    first = argv[0]
    if first in {"-h", "--help"}:
        install_usage()
        return 0
    if first == "--list":
        print("\n".join(get_all_type("skills")))
        return 0
    if first == "--list-groups":
        list_groups()
        return 0
    if first == "--list-templates":
        list_templates()
        return 0
    if first == "--installed":
        show_installed()
        return 0
    if first == "--install":
        install_group("default")
        return 0
    if first in {"--install-agent", "--install-skill", "--install-rule", "--install-workflow", "--install-hook", "--install-mcp"}:
        if len(argv) < 2:
            raise CLIError("Provide names (comma-separated)")
        mapping = {
            "--install-agent": "agents",
            "--install-skill": "skills",
            "--install-rule": "rules",
            "--install-workflow": "workflows",
            "--install-hook": "hooks",
            "--install-mcp": "mcp",
        }
        install_type(mapping[first], [item.strip() for item in argv[1].split(",")])
        return 0
    if first == "--install-group":
        if len(argv) < 2:
            raise CLIError("Provide group name")
        install_group(argv[1])
        return 0
    if first.startswith("--install-group-"):
        if len(argv) < 2:
            raise CLIError("Provide group name")
        content_type = first[len("--install-group-"):]
        if content_type not in CONTENT_TYPES:
            raise CLIError(f"Unknown type: {content_type} (valid: {', '.join(CONTENT_TYPES)})")
        install_group(argv[1], only_type=content_type)
        return 0
    if first == "--install-all":
        install_all()
        return 0
    if first.startswith("--install-all-"):
        content_type = first[len("--install-all-"):]
        if content_type not in CONTENT_TYPES:
            raise CLIError(f"Unknown type: {content_type} (valid: {', '.join(CONTENT_TYPES)})")
        install_all(only_type=content_type)
        return 0
    if first in {"--uninstall-agent", "--uninstall-skill", "--uninstall-rule", "--uninstall-workflow", "--uninstall-hook", "--uninstall-mcp"}:
        if len(argv) < 2:
            raise CLIError("Provide names (comma-separated)")
        mapping = {
            "--uninstall-agent": "agents",
            "--uninstall-skill": "skills",
            "--uninstall-rule": "rules",
            "--uninstall-workflow": "workflows",
            "--uninstall-hook": "hooks",
            "--uninstall-mcp": "mcp",
        }
        uninstall_type(mapping[first], [item.strip() for item in argv[1].split(",")])
        return 0
    if first == "--template":
        if len(argv) < 2:
            raise CLIError("Provide template name")
        install_template(argv[1], any(arg in {"--global", "-g"} for arg in argv[2:]))
        return 0
    raise CLIError(f"Unknown option: {first}")


def main(argv: Sequence[str] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv and argv[0] == "sync":
            return sync_command(argv[1:])
        return install_cli(argv)
    except KeyboardInterrupt:
        print()
        err("Cancelled")
        return 130
    except CLIError as exc:
        err(str(exc))
        if argv and argv[0] == "sync":
            sync_usage()
        else:
            install_usage()
        return 1
