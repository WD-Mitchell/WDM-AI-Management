from __future__ import annotations

import os
import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

BUILTIN_HARNESSES = ["copilot", "claude", "codex", "gemini"]
CONTENT_TYPES = ["agents", "skills", "rules", "workflows", "hooks", "mcp"]
MANAGED_DIRS = ["agents", "skills", "hooks", "rules", "workflows", "mcp", "groups", "templates", "harnesses"]
CORE_SOURCE_DIR = "core"
CORE_CONTENT_TYPES = set(CONTENT_TYPES)
DISPLAY_FIELDS = {"color", "emoji", "vibe"}
DEFAULT_TIERS = {"default", "default-small", "default-large"}
OMIT_SENTINEL = "__omit__"
MCP_SOURCE_EXTENSIONS = (".md", ".json", ".yaml", ".yml")
MCP_BUILD_EXTENSIONS = MCP_SOURCE_EXTENSIONS
SYNC_TEMPLATE_FILE = ".ai-management"

PACKAGE_DIR = Path(__file__).resolve().parent
SCRIPT_DIR = PACKAGE_DIR.parent
REPO_ROOT = SCRIPT_DIR
APP_CONFIG_DIR = Path(os.environ.get("AI_MANAGEMENT_CONFIG_DIR", str(Path.home() / ".config" / "wdm-ai-management"))).expanduser()
SOURCE_SETTINGS_FILE = APP_CONFIG_DIR / "source.json"
DEFAULT_AI_MGMT_HOME = Path.home() / ".wdm"


def default_source_settings() -> dict:
    return {
        "mode": "local",
        "local_path": str(DEFAULT_AI_MGMT_HOME),
        "repo_url": "",
        "repo_token": "",
        "repo_checkout_path": "",
        "server_url": "",
    }


