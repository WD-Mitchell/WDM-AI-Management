from __future__ import annotations

import sys
from typing import Sequence

from .groups import get_all_type, group_description, parse_group
from .install import install_all, install_group, install_type, show_installed, uninstall_type
from .sync import sync_command, sync_usage
from .tui import main_menu
from .utils import CLIError, CONTENT_TYPES, GROUPS_DIR, HARNESS_DEFINITIONS, TEMPLATES_DIR, err


def install_usage() -> None:
    print("Usage: wdm-ai [options]")
    print("       wdm-ai sync [targets] [flags]")
    print()
    print("Local web GUI and installer for AI Management content.")
    print()
    print("Options:")
    print("  --list                       List all available skills")
    print("  --list-groups                List all groups")
    print("  --list-templates             List content editor templates")
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
    print("  sync [targets] [flags]       Deploy installed and group content to harnesses")
    print(f"    default targets: {' '.join(sorted(HARNESS_DEFINITIONS))}")
    print("    flags:   -g/--global, --dry-run, --refresh, --purge, --no-backup,")
    print("             --restore [file], --restore-latest, --pull, --group")
    print()
    print("  Web UI:")
    print("  web                          Run the local web GUI")
    print("    flags:   --host <host>, --port <port>, --open, --reload")
    print("  wdm-ai                       Run the local web GUI and open it in the browser")
    print("    flags:   --host <host>, --port <port>, --no-open, --reload")
    print("  bootstrap                    Copy bundled files to ~/.wdm and install this skill globally")
    print("    flags:   --force, --no-sync, --quiet")
    print()
    print("  -h, --help                   Show this help")
    print()
    print("Examples:")
    print("  wdm-ai --install                           # install defaults")
    print("  wdm-ai --install-skill AI-Management")
    print("  wdm-ai --install-group default")
    print("  wdm-ai --install-all-skills")
    print("  wdm-ai --reload")
    print("  wdm-ai bootstrap")
    print("  wdm-ai --no-open")
    print()
    print("Without arguments, wdm-ai launches the local web GUI.")


def list_groups() -> None:
    for file_path in sorted(GROUPS_DIR.glob("*.group")):
        skills = parse_group(file_path)
        if not skills:
            continue
        print(f"{file_path.stem:<25} ({len(skills)} skills)  {group_description(file_path)}")


def list_templates() -> None:
    for file_path in sorted((TEMPLATES_DIR / "core").glob("*.template")):
        print(f"{file_path.stem:<25} {file_path}")


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
        raise CLIError("Repo templates have been removed. Use --install-group or sync --group for repo sets.")
    raise CLIError(f"Unknown option: {first}")


def web_cli(argv: Sequence[str], open_by_default: bool = False) -> int:
    host = "127.0.0.1"
    port = 8765
    open_browser = open_by_default
    reload = False
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--host":
            i += 1
            if i >= len(argv):
                raise CLIError("Provide host value")
            host = argv[i]
        elif arg == "--port":
            i += 1
            if i >= len(argv):
                raise CLIError("Provide port value")
            try:
                port = int(argv[i])
            except ValueError as exc:
                raise CLIError("Port must be a number") from exc
        elif arg == "--open":
            open_browser = True
        elif arg == "--no-open":
            open_browser = False
        elif arg == "--reload":
            reload = True
        elif arg in {"-h", "--help"}:
            print("Usage: wdm-ai [--host 127.0.0.1] [--port 8765] [--no-open] [--reload]")
            return 0
        else:
            raise CLIError(f"Unknown web option: {arg}")
        i += 1
    from .web import run_web

    return run_web(host=host, port=port, open_browser=open_browser, reload=reload)


def bootstrap_cli(argv: Sequence[str]) -> int:
    force = False
    sync_skills = True
    quiet = False
    for arg in argv:
        if arg == "--force":
            force = True
        elif arg == "--no-sync":
            sync_skills = False
        elif arg == "--quiet":
            quiet = True
        elif arg in {"-h", "--help"}:
            print("Usage: wdm-ai bootstrap [--force] [--no-sync] [--quiet]")
            return 0
        else:
            raise CLIError(f"Unknown bootstrap option: {arg}")
    from .bootstrap import bootstrap

    bootstrap(force=force, sync_skills=sync_skills, quiet=quiet)
    return 0


def ai_cli(argv: Sequence[str]) -> int:
    argv = list(argv)
    if argv and argv[0] in {"-h", "--help"}:
        install_usage()
        return 0
    if argv and argv[0] == "sync":
        return sync_command(argv[1:])
    if argv and argv[0] == "bootstrap":
        return bootstrap_cli(argv[1:])
    if argv and argv[0] == "web":
        return web_cli(argv[1:], open_by_default=True)
    if not argv or argv[0] in {"--host", "--port", "--open", "--no-open", "--reload"}:
        from .bootstrap import bootstrap

        bootstrap(quiet=True)
        return web_cli(argv, open_by_default=True)
    return install_cli(argv)


def main(argv: Sequence[str] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if not argv or argv[0] in {"-h", "--help"}:
            install_usage()
            return 0
        if argv and argv[0] == "ai":
            return ai_cli(argv[1:])
        raise CLIError("Use `wdm-ai ...` for AI Management commands.")
    except KeyboardInterrupt:
        print()
        err("Cancelled")
        return 130
    except CLIError as exc:
        err(str(exc))
        if len(argv) > 1 and argv[0] == "ai" and argv[1] == "sync":
            sync_usage()
        else:
            install_usage()
        return 1
