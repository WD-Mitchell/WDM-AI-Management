from __future__ import annotations

import json
import os
import time
import zipfile
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from .build import build_all
from .groups import apply_group_sections, apply_template_sections, group_path, resolve_selection_paths, template_path
from .install import load_installed_type
from .pull import pull_from_github
from .utils import (
    ALL_HARNESSES,
    BACKUP_DIR,
    CONTENT_TYPES,
    CONTENT_ROOT,
    SYNC_TEMPLATE_FILE,
    CLIError,
    SyncOptions,
    ensure_dir,
    info,
    log,
    remove_path,
    warn,
)


def sync_usage() -> None:
    print("Usage: install.sh sync [targets] [flags]")
    print()
    print("Targets: copilot codex claude gemini")
    print()
    print("Flags:")
    print("  -g, --global             Sync globally (~/) instead of the current project")
    print("      --dry-run            Show what would happen")
    print("      --refresh            Remove synced symlinks before re-syncing")
    print("      --purge              Remove all managed files from targets (no re-sync)")
    print("      --no-backup          Skip automatic backup before changes")
    print("      --restore [file.zip] Restore interactively or from a specific backup file")
    print("      --restore-latest     Restore the most recent backup")
    print("      --pull               Download latest content from GitHub")
    print("      --group <name>       Sync only items in the named group")
    print("      --template <name>    Sync items defined in a template")
    print("  -h, --help               Show this help")
    print()
    print("Examples:")
    print("  install.sh sync")
    print("  install.sh sync -g")
    print("  install.sh sync copilot codex --dry-run")
    print("  install.sh sync --group default --refresh")
    print("  install.sh sync --template example")


def parse_sync_args(argv: Sequence[str]) -> SyncOptions:
    options = SyncOptions()
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--dry-run":
            options.dry_run = True
        elif arg == "--refresh":
            options.refresh = True
        elif arg == "--purge":
            options.purge = True
        elif arg == "--no-backup":
            options.backup = False
        elif arg == "--pull":
            options.pull = True
        elif arg in {"-g", "--global"}:
            options.global_mode = True
        elif arg == "--group":
            if index + 1 >= len(argv) or argv[index + 1].startswith("--"):
                raise CLIError("Error: --group requires a name")
            options.selected_groups.append(argv[index + 1])
            index += 1
        elif arg == "--template":
            if index + 1 >= len(argv) or argv[index + 1].startswith("--"):
                raise CLIError("Error: --template requires a name")
            options.template = argv[index + 1]
            index += 1
        elif arg == "--restore-latest":
            options.restore_latest = True
        elif arg == "--restore":
            options.restore = True
            if index + 1 < len(argv):
                nxt = argv[index + 1]
                if not nxt.startswith("--") and nxt not in ALL_HARNESSES:
                    options.restore_file = nxt
                    index += 1
        elif arg in ALL_HARNESSES:
            options.targets.append(arg)
        elif arg in {"-h", "--help"}:
            sync_usage()
            raise SystemExit(0)
        else:
            raise CLIError(f"Unknown sync argument: {arg}")
        index += 1
    if not options.targets:
        options.targets = list(ALL_HARNESSES)
    return options


def sync_init_runtime(options: SyncOptions) -> None:
    options.target_root = Path.home() if options.global_mode else Path.cwd()
    options.copilot_agents_dir = options.target_root / ".github" / "copilot" / "agents"
    options.copilot_skills_dir = options.target_root / ".copilot" / "skills"
    options.copilot_rules_dir = options.target_root / ".copilot" / "instructions"
    options.copilot_workflows_dir = options.target_root / ".copilot" / "workflows"
    options.copilot_hooks_dir = options.target_root / ".copilot" / "hooks"
    options.codex_dir = options.target_root / ".codex"
    options.codex_agents_dir = options.codex_dir / "agents"
    options.claude_dir = options.target_root / ".claude"
    options.gemini_dir = options.target_root / ".gemini"
    mode = "global" if options.global_mode else "project"
    info(f"Mode: \033[1m{mode}\033[0m (target: {options.target_root})")


