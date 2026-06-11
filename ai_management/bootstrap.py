from __future__ import annotations

import importlib
import shutil
from pathlib import Path
from typing import Iterable

from .utils import AI_MGMT_HOME, MANAGED_DIRS, PACKAGE_DIR, ensure_dir, info, log, remove_path, warn

BOOTSTRAP_SKILL = "AI-Management"
LEGACY_BOOTSTRAP_SKILLS = ("WDM-Agent-Management",)


def package_repo_root() -> Path:
    return PACKAGE_DIR.parent


def copy_missing_tree(source: Path, destination: Path, overwrite: bool = False) -> None:
    if not source.exists():
        return
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_dir():
            ensure_dir(target)
            continue
        ensure_dir(target.parent)
        try:
            if path.resolve() == target.resolve():
                continue
        except OSError:
            pass
        if overwrite or not target.exists():
            shutil.copy2(path, target)


def bootstrap_content(overwrite: bool = False) -> None:
    root = package_repo_root()
    ensure_dir(AI_MGMT_HOME)
    for directory in MANAGED_DIRS:
        copy_missing_tree(root / directory, AI_MGMT_HOME / directory, overwrite=overwrite)
    for file_name in ("defaults.conf", "flags.md"):
        source = root / file_name
        target = AI_MGMT_HOME / file_name
        if source.exists() and (overwrite or not target.exists()):
            shutil.copy2(source, target)
    for template in (root / "templates" / "core").glob("*-standard.template"):
        target = AI_MGMT_HOME / "templates" / "core" / template.name
        if template.exists() and (overwrite or not target.exists() or template.name.endswith("-standard.template")):
            ensure_dir(target.parent)
            shutil.copy2(template, target)
    # Keep the management skill itself current so global harness skill installs
    # point at the package version that provided this bootstrap command.
    source_skill = root / "skills" / "core" / BOOTSTRAP_SKILL
    target_skill = AI_MGMT_HOME / "skills" / "core" / BOOTSTRAP_SKILL
    copy_missing_tree(source_skill, target_skill, overwrite=True)
    for legacy_child in ("ai_management", "build.py", "install.sh"):
        remove_path(target_skill / legacy_child)
    for legacy_skill in LEGACY_BOOTSTRAP_SKILLS:
        remove_path(AI_MGMT_HOME / "skills" / "core" / legacy_skill)


def reload_runtime_modules():
    from . import build, groups, install, sync, utils

    utils = importlib.reload(utils)
    groups = importlib.reload(groups)
    build = importlib.reload(build)
    install = importlib.reload(install)
    sync = importlib.reload(sync)
    return utils, build, install, sync


def install_bootstrap_skill(install_module) -> None:
    installed = [
        item
        for item in install_module.load_installed_type("skills")
        if item not in LEGACY_BOOTSTRAP_SKILLS
    ]
    if BOOTSTRAP_SKILL not in installed:
        installed.append(BOOTSTRAP_SKILL)
    install_module.save_installed_type("skills", installed)


def sync_bootstrap_skill(utils_module, build_module, sync_module, targets: Iterable[str], quiet: bool = False) -> None:
    selected_targets = [target for target in targets if target in utils_module.ALL_HARNESSES]
    if not selected_targets:
        if not quiet:
            warn("No enabled harnesses found for global skill sync.")
        return
    source = utils_module.content_source_dir("skills") / BOOTSTRAP_SKILL
    if not source.exists():
        if not quiet:
            warn(f"Bootstrap skill source not found: {source}")
        return
    options = utils_module.SyncOptions(global_mode=True, targets=selected_targets, backup=False)
    sync_module.sync_init_runtime(options)
    options.resolved["skills"] = [source]
    build_module.build_skills(utils_module.content_source_dir("skills"), selected_targets, dry_run=False)
    for target in selected_targets:
        target_dir = sync_module.managed_paths_for(options, target).get("skills")
        if not target_dir:
            continue
        label = str(utils_module.HARNESS_DEFINITIONS.get(target, {}).get("label") or target.title())
        sync_module.sync_items_to(target_dir, target, "skills", [source], dry_run=False, refresh=False, label=label)


def bootstrap(force: bool = False, sync_skills: bool = True, quiet: bool = False) -> None:
    if not quiet:
        info(f"Bootstrapping AI Management source files in {AI_MGMT_HOME}")
    bootstrap_content(overwrite=force)
    utils_module, build_module, install_module, sync_module = reload_runtime_modules()
    install_bootstrap_skill(install_module)
    if sync_skills:
        sync_bootstrap_skill(utils_module, build_module, sync_module, utils_module.ALL_HARNESSES, quiet=quiet)
    if not quiet:
        log("Bootstrap complete.")