def load_source_settings() -> dict:
    defaults = default_source_settings()
    try:
        data = json.loads(SOURCE_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    if not isinstance(data, dict):
        return defaults
    settings = {**defaults}
    for key in defaults:
        value = data.get(key)
        if isinstance(value, str):
            settings[key] = value
    if settings["mode"] not in {"local", "repo"}:
        settings["mode"] = "local"
    return settings


def save_source_settings(settings: dict) -> dict:
    current = load_source_settings()
    next_settings = {**current}
    for key in default_source_settings():
        value = settings.get(key)
        if isinstance(value, str):
            next_settings[key] = value.strip()
    if next_settings["mode"] not in {"local", "repo"}:
        next_settings["mode"] = "local"
    if not next_settings["local_path"]:
        next_settings["local_path"] = str(DEFAULT_AI_MGMT_HOME)
    if next_settings["repo_url"] and not next_settings["repo_checkout_path"]:
        next_settings["repo_checkout_path"] = str(repo_checkout_path(next_settings["repo_url"]))
    APP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SOURCE_SETTINGS_FILE.write_text(json.dumps(next_settings, indent=2, ensure_ascii=True).rstrip() + "\n", encoding="utf-8")
    return next_settings


def source_settings_env_override() -> bool:
    return bool(os.environ.get("AI_MANAGEMENT_HOME"))


def repo_checkout_path(repo_url: str) -> Path:
    import hashlib
    import re

    normalized = repo_url.strip().rstrip("/") or "repository"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", normalized.split("/")[-1]).strip("-._")
    if stem.endswith(".git"):
        stem = stem[:-4]
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return APP_CONFIG_DIR / "repositories" / f"{stem or 'repository'}-{digest}"


def configured_ai_management_home() -> Path:
    env_home = os.environ.get("AI_MANAGEMENT_HOME")
    if env_home:
        return Path(env_home).expanduser()
    settings = load_source_settings()
    if settings.get("mode") == "repo" and settings.get("repo_url"):
        checkout = settings.get("repo_checkout_path") or str(repo_checkout_path(settings.get("repo_url", "")))
        return Path(checkout).expanduser()
    return Path(settings.get("local_path") or str(DEFAULT_AI_MGMT_HOME)).expanduser()


AI_MGMT_HOME = configured_ai_management_home()
INSTALLED_DIR = AI_MGMT_HOME / "installed"
BACKUP_DIR = AI_MGMT_HOME / "backups"
GITHUB_REPO = os.environ.get("AI_MANAGEMENT_REPO", "")
GITHUB_BRANCH = os.environ.get("AI_MANAGEMENT_BRANCH", "main")


def detect_content_root() -> Path:
    return AI_MGMT_HOME


def package_version() -> str:
    package_json = REPO_ROOT / "package.json"
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    return str(data.get("version") or "unknown")


APP_VERSION = package_version()
CONTENT_ROOT = detect_content_root()
GROUPS_DIR = CONTENT_ROOT / "groups"
TEMPLATES_DIR = CONTENT_ROOT / "templates"
DEFAULTS_FILE = CONTENT_ROOT / "defaults.conf"


def content_source_dir(content_type: str) -> Path:
    base = CONTENT_ROOT / content_type
    if content_type in CORE_CONTENT_TYPES:
        return base / CORE_SOURCE_DIR
    return base


def harness_source_dir() -> Path:
    return CONTENT_ROOT / "harnesses" / CORE_SOURCE_DIR


def harness_detected(definition: dict) -> bool:
    detect = definition.get("detect") if isinstance(definition, dict) else None
    if not isinstance(detect, dict):
        return False
    for command in detect.get("commands") or []:
        if shutil.which(str(command)):
            return True
    for raw_path in detect.get("paths") or []:
        path = Path(str(raw_path)).expanduser()
        if path.exists():
            return True
    return False


def harness_enabled(definition: dict) -> bool:
    enabled = definition.get("enabled") if isinstance(definition, dict) else None
    if isinstance(enabled, bool):
        return enabled
    if definition.get("auto_enable") and harness_detected(definition):
        return True
    if "default_enabled" in definition:
        return bool(definition.get("default_enabled"))
    return bool(definition.get("builtin", False))


def load_harness_definitions(include_disabled: bool = False) -> Dict[str, dict]:
    definitions: Dict[str, dict] = {}
    for harness in BUILTIN_HARNESSES:
        definitions[harness] = {"name": harness, "label": harness.title(), "builtin": True}
    base = harness_source_dir()
    if not base.exists():
        return definitions
    for path in sorted(base.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        name = str(data.get("name") or path.stem).strip()
        if not name:
            continue
        data["name"] = name
        data.setdefault("label", name.title())
        data["detected"] = harness_detected(data)
        definitions[name] = data
    if include_disabled:
        return definitions
    return {name: data for name, data in definitions.items() if harness_enabled(data)}


ALL_HARNESS_DEFINITIONS = load_harness_definitions(include_disabled=True)
HARNESS_DEFINITIONS = {name: data for name, data in ALL_HARNESS_DEFINITIONS.items() if harness_enabled(data)}
ALL_HARNESSES = list(HARNESS_DEFINITIONS.keys())
CONFIGURED_HARNESSES = list(ALL_HARNESS_DEFINITIONS.keys())
HARNESS_SET = set(CONFIGURED_HARNESSES)
HARNESS_SKIP_DIRS = HARNESS_SET | {"__pycache__", "backups"}

USE_COLOR = sys.stdout.isatty() and os.environ.get("TERM", "") not in {"", "dumb"}
BOLD = "\033[1m" if USE_COLOR else ""
RED = "\033[0;31m" if USE_COLOR else ""
GREEN = "\033[0;32m" if USE_COLOR else ""
YELLOW = "\033[1;33m" if USE_COLOR else ""
BLUE = "\033[0;34m" if USE_COLOR else ""
CYAN = "\033[0;36m" if USE_COLOR else ""
NC = "\033[0m" if USE_COLOR else ""


class CLIError(Exception):
    pass


@dataclass
class SyncOptions:
    dry_run: bool = False
    refresh: bool = False
    purge: bool = False
    backup: bool = True
    pull: bool = False
    restore: bool = False
    restore_latest: bool = False
    restore_file: str = ""
    global_mode: bool = False
    targets: List[str] = field(default_factory=list)
    selected_groups: List[str] = field(default_factory=list)
    template: str = ""
    target_root: Optional[Path] = None
    copilot_agents_dir: Optional[Path] = None
    copilot_skills_dir: Optional[Path] = None
    copilot_rules_dir: Optional[Path] = None
    copilot_workflows_dir: Optional[Path] = None
    copilot_hooks_dir: Optional[Path] = None
    copilot_mcp_file: Optional[Path] = None
    codex_dir: Optional[Path] = None
    codex_agents_dir: Optional[Path] = None
    codex_config_toml: Optional[Path] = None
    codex_skills_dir: Optional[Path] = None
    claude_dir: Optional[Path] = None
    claude_mcp_file: Optional[Path] = None
    gemini_dir: Optional[Path] = None
    gemini_settings_file: Optional[Path] = None
    resolved: Dict[str, List[Path]] = field(default_factory=lambda: {content_type: [] for content_type in CONTENT_TYPES})


def log(message: str) -> None:
    print(f"{GREEN}✓{NC} {message}")


def ok(message: str) -> None:
    print(f"  {GREEN}✓{NC} {message}")


def warn(message: str) -> None:
    print(f"{YELLOW}⚠{NC} {message}")


def info(message: str) -> None:
    print(f"{BLUE}→{NC} {message}")


def err(message: str) -> None:
    print(f"{RED}✗{NC} {message}", file=sys.stderr)


def clear_screen() -> None:
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def remove_path(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def strip_inline_comment(line: str) -> str:
    if "#" in line:
        line = line.split("#", 1)[0]
    return line.strip()


def dedupe(items):
    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def singular_label(content_type: str) -> str:
    return content_type[:-1] if content_type.endswith("s") else content_type


def is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.relative_to(other)
        return True
    except ValueError:
        return False