def managed_paths_for(options: SyncOptions, target: str) -> Dict[str, Path]:
    if target == "copilot":
        return {
            "agents": options.copilot_agents_dir,
            "skills": options.copilot_skills_dir,
            "rules": options.copilot_rules_dir,
            "workflows": options.copilot_workflows_dir,
            "hooks": options.copilot_hooks_dir,
            "mcp": options.target_root / ".copilot" / "mcp.json",
        }
    if target == "codex":
        return {
            "agents": options.codex_agents_dir,
            "skills": options.codex_dir / "skills",
            "rules": options.codex_dir / "instructions",
            "workflows": options.codex_dir / "workflows",
            "hooks": options.codex_dir / "hooks",
            "mcp": options.codex_dir / "mcp-servers.json",
        }
    if target == "claude":
        return {
            "agents": options.claude_dir / "agents",
            "skills": options.claude_dir / "skills",
            "rules": options.claude_dir / "rules",
            "workflows": options.claude_dir / "workflows",
            "hooks": options.claude_dir / "hooks",
            "mcp": options.claude_dir / "mcp.json",
        }
    return {
        "gemini": options.gemini_dir / "GEMINI.md",
        "mcp": options.gemini_dir / "mcp-servers.json",
    }


def sync_resolve_selection(options: SyncOptions) -> None:
    raw = {content_type: [] for content_type in CONTENT_TYPES}
    group_names = list(options.selected_groups)
    explicit = bool(options.template or options.selected_groups)
    if options.template:
        tpl = template_path(options.template)
        if not tpl.exists():
            raise CLIError(f"Template file not found: {tpl}")
        info(f"Applying template: \033[1m{options.template}\033[0m")
        apply_template_sections(tpl, raw, group_names)
        if not options.global_mode and not options.dry_run:
            (options.target_root / SYNC_TEMPLATE_FILE).write_text(options.template + "\n", encoding="utf-8")
            log(f"Saved template reference → {options.target_root / SYNC_TEMPLATE_FILE}")
    elif not group_names and not options.global_mode:
        saved = options.target_root / SYNC_TEMPLATE_FILE
        if saved.exists():
            template_name = saved.read_text(encoding="utf-8").splitlines()[0].strip() if saved.read_text(encoding="utf-8").splitlines() else ""
            if template_name:
                tpl = template_path(template_name)
                if tpl.exists():
                    info(f"Using project template: \033[1m{template_name}\033[0m")
                    apply_template_sections(tpl, raw, group_names)
                    explicit = True
    for group_name in list(dict.fromkeys(group_names)):
        grp = group_path(group_name)
        if not grp.exists():
            raise CLIError(f"Group file not found: {grp}")
        info(f"Loading group: \033[1m{group_name}\033[0m")
        apply_group_sections(grp, raw)
    if not explicit and not group_names:
        for content_type in CONTENT_TYPES:
            raw[content_type].extend(load_installed_type(content_type))
    for content_type in CONTENT_TYPES:
        resolved = []
        for path in resolve_selection_paths(content_type, raw[content_type]):
            if path.exists() and path not in resolved:
                resolved.append(path)
            elif not path.exists():
                warn(f"Selection not found: {content_type}/{path.name}")
        options.resolved[content_type] = resolved
    info(
        "Resolved: " + ", ".join(f"{len(options.resolved[content_type])} {content_type}" for content_type in CONTENT_TYPES)
    )


def collect_backup_entries(path: Path, target_root: Path) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []
    if path.is_dir():
        for child in sorted(path.iterdir()):
            if child.name == "backups":
                continue
            if child.is_symlink():
                entries.append({"kind": "symlink", "relative_path": child.relative_to(target_root).as_posix(), "target": os.readlink(str(child))})
            elif child.is_file():
                entries.append({"kind": "file", "relative_path": child.relative_to(target_root).as_posix()})
    elif path.exists() or path.is_symlink():
        if path.is_symlink():
            entries.append({"kind": "symlink", "relative_path": path.relative_to(target_root).as_posix(), "target": os.readlink(str(path))})
        elif path.is_file():
            entries.append({"kind": "file", "relative_path": path.relative_to(target_root).as_posix()})
    return entries


def backup_path(target: str, type_name: str, path: Path, target_root: Path, dry_run: bool = False) -> None:
    entries = collect_backup_entries(path, target_root)
    if not entries:
        return
    ensure_dir(BACKUP_DIR)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    zip_path = BACKUP_DIR / f"{target}_{type_name}_{timestamp}.zip"
    if dry_run:
        info(f"[dry-run] Would back up {len(entries)} {type_name} entries → {zip_path.name}")
        return
    manifest = {"target": target, "type": type_name, "created_at": timestamp, "entries": entries}
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for entry in entries:
            if entry["kind"] == "file":
                archive.write(target_root / entry["relative_path"], arcname=entry["relative_path"])
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
    log(f"{target}: backed up {len(entries)} {type_name} entries → {zip_path.name}")


def parse_backup_name(path: Path) -> Tuple[str, str, str]:
    name = path.stem
    parts = name.split("_", 2)
    if len(parts) != 3:
        return "", "", ""
    return parts[0], parts[1], parts[2]


def backups_for_targets(targets: Sequence[str]) -> List[Path]:
    if not BACKUP_DIR.exists():
        return []
    selected = set(targets)
    matches = []
    for child in sorted(BACKUP_DIR.glob("*.zip"), key=lambda item: item.stat().st_mtime, reverse=True):
        target, _, _ = parse_backup_name(child)
        if target in selected:
            matches.append(child)
    return matches


def restore_backup(zip_path: Path, target_root: Path, dry_run: bool = False) -> None:
    if not zip_path.exists():
        raise CLIError(f"Backup not found: {zip_path}")
    with zipfile.ZipFile(zip_path) as archive:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8")) if "manifest.json" in archive.namelist() else {"entries": []}
        entries = manifest.get("entries", [])
        if dry_run:
            info(f"[dry-run] Would restore {len(entries)} entries from {zip_path.name} → {target_root}")
            return
        for entry in entries:
            dest = target_root / entry["relative_path"]
            ensure_dir(dest.parent)
            remove_path(dest)
            if entry["kind"] == "file":
                with archive.open(entry["relative_path"]) as src, open(dest, "wb") as dst:
                    dst.write(src.read())
            elif entry["kind"] == "symlink":
                os.symlink(entry["target"], str(dest))
    log(f"Restored {zip_path.name} → {target_root}")


def restore_targets(options: SyncOptions) -> None:
    if options.restore_file:
        path = Path(options.restore_file)
        if not path.exists():
            path = BACKUP_DIR / options.restore_file
        restore_backup(path, options.target_root, options.dry_run)
        return
    backups = backups_for_targets(options.targets)
    if not backups:
        warn("No backups found")
        return
    if options.restore_latest:
        latest = {}
        for path in backups:
            target, type_name, _ = parse_backup_name(path)
            latest.setdefault((target, type_name), path)
        for path in latest.values():
            restore_backup(path, options.target_root, options.dry_run)
        return
    print()
    print("\033[1m── Available backups ──\033[0m")
    for index, path in enumerate(backups, start=1):
        target, type_name, _ = parse_backup_name(path)
        print(f"  {index:2d}) {path.name:<50} [{target}/{type_name}]")
    print()
    choice = input("  Enter number to restore (or 'q' to skip): ").strip()
    if not choice or choice.lower() == "q":
        info("Restore skipped")
        return
    if not choice.isdigit() or not (1 <= int(choice) <= len(backups)):
        raise CLIError("Invalid selection")
    restore_backup(backups[int(choice) - 1], options.target_root, options.dry_run)


def make_link(src: Path, dest: Path, dry_run: bool = False) -> None:
    if dry_run:
        info(f"[dry-run] symlink: {src} → {dest}")
        return
    ensure_dir(dest.parent)
    if dest.is_dir() and not dest.is_symlink():
        warn(f"Skipping existing directory: {dest}")
        return
    remove_path(dest)
    os.symlink(str(src), str(dest))


def purge_symlinks_in(directory: Path) -> None:
    if not directory.exists() or not directory.is_dir():
        return
    for child in directory.iterdir():
        if child.name == "backups":
            continue
        if child.is_symlink():
            child.unlink()


def sync_items_to(target_dir: Path, harness: str, content_type: str, resolved_paths: Sequence[Path], dry_run: bool = False, refresh: bool = False, label: str = "") -> None:
    if not resolved_paths:
        return
    build_dir = CONTENT_ROOT / content_type / harness
    if not build_dir.exists():
        return
    if refresh:
        purge_symlinks_in(target_dir)
    count = 0
    for source_path in resolved_paths:
        if content_type == "skills":
            built_path = build_dir / source_path.name
        else:
            built_path = build_dir / source_path.name
        if not built_path.exists():
            continue
        make_link(built_path, target_dir / built_path.name, dry_run=dry_run)
        count += 1
    if count:
        log(f"{label}: symlinked {count} {content_type} → {target_dir}/")


def sync_mcp_to(harness: str, label: str, target_file: Path, resolved_paths: Sequence[Path], dry_run: bool = False) -> None:
    if not resolved_paths:
        return
    build_dir = CONTENT_ROOT / "mcp" / harness
    if not build_dir.exists():
        return
    servers = {}
    for source_path in resolved_paths:
        built_name = source_path.name if source_path.suffix == ".json" else f"{source_path.stem}.json"
        built_path = build_dir / built_name
        if not built_path.exists():
            continue
        servers[built_path.stem] = json.loads(built_path.read_text(encoding="utf-8"))
    if not servers:
        return
    if dry_run:
        info(f"[dry-run] Would write {len(servers)} MCP servers → {target_file}")
        return
    ensure_dir(target_file.parent)
    target_file.write_text(json.dumps({"mcpServers": servers}, indent=2) + "\n", encoding="utf-8")
    log(f"{label}: wrote {len(servers)} MCP servers → {target_file}")


def sync_copilot(options: SyncOptions) -> None:
    print()
    print("\033[1m── Syncing to GitHub Copilot CLI ──\033[0m")
    if options.refresh:
        purge_symlinks_in(options.copilot_agents_dir)
    build_dir = CONTENT_ROOT / "agents" / "copilot"
    count = 0
    for agent_file in options.resolved["agents"]:
        built_file = build_dir / agent_file.name
        if not built_file.exists():
            continue
        make_link(built_file, options.copilot_agents_dir / agent_file.name, options.dry_run)
        count += 1
    log(f"Copilot: symlinked {count} agent files → {options.copilot_agents_dir}/")
    sync_items_to(options.copilot_skills_dir, "copilot", "skills", options.resolved["skills"], options.dry_run, options.refresh, "Copilot")
    sync_items_to(options.copilot_rules_dir, "copilot", "rules", options.resolved["rules"], options.dry_run, options.refresh, "Copilot")
    sync_items_to(options.copilot_workflows_dir, "copilot", "workflows", options.resolved["workflows"], options.dry_run, options.refresh, "Copilot")
    sync_items_to(options.copilot_hooks_dir, "copilot", "hooks", options.resolved["hooks"], options.dry_run, options.refresh, "Copilot")
    sync_mcp_to("copilot", "Copilot", options.target_root / ".copilot" / "mcp.json", options.resolved["mcp"], options.dry_run)


def sync_codex(options: SyncOptions) -> None:
    print()
    print("\033[1m── Syncing to OpenAI Codex CLI ──\033[0m")
    if options.refresh:
        purge_symlinks_in(options.codex_agents_dir)
    build_dir = CONTENT_ROOT / "agents" / "codex"
    count = 0
    for agent_file in options.resolved["agents"]:
        built_file = build_dir / agent_file.name
        if not built_file.exists():
            continue
        make_link(built_file, options.codex_agents_dir / agent_file.name, options.dry_run)
        count += 1
    log(f"Codex: symlinked {count} agent files → {options.codex_agents_dir}/")
    sync_items_to(options.codex_dir / "skills", "codex", "skills", options.resolved["skills"], options.dry_run, options.refresh, "Codex")
    sync_items_to(options.codex_dir / "instructions", "codex", "rules", options.resolved["rules"], options.dry_run, options.refresh, "Codex")
    sync_items_to(options.codex_dir / "workflows", "codex", "workflows", options.resolved["workflows"], options.dry_run, options.refresh, "Codex")
    sync_items_to(options.codex_dir / "hooks", "codex", "hooks", options.resolved["hooks"], options.dry_run, options.refresh, "Codex")
    sync_mcp_to("codex", "Codex", options.codex_dir / "mcp-servers.json", options.resolved["mcp"], options.dry_run)


def sync_claude(options: SyncOptions) -> None:
    print()
    print("\033[1m── Syncing to Claude Code ──\033[0m")
    agents_dir = options.claude_dir / "agents"
    if options.refresh:
        purge_symlinks_in(agents_dir)
    build_dir = CONTENT_ROOT / "agents" / "claude"
    count = 0
    for agent_file in options.resolved["agents"]:
        built_file = build_dir / agent_file.name
        if not built_file.exists():
            continue
        make_link(built_file, agents_dir / agent_file.name, options.dry_run)
        count += 1
    log(f"Claude: symlinked {count} agent files → {agents_dir}/")
    sync_items_to(options.claude_dir / "skills", "claude", "skills", options.resolved["skills"], options.dry_run, options.refresh, "Claude")
    sync_items_to(options.claude_dir / "rules", "claude", "rules", options.resolved["rules"], options.dry_run, options.refresh, "Claude")
    sync_items_to(options.claude_dir / "workflows", "claude", "workflows", options.resolved["workflows"], options.dry_run, options.refresh, "Claude")
    sync_items_to(options.claude_dir / "hooks", "claude", "hooks", options.resolved["hooks"], options.dry_run, options.refresh, "Claude")
    sync_mcp_to("claude", "Claude", options.claude_dir / "mcp.json", options.resolved["mcp"], options.dry_run)


def sync_gemini(options: SyncOptions) -> None:
    print()
    print("\033[1m── Syncing to Gemini CLI ──\033[0m")
    output = options.gemini_dir / "GEMINI.md"
    if options.dry_run:
        info(f"[dry-run] Would generate {output}")
        sync_mcp_to("gemini", "Gemini", options.gemini_dir / "mcp-servers.json", options.resolved["mcp"], True)
        return
    ensure_dir(options.gemini_dir)
    lines = [
        "<!-- MANAGED BY ai-management install.sh sync — DO NOT EDIT MANUALLY -->",
        "",
        "# Custom Instructions",
        "",
        "> Auto-generated from AI Management content by `install.sh sync`",
        f"> Last synced: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        "",
    ]
    if options.resolved["rules"]:
        lines.extend(["## Global Rules", ""])
        for rule_file in options.resolved["rules"]:
            built_file = CONTENT_ROOT / "rules" / "gemini" / rule_file.name
            source = built_file if built_file.exists() else rule_file
            lines.extend([f"### {source.stem}", "", source.read_text(encoding='utf-8').rstrip(), ""])
        lines.extend(["---", ""])
    lines.extend(["## Available Agent Personas", "", "When asked to work as a specific agent or persona, adopt the matching instructions below.", ""])
    for agent_file in options.resolved["agents"]:
        built_file = CONTENT_ROOT / "agents" / "gemini" / agent_file.name
        if not built_file.exists():
            continue
        lines.extend(["---", "", f"### Agent: {built_file.stem}", "", built_file.read_text(encoding='utf-8').rstrip(), ""])
    if options.resolved["workflows"]:
        lines.extend(["---", "", "## Workflows", ""])
        for workflow_file in options.resolved["workflows"]:
            built_file = CONTENT_ROOT / "workflows" / "gemini" / workflow_file.name
            source = built_file if built_file.exists() else workflow_file
            lines.extend([f"### {source.stem}", "", source.read_text(encoding='utf-8').rstrip(), ""])
    if options.resolved["skills"]:
        lines.extend(["---", "", "## Skills", "", "The following skills are available. Use their instructions when relevant.", ""])
        for skill_dir in options.resolved["skills"]:
            built_dir = CONTENT_ROOT / "skills" / "gemini" / skill_dir.name
            use_dir = built_dir if built_dir.exists() else skill_dir
            skill_md = None
            for candidate in (use_dir / "SKILL.md", use_dir / "skill.md"):
                if candidate.exists():
                    skill_md = candidate
                    break
            if skill_md is None:
                continue
            lines.extend([f"### Skill: {skill_dir.name}", "", skill_md.read_text(encoding='utf-8').rstrip(), ""])
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    log(f"Gemini: generated {output} ({output.stat().st_size // 1024}KB)")
    sync_mcp_to("gemini", "Gemini", options.gemini_dir / "mcp-servers.json", options.resolved["mcp"], False)


def purge_target(options: SyncOptions, target: str) -> None:
    print()
    print(f"\033[1m── Purging {target.capitalize()} ──\033[0m")
    paths = managed_paths_for(options, target)
    if options.dry_run:
        for key, path in paths.items():
            info(f"[dry-run] Would purge {key} at {path}")
        return
    for path in paths.values():
        if path.is_dir():
            purge_symlinks_in(path)
        else:
            remove_path(path)
    log(f"{target.capitalize()}: purged all managed files")


def sync_command(argv: Sequence[str]) -> int:
    options = parse_sync_args(argv)
    sync_init_runtime(options)
    if options.pull:
        pull_from_github()
    if not (CONTENT_ROOT / "agents").exists():
        raise CLIError(f"No agents directory found at {CONTENT_ROOT / 'agents'}")
    sync_resolve_selection(options)
    print(f"\033[1m🔄 AI Management Sync — {time.strftime('%Y-%m-%d %H:%M:%S')}\033[0m")
    if options.dry_run:
        print("(dry-run mode)")
    if options.restore or options.restore_latest:
        restore_targets(options)
        print()
        log("Restore complete.")
        return 0
    if options.backup:
        print()
        print("\033[1m── Backing up existing managed files ──\033[0m")
        for target in options.targets:
            for type_name, path in managed_paths_for(options, target).items():
                backup_path(target, type_name, path, options.target_root, options.dry_run)
    if options.purge:
        print("(purge mode — removing all managed files from targets)")
        for target in options.targets:
            purge_target(options, target)
        if not options.refresh:
            print()
            log("Purge complete.")
            return 0
        print()
        info("Continuing with fresh sync…")
    build_all(options.targets, dry_run=options.dry_run, quiet=not options.dry_run)
    for target in options.targets:
        if target == "copilot":
            sync_copilot(options)
        elif target == "codex":
            sync_codex(options)
        elif target == "claude":
            sync_claude(options)
        elif target == "gemini":
            sync_gemini(options)
    print()
    log("Sync complete.")
    return 0
