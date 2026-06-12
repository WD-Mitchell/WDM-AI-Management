from __future__ import annotations

import contextlib
import html
import importlib
import io
import json
import os
import errno
import re
import shutil
import sys
import threading
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import yaml

from .build import (
    AGENT_SCHEMAS,
    RULE_SCHEMAS,
    SKILL_SCHEMAS,
    WORKFLOW_SCHEMAS,
    build_codex_agent_toml,
    build_md_file,
    load_defaults,
    parse_frontmatter,
)
from .groups import get_all_type, parse_group_section, parse_section_file, resolve_item_path
from .install import load_installed_type, save_installed_type
from .sync import sync_command
from .utils import (
    ALL_HARNESS_DEFINITIONS,
    ALL_HARNESSES,
    AI_MGMT_HOME,
    CONFIGURED_HARNESSES,
    CONTENT_ROOT,
    CONTENT_TYPES,
    DEFAULTS_FILE,
    HARNESS_DEFINITIONS,
    TEMPLATES_DIR,
    content_source_dir,
    harness_detected,
    harness_enabled,
)
from . import build as build_module
from . import sync as sync_module
from . import utils as utils_module


EDITABLE_TYPES = {"agents", "skills", "rules", "workflows", "hooks", "mcp", "groups", "templates", "harnesses"}
LIST_TYPES = ["agents", "skills", "mcp", "rules", "workflows", "hooks", "harnesses", "templates", "groups"]
EDITOR_VIEWS = {"form", "file"}
PREVIEW_TYPES = {"agents", "skills", "rules", "workflows", "mcp"}
FIELD_ORDER = [
    "name",
    "description",
    "model",
    "tools",
    "transport",
    "command",
    "args",
    "env",
    "url",
    "headers",
    "license",
    "metadata",
    "allowed-tools",
    "argument-hint",
    "codex_model",
    "codex_model_reasoning_effort",
    "codex_sandbox_mode",
    "claude_model",
    "claude_effort",
    "copilot_model",
    "gemini_model",
    "global_model",
]
TYPE_FIELD_ORDER = {
    "agents": [
        "name",
        "description",
        "model",
        "tools",
        "mcp_servers",
        "codex_model",
        "codex_model_reasoning_effort",
        "codex_sandbox_mode",
        "claude_model",
        "claude_effort",
        "copilot_model",
        "gemini_model",
        "global_model",
    ],
    "skills": ["name", "description", "license", "metadata"],
    "mcp": ["name", "description", "transport", "command", "args", "env", "url", "headers"],
    "rules": ["name", "description"],
    "workflows": ["name", "description", "model", "allowed-tools", "argument-hint"],
    "hooks": ["name", "hook_shebang", "hook_description", "hook_script"],
}
SOURCE_DIRS = ["agents", "skills", "rules", "workflows", "hooks", "mcp", "groups", "templates", "harnesses"]
TEMPLATE_TARGET_TYPES = {"agents", "skills", "rules", "workflows", "mcp", "hooks"}
SECTIONLESS_TEMPLATE_TYPES = {"hooks", "mcp"}
PROJECTS_FILE = AI_MGMT_HOME / "projects.json"
RELOAD_ENV = "AI_MANAGEMENT_WEB_RELOAD"
DEFAULT_SELECTION_ITEMS_PER_PAGE = 20
DEFAULT_SELECTION_SORT = "installed-desc"
MIN_SELECTION_ITEMS_PER_PAGE = 1
MAX_SELECTION_ITEMS_PER_PAGE = 100
HARNESS_NONE_VALUE = "__none__"
LIST_FIELD_NAMES = {
    "tools",
    "disallowedTools",
    "disallowed_tools",
    "allowed_tools",
    "allowed-tools",
    "mcp_servers",
    "mcp-servers",
    "exclude_tools",
    "exclude_mcp_servers",
    "args",
    "paths",
    "globs",
    "applyTo",
    "nicknames",
    "nickname_candidates",
    "watch_paths",
    "disabled_tools",
}
MAPPING_FIELD_NAMES = {"env", "headers", "metadata", "generation_config", "thinking_config", "activation"}
TEXTAREA_FIELD_NAMES = {
    "description",
    "argument_hint",
    "argument-hint",
    "license",
    "initial_prompt",
    "role_definition",
    "when_to_use",
    "custom_instructions",
    "developer_instructions",
    "hook_description",
    "hook_script",
}
BOOLEAN_FIELD_NAMES = {
    "alwaysApply",
    "always_apply",
    "disable_model_invocation",
    "disable-model-invocation",
    "user_invocable",
    "user-invocable",
    "auto_approve",
    "always_allow",
    "read_only",
    "background",
}
HOOK_TEMPLATE_FIELDS = ("hook_shebang", "hook_description", "hook_script")
FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="14" fill="#1d4ed8"/>
<path d="M16 42l8-20h6l8 20h-6l-1.5-4.5h-7L22 42h-6zm9-9h4l-2-6-2 6zm17 9V22h6v20h-6z" fill="#eff6ff"/>
</svg>
"""
SORT_OPTIONS = {
    "installed-desc": "Most projects",
    "installed-asc": "Least projects",
    "name-asc": "Name A-Z",
    "name-desc": "Name Z-A",
    "created-desc": "Newest created",
    "created-asc": "Oldest created",
    "modified-desc": "Recently modified",
    "modified-asc": "Least recently modified",
}
SOURCE_FILTER_MODES = {"managed", "combined", "external"}
IMPORT_MAX_BYTES = 3 * 1024 * 1024
TEMPLATE_TYPE_LABELS = {
    "agents": "Agents",
    "skills": "Skills",
    "mcp": "MCP",
    "hooks": "Hooks",
    "rules": "Rules",
    "workflows": "Workflows",
}
DEFAULT_MODEL_TIERS = [
    ("default-small", "Default small"),
    ("default", "Default"),
    ("default-large", "Default large"),
]
FIELD_LABELS = {
    "name": "Name",
    "description": "Description",
    "model": "Model",
    "tools": "Tools",
    "mcp_servers": "MCP servers",
    "mcp-servers": "MCP servers",
    "skills": "Skills",
    "reasoning": "Reasoning",
    "sandbox": "Sandbox",
    "sandbox_mode": "Sandbox",
    "allowed_tools": "Allowed tools",
    "allowed-tools": "Allowed tools",
    "argument_hint": "Argument hint",
    "argument-hint": "Argument hint",
    "disable_model_invocation": "Disable model invocation",
    "disable-model-invocation": "Disable model invocation",
    "user_invocable": "User invocable",
    "user-invocable": "User invocable",
    "disallowed_tools": "Disallowed tools",
    "disallowedTools": "Disallowed tools",
    "permission_mode": "Permission mode",
    "permissionMode": "Permission mode",
    "max_turns": "Max turns",
    "maxTurns": "Max turns",
    "initial_prompt": "Initial prompt",
    "initialPrompt": "Initial prompt",
    "nicknames": "Nicknames",
    "nickname_candidates": "Nicknames",
    "exclude_tools": "Excluded tools",
    "excludeTools": "Excluded tools",
    "exclude_mcp_servers": "Excluded MCP servers",
    "thinking_budget": "Thinking budget",
    "thinkingBudget": "Thinking budget",
    "thinking_config": "Thinking config",
    "thinkingConfig": "Thinking config",
    "always_apply": "Always apply",
    "alwaysApply": "Always apply",
    "context_file_name": "Context file name",
    "metadata": "Metadata",
    "env": "Environment",
    "headers": "Headers",
    "args": "Arguments",
    "globs": "Globs",
    "paths": "Paths",
    "url": "URL",
}
SANDBOX_OPTIONS = [
    ("", "Default"),
    ("read-only", "Read only"),
    ("workspace-write", "Workspace write"),
    ("danger-full-access", "Danger full access"),
]


def harness_field_mappings_for(harness: str, content_type: str) -> dict[str, list[str]]:
    definition = ALL_HARNESS_DEFINITIONS.get(harness, {})
    mappings = definition.get("field_mappings", {}) if isinstance(definition, dict) else {}
    type_mappings = mappings.get(content_type, {}) if isinstance(mappings, dict) else {}
    if not isinstance(type_mappings, dict):
        return {}
    normalized: dict[str, list[str]] = {}
    for source_field, output_fields in type_mappings.items():
        source = str(source_field or "").strip()
        if not source:
            continue
        if isinstance(output_fields, str):
            values = [output_fields]
        elif isinstance(output_fields, list):
            values = output_fields
        else:
            continue
        outputs = [str(item).strip() for item in values if str(item).strip()]
        if outputs:
            normalized[source] = outputs
    return normalized


def mapped_sources_for_output(harness: str, content_type: str, output_field: str) -> list[str]:
    return [
        source
        for source, output_fields in harness_field_mappings_for(harness, content_type).items()
        if output_field in output_fields
    ]


def mapped_outputs_for_source(harness: str, content_type: str, source_field: str) -> list[str]:
    return harness_field_mappings_for(harness, content_type).get(source_field, [])


def schema_supports_source_field(harness: str, content_type: str, source_field: str) -> bool:
    schema_map = {
        "agents": AGENT_SCHEMAS,
        "skills": SKILL_SCHEMAS,
        "rules": RULE_SCHEMAS,
        "workflows": WORKFLOW_SCHEMAS,
    }.get(content_type, {})
    schema = schema_map.get(harness, []) if isinstance(schema_map, dict) else []
    if source_field in schema:
        return True
    return any(output_field in schema for output_field in mapped_outputs_for_source(harness, content_type, source_field))


def schema_field_order(content_type: str) -> list[str]:
    schema_map = {
        "agents": AGENT_SCHEMAS,
        "skills": SKILL_SCHEMAS,
        "rules": RULE_SCHEMAS,
        "workflows": WORKFLOW_SCHEMAS,
    }.get(content_type)
    fields = list(TYPE_FIELD_ORDER.get(content_type, FIELD_ORDER))
    if isinstance(schema_map, dict):
        for harness in ALL_HARNESSES:
            for field_name in schema_map.get(harness, []):
                mapped_sources = mapped_sources_for_output(harness, content_type, field_name)
                if mapped_sources:
                    fields.extend(source for source in mapped_sources if source != "body")
                    continue
                fields.append(field_name)
    return list(dict.fromkeys(fields))
REASONING_OPTIONS = {
    "model_reasoning_effort": [
        ("", "Default"),
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
    ],
    "effort": [
        ("", "Default"),
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
    ],
    "thinkingLevel": [
        ("", "Default"),
        ("LOW", "Low"),
        ("MEDIUM", "Medium"),
        ("HIGH", "High"),
    ],
}
REASONING_MIDDLE_VALUES = {
    "model_reasoning_effort": "medium",
    "effort": "medium",
    "thinkingLevel": "MEDIUM",
}
REASONING_BUDGET_LEVELS = {
    "1024": "LOW",
    "4096": "MEDIUM",
    "16384": "HIGH",
}
REASONING_FIELDS = {
    "codex": "model_reasoning_effort",
    "claude": "effort",
    "gemini": "thinkingLevel",
}
AGENT_CAPABILITY_FIELDS = {
    "skills": {"content_type": "skills", "label": "Skills"},
    "mcp_servers": {"content_type": "mcp", "label": "MCP servers"},
    "mcp-servers": {"content_type": "mcp", "label": "MCP servers"},
}


class ReloadableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def browser_url(host: str, port: int) -> str:
    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    return f"http://{browser_host}:{port}/"


def web_server_responding(host: str, port: int, timeout: float = 0.5) -> bool:
    request = urllib.request.Request(browser_url(host, port), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout):
            return True
    except urllib.error.HTTPError:
        return True
    except (OSError, TimeoutError, urllib.error.URLError):
        return False


def run_web(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False, reload: bool = False) -> int:
    ensure_source_root()
    url = browser_url(host, port)
    if web_server_responding(host, port):
        print(f"AI Management web UI already running at {url}")
        if open_browser:
            webbrowser.open(url)
        return 0
    if reload:
        os.environ[RELOAD_ENV] = "1"
        start_reload_watcher()
    else:
        os.environ.pop(RELOAD_ENV, None)
    try:
        server = ReloadableThreadingHTTPServer((host, port), ManagementHandler)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            print(f"AI Management web UI already running at {url}")
            if open_browser:
                webbrowser.open(url)
            return 0
        raise
    url = browser_url(host, server.server_port)
    print(f"AI Management web UI running at {url}")
    if reload:
        print("Reload mode enabled. Python/UI changes will restart the server and refresh the page.")
    print("Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.2, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
    return 0


def iter_reload_files():
    package_dir = Path(__file__).resolve().parent
    script_dir = package_dir.parent
    for path in sorted(package_dir.glob("*.py")):
        yield path
    for path in sorted(script_dir.glob("*.py")):
        yield path
    for path in sorted((CONTENT_ROOT / "harnesses" / "core").glob("*.json")):
        yield path


def reload_token() -> str:
    values = []
    for path in iter_reload_files():
        try:
            stat = path.stat()
        except OSError:
            continue
        values.append(f"{path}:{stat.st_mtime_ns}:{stat.st_size}")
    return str(hash(tuple(values)))


def start_reload_watcher(interval: float = 1.0) -> None:
    original = reload_token()

    def watch() -> None:
        token = original
        while True:
            time.sleep(interval)
            current = reload_token()
            if current == token:
                continue
            print("Change detected; restarting AI Management web UI.", flush=True)
            os.execv(sys.executable, [sys.executable] + sys.argv)

    threading.Thread(target=watch, daemon=True).start()


def parse_query(path: str) -> tuple[str, dict[str, list[str]]]:
    parsed = urllib.parse.urlparse(path)
    return parsed.path, urllib.parse.parse_qs(parsed.query, keep_blank_values=True)


def first(query: dict[str, list[str]], key: str, default: str | None = "") -> str | None:
    values = query.get(key, [])
    return values[0] if key in query and values else default


def positive_int(value: str | None, default: int = 1) -> int:
    try:
        return max(1, int(value or default))
    except (TypeError, ValueError):
        return default


def escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def escape_textarea(value: Any) -> str:
    escaped = escape(value)
    if escaped.startswith("\r\n"):
        return "&#13;&#10;" + escaped[2:]
    if escaped.startswith("\n"):
        return "&#10;" + escaped[1:]
    if escaped.startswith("\r"):
        return "&#13;" + escaped[1:]
    return escaped


def ensure_source_root() -> None:
    try:
        AI_MGMT_HOME.mkdir(parents=True, exist_ok=True)
        for name in SOURCE_DIRS:
            (AI_MGMT_HOME / name).mkdir(parents=True, exist_ok=True)
            if name in CONTENT_TYPES:
                content_source_dir(name).mkdir(parents=True, exist_ok=True)
            if name == "harnesses":
                (AI_MGMT_HOME / name / "core").mkdir(parents=True, exist_ok=True)
            if name == "templates":
                (AI_MGMT_HOME / name / "core").mkdir(parents=True, exist_ok=True)
        ensure_default_content_templates()
        if not PROJECTS_FILE.exists():
            PROJECTS_FILE.write_text("[]\n", encoding="utf-8")
    except OSError:
        # Rendering can still work in restricted environments. Mutating actions
        # will report their own write errors when attempted.
        pass


def refresh_harness_runtime() -> None:
    global ALL_HARNESS_DEFINITIONS, ALL_HARNESSES, CONFIGURED_HARNESSES, HARNESS_DEFINITIONS
    global AGENT_SCHEMAS, RULE_SCHEMAS, SKILL_SCHEMAS, WORKFLOW_SCHEMAS
    global build_codex_agent_toml, build_md_file, load_defaults, parse_frontmatter, sync_command

    refreshed_utils = importlib.reload(utils_module)
    refreshed_build = importlib.reload(build_module)
    refreshed_sync = importlib.reload(sync_module)
    ALL_HARNESS_DEFINITIONS = refreshed_utils.ALL_HARNESS_DEFINITIONS
    HARNESS_DEFINITIONS = refreshed_utils.HARNESS_DEFINITIONS
    ALL_HARNESSES = refreshed_utils.ALL_HARNESSES
    CONFIGURED_HARNESSES = refreshed_utils.CONFIGURED_HARNESSES
    AGENT_SCHEMAS = refreshed_build.AGENT_SCHEMAS
    SKILL_SCHEMAS = refreshed_build.SKILL_SCHEMAS
    RULE_SCHEMAS = refreshed_build.RULE_SCHEMAS
    WORKFLOW_SCHEMAS = refreshed_build.WORKFLOW_SCHEMAS
    build_codex_agent_toml = refreshed_build.build_codex_agent_toml
    build_md_file = refreshed_build.build_md_file
    load_defaults = refreshed_build.load_defaults
    parse_frontmatter = refreshed_build.parse_frontmatter
    sync_command = refreshed_sync.sync_command


def default_content_template_definitions() -> dict[str, dict[str, Any]]:
    return {
        "agent-standard": {
            "name": "agent-standard",
            "type": "agents",
            "description": "Default agent instruction sections.",
            "sections": [
                {"title": "Communication Protocol", "level": 2},
                {"title": "Core Mission", "level": 2},
                {"title": "Responsibilities", "level": 2},
                {"title": "Execution Flow", "level": 2},
                {"title": "Output Format", "level": 2},
                {"title": "Failure Handling", "level": 2},
                {"title": "Success Metrics", "level": 2},
            ],
        },
        "skill-standard": {
            "name": "skill-standard",
            "type": "skills",
            "description": "Default skill documentation sections.",
            "sections": [
                {"title": "When To Use", "level": 2},
                {"title": "Workflow", "level": 2},
                {"title": "Examples", "level": 2},
                {"title": "Best Practices", "level": 2},
                {"title": "Output Rules", "level": 2},
                {"title": "Troubleshooting", "level": 2},
            ],
        },
        "mcp-standard": {
            "name": "mcp-standard",
            "type": "mcp",
            "description": "Default MCP server documentation sections.",
            "sections": [
                {"title": "Usage Notes", "level": 2},
                {"title": "Configuration", "level": 2},
                {"title": "Environment", "level": 2},
            ],
        },
        "rule-standard": {
            "name": "rule-standard",
            "type": "rules",
            "description": "Default rule sections.",
            "sections": [
                {"title": "Requirements", "level": 2},
                {"title": "Examples", "level": 2},
                {"title": "Exceptions", "level": 2},
            ],
        },
        "workflow-standard": {
            "name": "workflow-standard",
            "type": "workflows",
            "description": "Default workflow sections.",
            "sections": [
                {"title": "Steps", "level": 2},
                {"title": "Guidelines", "level": 2},
                {"title": "Output", "level": 2},
            ],
        },
        "hook-standard": {
            "name": "hook-standard",
            "type": "hooks",
            "description": "Default shell hook script template.",
            "fields": {
                "hook_shebang": "#!/usr/bin/env bash",
                "hook_description": "Describe when this hook runs and what it does.",
                "hook_script": "set -euo pipefail\n\n",
            },
            "sections": [],
        },
    }


def ensure_default_content_templates() -> None:
    base = TEMPLATES_DIR / "core"
    base.mkdir(parents=True, exist_ok=True)
    for name, definition in default_content_template_definitions().items():
        path = base / f"{name}.template"
        if path.exists():
            continue
        path.write_text(yaml.safe_dump(definition, sort_keys=False, allow_unicode=False), encoding="utf-8")


def normalize_template_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip().lower()).strip("-._")
    return slug or "template"


def template_definition_from_raw(raw: str, fallback_name: str = "") -> dict[str, Any]:
    loaded = yaml.safe_load(raw) if raw.strip() else {}
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise ValueError("Template file must be a YAML mapping.")
    name = str(loaded.get("name") or fallback_name).strip()
    target_type = str(loaded.get("type") or loaded.get("content_type") or "").strip()
    if target_type not in TEMPLATE_TARGET_TYPES:
        raise ValueError("Template type must be one of: " + ", ".join(sorted(TEMPLATE_TARGET_TYPES)))
    sections = loaded.get("sections") or []
    if not isinstance(sections, list):
        raise ValueError("Template sections must be a list.")
    normalized_sections: list[dict[str, Any]] = []
    for section in sections:
        if isinstance(section, str):
            title = section.strip()
            level = 2
            content = ""
        elif isinstance(section, dict):
            title = str(section.get("title") or "").strip()
            level = template_level_value(section.get("level"), 2)
            content = str(section.get("content") or "")
        else:
            continue
        if not title:
            continue
        normalized_sections.append({"title": title, "level": level, "content": content})
    if not normalized_sections and target_type not in SECTIONLESS_TEMPLATE_TYPES:
        raise ValueError("Template needs at least one section.")
    fields = loaded.get("fields") or {}
    if not isinstance(fields, dict):
        raise ValueError("Template fields must be a YAML mapping.")
    field_sections = sanitize_template_field_sections(
        target_type,
        normalize_template_field_sections(loaded.get("field_sections") or {}),
    )
    return {
        "name": name or normalize_template_slug(f"{target_type}-template"),
        "type": target_type,
        "description": str(loaded.get("description") or "").strip(),
        "fields": fields,
        "sections": normalized_sections,
        "field_sections": field_sections,
    }


def template_definition_path(name: str) -> Path:
    return TEMPLATES_DIR / "core" / f"{name}.template"


def template_level_value(value: Any, default: int = 2) -> int:
    try:
        return min(6, max(0, int(value)))
    except (TypeError, ValueError):
        return default


def read_template_definition(name: str) -> dict[str, Any]:
    path = template_definition_path(name)
    return template_definition_from_raw(path.read_text(encoding="utf-8"), path.stem)


def content_templates_for_type(content_type: str) -> list[dict[str, Any]]:
    if content_type not in TEMPLATE_TARGET_TYPES:
        return []
    templates: list[dict[str, Any]] = []
    for name in list_names("templates"):
        try:
            definition = read_template_definition(name)
        except (OSError, ValueError, yaml.YAMLError):
            continue
        if definition.get("type") == content_type:
            definition["name"] = name
            templates.append(definition)
    return sorted(templates, key=lambda item: (0 if str(item.get("name", "")).endswith("-standard") else 1, str(item.get("name", "")).casefold()))


def default_template_for_type(content_type: str) -> dict[str, Any] | None:
    templates = content_templates_for_type(content_type)
    if not templates:
        return None
    default_name = f"{content_type[:-1] if content_type.endswith('s') else content_type}-standard"
    for template in templates:
        if template.get("name") == default_name:
            return template
    return templates[0]


def template_sections_for_editor(template: dict[str, Any] | None) -> list[tuple[str, str, str]]:
    if not template:
        return []
    sections = []
    for section in template.get("sections") or []:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "").strip()
        if not title:
            continue
        level = str(template_level_value(section.get("level"), 2))
        content = str(section.get("content") or "")
        sections.append((title, level, content))
    return sections


def normalize_template_field_sections(raw: Any) -> dict[str, dict[str, Any]]:
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("Template field_sections must be a YAML mapping.")
    normalized: dict[str, dict[str, Any]] = {}
    for key, definition in raw.items():
        field_key = str(key or "").strip()
        if not field_key:
            continue
        if isinstance(definition, list):
            label = field_key.replace("_", " ").replace("-", " ").title()
            raw_sections = definition
        elif isinstance(definition, dict):
            label = str(definition.get("label") or field_key.replace("_", " ").replace("-", " ").title()).strip()
            raw_sections = definition.get("sections") or []
        else:
            continue
        if not isinstance(raw_sections, list):
            raise ValueError(f"Template field_sections.{field_key}.sections must be a list.")
        sections: list[dict[str, Any]] = []
        for section in raw_sections:
            if isinstance(section, str):
                title = section.strip()
                level = 2
                content = ""
            elif isinstance(section, dict):
                title = str(section.get("title") or "").strip()
                level = template_level_value(section.get("level"), 2)
                content = str(section.get("content") or "")
            else:
                continue
            if title:
                sections.append({"title": title, "level": level, "content": content})
        if sections:
            normalized[field_key] = {"label": label or field_key, "sections": sections}
    return normalized


def template_field_sections_for_editor(template: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    try:
        return normalize_template_field_sections(template.get("field_sections") if template else {})
    except ValueError:
        return {}


def sanitize_template_field_sections(target_type: str, field_sections: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    sanitized = dict(field_sections)
    if target_type == "agents":
        # Codex developer_instructions is generated from the shared markdown
        # body; it must not become a separate source frontmatter field.
        sanitized.pop("developer_instructions", None)
    return sanitized


def template_fields_for_editor(template: dict[str, Any] | None) -> dict[str, Any]:
    fields = template.get("fields") if template else {}
    return fields if isinstance(fields, dict) else {}


def filter_template_fields_for_target(fields: dict[str, Any], previous_type: str, target_type: str) -> dict[str, Any]:
    if not previous_type or previous_type == target_type or previous_type not in TEMPLATE_TARGET_TYPES:
        return fields
    previous_known_keys = reserved_form_field_keys(previous_type)
    target_known_keys = reserved_form_field_keys(target_type)
    return {
        key: value
        for key, value in fields.items()
        if key in target_known_keys or key not in previous_known_keys
    }


def template_fields_from_form(form: dict[str, Any], target_type: str) -> dict[str, Any]:
    if form.get("template_fields_mode") == "structured":
        original_fields = original_fields_from_form(form)
        field_form = dict(form)
        field_form["type"] = target_type
        loaded_fields = normalize_fields(field_form, original_fields)
        if target_type == "agents":
            loaded_fields = normalize_agent_model_fields(loaded_fields, original_fields)
            loaded_fields = expand_agent_capability_fields(loaded_fields, original_fields)
        previous_type = str(
            form.get("template_fields_previous_type")
            or form.get("template_fields_current_type")
            or ""
        ).strip()
        loaded_fields = filter_template_fields_for_target(loaded_fields, previous_type, target_type)
        loaded_fields.pop("name", None)
        return loaded_fields
    raw_fields = str(form.get("template_fields") or "").strip()
    try:
        loaded_fields = yaml.safe_load(raw_fields) if raw_fields else {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Template fields are invalid YAML: {exc}") from exc
    if loaded_fields is None:
        loaded_fields = {}
    if not isinstance(loaded_fields, dict):
        raise ValueError("Template fields must be a YAML mapping.")
    return loaded_fields


def template_field_sections_from_form(form: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = str(form.get("template_field_sections") or "").strip()
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Template field sections are invalid JSON: {exc}") from exc
    return normalize_template_field_sections(loaded)


def template_definition_from_form(form: dict[str, Any]) -> dict[str, Any]:
    name = str(form.get("name") or form.get("original_name") or "new-template").strip()
    target_type = str(form.get("template_type") or "agents").strip()
    if target_type not in TEMPLATE_TARGET_TYPES:
        raise ValueError("Template type must be one of: " + ", ".join(sorted(TEMPLATE_TARGET_TYPES)))
    raw_sections = str(form.get("template_sections") or "").strip()
    try:
        loaded_sections = json.loads(raw_sections) if raw_sections else []
    except json.JSONDecodeError as exc:
        raise ValueError(f"Template sections are invalid JSON: {exc}") from exc
    if not isinstance(loaded_sections, list):
        raise ValueError("Template sections must be a list.")
    sections = []
    for section in loaded_sections:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "").strip()
        content = str(section.get("content") or "")
        if not title and not content.strip():
            continue
        if not title:
            raise ValueError("Template sections need a title.")
        sections.append(
            {
                "title": title,
                "level": template_level_value(section.get("level"), 2),
                "content": content,
            }
        )
    if not sections and target_type not in SECTIONLESS_TEMPLATE_TYPES:
        raise ValueError("Template needs at least one section.")
    loaded_fields = template_fields_from_form(form, target_type)
    field_sections = sanitize_template_field_sections(target_type, template_field_sections_from_form(form))
    return {
        "name": name,
        "type": target_type,
        "description": str(form.get("template_description") or "").strip(),
        "fields": loaded_fields,
        "sections": sections,
        "field_sections": field_sections,
    }


def dump_template_definition(definition: dict[str, Any]) -> str:
    return yaml.safe_dump(definition, sort_keys=False, allow_unicode=False).strip() + "\n"


def load_projects() -> list[dict[str, str]]:
    ensure_source_root()
    try:
        data = json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    projects = []
    seen = set()
    for entry in data:
        if not isinstance(entry, dict):
            continue
        root = str(entry.get("root") or "").strip()
        if not root:
            continue
        resolved = str(Path(root).expanduser().resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        label = str(entry.get("label") or Path(resolved).name or resolved).strip()
        projects.append({"label": label, "root": resolved})
    return projects


def save_projects(projects: list[dict[str, str]]) -> None:
    AI_MGMT_HOME.mkdir(parents=True, exist_ok=True)
    PROJECTS_FILE.write_text(json.dumps(projects, indent=2) + "\n", encoding="utf-8")


def add_project(label: str, root: str) -> dict[str, str]:
    path = Path(root).expanduser().resolve()
    if not path.exists() or not path.is_dir():
        raise ValueError(f"Project path is not a directory: {path}")
    resolved = str(path)
    project = {"label": label.strip() or path.name or resolved, "root": resolved}
    projects = [item for item in load_projects() if item["root"] != resolved]
    projects.append(project)
    projects.sort(key=lambda item: item["label"].lower())
    save_projects(projects)
    return project


def browse_dirs(raw_path: str | None) -> dict[str, Any]:
    base = Path(raw_path or Path.home()).expanduser()
    if not base.exists():
        base = base.parent if base.parent.exists() else Path.home()
    if base.is_file():
        base = base.parent
    try:
        base = base.resolve()
    except OSError:
        base = Path.home().resolve()

    dirs = []
    files = []
    try:
        for child in sorted(base.iterdir(), key=lambda item: item.name.lower()):
            if child.is_dir():
                dirs.append({"name": child.name, "path": str(child)})
            elif child.is_file():
                files.append({"name": child.name, "path": str(child)})
    except OSError:
        dirs = []
        files = []
    parent = str(base.parent) if base.parent != base else ""
    return {"path": str(base), "parent": parent, "dirs": dirs, "files": files}


def project_choices() -> list[dict[str, str]]:
    choices = [
        {
            "value": "global",
            "label": "Global",
            "root": str(Path.home()),
            "kind": "global",
        }
    ]
    seen = {str(Path.home().resolve())}
    for project in load_projects():
        key = project["root"]
        if key in seen:
            continue
        seen.add(key)
        choices.append({"value": f"project:{key}", "label": project["label"], "root": key, "kind": "project"})
    return choices


def selected_project(scope: str | None) -> dict[str, str]:
    choices = project_choices()
    for choice in choices:
        if choice["value"] == scope:
            return choice
    raw_scope = str(scope or "").strip()
    if raw_scope and raw_scope != "global":
        candidate = raw_scope.removeprefix("project:")
        try:
            candidate_root = str(Path(candidate).expanduser().resolve())
        except OSError:
            candidate_root = str(Path(candidate).expanduser())
        for choice in choices:
            if choice["kind"] == "project" and choice["root"] == candidate_root:
                return choice
    return choices[0]


@contextlib.contextmanager
def pushd(path: Path):
    old = Path.cwd()
    try:
        import os

        os.chdir(path)
        yield
    finally:
        os.chdir(old)


def content_path(content_type: str, name: str = "") -> Path:
    if content_type == "groups":
        return CONTENT_ROOT / "groups" / f"{name}.group"
    if content_type == "templates":
        return TEMPLATES_DIR / "core" / f"{name}.template"
    if content_type == "harnesses":
        return CONTENT_ROOT / "harnesses" / "core" / f"{name}.json"
    return resolve_item_path(content_type, name)


def list_names(content_type: str) -> list[str]:
    if content_type in CONTENT_TYPES:
        return get_all_type(content_type)
    base = CONTENT_ROOT / content_type
    if content_type == "groups":
        return [path.stem for path in sorted(base.glob("*.group"))]
    if content_type == "templates":
        return [path.stem for path in sorted((TEMPLATES_DIR / "core").glob("*.template"))]
    if content_type == "harnesses":
        return [path.stem for path in sorted((CONTENT_ROOT / "harnesses" / "core").glob("*.json"))]
    return []


def read_item(content_type: str, name: str) -> tuple[Path, str, dict[str, Any], str]:
    path = content_path(content_type, name)
    if content_type == "skills":
        path = path / "SKILL.md"
    raw = path.read_text(encoding="utf-8") if path.exists() else ""
    if content_type == "mcp" and path.suffix == ".json":
        try:
            data = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            data = {}
        fields = data if isinstance(data, dict) else {}
        return path, raw, fields, ""
    if content_type == "mcp" and path.suffix in {".yaml", ".yml"}:
        try:
            data = yaml.safe_load(raw) if raw.strip() else {}
        except yaml.YAMLError:
            data = {}
        fields = data if isinstance(data, dict) else {}
        return path, raw, fields, ""
    if content_type == "harnesses":
        try:
            data = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            data = {}
        fields = data if isinstance(data, dict) else {}
        return path, raw, fields, raw
    if content_type == "templates":
        try:
            data = yaml.safe_load(raw) if raw.strip() else {}
        except yaml.YAMLError:
            data = {}
        fields = data if isinstance(data, dict) else {}
        return path, raw, fields, raw
    if content_type in {"hooks", "groups"}:
        return path, raw, {}, raw
    fields, body = parse_frontmatter(raw)
    return path, raw, fields, body


def item_summary(content_type: str, name: str) -> dict[str, str]:
    try:
        path, raw, fields, body = read_item(content_type, name)
    except OSError:
        return {"name": name, "description": "", "path": ""}
    description = str(fields.get("description") or "").strip()
    if not description and content_type in {"groups", "templates"}:
        for line in raw.splitlines():
            if line.strip().startswith("#"):
                description = line.strip().lstrip("# ").strip()
                break
    if not description and content_type == "harnesses":
        description = str(fields.get("label") or "").strip()
    if not description and body:
        description = body.strip().splitlines()[0][:100]
    template_type = ""
    section_count = ""
    field_count = ""
    if content_type == "templates":
        template_type = str(fields.get("type") or "").strip()
        sections = fields.get("sections")
        section_count = str(len(sections)) if isinstance(sections, list) else "0"
        template_fields = fields.get("fields")
        field_count = str(len(template_fields)) if isinstance(template_fields, dict) else "0"
    created_at = ""
    modified_at = ""
    created_ts = 0.0
    modified_ts = 0.0
    try:
        stat = path.stat()
        created_ts = float(getattr(stat, "st_birthtime", stat.st_mtime))
        modified_ts = float(stat.st_mtime)
        created_at = format_file_date(created_ts)
        modified_at = format_file_date(modified_ts)
    except OSError:
        pass
    return {
        "name": name,
        "description": description,
        "path": str(path),
        "created_at": created_at,
        "modified_at": modified_at,
        "created_ts": str(created_ts),
        "modified_ts": str(modified_ts),
        "template_type": template_type,
        "section_count": section_count,
        "field_count": field_count,
    }


def format_file_date(timestamp: float) -> str:
    value = datetime.fromtimestamp(timestamp)
    return f"{value.day} {value.strftime('%b %y %H:%M')}"


def parse_installed_conf(path: Path) -> set[str]:
    items = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return items
    for raw in lines:
        line = raw.split("#", 1)[0].replace(" ", "").strip()
        if line:
            items.add(line)
    return items


def project_installed_paths(project_root: str, content_type: str) -> list[Path]:
    root = Path(project_root).expanduser()
    return [
        root / ".wdm" / "installed" / f"{content_type}.conf",
        root / ".ai-management" / "installed" / f"{content_type}.conf",
    ]


def install_counts(content_type: str, names: list[str]) -> dict[str, int]:
    counts = {name: 0 for name in names}
    if content_type not in CONTENT_TYPES:
        return counts
    scopes = [set(load_installed_type(content_type))]
    for project in load_projects():
        project_items: set[str] = set()
        for path in project_installed_paths(project["root"], content_type):
            project_items.update(parse_installed_conf(path))
        scopes.append(project_items)
    for name in names:
        counts[name] = sum(1 for items in scopes if name in items)
    return counts


def group_memberships(content_type: str) -> tuple[list[str], dict[str, list[str]]]:
    groups = []
    memberships: dict[str, list[str]] = {}
    if content_type not in CONTENT_TYPES:
        return groups, memberships
    for group_name in list_names("groups"):
        path = content_path("groups", group_name)
        if not path.exists():
            continue
        try:
            items = parse_group_section(path, content_type)
        except OSError:
            continue
        if not items:
            continue
        groups.append(group_name)
        for item in items:
            memberships.setdefault(item, []).append(group_name)
    return groups, memberships


def template_memberships(content_type: str) -> dict[str, list[str]]:
    memberships: dict[str, list[str]] = {}
    if content_type not in CONTENT_TYPES:
        return memberships
    for template_name in list_names("templates"):
        path = content_path("templates", template_name)
        if not path.exists():
            continue
        try:
            _, sections = parse_section_file(path)
        except OSError:
            continue
        for item in sections.get(content_type, []):
            if item == "*":
                expanded = get_all_type(content_type)
            else:
                expanded = [item]
            for name in expanded:
                memberships.setdefault(name, []).append(template_name)
        for group_name in sections.get("groups", []):
            group_file = content_path("groups", group_name)
            if not group_file.exists():
                continue
            try:
                group_items = parse_group_section(group_file, content_type)
            except OSError:
                continue
            for name in group_items:
                memberships.setdefault(name, []).append(template_name)
    return {name: sorted(set(values)) for name, values in memberships.items()}


def original_fields_from_form(form: dict[str, Any]) -> dict[str, Any]:
    raw = str(form.get("original_fields") or "").strip()
    if not raw:
        return {}
    try:
        loaded = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def reserved_form_field_keys(content_type: str) -> set[str]:
    display_keys = set(schema_field_order(content_type))
    reserved_keys = set(display_keys)
    if content_type == "agents":
        harness_model_keys = {"model"} | {f"{harness}_model" for harness in ALL_HARNESSES}
        reasoning_keys = {"reasoning"} | set(REASONING_OPTIONS) | {"thinkingBudget", "thinkingConfig"}
        for harness in ALL_HARNESSES:
            for field_name in set(REASONING_OPTIONS) | {"thinkingBudget", "thinkingConfig"}:
                reasoning_keys.add(f"{harness}_{field_name}")
        capability_keys = set(AGENT_CAPABILITY_FIELDS) | {"agent_skills", "agent_mcp_servers"}
        sandbox_keys = {"sandbox", "sandbox_mode"}
        for harness in ALL_HARNESSES:
            for field_name in AGENT_CAPABILITY_FIELDS:
                capability_keys.add(f"{harness}_{field_name}")
                if field_name == "mcp-servers":
                    capability_keys.add(f"{harness}_mcp_servers")
                if field_name == "mcp_servers":
                    capability_keys.add(f"{harness}_mcp-servers")
            sandbox_keys.update({f"{harness}_sandbox", f"{harness}_sandbox_mode"})
        reserved_keys.update(harness_model_keys | reasoning_keys | capability_keys | sandbox_keys | {"developer_instructions", "body"})
    return reserved_keys


def normalize_fields(form: dict[str, Any], original_fields: dict[str, Any] | None = None) -> dict[str, Any]:
    original_fields = original_fields or {}
    fields: dict[str, Any] = {}
    controlled_field_names: set[str] = set()
    sectioned_field_names = {
        item.strip()
        for item in str(form.get("sectioned_field_keys") or "").split(",")
        if item.strip()
    }
    for key, value in form.items():
        if not key.startswith("field_"):
            continue
        field_name = key.removeprefix("field_").strip()
        if field_name:
            controlled_field_names.add(field_name)
        if isinstance(value, list):
            if field_name in BOOLEAN_FIELD_NAMES:
                lowered = {str(item).strip().lower() for item in value}
                fields[field_name] = any(item in {"true", "1", "yes", "on"} for item in lowered)
                continue
            items = [str(item).strip() for item in value if str(item).strip()]
            if field_name and (items or field_name.startswith("agent_")):
                fields[field_name] = items
            continue
        value = str(value).strip()
        if not field_name:
            continue
        if field_name in BOOLEAN_FIELD_NAMES:
            if value:
                fields[field_name] = value.lower() in {"true", "1", "yes", "on"}
            elif field_name in original_fields:
                fields[field_name] = False
            continue
        if not value:
            if field_name in original_fields:
                if field_name in LIST_FIELD_NAMES or field_name.endswith(("_mcp_servers", "_mcp-servers")):
                    fields[field_name] = []
                elif field_name in MAPPING_FIELD_NAMES:
                    fields[field_name] = {}
                else:
                    fields[field_name] = ""
            continue
        if field_name in sectioned_field_names:
            fields[field_name] = value
        elif field_name in TEXTAREA_FIELD_NAMES:
            fields[field_name] = value
        elif field_name in LIST_FIELD_NAMES or field_name.endswith(("_mcp_servers", "_mcp-servers")):
            fields[field_name] = field_list_value(value)
        elif field_name in MAPPING_FIELD_NAMES or value.startswith(("[", "{")) or "\n" in value:
            try:
                fields[field_name] = yaml.safe_load(value)
            except yaml.YAMLError as exc:
                raise ValueError(f"{field_name} must be valid YAML: {exc}") from exc
        else:
            fields[field_name] = value
    extra = form.get("extra_fields", "").strip()
    if extra:
        loaded = yaml.safe_load(extra) or {}
        if not isinstance(loaded, dict):
            raise ValueError("Extra fields must be a YAML mapping.")
        reserved_keys = controlled_field_names | reserved_form_field_keys(str(form.get("type", "")))
        collisions = sorted(str(key) for key in loaded if str(key) in reserved_keys)
        if collisions:
            raise ValueError("Additional fields cannot reuse reserved field keys: " + ", ".join(collisions))
        fields.update(loaded)
    return fields


def supported_agent_capability_fields(capability: str) -> list[tuple[str, str]]:
    field_names = ["skills"] if capability == "skills" else ["mcp_servers"]
    supported = []
    for harness in ALL_HARNESSES:
        schema = AGENT_SCHEMAS.get(harness, [])
        if not isinstance(schema, list):
            continue
        for field_name in field_names:
            if field_name in schema or schema_supports_source_field(harness, "agents", field_name):
                supported.append((harness, field_name))
                break
        if capability == "mcp" and "mcp-servers" in schema and not any(item[0] == harness for item in supported):
            supported.append((harness, "mcp_servers"))
    return supported


def capability_storage_keys(capability: str) -> set[str]:
    keys = {"skills"} if capability == "skills" else {"mcp_servers", "mcp-servers"}
    for harness, field_name in supported_agent_capability_fields(capability):
        keys.add(f"{harness}_{field_name}")
        if field_name == "mcp-servers":
            keys.add(f"{harness}_mcp_servers")
        if field_name == "mcp_servers":
            keys.add(f"{harness}_mcp-servers")
    return keys


def capability_base_keys(capability: str) -> list[str]:
    return ["skills"] if capability == "skills" else ["mcp_servers", "mcp-servers"]


def capability_harness_storage_key(fields: dict[str, Any], harness: str, field_name: str) -> str | None:
    candidates = [f"{harness}_{field_name}"]
    if field_name == "mcp-servers":
        candidates.append(f"{harness}_mcp_servers")
    if field_name == "mcp_servers":
        candidates.append(f"{harness}_mcp-servers")
    for key in candidates:
        if key in fields:
            return key
    return None


def apply_capability_delta(original_values: list[str], selected_values: list[str], original_union: list[str]) -> list[str]:
    selected_set = set(selected_values)
    original_union_set = set(original_union)
    added = [value for value in selected_values if value not in original_union_set]
    removed = original_union_set - selected_set
    updated = [value for value in original_values if value not in removed]
    for value in added:
        if value not in updated:
            updated.append(value)
    return updated


def expand_agent_capability_fields(fields: dict[str, Any], original_fields: dict[str, Any] | None = None) -> dict[str, Any]:
    expanded = dict(fields)
    ui_fields = {
        "agent_skills": "skills",
        "agent_mcp_servers": "mcp_servers",
    }
    for ui_field, canonical_field in ui_fields.items():
        if ui_field not in expanded:
            continue
        values = field_list_value(expanded.pop(ui_field))
        expanded[canonical_field] = values
    return expanded


def normalize_agent_model_fields(fields: dict[str, Any], original_fields: dict[str, Any] | None = None) -> dict[str, Any]:
    original_fields = original_fields or {}
    normalized = dict(fields)
    model_keys = [f"{harness}_model" for harness in ALL_HARNESSES if harness_supports_agent_model(harness)]
    posted = {key: normalized.pop(key) for key in model_keys if key in normalized}
    if "model" in original_fields and "model" not in normalized:
        normalized["model"] = original_fields["model"]
    for key, value in posted.items():
        text = str(value or "").strip()
        if key in original_fields or text != "default":
            normalized[key] = text or "default"
    return normalized


def body_with_final_newline(body: str) -> str:
    return body if body.endswith("\n") else body + "\n"


def serialize_markdown(fields: dict[str, Any], body: str) -> str:
    body_text = body_with_final_newline(body)
    if not fields:
        return body_text
    dumped = yaml.safe_dump(fields, sort_keys=False, allow_unicode=False).strip()
    return f"---\n{dumped}\n---\n{body_text}"


def parse_hook_script(raw: str) -> dict[str, str]:
    lines = raw.splitlines()
    shebang = "#!/usr/bin/env bash"
    if lines and lines[0].startswith("#!"):
        shebang = lines.pop(0).strip()
    description_lines: list[str] = []
    while lines and lines[0].startswith("#") and not lines[0].startswith("#!"):
        text = lines.pop(0)[1:]
        description_lines.append(text[1:] if text.startswith(" ") else text)
    while lines and not lines[0].strip():
        lines.pop(0)
    return {
        "shebang": shebang,
        "description": "\n".join(description_lines).strip(),
        "script": "\n".join(lines).rstrip() + ("\n" if lines else ""),
    }


def serialize_hook_script(form: dict[str, Any]) -> str:
    shebang = str(form.get("hook_shebang") or "#!/usr/bin/env bash").strip()
    if not shebang.startswith("#!"):
        shebang = "#!" + shebang.lstrip("# ")
    description = str(form.get("hook_description") or "").strip()
    script = str(form.get("hook_script") or "").rstrip()
    lines = [shebang]
    if description:
        lines.extend(f"# {line}".rstrip() for line in description.splitlines())
    if script:
        lines.append(script)
    return "\n".join(lines).rstrip() + "\n"


def hook_template_fields_from_form(form: dict[str, Any]) -> dict[str, str]:
    return {
        "hook_shebang": str(form.get("hook_shebang") or "#!/usr/bin/env bash").strip(),
        "hook_description": str(form.get("hook_description") or "").strip(),
        "hook_script": str(form.get("hook_script") or "").rstrip(),
    }


HARNESS_SCHEMA_TYPES = ("agents", "skills", "mcp", "rules", "workflows", "hooks")
HARNESS_FORM_HANDLED_KEYS = {
    "name",
    "label",
    "builtin",
    "default_enabled",
    "auto_enable",
    "detect",
    "renderers",
    "schemas",
    "field_mappings",
    "models",
    "outputs",
    "sync",
}


def harness_json_object(value: Any, label: str) -> dict[str, Any]:
    raw = str(value or "").strip()
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must be valid JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError(f"{label} must be a JSON object.")
    return loaded


def harness_list_value(value: Any) -> list[str]:
    return field_list_value(value)


def harness_original_definition(form: dict[str, Any]) -> dict[str, Any]:
    original = harness_json_object(form.get("original_raw") or "{}", "Original harness JSON")
    return json.loads(json.dumps(original))


def harness_definition_from_form(form: dict[str, Any]) -> dict[str, Any]:
    data = harness_original_definition(form)
    name = str(form.get("name") or form.get("original_name") or "").strip()
    if not name:
        raise ValueError("Name is required.")
    data["name"] = name

    label = str(form.get("harness_label") or "").strip()
    if label:
        data["label"] = label
    else:
        data.pop("label", None)

    for form_key, json_key in (
        ("harness_builtin", "builtin"),
        ("harness_default_enabled", "default_enabled"),
        ("harness_auto_enable", "auto_enable"),
    ):
        raw_value = str(form.get(form_key) or "").strip().lower()
        value = raw_value in {"true", "1", "yes", "on"}
        if json_key in data or value:
            data[json_key] = value

    detect = dict(data.get("detect") or {}) if isinstance(data.get("detect"), dict) else {}
    commands = harness_list_value(form.get("harness_detect_commands"))
    paths = harness_list_value(form.get("harness_detect_paths"))
    if commands or "commands" in detect:
        detect["commands"] = commands
    if paths or "paths" in detect:
        detect["paths"] = paths
    if detect:
        data["detect"] = detect
    else:
        data.pop("detect", None)

    renderers = dict(data.get("renderers") or {}) if isinstance(data.get("renderers"), dict) else {}
    for renderer_key, form_key in (("agents", "harness_renderer_agents"), ("mcp", "harness_renderer_mcp")):
        renderer = str(form.get(form_key) or "").strip()
        if renderer:
            renderers[renderer_key] = renderer
        elif renderer_key in renderers:
            renderers.pop(renderer_key, None)
    if renderers:
        data["renderers"] = renderers
    else:
        data.pop("renderers", None)

    schemas = dict(data.get("schemas") or {}) if isinstance(data.get("schemas"), dict) else {}
    for schema_type in HARNESS_SCHEMA_TYPES:
        values = harness_list_value(form.get(f"harness_schema_{schema_type}"))
        if values or schema_type in schemas:
            schemas[schema_type] = values
    if schemas:
        data["schemas"] = schemas
    else:
        data.pop("schemas", None)

    field_mappings = harness_json_object(form.get("harness_field_mappings_json"), "Field mappings")
    if field_mappings or "field_mappings" in data:
        data["field_mappings"] = field_mappings

    models = dict(data.get("models") or {}) if isinstance(data.get("models"), dict) else {}
    agent_models = harness_list_value(form.get("harness_models_agents"))
    if agent_models or "agents" in models:
        models["agents"] = agent_models
    if models:
        data["models"] = models
    else:
        data.pop("models", None)

    outputs = harness_json_object(form.get("harness_outputs_json"), "Outputs")
    if outputs or "outputs" in data:
        data["outputs"] = outputs

    sync = dict(data.get("sync") or {}) if isinstance(data.get("sync"), dict) else {}
    for form_key, json_key in (
        ("harness_sync_project_root", "project_root"),
        ("harness_sync_global_root", "global_root"),
    ):
        value = str(form.get(form_key) or "").strip()
        if value or json_key in sync:
            if value:
                sync[json_key] = value
            else:
                sync.pop(json_key, None)
    flat_paths = harness_json_object(form.get("harness_sync_flat_paths_json"), "Default sync paths")
    project_paths = harness_json_object(form.get("harness_sync_project_paths_json"), "Project sync paths")
    global_paths = harness_json_object(form.get("harness_sync_global_paths_json"), "Global sync paths")
    paths: dict[str, Any] = {}
    paths.update(flat_paths)
    if project_paths:
        paths["project"] = project_paths
    if global_paths:
        paths["global"] = global_paths
    if paths or "paths" in sync:
        sync["paths"] = paths
    skip = harness_json_object(form.get("harness_sync_skip_json"), "Sync skip")
    if skip or "skip" in sync:
        sync["skip"] = skip
    if sync:
        data["sync"] = sync
    else:
        data.pop("sync", None)

    extra = harness_json_object(form.get("harness_extra_json"), "Additional harness fields")
    for key in HARNESS_FORM_HANDLED_KEYS:
        extra.pop(key, None)
    data.update(extra)
    return data


def raw_from_form_state(form: dict[str, Any]) -> tuple[str, Path]:
    content_type = form.get("type", "")
    name = form.get("name", "").strip() or form.get("original_name", "").strip() or "new"
    suffix = form.get("original_suffix", "")
    if form.get("editor_view") == "file":
        path = content_path(content_type, name)
        if content_type == "skills":
            path = path / "SKILL.md"
        elif content_type == "mcp" and suffix in {".json", ".yaml", ".yml", ".md"}:
            path = content_source_dir("mcp") / f"{name}{suffix}"
        return form.get("raw", ""), path

    if content_type == "templates":
        definition = template_definition_from_form(form)
        definition["name"] = name
        return dump_template_definition(definition), template_definition_path(name)
    if content_type == "harnesses":
        definition = harness_definition_from_form(form)
        return json.dumps(definition, indent=2, ensure_ascii=True).rstrip() + "\n", content_path("harnesses", name)

    original_fields = original_fields_from_form(form)
    fields = normalize_fields(form, original_fields)
    if content_type == "agents":
        fields = normalize_agent_model_fields(fields, original_fields)
        fields = expand_agent_capability_fields(fields, original_fields)
    if content_type == "skills":
        return serialize_markdown(fields, form.get("body", "")), content_source_dir("skills") / name / "SKILL.md"
    if content_type == "hooks":
        return serialize_hook_script(form), content_source_dir("hooks") / name
    if content_type == "mcp" and suffix == ".json":
        raw = json.dumps(fields, indent=2, ensure_ascii=True).rstrip() + "\n"
        return raw, content_source_dir("mcp") / f"{name}{suffix}"
    if content_type == "mcp" and suffix in {".yaml", ".yml"}:
        raw = yaml.safe_dump(fields, sort_keys=False, allow_unicode=False).strip() + "\n"
        return raw, content_source_dir("mcp") / f"{name}{suffix}"
    return serialize_markdown(fields, form.get("body", "")), content_source_dir(content_type) / f"{name}.md"


def parse_frontmatter_strict(content: str) -> tuple[dict[str, Any], str]:
    if not content.startswith("---"):
        return {}, content
    end = content.find("\n---", 3)
    if end == -1:
        raise ValueError("Markdown frontmatter is missing a closing --- line.")
    fm_text = content[4:end]
    body = content[end + 4:]
    if body.startswith("\n"):
        body = body[1:]
    loaded = yaml.safe_load(fm_text) or {}
    if not isinstance(loaded, dict):
        raise ValueError("Markdown frontmatter must be a YAML mapping.")
    return loaded, body


def validate_form_state(form: dict[str, Any]) -> None:
    raw, path = raw_from_form_state(form)
    if form.get("target_view") != "form":
        return
    content_type = form.get("type", "")
    if content_type == "templates":
        template_definition_from_raw(raw, form.get("name", ""))
        return
    if content_type == "harnesses":
        loaded = json.loads(raw) if raw.strip() else {}
        if not isinstance(loaded, dict):
            raise ValueError("Harness config must be a JSON object.")
        return
    if content_type == "mcp" and path.suffix == ".json":
        loaded = json.loads(raw) if raw.strip() else {}
        if not isinstance(loaded, dict):
            raise ValueError("JSON MCP source must be an object.")
        return
    if content_type == "mcp" and path.suffix in {".yaml", ".yml"}:
        loaded = yaml.safe_load(raw) if raw.strip() else {}
        if not isinstance(loaded, dict):
            raise ValueError("YAML MCP source must be a mapping.")
        return
    if content_type not in {"agents", "skills", "rules", "workflows", "mcp"}:
        return
    parse_frontmatter_strict(raw)


def save_item(form: dict[str, str]) -> str:
    content_type = form.get("type", "")
    original_name = form.get("original_name", "").strip()
    name = form.get("name", "").strip()
    if content_type not in EDITABLE_TYPES:
        raise ValueError(f"Unsupported type: {content_type}")
    if not name:
        raise ValueError("Name is required.")
    if form.get("editor_view") == "file":
        return save_raw_item(content_type, original_name, name, form)

    if content_type == "groups":
        path = CONTENT_ROOT / "groups" / f"{name}.group"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(form.get("raw", "").rstrip() + "\n", encoding="utf-8")
        maybe_remove_renamed(content_type, original_name, name)
        return name

    if content_type == "templates":
        path = template_definition_path(name)
        definition = template_definition_from_form(form)
        definition["name"] = name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump_template_definition(definition), encoding="utf-8")
        maybe_remove_renamed(content_type, original_name, name)
        return name

    if content_type == "harnesses":
        path = content_path("harnesses", name)
        definition = harness_definition_from_form(form)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(definition, indent=2, ensure_ascii=True).rstrip() + "\n", encoding="utf-8")
        maybe_remove_renamed(content_type, original_name, name)
        refresh_harness_runtime()
        return name

    if content_type == "skills":
        path = content_source_dir("skills") / name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        original_fields = original_fields_from_form(form)
        fields = normalize_fields(form, original_fields)
        path.write_text(serialize_markdown(fields, form.get("body", "")), encoding="utf-8")
        maybe_remove_renamed(content_type, original_name, name)
        return name

    if content_type == "hooks":
        path = content_source_dir("hooks") / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialize_hook_script(form), encoding="utf-8")
        maybe_remove_renamed(content_type, original_name, name)
        return name

    if content_type == "mcp" and form.get("mcp_format") == "json":
        path = content_source_dir("mcp") / f"{name}.json"
        json.loads(form.get("raw", "{}") or "{}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(form.get("raw", "").rstrip() + "\n", encoding="utf-8")
        maybe_remove_renamed(content_type, original_name, name)
        return name

    original_suffix = form.get("original_suffix", "")
    if content_type == "mcp" and original_suffix == ".json":
        path = content_source_dir("mcp") / f"{name}{original_suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        original_fields = original_fields_from_form(form)
        fields = normalize_fields(form, original_fields)
        path.write_text(json.dumps(fields, indent=2, ensure_ascii=True).rstrip() + "\n", encoding="utf-8")
        maybe_remove_renamed(content_type, original_name, name)
        return name
    if content_type == "mcp" and original_suffix in {".yaml", ".yml"}:
        path = content_source_dir("mcp") / f"{name}{original_suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        original_fields = original_fields_from_form(form)
        fields = normalize_fields(form, original_fields)
        path.write_text(yaml.safe_dump(fields, sort_keys=False, allow_unicode=False).strip() + "\n", encoding="utf-8")
        maybe_remove_renamed(content_type, original_name, name)
        return name

    path = content_source_dir(content_type) / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    original_fields = original_fields_from_form(form)
    fields = normalize_fields(form, original_fields)
    if content_type == "agents":
        fields = normalize_agent_model_fields(fields, original_fields)
        fields = expand_agent_capability_fields(fields, original_fields)
    path.write_text(serialize_markdown(fields, form.get("body", "")), encoding="utf-8")
    maybe_remove_renamed(content_type, original_name, name)
    return name


def unique_template_name(raw_name: str) -> str:
    base = normalize_template_slug(raw_name)
    candidate = base
    index = 2
    while template_definition_path(candidate).exists():
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def field_sections_from_item_form(form: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    keys = [
        key.strip()
        for key in str(form.get("sectioned_field_keys") or "").split(",")
        if key.strip()
    ]
    for key in keys:
        raw_value = str(form.get(f"field_{key}") or "")
        sections = []
        for section in split_body_sections(raw_value):
            title = str(section.get("title") or "").strip()
            content = str(section.get("content") or "")
            if not title and not content.strip():
                continue
            sections.append(
                {
                    "title": title or "Overview",
                    "level": template_level_value(section.get("level"), 2),
                    "content": content,
                }
            )
        if sections:
            result[key] = {
                "label": key.replace("_", " ").replace("-", " ").title(),
                "sections": sections,
            }
    return result


def save_template_from_item(form: dict[str, Any]) -> dict[str, Any]:
    content_type = str(form.get("type") or "").strip()
    if content_type not in TEMPLATE_TARGET_TYPES:
        raise ValueError(f"{content_type or 'This type'} does not support body templates.")
    raw_name = str(form.get("template_name") or "").strip()
    if not raw_name:
        raise ValueError("Template name is required.")
    name = unique_template_name(raw_name)
    sections = []
    field_sections: dict[str, dict[str, Any]] = {}
    if content_type == "hooks":
        fields = hook_template_fields_from_form(form)
    else:
        original_fields = original_fields_from_form(form)
        fields = normalize_fields(form, original_fields)
        if content_type == "agents":
            fields = normalize_agent_model_fields(fields, original_fields)
            fields = expand_agent_capability_fields(fields, original_fields)
        fields.pop("name", None)
        body = str(form.get("body") or "")
        has_body_editor = "body" in form
        if has_body_editor:
            for section in split_body_sections(body):
                title = str(section.get("title") or "").strip()
                content = str(section.get("content") or "")
                if not title and not content.strip():
                    continue
                if not title:
                    title = "Overview"
                sections.append(
                    {
                        "title": title,
                        "level": template_level_value(section.get("level"), 2),
                        "content": content,
                    }
                )
        if not sections and content_type not in SECTIONLESS_TEMPLATE_TYPES:
            raise ValueError("Add at least one body section before saving a template.")
        field_sections = field_sections_from_item_form(form)
    definition = {
        "name": name,
        "type": content_type,
        "description": f"Saved from {str(form.get('name') or form.get('original_name') or content_type).strip() or content_type}.",
        "fields": fields,
        "sections": sections,
        "field_sections": field_sections,
    }
    path = template_definition_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_template_definition(definition), encoding="utf-8")
    return {
        "name": name,
        "fields": fields,
        "sections": [(section["title"], str(section["level"]), section["content"]) for section in sections],
        "field_sections": field_sections,
    }


def save_raw_item(content_type: str, original_name: str, name: str, form: dict[str, str]) -> str:
    suffix = form.get("original_suffix", "")
    if content_type == "groups":
        path = CONTENT_ROOT / "groups" / f"{name}.group"
    elif content_type == "templates":
        path = template_definition_path(name)
    elif content_type == "skills":
        path = content_source_dir("skills") / name / "SKILL.md"
    elif content_type == "hooks":
        path = content_source_dir("hooks") / name
    elif content_type == "mcp":
        if suffix not in {".json", ".yaml", ".yml", ".md"}:
            suffix = ".md"
        path = content_source_dir("mcp") / f"{name}{suffix}"
    elif content_type == "harnesses":
        path = CONTENT_ROOT / "harnesses" / "core" / f"{name}.json"
    else:
        path = content_source_dir(content_type) / f"{name}.md"

    raw = form.get("raw", "")
    if path.suffix == ".json":
        json.loads(raw or "{}")
    if content_type == "templates":
        definition = template_definition_from_raw(raw, name)
        definition["name"] = name
        raw = yaml.safe_dump(definition, sort_keys=False, allow_unicode=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw.rstrip() + "\n", encoding="utf-8")
    maybe_remove_renamed(content_type, original_name, name)
    if content_type == "harnesses":
        refresh_harness_runtime()
    return name


def imported_name_from_source(content_type: str, raw_name: str, source_hint: str) -> str:
    candidate = str(raw_name or "").strip()
    if not candidate:
        hint = urllib.parse.urlparse(source_hint).path if source_hint.startswith(("http://", "https://")) else source_hint
        path = Path(urllib.parse.unquote(hint))
        if content_type == "skills" and path.name == "SKILL.md":
            candidate = path.parent.name
        else:
            candidate = path.stem or path.name
    return normalize_template_slug(candidate or f"imported-{singular_type(content_type)}")


def import_suffix_for_source(content_type: str, source_hint: str, file_name: str = "") -> str:
    suffix = Path(urllib.parse.urlparse(source_hint).path or file_name).suffix.lower()
    if content_type == "mcp" and suffix in {".json", ".yaml", ".yml", ".md"}:
        return suffix
    if content_type == "templates":
        return ".template"
    if content_type == "harnesses":
        return ".json"
    if content_type == "groups":
        return ".group"
    if content_type in {"hooks", "skills"}:
        return ""
    return ".md"


def read_import_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Import URL must start with http:// or https://.")
    request = urllib.request.Request(url, headers={"User-Agent": "AI-Management-Importer/1.0"})
    with urllib.request.urlopen(request, timeout=12) as response:
        data = response.read(IMPORT_MAX_BYTES + 1)
    if len(data) > IMPORT_MAX_BYTES:
        raise ValueError("Imported content is larger than 3MB.")
    return data.decode("utf-8")


def read_import_path(raw_path: str, content_type: str) -> tuple[str, str]:
    path = Path(raw_path).expanduser()
    if path.is_dir() and content_type == "skills":
        path = path / "SKILL.md"
    if not path.exists() or not path.is_file():
        raise ValueError("Import path must point to a readable file.")
    data = path.read_bytes()
    if len(data) > IMPORT_MAX_BYTES:
        raise ValueError("Imported content is larger than 3MB.")
    return data.decode("utf-8"), str(path)


def unique_import_name(content_type: str, base_name: str) -> str:
    base = normalize_template_slug(base_name)
    candidate = base
    index = 2
    while content_path(content_type, candidate).exists():
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def import_item(form: dict[str, str]) -> str:
    content_type = str(form.get("type") or "").strip()
    if content_type not in EDITABLE_TYPES:
        raise ValueError(f"Unsupported type: {content_type}")
    source = str(form.get("import_source") or "paste").strip()
    source_hint = ""
    file_name = str(form.get("import_file_name") or "").strip()
    if source == "url":
        source_hint = str(form.get("import_url") or "").strip()
        raw = read_import_url(source_hint)
    elif source == "path":
        raw, source_hint = read_import_path(str(form.get("import_path") or "").strip(), content_type)
    elif source == "file":
        raw = str(form.get("import_raw") or "")
        source_hint = file_name
    else:
        raw = str(form.get("import_raw") or "")
        source_hint = file_name or "pasted-content"
    if not raw.strip():
        raise ValueError("Import content is empty.")
    name = unique_import_name(content_type, imported_name_from_source(content_type, form.get("name", ""), source_hint))
    suffix = import_suffix_for_source(content_type, source_hint, file_name)
    save_raw_item(content_type, "", name, {"raw": raw, "original_suffix": suffix})
    return name


def duplicate_item(content_type: str, name: str) -> str:
    if content_type not in EDITABLE_TYPES:
        raise ValueError(f"Unsupported type: {content_type}")
    if not name:
        raise ValueError("Name is required.")
    path, raw, _, _ = read_item(content_type, name)
    if not raw.strip() and not path.exists():
        raise ValueError(f"Item not found: {name}")
    duplicate_name = unique_import_name(content_type, f"{name}-copy")
    suffix = path.suffix
    if content_type == "skills":
        suffix = ""
    save_raw_item(content_type, "", duplicate_name, {"raw": raw, "original_suffix": suffix})
    return duplicate_name


def set_harness_enabled(name: str, enabled: bool) -> None:
    path = content_path("harnesses", name)
    if not path.exists():
        raise ValueError(f"Harness not found: {name}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Harness config is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Harness config must be a JSON object.")
    data["enabled"] = bool(enabled)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True).rstrip() + "\n", encoding="utf-8")
    refresh_harness_runtime()


def maybe_remove_renamed(content_type: str, old: str, new: str) -> None:
    if not old or old == new:
        return
    old_path = content_path(content_type, old)
    if content_type == "skills":
        old_path = old_path / "SKILL.md"
    if old_path.exists():
        old_path.unlink()


def delete_item(content_type: str, name: str) -> None:
    name = name.strip()
    if content_type not in EDITABLE_TYPES:
        raise ValueError(f"Unsupported type: {content_type}")
    if not name:
        raise ValueError("Name is required.")
    path = content_path(content_type, name)
    if content_type == "skills":
        if path.exists():
            shutil.rmtree(path)
    elif path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()
    else:
        raise ValueError(f"{name} was not found.")
    if content_type in CONTENT_TYPES:
        items = [item for item in load_installed_type(content_type) if item != name]
        save_installed_type(content_type, items)


def safe_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def external_name_from_path(harness: str, path: Path) -> str:
    if harness == "copilot" and path.name.endswith(".agent.md"):
        return path.name.removesuffix(".agent.md")
    return path.stem


def external_description(raw: str, harness: str) -> str:
    if harness == "codex":
        match = re.search(r'^\s*description\s*=\s*"([^"]+)"', raw, re.MULTILINE)
        if match:
            return match.group(1).strip()
    fields, body = parse_frontmatter(raw)
    description = str(fields.get("description") or "").strip()
    if description:
        return description
    for line in body.splitlines() if body else raw.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:140]
    return ""


def has_frontmatter(raw: str) -> bool:
    return raw.startswith("---\n") and "\n---\n" in raw[4:]


def app_managed_target(path: Path) -> bool:
    if not path.is_symlink():
        return False
    try:
        return path.resolve().relative_to(CONTENT_ROOT.resolve()) is not None
    except (OSError, ValueError):
        return False


def external_item_candidates(content_type: str, scope: str) -> list[dict[str, Any]]:
    if content_type != "agents":
        return []
    root = scoped_target_root(scope)
    global_mode = is_global_scope(scope)
    specs = [
        ("codex", root / ".codex" / "agents", "*.toml"),
        ("claude", root / ".claude" / "agents", "*.md"),
        ("gemini", root / ".gemini" / "agents", "*.md"),
        ("copilot", (root / ".copilot" if global_mode else root / ".github") / "agents", "*.agent.md"),
    ]
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for harness, directory, pattern in specs:
        for path in sorted(directory.glob(pattern)):
            if not path.is_file() and not path.is_symlink():
                continue
            if app_managed_target(path):
                continue
            name = external_name_from_path(harness, path).strip()
            if not name:
                continue
            key = (content_type, harness, name)
            if key in seen:
                continue
            seen.add(key)
            try:
                raw = path.read_text(encoding="utf-8")
            except OSError:
                raw = ""
            try:
                stat = path.stat()
                created_ts = float(getattr(stat, "st_birthtime", stat.st_mtime))
                modified_ts = float(stat.st_mtime)
            except OSError:
                created_ts = 0.0
                modified_ts = 0.0
            definition = HARNESS_DEFINITIONS.get(harness, {})
            label = str(definition.get("label") or harness).strip()
            items.append(
                {
                    "name": name,
                    "harness": harness,
                    "harness_label": label,
                    "path": str(path),
                    "description": external_description(raw, harness),
                    "source_exists": content_path(content_type, name).exists(),
                    "created_at": format_file_date(created_ts) if created_ts else "",
                    "modified_at": format_file_date(modified_ts) if modified_ts else "",
                    "created_ts": str(created_ts),
                    "modified_ts": str(modified_ts),
                }
            )
    return sorted(items, key=lambda item: (str(item["harness_label"]).casefold(), str(item["name"]).casefold()))


def external_item_from_path(content_type: str, harness: str, raw_path: str, scope: str) -> dict[str, Any]:
    if content_type != "agents":
        raise ValueError("External files are currently supported for agents.")
    if harness not in ALL_HARNESSES:
        raise ValueError("Unsupported harness.")
    requested = Path(raw_path).expanduser()
    try:
        resolved = requested.resolve()
    except OSError as exc:
        raise ValueError("External file was not found.") from exc
    root = scoped_target_root(scope)
    if not safe_relative_to(resolved, root):
        raise ValueError("External file must be inside the selected project.")
    for item in external_item_candidates(content_type, scope):
        if item.get("harness") != harness:
            continue
        try:
            candidate = Path(str(item.get("path") or "")).resolve()
        except OSError:
            continue
        if candidate == resolved:
            return item
    raise ValueError("External file is not available for this project and harness.")


def rendered_preview_external_item(content_type: str, harness: str, raw_path: str, scope: str) -> str:
    item = external_item_from_path(content_type, harness, raw_path, scope)
    path = Path(str(item["path"]))
    raw = path.read_text(encoding="utf-8")
    label = str(item.get("harness_label") or harness)
    return f"""<div class="rendered-preview external-rendered-preview">
  {render_external_preview_harness_selector(content_type, str(item.get("name") or ""), scope, harness, str(path))}
  <section class="rendered-preview-section">
    <h3>{escape(label)}</h3>
    <p class="external-preview-path">{escape(path)}</p>
    {render_preview_content(raw, path.suffix)}
  </section>
</div>"""


def render_external_preview_harness_selector(content_type: str, name: str, scope: str, selected_harness: str, path: str) -> str:
    options = []
    for harness in ALL_HARNESSES:
        selected = " selected" if harness == selected_harness else ""
        disabled = "" if harness == selected_harness else " disabled"
        options.append(
            f'<option value="{escape(harness)}"{selected}{disabled}>{escape(preview_harness_label(harness))}</option>'
        )
    return f"""<div class="preview-harness-row">
  <label>
    <span>Harness</span>
    <select data-external-preview-harness-select data-external-type="{escape(content_type)}" data-external-name="{escape(name)}" data-external-path="{escape(path)}" data-external-scope="{escape(scope)}">
      {"".join(options)}
    </select>
  </label>
</div>"""


def save_external_item(form: dict[str, str]) -> None:
    item = external_item_from_path(
        form.get("type", "agents"),
        form.get("harness", ""),
        form.get("path", ""),
        form.get("scope", "global"),
    )
    path = Path(str(item["path"]))
    path.write_text(form.get("raw", "").rstrip() + "\n", encoding="utf-8")


def import_external_item(form: dict[str, str]) -> str:
    content_type = form.get("type", "agents").strip()
    if content_type != "agents":
        raise ValueError("External import is currently supported for agents.")
    scope = form.get("scope", "global")
    root = scoped_target_root(scope)
    source_path = Path(form.get("path", "")).expanduser()
    if not source_path.exists() or not source_path.is_file():
        raise ValueError("External file was not found.")
    if not safe_relative_to(source_path, root):
        raise ValueError("External file must be inside the selected project.")
    harness = form.get("harness", "").strip()
    if harness not in ALL_HARNESSES:
        raise ValueError("Unsupported harness.")
    name = form.get("name", "").strip() or external_name_from_path(harness, source_path)
    if not name:
        raise ValueError("Name is required.")
    destination = content_source_dir(content_type) / f"{name}.md"
    if destination.exists():
        raise ValueError(f"{name} is already managed by this app.")
    raw = source_path.read_text(encoding="utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source_path.suffix == ".md" and has_frontmatter(raw):
        managed = raw.rstrip() + "\n"
    else:
        description = external_description(raw, harness) or f"Imported {harness} agent."
        fields = {
            "name": name,
            "description": description,
            "imported_from": str(source_path),
            "imported_harness": harness,
        }
        language = "toml" if source_path.suffix == ".toml" else "markdown"
        body = f"Imported from `{source_path}`.\n\n```{language}\n{raw.rstrip()}\n```"
        managed = serialize_markdown(fields, body)
    destination.write_text(managed, encoding="utf-8")
    installed = load_installed_type(content_type)
    if name not in installed:
        save_installed_type(content_type, installed + [name])
    return name


def preview_item(content_type: str, name: str) -> str:
    if content_type not in PREVIEW_TYPES:
        return "Preview is available for agents, skills, rules, workflows, and MCP servers."
    path, raw, fields, body = read_item(content_type, name)
    defaults = load_defaults(DEFAULTS_FILE) if DEFAULTS_FILE.exists() else {}
    chunks = []
    if content_type == "agents":
        for harness in ALL_HARNESSES:
            if harness == "codex":
                rendered = build_codex_agent_toml(fields, body, defaults=defaults, source_name=str(path))
            else:
                rendered = build_md_file(fields, body, harness, AGENT_SCHEMAS.get(harness, []), defaults=defaults, content_type="agents")
            chunks.append(f"## {harness}\n\n{rendered or ''}".rstrip())
    elif content_type == "skills":
        for harness in ALL_HARNESSES:
            rendered = build_md_file(fields, body, harness, SKILL_SCHEMAS.get(harness, []), defaults=defaults, content_type="skills")
            chunks.append(f"## {harness}\n\n{rendered or ''}".rstrip())
    else:
        chunks.append(raw)
    return "\n\n".join(chunks)


def preview_harness_label(harness: str) -> str:
    definition = HARNESS_DEFINITIONS.get(harness, {})
    return str(definition.get("label") or harness).strip()


def selected_preview_harness(content_type: str, name: str, scope: str, requested: str) -> str:
    statuses = harness_item_statuses(content_type, name, scope) if content_type in CONTENT_TYPES else {}
    if requested in ALL_HARNESSES:
        return requested
    for harness in ALL_HARNESSES:
        status = statuses.get(harness, {})
        if status.get("supported") and status.get("checked"):
            return harness
    for harness in ALL_HARNESSES:
        if statuses.get(harness, {}).get("supported"):
            return harness
    return ALL_HARNESSES[0] if ALL_HARNESSES else ""


def render_preview_harness_selector(content_type: str, name: str, scope: str, selected_harness: str) -> str:
    if content_type not in CONTENT_TYPES or content_type not in {"agents", "skills"}:
        return ""
    statuses = harness_item_statuses(content_type, name, scope)
    options = []
    for harness in ALL_HARNESSES:
        status = statuses.get(harness, {})
        selected = " selected" if harness == selected_harness else ""
        disabled = "" if status.get("supported") else " disabled"
        options.append(
            f'<option value="{escape(harness)}"{selected}{disabled}>{escape(preview_harness_label(harness))}</option>'
        )
    return f"""<div class="preview-harness-row">
  <label>
    <span>Harness</span>
    <select data-preview-harness-select data-preview-type="{escape(content_type)}" data-preview-name="{escape(name)}" data-preview-scope="{escape(scope)}">
      {"".join(options)}
    </select>
  </label>
</div>"""


def rendered_preview_item(content_type: str, name: str, scope: str = "global", requested_harness: str = "") -> str:
    if content_type not in PREVIEW_TYPES:
        return '<div class="rendered-preview"><p>Preview is available for agents, skills, rules, workflows, and MCP servers.</p></div>'
    path, raw, fields, body = read_item(content_type, name)
    defaults = load_defaults(DEFAULTS_FILE) if DEFAULTS_FILE.exists() else {}
    if content_type == "agents":
        harness = selected_preview_harness(content_type, name, scope, requested_harness)
        if harness == "codex":
            rendered = build_codex_agent_toml(fields, body, defaults=defaults, source_name=str(path))
            section = render_preview_section(harness, rendered or "", "toml")
        else:
            rendered = build_md_file(fields, body, harness, AGENT_SCHEMAS.get(harness, []), defaults=defaults, content_type="agents")
            section = render_preview_section(harness, rendered or "", "markdown")
        return f'<div class="rendered-preview">{render_preview_harness_selector(content_type, name, scope, harness)}{section}</div>'
    if content_type == "skills":
        harness = selected_preview_harness(content_type, name, scope, requested_harness)
        rendered = build_md_file(fields, body, harness, SKILL_SCHEMAS.get(harness, []), defaults=defaults, content_type="skills")
        section = render_preview_section(harness, rendered or "", "markdown")
        return f'<div class="rendered-preview">{render_preview_harness_selector(content_type, name, scope, harness)}{section}</div>'
    return f'<div class="rendered-preview">{render_preview_content(raw, path.suffix)}</div>'


def render_preview_section(harness: str, content: str, format_hint: str) -> str:
    definition = HARNESS_DEFINITIONS.get(harness, {})
    label = str(definition.get("label") or harness).strip()
    return f"""<section class="rendered-preview-section">
  <h3>{escape(label)}</h3>
  {render_preview_content(content, format_hint)}
</section>"""


def render_preview_content(content: str, format_hint: str = "") -> str:
    text = content or ""
    hint = format_hint.lower().lstrip(".")
    if not text.strip():
        return '<p class="rendered-empty">No preview content.</p>'
    if hint in {"html", "htm"} or looks_like_html(text):
        return render_html_preview(text)
    if hint == "json" or looks_like_json(text):
        return render_code_preview(pretty_json(text), "json")
    if hint in {"toml"}:
        return render_toml_preview(text)
    if hint in {"yaml", "yml"}:
        return render_code_preview(text, "yaml")
    if hint in {"markdown", "md"} or looks_like_markdown(text):
        return render_markdown_document(text)
    return render_code_preview(text, "text")


def render_html_preview(content: str) -> str:
    return f'<iframe class="rendered-html-frame" sandbox srcdoc="{escape(content)}"></iframe>'


def render_code_preview(content: str, language: str) -> str:
    return f'<pre class="rendered-code language-{escape(language)}"><code>{escape(content)}</code></pre>'


def render_toml_preview(content: str) -> str:
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return render_code_preview(content, "toml")
    if not isinstance(data, dict) or not data:
        return render_code_preview(content, "toml")
    instruction_keys = ["developer_instructions", "instructions"]
    instructions = find_instruction_value(data, instruction_keys)
    fields = {}
    for key, value in data.items():
        if key in instruction_keys and isinstance(value, str):
            continue
        fields[key] = strip_instruction_fields(value, instruction_keys)
    rows = []
    for key, value in fields.items():
        rows.append(f"<dt>{escape(humanize_field_name(key))}</dt><dd>{render_structured_value(value)}</dd>")
    fields_html = (
        f'<dl class="rendered-structured-fields">{"".join(rows)}</dl>'
        if rows
        else '<p class="rendered-empty">No metadata fields.</p>'
    )
    instructions_html = ""
    if instructions.strip():
        instructions_html = f"""<section class="rendered-instructions">
  <h4>Instructions</h4>
  {render_markdown_document(instructions)}
</section>"""
    return f'<div class="rendered-structured">{fields_html}{instructions_html}</div>'


def find_instruction_value(value: Any, instruction_keys: list[str]) -> str:
    if not isinstance(value, dict):
        return ""
    for key in instruction_keys:
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return item
    for item in value.values():
        nested = find_instruction_value(item, instruction_keys)
        if nested:
            return nested
    return ""


def strip_instruction_fields(value: Any, instruction_keys: list[str]) -> Any:
    if isinstance(value, dict):
        return {
            key: strip_instruction_fields(item, instruction_keys)
            for key, item in value.items()
            if key not in instruction_keys
        }
    if isinstance(value, list):
        return [strip_instruction_fields(item, instruction_keys) for item in value]
    return value


def humanize_field_name(key: str) -> str:
    return FIELD_LABELS.get(key, key.replace("_", " ").replace("-", " ").strip().title())


def render_structured_value(value: Any) -> str:
    if isinstance(value, bool):
        return f'<span class="rendered-value-pill">{escape(str(value).lower())}</span>'
    if isinstance(value, (int, float)):
        return f'<code>{escape(value)}</code>'
    if isinstance(value, str):
        return markdown_inline(value) if looks_like_markdown(value) else escape(value)
    if isinstance(value, list) and all(not isinstance(item, (dict, list)) for item in value):
        if not value:
            return '<span class="rendered-muted">Empty list</span>'
        return '<div class="rendered-value-list">' + "".join(
            f'<span class="rendered-value-pill">{escape(item)}</span>' for item in value
        ) + "</div>"
    try:
        dumped = yaml.safe_dump(value, sort_keys=False).strip()
    except yaml.YAMLError:
        dumped = str(value)
    return f'<pre class="rendered-yaml-value"><code>{escape(dumped)}</code></pre>'


def pretty_json(content: str) -> str:
    try:
        return json.dumps(json.loads(content), indent=2, sort_keys=False)
    except json.JSONDecodeError:
        return content


def looks_like_json(content: str) -> bool:
    text = content.strip()
    if not (text.startswith("{") or text.startswith("[")):
        return False
    try:
        json.loads(text)
    except json.JSONDecodeError:
        return False
    return True


def looks_like_html(content: str) -> bool:
    text = content.lstrip().lower()
    if text.startswith("<!doctype html") or text.startswith("<html"):
        return True
    return bool(re.search(r"<(article|aside|body|div|form|h[1-6]|head|main|nav|p|section|table|ul|ol|li|span|style|script)(\s|>|/)", text))


def looks_like_markdown(content: str) -> bool:
    return bool(
        re.search(r"(^|\n)#{1,6}\s+\S", content)
        or re.search(r"(^|\n)\s*[-*+]\s+\S", content)
        or re.search(r"(^|\n)```", content)
        or re.search(r"\[[^\]]+\]\([^)]+\)", content)
        or re.search(r"[*_]{1,2}[^*_]+[*_]{1,2}", content)
    )


def render_markdown_document(content: str) -> str:
    fields, body = parse_frontmatter(content)
    metadata = ""
    if fields:
        rows = []
        for key, value in fields.items():
            if isinstance(value, (dict, list)):
                display = yaml.safe_dump(value, sort_keys=False).strip()
            else:
                display = str(value)
            rows.append(f"<dt>{escape(key)}</dt><dd>{markdown_inline(display)}</dd>")
        metadata = f'<dl class="rendered-frontmatter">{"".join(rows)}</dl>'
    return f'<div class="rendered-markdown">{metadata}{markdown_blocks(body)}</div>'


def markdown_blocks(content: str) -> str:
    lines = content.splitlines()
    html_parts: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    code_lines: list[str] = []
    in_code = False
    code_language = ""

    def flush_paragraph() -> None:
        if paragraph:
            html_parts.append(f"<p>{markdown_inline(' '.join(line.strip() for line in paragraph))}</p>")
            paragraph.clear()

    def flush_list() -> None:
        if list_items:
            html_parts.append(f"<ul>{''.join(list_items)}</ul>")
            list_items.clear()

    for line in lines:
        stripped = line.strip()
        fence = re.match(r"^```([\w-]+)?\s*$", stripped)
        if fence:
            if in_code:
                html_parts.append(render_code_preview("\n".join(code_lines), code_language or "text"))
                code_lines.clear()
                code_language = ""
                in_code = False
            else:
                flush_paragraph()
                flush_list()
                in_code = True
                code_language = fence.group(1) or "text"
            continue
        if in_code:
            code_lines.append(line)
            continue
        if not stripped:
            flush_paragraph()
            flush_list()
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            flush_paragraph()
            flush_list()
            level = len(heading.group(1))
            html_parts.append(f"<h{level}>{markdown_inline(heading.group(2))}</h{level}>")
            continue
        if re.match(r"^[-*+]\s+.+$", stripped):
            flush_paragraph()
            item = re.sub(r"^[-*+]\s+", "", stripped)
            list_items.append(f"<li>{markdown_inline(item)}</li>")
            continue
        if stripped.startswith("> "):
            flush_paragraph()
            flush_list()
            html_parts.append(f"<blockquote>{markdown_inline(stripped[2:])}</blockquote>")
            continue
        if re.match(r"^-{3,}$", stripped):
            flush_paragraph()
            flush_list()
            html_parts.append("<hr>")
            continue
        paragraph.append(line)

    if in_code:
        html_parts.append(render_code_preview("\n".join(code_lines), code_language or "text"))
    flush_paragraph()
    flush_list()
    if not html_parts:
        return '<p class="rendered-empty">No preview content.</p>'
    return "\n".join(html_parts)


def markdown_inline(content: str) -> str:
    escaped = escape(content)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"(?<!_)_([^_]+)_(?!_)", r"<em>\1</em>", escaped)

    def link(match: re.Match[str]) -> str:
        label = match.group(1)
        href = html.unescape(match.group(2)).strip()
        if not (href.startswith(("http://", "https://", "mailto:", "#", "/"))):
            return label
        return f'<a href="{escape(href)}" target="_blank" rel="noreferrer">{label}</a>'

    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, escaped)


def run_sync_capture(form: dict[str, list[str]]) -> tuple[int, str]:
    targets = form.get("targets", []) or ALL_HARNESSES
    args = [target for target in targets if target in ALL_HARNESSES]
    project = selected_project((form.get("scope") or ["global"])[-1])
    if project["kind"] == "global":
        args.append("--global")
    if "refresh" in form:
        args.append("--refresh")
    if "apply" not in form:
        args.append("--dry-run")
    output = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        try:
            if project["kind"] == "project":
                with pushd(Path(project["root"])):
                    code = sync_command(args)
            else:
                code = sync_command(args)
        except Exception as exc:  # UI should show operational failures inline.
            code = 1
            print(f"Error: {exc}")
    return code, output.getvalue()


class ManagementHandler(BaseHTTPRequestHandler):
    server_version = "AIManagementWeb/1.0"

    def do_GET(self) -> None:
        path, query = parse_query(self.path)
        try:
            if path == "/":
                self.html(
                    render_index(
                        first(query, "type", "agents") or "agents",
                        first(query, "name", None),
                        first(query, "scope", "global") or "global",
                        first(query, "view", "form") or "form",
                        positive_int(first(query, "page", "1")),
                        {
                            "q": first(query, "q", "") or "",
                            "group": query.get("group", []),
                            "group_filter": "1" if "group_filter" in query else "",
                            "harness": query.get("harness", []),
                            "harness_filter": "1" if "harness_filter" in query else "",
                            "sort": first(query, "sort", DEFAULT_SELECTION_SORT) or DEFAULT_SELECTION_SORT,
                            "per_page": first(query, "per_page", str(DEFAULT_SELECTION_ITEMS_PER_PAGE)) or str(DEFAULT_SELECTION_ITEMS_PER_PAGE),
                            "source": first(query, "source", "") or "",
                            "external": "1" if "external" in query else "",
                            "hide_global_loaded": "1" if "hide_global_loaded" in query else "",
                            "template_type": first(query, "template_type", "agents") or "agents",
                        },
                    )
                )
            elif path == "/preview":
                content_type = first(query, "type", "agents")
                name = first(query, "name")
                self.text(preview_item(content_type, name))
            elif path == "/preview/rendered":
                content_type = first(query, "type", "agents")
                name = first(query, "name")
                self.html(
                    rendered_preview_item(
                        content_type,
                        name,
                        first(query, "scope", "global") or "global",
                        first(query, "harness", "") or "",
                    )
                )
            elif path == "/external/preview/rendered":
                self.html(
                    rendered_preview_external_item(
                        first(query, "type", "agents") or "agents",
                        first(query, "harness", "") or "",
                        first(query, "path", "") or "",
                        first(query, "scope", "global") or "global",
                    )
                )
            elif path == "/modal/edit":
                content_type = first(query, "type", "agents") or "agents"
                name = first(query, "name")
                scope = first(query, "scope", "global") or "global"
                view = first(query, "view", "form") or "form"
                if content_type not in LIST_TYPES:
                    content_type = "agents"
                if view not in EDITOR_VIEWS:
                    view = "form"
                installed = set(load_installed_type(content_type)) if content_type in CONTENT_TYPES else set()
                self.html(render_editor(content_type, name, installed, scope, view))
            elif path == "/external/modal/edit":
                self.html(
                    render_external_editor(
                        first(query, "type", "agents") or "agents",
                        first(query, "harness", "") or "",
                        first(query, "path", "") or "",
                        first(query, "scope", "global") or "global",
                    )
                )
            elif path == "/api/harness-paths":
                self.json({"harnesses": web_harness_paths(), "targets": ALL_HARNESSES})
            elif path == "/api/reload-token":
                self.json({"token": reload_token()})
            elif path == "/api/browse-dirs":
                self.json(browse_dirs(first(query, "path", str(Path.home()))))
            elif path == "/styles.css":
                self.css(STYLES)
            elif path in {"/favicon.svg", "/favicon.ico"}:
                self.svg(FAVICON_SVG)
            else:
                self.error(HTTPStatus.NOT_FOUND, "Not found")
        except Exception as exc:
            self.html(render_error(str(exc)), HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        path, _ = parse_query(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        parsed = urllib.parse.parse_qs(body, keep_blank_values=True)
        form = {
            key: values if key.startswith("field_") and (len(values) > 1 or key.startswith("field_agent_")) else values[-1]
            for key, values in parsed.items()
        }
        try:
            if path == "/modal/validate-form":
                try:
                    validate_form_state(form)
                    self.json({"ok": True})
                except Exception as exc:
                    self.json({"ok": False, "error": str(exc)})
            elif path == "/modal/convert-view":
                self.html(render_editor_from_form_state(form))
            elif path == "/templates/from-item":
                try:
                    payload = save_template_from_item(form)
                    self.json({"ok": True, **payload})
                except Exception as exc:
                    self.json({"ok": False, "error": str(exc)})
            elif path == "/templates/field-editor":
                try:
                    target_type = str(form.get("template_type") or "agents").strip()
                    if target_type not in TEMPLATE_TARGET_TYPES:
                        raise ValueError("Template type must be one of: " + ", ".join(sorted(TEMPLATE_TARGET_TYPES)))
                    fields = template_fields_from_form(form, target_type)
                    self.html(render_template_field_preset_editor(target_type, fields, form.get("scope", "global")))
                except Exception as exc:
                    self.html(render_error(str(exc)), HTTPStatus.BAD_REQUEST)
            elif path == "/save":
                name = save_item(form)
                view = form.get("editor_view", "form")
                target = (
                    f"/?type={urllib.parse.quote(form.get('type', 'agents'))}"
                    f"&name={urllib.parse.quote(name)}"
                    f"&scope={urllib.parse.quote(form.get('scope', 'global'))}"
                    f"&view={urllib.parse.quote(view if view in EDITOR_VIEWS else 'form')}"
                )
                self.redirect(target)
            elif path == "/install":
                if form.get("harness_update") == "1" or "targets" in parsed or form.get("scope", "global") != "global":
                    update_harness_installation(
                        form.get("type", ""),
                        form.get("name", ""),
                        form.get("scope", "global"),
                        parsed.get("targets", []),
                    )
                else:
                    update_installed(form.get("type", ""), form.get("name", ""), form.get("action", "install"))
                return_to = form.get("return_to", "")
                if return_to.startswith("/?"):
                    target = return_to
                else:
                    target = f"/?type={urllib.parse.quote(form.get('type', 'agents'))}&name={urllib.parse.quote(form.get('name', ''))}&scope={urllib.parse.quote(form.get('scope', 'global'))}"
                self.redirect(target)
            elif path == "/harnesses/toggle":
                name = form.get("name", "").strip()
                action = form.get("action", "enable")
                set_harness_enabled(name, action == "enable")
                target = (
                    f"/?type=harnesses"
                    f"&name={urllib.parse.quote(name)}"
                    f"&scope={urllib.parse.quote(form.get('scope', 'global'))}"
                    "&view=form"
                )
                self.redirect(target)
            elif path == "/delete":
                content_type = form.get("type", "agents")
                delete_item(content_type, form.get("name", ""))
                target = (
                    f"/?type={urllib.parse.quote(content_type)}"
                    f"&scope={urllib.parse.quote(form.get('scope', 'global'))}"
                )
                self.redirect(target)
            elif path == "/import-item":
                try:
                    name = import_item(form)
                    target = (
                        f"/?type={urllib.parse.quote(form.get('type', 'agents'))}"
                        f"&name={urllib.parse.quote(name)}"
                        f"&scope={urllib.parse.quote(form.get('scope', 'global'))}"
                        "&view=form"
                    )
                    if self.wants_json():
                        self.json({"ok": True, "name": name, "location": target})
                    else:
                        self.redirect(target)
                except Exception as exc:
                    if self.wants_json():
                        self.json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                    else:
                        raise
            elif path == "/duplicate":
                try:
                    content_type = form.get("type", "agents")
                    name = duplicate_item(content_type, form.get("name", ""))
                    self.json({"ok": True, "name": name})
                except Exception as exc:
                    self.json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            elif path == "/import-external":
                name = import_external_item(form)
                return_to = form.get("return_to", "")
                if return_to.startswith("/?"):
                    target = return_to
                else:
                    target = (
                        f"/?type={urllib.parse.quote(form.get('type', 'agents'))}"
                        f"&scope={urllib.parse.quote(form.get('scope', 'global'))}"
                        f"&external=1"
                    )
                if "name=" not in target:
                    separator = "&" if "?" in target else "?"
                    target = f"{target}{separator}name={urllib.parse.quote(name)}"
                self.redirect(target)
            elif path == "/save-external":
                save_external_item(form)
                name = form.get("name", "")
                target = (
                    f"/?type={urllib.parse.quote(form.get('type', 'agents'))}"
                    f"&scope={urllib.parse.quote(form.get('scope', 'global'))}"
                    f"&source=combined"
                    f"&name={urllib.parse.quote(name)}"
                )
                self.redirect(target)
            elif path == "/sync":
                code, output = run_sync_capture(parsed)
                self.html(render_sync_output(code, output))
            elif path == "/projects/add":
                project = add_project(form.get("project_label", ""), form.get("project_path", ""))
                scope = f"project:{project['root']}"
                name = form.get("name")
                name_param = "" if name is None else f"&name={urllib.parse.quote(name)}"
                target = (
                    f"/?type={urllib.parse.quote(form.get('type', 'agents'))}"
                    f"{name_param}"
                    f"&scope={urllib.parse.quote(scope)}"
                )
                self.redirect(target)
            else:
                self.error(HTTPStatus.NOT_FOUND, "Not found")
        except Exception as exc:
            self.html(render_error(str(exc)), HTTPStatus.BAD_REQUEST)

    def wants_json(self) -> bool:
        requested_with = self.headers.get("X-Requested-With", "")
        accept = self.headers.get("Accept", "")
        return requested_with == "fetch" or "application/json" in accept

    def html(self, content: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def text(self, content: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def json(self, content: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(content, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def css(self, content: str) -> None:
        data = content.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/css; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def svg(self, content: str) -> None:
        data = content.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
        self.send_header("Cache-Control", "public, max-age=86400")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def error(self, status: HTTPStatus, message: str) -> None:
        self.html(render_error(message), status)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}", file=sys.stderr)


def update_installed(content_type: str, name: str, action: str) -> None:
    if content_type not in CONTENT_TYPES:
        raise ValueError(f"{content_type} cannot be installed.")
    items = load_installed_type(content_type)
    if action == "uninstall":
        items = [item for item in items if item != name]
    elif name not in items:
        items.append(name)
    save_installed_type(content_type, items)


def normalize_harness_targets(values: list[str]) -> list[str]:
    targets: list[str] = []
    seen: set[str] = set()
    for value in values:
        harness = str(value or "").strip()
        if harness in ALL_HARNESSES and harness not in seen:
            targets.append(harness)
            seen.add(harness)
    return targets


def save_project_installed_type(project_root: str, content_type: str, items: list[str]) -> None:
    path = Path(project_root).expanduser() / ".wdm" / "installed" / f"{content_type}.conf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(sorted(dict.fromkeys(items))) + ("\n" if items else ""), encoding="utf-8")


def set_scope_installed(content_type: str, name: str, scope: str, installed: bool) -> None:
    project = selected_project(scope)
    if project["kind"] == "project":
        items: set[str] = set()
        for path in project_installed_paths(project["root"], content_type):
            items.update(parse_installed_conf(path))
        if installed:
            items.add(name)
        else:
            items.discard(name)
        save_project_installed_type(project["root"], content_type, sorted(items))
        return
    items = load_installed_type(content_type)
    if installed and name not in items:
        items.append(name)
    elif not installed:
        items = [item for item in items if item != name]
    save_installed_type(content_type, items)


def build_harness_outputs(content_type: str, harnesses: list[str]) -> None:
    if not harnesses:
        return
    builder = build_module.BUILDERS.get(content_type)
    if builder is None:
        raise ValueError(f"{content_type} cannot be built for harnesses.")
    source_dir = content_source_dir(content_type)
    defaults = load_defaults(DEFAULTS_FILE) if DEFAULTS_FILE.exists() else {}
    builder(source_dir, harnesses, dry_run=False, defaults=defaults)


def built_artifact_path(content_type: str, name: str, harness: str) -> Path:
    source_path = resolve_item_path(content_type, name)
    build_root = build_module.build_output_root(content_source_dir(content_type))
    build_dir = build_root / harness
    if content_type == "skills":
        return build_dir / name
    if content_type == "agents":
        default = ".toml" if harness == "codex" else ".md"
        return build_dir / f"{name}{build_module.output_extension(harness, content_type, default)}"
    if content_type in {"rules", "workflows"}:
        return build_dir / f"{name}{build_module.output_extension(harness, content_type, '.md')}"
    if content_type == "mcp":
        default = ".toml" if harness == "codex" else ".json"
        return build_dir / f"{name}{build_module.output_extension(harness, content_type, default)}"
    if content_type == "hooks":
        return build_dir / source_path.name
    return build_dir / source_path.name


def remove_direct_harness_destination(path: Path) -> None:
    if path.is_symlink():
        path.unlink()


def update_harness_installation(content_type: str, name: str, scope: str, target_values: list[str]) -> None:
    if content_type not in CONTENT_TYPES:
        raise ValueError(f"{content_type} cannot be installed.")
    if name not in list_names(content_type):
        raise ValueError(f"Unknown {content_type} item: {name}")
    scope = selected_project(scope).get("value", "global")
    selected_targets = set(normalize_harness_targets(target_values))

    supported_targets: list[str] = []
    aggregate_targets: list[str] = []
    destinations: dict[str, Path] = {}
    for harness in ALL_HARNESSES:
        destination, aggregate = harness_destination(content_type, name, harness, scope)
        if destination is None:
            continue
        if aggregate:
            aggregate_targets.append(harness)
            continue
        supported_targets.append(harness)
        destinations[harness] = destination

    selected_supported = [harness for harness in supported_targets if harness in selected_targets]
    build_harness_outputs(content_type, selected_supported)

    for harness in supported_targets:
        destination = destinations[harness]
        if harness in selected_targets:
            built = built_artifact_path(content_type, name, harness)
            if not built.exists():
                raise ValueError(f"Built {content_type} output is missing for {harness}: {built}")
            sync_module.make_link(built, destination)
        else:
            remove_direct_harness_destination(destination)

    selected_aggregate = sorted(set(aggregate_targets) & selected_targets)
    if selected_aggregate:
        labels = ", ".join(harness_label(harness) for harness in selected_aggregate)
        raise ValueError(f"{content_type} uses aggregate config for {labels}; use Sync for those targets.")

    set_scope_installed(content_type, name, scope, bool(selected_supported))


def render_index(
    content_type: str,
    selected_name: str | None,
    scope: str = "global",
    view: str = "form",
    selection_page: int = 1,
    filters: dict[str, str] | None = None,
) -> str:
    if content_type not in LIST_TYPES:
        content_type = "agents"
    if view not in EDITOR_VIEWS:
        view = "form"
    scope = selected_project(scope).get("value", "global")
    filters = filters or {}
    if content_type == "templates":
        active_template_type = str(filters.get("template_type") or "agents").strip()
        if active_template_type not in TEMPLATE_TARGET_TYPES:
            active_template_type = "agents"
        if selected_name:
            try:
                _, _, template_fields, _ = read_item("templates", selected_name)
                selected_template_type = str(template_fields.get("type") or "").strip()
                if selected_template_type in TEMPLATE_TARGET_TYPES:
                    active_template_type = selected_template_type
            except OSError:
                pass
        filters = {**filters, "template_type": active_template_type}
    names = list_names(content_type)
    summaries = [item_summary(content_type, name) for name in names]
    if content_type == "templates" and selected_name is None:
        summaries = [
            item
            for item in summaries
            if item.get("template_type") == filters.get("template_type")
        ]
    installed = set(load_installed_type(content_type)) if content_type in CONTENT_TYPES else set()
    if selected_name is None:
        body = render_selection_page(content_type, summaries, installed, scope, selection_page, filters)
    else:
        body = (
            "" if content_type in {"harnesses", "templates"} else render_sidebar(content_type, summaries, installed, selected_name, scope)
        ) + render_editor(content_type, selected_name, installed, scope, view, filters.get("template_type", "agents"))
    return page(
        content_type,
        selected_name,
        scope,
        body,
        filters,
    )


def page(content_type: str, selected_name: str | None, scope: str, body: str, filters: dict[str, str] | None = None) -> str:
    title = "AI Management"
    project = selected_project(scope)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/styles.css">
</head>
<body>
  <header class="topbar">
    <div class="topbar-brand">
      <h1>AI Management</h1>
    </div>
    {render_type_submenu(content_type, project["value"])}
  </header>
  <main class="layout">
    <nav class="rail" aria-label="Projects and harnesses">
      {render_rail(content_type, selected_name, project["value"], filters or {})}
    </nav>
    {body}
  </main>
  {render_project_modal(content_type, selected_name)}
  {render_import_modal(content_type, project["value"])}
  {render_content_modal()}
  {render_delete_modal()}
  <script>
    async function loadPreview(type, name) {{
      const target = document.querySelector('[data-preview]');
      if (!target || !name) return;
      target.textContent = 'Generating preview...';
      const res = await fetch('/preview?type=' + encodeURIComponent(type) + '&name=' + encodeURIComponent(name));
      target.textContent = await res.text();
    }}
    async function loadSelectionPreview(type, name, harness = '') {{
      if (!name) return;
      const scope = currentScope();
      const parts = openContentModal(name + ' preview');
      if (!parts) return;
      parts.actions.innerHTML = renderPreviewActions(type, name, scope);
      parts.body.innerHTML = '<div class="modal-loading">Generating preview...</div>';
      const url = '/preview/rendered?type=' + encodeURIComponent(type) +
        '&name=' + encodeURIComponent(name) +
        '&scope=' + encodeURIComponent(scope) +
        (harness ? '&harness=' + encodeURIComponent(harness) : '');
      const res = await fetch(url);
      parts.body.innerHTML = await res.text();
    }}
    async function loadExternalSelectionPreview(type, name, harness, path, scope) {{
      if (!path) return;
      const parts = openContentModal((name || 'External item') + ' preview');
      if (!parts) return;
      parts.actions.innerHTML = renderExternalPreviewActions(type, name, harness, path, scope || currentScope());
      parts.body.innerHTML = '<div class="modal-loading">Generating preview...</div>';
      const url = '/external/preview/rendered?type=' + encodeURIComponent(type || 'agents') +
        '&harness=' + encodeURIComponent(harness || '') +
        '&path=' + encodeURIComponent(path || '') +
        '&scope=' + encodeURIComponent(scope || currentScope());
      const res = await fetch(url);
      parts.body.innerHTML = await res.text();
    }}
    function renderPreviewActions(type, name, scope) {{
      const view = 'form';
      return '<div class="modal-action-bar">' +
        '<button type="button" class="secondary" data-preview-edit data-edit-type="' + escapeAttr(type) + '" data-edit-name="' + escapeAttr(name) + '" data-edit-scope="' + escapeAttr(scope || 'global') + '" data-edit-view="' + escapeAttr(view) + '">Edit</button>' +
        '<button type="button" class="secondary" data-preview-duplicate data-duplicate-type="' + escapeAttr(type) + '" data-duplicate-name="' + escapeAttr(name) + '" data-duplicate-scope="' + escapeAttr(scope || 'global') + '">Duplicate</button>' +
        '<button type="button" class="danger secondary" data-preview-delete data-delete-type="' + escapeAttr(type) + '" data-delete-name="' + escapeAttr(name) + '" data-delete-scope="' + escapeAttr(scope || 'global') + '">Delete</button>' +
      '</div>';
    }}
    function renderExternalPreviewActions(type, name, harness, path, scope) {{
      return '<div class="modal-action-bar">' +
        '<button type="button" class="secondary" data-external-preview-edit data-external-type="' + escapeAttr(type || 'agents') + '" data-external-name="' + escapeAttr(name || '') + '" data-external-harness="' + escapeAttr(harness || '') + '" data-external-path="' + escapeAttr(path || '') + '" data-external-scope="' + escapeAttr(scope || 'global') + '">Edit</button>' +
      '</div>';
    }}
    async function loadSelectionEdit(type, name, scope, view) {{
      if (!name) return;
      const parts = openContentModal('Edit ' + name);
      if (!parts) return;
      parts.body.innerHTML = '<div class="modal-loading">Loading...</div>';
      const url = '/modal/edit?type=' + encodeURIComponent(type) + '&name=' + encodeURIComponent(name) + '&scope=' + encodeURIComponent(scope || 'global') + '&view=' + encodeURIComponent(view || 'form');
      const res = await fetch(url);
      parts.body.innerHTML = await res.text();
      resetBodySectionEditors(parts.body);
      resetTemplateFieldSectionEditors(parts.body);
      parts.actions.innerHTML = renderEditActions(type, name, scope || 'global', view || 'form');
      setEditorCleanSnapshot(parts.body);
      updateReactivePaths();
    }}
    async function loadExternalSelectionEdit(type, name, harness, path, scope) {{
      if (!path) return;
      const parts = openContentModal('Edit ' + (name || 'external item'));
      if (!parts) return;
      parts.body.innerHTML = '<div class="modal-loading">Loading...</div>';
      const url = '/external/modal/edit?type=' + encodeURIComponent(type || 'agents') +
        '&harness=' + encodeURIComponent(harness || '') +
        '&path=' + encodeURIComponent(path || '') +
        '&scope=' + encodeURIComponent(scope || currentScope());
      const res = await fetch(url);
      parts.body.innerHTML = await res.text();
      parts.actions.innerHTML = renderExternalEditActions(type || 'agents', name || '', harness || '', path || '', scope || currentScope());
      resetBodySectionEditors(parts.body);
      resetTemplateFieldSectionEditors(parts.body);
      setEditorCleanSnapshot(parts.body);
    }}
    function renderEditActions(type, name, scope, view) {{
      const deleteButton = name ? '<button type="button" class="danger secondary" data-edit-delete data-delete-type="' + escapeAttr(type || 'agents') + '" data-delete-name="' + escapeAttr(name || '') + '" data-delete-scope="' + escapeAttr(scope || 'global') + '">Delete</button>' : '';
      return '<div class="modal-action-bar">' +
        '<button type="button" class="secondary" data-edit-revert>Revert</button>' +
        '<button type="button" data-edit-save>Save</button>' +
        deleteButton +
      '</div>';
    }}
    function renderExternalEditActions(type, name, harness, path, scope) {{
      return '<div class="modal-action-bar">' +
        '<button type="button" class="secondary" data-edit-revert>Revert</button>' +
        '<button type="button" data-edit-save>Save</button>' +
      '</div>';
    }}
    function activeEditorForm() {{
      return document.querySelector('[data-content-modal] form.edit-form');
    }}
    function syncStructuredEditors(form) {{
      if (!form) return;
      syncBodySectionEditor(form);
      syncTemplateSectionEditor(form);
      syncTemplateFieldSectionEditor(form);
      syncExtraFieldEditor(form);
      syncListFieldEditor(form);
      syncMappingFieldEditor(form);
    }}
    async function refreshTemplateFieldPresetEditor(select) {{
      const form = select?.closest('form.edit-form');
      const currentEditor = form?.querySelector('[data-template-field-preset-editor]');
      if (!form || !currentEditor) return false;
      syncStructuredEditors(form);
      const formData = new FormData(form);
      formData.set('template_fields_previous_type', currentEditor.dataset.templateFieldType || '');
      formData.set('template_type', select.value || 'agents');
      try {{
        const res = await fetch('/templates/field-editor', {{
          method: 'post',
          body: new URLSearchParams(formData),
        }});
        if (!res.ok) throw new Error(await res.text());
        currentEditor.outerHTML = await res.text();
        const updatedEditor = form.querySelector('[data-template-field-preset-editor]');
        if (updatedEditor) {{
          syncExtraFieldEditor(updatedEditor);
          syncListFieldEditor(updatedEditor);
          syncMappingFieldEditor(updatedEditor);
          syncTemplateFieldSectionEditor(form);
        }}
        updateContentModalDirtyState();
        return true;
      }} catch (error) {{
        showModalClientError(error && error.message ? error.message : 'Unable to update template fields.', select);
        return false;
      }}
    }}
    function editorFormSnapshot(form) {{
      if (!form) return '';
      syncStructuredEditors(form);
      return JSON.stringify(Array.from(new FormData(form).entries()));
    }}
    function setEditorCleanSnapshot(root = document) {{
      const form = root.matches && root.matches('form.edit-form') ? root : root.querySelector?.('form.edit-form');
      if (!form) return;
      form.dataset.initialSnapshot = editorFormSnapshot(form);
      updateContentModalDirtyState();
    }}
    function isEditorFormDirty(form = activeEditorForm()) {{
      if (!form || !form.dataset.initialSnapshot) return false;
      return editorFormSnapshot(form) !== form.dataset.initialSnapshot;
    }}
    function updateContentModalDirtyState() {{
      const modal = document.querySelector('[data-content-modal]');
      if (!modal) return;
      modal.dataset.dirty = isEditorFormDirty() ? 'true' : 'false';
    }}
    function confirmDiscardChanges() {{
      return !isEditorFormDirty() || window.confirm('Discard unsaved changes?');
    }}
    function confirmDirtyDelete() {{
      return !isEditorFormDirty() || window.confirm('Continue to delete? Unsaved editor changes will not be saved.');
    }}
    function clearModalClientErrors(root = document) {{
      root.querySelectorAll?.('[data-client-error]').forEach(node => node.remove());
    }}
    function modalFocusableElements(root) {{
      return Array.from(root?.querySelectorAll?.('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])') || [])
        .filter(node => node.offsetParent !== null || node === document.activeElement);
    }}
    function showModalClientError(message, focusNode) {{
      const body = document.querySelector('[data-content-modal-body]');
      if (!body) return;
      clearModalClientErrors(body);
      const node = document.createElement('div');
      node.className = 'modal-error';
      node.dataset.clientError = 'true';
      node.setAttribute('role', 'alert');
      node.setAttribute('aria-live', 'assertive');
      node.tabIndex = -1;
      node.textContent = message;
      body.prepend(node);
      if (focusNode) focusNode.focus();
      else node.focus();
    }}
    function validateKeyedEditorRows(form, editorSelector, rowSelector, keySelector, valueSelector, label) {{
      for (const editor of form.querySelectorAll(editorSelector)) {{
        const seen = new Map();
        for (const row of editor.querySelectorAll(rowSelector)) {{
          const keyInput = row.querySelector(keySelector);
          const valueInput = row.querySelector(valueSelector);
          const key = (keyInput?.value || '').trim();
          const value = valueInput?.value || '';
          if (!key && value.trim()) {{
            row.dataset.fieldInvalid = 'true';
            showModalClientError(label + ' rows need a key when a value is entered.', keyInput || valueInput);
            return false;
          }}
          if (!key) continue;
          const duplicate = seen.get(key);
          if (duplicate) {{
            row.dataset.fieldInvalid = 'true';
            duplicate.dataset.fieldInvalid = 'true';
            showModalClientError(label + ' contains duplicate key "' + key + '".', keyInput);
            return false;
          }}
          seen.set(key, row);
        }}
      }}
      return true;
    }}
    function validateAdditionalFieldCollisions(form) {{
      const controlled = new Set(
        Array.from(form.querySelectorAll('[name^="field_"]'))
          .map(input => String(input.getAttribute('name') || '').replace(/^field_/, '').trim())
          .filter(Boolean)
      );
      for (const editor of form.querySelectorAll('[data-extra-fields-editor]')) {{
        let reserved = [];
        try {{
          reserved = JSON.parse(editor.querySelector('[data-extra-fields-source]')?.dataset.reservedKeys || '[]');
        }} catch (_error) {{
          reserved = [];
        }}
        const reservedKeys = new Set([...controlled, ...reserved]);
        for (const row of editor.querySelectorAll('[data-extra-field-row]')) {{
          const keyInput = row.querySelector('[data-extra-field-key]');
          const key = (keyInput?.value || '').trim();
          if (key && reservedKeys.has(key)) {{
            row.dataset.fieldInvalid = 'true';
            showModalClientError('Additional fields cannot reuse reserved field key "' + key + '".', keyInput);
            return false;
          }}
        }}
      }}
      return true;
    }}
    function validateTemplateSections(form) {{
      const editor = form.querySelector('[data-template-section-editor]');
      if (!editor) return true;
      let hasSection = false;
      for (const row of editor.querySelectorAll('[data-template-section-row]')) {{
        const titleInput = row.querySelector('[data-template-section-title]');
        const content = row.querySelector('[data-template-section-content]')?.value || '';
        const title = (titleInput?.value || '').trim();
        if (!title && !content.trim()) continue;
        hasSection = true;
        if (!title) {{
          row.dataset.fieldInvalid = 'true';
          showModalClientError('Template sections need a title.', titleInput);
          return false;
        }}
      }}
      if (!hasSection) {{
        const firstTitle = editor.querySelector('[data-template-section-title]');
        showModalClientError('Template needs at least one section.', firstTitle);
        return false;
      }}
      return true;
    }}
    function validateTemplateFieldSections(form) {{
      const editor = form.querySelector('[data-template-field-section-editor]');
      if (!editor) return true;
      for (const group of editor.querySelectorAll('[data-template-field-section-group]')) {{
        const key = group.querySelector('[data-template-field-section-key]');
        const label = group.querySelector('[data-template-field-section-label]');
        const hasAnySection = Array.from(group.querySelectorAll('[data-template-field-section-row]')).some(row => {{
          const title = (row.querySelector('[data-template-field-section-title]')?.value || '').trim();
          const content = (row.querySelector('[data-template-field-section-content]')?.value || '').trim();
          return !!title || !!content;
        }});
        const hasContent = !!((key?.value || '').trim() || (label?.value || '').trim() || hasAnySection);
        if (!hasContent) continue;
        if (!key || !key.value.trim()) {{
          showModalClientError('Sectioned fields need a field key.', key || group);
          return false;
        }}
        for (const row of group.querySelectorAll('[data-template-field-section-row]')) {{
          const title = row.querySelector('[data-template-field-section-title]');
          const content = row.querySelector('[data-template-field-section-content]');
          if ((content?.value || '').trim() && title && !title.value.trim()) {{
            showModalClientError('Field sections with starter content need a title.', title);
            return false;
          }}
        }}
      }}
      return true;
    }}
    function validateEditorForm(form) {{
      if (!form) return true;
      clearModalClientErrors(document.querySelector('[data-content-modal-body]') || form);
      form.querySelectorAll('[data-field-invalid="true"]').forEach(node => {{
        delete node.dataset.fieldInvalid;
      }});
      if (!validateKeyedEditorRows(form, '[data-extra-fields-editor]', '[data-extra-field-row]', '[data-extra-field-key]', '[data-extra-field-value]', 'Additional fields')) return false;
      if (!validateKeyedEditorRows(form, '[data-mapping-field-editor]', '[data-mapping-field-row]', '[data-mapping-field-key]', '[data-mapping-field-value]', 'Mapping fields')) return false;
      if (!validateAdditionalFieldCollisions(form)) return false;
      if (!validateTemplateSections(form)) return false;
      if (!validateTemplateFieldSections(form)) return false;
      for (const section of form.querySelectorAll('[data-body-section]')) {{
        const level = section.querySelector('[data-body-section-level]')?.value || '0';
        const title = section.querySelector('[data-body-section-title]');
        if (level !== '0' && title && !title.value.trim()) {{
          showModalClientError('Body sections with a heading level need a section title.', title);
          return false;
        }}
      }}
      return true;
    }}
    function focusFirstYamlModeField(form) {{
      const field = Array.from(form?.querySelectorAll('[data-value-mode]') || []).find(node => node.value === 'yaml');
      if (field) {{
        const row = field.closest('[data-extra-field-row], [data-mapping-field-row]');
        if (row) row.dataset.fieldInvalid = 'true';
        const value = row?.querySelector('[data-extra-field-value], [data-mapping-field-value]');
        if (value) value.focus();
      }}
    }}
    async function validateEditorFormWithServer(form, targetView = '') {{
      if (!validateEditorForm(form)) return false;
      syncStructuredEditors(form);
      try {{
        const formData = new FormData(form);
        if (targetView) formData.set('target_view', targetView);
        const res = await fetch('/modal/validate-form', {{
          method: 'post',
          body: new URLSearchParams(formData),
        }});
        const data = await res.json();
        if (data.ok) return true;
        showModalClientError(data.error || 'Unable to validate this form.');
        focusFirstYamlModeField(form);
        return false;
      }} catch (error) {{
        showModalClientError(error && error.message ? error.message : 'Unable to validate this form.');
        return false;
      }}
    }}
    let contentModalReturnFocus = null;
    function focusContentModal(modal) {{
      const target = modal?.querySelector('[data-close-content-modal]') || modalFocusableElements(modal)[0];
      if (target) target.focus();
    }}
    function openContentModal(title) {{
      if (!confirmDiscardChanges()) return null;
      const modal = document.querySelector('[data-content-modal]');
      const titleNode = document.querySelector('[data-content-modal-title]');
      const actions = document.querySelector('[data-content-modal-actions]');
      const body = document.querySelector('[data-content-modal-body]');
      if (!modal || !titleNode || !body || !actions) return null;
      titleNode.textContent = title || 'Details';
      actions.innerHTML = '';
      body.innerHTML = '';
      contentModalReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      modal.hidden = false;
      modal.dataset.dirty = 'false';
      window.requestAnimationFrame(() => focusContentModal(modal));
      return {{ modal, title: titleNode, actions, body }};
    }}
    function closeContentModal(force = false) {{
      if (!force && !confirmDiscardChanges()) return false;
      const modal = document.querySelector('[data-content-modal]');
      const body = document.querySelector('[data-content-modal-body]');
      const actions = document.querySelector('[data-content-modal-actions]');
      if (modal) modal.hidden = true;
      if (body) body.innerHTML = '';
      if (actions) actions.innerHTML = '';
      if (modal) modal.dataset.dirty = 'false';
      if (contentModalReturnFocus && document.contains(contentModalReturnFocus)) contentModalReturnFocus.focus();
      contentModalReturnFocus = null;
      return true;
    }}
    function currentScope() {{
      const option = document.querySelector('[data-project-entry].active');
      return option ? option.dataset.scope : 'global';
    }}
    function openDeleteModal(type, name, scope) {{
      const modal = document.querySelector('[data-delete-modal]');
      if (!modal) return;
      const typeInput = modal.querySelector('[data-delete-type]');
      const nameInput = modal.querySelector('[data-delete-name]');
      const scopeInput = modal.querySelector('[data-delete-scope]');
      const label = modal.querySelector('[data-delete-label]');
      if (typeInput) typeInput.value = type || '';
      if (nameInput) nameInput.value = name || '';
      if (scopeInput) scopeInput.value = scope || currentScope();
      if (label) label.textContent = name || 'this item';
      modal.hidden = false;
      const button = modal.querySelector('button[type="submit"]');
      if (button) button.focus();
    }}
    function closeDeleteModal() {{
      const modal = document.querySelector('[data-delete-modal]');
      if (modal) modal.hidden = true;
    }}
    async function submitDeleteForm(form) {{
      const button = form.querySelector('button[type="submit"]');
      if (button) button.disabled = true;
      try {{
        const res = await fetch(form.action || '/delete', {{
          method: form.method || 'post',
          body: new URLSearchParams(new FormData(form)),
        }});
        if (!res.ok) throw new Error(await res.text());
        closeDeleteModal();
        closeContentModal(true);
        const type = new FormData(form).get('type') || 'agents';
        const scope = new FormData(form).get('scope') || currentScope();
        window.location.href = '/?type=' + encodeURIComponent(type) + '&scope=' + encodeURIComponent(scope);
      }} catch (error) {{
        const label = form.querySelector('[data-delete-label]');
        if (label) label.textContent = error && error.message ? error.message : 'Unable to delete.';
      }} finally {{
        if (button) button.disabled = false;
      }}
    }}
    async function duplicateManagedItem(type, name, scope) {{
      if (!type || !name) return;
      const data = new URLSearchParams();
      data.set('type', type);
      data.set('name', name);
      data.set('scope', scope || currentScope());
      try {{
        const res = await fetch('/duplicate', {{
          method: 'post',
          headers: {{ 'Accept': 'application/json', 'X-Requested-With': 'fetch' }},
          body: data,
        }});
        const payload = await res.json().catch(() => ({{ ok: false, error: 'Duplicate failed.' }}));
        if (!res.ok || !payload.ok) throw new Error(payload.error || 'Duplicate failed');
        await loadSelectionEdit(type, payload.name, scope || currentScope(), 'form');
      }} catch (error) {{
        showModalClientError(error && error.message ? error.message : 'Unable to duplicate item.');
      }}
    }}
    function readFileAsText(file) {{
      return new Promise((resolve, reject) => {{
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ''));
        reader.onerror = () => reject(reader.error || new Error('Unable to read file.'));
        reader.readAsText(file);
      }});
    }}
    async function submitImportForm(form) {{
      const source = form.querySelector('[name="import_source"]:checked')?.value || 'paste';
      const rawField = form.querySelector('[name="import_raw"]');
      const fileNameField = form.querySelector('[data-import-file-name]');
      const submit = form.querySelector('button[type="submit"]');
      try {{
        if (source === 'file') {{
          const file = form.querySelector('[data-import-file-input]')?.files?.[0];
          if (!file) throw new Error('Choose a file to import.');
          if (fileNameField) fileNameField.value = file.name || '';
          if (rawField) rawField.value = await readFileAsText(file);
        }}
        if (submit) submit.disabled = true;
        const res = await fetch(form.action || '/import-item', {{
          method: form.method || 'post',
          headers: {{ 'Accept': 'application/json', 'X-Requested-With': 'fetch' }},
          body: new URLSearchParams(new FormData(form)),
        }});
        const payload = await res.json().catch(() => ({{ ok: false, error: 'Import failed.' }}));
        if (!res.ok || !payload.ok) throw new Error(payload.error || 'Import failed.');
        window.location.href = payload.location || res.url || window.location.href;
      }} catch (error) {{
        const message = error && error.message ? error.message : 'Unable to import item.';
        let target = form.querySelector('[data-import-error]');
        if (!target) {{
          target = document.createElement('div');
          target.className = 'modal-error';
          target.dataset.importError = 'true';
          target.setAttribute('role', 'alert');
          target.tabIndex = -1;
          form.prepend(target);
        }}
        target.textContent = message;
        target.focus?.();
      }} finally {{
        if (submit) submit.disabled = false;
      }}
    }}
    async function submitModalEditorForm(form) {{
      const button = form.querySelector('button[type="submit"]');
      if (!(await validateEditorFormWithServer(form))) return;
      if (button) button.disabled = true;
      try {{
        syncBodySectionEditor(form);
        syncExtraFieldEditor(form);
        syncListFieldEditor(form);
        syncMappingFieldEditor(form);
        const formData = new FormData(form);
        const res = await fetch(form.action || '/save', {{
          method: form.method || 'post',
          body: new URLSearchParams(formData),
        }});
        if (!res.ok) throw new Error(await res.text());
        const finalUrl = new URL(res.url || window.location.href, window.location.href);
        const savedName = finalUrl.searchParams.get('name') || formData.get('name') || '';
        const type = formData.get('type') || finalUrl.searchParams.get('type') || 'agents';
        setEditorCleanSnapshot(form);
        if ((form.action || '').endsWith('/save-external')) {{
          await loadExternalSelectionPreview(type, savedName, formData.get('harness') || '', formData.get('path') || '', formData.get('scope') || currentScope());
        }} else {{
          await loadSelectionPreview(type, savedName);
        }}
      }} catch (error) {{
        showModalClientError(error && error.message ? error.message : 'Unable to save.');
      }} finally {{
        if (button) button.disabled = false;
      }}
    }}
    async function convertModalEditorView(form, targetView) {{
      if (!form) return false;
      syncStructuredEditors(form);
      if (!(await validateEditorFormWithServer(form, targetView || 'file'))) return false;
      const wasDirty = isEditorFormDirty(form);
      const formData = new FormData(form);
      formData.set('target_view', targetView || 'file');
      const modalBody = form.closest('[data-content-modal-body]');
      const editorSection = form.closest('section.editor');
      if (!modalBody && !editorSection) return false;
      try {{
        const res = await fetch('/modal/convert-view', {{
          method: 'post',
          body: new URLSearchParams(formData),
        }});
        if (!res.ok) throw new Error(await res.text());
        const html = await res.text();
        let root = modalBody;
        if (modalBody) {{
          modalBody.innerHTML = html;
        }} else if (editorSection) {{
          const wrapper = document.createElement('div');
          wrapper.innerHTML = html;
          const nextEditor = wrapper.querySelector('section.editor');
          if (nextEditor) {{
            editorSection.replaceWith(nextEditor);
            root = nextEditor;
          }}
        }}
        if (!root) return false;
        resetBodySectionEditors(root);
        resetTemplateSectionEditors(root);
        resetTemplateFieldSectionEditors(root);
        updateReactivePaths();
        const nextForm = root.querySelector('form.edit-form');
        if (nextForm) {{
          if (wasDirty) {{
            nextForm.dataset.initialSnapshot = '__dirty_before_view_toggle__';
            updateContentModalDirtyState();
          }} else {{
            setEditorCleanSnapshot(nextForm);
          }}
        }}
        return true;
      }} catch (error) {{
        showModalClientError(error && error.message ? error.message : 'Unable to switch editor view.');
        return false;
      }}
    }}
    function defaultTarget() {{
      return {json.dumps(ALL_HARNESSES[0] if ALL_HARNESSES else "")};
    }}
    function sourcePath(type, name) {{
      const root = {json.dumps(str(CONTENT_ROOT))};
      const coreRoot = root + '/' + type + '/core';
      const safeName = (name || 'new').trim() || 'new';
      if (type === 'skills') return root + '/skills/core/' + safeName + '/SKILL.md';
      if (type === 'groups') return root + '/groups/' + safeName + '.group';
      if (type === 'templates') return root + '/templates/core/' + safeName + '.template';
      if (type === 'harnesses') return root + '/harnesses/core/' + safeName + '.json';
      if (type === 'hooks') return root + '/hooks/core/' + safeName;
      const ext = type === 'mcp' ? '.md' : '.md';
      return coreRoot + '/' + safeName + ext;
    }}
    function destinationPath(type, name, target, root, isGlobal) {{
      const safeName = (name || 'new').trim() || 'new';
      const harnessPaths = {json.dumps(web_harness_paths())};
      if (type === 'harnesses') return 'Harness configs are source files only';
      if (target === 'codex') {{
        if (type === 'agents') return root + '/.codex/agents/' + safeName + '.toml';
        if (type === 'skills') return root + '/.agents/skills/' + safeName + '/';
        if (type === 'mcp') return root + '/.codex/config.toml';
        if (type === 'hooks') return root + '/.codex/hooks/' + safeName;
        return 'Codex does not sync ' + type + ' directly';
      }}
      if (target === 'claude') {{
        if (type === 'agents') return root + '/.claude/agents/' + safeName + '.md';
        if (type === 'skills') return root + '/.claude/skills/' + safeName + '/';
        if (type === 'rules') return root + '/.claude/rules/' + safeName + '.md';
        if (type === 'workflows') return root + '/.claude/commands/' + safeName + '.md';
        if (type === 'hooks') return root + '/.claude/hooks/' + safeName;
        if (type === 'mcp') return isGlobal ? 'Claude global MCP is not overwritten' : root + '/.mcp.json';
      }}
      if (target === 'copilot') {{
        const base = isGlobal ? root + '/.copilot' : root + '/.github';
        if (type === 'agents') return base + '/agents/' + safeName + '.agent.md';
        if (type === 'skills') return base + '/skills/' + safeName + '/';
        if (type === 'rules') return isGlobal ? base + '/instructions/' + safeName + '.instructions.md' : base + '/copilot-instructions.md';
        if (type === 'hooks') return base + '/hooks/' + safeName;
        if (type === 'mcp') return isGlobal ? base + '/mcp-config.json' : root + '/.github/mcp.json';
      }}
      if (target === 'gemini') {{
        if (type === 'agents') return root + '/.gemini/agents/' + safeName + '.md';
        if (type === 'skills') return root + '/.gemini/skills/' + safeName + '/';
        if (type === 'mcp') return root + '/.gemini/settings.json';
        return 'Gemini does not sync ' + type + ' directly';
      }}
      const mode = isGlobal ? 'global' : 'project';
      const template = harnessPaths[target] && harnessPaths[target][mode] && harnessPaths[target][mode][type];
      if (template) {{
        return root + '/' + template
          .replaceAll('{{name}}', safeName)
          .replaceAll('{{stem}}', safeName)
          .replaceAll('{{file}}', safeName);
      }}
      return root;
    }}
    function updateReactivePaths() {{
      const option = document.querySelector('[data-project-entry].active');
      const root = option ? option.dataset.root : {json.dumps(str(Path.home()))};
      const isGlobal = option ? option.dataset.kind === 'global' : true;
      const scope = option ? option.dataset.scope : 'global';
      document.querySelectorAll('[data-scope-hidden]').forEach(input => input.value = scope);
      document.querySelectorAll('[data-project-root]').forEach(node => node.textContent = root);
      document.querySelectorAll('[data-project-mode]').forEach(node => node.textContent = isGlobal ? 'Global' : 'Project');
      const nameInput = document.querySelector('[data-name-input]');
      const typeNode = document.querySelector('[data-editor-type]');
      const type = typeNode ? typeNode.dataset.editorType : {json.dumps(content_type)};
      const name = nameInput ? nameInput.value : {json.dumps(selected_name or "")};
      const target = defaultTarget();
      document.querySelectorAll('[data-source-path]').forEach(node => node.textContent = sourcePath(type, name));
      document.querySelectorAll('[data-target-path]').forEach(node => node.textContent = destinationPath(type, name, target, root, isGlobal));
    }}
    const projectModal = document.querySelector('[data-project-modal]');
    const projectPathInput = document.querySelector('[data-project-path-input]');
    const projectBrowser = document.querySelector('[data-project-browser]');
    const importModal = document.querySelector('[data-import-modal]');
    const importBrowser = document.querySelector('[data-import-browser]');
    const importPathInput = document.querySelector('[data-import-path-input]');
    function openProjectModal() {{
      if (!projectModal) return;
      projectModal.hidden = false;
      const firstInput = projectModal.querySelector('input[name="project_label"]');
      if (firstInput) firstInput.focus();
      browseProjectDirs(projectPathInput ? projectPathInput.value : '');
    }}
    function closeProjectModal() {{
      if (projectModal) projectModal.hidden = true;
    }}
    function singularLabel(type) {{
      if (type === 'mcp') return 'MCP server';
      if (type === 'harnesses') return 'harness';
      if (type === 'templates') return 'template';
      if (type && type.endsWith('ies')) return type.slice(0, -3) + 'y';
      if (type && type.endsWith('s')) return type.slice(0, -1);
      return type || 'item';
    }}
    function updateImportSourcePanes() {{
      const form = importModal?.querySelector('[data-import-form]');
      if (!form) return;
      const selected = form.querySelector('[name="import_source"]:checked')?.value || 'paste';
      form.querySelectorAll('[data-import-pane]').forEach(pane => {{
        pane.hidden = pane.dataset.importPane !== selected;
      }});
      if (importBrowser) importBrowser.hidden = selected !== 'path';
    }}
    function openImportModal(type, scope) {{
      if (!importModal) return;
      const form = importModal.querySelector('[data-import-form]');
      if (form) form.reset();
      const typeInput = importModal.querySelector('[data-import-type]');
      const scopeInput = importModal.querySelector('[data-import-scope]');
      const fileNameInput = importModal.querySelector('[data-import-file-name]');
      if (typeInput) typeInput.value = type || 'agents';
      if (scopeInput) scopeInput.value = scope || currentScope();
      if (fileNameInput) fileNameInput.value = '';
      importModal.querySelectorAll('[data-import-error]').forEach(node => node.remove());
      const title = importModal.querySelector('#import-modal-title');
      if (title) title.textContent = 'Import ' + singularLabel(type || 'item');
      importModal.hidden = false;
      updateImportSourcePanes();
      const firstInput = importModal.querySelector('input[name="name"]');
      if (firstInput) firstInput.focus();
    }}
    function closeImportModal() {{
      if (importModal) importModal.hidden = true;
    }}
    async function browseProjectDirs(path) {{
      if (!projectBrowser || !projectPathInput) return;
      projectBrowser.textContent = 'Loading...';
      try {{
        const res = await fetch('/api/browse-dirs?path=' + encodeURIComponent(path || ''));
        const data = await res.json();
        projectPathInput.value = data.path || projectPathInput.value;
        const rows = [];
        rows.push('<div class="browser-current">' + escapeHtml(data.path || '') + '</div>');
        if (data.parent) {{
          rows.push('<button type="button" class="browser-row" data-browse-path="' + escapeAttr(data.parent) + '">..</button>');
        }}
        for (const dir of data.dirs || []) {{
          rows.push('<button type="button" class="browser-row" data-browse-path="' + escapeAttr(dir.path) + '">' + escapeHtml(dir.name) + '</button>');
        }}
        projectBrowser.innerHTML = rows.join('');
      }} catch (_error) {{
        projectBrowser.textContent = 'Unable to browse this path.';
      }}
    }}
    async function browseImportDirs(path) {{
      if (!importBrowser || !importPathInput) return;
      importBrowser.hidden = false;
      importBrowser.textContent = 'Loading...';
      try {{
        const res = await fetch('/api/browse-dirs?path=' + encodeURIComponent(path || ''));
        const data = await res.json();
        importPathInput.value = data.path || importPathInput.value;
        const rows = [];
        rows.push('<div class="browser-current">' + escapeHtml(data.path || '') + '</div>');
        if (data.parent) {{
          rows.push('<button type="button" class="browser-row" data-import-browse-path="' + escapeAttr(data.parent) + '">..</button>');
        }}
        for (const dir of data.dirs || []) {{
          rows.push('<button type="button" class="browser-row" data-import-browse-path="' + escapeAttr(dir.path) + '">' + escapeHtml(dir.name) + '</button>');
        }}
        for (const file of data.files || []) {{
          rows.push('<button type="button" class="browser-row" data-import-file-path="' + escapeAttr(file.path) + '">' + escapeHtml(file.name) + '</button>');
        }}
        importBrowser.innerHTML = rows.join('');
      }} catch (_error) {{
        importBrowser.textContent = 'Unable to browse this path.';
      }}
    }}
    function escapeHtml(value) {{
      return String(value).replace(/[&<>"']/g, char => ({{'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}}[char]));
    }}
    function escapeAttr(value) {{
      return escapeHtml(value).replace(/`/g, '&#96;');
    }}
    function cssEscape(value) {{
      if (window.CSS && typeof window.CSS.escape === 'function') return window.CSS.escape(String(value || ''));
      return String(value || '').replace(/[^a-zA-Z0-9_-]/g, '\\\\$&');
    }}
    function escapeTextarea(value) {{
      const text = escapeHtml(value);
      if (text.startsWith('\\r\\n')) return '&#13;&#10;' + text.slice(2);
      if (text.startsWith('\\n')) return '&#10;' + text.slice(1);
      if (text.startsWith('\\r')) return '&#13;' + text.slice(1);
      return text;
    }}
    function bodySectionPlaceholder(title = '') {{
      const placeholders = {{
        'Communication Protocol': 'Define how the agent should communicate, ask clarifying questions, and handle ambiguity.',
        'Core Mission': 'Describe the agent purpose, primary outcomes, and what success looks like.',
        'Responsibilities': 'List the concrete tasks this agent owns and the boundaries it should respect.',
        'Execution Flow': 'Describe the step-by-step workflow the agent should follow.',
        'Output Format': 'Specify required response structure, artifacts, formats, or acceptance criteria.',
        'Failure Handling': 'Explain what the agent should do when inputs are missing, tools fail, or confidence is low.',
        'Success Metrics': 'Describe how to judge whether this agent performed well.',
        'When To Use': 'Describe the situations where this skill should be selected.',
        'Workflow': 'Write the ordered process the skill should follow.',
        'Examples': 'Add representative examples or prompts that clarify expected usage.',
        'Best Practices': 'List constraints, quality bars, and patterns the skill should apply.',
        'Output Rules': 'Describe required output shape, tone, and formatting.',
        'Troubleshooting': 'Add common failure modes and how to recover.',
        'Usage Notes': 'Explain when and how this MCP server should be used.',
        'Configuration': 'Describe required configuration, commands, URLs, or setup.',
        'Environment': 'List environment variables and operational requirements.',
        'Requirements': 'Define required behavior and constraints.',
        'Exceptions': 'Describe cases where the rule should not apply.',
        'Steps': 'List the workflow steps in execution order.',
        'Guidelines': 'Add decision rules and quality checks for this workflow.',
        'Output': 'Describe the final output, files, or status the workflow should produce.',
      }};
      return placeholders[String(title || '').trim()] || 'Write this section content.';
    }}
    function bodySectionTemplate(title = 'New section', level = '2', content = '', headingSuffix = '\\n\\n', emptyStarter = false, placeholder = '') {{
      const options = [
        ['0', 'None'],
        ['1', 'H1'],
        ['2', 'H2'],
        ['3', 'H3'],
        ['4', 'H4'],
        ['5', 'H5'],
        ['6', 'H6'],
      ].map(([value, label]) => '<option value="' + value + '"' + (String(level) === value ? ' selected' : '') + '>' + label + '</option>').join('');
      return '<article class="body-section" data-body-section data-heading-suffix="' + escapeAttr(headingSuffix) + '"' +
        (emptyStarter ? ' data-empty-starter="true" data-starter-title="' + escapeAttr(title) + '" data-starter-level="' + escapeAttr(level) + '"' : '') + '>' +
        '<div class="body-section-head">' +
          '<label><span>Section</span><input data-body-section-title value="' + escapeAttr(title) + '"></label>' +
          '<label><span>Heading</span><select data-body-section-level>' + options + '</select></label>' +
          '<button type="button" class="secondary body-section-move" data-move-body-section=\"up\">Up</button>' +
          '<button type="button" class="secondary body-section-move" data-move-body-section=\"down\">Down</button>' +
          '<button type="button" class="secondary body-section-preview-toggle" data-toggle-body-preview>Preview</button>' +
          '<button type="button" class="secondary body-section-collapse" data-toggle-body-section>Collapse</button>' +
          '<button type="button" class="secondary body-section-remove" data-remove-body-section>Remove</button>' +
        '</div>' +
        '<label class="wide" data-body-section-content-wrap><span class="body-section-content-label"><span>Content</span><small data-body-section-meta></small></span><textarea data-body-section-content rows="7" placeholder="' + escapeAttr(placeholder || bodySectionPlaceholder(title)) + '">' + escapeTextarea(content) + '</textarea></label>' +
        '<div class="body-section-preview" data-body-section-preview hidden></div>' +
      '</article>';
    }}
    function headingLevelOptions(level = '2') {{
      return [
        ['0', 'None'],
        ['1', 'H1'],
        ['2', 'H2'],
        ['3', 'H3'],
        ['4', 'H4'],
        ['5', 'H5'],
        ['6', 'H6'],
      ].map(([value, label]) => '<option value="' + value + '"' + (String(level) === value ? ' selected' : '') + '>' + label + '</option>').join('');
    }}
    function templateSectionTemplate(title = 'New section', level = '2', content = '') {{
      return '<article class="template-section-row" data-template-section-row>' +
        '<div class="template-section-head">' +
          '<label><span>Section</span><input data-template-section-title value="' + escapeAttr(title) + '" placeholder="Section title"></label>' +
          '<label><span>Heading</span><select data-template-section-level>' + headingLevelOptions(level) + '</select></label>' +
          '<button type="button" class="secondary template-section-move" data-move-template-section="up">Up</button>' +
          '<button type="button" class="secondary template-section-move" data-move-template-section="down">Down</button>' +
          '<button type="button" class="secondary template-section-remove" data-remove-template-section>Remove</button>' +
        '</div>' +
        '<label class="wide"><span>Starter content</span><textarea data-template-section-content rows="4" placeholder="Optional default text for this section">' + escapeTextarea(content) + '</textarea></label>' +
      '</article>';
    }}
    function templateFieldSectionTemplate(title = 'New section', level = '2', content = '') {{
      return '<article class="template-section-row" data-template-field-section-row>' +
        '<div class="template-section-head">' +
          '<label><span>Section</span><input data-template-field-section-title value="' + escapeAttr(title) + '" placeholder="Section title"></label>' +
          '<label><span>Heading</span><select data-template-field-section-level>' + headingLevelOptions(level) + '</select></label>' +
          '<button type="button" class="secondary template-section-move" data-move-template-field-section="up">Up</button>' +
          '<button type="button" class="secondary template-section-move" data-move-template-field-section="down">Down</button>' +
          '<button type="button" class="secondary template-section-remove" data-remove-template-field-section>Remove</button>' +
        '</div>' +
        '<label class="wide"><span>Starter content</span><textarea data-template-field-section-content rows="4" placeholder="Optional default text for this field section">' + escapeTextarea(content) + '</textarea></label>' +
      '</article>';
    }}
    function templateFieldSectionGroupTemplate(key = '', label = '', sections = []) {{
      const sectionRows = (Array.isArray(sections) && sections.length ? sections : [{{ title: 'Overview', level: '2', content: '' }}])
        .map(section => templateFieldSectionTemplate(section.title || '', section.level || '2', section.content || ''))
        .join('');
      return '<article class="template-field-section-row" data-template-field-section-group>' +
        '<div class="template-field-section-head">' +
          '<label><span>Field key</span><input data-template-field-section-key value="' + escapeAttr(key) + '" placeholder="field_key"></label>' +
          '<label><span>Label</span><input data-template-field-section-label value="' + escapeAttr(label) + '" placeholder="Section label"></label>' +
          '<button type="button" class="secondary" data-add-template-field-section>Add section</button>' +
          '<button type="button" class="secondary template-section-remove" data-remove-template-field-section-group>Remove field</button>' +
        '</div>' +
        '<div class="template-field-section-list" data-template-field-section-list>' + sectionRows + '</div>' +
      '</article>';
    }}
    function composeTemplateSections(editor) {{
      const sections = [];
      editor.querySelectorAll('[data-template-section-row]').forEach(row => {{
        const title = (row.querySelector('[data-template-section-title]')?.value || '').trim();
        const content = row.querySelector('[data-template-section-content]')?.value || '';
        const level = row.querySelector('[data-template-section-level]')?.value || '2';
        if (!title && !content.trim()) return;
        sections.push({{ title, level, content }});
      }});
      return JSON.stringify(sections);
    }}
    function composeTemplateFieldSections(editor) {{
      const result = {{}};
      editor.querySelectorAll('[data-template-field-section-group]').forEach(group => {{
        const key = (group.querySelector('[data-template-field-section-key]')?.value || '').trim();
        const label = (group.querySelector('[data-template-field-section-label]')?.value || '').trim();
        if (!key) return;
        const sections = [];
        group.querySelectorAll('[data-template-field-section-row]').forEach(row => {{
          const title = (row.querySelector('[data-template-field-section-title]')?.value || '').trim();
          const content = row.querySelector('[data-template-field-section-content]')?.value || '';
          const level = row.querySelector('[data-template-field-section-level]')?.value || '2';
          if (!title && !content.trim()) return;
          sections.push({{ title, level, content }});
        }});
        if (sections.length) result[key] = {{ label: label || key, sections }};
      }});
      return JSON.stringify(result);
    }}
    function syncTemplateSectionEditor(root = document) {{
      const editors = root.matches && root.matches('[data-template-section-editor]')
        ? [root]
        : Array.from(root.querySelectorAll('[data-template-section-editor]'));
      editors.forEach(editor => {{
        const source = editor.closest('form')?.querySelector('[data-template-sections-source]');
        if (source) source.value = composeTemplateSections(editor);
      }});
    }}
    function syncTemplateFieldSectionEditor(root = document) {{
      const editors = root.matches && root.matches('[data-template-field-section-editor]')
        ? [root]
        : Array.from(root.querySelectorAll('[data-template-field-section-editor]'));
      editors.forEach(editor => {{
        const source = editor.closest('form')?.querySelector('[data-template-field-sections-source]');
        if (source) source.value = composeTemplateFieldSections(editor);
      }});
    }}
    function resetTemplateSectionEditors(root = document) {{
      const editors = root.matches && root.matches('[data-template-section-editor]')
        ? [root]
        : Array.from(root.querySelectorAll('[data-template-section-editor]'));
      editors.forEach(editor => {{
        const source = editor.closest('form')?.querySelector('[data-template-sections-source]');
        const list = editor.querySelector('[data-template-section-list]');
        if (!source || !list) return;
        let sections = [];
        try {{
          sections = JSON.parse(source.value || '[]');
        }} catch (_error) {{
          sections = [];
        }}
        if (!Array.isArray(sections) || !sections.length) sections = [{{ title: 'Overview', level: '2', content: '' }}];
        list.innerHTML = sections.map(section => templateSectionTemplate(section.title || '', section.level || '2', section.content || '')).join('');
        syncTemplateSectionEditor(editor);
      }});
    }}
    function resetTemplateFieldSectionEditors(root = document) {{
      const editors = root.matches && root.matches('[data-template-field-section-editor]')
        ? [root]
        : Array.from(root.querySelectorAll('[data-template-field-section-editor]'));
      editors.forEach(editor => {{
        const source = editor.closest('form')?.querySelector('[data-template-field-sections-source]');
        const list = editor.querySelector('[data-template-field-section-group-list]');
        if (!source || !list) return;
        let definitions = {{}};
        try {{
          definitions = JSON.parse(source.value || '{{}}');
        }} catch (_error) {{
          definitions = {{}};
        }}
        const rows = [];
        for (const [key, definition] of Object.entries(definitions || {{}})) {{
          const sections = definition && Array.isArray(definition.sections) ? definition.sections : [];
          rows.push(templateFieldSectionGroupTemplate(key, definition?.label || key, sections));
        }}
        list.innerHTML = rows.join('');
        syncTemplateFieldSectionEditor(editor);
      }});
    }}
    function templateFieldSectionEditorHasMeaningfulContent(editor) {{
      const groups = Array.from(editor?.querySelectorAll('[data-template-field-section-group]') || []);
      if (!groups.length) return false;
      return groups.some(group => {{
        const key = (group.querySelector('[data-template-field-section-key]')?.value || '').trim();
        const label = (group.querySelector('[data-template-field-section-label]')?.value || '').trim();
        const sections = Array.from(group.querySelectorAll('[data-template-field-section-row]'));
        const hasSectionContent = sections.some(row => {{
          const title = (row.querySelector('[data-template-field-section-title]')?.value || '').trim();
          const content = (row.querySelector('[data-template-field-section-content]')?.value || '').trim();
          return !!content || (!!title && title !== 'Overview');
        }});
        return !!key || !!label || hasSectionContent;
      }});
    }}
    function defaultTemplateFieldSectionsForType(editor, contentType) {{
      if (!editor) return {{}};
      let definitions = {{}};
      try {{
        definitions = JSON.parse(editor.dataset.templateDefaultFieldSections || '{{}}');
      }} catch (_error) {{
        definitions = {{}};
      }}
      const fieldSections = definitions[contentType];
      return fieldSections && typeof fieldSections === 'object' && !Array.isArray(fieldSections) ? fieldSections : {{}};
    }}
    function replaceTemplateFieldSections(editor, definitions) {{
      const list = editor ? editor.querySelector('[data-template-field-section-group-list]') : null;
      if (!list || !definitions || typeof definitions !== 'object' || Array.isArray(definitions)) return false;
      const rows = [];
      Object.entries(definitions).forEach(([key, definition]) => {{
        const sections = definition && Array.isArray(definition.sections) ? definition.sections : [];
        rows.push(templateFieldSectionGroupTemplate(key, definition?.label || key, sections));
      }});
      list.innerHTML = rows.join('');
      syncTemplateFieldSectionEditor(editor);
      return true;
    }}
    function templateSectionEditorHasMeaningfulContent(editor) {{
      const rows = Array.from(editor?.querySelectorAll('[data-template-section-row]') || []);
      if (!rows.length) return false;
      return rows.some(row => {{
        const title = (row.querySelector('[data-template-section-title]')?.value || '').trim();
        const content = (row.querySelector('[data-template-section-content]')?.value || '').trim();
        return !!content || (!!title && title !== 'Overview');
      }});
    }}
    function defaultTemplateSectionsForType(editor, contentType) {{
      if (!editor) return [];
      let definitions = {{}};
      try {{
        definitions = JSON.parse(editor.dataset.templateDefaultSections || '{{}}');
      }} catch (_error) {{
        definitions = {{}};
      }}
      const sections = definitions[contentType];
      return Array.isArray(sections) ? sections : [];
    }}
    function replaceTemplateSections(editor, sections) {{
      const list = editor ? editor.querySelector('[data-template-section-list]') : null;
      if (!list || !Array.isArray(sections) || !sections.length) return false;
      list.innerHTML = sections.map(section => {{
        const title = Array.isArray(section) ? section[0] : section.title;
        const level = Array.isArray(section) ? section[1] : section.level;
        const content = Array.isArray(section) ? section[2] : section.content;
        return templateSectionTemplate(title || '', level || '2', content || '');
      }}).join('');
      syncTemplateSectionEditor(editor);
      return true;
    }}
    function maybeRefreshTemplateSectionsForType(form, force = false) {{
      const typeSelect = form?.querySelector('[data-template-type-select]');
      const editor = form?.querySelector('[data-template-section-editor]');
      if (!typeSelect || !editor) return false;
      if (!force && templateSectionEditorHasMeaningfulContent(editor)) return false;
      const sections = defaultTemplateSectionsForType(editor, typeSelect.value || 'agents');
      const updated = replaceTemplateSections(editor, sections);
      if (updated) updateContentModalDirtyState();
      return updated;
    }}
    function maybeRefreshTemplateFieldSectionsForType(form, force = false) {{
      const typeSelect = form?.querySelector('[data-template-type-select]');
      const editor = form?.querySelector('[data-template-field-section-editor]');
      if (!typeSelect || !editor) return false;
      if (!force && templateFieldSectionEditorHasMeaningfulContent(editor)) return false;
      const definitions = defaultTemplateFieldSectionsForType(editor, typeSelect.value || 'agents');
      const updated = replaceTemplateFieldSections(editor, definitions);
      if (updated) updateContentModalDirtyState();
      return updated;
    }}
    function inlineMarkdown(value) {{
      let text = escapeHtml(value || '');
      text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
      text = text.replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>');
      text = text.replace(/\\*([^*]+)\\*/g, '<em>$1</em>');
      text = text.replace(/\\[([^\\]]+)\\]\\(([^)]+)\\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
      return text;
    }}
    function renderSectionMarkdown(text) {{
      const blocks = [];
      const lines = String(text || '').split(/\\r?\\n/);
      let paragraph = [];
      let list = [];
      let code = [];
      let inFence = false;
      function flushParagraph() {{
        if (paragraph.length) {{
          blocks.push('<p>' + inlineMarkdown(paragraph.join(' ')) + '</p>');
          paragraph = [];
        }}
      }}
      function flushList() {{
        if (list.length) {{
          blocks.push('<ul>' + list.map(item => '<li>' + inlineMarkdown(item) + '</li>').join('') + '</ul>');
          list = [];
        }}
      }}
      function flushCode() {{
        if (code.length) {{
          blocks.push('<pre><code>' + escapeHtml(code.join('\\n')) + '</code></pre>');
          code = [];
        }}
      }}
      for (const line of lines) {{
        if (/^\\s*(```|~~~)/.test(line)) {{
          if (inFence) {{
            flushCode();
            inFence = false;
          }} else {{
            flushParagraph();
            flushList();
            inFence = true;
          }}
          continue;
        }}
        if (inFence) {{
          code.push(line);
          continue;
        }}
        const heading = line.match(/^(#{{1,6}})\\s+(.+?)\\s*$/);
        if (heading) {{
          flushParagraph();
          flushList();
          const level = Math.min(6, heading[1].length + 2);
          blocks.push('<h' + level + '>' + inlineMarkdown(heading[2]) + '</h' + level + '>');
          continue;
        }}
        const bullet = line.match(/^\\s*[-*+]\\s+(.+?)\\s*$/);
        if (bullet) {{
          flushParagraph();
          list.push(bullet[1]);
          continue;
        }}
        if (!line.trim()) {{
          flushParagraph();
          flushList();
          continue;
        }}
        paragraph.push(line.trim());
      }}
      flushCode();
      flushParagraph();
      flushList();
      return blocks.join('') || '<p class="empty">Nothing to preview.</p>';
    }}
    function updateBodySectionPreview(section) {{
      const preview = section?.querySelector('[data-body-section-preview]');
      const content = section?.querySelector('[data-body-section-content]');
      if (preview && content) preview.innerHTML = renderSectionMarkdown(content.value);
    }}
    function pluralizeCount(count, singular) {{
      return String(count) + ' ' + singular + (count === 1 ? '' : 's');
    }}
    function updateBodySectionMeta(section) {{
      if (!section) return;
      const title = (section.querySelector('[data-body-section-title]')?.value || '').trim();
      const content = section.querySelector('[data-body-section-content]');
      const meta = section.querySelector('[data-body-section-meta]');
      if (content && title) content.placeholder = bodySectionPlaceholder(title);
      if (!content || !meta) return;
      const text = content.value || '';
      const lines = text ? text.replace(/\\r\\n/g, '\\n').split('\\n').length : 0;
      const words = text.trim() ? text.trim().split(/\\s+/).length : 0;
      meta.textContent = pluralizeCount(lines, 'line') + ' • ' + pluralizeCount(words, 'word');
    }}
    function bodySectionHasMeaningfulContent(section) {{
      if (!section) return false;
      const title = (section.querySelector('[data-body-section-title]')?.value || '').trim();
      const content = (section.querySelector('[data-body-section-content]')?.value || '').trim();
      return !!(title || content);
    }}
    function addBodySectionUndo(list, section, editor) {{
      if (!list || !section) return;
      const undo = document.createElement('div');
      undo.className = 'body-section-undo';
      undo.innerHTML = '<span>Section removed.</span><button type="button" class="secondary" data-undo-body-section>Undo</button>';
      undo._removedSection = section;
      undo._editor = editor;
      list.insertBefore(undo, section.nextSibling);
      section.remove();
    }}
    function setBodySectionPreview(section, visible) {{
      if (!section) return;
      const preview = section.querySelector('[data-body-section-preview]');
      const button = section.querySelector('[data-toggle-body-preview]');
      if (preview) {{
        if (visible) updateBodySectionPreview(section);
        preview.hidden = !visible;
      }}
      if (button) {{
        button.textContent = visible ? 'Hide preview' : 'Preview';
        button.setAttribute('aria-pressed', visible ? 'true' : 'false');
      }}
    }}
    function splitBodySections(text) {{
      const sections = [];
      let currentTitle = 'Overview';
      let currentLevel = '0';
      let currentLines = [];
      let foundHeading = false;
      let fenceMarker = '';
      let fenceLength = 0;
      let currentHeadingSuffix = '';
      const rawLines = String(text || '').match(/.*(?:\\r?\\n|$)/g) || [];
      if (rawLines.length && rawLines[rawLines.length - 1] === '') rawLines.pop();
      for (const line of rawLines) {{
        const lineText = line.replace(/\\r?\\n$/, '');
        const fence = lineText.match(/^\\s*(`{{3,}}|~{{3,}})/);
        if (fence) {{
          const marker = fence[1][0];
          const length = fence[1].length;
          if (!fenceMarker) {{
            fenceMarker = marker;
            fenceLength = length;
          }} else if (marker === fenceMarker && length >= fenceLength) {{
            fenceMarker = '';
            fenceLength = 0;
          }}
          currentLines.push(line);
          continue;
        }}
        const match = lineText.match(/^(#{{1,6}})\\s+(.+?)\\s*$/);
        if (!fenceMarker && match) {{
          if (currentLines.length || foundHeading) {{
            sections.push({{ title: currentTitle, level: currentLevel, content: currentLines.join(''), headingSuffix: currentHeadingSuffix }});
          }}
          currentTitle = match[2].trim();
          currentLevel = String(match[1].length);
          currentHeadingSuffix = (line.match(/\\r?\\n$/) || [''])[0];
          currentLines = [];
          foundHeading = true;
        }} else {{
          currentLines.push(line);
        }}
      }}
      if (currentLines.length || foundHeading || String(text || '')) {{
        sections.push({{ title: currentTitle, level: currentLevel, content: currentLines.join(''), headingSuffix: currentHeadingSuffix }});
      }}
      if (!sections.length) sections.push({{ title: 'Overview', level: '0', content: '', headingSuffix: '' }});
      return sections;
    }}
    function renderBodySections(editor, body) {{
      const list = editor.querySelector('[data-body-section-list]');
      if (!list) return;
      list.innerHTML = '';
      let sections = splitBodySections(body);
      if (!String(body || '') && editor.dataset.starterSections) {{
        try {{
          const starter = JSON.parse(editor.dataset.starterSections);
          if (Array.isArray(starter) && starter.length) {{
            sections = starter.map(([title, level, content]) => ({{ title, level: String(level || '2'), content: content || '', headingSuffix: '\\n\\n', emptyStarter: true }}));
          }}
        }} catch (_error) {{}}
      }}
      sections.forEach(section => {{
        const wrapper = document.createElement('div');
        wrapper.innerHTML = bodySectionTemplate(section.title, section.level, section.content, section.headingSuffix || '', !!section.emptyStarter);
        const node = wrapper.firstElementChild;
        if (!node) return;
        const content = node.querySelector('[data-body-section-content]');
        if (content) content.value = section.content || '';
        updateBodySectionMeta(node);
        list.appendChild(node);
      }});
    }}
    function bodyPresetSections(editor) {{
      const raw = editor?.dataset.presetSections || editor?.dataset.starterSections || '';
      if (!raw) return [];
      try {{
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed : [];
      }} catch (_error) {{
        return [];
      }}
    }}
    function updateBodyPresetSelect(editor) {{
      const select = editor ? editor.querySelector('[data-body-section-preset]') : null;
      if (!select) return;
      const options = ['<option value="">Custom section</option>'];
      for (const [title, level, content] of bodyPresetSections(editor)) {{
        if (!title) continue;
        options.push('<option value="' + escapeAttr(title) + '" data-level="' + escapeAttr(level || '2') + '" data-content="' + escapeAttr(content || '') + '">' + escapeHtml(title) + '</option>');
      }}
      select.innerHTML = options.join('');
    }}
    function setBodyTemplate(editor, templateName, addMissing = true) {{
      if (!editor) return;
      let definitions = {{}};
      try {{
        definitions = JSON.parse(editor.dataset.templateDefinitions || '{{}}');
      }} catch (_error) {{
        definitions = {{}};
      }}
      const sections = Array.isArray(definitions[templateName]) ? definitions[templateName] : [];
      if (sections.length) {{
        editor.dataset.presetSections = JSON.stringify(sections);
        updateBodyPresetSelect(editor);
        if (addMissing) addMissingBodySections(editor);
      }}
    }}
    function bodyTemplateEditorFor(control) {{
      return control?.closest('[data-body-section-editor]') ||
        control?.closest('form.edit-form')?.querySelector('[data-body-section-editor]') ||
        document.querySelector('[data-content-modal] form.edit-form [data-body-section-editor]');
    }}
    function itemTemplateControlsFor(control) {{
      return control?.closest('[data-item-template-controls]') ||
        control?.closest('form.edit-form')?.querySelector('[data-item-template-controls]') ||
        document.querySelector('[data-content-modal] form.edit-form [data-item-template-controls]');
    }}
    function templateFieldValues(editor, templateName) {{
      if (!editor) return {{}};
      let definitions = {{}};
      try {{
        definitions = JSON.parse(editor.dataset.templateFieldDefinitions || '{{}}');
      }} catch (_error) {{
        definitions = {{}};
      }}
      const fields = definitions[templateName];
      return fields && typeof fields === 'object' && !Array.isArray(fields) ? fields : {{}};
    }}
    function templateFieldSectionValues(editor, templateName) {{
      if (!editor) return {{}};
      let definitions = {{}};
      try {{
        definitions = JSON.parse(editor.dataset.templateFieldSectionDefinitions || '{{}}');
      }} catch (_error) {{
        definitions = {{}};
      }}
      const fields = definitions[templateName];
      return fields && typeof fields === 'object' && !Array.isArray(fields) ? fields : {{}};
    }}
    function sectionedFieldDefinitionToText(definition) {{
      const parts = [];
      for (const section of definition && Array.isArray(definition.sections) ? definition.sections : []) {{
        const title = String(section.title || '').trim();
        const level = String(section.level || '2');
        const content = String(section.content || '');
        if (!title && !content.trim()) continue;
        if (title && level !== '0') {{
          parts.push('#'.repeat(Math.max(1, Math.min(6, Number(level) || 2))) + ' ' + title + (content ? '\\n\\n' + content : ''));
        }} else {{
          parts.push(content);
        }}
      }}
      return parts.filter(part => String(part || '').trim()).join('\\n\\n');
    }}
    function bodyTemplateSections(editor, templateName) {{
      if (!editor) return [];
      let definitions = {{}};
      try {{
        definitions = JSON.parse(editor.dataset.templateDefinitions || '{{}}');
      }} catch (_error) {{
        definitions = {{}};
      }}
      const sections = Array.isArray(definitions[templateName]) ? definitions[templateName] : [];
      return sections.map(([title, level, content]) => ({{
        title: title || 'New section',
        level: String(level || '2'),
        content: content || '',
        headingSuffix: '\\n\\n',
        emptyStarter: true,
      }}));
    }}
    function valueToText(value) {{
      if (value === null || value === undefined) return '';
      if (Array.isArray(value)) return value.join('\\n');
      if (typeof value === 'object') return JSON.stringify(value, null, 2);
      return String(value);
    }}
    function valueToYamlInline(value) {{
      if (value === null || value === undefined) return 'null';
      if (Array.isArray(value) || typeof value === 'object') return JSON.stringify(value);
      return yamlValue(value);
    }}
    function resetListFieldValues(editor, values) {{
      const list = editor.querySelector('[data-list-field-list]');
      if (!list) return;
      const items = Array.isArray(values) ? values : String(values || '').split(/[\\n,]+/).map(item => item.trim()).filter(Boolean);
      list.innerHTML = '';
      (items.length ? items : ['']).forEach(value => list.insertAdjacentHTML('beforeend', listFieldItemTemplate(String(value))));
      syncListFieldEditor(editor);
    }}
    function resetMappingFieldValues(editor, value) {{
      const list = editor.querySelector('[data-mapping-field-list]');
      if (!list) return;
      const entries = value && typeof value === 'object' && !Array.isArray(value) ? Object.entries(value) : [];
      list.innerHTML = '';
      if (!entries.length) {{
        list.innerHTML = mappingFieldItemTemplate();
      }} else {{
        entries.forEach(([key, item]) => {{
          const mode = item && typeof item === 'object' ? 'yaml' : 'string';
          const text = mode === 'yaml' ? JSON.stringify(item, null, 2) : String(item ?? '');
          list.insertAdjacentHTML('beforeend', mappingFieldItemTemplate(String(key), text, mode));
        }});
      }}
      syncMappingFieldEditor(editor);
    }}
    function setExtraFieldValue(form, key, value) {{
      const editor = form.querySelector('[data-extra-fields-editor]');
      const list = editor ? editor.querySelector('[data-extra-fields-list]') : null;
      if (!editor || !list || !key) return false;
      let row = Array.from(list.querySelectorAll('[data-extra-field-row]')).find(candidate => {{
        return (candidate.querySelector('[data-extra-field-key]')?.value || '').trim() === key;
      }});
      if (!row) {{
        row = Array.from(list.querySelectorAll('[data-extra-field-row]')).find(candidate => {{
          const existingKey = (candidate.querySelector('[data-extra-field-key]')?.value || '').trim();
          const existingValue = (candidate.querySelector('[data-extra-field-value]')?.value || '').trim();
          return !existingKey && !existingValue;
        }});
      }}
      if (!row) {{
        list.insertAdjacentHTML('beforeend', extraFieldTemplate());
        row = list.querySelector('[data-extra-field-row]:last-child');
      }}
      if (!row) return false;
      const keyInput = row.querySelector('[data-extra-field-key]');
      const valueInput = row.querySelector('[data-extra-field-value]');
      const modeInput = row.querySelector('[data-value-mode]');
      if (keyInput) keyInput.value = key;
      if (valueInput) valueInput.value = valueToText(value);
      if (modeInput) modeInput.value = value && typeof value === 'object' ? 'yaml' : 'string';
      syncExtraFieldEditor(editor);
      return true;
    }}
    function setCapabilityFieldValues(form, key, value) {{
      const normalized = key === 'mcp-servers' ? 'mcp_servers' : key;
      const inputName = normalized === 'skills' ? 'field_agent_skills' : normalized === 'mcp_servers' ? 'field_agent_mcp_servers' : '';
      if (!inputName) return false;
      const values = new Set((Array.isArray(value) ? value : String(value || '').split(/[\\n,]+/)).map(item => String(item || '').trim()).filter(Boolean));
      const inputs = Array.from(form.querySelectorAll('[name="' + inputName + '"]'));
      if (!inputs.length) return false;
      inputs.forEach(input => {{
        if (input.type === 'hidden') return;
        input.checked = values.has(input.value);
        const option = input.closest('.capability-option');
        const source = option ? option.querySelector('.capability-source') : null;
        if (source) source.textContent = input.checked ? 'Override' : (source.dataset.defaultLabel || 'Available');
      }});
      return true;
    }}
    function applyTemplateFieldsToForm(form, fields) {{
      if (!form || !fields || typeof fields !== 'object') return 0;
      let applied = 0;
      for (const [key, value] of Object.entries(fields)) {{
        if (!key || key === 'name') continue;
        const directControl = form.querySelector('[name="' + cssEscape(key) + '"]');
        if (directControl && !directControl.matches('[name^="field_"]')) {{
          if (directControl.type === 'checkbox') directControl.checked = !!value;
          else directControl.value = valueToText(value);
          applied += 1;
          continue;
        }}
        if (setCapabilityFieldValues(form, key, value)) {{
          applied += 1;
          continue;
        }}
        const controls = Array.from(form.querySelectorAll('[name^="field_"]'))
          .filter(control => control.getAttribute('name') === 'field_' + key);
        const checkbox = controls.find(control => control.type === 'checkbox');
        if (checkbox) {{
          checkbox.checked = !!value;
          applied += 1;
          continue;
        }}
        const source = controls.find(control => control.matches('textarea[data-list-field-source], textarea[data-mapping-field-source], textarea[data-body-source]'));
        if (source) {{
          const listEditor = source.closest('[data-list-field-editor]');
          const mappingEditor = source.closest('[data-mapping-field-editor]');
          const bodyEditor = source.closest('[data-body-section-editor]');
          if (listEditor) resetListFieldValues(listEditor, value);
          else if (mappingEditor) resetMappingFieldValues(mappingEditor, value);
          else if (bodyEditor) {{
            source.value = valueToText(value);
            renderBodySections(bodyEditor, source.value);
            markBodySectionEditorDirty(bodyEditor);
          }}
          else source.value = valueToYamlInline(value);
          applied += 1;
          continue;
        }}
        const control = controls.find(item => item.type !== 'hidden') || controls[0];
        if (control) {{
          control.value = valueToText(value);
          applied += 1;
          continue;
        }}
        if (setExtraFieldValue(form, key, value)) applied += 1;
      }}
      syncStructuredEditors(form);
      return applied;
    }}
    function applyTemplateFieldSectionsToForm(form, fieldSections) {{
      if (!form || !fieldSections || typeof fieldSections !== 'object') return 0;
      let applied = 0;
      const keyInput = form.querySelector('[name="sectioned_field_keys"]');
      const knownKeys = new Set(String(keyInput?.value || '').split(',').map(item => item.trim()).filter(Boolean));
      for (const [key, definition] of Object.entries(fieldSections)) {{
        if (!key || !definition || typeof definition !== 'object') continue;
        const text = sectionedFieldDefinitionToText(definition);
        const source = form.querySelector('[name="field_' + cssEscape(key) + '"][data-body-source]');
        if (source) {{
          const editor = source.closest('[data-body-section-editor]');
          source.value = text;
          if (editor) {{
            renderBodySections(editor, text);
            markBodySectionEditorDirty(editor);
            syncBodySectionEditor(editor);
          }}
          knownKeys.add(key);
          applied += 1;
        }} else if (setExtraFieldValue(form, key, text)) {{
          applied += 1;
        }}
      }}
      if (keyInput) keyInput.value = Array.from(knownKeys).join(',');
      syncStructuredEditors(form);
      return applied;
    }}
    function bodySectionListHasContent(list) {{
      if (!list) return false;
      return Array.from(list.querySelectorAll('[data-body-section]')).some(section => {{
        const title = (section.querySelector('[data-body-section-title]')?.value || '').trim();
        const content = (section.querySelector('[data-body-section-content]')?.value || '').trim();
        const starterTitle = (section.dataset.starterTitle || '').trim();
        return !!content || (!!title && title !== starterTitle && title !== 'Overview');
      }});
    }}
    function replaceBodySectionsFromTemplate(control) {{
      const editor = bodyTemplateEditorFor(control);
      const controls = itemTemplateControlsFor(control);
      const select = controls ? controls.querySelector('[data-body-template-select]') : editor?.querySelector('[data-body-template-select]');
      const list = editor ? editor.querySelector('[data-body-section-list]') : null;
      const sections = bodyTemplateSections(editor, select ? select.value : '');
      const fields = templateFieldValues(controls || editor, select ? select.value : '');
      const fieldSections = templateFieldSectionValues(controls || editor, select ? select.value : '');
      if (!editor || !list || (!sections.length && !Object.keys(fields).length && !Object.keys(fieldSections).length)) return false;
      if (sections.length && bodySectionListHasContent(list) && !window.confirm('Replace current body sections with the selected template?')) return false;
      if (sections.length) {{
        list.innerHTML = '';
        sections.forEach(section => {{
          const wrapper = document.createElement('div');
          wrapper.innerHTML = bodySectionTemplate(section.title, section.level, section.content, section.headingSuffix, section.emptyStarter);
          const node = wrapper.firstElementChild;
          if (!node) return;
          const content = node.querySelector('[data-body-section-content]');
          if (content) content.value = section.content || '';
          updateBodySectionMeta(node);
          list.appendChild(node);
        }});
        markBodySectionEditorDirty(editor);
        syncBodySectionEditor(editor);
      }}
      const form = editor.closest('form.edit-form');
      applyTemplateFieldsToForm(form, fields);
      applyTemplateFieldSectionsToForm(form, fieldSections);
      updateContentModalDirtyState();
      return true;
    }}
    function applyItemTemplateFromControls(control) {{
      const container = itemTemplateControlsFor(control);
      const form = container?.closest('form.edit-form');
      const select = container?.querySelector('[data-body-template-select]');
      if (!container || !form || !select) return false;
      const applied = applyTemplateFieldsToForm(form, templateFieldValues(container, select.value || '')) +
        applyTemplateFieldSectionsToForm(form, templateFieldSectionValues(container, select.value || ''));
      if (applied) updateContentModalDirtyState();
      return applied > 0;
    }}
    async function saveBodyAsTemplate(button) {{
      const form = button?.closest('form.edit-form');
      const editor = bodyTemplateEditorFor(button);
      const controls = itemTemplateControlsFor(button);
      if (!form || (!editor && !controls)) return;
      syncStructuredEditors(form);
      const currentName = (form.querySelector('[name="name"]')?.value || '').trim();
      const fallbackType = editor?.dataset.templateContentType || controls?.dataset.templateContentType || 'template';
      const fallback = (currentName || fallbackType) + '-template';
      const templateName = window.prompt('Template name', fallback);
      if (!templateName) return;
      const data = new URLSearchParams();
      for (const [key, value] of new FormData(form).entries()) data.append(key, value);
      const editorType = form.querySelector('[name="type"]')?.value ||
        form.closest('[data-content-modal]')?.querySelector('[data-editor-type]')?.dataset.editorType ||
        editor?.dataset.templateContentType ||
        controls?.dataset.templateContentType ||
        '';
      if (editorType) data.set('type', editorType);
      data.set('template_name', templateName);
      const res = await fetch('/templates/from-item', {{ method: 'POST', body: data }});
      const payload = await res.json();
      if (!payload.ok) {{
        showModalClientError(payload.error || 'Template could not be saved.', button);
        return;
      }}
      let definitions = {{}};
      if (editor) {{
        try {{
          definitions = JSON.parse(editor.dataset.templateDefinitions || '{{}}');
        }} catch (_error) {{
          definitions = {{}};
        }}
        definitions[payload.name] = payload.sections || [];
        editor.dataset.templateDefinitions = JSON.stringify(definitions);
      }}
      let fieldDefinitions = {{}};
      try {{
        fieldDefinitions = JSON.parse((controls || editor).dataset.templateFieldDefinitions || '{{}}');
      }} catch (_error) {{
        fieldDefinitions = {{}};
      }}
      fieldDefinitions[payload.name] = payload.fields || {{}};
      if (editor) editor.dataset.templateFieldDefinitions = JSON.stringify(fieldDefinitions);
      if (controls) controls.dataset.templateFieldDefinitions = JSON.stringify(fieldDefinitions);
      let fieldSectionDefinitions = {{}};
      try {{
        fieldSectionDefinitions = JSON.parse((controls || editor).dataset.templateFieldSectionDefinitions || '{{}}');
      }} catch (_error) {{
        fieldSectionDefinitions = {{}};
      }}
      fieldSectionDefinitions[payload.name] = payload.field_sections || {{}};
      if (editor) editor.dataset.templateFieldSectionDefinitions = JSON.stringify(fieldSectionDefinitions);
      if (controls) controls.dataset.templateFieldSectionDefinitions = JSON.stringify(fieldSectionDefinitions);
      const select = form.querySelector('[data-body-template-select]');
      if (select && !Array.from(select.options).some(option => option.value === payload.name)) {{
        select.insertAdjacentHTML('beforeend', '<option value="' + escapeAttr(payload.name) + '">' + escapeHtml(payload.name) + '</option>');
      }}
      if (select) select.value = payload.name;
      if (editor) setBodyTemplate(editor, payload.name, false);
    }}
    function addMissingBodySections(editor) {{
      const list = editor ? editor.querySelector('[data-body-section-list]') : null;
      if (!list) return 0;
      const existing = new Set(
        Array.from(list.querySelectorAll('[data-body-section-title]'))
          .map(input => String(input.value || '').trim().toLowerCase())
          .filter(Boolean)
      );
      let addedCount = 0;
      for (const [title, level, content] of bodyPresetSections(editor)) {{
        const key = String(title || '').trim().toLowerCase();
        if (!key || existing.has(key)) continue;
        list.insertAdjacentHTML('beforeend', bodySectionTemplate(title, String(level || '2'), content || '', '\\n\\n', true));
        updateBodySectionMeta(list.querySelector('[data-body-section]:last-child'));
        existing.add(key);
        addedCount += 1;
      }}
      if (addedCount) syncBodySectionEditor(editor);
      return addedCount;
    }}
    function setBodySectionCollapsed(section, collapsed) {{
      if (!section) return;
      section.dataset.collapsed = collapsed ? 'true' : 'false';
      const body = section.querySelector('[data-body-section-content-wrap]');
      if (body) body.hidden = collapsed;
      const button = section.querySelector('[data-toggle-body-section]');
      if (button) {{
        button.textContent = collapsed ? 'Expand' : 'Collapse';
        button.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
      }}
    }}
    function resetBodySectionEditors(root = document) {{
      const editors = root.matches && root.matches('[data-body-section-editor]')
        ? [root]
        : Array.from(root.querySelectorAll('[data-body-section-editor]'));
      editors.forEach(editor => {{
        const source = editor.querySelector('[data-body-source]');
        if (!source) return;
        renderBodySections(editor, source.value);
        editor.querySelectorAll('[data-body-section]').forEach(section => setBodySectionPreview(section, false));
        editor.dataset.bodyDirty = 'false';
      }});
    }}
    function markBodySectionEditorDirty(editor) {{
      if (editor) editor.dataset.bodyDirty = 'true';
    }}
    function composeBodySections(editor) {{
      const parts = [];
      function pushBodyPart(text) {{
        if (!text) return;
        if (parts.length && !/[\\r\\n]$/.test(parts[parts.length - 1]) && !/^[\\r\\n]/.test(text)) {{
          parts.push('\\n\\n' + text);
        }} else {{
          parts.push(text);
        }}
      }}
      editor.querySelectorAll('[data-body-section]').forEach(section => {{
        const title = (section.querySelector('[data-body-section-title]')?.value || '').trim();
        const level = section.querySelector('[data-body-section-level]')?.value || '0';
        const content = section.querySelector('[data-body-section-content]')?.value || '';
        const headingSuffix = section.dataset.headingSuffix !== undefined ? section.dataset.headingSuffix : '\\n\\n';
        const unchangedStarter = section.dataset.emptyStarter === 'true' &&
          !content.trim() &&
          title === (section.dataset.starterTitle || '').trim() &&
          level === (section.dataset.starterLevel || '0');
        if (unchangedStarter) return;
        let text = content;
        if (level !== '0' && title) {{
          const suffix = headingSuffix || (content ? '\\n\\n' : '');
          text = '#'.repeat(Number(level)) + ' ' + title + suffix + content;
        }}
        pushBodyPart(text);
      }});
      return parts.join('');
    }}
    function syncBodySectionEditor(root = document) {{
      const editors = root.matches && root.matches('[data-body-section-editor]')
        ? [root]
        : Array.from(root.querySelectorAll('[data-body-section-editor]'));
      editors.forEach(editor => {{
        const source = editor.querySelector('[data-body-source]');
        if (source && editor.dataset.bodyDirty === 'true') source.value = composeBodySections(editor);
      }});
    }}
    function valueModeOptions(selected = 'string') {{
      return '<option value="string"' + (selected === 'string' ? ' selected' : '') + '>String</option>' +
        '<option value="yaml"' + (selected === 'yaml' ? ' selected' : '') + '>YAML</option>';
    }}
    function extraFieldTemplate(key = '', value = '', mode = 'string') {{
      return '<div class="extra-field-row" data-extra-field-row data-extra-field-dynamic>' +
        '<label><span>Key</span><input data-extra-field-key value="' + escapeAttr(key) + '" placeholder="field_name"></label>' +
        '<label><span>Type</span><select data-value-mode>' + valueModeOptions(mode) + '</select></label>' +
        '<label><span>Value</span><textarea data-extra-field-value rows="2" placeholder="value">' + escapeHtml(value) + '</textarea></label>' +
        '<button type="button" class="secondary extra-field-remove" data-remove-extra-field>Remove</button>' +
      '</div>';
    }}
    function yamlValue(value) {{
      const text = String(value || '');
      if (text.includes('\\n')) {{
        return '|\\n' + text.split('\\n').map(line => '  ' + line).join('\\n');
      }}
      return JSON.stringify(text);
    }}
    function yamlEntry(key, valueYaml) {{
      const yaml = String(valueYaml || '""');
      if (yaml.includes('\\n') && !yaml.trimStart().startsWith('|')) {{
        return JSON.stringify(key) + ':\\n' + yaml.split('\\n').map(line => '  ' + line).join('\\n');
      }}
      return JSON.stringify(key) + ': ' + yaml;
    }}
    function rowYamlValue(row, key, value) {{
      const originalKey = row.dataset.originalKey || '';
      const originalValue = row.dataset.originalValue || '';
      const originalYaml = row.dataset.originalYaml || '';
      const originalMode = row.dataset.originalMode || '';
      const mode = row.querySelector('[data-value-mode]')?.value || 'string';
      if (originalYaml && key === originalKey && value === originalValue && (!originalMode || mode === originalMode)) return originalYaml;
      if (mode === 'yaml') return String(value || '').trim() || 'null';
      return yamlValue(value);
    }}
    function composeExtraFields(editor) {{
      const lines = [];
      editor.querySelectorAll('[data-extra-field-row]').forEach(row => {{
        const key = (row.querySelector('[data-extra-field-key]')?.value || '').trim();
        const value = row.querySelector('[data-extra-field-value]')?.value || '';
        if (!key) return;
        lines.push(yamlEntry(key, rowYamlValue(row, key, value)));
      }});
      return lines.join('\\n');
    }}
    function resetExtraFieldEditors(root = document) {{
      const editors = root.matches && root.matches('[data-extra-fields-editor]')
        ? [root]
        : Array.from(root.querySelectorAll('[data-extra-fields-editor]'));
      editors.forEach(editor => {{
        const list = editor.querySelector('[data-extra-fields-list]');
        if (!list) return;
        list.querySelectorAll('[data-extra-field-dynamic]').forEach(row => row.remove());
        if (!list.querySelector('[data-extra-field-row]')) list.innerHTML = extraFieldTemplate();
        syncExtraFieldEditor(editor);
      }});
    }}
    function syncExtraFieldEditor(root = document) {{
      const editors = root.matches && root.matches('[data-extra-fields-editor]')
        ? [root]
        : Array.from(root.querySelectorAll('[data-extra-fields-editor]'));
      editors.forEach(editor => {{
        const source = editor.querySelector('[data-extra-fields-source]');
        if (source) source.value = composeExtraFields(editor);
      }});
    }}
    function listFieldItemTemplate(value = '') {{
      return '<div class="list-field-row" data-list-field-row data-list-field-dynamic>' +
        '<label><span>Value</span><input data-list-field-value value="' + escapeAttr(value) + '"></label>' +
        '<button type="button" class="secondary list-field-remove" data-remove-list-field-item>Remove</button>' +
      '</div>';
    }}
    function composeListField(editor) {{
      const values = [];
      editor.querySelectorAll('[data-list-field-value]').forEach(input => {{
        const value = (input.value || '').trim();
        if (value) values.push(value);
      }});
      return values.map(value => '- ' + yamlValue(value)).join('\\n');
    }}
    function resetListFieldEditors(root = document) {{
      const editors = root.matches && root.matches('[data-list-field-editor]')
        ? [root]
        : Array.from(root.querySelectorAll('[data-list-field-editor]'));
      editors.forEach(editor => {{
        const list = editor.querySelector('[data-list-field-list]');
        if (!list) return;
        list.querySelectorAll('[data-list-field-dynamic]').forEach(row => row.remove());
        if (!list.querySelector('[data-list-field-row]')) list.innerHTML = listFieldItemTemplate();
        syncListFieldEditor(editor);
      }});
    }}
    function syncListFieldEditor(root = document) {{
      const editors = root.matches && root.matches('[data-list-field-editor]')
        ? [root]
        : Array.from(root.querySelectorAll('[data-list-field-editor]'));
      editors.forEach(editor => {{
        const source = editor.querySelector('[data-list-field-source]');
        if (source) source.value = composeListField(editor);
      }});
    }}
    function mappingFieldItemTemplate(key = '', value = '', mode = 'string') {{
      return '<div class="mapping-field-row" data-mapping-field-row data-mapping-field-dynamic>' +
        '<label><span>Key</span><input data-mapping-field-key value="' + escapeAttr(key) + '" placeholder="KEY"></label>' +
        '<label><span>Type</span><select data-value-mode>' + valueModeOptions(mode) + '</select></label>' +
        '<label><span>Value</span><textarea data-mapping-field-value rows="2" placeholder="value">' + escapeHtml(value) + '</textarea></label>' +
        '<button type="button" class="secondary mapping-field-remove" data-remove-mapping-field-item>Remove</button>' +
      '</div>';
    }}
    function composeMappingField(editor) {{
      const lines = [];
      editor.querySelectorAll('[data-mapping-field-row]').forEach(row => {{
        const key = (row.querySelector('[data-mapping-field-key]')?.value || '').trim();
        const value = row.querySelector('[data-mapping-field-value]')?.value || '';
        if (!key) return;
        lines.push(yamlEntry(key, rowYamlValue(row, key, value)));
      }});
      return lines.join('\\n');
    }}
    function resetMappingFieldEditors(root = document) {{
      const editors = root.matches && root.matches('[data-mapping-field-editor]')
        ? [root]
        : Array.from(root.querySelectorAll('[data-mapping-field-editor]'));
      editors.forEach(editor => {{
        const list = editor.querySelector('[data-mapping-field-list]');
        if (!list) return;
        list.querySelectorAll('[data-mapping-field-dynamic]').forEach(row => row.remove());
        if (!list.querySelector('[data-mapping-field-row]')) list.innerHTML = mappingFieldItemTemplate();
        syncMappingFieldEditor(editor);
      }});
    }}
    function syncMappingFieldEditor(root = document) {{
      const editors = root.matches && root.matches('[data-mapping-field-editor]')
        ? [root]
        : Array.from(root.querySelectorAll('[data-mapping-field-editor]'));
      editors.forEach(editor => {{
        const source = editor.querySelector('[data-mapping-field-source]');
        if (source) source.value = composeMappingField(editor);
      }});
    }}
    function setRailSection(section, collapsed) {{
      const toggle = document.querySelector('[data-collapse-section="' + section + '"]');
      const body = document.querySelector('[data-collapse-body="' + section + '"]');
      if (!toggle || !body) return;
      toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
      body.hidden = collapsed;
      const nav = toggle.closest('[data-rail-section]');
      if (nav) nav.dataset.collapsed = collapsed ? 'true' : 'false';
      try {{
        window.localStorage.setItem('wdm.rail.' + section + '.collapsed', collapsed ? '1' : '0');
      }} catch (_error) {{}}
    }}
    function restoreRailSections() {{
      document.querySelectorAll('[data-collapse-section]').forEach(toggle => {{
        const section = toggle.dataset.collapseSection;
        let collapsed = false;
        try {{
          collapsed = window.localStorage.getItem('wdm.rail.' + section + '.collapsed') === '1';
        }} catch (_error) {{}}
        if (toggle.closest('[data-active-section="true"]')) collapsed = false;
        setRailSection(section, collapsed);
      }});
    }}
    let filterSubmitTimer = null;
    function submitFilterForm(form, delay = 0) {{
      if (!form) return;
      window.clearTimeout(filterSubmitTimer);
      filterSubmitTimer = window.setTimeout(() => {{
        if (form.requestSubmit) form.requestSubmit();
        else form.submit();
      }}, delay);
    }}
    let searchRefreshTimer = null;
    let searchRefreshSeq = 0;
    async function refreshSelectionResults(form, sourceInput) {{
      if (!form) return;
      const seq = ++searchRefreshSeq;
      const url = new URL(form.action || window.location.href, window.location.href);
      const data = new FormData(form);
      data.set('page', '1');
      for (const [key, value] of data.entries()) {{
        if (value === '' && key !== 'q') continue;
        url.searchParams.append(key, value);
      }}
      try {{
        const res = await fetch(url.toString(), {{ cache: 'no-store' }});
        if (!res.ok) throw new Error('Search failed');
        const html = await res.text();
        if (seq !== searchRefreshSeq) return;
        const doc = new DOMParser().parseFromString(html, 'text/html');
        const nextGrid = doc.querySelector('.selection-grid');
        const nextPagination = doc.querySelector('.pagination-footer');
        const grid = document.querySelector('.selection-grid');
        const pagination = document.querySelector('.pagination-footer');
        if (nextGrid && grid) grid.replaceWith(nextGrid);
        if (nextPagination && pagination) pagination.replaceWith(nextPagination);
        window.history.replaceState(null, '', url.toString());
        if (sourceInput && document.activeElement === sourceInput) {{
          const start = sourceInput.selectionStart;
          const end = sourceInput.selectionEnd;
          sourceInput.focus({{ preventScroll: true }});
          if (start !== null && end !== null) sourceInput.setSelectionRange(start, end);
        }}
      }} catch (_error) {{
        submitFilterForm(form);
      }}
    }}
    function submitSearchWhenIdle(form, sourceInput, delay = 500) {{
      window.clearTimeout(searchRefreshTimer);
      searchRefreshTimer = window.setTimeout(() => refreshSelectionResults(form, sourceInput), delay);
    }}
    let dynamicPageSizeTimer = null;
    function computeDynamicPageSize() {{
      const grid = document.querySelector('.selection-grid');
      if (!grid) return null;
      const styles = window.getComputedStyle(grid);
      const columns = Math.max(1, styles.gridTemplateColumns.split(' ').filter(Boolean).length);
      const card = grid.querySelector('.selection-card');
      const cardHeight = card ? card.getBoundingClientRect().height : 220;
      const rowGap = parseFloat(styles.rowGap || styles.gap || '14') || 14;
      const footer = document.querySelector('.pagination-footer');
      const footerHeight = footer ? footer.getBoundingClientRect().height : 44;
      const top = grid.getBoundingClientRect().top;
      const available = Math.max(cardHeight, window.innerHeight - top - footerHeight - 28);
      const rows = Math.max(1, Math.floor((available + rowGap) / (cardHeight + rowGap)));
      return Math.min({MAX_SELECTION_ITEMS_PER_PAGE}, Math.max({MIN_SELECTION_ITEMS_PER_PAGE}, rows * columns));
    }}
    function applyDynamicPageSize(delay = 0) {{
      window.clearTimeout(dynamicPageSizeTimer);
      dynamicPageSizeTimer = window.setTimeout(() => {{
        const next = computeDynamicPageSize();
        if (!next) return;
        const url = new URL(window.location.href);
        const current = parseInt(url.searchParams.get('per_page') || '{DEFAULT_SELECTION_ITEMS_PER_PAGE}', 10);
        if (next === current) return;
        url.searchParams.set('per_page', String(next));
        url.searchParams.set('page', '1');
        window.location.href = url.toString();
      }}, delay);
    }}
    function syncHarnessMenuCheckboxes(input) {{
      const menu = input.closest('[data-harness-menu], .selection-card-action-panel');
      if (!menu) return;
      const targets = Array.from(menu.querySelectorAll('[data-harness-target]'));
      if (targets.length === 0) return;
      const enabledTargets = targets.filter(target => !target.disabled);
      const checkedTargets = enabledTargets.filter(target => target.checked);
      const summary = menu.querySelector('[data-harness-summary]');
      if (summary) {{
	        const summaryText = summary.querySelector('[data-harness-summary-text]') || summary;
        const isFilterMenu = menu.matches('[data-filter-multiselect-menu], [data-harness-filter-menu]');
        const noneTarget = enabledTargets.find(target => target.value === {json.dumps(HARNESS_NONE_VALUE)});
        const noneOnly = isFilterMenu && checkedTargets.length === 1 && noneTarget && noneTarget.checked;
	        if (enabledTargets.length === 0) summaryText.textContent = 'None';
	        else if (noneOnly) summaryText.textContent = 'None';
	        else if (checkedTargets.length === enabledTargets.length) summaryText.textContent = 'All';
	        else if (checkedTargets.length === 0) summaryText.textContent = isFilterMenu ? 'None selected' : 'None';
	        else summaryText.textContent = checkedTargets.length + ' selected';
	        const label = summary.dataset.summaryLabel;
	        if (label) summary.setAttribute('aria-label', label + ': ' + summaryText.textContent);
	      }}
    }}
    function setHarnessMenuSelection(button, checked) {{
      const menu = button.closest('[data-harness-menu]');
      if (!menu) return;
      menu.querySelectorAll('[data-harness-target]').forEach(target => {{
        if (!target.disabled) target.checked = checked;
      }});
      syncHarnessMenuCheckboxes(button);
      if (menu.matches('[data-filter-multiselect-menu], [data-harness-filter-menu]')) {{
        submitFilterForm(menu.closest('form'));
      }}
    }}
    function closeHarnessMenus(exceptMenu = null) {{
      document.querySelectorAll('[data-harness-menu][open]').forEach(menu => {{
        if (menu !== exceptMenu) menu.removeAttribute('open');
      }});
    }}
    document.addEventListener('click', async event => {{
      closeHarnessMenus(event.target.closest('[data-harness-menu]'));
      const sectionToggle = event.target.closest('[data-collapse-section]');
      if (sectionToggle) {{
        const collapsed = sectionToggle.getAttribute('aria-expanded') === 'true';
        setRailSection(sectionToggle.dataset.collapseSection, collapsed);
        return;
      }}
      const harnessOthersToggle = event.target.closest('[data-toggle-harness-others]');
      if (harnessOthersToggle) {{
        event.preventDefault();
        const list = document.getElementById(harnessOthersToggle.getAttribute('aria-controls') || '');
        const willOpen = list ? list.hidden : false;
        if (list) list.hidden = !willOpen;
        harnessOthersToggle.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
        harnessOthersToggle.textContent = willOpen ? (harnessOthersToggle.dataset.hideLabel || 'Hide others') : (harnessOthersToggle.dataset.showLabel || 'Show others');
        return;
      }}
      const selectAllHarnesses = event.target.closest('[data-harness-select-all]');
      if (selectAllHarnesses) {{
        event.preventDefault();
        setHarnessMenuSelection(selectAllHarnesses, true);
        return;
      }}
      const deselectAllHarnesses = event.target.closest('[data-harness-deselect-all]');
      if (deselectAllHarnesses) {{
        event.preventDefault();
        setHarnessMenuSelection(deselectAllHarnesses, false);
        return;
      }}
      const selectionCard = event.target.closest('[data-selection-preview-card]');
      if (selectionCard && !event.target.closest('a, button, input, label, summary, details, form, textarea, select')) {{
        event.preventDefault();
        loadSelectionPreview(selectionCard.dataset.previewType, selectionCard.dataset.previewName);
        return;
      }}
      const externalCard = event.target.closest('[data-external-preview-card]');
      if (externalCard && !event.target.closest('a, button, input, label, summary, details, form, textarea, select')) {{
        event.preventDefault();
        loadExternalSelectionPreview(externalCard.dataset.externalType, externalCard.dataset.externalName, externalCard.dataset.externalHarness, externalCard.dataset.externalPath, externalCard.dataset.externalScope);
        return;
      }}
      const selectionEdit = event.target.closest('[data-selection-edit-button]');
      if (selectionEdit) {{
        event.preventDefault();
        loadSelectionEdit(selectionEdit.dataset.editType, selectionEdit.dataset.editName, selectionEdit.dataset.editScope, selectionEdit.dataset.editView);
        return;
      }}
      const externalEdit = event.target.closest('[data-external-edit-button]');
      if (externalEdit) {{
        event.preventDefault();
        loadExternalSelectionEdit(externalEdit.dataset.externalType, externalEdit.dataset.externalName, externalEdit.dataset.externalHarness, externalEdit.dataset.externalPath, externalEdit.dataset.externalScope);
        return;
      }}
      const previewEdit = event.target.closest('[data-preview-edit]');
      if (previewEdit) {{
        event.preventDefault();
        loadSelectionEdit(previewEdit.dataset.editType, previewEdit.dataset.editName, previewEdit.dataset.editScope, previewEdit.dataset.editView);
        return;
      }}
      const externalPreviewEdit = event.target.closest('[data-external-preview-edit]');
      if (externalPreviewEdit) {{
        event.preventDefault();
        loadExternalSelectionEdit(externalPreviewEdit.dataset.externalType, externalPreviewEdit.dataset.externalName, externalPreviewEdit.dataset.externalHarness, externalPreviewEdit.dataset.externalPath, externalPreviewEdit.dataset.externalScope);
        return;
      }}
      const editRevert = event.target.closest('[data-edit-revert]');
      if (editRevert) {{
        event.preventDefault();
        const form = document.querySelector('[data-content-modal] form.edit-form');
        if (form) form.reset();
        if (form) resetBodySectionEditors(form);
        if (form) resetTemplateSectionEditors(form);
        if (form) resetTemplateFieldSectionEditors(form);
        if (form) resetExtraFieldEditors(form);
        if (form) resetListFieldEditors(form);
        if (form) resetMappingFieldEditors(form);
        if (form) setEditorCleanSnapshot(form);
        updateReactivePaths();
        return;
      }}
      const addTemplateSection = event.target.closest('[data-add-template-section]');
      if (addTemplateSection) {{
        event.preventDefault();
        const editor = addTemplateSection.closest('[data-template-section-editor]');
        const list = editor ? editor.querySelector('[data-template-section-list]') : null;
        if (list) {{
          list.insertAdjacentHTML('beforeend', templateSectionTemplate());
          const added = list.querySelector('[data-template-section-row]:last-child [data-template-section-title]');
          if (added) added.focus();
          syncTemplateSectionEditor(editor);
          updateContentModalDirtyState();
        }}
        return;
      }}
      const removeTemplateSection = event.target.closest('[data-remove-template-section]');
      if (removeTemplateSection) {{
        event.preventDefault();
        const editor = removeTemplateSection.closest('[data-template-section-editor]');
        const row = removeTemplateSection.closest('[data-template-section-row]');
        const list = editor ? editor.querySelector('[data-template-section-list]') : null;
        if (row && list && list.querySelectorAll('[data-template-section-row]').length > 1) {{
          row.remove();
        }} else if (row) {{
          const title = row.querySelector('[data-template-section-title]');
          const content = row.querySelector('[data-template-section-content]');
          if (title) title.value = '';
          if (content) content.value = '';
        }}
        if (editor) syncTemplateSectionEditor(editor);
        updateContentModalDirtyState();
        return;
      }}
      const moveTemplateSection = event.target.closest('[data-move-template-section]');
      if (moveTemplateSection) {{
        event.preventDefault();
        const editor = moveTemplateSection.closest('[data-template-section-editor]');
        const row = moveTemplateSection.closest('[data-template-section-row]');
        if (editor && row) {{
          if (moveTemplateSection.dataset.moveTemplateSection === 'up' && row.previousElementSibling) {{
            row.parentNode.insertBefore(row, row.previousElementSibling);
          }}
          if (moveTemplateSection.dataset.moveTemplateSection === 'down' && row.nextElementSibling) {{
            row.parentNode.insertBefore(row.nextElementSibling, row);
          }}
          syncTemplateSectionEditor(editor);
          updateContentModalDirtyState();
        }}
        return;
      }}
      const resetTemplateSections = event.target.closest('[data-reset-template-sections]');
      if (resetTemplateSections) {{
        event.preventDefault();
        const form = resetTemplateSections.closest('form.edit-form');
        const editor = resetTemplateSections.closest('[data-template-section-editor]');
        if (!editor || !form) return;
        if (templateSectionEditorHasMeaningfulContent(editor) && !window.confirm('Replace current template sections with the defaults for this type?')) return;
        maybeRefreshTemplateSectionsForType(form, true);
        updateContentModalDirtyState();
        return;
      }}
      const resetTemplateFieldSections = event.target.closest('[data-reset-template-field-sections]');
      if (resetTemplateFieldSections) {{
        event.preventDefault();
        const form = resetTemplateFieldSections.closest('form.edit-form');
        const editor = resetTemplateFieldSections.closest('[data-template-field-section-editor]');
        if (!editor || !form) return;
        if (templateFieldSectionEditorHasMeaningfulContent(editor) && !window.confirm('Replace current sectioned fields with the defaults for this type?')) return;
        maybeRefreshTemplateFieldSectionsForType(form, true);
        updateContentModalDirtyState();
        return;
      }}
      const addBodySection = event.target.closest('[data-add-body-section]');
      if (addBodySection) {{
        event.preventDefault();
        const editor = addBodySection.closest('[data-body-section-editor]');
        const list = editor ? editor.querySelector('[data-body-section-list]') : null;
        if (list) {{
          const preset = editor.querySelector('[data-body-section-preset]');
          const selected = preset ? preset.options[preset.selectedIndex] : null;
          const title = selected && selected.value ? selected.value : 'New section';
          const level = selected && selected.dataset.level ? selected.dataset.level : '2';
          const content = selected && selected.dataset.content ? selected.dataset.content : '';
          list.insertAdjacentHTML('beforeend', bodySectionTemplate(title, level, content, '\\n\\n', true));
          updateBodySectionMeta(list.querySelector('[data-body-section]:last-child'));
          const added = list.querySelector('[data-body-section]:last-child [data-body-section-title]');
          if (added) added.focus();
          syncBodySectionEditor(editor);
          updateContentModalDirtyState();
        }}
        return;
      }}
      const addMissingBodySectionsButton = event.target.closest('[data-add-missing-body-sections]');
      if (addMissingBodySectionsButton) {{
        event.preventDefault();
        const editor = addMissingBodySectionsButton.closest('[data-body-section-editor]');
        const addedCount = addMissingBodySections(editor);
        if (addedCount) {{
          const firstAdded = editor.querySelector('[data-body-section]:last-child [data-body-section-title]');
          if (firstAdded) firstAdded.focus();
        }}
        updateContentModalDirtyState();
        return;
      }}
      const applyBodyTemplate = event.target.closest('[data-apply-body-template]');
      if (applyBodyTemplate) {{
        event.preventDefault();
        const editor = bodyTemplateEditorFor(applyBodyTemplate);
        if (editor) replaceBodySectionsFromTemplate(applyBodyTemplate);
        else applyItemTemplateFromControls(applyBodyTemplate);
        return;
      }}
      const saveBodyTemplate = event.target.closest('[data-save-body-template]');
      if (saveBodyTemplate) {{
        event.preventDefault();
        saveBodyAsTemplate(saveBodyTemplate);
        return;
      }}
      const addTemplateFieldGroup = event.target.closest('[data-add-template-field-section-group]');
      if (addTemplateFieldGroup) {{
        event.preventDefault();
        const editor = addTemplateFieldGroup.closest('[data-template-field-section-editor]');
        const list = editor ? editor.querySelector('[data-template-field-section-group-list]') : null;
        if (list) {{
          list.insertAdjacentHTML('beforeend', templateFieldSectionGroupTemplate());
          const added = list.querySelector('[data-template-field-section-group]:last-child [data-template-field-section-key]');
          if (added) added.focus();
          syncTemplateFieldSectionEditor(editor);
          updateContentModalDirtyState();
        }}
        return;
      }}
      const removeTemplateFieldGroup = event.target.closest('[data-remove-template-field-section-group]');
      if (removeTemplateFieldGroup) {{
        event.preventDefault();
        const editor = removeTemplateFieldGroup.closest('[data-template-field-section-editor]');
        const group = removeTemplateFieldGroup.closest('[data-template-field-section-group]');
        if (group) group.remove();
        if (editor) syncTemplateFieldSectionEditor(editor);
        updateContentModalDirtyState();
        return;
      }}
      const addTemplateFieldSection = event.target.closest('[data-add-template-field-section]');
      if (addTemplateFieldSection) {{
        event.preventDefault();
        const editor = addTemplateFieldSection.closest('[data-template-field-section-editor]');
        const group = addTemplateFieldSection.closest('[data-template-field-section-group]');
        const list = group ? group.querySelector('[data-template-field-section-list]') : null;
        if (list) {{
          list.insertAdjacentHTML('beforeend', templateFieldSectionTemplate());
          const added = list.querySelector('[data-template-field-section-row]:last-child [data-template-field-section-title]');
          if (added) added.focus();
          if (editor) syncTemplateFieldSectionEditor(editor);
          updateContentModalDirtyState();
        }}
        return;
      }}
      const removeTemplateFieldSection = event.target.closest('[data-remove-template-field-section]');
      if (removeTemplateFieldSection) {{
        event.preventDefault();
        const editor = removeTemplateFieldSection.closest('[data-template-field-section-editor]');
        const row = removeTemplateFieldSection.closest('[data-template-field-section-row]');
        const list = row ? row.closest('[data-template-field-section-list]') : null;
        if (row && list && list.querySelectorAll('[data-template-field-section-row]').length > 1) {{
          row.remove();
        }} else if (row) {{
          const title = row.querySelector('[data-template-field-section-title]');
          const content = row.querySelector('[data-template-field-section-content]');
          if (title) title.value = '';
          if (content) content.value = '';
        }}
        if (editor) syncTemplateFieldSectionEditor(editor);
        updateContentModalDirtyState();
        return;
      }}
      const moveTemplateFieldSection = event.target.closest('[data-move-template-field-section]');
      if (moveTemplateFieldSection) {{
        event.preventDefault();
        const editor = moveTemplateFieldSection.closest('[data-template-field-section-editor]');
        const row = moveTemplateFieldSection.closest('[data-template-field-section-row]');
        if (row) {{
          if (moveTemplateFieldSection.dataset.moveTemplateFieldSection === 'up' && row.previousElementSibling) {{
            row.parentNode.insertBefore(row, row.previousElementSibling);
          }}
          if (moveTemplateFieldSection.dataset.moveTemplateFieldSection === 'down' && row.nextElementSibling) {{
            row.parentNode.insertBefore(row.nextElementSibling, row);
          }}
          if (editor) syncTemplateFieldSectionEditor(editor);
          updateContentModalDirtyState();
        }}
        return;
      }}
      const removeBodySection = event.target.closest('[data-remove-body-section]');
      if (removeBodySection) {{
        event.preventDefault();
        const editor = removeBodySection.closest('[data-body-section-editor]');
        const section = removeBodySection.closest('[data-body-section]');
        const list = editor ? editor.querySelector('[data-body-section-list]') : null;
        if (section && list && list.querySelectorAll('[data-body-section]').length > 1 && bodySectionHasMeaningfulContent(section)) {{
          addBodySectionUndo(list, section, editor);
        }} else if (section && list && list.querySelectorAll('[data-body-section]').length > 1) {{
          section.remove();
        }} else if (section) {{
          const title = section.querySelector('[data-body-section-title]');
          const level = section.querySelector('[data-body-section-level]');
          const content = section.querySelector('[data-body-section-content]');
          if (title) title.value = 'Overview';
          if (level) level.value = '0';
          if (content) content.value = '';
          updateBodySectionMeta(section);
        }}
        markBodySectionEditorDirty(editor);
        if (editor) syncBodySectionEditor(editor);
        updateContentModalDirtyState();
        return;
      }}
      const undoBodySection = event.target.closest('[data-undo-body-section]');
      if (undoBodySection) {{
        event.preventDefault();
        const undo = undoBodySection.closest('.body-section-undo');
        const section = undo && undo._removedSection;
        const editor = undo && undo._editor ? undo._editor : undo?.closest('[data-body-section-editor]');
        if (undo && section) {{
          undo.replaceWith(section);
          updateBodySectionMeta(section);
          markBodySectionEditorDirty(editor);
          if (editor) syncBodySectionEditor(editor);
          updateContentModalDirtyState();
        }}
        return;
      }}
      const moveBodySection = event.target.closest('[data-move-body-section]');
      if (moveBodySection) {{
        event.preventDefault();
        const editor = moveBodySection.closest('[data-body-section-editor]');
        const section = moveBodySection.closest('[data-body-section]');
        if (editor && section) {{
          if (moveBodySection.dataset.moveBodySection === 'up' && section.previousElementSibling) {{
            section.parentNode.insertBefore(section, section.previousElementSibling);
          }}
          if (moveBodySection.dataset.moveBodySection === 'down' && section.nextElementSibling) {{
            section.parentNode.insertBefore(section.nextElementSibling, section);
          }}
          markBodySectionEditorDirty(editor);
          syncBodySectionEditor(editor);
          updateContentModalDirtyState();
        }}
        return;
      }}
      const toggleBodyPreview = event.target.closest('[data-toggle-body-preview]');
      if (toggleBodyPreview) {{
        event.preventDefault();
        const section = toggleBodyPreview.closest('[data-body-section]');
        const preview = section ? section.querySelector('[data-body-section-preview]') : null;
        setBodySectionPreview(section, !!(preview && preview.hidden));
        return;
      }}
      const toggleBodySection = event.target.closest('[data-toggle-body-section]');
      if (toggleBodySection) {{
        event.preventDefault();
        const section = toggleBodySection.closest('[data-body-section]');
        setBodySectionCollapsed(section, !(section && section.dataset.collapsed === 'true'));
        return;
      }}
      const collapseAllBodySections = event.target.closest('[data-collapse-all-body-sections]');
      if (collapseAllBodySections) {{
        event.preventDefault();
        collapseAllBodySections.closest('[data-body-section-editor]')?.querySelectorAll('[data-body-section]').forEach(section => setBodySectionCollapsed(section, true));
        return;
      }}
      const expandAllBodySections = event.target.closest('[data-expand-all-body-sections]');
      if (expandAllBodySections) {{
        event.preventDefault();
        expandAllBodySections.closest('[data-body-section-editor]')?.querySelectorAll('[data-body-section]').forEach(section => setBodySectionCollapsed(section, false));
        return;
      }}
      const addExtraField = event.target.closest('[data-add-extra-field]');
      if (addExtraField) {{
        event.preventDefault();
        const editor = addExtraField.closest('[data-extra-fields-editor]');
        const list = editor ? editor.querySelector('[data-extra-fields-list]') : null;
        if (list) {{
          list.insertAdjacentHTML('beforeend', extraFieldTemplate());
          const added = list.querySelector('[data-extra-field-row]:last-child [data-extra-field-key]');
          if (added) added.focus();
          syncExtraFieldEditor(editor);
          updateContentModalDirtyState();
        }}
        return;
      }}
      const removeExtraField = event.target.closest('[data-remove-extra-field]');
      if (removeExtraField) {{
        event.preventDefault();
        const editor = removeExtraField.closest('[data-extra-fields-editor]');
        const row = removeExtraField.closest('[data-extra-field-row]');
        const list = editor ? editor.querySelector('[data-extra-fields-list]') : null;
        if (row && list && list.querySelectorAll('[data-extra-field-row]').length > 1) {{
          row.remove();
        }} else if (row) {{
          const key = row.querySelector('[data-extra-field-key]');
          const value = row.querySelector('[data-extra-field-value]');
          if (key) key.value = '';
          if (value) value.value = '';
        }}
        if (editor) syncExtraFieldEditor(editor);
        updateContentModalDirtyState();
        return;
      }}
      const addListFieldItem = event.target.closest('[data-add-list-field-item]');
      if (addListFieldItem) {{
        event.preventDefault();
        const editor = addListFieldItem.closest('[data-list-field-editor]');
        const list = editor ? editor.querySelector('[data-list-field-list]') : null;
        if (list) {{
          list.insertAdjacentHTML('beforeend', listFieldItemTemplate());
          const added = list.querySelector('[data-list-field-row]:last-child [data-list-field-value]');
          if (added) added.focus();
          syncListFieldEditor(editor);
          updateContentModalDirtyState();
        }}
        return;
      }}
      const removeListFieldItem = event.target.closest('[data-remove-list-field-item]');
      if (removeListFieldItem) {{
        event.preventDefault();
        const editor = removeListFieldItem.closest('[data-list-field-editor]');
        const row = removeListFieldItem.closest('[data-list-field-row]');
        const list = editor ? editor.querySelector('[data-list-field-list]') : null;
        if (row && list && list.querySelectorAll('[data-list-field-row]').length > 1) {{
          row.remove();
        }} else if (row) {{
          const value = row.querySelector('[data-list-field-value]');
          if (value) value.value = '';
        }}
        if (editor) syncListFieldEditor(editor);
        updateContentModalDirtyState();
        return;
      }}
      const addMappingFieldItem = event.target.closest('[data-add-mapping-field-item]');
      if (addMappingFieldItem) {{
        event.preventDefault();
        const editor = addMappingFieldItem.closest('[data-mapping-field-editor]');
        const list = editor ? editor.querySelector('[data-mapping-field-list]') : null;
        if (list) {{
          list.insertAdjacentHTML('beforeend', mappingFieldItemTemplate());
          const added = list.querySelector('[data-mapping-field-row]:last-child [data-mapping-field-key]');
          if (added) added.focus();
          syncMappingFieldEditor(editor);
          updateContentModalDirtyState();
        }}
        return;
      }}
      const removeMappingFieldItem = event.target.closest('[data-remove-mapping-field-item]');
      if (removeMappingFieldItem) {{
        event.preventDefault();
        const editor = removeMappingFieldItem.closest('[data-mapping-field-editor]');
        const row = removeMappingFieldItem.closest('[data-mapping-field-row]');
        const list = editor ? editor.querySelector('[data-mapping-field-list]') : null;
        if (row && list && list.querySelectorAll('[data-mapping-field-row]').length > 1) {{
          row.remove();
        }} else if (row) {{
          const key = row.querySelector('[data-mapping-field-key]');
          const value = row.querySelector('[data-mapping-field-value]');
          if (key) key.value = '';
          if (value) value.value = '';
        }}
        if (editor) syncMappingFieldEditor(editor);
        updateContentModalDirtyState();
        return;
      }}
      const editSave = event.target.closest('[data-edit-save]');
      if (editSave) {{
        event.preventDefault();
        const form = document.querySelector('[data-content-modal] form.edit-form');
        if (form) {{
          if (form.requestSubmit) form.requestSubmit();
          else submitModalEditorForm(form);
        }}
        return;
      }}
      const editDelete = event.target.closest('[data-edit-delete]');
      if (editDelete) {{
        event.preventDefault();
        if (!confirmDirtyDelete()) return;
        openDeleteModal(editDelete.dataset.deleteType, editDelete.dataset.deleteName, editDelete.dataset.deleteScope);
        return;
      }}
      const previewDelete = event.target.closest('[data-preview-delete]');
      if (previewDelete) {{
        event.preventDefault();
        openDeleteModal(previewDelete.dataset.deleteType, previewDelete.dataset.deleteName, previewDelete.dataset.deleteScope);
        return;
      }}
      const previewDuplicate = event.target.closest('[data-preview-duplicate]');
      if (previewDuplicate) {{
        event.preventDefault();
        duplicateManagedItem(previewDuplicate.dataset.duplicateType, previewDuplicate.dataset.duplicateName, previewDuplicate.dataset.duplicateScope);
        return;
      }}
      const modalViewToggle = event.target.closest('[data-content-modal] .view-toggle a');
      if (modalViewToggle) {{
        event.preventDefault();
        const url = new URL(modalViewToggle.href, window.location.href);
        const form = activeEditorForm();
        const targetView = url.searchParams.get('view') || 'form';
        if (form) {{
          convertModalEditorView(form, targetView);
        }} else {{
          loadSelectionEdit(url.searchParams.get('type') || 'agents', url.searchParams.get('name') || '', url.searchParams.get('scope') || 'global', targetView);
        }}
        return;
      }}
      const pageViewToggle = event.target.closest('section.editor .view-toggle a');
      if (pageViewToggle) {{
        const modal = pageViewToggle.closest('[data-content-modal]');
        if (!modal) {{
          event.preventDefault();
          const url = new URL(pageViewToggle.href, window.location.href);
          const form = pageViewToggle.closest('section.editor')?.querySelector('form.edit-form');
          if (form) await convertModalEditorView(form, url.searchParams.get('view') || 'form');
          return;
        }}
      }}
      const openButton = event.target.closest('[data-open-project-modal]');
      if (openButton) {{
        openProjectModal();
        return;
      }}
      const openImportButton = event.target.closest('[data-open-import-modal]');
      if (openImportButton) {{
        event.preventDefault();
        openImportModal(openImportButton.dataset.importType, openImportButton.dataset.importScope);
        return;
      }}
      const closeButton = event.target.closest('[data-close-project-modal]');
      if (closeButton || event.target.matches('[data-project-modal]')) {{
        closeProjectModal();
        return;
      }}
      const closeImportButton = event.target.closest('[data-close-import-modal]');
      if (closeImportButton || event.target.matches('[data-import-modal]')) {{
        closeImportModal();
        return;
      }}
      const closeContentButton = event.target.closest('[data-close-content-modal]');
      if (closeContentButton || event.target.matches('[data-content-modal]')) {{
        closeContentModal();
        return;
      }}
      const closeDeleteButton = event.target.closest('[data-close-delete-modal]');
      if (closeDeleteButton || event.target.matches('[data-delete-modal]')) {{
        closeDeleteModal();
        return;
      }}
      const browseButton = event.target.closest('[data-browse-path]');
      if (browseButton) {{
        browseProjectDirs(browseButton.dataset.browsePath);
        return;
      }}
      const importBrowseButton = event.target.closest('[data-import-browse-path]');
      if (importBrowseButton) {{
        browseImportDirs(importBrowseButton.dataset.importBrowsePath);
        return;
      }}
      const importFilePath = event.target.closest('[data-import-file-path]');
      if (importFilePath && importPathInput) {{
        importPathInput.value = importFilePath.dataset.importFilePath || '';
        return;
      }}
      const browseCurrent = event.target.closest('[data-browse-current]');
      if (browseCurrent && projectPathInput) {{
        browseProjectDirs(projectPathInput.value);
      }}
      const browseImportCurrent = event.target.closest('[data-browse-import-current]');
      if (browseImportCurrent && importPathInput) {{
        browseImportDirs(importPathInput.value);
      }}
    }});
    document.addEventListener('keydown', event => {{
      const visibleContentModal = document.querySelector('[data-content-modal]:not([hidden]) .content-modal');
      if (event.key === 'Tab' && visibleContentModal) {{
        const focusables = modalFocusableElements(visibleContentModal);
        if (focusables.length) {{
          const first = focusables[0];
          const last = focusables[focusables.length - 1];
          if (event.shiftKey && document.activeElement === first) {{
            event.preventDefault();
            last.focus();
          }} else if (!event.shiftKey && document.activeElement === last) {{
            event.preventDefault();
            first.focus();
          }}
        }}
      }}
      if (event.key === 'Escape') {{
        if (document.querySelector('[data-delete-modal]:not([hidden])')) {{
          closeDeleteModal();
          return;
        }}
        if (document.querySelector('[data-content-modal]:not([hidden])')) {{
          closeContentModal();
          return;
        }}
        if (document.querySelector('[data-import-modal]:not([hidden])')) {{
          closeImportModal();
          return;
        }}
        if (document.querySelector('[data-project-modal]:not([hidden])')) {{
          closeProjectModal();
          return;
        }}
        closeHarnessMenus();
        return;
      }}
      const selectionCard = event.target.closest('[data-selection-preview-card]');
      if (selectionCard && (event.key === 'Enter' || event.key === ' ')) {{
        event.preventDefault();
        loadSelectionPreview(selectionCard.dataset.previewType, selectionCard.dataset.previewName);
      }}
      const externalCard = event.target.closest('[data-external-preview-card]');
      if (externalCard && (event.key === 'Enter' || event.key === ' ')) {{
        event.preventDefault();
        loadExternalSelectionPreview(externalCard.dataset.externalType, externalCard.dataset.externalName, externalCard.dataset.externalHarness, externalCard.dataset.externalPath, externalCard.dataset.externalScope);
      }}
    }});
    document.addEventListener('submit', event => {{
      const deleteForm = event.target.closest('[data-delete-form]');
      if (deleteForm) {{
        event.preventDefault();
        submitDeleteForm(deleteForm);
        return;
      }}
      const importForm = event.target.closest('[data-import-form]');
      if (importForm) {{
        event.preventDefault();
        submitImportForm(importForm);
        return;
      }}
      const form = event.target.closest('[data-content-modal] form[action="/save"], [data-content-modal] form[action="/save-external"]');
      if (!form) return;
      event.preventDefault();
      submitModalEditorForm(form);
    }});
    document.addEventListener('input', event => {{
      const filterSearch = event.target.closest('[data-filter-search]');
      if (filterSearch) submitSearchWhenIdle(filterSearch.form, filterSearch, 500);
      const bodyEditor = event.target.closest('[data-body-section-editor]');
      if (bodyEditor) {{
        const section = event.target.closest('[data-body-section]');
        if (section) {{
          markBodySectionEditorDirty(bodyEditor);
          syncBodySectionEditor(bodyEditor);
          updateBodySectionMeta(section);
          const preview = section.querySelector('[data-body-section-preview]');
          if (preview && !preview.hidden) updateBodySectionPreview(section);
        }}
      }}
      const templateSectionEditor = event.target.closest('[data-template-section-editor]');
      if (templateSectionEditor) syncTemplateSectionEditor(templateSectionEditor);
      const extraEditor = event.target.closest('[data-extra-fields-editor]');
      if (extraEditor) syncExtraFieldEditor(extraEditor);
      const listEditor = event.target.closest('[data-list-field-editor]');
      if (listEditor) syncListFieldEditor(listEditor);
      const mappingEditor = event.target.closest('[data-mapping-field-editor]');
      if (mappingEditor) syncMappingFieldEditor(mappingEditor);
      updateContentModalDirtyState();
      updateReactivePaths();
    }});
    document.addEventListener('change', event => {{
      const previewHarnessSelect = event.target.closest('[data-preview-harness-select]');
      if (previewHarnessSelect) {{
        loadSelectionPreview(previewHarnessSelect.dataset.previewType, previewHarnessSelect.dataset.previewName, previewHarnessSelect.value);
        return;
      }}
      const externalPreviewHarnessSelect = event.target.closest('[data-external-preview-harness-select]');
      if (externalPreviewHarnessSelect) {{
        loadExternalSelectionPreview(externalPreviewHarnessSelect.dataset.externalType, externalPreviewHarnessSelect.dataset.externalName, externalPreviewHarnessSelect.value, externalPreviewHarnessSelect.dataset.externalPath, externalPreviewHarnessSelect.dataset.externalScope);
        return;
      }}
      const importSourceOption = event.target.closest('[data-import-source-option]');
      if (importSourceOption) {{
        updateImportSourcePanes();
        return;
      }}
      const importFileInput = event.target.closest('[data-import-file-input]');
      if (importFileInput) {{
        const file = importFileInput.files && importFileInput.files[0];
        const fileNameField = importFileInput.closest('[data-import-form]')?.querySelector('[data-import-file-name]');
        if (fileNameField) fileNameField.value = file ? file.name : '';
        return;
      }}
      const capabilityChoice = event.target.closest('.capability-option input[type="checkbox"]');
      if (capabilityChoice) {{
        const source = capabilityChoice.closest('.capability-option').querySelector('.capability-source');
        if (source) source.textContent = capabilityChoice.checked ? 'Override' : (source.dataset.defaultLabel || 'Available');
        return;
      }}
      const harnessChoice = event.target.closest('[data-harness-target]');
      if (harnessChoice) {{
        syncHarnessMenuCheckboxes(harnessChoice);
        const menu = harnessChoice.closest('[data-filter-multiselect-menu], [data-harness-filter-menu]');
        if (menu) submitFilterForm(menu.closest('form'));
        return;
      }}
      const bodyTemplateSelect = event.target.closest('[data-body-template-select]');
      if (bodyTemplateSelect) {{
        const editor = bodyTemplateEditorFor(bodyTemplateSelect);
        setBodyTemplate(editor, bodyTemplateSelect.value, false);
        return;
      }}
      const templateTypeSelect = event.target.closest('[data-template-type-select]');
      if (templateTypeSelect) {{
        refreshTemplateFieldPresetEditor(templateTypeSelect);
        maybeRefreshTemplateSectionsForType(templateTypeSelect.closest('form.edit-form'), false);
        maybeRefreshTemplateFieldSectionsForType(templateTypeSelect.closest('form.edit-form'), false);
        updateContentModalDirtyState();
        return;
      }}
      const autoFilter = event.target.closest('[data-filter-auto-submit]');
      if (autoFilter) {{
        submitFilterForm(autoFilter.form);
        return;
      }}
      const bodyEditor = event.target.closest('[data-body-section-editor]');
      if (bodyEditor) {{
        const section = event.target.closest('[data-body-section]');
        if (section) {{
          markBodySectionEditorDirty(bodyEditor);
          syncBodySectionEditor(bodyEditor);
          updateBodySectionMeta(section);
        }}
      }}
      const templateSectionEditor = event.target.closest('[data-template-section-editor]');
      if (templateSectionEditor) syncTemplateSectionEditor(templateSectionEditor);
      const extraEditor = event.target.closest('[data-extra-fields-editor]');
      if (extraEditor) syncExtraFieldEditor(extraEditor);
      const listEditor = event.target.closest('[data-list-field-editor]');
      if (listEditor) syncListFieldEditor(listEditor);
      const mappingEditor = event.target.closest('[data-mapping-field-editor]');
      if (mappingEditor) syncMappingFieldEditor(mappingEditor);
      updateContentModalDirtyState();
      updateReactivePaths();
    }});
    window.addEventListener('resize', () => applyDynamicPageSize(250));
    document.addEventListener('DOMContentLoaded', () => {{
      restoreRailSections();
      resetBodySectionEditors(document);
      resetTemplateSectionEditors(document);
      resetTemplateFieldSectionEditors(document);
      updateReactivePaths();
      applyDynamicPageSize(50);
    }});
    {render_reload_script()}
  </script>
</body>
</html>"""


def web_harness_paths() -> dict[str, dict[str, dict[str, str]]]:
    result = {}
    for harness, definition in HARNESS_DEFINITIONS.items():
        sync = definition.get("sync", {}) if isinstance(definition, dict) else {}
        paths = sync.get("paths", {}) if isinstance(sync, dict) else {}
        if not isinstance(paths, dict):
            continue
        if any(isinstance(paths.get(mode), dict) for mode in ("project", "global")):
            result[harness] = {
                "project": {str(k): str(v) for k, v in (paths.get("project") or {}).items()},
                "global": {str(k): str(v) for k, v in (paths.get("global") or {}).items()},
            }
        else:
            flat = {str(k): str(v) for k, v in paths.items() if isinstance(v, str)}
            result[harness] = {"project": flat, "global": flat}
    return result


def scoped_target_root(scope: str) -> Path:
    return Path(selected_project(scope).get("root") or str(Path.home())).expanduser()


def is_global_scope(scope: str) -> bool:
    return selected_project(scope).get("kind") == "global"


def generic_harness_template(harness: str, content_type: str, global_mode: bool) -> str:
    definition = HARNESS_DEFINITIONS.get(harness, {})
    sync = definition.get("sync", {}) if isinstance(definition, dict) else {}
    paths = sync.get("paths", {}) if isinstance(sync, dict) else {}
    if not isinstance(paths, dict):
        return ""
    mode_key = "global" if global_mode else "project"
    mode_paths = paths.get(mode_key)
    if isinstance(mode_paths, dict):
        return str(mode_paths.get(content_type) or "")
    value = paths.get(content_type)
    return str(value) if isinstance(value, str) else ""


def generic_harness_output_name(harness: str, content_type: str, name: str) -> str:
    if content_type == "skills":
        return name
    definition = HARNESS_DEFINITIONS.get(harness, {})
    outputs = definition.get("outputs", {}) if isinstance(definition, dict) else {}
    output = outputs.get(content_type, {}) if isinstance(outputs, dict) else {}
    extension = output.get("extension") if isinstance(output, dict) else None
    return f"{name}{extension}" if extension else name


def format_harness_template(template: str, content_type: str, harness: str, name: str) -> Path:
    file_name = f"{name}.json" if content_type == "mcp" else f"{name}.md"
    output_name = generic_harness_output_name(harness, content_type, name)
    return Path(
        template.format(
            name=name,
            stem=name,
            file=file_name,
            output=output_name,
        )
    )


def harness_destination(content_type: str, name: str, harness: str, scope: str) -> tuple[Path | None, bool]:
    root = scoped_target_root(scope)
    global_mode = is_global_scope(scope)
    if harness == "codex":
        if content_type == "agents":
            return root / ".codex" / "agents" / f"{name}.toml", False
        if content_type == "skills":
            skills_root = Path.home() if global_mode else root
            return skills_root / ".agents" / "skills" / name, False
        if content_type == "mcp":
            return root / ".codex" / "config.toml", True
        if content_type == "hooks":
            return root / ".codex" / "hooks" / name, False
        return None, False
    if harness == "claude":
        if content_type == "agents":
            return root / ".claude" / "agents" / f"{name}.md", False
        if content_type == "skills":
            return root / ".claude" / "skills" / name, False
        if content_type == "rules":
            return root / ".claude" / "rules" / f"{name}.md", False
        if content_type == "workflows":
            return root / ".claude" / "commands" / f"{name}.md", False
        if content_type == "hooks":
            return root / ".claude" / "hooks" / name, False
        if content_type == "mcp" and not global_mode:
            return root / ".mcp.json", True
        return None, False
    if harness == "copilot":
        base = root / ".copilot" if global_mode else root / ".github"
        if content_type == "agents":
            return base / "agents" / f"{name}.agent.md", False
        if content_type == "skills":
            return base / "skills" / name, False
        if content_type == "rules":
            if global_mode:
                return base / "instructions" / f"{name}.instructions.md", False
            return base / "copilot-instructions.md", True
        if content_type == "hooks":
            return base / "hooks" / name, False
        if content_type == "mcp" and global_mode:
            return base / "mcp-config.json", True
        return None, False
    if harness == "gemini":
        if content_type == "agents":
            return root / ".gemini" / "agents" / f"{name}.md", False
        if content_type == "skills":
            return root / ".gemini" / "skills" / name, False
        if content_type == "mcp":
            return root / ".gemini" / "settings.json", True
        return None, False
    template = generic_harness_template(harness, content_type, global_mode)
    if not template:
        return None, False
    aggregate = content_type == "mcp" and "{" not in template
    if "{" not in template and content_type != "mcp":
        aggregate = True
    return root / format_harness_template(template, content_type, harness, name), aggregate


def text_file_contains_item(path: Path, content_type: str, name: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    if content_type == "mcp":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            servers = data.get("mcpServers")
            return isinstance(servers, dict) and name in servers
        return bool(
            re.search(rf"^\s*\[mcp_servers\.{re.escape(name)}\]\s*$", text, re.MULTILINE)
            or re.search(rf'"{re.escape(name)}"\s*:', text)
        )
    if content_type == "rules":
        return bool(re.search(rf"^##\s+{re.escape(name)}\s*$", text, re.MULTILINE))
    return name in text


def item_exists_at_destination(path: Path, aggregate: bool, content_type: str, name: str) -> bool:
    if not path.exists() and not path.is_symlink():
        return False
    if aggregate:
        return text_file_contains_item(path, content_type, name)
    return True


def harness_item_statuses(content_type: str, name: str, scope: str) -> dict[str, dict[str, Any]]:
    statuses: dict[str, dict[str, Any]] = {}
    for harness in ALL_HARNESSES:
        path, aggregate = harness_destination(content_type, name, harness, scope)
        supported = path is not None
        statuses[harness] = {
            "supported": supported,
            "checked": item_exists_at_destination(path, aggregate, content_type, name) if path else False,
            "path": str(path) if path else "",
        }
    return statuses


def harness_label(harness: str) -> str:
    definition = HARNESS_DEFINITIONS.get(harness, {})
    return str(definition.get("label") or harness).strip()


def checked_harness_labels(statuses: dict[str, dict[str, Any]]) -> list[str]:
    labels = []
    for harness in ALL_HARNESSES:
        if statuses.get(harness, {}).get("checked"):
            labels.append(harness_label(harness))
    return labels


def is_loaded_globally(content_type: str, name: str, installed: set[str], scope: str) -> bool:
    if content_type not in CONTENT_TYPES or is_global_scope(scope):
        return False
    if name in installed:
        return True
    statuses = harness_item_statuses(content_type, name, "global")
    return any(bool(status.get("checked")) for status in statuses.values())


def render_reload_script() -> str:
    if os.environ.get(RELOAD_ENV) != "1":
        return ""
    return """
    let reloadToken = null;
    async function pollReloadToken() {
      try {
        const res = await fetch('/api/reload-token', { cache: 'no-store' });
        if (!res.ok) return;
        const data = await res.json();
        if (reloadToken === null) {
          reloadToken = data.token;
          return;
        }
        if (data.token !== reloadToken) {
          window.setTimeout(() => window.location.reload(), 800);
        }
      } catch (_error) {
        // The Python process may be between execs; the next poll will retry.
      }
    }
    window.setInterval(pollReloadToken, 1000);
    pollReloadToken();
    """


def render_rail(active: str, selected_name: str | None, scope: str, filters: dict[str, str] | None = None) -> str:
    filters = filters or {}
    return (
        render_harness_nav(active, selected_name, scope)
        + '<div class="rail-divider"></div>'
        + render_template_nav(active, selected_name, scope, str(filters.get("template_type") or "agents"))
        + '<div class="rail-divider"></div>'
        + render_project_nav(active, selected_name, scope)
        + render_sync_controls(scope)
    )


def render_type_submenu(active: str, scope: str) -> str:
    items = ["agents", "skills", "mcp", "hooks", "rules", "workflows", "groups"]

    def link(content_type: str) -> str:
        cls = "active" if content_type == active else ""
        return f'<a class="{cls}" href="/?type={content_type}&scope={urllib.parse.quote(scope)}">{content_type.title()}</a>'

    return f'<nav class="type-tabs" aria-label="Content menu">{"".join(link(item) for item in items)}</nav>'


def render_sync_controls(scope: str) -> str:
    return f"""<form class="sync-form rail-sync-form" action="/sync" method="post" data-sync-form>
  <input type="hidden" name="scope" value="{escape(scope)}" data-scope-hidden>
  <button type="submit" class="secondary">Dry Run</button>
  <button type="submit" name="apply" value="1">Sync</button>
</form>"""


def render_project_nav(content_type: str, selected_name: str | None, scope: str) -> str:
    choices = project_choices()
    global_choice = choices[0]
    project_choices_only = choices[1:]
    active_section = "true" if content_type not in {"harnesses", "templates"} else "false"

    def project_link(choice: dict[str, str]) -> str:
        active = " active" if choice["value"] == scope else ""
        name_param = "" if selected_name is None else f"&name={urllib.parse.quote(selected_name)}"
        href = (
            f"/?type={urllib.parse.quote(content_type)}"
            f"{name_param}"
            f"&scope={urllib.parse.quote(choice['value'])}"
        )
        return f"""<a class="project-entry{active}" href="{href}" data-project-entry data-scope="{escape(choice['value'])}" data-root="{escape(choice['root'])}" data-kind="{escape(choice['kind'])}">
  <span>{escape(choice['label'])}</span>
  <small>{escape(choice['root'])}</small>
</a>"""

    project_entries = "".join(project_link(choice) for choice in project_choices_only)
    return f"""
<div class="project-nav" data-rail-section="projects" data-active-section="{active_section}">
  <div class="project-nav-head">
    <h2><button type="button" class="rail-section-toggle" aria-expanded="true" aria-controls="rail-section-projects" data-collapse-section="projects"><span class="rail-caret" aria-hidden="true">&gt;</span><span>Projects</span></button></h2>
    <button type="button" class="add-project-button" title="Add project" aria-label="Add project" data-open-project-modal>+</button>
  </div>
  <div class="rail-section-body" id="rail-section-projects" data-collapse-body="projects">
    {project_link(global_choice)}
    {project_entries}
  </div>
</div>"""


def render_project_modal(content_type: str, selected_name: str | None) -> str:
    name_input = "" if selected_name is None else f'<input type="hidden" name="name" value="{escape(selected_name)}">'
    return f"""<div class="modal-backdrop" data-project-modal hidden>
  <section class="modal" role="dialog" aria-modal="true" aria-labelledby="project-modal-title">
    <div class="modal-head">
      <h2 id="project-modal-title">Add Project</h2>
      <button type="button" class="icon-button" aria-label="Close" data-close-project-modal>+</button>
    </div>
    <form class="modal-form" action="/projects/add" method="post">
      <input type="hidden" name="type" value="{escape(content_type)}">
      {name_input}
      <label>
        <span>Name</span>
        <input name="project_label" placeholder="Project name">
      </label>
      <label>
        <span>Path</span>
        <div class="path-input-row">
          <input name="project_path" value="{escape(Path.cwd())}" required data-project-path-input>
          <button type="button" class="secondary" data-browse-current>Browse</button>
        </div>
      </label>
      <div class="path-browser" data-project-browser></div>
      <div class="form-actions">
        <button type="submit">Add</button>
        <button type="button" class="secondary" data-close-project-modal>Cancel</button>
      </div>
    </form>
  </section>
</div>"""


def render_import_modal(content_type: str, scope: str) -> str:
    return f"""<div class="modal-backdrop" data-import-modal hidden>
  <section class="modal import-modal" role="dialog" aria-modal="true" aria-labelledby="import-modal-title">
    <div class="modal-head">
      <h2 id="import-modal-title">Import Item</h2>
      <button type="button" class="icon-button" aria-label="Close" data-close-import-modal>+</button>
    </div>
    <form class="modal-form import-form" action="/import-item" method="post" data-import-form>
      <input type="hidden" name="type" value="{escape(content_type)}" data-import-type>
      <input type="hidden" name="scope" value="{escape(scope)}" data-import-scope>
      <input type="hidden" name="import_file_name" data-import-file-name>
      <label>
        <span>Name</span>
        <input name="name" placeholder="Leave blank to derive from source">
      </label>
      <fieldset class="import-source-group">
        <legend>Source</legend>
        <label><input type="radio" name="import_source" value="paste" checked data-import-source-option><span>Paste</span></label>
        <label><input type="radio" name="import_source" value="url" data-import-source-option><span>URL</span></label>
        <label><input type="radio" name="import_source" value="path" data-import-source-option><span>Local path</span></label>
        <label><input type="radio" name="import_source" value="file" data-import-source-option><span>File</span></label>
      </fieldset>
      <label class="wide" data-import-pane="paste">
        <span>Content</span>
        <textarea name="import_raw" rows="14" spellcheck="false" placeholder="Paste markdown, JSON, YAML, TOML, shell script, or template content here"></textarea>
      </label>
      <label class="wide" data-import-pane="url" hidden>
        <span>URL</span>
        <input name="import_url" placeholder="https://example.com/agent.md">
      </label>
      <label class="wide" data-import-pane="path" hidden>
        <span>Local path</span>
        <div class="path-input-row">
          <input name="import_path" placeholder="/Users/will/path/to/file.md" data-import-path-input>
          <button type="button" class="secondary" data-browse-import-current>Browse</button>
        </div>
      </label>
      <div class="path-browser import-path-browser" data-import-browser hidden></div>
      <label class="wide" data-import-pane="file" hidden>
        <span>File</span>
        <input type="file" data-import-file-input>
      </label>
      <div class="form-actions">
        <button type="submit">Import</button>
        <button type="button" class="secondary" data-close-import-modal>Cancel</button>
      </div>
    </form>
  </section>
</div>"""


def render_content_modal() -> str:
    return """<div class="modal-backdrop" data-content-modal hidden>
  <section class="modal content-modal" role="dialog" aria-modal="true" aria-labelledby="content-modal-title">
    <div class="modal-head">
      <div class="modal-title-group">
        <h2 id="content-modal-title" data-content-modal-title>Details</h2>
        <div class="modal-head-actions" data-content-modal-actions></div>
      </div>
      <button type="button" class="icon-button" aria-label="Close" data-close-content-modal>+</button>
    </div>
    <div class="content-modal-body" data-content-modal-body></div>
  </section>
</div>"""


def render_delete_modal() -> str:
    return """<div class="modal-backdrop" data-delete-modal hidden>
  <section class="modal confirm-modal" role="dialog" aria-modal="true" aria-labelledby="delete-modal-title">
    <div class="modal-head">
      <h2 id="delete-modal-title">Delete item</h2>
      <button type="button" class="icon-button" aria-label="Close" data-close-delete-modal>+</button>
    </div>
    <form class="modal-form" action="/delete" method="post" data-delete-form>
      <input type="hidden" name="type" data-delete-type>
      <input type="hidden" name="name" data-delete-name>
      <input type="hidden" name="scope" data-delete-scope>
      <p class="confirm-copy">Delete <strong data-delete-label></strong>? This removes the source file.</p>
      <div class="form-actions">
        <button type="submit" class="danger">Delete</button>
        <button type="button" class="secondary" data-close-delete-modal>Cancel</button>
      </div>
    </form>
  </section>
</div>"""


def render_harness_nav(content_type: str, selected_name: str | None, scope: str) -> str:
    installed_rows = []
    other_rows = []
    active_section = "true" if content_type == "harnesses" else "false"
    selected_in_other = False
    for name in list_names("harnesses"):
        path, raw, fields, _ = read_item("harnesses", name)
        label = str(fields.get("label") or name).strip()
        enabled = harness_enabled(fields)
        detected = harness_detected(fields)
        status_text = "Enabled" if enabled else ("Detected" if detected else "Disabled")
        active = " active" if content_type == "harnesses" and selected_name == name else ""
        if active and not enabled:
            selected_in_other = True
        href = (
            f"/?type=harnesses"
            f"&name={urllib.parse.quote(name)}"
            f"&scope={urllib.parse.quote(scope)}"
            "&view=form"
        )
        row = (
            f"""<a class="project-entry{active}" href="{href}">
  <span>{escape(name)}</span>
  <small>{escape(label)} · {escape(status_text)}</small>
</a>"""
        )
        if enabled:
            installed_rows.append(row)
        else:
            other_rows.append(row)
    new_href = f"/?type=harnesses&name=&scope={urllib.parse.quote(scope)}&view=form"
    installed_html = "".join(installed_rows) if installed_rows else '<p class="empty compact">No enabled harnesses.</p>'
    other_count = len(other_rows)
    other_hidden = "" if selected_in_other else " hidden"
    other_button = ""
    if other_rows:
        button_label = "Hide others" if selected_in_other else f"Show others ({other_count})"
        expanded = "true" if selected_in_other else "false"
        other_button = f"""<button type="button" class="rail-show-others-button" data-toggle-harness-others aria-expanded="{expanded}" aria-controls="rail-harness-other-list" data-show-label="Show others ({other_count})" data-hide-label="Hide others">{escape(button_label)}</button>
    <div class="harness-other-list" id="rail-harness-other-list"{other_hidden}>
      {"".join(other_rows)}
    </div>"""
    return f"""
<div class="project-nav harness-nav" data-rail-section="harnesses" data-active-section="{active_section}">
  <div class="project-nav-head">
    <h2><button type="button" class="rail-section-toggle" aria-expanded="true" aria-controls="rail-section-harnesses" data-collapse-section="harnesses"><span class="rail-caret" aria-hidden="true">&gt;</span><span>Harnesses</span></button></h2>
    <a class="add-project-button" href="{new_href}" title="Add harness" aria-label="Add harness">+</a>
  </div>
  <div class="rail-section-body" id="rail-section-harnesses" data-collapse-body="harnesses">
    {installed_html}
    {other_button}
  </div>
</div>"""


def render_template_nav(content_type: str, selected_name: str | None, scope: str, template_type: str = "agents") -> str:
    rows = []
    active_section = "true" if content_type == "templates" else "false"
    if template_type not in TEMPLATE_TARGET_TYPES:
        template_type = "agents"
    counts = {target_type: 0 for target_type in TEMPLATE_TARGET_TYPES}
    for name in list_names("templates"):
        try:
            _, _, fields, _ = read_item("templates", name)
        except OSError:
            fields = {}
        target_type = str(fields.get("type") or "").strip()
        if target_type in counts:
            counts[target_type] += 1
    ordered_types = sorted(TEMPLATE_TARGET_TYPES, key=lambda item: TEMPLATE_TYPE_LABELS.get(item, item))
    for target_type in ordered_types:
        label = TEMPLATE_TYPE_LABELS.get(target_type, target_type.title())
        count = counts.get(target_type, 0)
        active = " active" if content_type == "templates" and target_type == template_type else ""
        href = (
            f"/?type=templates"
            f"&template_type={urllib.parse.quote(target_type)}"
            f"&scope={urllib.parse.quote(scope)}"
        )
        rows.append(
            f"""<a class="project-entry{active}" href="{href}">
  <span>{escape(label)}</span>
  <small>{count} template{'' if count == 1 else 's'}</small>
</a>"""
        )
    new_href = f"/?type=templates&name=&scope={urllib.parse.quote(scope)}&template_type={urllib.parse.quote(template_type)}"
    return f"""
<div class="project-nav template-nav" data-rail-section="templates" data-active-section="{active_section}">
  <div class="project-nav-head">
    <h2><button type="button" class="rail-section-toggle" aria-expanded="true" aria-controls="rail-section-templates" data-collapse-section="templates"><span class="rail-caret" aria-hidden="true">&gt;</span><span>Templates</span></button></h2>
    <a class="add-project-button" href="{new_href}" title="Add template" aria-label="Add template">+</a>
  </div>
  <div class="rail-section-body" id="rail-section-templates" data-collapse-body="templates">
    {"".join(rows) if rows else '<p class="empty compact">No templates yet.</p>'}
  </div>
</div>"""


def singular_type(content_type: str) -> str:
    if content_type == "mcp":
        return "MCP server"
    if content_type == "harnesses":
        return "harness"
    if content_type.endswith("ies"):
        return content_type[:-3] + "y"
    if content_type.endswith("s"):
        return content_type[:-1]
    return content_type


def render_selection_page(
    content_type: str,
    summaries: list[dict[str, str]],
    installed: set[str],
    scope: str,
    selection_page: int,
    filters: dict[str, str],
) -> str:
    singular = singular_type(content_type)
    group_names, memberships = group_memberships(content_type)
    normalized_filters = normalize_selection_filters(filters, group_names)
    templates = template_memberships(content_type)
    counts = install_counts(content_type, [item["name"] for item in summaries])
    _, project_installed = scope_installed_names(content_type, scope)
    annotated = []
    for item in summaries:
        enriched = dict(item)
        enriched["groups"] = memberships.get(item["name"], [])
        enriched["templates"] = templates.get(item["name"], [])
        enriched["install_count"] = counts.get(item["name"], 0)
        enriched["installed"] = item["name"] in installed
        enriched["harness_statuses"] = (
            harness_item_statuses(content_type, item["name"], scope) if content_type in CONTENT_TYPES else {}
        )
        enriched["global_loaded"] = is_loaded_globally(content_type, item["name"], installed, scope)
        enriched["project_loaded"] = any(
            bool(status.get("checked")) for status in enriched.get("harness_statuses", {}).values()
        ) or item["name"] in project_installed
        annotated.append(enriched)
    filtered = filter_selection_items(annotated, normalized_filters)
    filtered = sort_selection_items(filtered, normalized_filters["sort"])
    source_mode = str(normalized_filters.get("source_mode") or "managed")
    if content_type != "agents":
        source_mode = "managed"
        normalized_filters["source_mode"] = "managed"
    show_managed = source_mode in {"managed", "combined"}
    show_external = content_type == "agents" and source_mode in {"combined", "external"}
    external_items = []
    if show_external:
        external_items = sort_external_items(filter_external_items(external_item_candidates(content_type, scope), normalized_filters), normalized_filters["sort"])
    new_view = "&view=file" if content_type in {"groups"} else ""
    entries: list[tuple[str, dict[str, Any]]] = []
    if show_external:
        entries.extend(("external", item) for item in external_items)
    if show_managed:
        entries.extend(("managed", item) for item in filtered)
    per_page = int(normalized_filters["per_page"])
    total_pages = max(1, (len(entries) + per_page - 1) // per_page)
    current_page = min(max(1, selection_page), total_pages)
    start = (current_page - 1) * per_page
    end = start + per_page
    cards = []
    for kind, item in entries[start:end]:
        if kind == "external":
            cards.append(render_external_card(content_type, item, scope, current_page, normalized_filters))
        else:
            cards.append(render_selection_card(content_type, item, installed, scope, current_page, normalized_filters))
    if source_mode == "external" and content_type == "agents":
        count = f"{len(external_items)} external item" + ("" if len(external_items) == 1 else "s")
    elif source_mode == "combined" and content_type == "agents":
        count = f"{len(entries)} items ({len(external_items)} external, {len(filtered)} managed)"
    else:
        count = f"{len(filtered)} of {len(summaries)} item" + ("" if len(summaries) == 1 else "s")
    summary = render_selection_summary(content_type, scope, normalized_filters, group_names)
    actions = render_selection_actions(content_type, scope, singular, new_view, normalized_filters)
    pagination = render_selection_pagination(content_type, scope, current_page, total_pages, normalized_filters, count)
    return f"""<section class="selection-page">
  {actions}
  {summary}
  <div class="selection-grid">{"".join(cards)}</div>
  {pagination}
</section>"""


def normalize_selection_filters(filters: dict[str, str], group_names: list[str] | None = None) -> dict[str, Any]:
    available_groups = group_names or []
    raw_groups = filters.get("group", [])
    if isinstance(raw_groups, str):
        group_values = [value for value in raw_groups.split(",") if value]
    else:
        group_values = [str(value) for value in raw_groups]
    group_filter = bool(filters.get("group_filter"))
    group_none = HARNESS_NONE_VALUE in group_values
    groups = [group for group in dict.fromkeys(group_values) if group in available_groups]
    if not group_filter and not groups and not group_none:
        groups = list(available_groups)
        group_none = True

    raw_harnesses = filters.get("harness", [])
    if isinstance(raw_harnesses, str):
        harness_values = [value for value in raw_harnesses.split(",") if value]
    else:
        harness_values = [str(value) for value in raw_harnesses]
    harness_filter = bool(filters.get("harness_filter"))
    harness_none = HARNESS_NONE_VALUE in harness_values
    harnesses = [harness for harness in dict.fromkeys(harness_values) if harness in ALL_HARNESSES]
    if not harness_filter and not harnesses and not harness_none:
        harnesses = list(ALL_HARNESSES)
        harness_none = True
    sort = filters.get("sort", DEFAULT_SELECTION_SORT)
    if sort not in SORT_OPTIONS:
        sort = DEFAULT_SELECTION_SORT
    per_page = positive_int(filters.get("per_page"), DEFAULT_SELECTION_ITEMS_PER_PAGE)
    per_page = min(MAX_SELECTION_ITEMS_PER_PAGE, max(MIN_SELECTION_ITEMS_PER_PAGE, per_page))
    source_mode = str(filters.get("source") or "").strip()
    if source_mode not in SOURCE_FILTER_MODES:
        source_mode = "combined" if filters.get("external") else "managed"
    hide_global_loaded = bool(filters.get("hide_global_loaded"))
    template_type = str(filters.get("template_type") or "agents").strip()
    if template_type not in TEMPLATE_TARGET_TYPES:
        template_type = "agents"
    return {
        "q": filters.get("q", "").strip(),
        "groups": groups,
        "group_none": group_none,
        "group_filter": group_filter,
        "harnesses": harnesses,
        "harness_none": harness_none,
        "harness_filter": harness_filter,
        "sort": sort,
        "per_page": str(per_page),
        "source_mode": source_mode,
        "hide_global_loaded": hide_global_loaded,
        "template_type": template_type,
    }


def filter_selection_items(items: list[dict[str, Any]], filters: dict[str, str]) -> list[dict[str, Any]]:
    query = filters["q"].casefold()
    groups = filters["groups"]
    group_none = bool(filters.get("group_none"))
    group_filter = bool(filters.get("group_filter"))
    harnesses = filters["harnesses"]
    harness_none = bool(filters.get("harness_none"))
    harness_filter = bool(filters.get("harness_filter"))
    result = []
    for item in items:
        haystack = " ".join(
            [
                str(item.get("name", "")),
                str(item.get("description", "")),
                str(item.get("path", "")),
                " ".join(item.get("groups", [])),
            ]
        ).casefold()
        if query and query not in haystack:
            continue
        if filters.get("hide_global_loaded") and item.get("global_loaded") and not item.get("project_loaded"):
            continue
        if group_filter:
            item_groups = item.get("groups", [])
            matches_group = any(group in item_groups for group in groups)
            matches_none = group_none and not item_groups
            if not matches_group and not matches_none:
                continue
        if harness_filter:
            statuses = item.get("harness_statuses", {})
            has_any_harness = any(status.get("checked") for status in statuses.values())
            matches_harness = any(statuses.get(harness, {}).get("checked") for harness in harnesses)
            matches_none = harness_none and not has_any_harness
            if not matches_harness and not matches_none:
                continue
        result.append(item)
    return result


def filter_external_items(items: list[dict[str, Any]], filters: dict[str, Any]) -> list[dict[str, Any]]:
    query = filters["q"].casefold()
    group_filter = bool(filters.get("group_filter"))
    group_none = bool(filters.get("group_none"))
    harness_filter = bool(filters.get("harness_filter"))
    harnesses = set(filters.get("harnesses") or [])
    result = []
    for item in items:
        haystack = " ".join(
            [
                str(item.get("name", "")),
                str(item.get("description", "")),
                str(item.get("path", "")),
                str(item.get("harness_label", "")),
                str(item.get("harness", "")),
            ]
        ).casefold()
        if query and query not in haystack:
            continue
        if group_filter and not group_none:
            continue
        if harness_filter and str(item.get("harness", "")) not in harnesses:
            continue
        result.append(item)
    return result


def sort_selection_items(items: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    if sort == "name-desc":
        return sorted(items, key=lambda item: str(item.get("name", "")).casefold(), reverse=True)
    if sort == "installed-desc":
        return sorted(items, key=lambda item: (-int(item.get("install_count", 0)), str(item.get("name", "")).casefold()))
    if sort == "installed-asc":
        return sorted(items, key=lambda item: (int(item.get("install_count", 0)), str(item.get("name", "")).casefold()))
    if sort == "created-desc":
        return sorted(items, key=lambda item: (-float(item.get("created_ts") or 0), str(item.get("name", "")).casefold()))
    if sort == "created-asc":
        return sorted(items, key=lambda item: (float(item.get("created_ts") or 0), str(item.get("name", "")).casefold()))
    if sort == "modified-desc":
        return sorted(items, key=lambda item: (-float(item.get("modified_ts") or 0), str(item.get("name", "")).casefold()))
    if sort == "modified-asc":
        return sorted(items, key=lambda item: (float(item.get("modified_ts") or 0), str(item.get("name", "")).casefold()))
    return sorted(items, key=lambda item: str(item.get("name", "")).casefold())


def sort_external_items(items: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    if sort == "name-desc":
        return sorted(items, key=lambda item: str(item.get("name", "")).casefold(), reverse=True)
    if sort == "created-desc":
        return sorted(items, key=lambda item: (-float(item.get("created_ts") or 0), str(item.get("name", "")).casefold()))
    if sort == "created-asc":
        return sorted(items, key=lambda item: (float(item.get("created_ts") or 0), str(item.get("name", "")).casefold()))
    if sort == "modified-desc":
        return sorted(items, key=lambda item: (-float(item.get("modified_ts") or 0), str(item.get("name", "")).casefold()))
    if sort == "modified-asc":
        return sorted(items, key=lambda item: (float(item.get("modified_ts") or 0), str(item.get("name", "")).casefold()))
    if sort == "name-asc":
        return sorted(items, key=lambda item: str(item.get("name", "")).casefold())
    return sorted(items, key=lambda item: (str(item.get("harness_label", "")).casefold(), str(item.get("name", "")).casefold()))


def selection_query_params(filters: dict[str, str]) -> str:
    params = {}
    if filters.get("q"):
        params["q"] = filters["q"]
    groups = filters.get("groups") or []
    group_none = bool(filters.get("group_none"))
    if filters.get("group_filter"):
        params["group_filter"] = "1"
        if groups:
            params["group"] = list(groups)
        if group_none:
            params.setdefault("group", [])
            params["group"].append(HARNESS_NONE_VALUE)
    harnesses = filters.get("harnesses") or []
    harness_none = bool(filters.get("harness_none"))
    if filters.get("harness_filter"):
        params["harness_filter"] = "1"
        if harnesses:
            params["harness"] = list(harnesses)
        if harness_none:
            params.setdefault("harness", [])
            params["harness"].append(HARNESS_NONE_VALUE)
    if filters.get("sort") and filters["sort"] != DEFAULT_SELECTION_SORT:
        params["sort"] = filters["sort"]
    if filters.get("per_page") and filters["per_page"] != str(DEFAULT_SELECTION_ITEMS_PER_PAGE):
        params["per_page"] = filters["per_page"]
    if filters.get("source_mode") and filters["source_mode"] != "managed":
        params["source"] = filters["source_mode"]
    if filters.get("hide_global_loaded"):
        params["hide_global_loaded"] = "1"
    if filters.get("template_type") and filters["template_type"] != "agents":
        params["template_type"] = filters["template_type"]
    return urllib.parse.urlencode(params, doseq=True)


def filter_hidden_inputs(filters: dict[str, Any]) -> str:
    fields = []
    if filters.get("q"):
        fields.append(f'<input type="hidden" name="q" value="{escape(filters["q"])}">')
    if filters.get("group_filter"):
        fields.append('<input type="hidden" name="group_filter" value="1">')
        for group in filters.get("groups") or []:
            fields.append(f'<input type="hidden" name="group" value="{escape(group)}">')
        if filters.get("group_none"):
            fields.append(f'<input type="hidden" name="group" value="{HARNESS_NONE_VALUE}">')
    if filters.get("harness_filter"):
        fields.append('<input type="hidden" name="harness_filter" value="1">')
        for harness in filters.get("harnesses") or []:
            fields.append(f'<input type="hidden" name="harness" value="{escape(harness)}">')
        if filters.get("harness_none"):
            fields.append(f'<input type="hidden" name="harness" value="{HARNESS_NONE_VALUE}">')
    if filters.get("sort") and filters["sort"] != DEFAULT_SELECTION_SORT:
        fields.append(f'<input type="hidden" name="sort" value="{escape(filters["sort"])}">')
    if filters.get("per_page"):
        fields.append(f'<input type="hidden" name="per_page" value="{escape(filters["per_page"])}" data-dynamic-per-page>')
    if filters.get("source_mode") and filters["source_mode"] != "managed":
        fields.append(f'<input type="hidden" name="source" value="{escape(filters["source_mode"])}">')
    if filters.get("hide_global_loaded"):
        fields.append('<input type="hidden" name="hide_global_loaded" value="1">')
    if filters.get("template_type"):
        fields.append(f'<input type="hidden" name="template_type" value="{escape(filters["template_type"])}">')
    return "\n".join(fields)


def render_selection_summary(
    content_type: str,
    scope: str,
    filters: dict[str, str],
    group_names: list[str],
) -> str:
    source_hidden = (
        f'<input type="hidden" name="source" value="{escape(filters["source_mode"])}">'
        if filters.get("source_mode") and filters["source_mode"] != "managed"
        else ""
    )
    hide_global_hidden = '<input type="hidden" name="hide_global_loaded" value="1">' if filters.get("hide_global_loaded") else ""
    template_hidden = (
        f'<input type="hidden" name="template_type" value="{escape(filters["template_type"])}">'
        if content_type == "templates" and filters.get("template_type")
        else ""
    )
    return f"""<div class="selection-summary-row">
  <form class="selection-summary-controls" method="get" action="/">
    <input type="hidden" name="type" value="{escape(content_type)}">
    <input type="hidden" name="scope" value="{escape(scope)}" data-scope-hidden>
    <input type="hidden" name="per_page" value="{escape(filters["per_page"])}" data-dynamic-per-page>
    {source_hidden}
    {hide_global_hidden}
    {template_hidden}
    <label class="selection-search">
      <span>Search</span>
      <input name="q" value="{escape(filters["q"])}" placeholder="Search names, descriptions, groups" aria-label="Search" data-filter-search>
    </label>
    {render_group_filter_multiselect(filters["groups"], bool(filters.get("group_none")), group_names)}
    {render_harness_filter_multiselect(filters["harnesses"], bool(filters.get("harness_none")))}
    {render_sort_filter_dropdown(filters["sort"])}
  </form>
</div>"""


def render_selection_actions(content_type: str, scope: str, singular: str, new_view: str, filters: dict[str, Any]) -> str:
    create_href = f"/?type={urllib.parse.quote(content_type)}&name=&scope={urllib.parse.quote(scope)}{new_view}"
    if content_type == "templates":
        template_param = urllib.parse.quote(str(filters.get("template_type") or "agents"))
        create_href += f"&template_type={template_param}"
    disabled = " disabled" if content_type != "agents" else ""
    source_mode = str(filters.get("source_mode") or "managed")
    source_fields = filter_hidden_inputs({key: value for key, value in filters.items() if key not in {"source_mode", "hide_global_loaded"}})
    hide_checked = " checked" if filters.get("hide_global_loaded") else ""
    hide_disabled = " disabled" if content_type not in CONTENT_TYPES or is_global_scope(scope) else ""
    hide_global_control = f"""<label class="hide-global-loaded-option">
      <input type="checkbox" name="hide_global_loaded" value="1"{hide_checked}{hide_disabled} data-filter-auto-submit>
      <span>Hide globally loaded</span>
    </label>"""
    source_options = []
    for value, label in (("managed", "App managed"), ("combined", "Combined"), ("external", "External")):
        checked = " checked" if source_mode == value else ""
        source_options.append(
            f"""<label class="source-mode-option">
        <input type="radio" name="source" value="{value}"{checked}{disabled} data-filter-auto-submit>
        <span>{label}</span>
      </label>"""
        )
    return f"""<div class="selection-bottom-actions">
  <div class="selection-action-buttons">
    <a class="button" href="{create_href}">Create {escape(singular.title())}</a>
    <button type="button" class="button secondary" data-open-import-modal data-import-type="{escape(content_type)}" data-import-scope="{escape(scope)}">Import</button>
  </div>
  <form class="source-mode-form" method="get" action="/">
    <input type="hidden" name="type" value="{escape(content_type)}">
    <input type="hidden" name="scope" value="{escape(scope)}" data-scope-hidden>
    {source_fields}
    {hide_global_control}
    <fieldset class="source-mode-group" aria-label="Source">
      {"".join(source_options)}
    </fieldset>
  </form>
</div>"""


def render_sort_filter_dropdown(selected_sort: str) -> str:
    selected_label = SORT_OPTIONS.get(selected_sort, SORT_OPTIONS[DEFAULT_SELECTION_SORT])
    rows = []
    for value, label in SORT_OPTIONS.items():
        checked = " checked" if value == selected_sort else ""
        rows.append(
            f"""<label class="harness-option">
    <input type="radio" name="sort" value="{escape(value)}"{checked} data-filter-auto-submit>
    <span>{escape(label)}</span>
  </label>"""
        )
    return f"""<div class="sort-filter-field control-field">
      <span>Sort</span>
      <details class="harness-multiselect filter-multiselect sort-filter-dropdown" data-harness-menu>
        <summary data-harness-summary data-summary-label="Sort" aria-label="Sort: {escape(selected_label)}"><span data-harness-summary-text>{escape(selected_label)}</span><span class="multiselect-caret" aria-hidden="true"></span></summary>
        <fieldset class="harness-menu-options">
          <legend class="sr-only">Sort</legend>
          {"".join(rows)}
        </fieldset>
      </details>
    </div>"""


def render_filter_multiselect(
    label: str,
    field_name: str,
    hidden_name: str,
    selected_values: list[str],
    include_none: bool,
    options: list[tuple[str, str]],
    css_class: str,
) -> str:
    selected = set(selected_values)
    selected_count = len(selected) + (1 if include_none else 0)
    option_count = len(options) + 1
    if selected_count == 0:
        summary = "None selected"
    elif include_none and not selected:
        summary = "None"
    elif selected_count == option_count:
        summary = "All"
    else:
        summary = f"{selected_count} selected"
    rows = [
        f'<input type="hidden" name="{escape(hidden_name)}" value="1">',
        """<div class="harness-menu-actions">
    <button type="button" data-harness-select-all>Select all</button>
    <button type="button" data-harness-deselect-all>Deselect all</button>
  </div>""",
    ]
    none_checked = " checked" if include_none else ""
    rows.append(
        f"""<label class="harness-option harness-option-none">
    <input type="checkbox" name="{escape(field_name)}" value="{HARNESS_NONE_VALUE}"{none_checked} data-harness-target>
    <span>None</span>
  </label>"""
    )
    for value, option_label in options:
        checked = " checked" if value in selected else ""
        rows.append(
            f"""<label class="harness-option">
    <input type="checkbox" name="{escape(field_name)}" value="{escape(value)}"{checked} data-harness-target>
    <span>{escape(option_label)}</span>
  </label>"""
        )
    return f"""<div class="{escape(css_class)} control-field">
      <span>{escape(label)}</span>
      <details class="harness-multiselect filter-multiselect" data-harness-menu data-filter-multiselect-menu>
        <summary data-harness-summary data-summary-label="{escape(label)} filter" aria-label="{escape(label)} filter: {escape(summary)}"><span data-harness-summary-text>{escape(summary)}</span><span class="multiselect-caret" aria-hidden="true"></span></summary>
        <fieldset class="harness-menu-options">
          <legend class="sr-only">{escape(label)}</legend>
          {"".join(rows)}
        </fieldset>
      </details>
    </div>"""


def render_group_filter_multiselect(selected_groups: list[str], include_none: bool, group_names: list[str]) -> str:
    return render_filter_multiselect(
        "Group",
        "group",
        "group_filter",
        selected_groups,
        include_none,
        [(group_name, group_name) for group_name in group_names],
        "group-filter-field",
    )


def render_harness_filter_multiselect(selected_harnesses: list[str], include_none: bool) -> str:
    options = []
    for harness in ALL_HARNESSES:
        definition = HARNESS_DEFINITIONS.get(harness, {})
        label = str(definition.get("label") or harness).strip()
        options.append((harness, label))
    return render_filter_multiselect(
        "Harness",
        "harness",
        "harness_filter",
        selected_harnesses,
        include_none,
        options,
        "harness-filter-field",
    )


def render_harness_multiselect(statuses: dict[str, dict[str, Any]]) -> str:
    supported_statuses = [status for status in statuses.values() if status.get("supported")]
    checked_count = sum(1 for status in supported_statuses if status.get("checked"))
    if not supported_statuses or checked_count == 0:
        summary = "None"
    elif checked_count == len(supported_statuses):
        summary = "All"
    else:
        summary = f"{checked_count} selected"
    options = []
    options.append(
        """<div class="harness-menu-actions">
    <button type="button" data-harness-select-all>Select all</button>
    <button type="button" data-harness-deselect-all>Deselect all</button>
  </div>"""
    )
    for harness in ALL_HARNESSES:
        definition = HARNESS_DEFINITIONS.get(harness, {})
        label = str(definition.get("label") or harness).strip()
        status = statuses.get(harness, {})
        checked = " checked" if status.get("checked") else ""
        disabled = "" if status.get("supported") else " disabled"
        options.append(
            f"""<label class="harness-option">
    <input type="checkbox" name="targets" value="{escape(harness)}"{checked}{disabled} data-harness-target>
    <span>{escape(label)}</span>
  </label>"""
        )
    return f"""<details class="harness-multiselect" data-harness-menu>
  <summary data-harness-summary data-summary-label="Harness targets" aria-label="Harness targets: {escape(summary)}"><span data-harness-summary-text>{escape(summary)}</span><span class="multiselect-caret" aria-hidden="true"></span></summary>
  <fieldset class="harness-menu-options">
    <legend class="sr-only">Harnesses</legend>
    {"".join(options)}
  </fieldset>
</details>"""


def render_selection_card(
    content_type: str,
    item: dict[str, str],
    installed: set[str],
    scope: str,
    current_page: int,
    filters: dict[str, str],
) -> str:
    name = item["name"]
    is_installed = name in installed
    loaded_globally = is_loaded_globally(content_type, name, installed, scope)
    global_harnesses: list[str] = []
    project_harnesses: list[str] = []
    if content_type in CONTENT_TYPES:
        if is_global_scope(scope):
            if is_installed:
                global_harnesses = checked_harness_labels(harness_item_statuses(content_type, name, "global"))
        else:
            global_harnesses = checked_harness_labels(harness_item_statuses(content_type, name, "global"))
            project_harnesses = checked_harness_labels(item.get("harness_statuses") or harness_item_statuses(content_type, name, scope))
        if (is_installed or loaded_globally) and not global_harnesses and name in installed:
            global_harnesses = ["Global installed marker"]
    meta = item["description"] or item["path"]
    install_count = int(item.get("install_count", 0))
    project_label = f"{install_count} project" + ("" if install_count == 1 else "s")
    group_count = len(item.get("groups", []))
    group_label = f"{group_count} group" + ("" if group_count == 1 else "s")
    if content_type == "templates":
        template_label = TEMPLATE_TYPE_LABELS.get(str(item.get("template_type") or ""), "Template")
        section_count = int(item.get("section_count") or 0)
        field_count = int(item.get("field_count") or 0)
        project_label = template_label
        group_label = f"{section_count} section{'' if section_count == 1 else 's'} · {field_count} field{'' if field_count == 1 else 's'}"
    created_at = str(item.get("created_at") or "unknown")
    modified_at = str(item.get("modified_at") or "unknown")
    view = ""
    edit_href = (
        f"/?type={urllib.parse.quote(content_type)}"
        f"&name={urllib.parse.quote(name)}"
        f"&scope={urllib.parse.quote(scope)}"
        f"{view}"
    )
    install_control = ""
    if content_type in CONTENT_TYPES:
        extra = selection_query_params(filters)
        return_to = f"/?type={urllib.parse.quote(content_type)}&scope={urllib.parse.quote(scope)}&page={current_page}"
        if extra:
            return_to += f"&{extra}"
        harness_statuses = harness_item_statuses(content_type, name, scope)
        install_control = f"""<form class="selection-card-form selection-card-update-form" action="/install" method="post">
  <input type="hidden" name="type" value="{escape(content_type)}">
  <input type="hidden" name="name" value="{escape(name)}">
  <input type="hidden" name="action" value="install">
  <input type="hidden" name="harness_update" value="1">
  <input type="hidden" name="scope" value="{escape(scope)}" data-scope-hidden>
  <input type="hidden" name="return_to" value="{escape(return_to)}">
  {render_harness_multiselect(harness_statuses)}
  <button type="submit" class="secondary selection-card-action-update">Update</button>
</form>"""
    else:
        install_control = """<button type="button" class="secondary selection-card-action-update" disabled>Update</button>"""
    preview_attrs = ""
    if content_type in PREVIEW_TYPES:
        preview_attrs = f""" data-selection-preview-card data-preview-type="{escape(content_type)}" data-preview-name="{escape(name)}" tabindex="0" aria-label="Preview {escape(name)}" title="Preview {escape(name)}" """
    classes = ["selection-card"]
    if content_type == "templates":
        classes.append("template-selection-card")
    if loaded_globally:
        classes.append("global-loaded-selection-card")
    card_class = " ".join(classes)
    scope_icons = render_selection_scope_icons(global_harnesses, project_harnesses)
    return f"""<article class="{card_class}"{preview_attrs}>
  <div class="selection-card-main">
    <div class="selection-card-title">
      <span class="selection-card-name">{escape(name)}</span>
      {scope_icons}
      <a class="selection-card-edit" href="{edit_href}" title="Edit {escape(name)}" aria-label="Edit {escape(name)}" data-selection-edit-button data-edit-type="{escape(content_type)}" data-edit-name="{escape(name)}" data-edit-scope="{escape(scope)}" data-edit-view="form">Edit</a>
    </div>
    <small>{escape(meta)}</small>
  </div>
  <div class="selection-card-meta">
    <p class="selection-card-counts"><span>{escape(project_label)}</span><span>{escape(group_label)}</span></p>
    <p class="selection-card-dates"><span>Created: {escape(created_at)}</span><span>Modified: {escape(modified_at)}</span></p>
  </div>
  <div class="selection-card-actions">
    {install_control}
  </div>
</article>"""


def render_selection_scope_icons(global_harnesses: list[str], project_harnesses: list[str]) -> str:
    icons = []
    if global_harnesses:
        tooltip = render_scope_tooltip("Global", global_harnesses)
        aria = "Global: " + ", ".join(global_harnesses)
        icons.append(
            f"""<span class="selection-card-scope-indicator global" aria-label="{escape(aria)}" tabindex="0">
  <span class="scope-indicator-icon" aria-hidden="true">{scope_indicator_svg("global")}</span>
  {tooltip}
</span>"""
        )
    if project_harnesses:
        tooltip = render_scope_tooltip("Project", project_harnesses)
        aria = "Project: " + ", ".join(project_harnesses)
        icons.append(
            f"""<span class="selection-card-scope-indicator project" aria-label="{escape(aria)}" tabindex="0">
  <span class="scope-indicator-icon" aria-hidden="true">{scope_indicator_svg("project")}</span>
  {tooltip}
</span>"""
        )
    if not icons:
        return ""
    return f'<span class="selection-card-scope-icons">{"".join(icons)}</span>'


def render_scope_tooltip(header: str, harnesses: list[str]) -> str:
    items = "".join(f"<li>{escape(harness)}</li>" for harness in harnesses)
    return f"""<span class="scope-tooltip" role="tooltip">
  <span class="scope-tooltip-title">{escape(header)}</span>
  <ul>{items}</ul>
</span>"""


def scope_indicator_svg(kind: str) -> str:
    if kind == "project":
        return """<svg viewBox="0 0 24 24" focusable="false">
  <path d="M3.5 6.5h6l2 2h9v9.5a2 2 0 0 1-2 2h-15a2 2 0 0 1-2-2v-9.5a2 2 0 0 1 2-2Z"></path>
  <path d="M3.5 8.5h17"></path>
</svg>"""
    return """<svg viewBox="0 0 24 24" focusable="false">
  <circle cx="12" cy="12" r="8.5"></circle>
  <path d="M3.5 12h17"></path>
  <path d="M12 3.5c2.2 2.4 3.2 5.2 3.2 8.5s-1 6.1-3.2 8.5"></path>
  <path d="M12 3.5c-2.2 2.4-3.2 5.2-3.2 8.5s1 6.1 3.2 8.5"></path>
</svg>"""


def render_external_card(
    content_type: str,
    item: dict[str, Any],
    scope: str,
    current_page: int,
    filters: dict[str, Any],
) -> str:
    name = str(item.get("name") or "")
    harness = str(item.get("harness") or "")
    harness_label = str(item.get("harness_label") or harness)
    source_path = str(item.get("path") or "")
    description = str(item.get("description") or source_path or "External item")
    created_at = str(item.get("created_at") or "unknown")
    modified_at = str(item.get("modified_at") or "unknown")
    extra = selection_query_params(filters)
    return_to = f"/?type={urllib.parse.quote(content_type)}&scope={urllib.parse.quote(scope)}&page={current_page}"
    if extra:
        return_to += f"&{extra}"
    duplicate = bool(item.get("source_exists"))
    button = (
        '<button type="submit" class="secondary selection-card-action-update">Import</button>'
        if not duplicate
        else '<button type="button" class="secondary selection-card-action-update" disabled>Managed</button>'
    )
    duplicate_note = "Already managed" if duplicate else "External"
    preview_attrs = (
        f""" data-external-preview-card data-external-type="{escape(content_type)}" data-external-name="{escape(name)}" data-external-harness="{escape(harness)}" data-external-path="{escape(source_path)}" data-external-scope="{escape(scope)}" tabindex="0" aria-label="Preview external {escape(name)}" title="Preview external {escape(name)}" """
    )
    return f"""<article class="selection-card external-selection-card"{preview_attrs}>
  <div class="selection-card-main">
    <div class="selection-card-title">
      <span>{escape(name)}</span>
      <a class="selection-card-edit" href="#" title="Edit external {escape(name)}" aria-label="Edit external {escape(name)}" data-external-edit-button data-external-type="{escape(content_type)}" data-external-name="{escape(name)}" data-external-harness="{escape(harness)}" data-external-path="{escape(source_path)}" data-external-scope="{escape(scope)}">Edit</a>
    </div>
    <small>{escape(description)}</small>
  </div>
  <div class="selection-card-meta">
    <p class="selection-card-counts"><span>{escape(duplicate_note)}</span><span>{escape(harness_label)}</span></p>
    <p class="selection-card-dates"><span>Created: {escape(created_at)}</span><span>Modified: {escape(modified_at)}</span></p>
  </div>
  <div class="selection-card-actions">
    <form class="selection-card-form external-import-form" action="/import-external" method="post">
      <input type="hidden" name="type" value="{escape(content_type)}">
      <input type="hidden" name="name" value="{escape(name)}">
      <input type="hidden" name="harness" value="{escape(harness)}">
      <input type="hidden" name="path" value="{escape(source_path)}">
      <input type="hidden" name="scope" value="{escape(scope)}" data-scope-hidden>
      <input type="hidden" name="return_to" value="{escape(return_to)}">
      {button}
    </form>
  </div>
</article>"""


def render_selection_pagination(
    content_type: str,
    scope: str,
    current_page: int,
    total_pages: int,
    filters: dict[str, str],
    count: str,
) -> str:
    extra = selection_query_params(filters)

    def page_href(page_number: int) -> str:
        href = (
            f"/?type={urllib.parse.quote(content_type)}"
            f"&scope={urllib.parse.quote(scope)}"
            f"&page={page_number}"
        )
        if extra:
            href += f"&{extra}"
        return href

    links = []
    if total_pages > 1:
        if current_page > 1:
            links.append(f'<a class="page-link" href="{page_href(current_page - 1)}">Previous</a>')
        else:
            links.append('<span class="page-link disabled">Previous</span>')
        for page_number in range(1, total_pages + 1):
            active = " active" if page_number == current_page else ""
            links.append(f'<a class="page-link{active}" href="{page_href(page_number)}">{page_number}</a>')
        if current_page < total_pages:
            links.append(f'<a class="page-link" href="{page_href(current_page + 1)}">Next</a>')
        else:
            links.append('<span class="page-link disabled">Next</span>')
    nav = f'<nav class="pagination" aria-label="Selection pages">{"".join(links)}</nav>' if links else ""
    return f"""<div class="pagination-footer">
  {nav}
  <p class="selection-summary">{escape(count)} - Page {current_page} of {total_pages}</p>
</div>"""


def render_sidebar(content_type: str, summaries: list[dict[str, str]], installed: set[str], selected: str, scope: str) -> str:
    rows = []
    for item in summaries:
        active = " active" if item["name"] == selected else ""
        marker = "Installed" if item["name"] in installed else ""
        rows.append(
            f"""<a class="item{active}" href="/?type={content_type}&name={urllib.parse.quote(item['name'])}&scope={urllib.parse.quote(scope)}">
  <span>{escape(item['name'])}</span>
  <small>{escape(marker or item['description'])}</small>
</a>"""
        )
    return f"""<aside class="list-pane">
  <div class="pane-head">
    <h2>{escape(content_type.title())}</h2>
    <a class="button secondary" href="/?type={content_type}&name=&scope={urllib.parse.quote(scope)}">New</a>
  </div>
  <div class="item-list">{"".join(rows) if rows else '<p class="empty">No items yet.</p>'}</div>
</aside>"""


def render_editor(content_type: str, name: str | None, installed: set[str], scope: str, view: str = "form", template_type: str = "agents") -> str:
    if not name:
        return render_new_editor(content_type, scope, view, template_type)
    if content_type not in EDITABLE_TYPES:
        return f"""<section class="editor"><h2>{escape(name)}</h2><p class="empty">This item type is read-only in the web UI.</p></section>"""
    path, raw, fields, body = read_item(content_type, name)
    if view == "file":
        return render_file_editor(content_type, name, raw, path, scope, name in installed)
    if content_type == "templates":
        try:
            definition = template_definition_from_raw(raw, name)
        except ValueError:
            return render_file_editor(content_type, name, raw, path, scope, name in installed)
        return render_template_editor(name, definition, raw, path, scope, name in installed)
    if content_type == "harnesses":
        try:
            definition = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return render_file_editor(content_type, name, raw, path, scope, name in installed)
        if not isinstance(definition, dict):
            return render_file_editor(content_type, name, raw, path, scope, name in installed)
        return render_harness_editor(name, definition, raw, path, scope, name in installed)
    if content_type == "hooks":
        return render_hook_editor(name, raw, path, scope, name in installed)
    if content_type in {"groups"}:
        return render_file_editor(content_type, name, raw, path, scope, name in installed)
    if content_type == "mcp" and path.suffix in {".json", ".yaml", ".yml"}:
        return render_mapping_editor(content_type, name, fields, raw, path, name in installed, scope)
    return render_markdown_editor(content_type, name, fields, body, raw, path, name in installed, scope)


def render_editor_from_form_state(form: dict[str, Any]) -> str:
    content_type = form.get("type", "agents")
    if content_type not in EDITABLE_TYPES:
        content_type = "agents"
    target_view = form.get("target_view", "file")
    if target_view not in EDITOR_VIEWS:
        target_view = "file"
    name = form.get("name", "").strip() or form.get("original_name", "").strip()
    scope = form.get("scope", "global")
    installed = set(load_installed_type(content_type)) if content_type in CONTENT_TYPES else set()
    raw, path = raw_from_form_state(form)
    if target_view == "file" or content_type in {"groups"}:
        return render_file_editor(content_type, name, raw, path, scope, name in installed)
    if content_type == "templates":
        definition = template_definition_from_raw(raw, name)
        return render_template_editor(name, definition, raw, path, scope, name in installed)
    if content_type == "harnesses":
        definition = json.loads(raw) if raw.strip() else {}
        if not isinstance(definition, dict):
            raise ValueError("Harness config must be a JSON object.")
        return render_harness_editor(name, definition, raw, path, scope, name in installed)
    if content_type == "hooks":
        return render_hook_editor(name, raw, path, scope, name in installed)
    if content_type == "mcp" and path.suffix == ".json":
        loaded = json.loads(raw) if raw.strip() else {}
        if not isinstance(loaded, dict):
            raise ValueError("JSON MCP source must be an object.")
        return render_mapping_editor(content_type, name, loaded, raw, path, name in installed, scope)
    if content_type == "mcp" and path.suffix in {".yaml", ".yml"}:
        loaded = yaml.safe_load(raw) if raw.strip() else {}
        if not isinstance(loaded, dict):
            raise ValueError("YAML MCP source must be a mapping.")
        return render_mapping_editor(content_type, name, loaded, raw, path, name in installed, scope)
    else:
        fields, body = parse_frontmatter_strict(raw)
    return render_markdown_editor(content_type, name, fields, body, raw, path, name in installed, scope)


def render_new_editor(content_type: str, scope: str, view: str = "form", template_type: str = "agents") -> str:
    if content_type == "groups":
        return render_file_editor(content_type, "", "# New item\n\n[agents]\n", content_path(content_type, "new"), scope, False)
    if content_type == "templates":
        if template_type not in TEMPLATE_TARGET_TYPES:
            template_type = "agents"
        default_template = default_template_for_type(template_type)
        definition = {
            "name": "new-template",
            "type": template_type,
            "description": "Reusable section template.",
            "sections": [
                {"title": title, "level": level, "content": content}
                for title, level, content in template_sections_for_editor(default_template)
            ]
            or [{"title": "Overview", "level": 2, "content": ""}],
            "field_sections": sanitize_template_field_sections(
                template_type,
                template_field_sections_for_editor(default_template),
            ),
        }
        raw = dump_template_definition(definition)
        path = content_path(content_type, "new-template")
        if view == "file":
            return render_file_editor(content_type, "", raw, path, scope, False)
        return render_template_editor("", definition, raw, path, scope, False)
    if content_type == "harnesses":
        raw = json.dumps(
            {
                "name": "new-harness",
                "label": "New Harness",
                "schemas": {"agents": ["name", "description", "model"], "skills": ["name", "description"]},
                "outputs": {"agents": {"extension": ".md"}, "skills": {"directory": True}},
                "sync": {
                    "paths": {
                        "project": {"agents": ".new-harness/agents/{name}.md", "skills": ".new-harness/skills/{name}/"},
                        "global": {"agents": ".new-harness/agents/{name}.md", "skills": ".new-harness/skills/{name}/"},
                    }
                },
            },
            indent=2,
        )
        path = content_path(content_type, "new")
        if view == "file":
            return render_file_editor(content_type, "", raw, path, scope, False)
        definition = json.loads(raw)
        return render_harness_editor("", definition, raw, path, scope, False)
    fields = {"name": "", "description": ""}
    body = ""
    path = content_path(content_type, "new")
    raw = serialize_markdown(fields, body)
    if content_type == "hooks":
        selected_template = default_template_for_type("hooks")
        selected_template_name = str(selected_template.get("name") or "") if selected_template else ""
        raw = "#!/usr/bin/env bash\n"
        if selected_template:
            raw = serialize_hook_script(template_fields_for_editor(selected_template))
        if view == "file":
            return render_file_editor(content_type, "", raw, path, scope, False)
        return render_hook_editor("", raw, path, scope, False, selected_template_name)
    if view == "file":
        return render_file_editor(content_type, "", raw, path, scope, False)
    return render_markdown_editor(content_type, "", fields, body, raw, path, False, scope, starter_sections=True)


def harness_supports_agent_model(harness: str) -> bool:
    schema = AGENT_SCHEMAS.get(harness, [])
    return isinstance(schema, list) and "model" in schema


def configured_agent_models(harness: str) -> list[str]:
    definition = HARNESS_DEFINITIONS.get(harness, {})
    models = definition.get("models", {}) if isinstance(definition, dict) else {}
    values = models.get("agents") if isinstance(models, dict) else []
    result = []
    if isinstance(values, list):
        for value in values:
            if isinstance(value, str) and value.strip():
                result.append(value.strip())
            elif isinstance(value, dict):
                model = str(value.get("value") or value.get("model") or value.get("name") or "").strip()
                if model:
                    result.append(model)
    return list(dict.fromkeys(result))


def default_model_options(harness: str, defaults: dict[str, Any]) -> list[tuple[str, str]]:
    harness_defaults = defaults.get(harness, {}) if isinstance(defaults, dict) else {}
    options = []
    for value, label in DEFAULT_MODEL_TIERS:
        model = ""
        tier_config = harness_defaults.get(value, {}) if isinstance(harness_defaults, dict) else {}
        if isinstance(tier_config, dict):
            model = str(tier_config.get("model") or "").strip()
        display = f"{label} ({model})" if model else label
        options.append((value, display))
    return options


def agent_model_options(harness: str, defaults: dict[str, Any], current: str = "") -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    defaults_options = default_model_options(harness, defaults)
    harness_defaults = defaults.get(harness, {}) if isinstance(defaults, dict) else {}
    model_values = configured_agent_models(harness)
    if isinstance(harness_defaults, dict):
        for tier_config in harness_defaults.values():
            if isinstance(tier_config, dict):
                model = str(tier_config.get("model") or "").strip()
                if model:
                    model_values.append(model)
    if current and current not in {value for value, _ in defaults_options}:
        model_values.append(current)
    models = [(value, value) for value in dict.fromkeys(value for value in model_values if value)]
    return defaults_options, models


def render_model_select(name: str, label: str, value: Any, defaults_options: list[tuple[str, str]], model_options: list[tuple[str, str]]) -> str:
    current = str(value or "default").strip()

    def option_rows(options: list[tuple[str, str]]) -> str:
        rows = []
        for option_value, option_label in options:
            selected = " selected" if option_value == current else ""
            rows.append(f'<option value="{escape(option_value)}"{selected}>{escape(option_label)}</option>')
        return "".join(rows)

    current_known = current in {value for value, _ in defaults_options + model_options}
    custom = "" if current_known else f'<option value="{escape(current)}" selected>{escape(current)}</option>'
    return f"""<label>
  <span>{escape(label)}</span>
  <select name="field_{escape(name)}">
    <optgroup label="Default tiers">
      {option_rows(defaults_options)}
    </optgroup>
    <optgroup label="Models">
      {custom}{option_rows(model_options)}
    </optgroup>
  </select>
</label>"""


def harness_supports_agent_sandbox(harness: str) -> bool:
    schema = AGENT_SCHEMAS.get(harness, [])
    if not isinstance(schema, list):
        return False
    return "sandbox" in schema or schema_supports_source_field(harness, "agents", "sandbox")


def sandbox_field_value(fields: dict[str, Any], harness: str) -> str:
    for key in (f"{harness}_sandbox", f"{harness}_sandbox_mode", "sandbox", "sandbox_mode"):
        if key in fields:
            return str(fields.get(key) or "").strip()
    return ""


def render_sandbox_select(harness: str, fields: dict[str, Any], label: str = "Sandbox") -> str:
    key = f"{harness}_sandbox"
    current = sandbox_field_value(fields, harness)
    rows = []
    known_values = {value for value, _ in SANDBOX_OPTIONS}
    if current and current not in known_values:
        rows.append(f'<option value="{escape(current)}" selected>{escape(current)}</option>')
    for value, option_label in SANDBOX_OPTIONS:
        selected = " selected" if value == current else ""
        rows.append(f'<option value="{escape(value)}"{selected}>{escape(option_label)}</option>')
    return f"""<label>
  <span>{escape(label)}</span>
  <select name="field_{escape(key)}">
    {"".join(rows)}
  </select>
</label>"""


def render_agent_model_inputs(fields: dict[str, Any]) -> str:
    defaults = load_defaults(DEFAULTS_FILE) if DEFAULTS_FILE.exists() else {}
    controls = []
    for harness in ALL_HARNESSES:
        if not harness_supports_agent_model(harness):
            continue
        key = f"{harness}_model"
        definition = HARNESS_DEFINITIONS.get(harness, {})
        label = str(definition.get("label") or harness).strip()
        model_value = str(fields.get(key) or "default")
        defaults_options, model_options = agent_model_options(harness, defaults, model_value)
        reasoning_field = harness_reasoning_field(harness)
        reasoning = render_reasoning_select(harness, reasoning_field, fields, defaults, model_value) if reasoning_field else render_disabled_reasoning_select()
        sandbox = render_sandbox_select(harness, fields) if harness_supports_agent_sandbox(harness) else ""
        controls.append(
            f"""<section class="agent-harness-settings">
  <h4>{escape(label)}</h4>
  {render_model_select(key, "Model", model_value, defaults_options, model_options)}
  {reasoning}
  {sandbox}
</section>"""
        )
    return f"""<fieldset class="agent-model-fields wide">
  <legend>Models</legend>
  <div class="agent-model-grid">{"".join(controls)}</div>
</fieldset>"""


def harness_reasoning_field(harness: str) -> str:
    schema = AGENT_SCHEMAS.get(harness, [])
    if not isinstance(schema, list):
        return ""
    preferred = REASONING_FIELDS.get(harness)
    if preferred and preferred in schema:
        return preferred
    for field_name in REASONING_OPTIONS:
        if field_name in schema:
            return field_name
    return ""


def reasoning_field_value(fields: dict[str, Any], harness: str, field_name: str) -> str:
    candidates = [f"{harness}_{field_name}", field_name]
    if field_name == "thinkingLevel":
        candidates.extend([f"{harness}_thinkingBudget", f"{harness}_thinkingConfig", "thinkingBudget", "thinkingConfig"])
    for key in candidates:
        if key not in fields:
            continue
        value = fields.get(key)
        if field_name == "thinkingLevel" and isinstance(value, dict):
            budget = str(value.get("thinkingBudget") or "").strip()
            return REASONING_BUDGET_LEVELS.get(budget, "")
        return str(value or "").strip()
    return ""


def reasoning_option_label(field_name: str, value: str) -> str:
    for option_value, label in REASONING_OPTIONS.get(field_name, []):
        if option_value == value:
            return label
    return value.title() if value else "Medium"


def default_reasoning_value(harness: str, field_name: str, defaults: dict[str, Any], tier: str = "default") -> str:
    harness_defaults = defaults.get(harness, {}) if isinstance(defaults, dict) else {}
    if tier not in {value for value, _ in DEFAULT_MODEL_TIERS}:
        tier = "default"
    tier_config = harness_defaults.get(tier, {}) if isinstance(harness_defaults, dict) else {}
    value = ""
    if isinstance(tier_config, dict):
        value = str(tier_config.get(field_name) or "").strip()
        if not value and field_name == "thinkingLevel":
            budget = str(tier_config.get("thinkingBudget") or "").strip()
            value = REASONING_BUDGET_LEVELS.get(budget, "")
    return value or REASONING_MIDDLE_VALUES.get(field_name, "medium")


def render_reasoning_select(harness: str, field_name: str, fields: dict[str, Any], defaults: dict[str, Any], model_tier: str = "default", label: str = "Reasoning") -> str:
    key = f"{harness}_{field_name}"
    current = reasoning_field_value(fields, harness, field_name)
    default_value = default_reasoning_value(harness, field_name, defaults, model_tier)
    default_label = f"Default ({reasoning_option_label(field_name, default_value)})"
    options = []
    inserted_default = False
    for value, option_label in REASONING_OPTIONS.get(field_name, [("", "Default")]):
        if value == "":
            continue
        if value == default_value:
            options.append(("", default_label))
            inserted_default = True
            continue
        options.append((value, option_label))
    if not inserted_default:
        options.insert(0, ("", default_label))
    rows = []
    known_values = {value for value, _ in options}
    if current and current not in known_values:
        rows.append(f'<option value="{escape(current)}" selected>{escape(current)}</option>')
    for value, option_label in options:
        selected = " selected" if value == current else ""
        rows.append(f'<option value="{escape(value)}"{selected}>{escape(option_label)}</option>')
    return f"""<label>
  <span>{escape(label)}</span>
  <select name="field_{escape(key)}">
    {"".join(rows)}
  </select>
</label>"""


def render_disabled_reasoning_select(label: str = "Reasoning") -> str:
    return f"""<label>
  <span>{escape(label)}</span>
  <select disabled>
    <option>Not supported</option>
  </select>
</label>"""


def render_agent_reasoning_inputs(fields: dict[str, Any]) -> str:
    defaults = load_defaults(DEFAULTS_FILE) if DEFAULTS_FILE.exists() else {}
    controls = []
    for harness in ALL_HARNESSES:
        field_name = harness_reasoning_field(harness)
        if not field_name:
            continue
        controls.append(render_reasoning_select(harness, field_name, fields, defaults, str(fields.get(f"{harness}_model") or "default")))
    if not controls:
        return ""
    return f"""<fieldset class="agent-reasoning-fields wide">
  <legend>Reasoning</legend>
  <div class="agent-reasoning-grid">{"".join(controls)}</div>
</fieldset>"""


def field_list_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError:
        loaded = None
    if isinstance(loaded, list):
        return [str(item).strip() for item in loaded if str(item).strip()]
    return [part.strip() for part in re.split(r"[\n,]+", text) if part.strip()]


def scope_installed_names(content_type: str, scope: str) -> tuple[set[str], set[str]]:
    global_items = set(load_installed_type(content_type)) if content_type in CONTENT_TYPES else set()
    project_items: set[str] = set()
    project = selected_project(scope)
    if project["kind"] == "project":
        for path in project_installed_paths(project["root"], content_type):
            project_items.update(parse_installed_conf(path))
    return global_items, project_items


def capability_base_source_label(content_type: str, name: str, scope: str) -> str:
    global_items, project_items = scope_installed_names(content_type, scope)
    project = selected_project(scope)
    if project["kind"] == "project" and name in project_items:
        return "Project"
    if name in global_items:
        return "Global"
    return "Available"


def capability_field_value(fields: dict[str, Any], harness: str, field_name: str) -> list[str]:
    candidates = [f"{harness}_{field_name}"]
    if field_name == "mcp-servers":
        candidates.extend([f"{harness}_mcp_servers", "mcp-servers", "mcp_servers"])
    elif field_name == "mcp_servers":
        candidates.extend([f"{harness}_mcp-servers", "mcp_servers", "mcp-servers"])
    else:
        candidates.append(field_name)
    for key in candidates:
        if key in fields:
            return field_list_value(fields.get(key))
    return []


def unified_capability_value(fields: dict[str, Any], capability: str) -> list[str]:
    values = []
    for harness, field_name in supported_agent_capability_fields(capability):
        values.extend(capability_field_value(fields, harness, field_name))
    base_key = "skills" if capability == "skills" else "mcp_servers"
    if base_key in fields:
        values.extend(field_list_value(fields.get(base_key)))
    if capability == "mcp" and "mcp-servers" in fields:
        values.extend(field_list_value(fields.get("mcp-servers")))
    return list(dict.fromkeys(value for value in values if value))


def render_unified_capability_selector(capability: str, fields: dict[str, Any], scope: str) -> str:
    content_type = "skills" if capability == "skills" else "mcp"
    label = "Skills" if capability == "skills" else "MCP servers"
    input_name = "agent_skills" if capability == "skills" else "agent_mcp_servers"
    selected = set(unified_capability_value(fields, capability))
    names = list(dict.fromkeys(list_names(content_type) + sorted(selected)))
    supported = supported_agent_capability_fields(capability)
    supported_labels = []
    for harness, _ in supported:
        definition = HARNESS_DEFINITIONS.get(harness, {})
        supported_labels.append(str(definition.get("label") or harness))
    rows = []
    for name in names:
        summary = item_summary(content_type, name)
        description = str(summary.get("description") or "").strip()
        checked = " checked" if name in selected else ""
        base_source = capability_base_source_label(content_type, name, scope)
        source = "Override" if name in selected else base_source
        rows.append(
            f"""<label class="capability-option">
  <input type="checkbox" name="field_{escape(input_name)}" value="{escape(name)}"{checked}>
  <span class="capability-option-text">
    <strong>{escape(name)}</strong>
    <small>{escape(description)}</small>
  </span>
  <span class="capability-source" data-default-label="{escape(base_source)}">{escape(source)}</span>
</label>"""
        )
    if not rows:
        rows.append('<div class="capability-empty">No source items found.</div>')
    harness_text = ", ".join(supported_labels) if supported_labels else "No harnesses"
    hidden_clear = f'<input type="hidden" name="field_{escape(input_name)}" value="">' if selected else ""
    return f"""<section class="capability-group">
  {hidden_clear}
  <div class="capability-group-head">
    <h4>{escape(label)}</h4>
    <span>{len(selected)} selected</span>
  </div>
  <p class="capability-support">Applies to {escape(harness_text)}</p>
  <div class="capability-list">{"".join(rows)}</div>
</section>"""


def render_agent_capability_inputs(fields: dict[str, Any], scope: str) -> str:
    controls = []
    for capability in ("skills", "mcp"):
        if supported_agent_capability_fields(capability):
            controls.append(render_unified_capability_selector(capability, fields, scope))
    if not controls:
        return ""
    return f"""<fieldset class="agent-capability-fields wide">
  <legend>Skills and MCP</legend>
  <div class="agent-capability-grid">{"".join(controls)}</div>
</fieldset>"""


def render_field_inputs(
    content_type: str,
    fields: dict[str, Any],
    scope: str,
    include_name: bool = True,
    sectioned_fields: dict[str, dict[str, Any]] | None = None,
) -> str:
    display_keys = schema_field_order(content_type)
    controls = []
    sectioned_fields = sectioned_fields or {}
    sectioned_keys = [key for key in sectioned_fields if key in display_keys or key in fields]
    if sectioned_keys:
        controls.append(f'<input type="hidden" name="sectioned_field_keys" value="{escape(",".join(sectioned_keys))}">')
    harness_model_keys = {"model"} | {f"{harness}_model" for harness in ALL_HARNESSES}
    reasoning_keys = {"reasoning"} | set(REASONING_OPTIONS) | {"thinkingBudget", "thinkingConfig"}
    for harness in ALL_HARNESSES:
        for field_name in set(REASONING_OPTIONS) | {"thinkingBudget", "thinkingConfig"}:
            reasoning_keys.add(f"{harness}_{field_name}")
    capability_keys = set(AGENT_CAPABILITY_FIELDS) | {"agent_skills", "agent_mcp_servers"}
    sandbox_keys = {"sandbox", "sandbox_mode"}
    for harness in ALL_HARNESSES:
        for field_name in AGENT_CAPABILITY_FIELDS:
            capability_keys.add(f"{harness}_{field_name}")
            if field_name == "mcp-servers":
                capability_keys.add(f"{harness}_mcp_servers")
            if field_name == "mcp_servers":
                capability_keys.add(f"{harness}_mcp-servers")
        sandbox_keys.update({f"{harness}_sandbox", f"{harness}_sandbox_mode"})
    reserved_keys = reserved_form_field_keys(content_type)
    if content_type == "agents":
        controls.append(render_agent_model_inputs(fields))
        capability_section = render_agent_capability_inputs(fields, scope)
        if capability_section:
            controls.append(capability_section)
    for key in display_keys:
        if key == "name" and not include_name:
            continue
        if content_type == "agents" and key in harness_model_keys:
            continue
        if content_type == "agents" and key in reasoning_keys:
            continue
        if content_type == "agents" and key in capability_keys:
            continue
        if content_type == "agents" and key in sandbox_keys:
            continue
        value = fields.get(key, "")
        if key not in fields and key not in display_keys and key not in {"name", "description", "model"}:
            continue
        if key in BOOLEAN_FIELD_NAMES:
            checked = bool(value) if key in fields else False
            hidden = f'<input type="hidden" name="field_{escape(key)}" value="false">' if key in fields else ""
            controls.append(
                f"""<label class="checkbox-field">
  {hidden}
  <input type="checkbox" name="field_{escape(key)}" value="true"{" checked" if checked else ""}>
  <span>{escape(humanize_field_name(key))}</span>
</label>"""
            )
            continue
        if key in LIST_FIELD_NAMES:
            controls.append(render_list_field_editor(key, value))
            continue
        if key in MAPPING_FIELD_NAMES:
            controls.append(render_mapping_field_editor(key, value))
            continue
        if key in sectioned_fields:
            definition = sectioned_fields.get(key) or {}
            preset_sections = [
                (
                    str(section.get("title") or ""),
                    str(template_level_value(section.get("level"), 2)),
                    str(section.get("content") or ""),
                )
                for section in definition.get("sections") or []
                if isinstance(section, dict) and str(section.get("title") or "").strip()
            ]
            label = str(definition.get("label") or key.replace("_", " ").replace("-", " ").title())
            controls.append(
                render_body_section_editor(
                    content_type,
                    str(value or ""),
                    starter_sections=True,
                    source_name=f"field_{key}",
                    legend=label,
                    preset_sections_override=preset_sections,
                )
            )
            continue
        if isinstance(value, (dict, list)):
            value = yaml.safe_dump(value, sort_keys=False).strip()
        if key in TEXTAREA_FIELD_NAMES or "\n" in str(value):
            rows = 3 if key == "description" else 2
            controls.append(
                f"""<label class="wide">
  <span>{escape(humanize_field_name(key))}</span>
  <textarea name="field_{escape(key)}" rows="{rows}">{escape(value)}</textarea>
</label>"""
            )
            continue
        controls.append(
            f"""<label>
  <span>{escape(humanize_field_name(key))}</span>
  <input name="field_{escape(key)}" value="{escape(value)}">
</label>"""
        )
    extras = {key: value for key, value in fields.items() if key not in reserved_keys}
    extra_text = yaml.safe_dump(extras, sort_keys=False).strip() if extras else ""
    controls.append(render_extra_fields_editor(extra_text, reserved_keys))
    return "\n".join(controls)


def render_template_field_preset_editor(content_type: str, fields: dict[str, Any], scope: str) -> str:
    original_fields = yaml.safe_dump(fields, sort_keys=False).strip() if fields else ""
    return f"""<fieldset class="template-field-preset-editor wide" data-template-field-preset-editor data-template-field-type="{escape(content_type)}">
  <legend>Field presets</legend>
  <input type="hidden" name="template_fields_mode" value="structured">
  <input type="hidden" name="template_fields_current_type" value="{escape(content_type)}">
  <textarea name="original_fields" hidden>{escape_textarea(original_fields)}</textarea>
  <div class="template-field-preset-note">These values are applied to new or edited items when this template is selected.</div>
  <div class="fields">{render_field_inputs(content_type, fields, scope, include_name=False)}</div>
</fieldset>"""


def render_extra_fields_editor(extra_text: str, reserved_keys: set[str] | None = None) -> str:
    rows = []
    try:
        loaded = yaml.safe_load(extra_text) if extra_text.strip() else {}
    except yaml.YAMLError:
        loaded = {}
    if isinstance(loaded, dict):
        for key, value in loaded.items():
            text_value = form_editor_display_value(value)
            mode = form_editor_value_mode(value)
            rows.append(render_extra_field_row(str(key), text_value, str(key), text_value, form_editor_yaml_value(value), mode))
    if not rows:
        rows.append(render_extra_field_row("", ""))
    reserved_attr = escape(json.dumps(sorted(reserved_keys or set())))
    return f"""<fieldset class="extra-fields-editor wide" data-extra-fields-editor>
  <legend>Additional fields</legend>
  <textarea name="extra_fields" hidden data-extra-fields-source data-reserved-keys="{reserved_attr}">{escape(extra_text)}</textarea>
  <div class="extra-fields-list" data-extra-fields-list>{"".join(rows)}</div>
  <div class="extra-fields-actions">
    <button type="button" class="secondary" data-add-extra-field>Add field</button>
  </div>
</fieldset>"""


def strip_yaml_document_end(value: str) -> str:
    return re.sub(r"\n\.\.\.\s*$", "", value.strip())


def form_editor_display_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return strip_yaml_document_end(yaml.safe_dump(value, sort_keys=False, default_flow_style=True))


def form_editor_value_mode(value: Any) -> str:
    return "string" if isinstance(value, str) else "yaml"


def form_editor_yaml_value(value: Any) -> str:
    if isinstance(value, str):
        if "\n" in value:
            return "|\n" + "\n".join(f"  {line}" for line in value.split("\n"))
        return json.dumps(value)
    return strip_yaml_document_end(yaml.safe_dump(value, sort_keys=False, default_flow_style=True))


def render_value_mode_select(mode: str) -> str:
    normalized = mode if mode in {"string", "yaml"} else "string"
    string_selected = " selected" if normalized == "string" else ""
    yaml_selected = " selected" if normalized == "yaml" else ""
    return f"""<select data-value-mode>
  <option value="string"{string_selected}>String</option>
  <option value="yaml"{yaml_selected}>YAML</option>
</select>"""


def render_extra_field_row(
    key: str,
    value: str,
    original_key: str = "",
    original_value: str = "",
    original_yaml: str = "",
    mode: str = "string",
) -> str:
    normalized_mode = mode if mode in {"string", "yaml"} else "string"
    return f"""<div class="extra-field-row" data-extra-field-row data-original-key="{escape(original_key)}" data-original-value="{escape(original_value)}" data-original-yaml="{escape(original_yaml)}" data-original-mode="{escape(normalized_mode)}">
  <label>
    <span>Key</span>
    <input data-extra-field-key value="{escape(key)}" placeholder="field_name">
  </label>
  <label>
    <span>Type</span>
    {render_value_mode_select(normalized_mode)}
  </label>
  <label>
    <span>Value</span>
    <textarea data-extra-field-value rows="2" placeholder="value">{escape(value)}</textarea>
  </label>
  <button type="button" class="secondary extra-field-remove" data-remove-extra-field>Remove</button>
</div>"""


def render_list_field_editor(key: str, value: Any) -> str:
    values = field_list_value(value)
    rows = [render_list_field_row(item) for item in values] or [render_list_field_row("")]
    hidden_value = yaml.safe_dump(values, sort_keys=False).strip() if values else ""
    return f"""<fieldset class="list-field-editor wide" data-list-field-editor>
  <legend>{escape(humanize_field_name(key))}</legend>
  <textarea name="field_{escape(key)}" hidden data-list-field-source>{escape(hidden_value)}</textarea>
  <div class="list-field-list" data-list-field-list>{"".join(rows)}</div>
  <div class="list-field-actions">
    <button type="button" class="secondary" data-add-list-field-item>Add item</button>
  </div>
</fieldset>"""


def render_list_field_row(value: str) -> str:
    return f"""<div class="list-field-row" data-list-field-row>
  <label>
    <span>Value</span>
    <input data-list-field-value value="{escape(value)}">
  </label>
  <button type="button" class="secondary list-field-remove" data-remove-list-field-item>Remove</button>
</div>"""


def render_mapping_field_editor(key: str, value: Any) -> str:
    rows = []
    mapping: dict[str, Any] = {}
    if isinstance(value, dict):
        mapping = value
    elif isinstance(value, str) and value.strip():
        try:
            loaded = yaml.safe_load(value)
            if isinstance(loaded, dict):
                mapping = loaded
        except yaml.YAMLError:
            mapping = {}
    for map_key, map_value in mapping.items():
        text_value = form_editor_display_value(map_value)
        mode = form_editor_value_mode(map_value)
        rows.append(render_mapping_field_row(str(map_key), text_value, str(map_key), text_value, form_editor_yaml_value(map_value), mode))
    if not rows:
        rows.append(render_mapping_field_row("", ""))
    hidden_value = yaml.safe_dump(mapping, sort_keys=False).strip() if mapping else ""
    return f"""<fieldset class="mapping-field-editor wide" data-mapping-field-editor>
  <legend>{escape(humanize_field_name(key))}</legend>
  <textarea name="field_{escape(key)}" hidden data-mapping-field-source>{escape(hidden_value)}</textarea>
  <div class="mapping-field-list" data-mapping-field-list>{"".join(rows)}</div>
  <div class="mapping-field-actions">
    <button type="button" class="secondary" data-add-mapping-field-item>Add entry</button>
  </div>
</fieldset>"""


def render_mapping_field_row(
    key: str,
    value: str,
    original_key: str = "",
    original_value: str = "",
    original_yaml: str = "",
    mode: str = "string",
) -> str:
    normalized_mode = mode if mode in {"string", "yaml"} else "string"
    return f"""<div class="mapping-field-row" data-mapping-field-row data-original-key="{escape(original_key)}" data-original-value="{escape(original_value)}" data-original-yaml="{escape(original_yaml)}" data-original-mode="{escape(normalized_mode)}">
  <label>
    <span>Key</span>
    <input data-mapping-field-key value="{escape(key)}" placeholder="KEY">
  </label>
  <label>
    <span>Type</span>
    {render_value_mode_select(normalized_mode)}
  </label>
  <label>
    <span>Value</span>
    <textarea data-mapping-field-value rows="2" placeholder="value">{escape(value)}</textarea>
  </label>
  <button type="button" class="secondary mapping-field-remove" data-remove-mapping-field-item>Remove</button>
</div>"""


def render_editor_header(content_type: str, name: str, path: Path, scope: str, active_view: str, installed: bool) -> str:
    current_name = name or ""
    form_href = (
        f"/?type={urllib.parse.quote(content_type)}"
        f"&name={urllib.parse.quote(current_name)}"
        f"&scope={urllib.parse.quote(scope)}"
        "&view=form"
    )
    file_href = (
        f"/?type={urllib.parse.quote(content_type)}"
        f"&name={urllib.parse.quote(current_name)}"
        f"&scope={urllib.parse.quote(scope)}"
        "&view=file"
    )
    form_active = " active" if active_view == "form" else ""
    file_active = " active" if active_view == "file" else ""
    toggle = f"""<div class="view-toggle" aria-label="Editor view">
  <a class="{form_active}" href="{form_href}">Form</a>
  <a class="{file_active}" href="{file_href}">File</a>
</div>"""
    return f"""<div class="editor-head">
    <div>
      <h2>{escape(current_name or "New " + content_type[:-1])}</h2>
    </div>
    <div class="actions">{toggle}</div>
  </div>"""


def render_markdown_editor(
    content_type: str,
    name: str,
    fields: dict[str, Any],
    body: str,
    raw: str,
    path: Path,
    installed: bool,
    scope: str,
    starter_sections: bool = False,
) -> str:
    current_name = name or str(fields.get("name") or "")
    original_fields = yaml.safe_dump(fields, sort_keys=False).strip() if fields else ""
    default_template = default_template_for_type(content_type) if starter_sections and not body else None
    template_name = str(default_template.get("name") or "") if default_template else ""
    section_template = default_template or default_template_for_type(content_type)
    sectioned_fields = template_field_sections_for_editor(section_template)
    if content_type == "agents":
        sectioned_fields.pop("developer_instructions", None)
    return f"""<section class="editor">
  <span data-editor-type="{escape(content_type)}"></span>
  {render_editor_header(content_type, current_name, path, scope, "form", installed)}
  <form class="edit-form" action="/save" method="post">
    <input type="hidden" name="type" value="{content_type}">
    <input type="hidden" name="original_name" value="{escape(current_name)}">
    <input type="hidden" name="original_suffix" value="{escape(path.suffix)}">
    <input type="hidden" name="scope" value="{escape(scope)}" data-scope-hidden>
    <input type="hidden" name="editor_view" value="form">
    <textarea name="original_fields" hidden>{escape(original_fields)}</textarea>
	    <label>
	      <span>file name</span>
	      <input name="name" value="{escape(current_name)}" required data-name-input>
	    </label>
	    {render_body_template_controls(content_type, template_name)}
	    <div class="fields">{render_field_inputs(content_type, fields, scope, sectioned_fields=sectioned_fields)}</div>
	    {render_body_section_editor(content_type, body, starter_sections, template_name)}
		</form>
	</section>"""


def render_mapping_editor(
    content_type: str,
    name: str,
    fields: dict[str, Any],
    raw: str,
    path: Path,
    installed: bool,
    scope: str,
) -> str:
    current_name = name or str(fields.get("name") or "")
    original_fields = yaml.safe_dump(fields, sort_keys=False).strip() if fields else ""
    label = path.suffix.upper().lstrip(".") or "mapping"
    return f"""<section class="editor">
  <span data-editor-type="{escape(content_type)}"></span>
  {render_editor_header(content_type, current_name, path, scope, "form", installed)}
  <form class="edit-form" action="/save" method="post">
    <input type="hidden" name="type" value="{content_type}">
    <input type="hidden" name="original_name" value="{escape(current_name)}">
    <input type="hidden" name="original_suffix" value="{escape(path.suffix)}">
    <input type="hidden" name="scope" value="{escape(scope)}" data-scope-hidden>
    <input type="hidden" name="editor_view" value="form">
    <textarea name="original_fields" hidden>{escape_textarea(original_fields)}</textarea>
	    <label>
	      <span>file name</span>
	      <input name="name" value="{escape(current_name)}" required data-name-input>
	    </label>
	    {render_body_template_controls(content_type, "", include_save=True) if content_type in TEMPLATE_TARGET_TYPES else ""}
	    <div class="mapping-editor-note wide">Editing {escape(label)} as structured fields. Use File view for exact raw formatting.</div>
	    <div class="fields">{render_field_inputs(content_type, fields, scope)}</div>
	  </form>
</section>"""


def template_type_options(selected: str) -> str:
    return "".join(
        f'<option value="{escape(content_type)}"{" selected" if content_type == selected else ""}>{escape(TEMPLATE_TYPE_LABELS.get(content_type, content_type.title()))}</option>'
        for content_type in sorted(TEMPLATE_TARGET_TYPES, key=lambda item: TEMPLATE_TYPE_LABELS.get(item, item))
    )


def heading_level_options(selected: Any) -> str:
    selected_text = str(template_level_value(selected, 2))
    return "".join(
        f'<option value="{value}"{" selected" if selected_text == value else ""}>{label}</option>'
        for value, label in [
            ("0", "None"),
            ("1", "H1"),
            ("2", "H2"),
            ("3", "H3"),
            ("4", "H4"),
            ("5", "H5"),
            ("6", "H6"),
        ]
    )


def render_template_section_rows(sections: list[dict[str, Any]]) -> str:
    rows = []
    if not sections:
        sections = [{"title": "Overview", "level": 2, "content": ""}]
    for section in sections:
        title = str(section.get("title") or "")
        level = section.get("level", 2)
        content = str(section.get("content") or "")
        rows.append(
            f"""<article class="template-section-row" data-template-section-row>
  <div class="template-section-head">
    <label>
      <span>Section</span>
      <input data-template-section-title value="{escape(title)}" placeholder="Section title">
    </label>
    <label>
      <span>Heading</span>
      <select data-template-section-level>{heading_level_options(level)}</select>
    </label>
    <button type="button" class="secondary template-section-move" data-move-template-section="up">Up</button>
    <button type="button" class="secondary template-section-move" data-move-template-section="down">Down</button>
    <button type="button" class="secondary template-section-remove" data-remove-template-section>Remove</button>
  </div>
  <label class="wide">
    <span>Starter content</span>
    <textarea data-template-section-content rows="4" placeholder="Optional default text for this section">{escape_textarea(content)}</textarea>
  </label>
</article>"""
        )
    return "".join(rows)


def render_template_field_section_rows(field_sections: dict[str, dict[str, Any]]) -> str:
    rows = []
    for key, definition in field_sections.items():
        label = str(definition.get("label") or key.replace("_", " ").replace("-", " ").title())
        sections = [section for section in definition.get("sections") or [] if isinstance(section, dict)]
        if not sections:
            sections = [{"title": "Overview", "level": 2, "content": ""}]
        section_rows = []
        for section in sections:
            title = str(section.get("title") or "")
            level = section.get("level", 2)
            content = str(section.get("content") or "")
            section_rows.append(
                f"""<article class="template-section-row" data-template-field-section-row>
  <div class="template-section-head">
    <label>
      <span>Section</span>
      <input data-template-field-section-title value="{escape(title)}" placeholder="Section title">
    </label>
    <label>
      <span>Heading</span>
      <select data-template-field-section-level>{heading_level_options(level)}</select>
    </label>
    <button type="button" class="secondary template-section-move" data-move-template-field-section="up">Up</button>
    <button type="button" class="secondary template-section-move" data-move-template-field-section="down">Down</button>
    <button type="button" class="secondary template-section-remove" data-remove-template-field-section>Remove</button>
  </div>
  <label class="wide">
    <span>Starter content</span>
    <textarea data-template-field-section-content rows="4" placeholder="Optional default text for this field section">{escape_textarea(content)}</textarea>
  </label>
</article>"""
            )
        rows.append(
            f"""<article class="template-field-section-row" data-template-field-section-group>
  <div class="template-field-section-head">
    <label>
      <span>Field key</span>
      <input data-template-field-section-key value="{escape(key)}" placeholder="field_key">
    </label>
    <label>
      <span>Label</span>
      <input data-template-field-section-label value="{escape(label)}" placeholder="Section label">
    </label>
    <button type="button" class="secondary" data-add-template-field-section>Add section</button>
    <button type="button" class="secondary template-section-remove" data-remove-template-field-section-group>Remove field</button>
  </div>
  <div class="template-field-section-list" data-template-field-section-list>{"".join(section_rows)}</div>
</article>"""
        )
    return "".join(rows)


def render_template_editor(
    name: str,
    definition: dict[str, Any],
    raw: str,
    path: Path,
    scope: str,
    installed: bool,
) -> str:
    current_name = name or str(definition.get("name") or "")
    target_type = str(definition.get("type") or "agents")
    description = str(definition.get("description") or "")
    sections = [section for section in definition.get("sections") or [] if isinstance(section, dict)]
    if not sections and not current_name:
        default_template = default_template_for_type(target_type)
        sections = [
            {"title": title, "level": level, "content": content}
            for title, level, content in template_sections_for_editor(default_template)
        ]
    sections_json = json.dumps(sections)
    field_sections = template_field_sections_for_editor(definition)
    if not field_sections and not current_name:
        field_sections = template_field_sections_for_editor(default_template_for_type(target_type))
    field_sections_json = json.dumps(field_sections)
    fields = template_fields_for_editor(definition)
    default_sections_by_type = {
        content_type: template_sections_for_editor(default_template_for_type(content_type))
        for content_type in sorted(TEMPLATE_TARGET_TYPES)
    }
    default_field_sections_by_type = {
        content_type: template_field_sections_for_editor(default_template_for_type(content_type))
        for content_type in sorted(TEMPLATE_TARGET_TYPES)
    }
    return f"""<section class="editor">
  <span data-editor-type="templates"></span>
  {render_editor_header("templates", current_name, path, scope, "form", installed)}
  <form class="edit-form" action="/save" method="post">
    <input type="hidden" name="type" value="templates">
    <input type="hidden" name="original_name" value="{escape(current_name)}">
    <input type="hidden" name="original_suffix" value="{escape(path.suffix)}">
    <input type="hidden" name="scope" value="{escape(scope)}" data-scope-hidden>
    <input type="hidden" name="editor_view" value="form">
    <textarea name="template_sections" hidden data-template-sections-source>{escape_textarea(sections_json)}</textarea>
    <textarea name="template_field_sections" hidden data-template-field-sections-source>{escape_textarea(field_sections_json)}</textarea>
    <label>
      <span>file name</span>
      <input name="name" value="{escape(current_name)}" required data-name-input>
    </label>
    <label>
      <span>Template type</span>
      <select name="template_type" data-template-type-select>{template_type_options(target_type)}</select>
    </label>
    <label class="wide">
      <span>Description</span>
      <textarea name="template_description" rows="3">{escape_textarea(description)}</textarea>
    </label>
    {render_template_field_preset_editor(target_type, fields, scope)}
    <fieldset class="template-field-section-editor wide" data-template-field-section-editor data-template-default-field-sections="{escape(json.dumps(default_field_sections_by_type))}">
      <legend>Sectioned fields</legend>
      <div class="template-field-section-note">Split large frontmatter fields into smaller editable sections while saving them back to a single field.</div>
      <div class="template-field-section-group-list" data-template-field-section-group-list>{render_template_field_section_rows(field_sections)}</div>
      <div class="template-section-actions">
        <button type="button" class="secondary" data-add-template-field-section-group>Add sectioned field</button>
        <button type="button" class="secondary" data-reset-template-field-sections>Use type defaults</button>
      </div>
    </fieldset>
    <fieldset class="template-section-editor wide" data-template-section-editor data-template-default-sections="{escape(json.dumps(default_sections_by_type))}">
      <legend>Sections</legend>
      <div class="template-section-list" data-template-section-list>{render_template_section_rows(sections)}</div>
      <div class="template-section-actions">
        <button type="button" class="secondary" data-add-template-section>Add section</button>
        <button type="button" class="secondary" data-reset-template-sections>Use type defaults</button>
      </div>
    </fieldset>
  </form>
</section>"""


def split_body_sections(body: str) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    current_title = "Overview"
    current_lines: list[str] = []
    current_level = 0
    current_heading_suffix = ""
    found_heading = False
    fence_marker = ""
    fence_length = 0
    for line in body.splitlines(keepends=True):
        line_text = line.rstrip("\r\n")
        fence = re.match(r"^\s*(`{3,}|~{3,})", line_text)
        if fence:
            marker_text = fence.group(1)
            marker = marker_text[0]
            length = len(marker_text)
            if not fence_marker:
                fence_marker = marker
                fence_length = length
            elif marker == fence_marker and length >= fence_length:
                fence_marker = ""
                fence_length = 0
            current_lines.append(line)
            continue
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line_text)
        if match and not fence_marker:
            if current_lines or found_heading:
                sections.append(
                    {
                        "title": current_title,
                        "level": str(current_level),
                        "content": "".join(current_lines),
                        "heading_suffix": current_heading_suffix,
                    }
                )
            current_level = len(match.group(1))
            current_title = match.group(2).strip()
            suffix_match = re.search(r"\r?\n$", line)
            current_heading_suffix = suffix_match.group(0) if suffix_match else ""
            current_lines = []
            found_heading = True
        else:
            current_lines.append(line)
    if current_lines or found_heading or body:
        sections.append(
            {
                "title": current_title,
                "level": str(current_level),
                "content": "".join(current_lines),
                "heading_suffix": current_heading_suffix,
            }
        )
    if not sections:
        sections.append({"title": "Overview", "level": "0", "content": "", "heading_suffix": ""})
    return sections


def body_section_presets(content_type: str) -> list[tuple[str, str]]:
    template = default_template_for_type(content_type)
    sections = template_sections_for_editor(template)
    return sections or [("Notes", "2"), ("Examples", "2")]


def body_starter_sections(content_type: str) -> list[tuple[str, str]]:
    presets = body_section_presets(content_type)
    limit = 4 if content_type in {"agents", "skills"} else len(presets)
    return presets[:limit]


def body_section_placeholder(title: str) -> str:
    placeholders = {
        "Communication Protocol": "Define how the agent should communicate, ask clarifying questions, and handle ambiguity.",
        "Core Mission": "Describe the agent purpose, primary outcomes, and what success looks like.",
        "Responsibilities": "List the concrete tasks this agent owns and the boundaries it should respect.",
        "Execution Flow": "Describe the step-by-step workflow the agent should follow.",
        "Output Format": "Specify required response structure, artifacts, formats, or acceptance criteria.",
        "Failure Handling": "Explain what the agent should do when inputs are missing, tools fail, or confidence is low.",
        "Success Metrics": "Describe how to judge whether this agent performed well.",
        "When To Use": "Describe the situations where this skill should be selected.",
        "Workflow": "Write the ordered process the skill should follow.",
        "Examples": "Add representative examples or prompts that clarify expected usage.",
        "Best Practices": "List constraints, quality bars, and patterns the skill should apply.",
        "Output Rules": "Describe required output shape, tone, and formatting.",
        "Troubleshooting": "Add common failure modes and how to recover.",
        "Usage Notes": "Explain when and how this MCP server should be used.",
        "Configuration": "Describe required configuration, commands, URLs, or setup.",
        "Environment": "List environment variables and operational requirements.",
        "Requirements": "Define required behavior and constraints.",
        "Exceptions": "Describe cases where the rule should not apply.",
        "Steps": "List the workflow steps in execution order.",
        "Guidelines": "Add decision rules and quality checks for this workflow.",
        "Output": "Describe the final output, files, or status the workflow should produce.",
    }
    return placeholders.get(title.strip(), "Write this section content.")


def render_body_template_controls(content_type: str, selected_template_name: str = "", include_save: bool = True) -> str:
    available_templates = content_templates_for_type(content_type)
    template_field_definitions = {
        str(template.get("name")): template_fields_for_editor(template)
        for template in available_templates
        if template.get("name")
    }
    template_field_section_definitions = {
        str(template.get("name")): template_field_sections_for_editor(template)
        for template in available_templates
        if template.get("name")
    }
    template_options = ['<option value=""' + (" selected" if not selected_template_name else "") + ">Custom</option>"]
    template_options.extend(
        f'<option value="{escape(str(template.get("name") or ""))}"{" selected" if str(template.get("name") or "") == selected_template_name else ""}>{escape(str(template.get("name") or ""))}</option>'
        for template in available_templates
    )
    fields_attr = f" data-template-field-definitions=\"{escape(json.dumps(template_field_definitions))}\""
    field_sections_attr = f" data-template-field-section-definitions=\"{escape(json.dumps(template_field_section_definitions))}\""
    save_button = '<button type="button" class="secondary" data-save-body-template>Save as template</button>' if include_save else ""
    return f"""<div class="body-template-row wide" data-item-template-controls data-template-content-type="{escape(content_type)}"{fields_attr}{field_sections_attr}>
  <label>
    <span>Template</span>
    <select name="body_template" data-body-template-select>
      {"".join(template_options)}
    </select>
  </label>
  <button type="button" class="secondary" data-apply-body-template>Apply template</button>
  {save_button}
</div>"""


def render_body_section_editor(
    content_type: str,
    body: str,
    starter_sections: bool = False,
    selected_template_name: str = "",
    source_name: str = "body",
    legend: str = "Body",
    preset_sections_override: list[tuple[str, str, str]] | None = None,
) -> str:
    section_rows = []
    available_templates = content_templates_for_type(content_type)
    selected_template = next((template for template in available_templates if str(template.get("name") or "") == selected_template_name), None)
    if selected_template is None and starter_sections and not body:
        selected_template = default_template_for_type(content_type)
        selected_template_name = str(selected_template.get("name") if selected_template else "")
    preset_sections = preset_sections_override or template_sections_for_editor(selected_template) or body_section_presets(content_type)
    if preset_sections_override is None:
        template_definitions = {
            str(template.get("name")): template_sections_for_editor(template)
            for template in available_templates
            if template.get("name")
        }
        template_field_definitions = {
            str(template.get("name")): template_fields_for_editor(template)
            for template in available_templates
            if template.get("name")
        }
        template_field_section_definitions = {
            str(template.get("name")): template_field_sections_for_editor(template)
            for template in available_templates
            if template.get("name")
        }
    else:
        template_definitions = {}
        template_field_definitions = {}
        template_field_section_definitions = {}
    starter_data = preset_sections if starter_sections and not body and preset_sections_override is not None else body_starter_sections(content_type) if starter_sections and not body else []
    sections = (
        [
            {
                "title": title,
                "level": level,
                "content": content if len(section) > 2 else "",
                "heading_suffix": "\n\n",
                "empty_starter": True,
            }
            for section in starter_data
            for title, level, *content_parts in [section]
            for content in ["".join(str(part) for part in content_parts)]
        ]
        if starter_data
        else split_body_sections(body)
    )
    for section in sections:
        level = section.get("level", "0")
        title = section.get("title", "Overview")
        content = section.get("content", "")
        heading_suffix = section.get("heading_suffix", "")
        placeholder = body_section_placeholder(title)
        empty_starter = ' data-empty-starter="true"' if section.get("empty_starter") else ""
        starter_meta = (
            f' data-starter-title="{escape(title)}" data-starter-level="{escape(level)}"'
            if section.get("empty_starter")
            else ""
        )
        level_options = "".join(
            f'<option value="{option}"{" selected" if level == option else ""}>{label}</option>'
            for option, label in [
                ("0", "None"),
                ("1", "H1"),
                ("2", "H2"),
                ("3", "H3"),
                ("4", "H4"),
                ("5", "H5"),
                ("6", "H6"),
            ]
        )
        section_rows.append(
            f"""<article class="body-section" data-body-section data-heading-suffix="{escape(heading_suffix)}"{empty_starter}{starter_meta}>
  <div class="body-section-head">
    <label>
      <span>Section</span>
      <input data-body-section-title value="{escape(title)}">
    </label>
    <label>
      <span>Heading</span>
      <select data-body-section-level>
        {level_options}
      </select>
    </label>
    <button type="button" class="secondary body-section-move" data-move-body-section="up">Up</button>
    <button type="button" class="secondary body-section-move" data-move-body-section="down">Down</button>
    <button type="button" class="secondary body-section-preview-toggle" data-toggle-body-preview aria-pressed="false">Preview</button>
    <button type="button" class="secondary body-section-collapse" data-toggle-body-section aria-expanded="true">Collapse</button>
    <button type="button" class="secondary body-section-remove" data-remove-body-section>Remove</button>
  </div>
  <label class="wide" data-body-section-content-wrap>
    <span class="body-section-content-label"><span>Content</span><small data-body-section-meta></small></span>
    <textarea data-body-section-content rows="7" placeholder="{escape(placeholder)}">{escape_textarea(content)}</textarea>
  </label>
  <div class="body-section-preview" data-body-section-preview hidden></div>
</article>"""
        )
    preset_options = "".join(
        f'<option value="{escape(title)}" data-level="{escape(level)}" data-content="{escape(content if len(section) > 2 else "")}">{escape(title)}</option>'
        for section in preset_sections
        for title, level, *content_parts in [section]
        for content in ["".join(str(part) for part in content_parts)]
    )
    starter_attr = (
        f" data-starter-sections=\"{escape(json.dumps(starter_data))}\""
        if starter_data
        else ""
    )
    preset_attr = f" data-preset-sections=\"{escape(json.dumps(preset_sections))}\""
    template_attr = f" data-template-definitions=\"{escape(json.dumps(template_definitions))}\""
    template_fields_attr = f" data-template-field-definitions=\"{escape(json.dumps(template_field_definitions))}\""
    template_field_sections_attr = f" data-template-field-section-definitions=\"{escape(json.dumps(template_field_section_definitions))}\""
    return f"""<fieldset class="body-section-editor wide" data-body-section-editor data-template-content-type="{escape(content_type)}"{starter_attr}{preset_attr}{template_attr}{template_fields_attr}{template_field_sections_attr}>
  <legend>{escape(legend)}</legend>
  <textarea name="{escape(source_name)}" hidden data-body-source>{escape_textarea(body)}</textarea>
  <div class="body-section-list" data-body-section-list>{"".join(section_rows)}</div>
  <div class="body-section-actions">
    <select data-body-section-preset aria-label="Section preset">
      <option value="">Custom section</option>
      {preset_options}
    </select>
    <button type="button" class="secondary" data-add-body-section>Add section</button>
    <button type="button" class="secondary" data-add-missing-body-sections>Add missing</button>
    <button type="button" class="secondary" data-collapse-all-body-sections>Collapse all</button>
    <button type="button" class="secondary" data-expand-all-body-sections>Expand all</button>
  </div>
	</fieldset>"""


def render_hook_editor(name: str, raw: str, path: Path, scope: str, installed: bool, selected_template_name: str = "") -> str:
    current_name = name or path.name if path.name != "new" else ""
    parsed = parse_hook_script(raw)
    return f"""<section class="editor">
  <span data-editor-type="hooks"></span>
  {render_editor_header("hooks", current_name, path, scope, "form", installed)}
  <form class="edit-form" action="/save" method="post">
    <input type="hidden" name="type" value="hooks">
    <input type="hidden" name="original_name" value="{escape(current_name)}">
    <input type="hidden" name="original_suffix" value="">
    <input type="hidden" name="scope" value="{escape(scope)}" data-scope-hidden>
    <input type="hidden" name="editor_view" value="form">
	    <label>
	      <span>file name</span>
	      <input name="name" value="{escape(current_name)}" required data-name-input>
	    </label>
	    {render_body_template_controls("hooks", selected_template_name)}
	    <label>
	      <span>interpreter</span>
      <input name="hook_shebang" value="{escape(parsed['shebang'])}" placeholder="#!/usr/bin/env bash">
    </label>
    <label class="wide">
      <span>Description comments</span>
      <textarea name="hook_description" rows="3" placeholder="Describe when this hook runs and what it does.">{escape_textarea(parsed['description'])}</textarea>
    </label>
    <label class="wide">
      <span>Script body</span>
      <textarea class="file-editor hook-script-editor" name="hook_script" rows="22" spellcheck="false" placeholder="cd &quot;$(git rev-parse --show-toplevel)&quot; || exit 0&#10;wdm-ai sync">{escape_textarea(parsed['script'])}</textarea>
    </label>
  </form>
</section>"""


def pretty_json_value(value: Any) -> str:
    if not value:
        return "{}"
    return json.dumps(value, indent=2, ensure_ascii=True)


def harness_json_textarea(name: str, label: str, value: Any, rows: int = 7) -> str:
    return f"""<label class="wide harness-json-field">
  <span>{escape(label)}</span>
  <textarea name="{escape(name)}" rows="{rows}" spellcheck="false">{escape_textarea(pretty_json_value(value))}</textarea>
</label>"""


def harness_list_textarea(name: str, label: str, value: Any, rows: int = 4) -> str:
    text = "\n".join(field_list_value(value))
    return f"""<label>
  <span>{escape(label)}</span>
  <textarea name="{escape(name)}" rows="{rows}" spellcheck="false">{escape_textarea(text)}</textarea>
</label>"""


def harness_checkbox(name: str, label: str, checked: bool) -> str:
    return f"""<label class="checkbox-field">
  <input type="hidden" name="{escape(name)}" value="false">
  <input type="checkbox" name="{escape(name)}" value="true"{" checked" if checked else ""}>
  <span>{escape(label)}</span>
</label>"""


def render_harness_field_mapping_summary(field_mappings: dict[str, Any]) -> str:
    rows = []
    for content_type in HARNESS_SCHEMA_TYPES:
        mappings = field_mappings.get(content_type)
        if not isinstance(mappings, dict) or not mappings:
            continue
        for source_field, output_fields in mappings.items():
            if isinstance(output_fields, str):
                outputs = [output_fields]
            elif isinstance(output_fields, list):
                outputs = [str(item) for item in output_fields]
            else:
                outputs = [str(output_fields)]
            output_html = "".join(
                f'<code>{escape(output)}</code>'
                for output in outputs
                if str(output).strip()
            )
            rows.append(
                f"""<tr>
  <td>{escape(content_type.title())}</td>
  <td><code>{escape(source_field)}</code></td>
  <td>{output_html or '<span class="muted">None</span>'}</td>
</tr>"""
            )
    if not rows:
        return '<div class="mapping-contract-empty">No field mappings defined.</div>'
    return f"""<div class="mapping-contract-summary">
  <table>
    <thead><tr><th>Type</th><th>WDM field</th><th>Harness output</th></tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</div>"""


def render_harness_editor(
    name: str,
    definition: dict[str, Any],
    raw: str,
    path: Path,
    scope: str,
    installed: bool,
) -> str:
    current_name = name or str(definition.get("name") or "")
    label = str(definition.get("label") or "")
    detect = definition.get("detect") if isinstance(definition.get("detect"), dict) else {}
    renderers = definition.get("renderers") if isinstance(definition.get("renderers"), dict) else {}
    schemas = definition.get("schemas") if isinstance(definition.get("schemas"), dict) else {}
    field_mappings = definition.get("field_mappings") if isinstance(definition.get("field_mappings"), dict) else {}
    models = definition.get("models") if isinstance(definition.get("models"), dict) else {}
    outputs = definition.get("outputs") if isinstance(definition.get("outputs"), dict) else {}
    sync = definition.get("sync") if isinstance(definition.get("sync"), dict) else {}
    sync_paths = sync.get("paths") if isinstance(sync.get("paths"), dict) else {}
    flat_paths = {key: value for key, value in sync_paths.items() if key not in {"project", "global"}}
    project_paths = sync_paths.get("project") if isinstance(sync_paths.get("project"), dict) else {}
    global_paths = sync_paths.get("global") if isinstance(sync_paths.get("global"), dict) else {}
    sync_skip = sync.get("skip") if isinstance(sync.get("skip"), dict) else {}
    extra = {key: value for key, value in definition.items() if key not in HARNESS_FORM_HANDLED_KEYS}
    schema_fields = "".join(
        harness_list_textarea(f"harness_schema_{schema_type}", schema_type.title(), schemas.get(schema_type, []), 3)
        for schema_type in HARNESS_SCHEMA_TYPES
    )
    return f"""<section class="editor full harness-structured-editor">
  <span data-editor-type="harnesses"></span>
  {render_editor_header("harnesses", current_name, path, scope, "form", installed)}
  {render_harness_status_panel(current_name, raw, scope)}
  <form class="edit-form" action="/save" method="post">
    <input type="hidden" name="type" value="harnesses">
    <input type="hidden" name="original_name" value="{escape(current_name)}">
    <input type="hidden" name="original_suffix" value="{escape(path.suffix or '.json')}">
    <input type="hidden" name="scope" value="{escape(scope)}" data-scope-hidden>
    <input type="hidden" name="editor_view" value="form">
    <textarea name="original_raw" hidden>{escape_textarea(raw)}</textarea>
    <fieldset class="harness-form-section wide">
      <legend>Identity</legend>
      <div class="harness-form-grid">
        <label>
          <span>file name</span>
          <input name="name" value="{escape(current_name)}" required data-name-input>
        </label>
        <label>
          <span>Label</span>
          <input name="harness_label" value="{escape(label)}" placeholder="Display name">
        </label>
        {harness_checkbox("harness_builtin", "Built in", bool(definition.get("builtin")))}
        {harness_checkbox("harness_default_enabled", "Enabled by default", bool(definition.get("default_enabled")))}
        {harness_checkbox("harness_auto_enable", "Auto enable when detected", bool(definition.get("auto_enable")))}
      </div>
    </fieldset>
    <fieldset class="harness-form-section wide">
      <legend>Detection</legend>
      <div class="harness-form-grid">
        {harness_list_textarea("harness_detect_commands", "Commands", detect.get("commands", []), 4)}
        {harness_list_textarea("harness_detect_paths", "Paths", detect.get("paths", []), 4)}
      </div>
    </fieldset>
    <fieldset class="harness-form-section wide">
      <legend>Rendering</legend>
      <div class="harness-form-grid">
        <label>
          <span>Agent renderer</span>
          <input name="harness_renderer_agents" value="{escape(renderers.get("agents", ""))}" placeholder="markdown">
        </label>
        <label>
          <span>MCP renderer</span>
          <input name="harness_renderer_mcp" value="{escape(renderers.get("mcp", ""))}" placeholder="json">
        </label>
        {harness_list_textarea("harness_models_agents", "Agent models", models.get("agents", []), 5)}
      </div>
    </fieldset>
    <fieldset class="harness-form-section wide">
      <legend>Schemas</legend>
      <div class="harness-form-grid compact">{schema_fields}</div>
    </fieldset>
    <fieldset class="harness-form-section wide">
      <legend>Field mappings</legend>
      {render_harness_field_mapping_summary(field_mappings)}
      <div class="harness-form-grid">
        {harness_json_textarea("harness_field_mappings_json", "Canonical field mappings", field_mappings, 10)}
      </div>
    </fieldset>
    <fieldset class="harness-form-section wide">
      <legend>Output and sync</legend>
      <div class="harness-form-grid">
        {harness_json_textarea("harness_outputs_json", "Outputs", outputs)}
        <label>
          <span>Project root</span>
          <input name="harness_sync_project_root" value="{escape(sync.get("project_root", ""))}" placeholder=".harness">
        </label>
        <label>
          <span>Global root</span>
          <input name="harness_sync_global_root" value="{escape(sync.get("global_root", ""))}" placeholder="~/.harness">
        </label>
        {harness_json_textarea("harness_sync_flat_paths_json", "Default sync paths", flat_paths)}
        {harness_json_textarea("harness_sync_project_paths_json", "Project sync paths", project_paths)}
        {harness_json_textarea("harness_sync_global_paths_json", "Global sync paths", global_paths)}
        {harness_json_textarea("harness_sync_skip_json", "Sync skip notes", sync_skip, 5)}
      </div>
    </fieldset>
    <fieldset class="harness-form-section wide">
      <legend>Additional fields</legend>
      <div class="harness-form-grid">
        {harness_json_textarea("harness_extra_json", "Custom top-level JSON", extra, 8)}
      </div>
    </fieldset>
  </form>
</section>"""


def render_harness_status_panel(name: str, raw: str, scope: str) -> str:
    if not name:
        return """<div class="harness-status-panel wide">
  <strong>New harness</strong>
  <span>Add a JSON config, then save it before enabling.</span>
</div>"""
    try:
        definition = json.loads(raw or "{}")
    except json.JSONDecodeError:
        definition = {}
    if not isinstance(definition, dict):
        definition = {}
    definition.setdefault("name", name)
    enabled = harness_enabled(definition)
    detected = harness_detected(definition)
    status = "Enabled" if enabled else "Disabled"
    detect_status = "Detected" if detected else "Not detected"
    action = "disable" if enabled else "enable"
    action_label = "Disable" if enabled else "Enable"
    return f"""<div class="harness-status-panel wide">
  <div>
    <strong>{escape(status)}</strong>
    <span>{escape(detect_status)}</span>
  </div>
  <form action="/harnesses/toggle" method="post">
    <input type="hidden" name="name" value="{escape(name)}">
    <input type="hidden" name="scope" value="{escape(scope)}">
    <input type="hidden" name="action" value="{escape(action)}">
    <button type="submit" class="secondary">{escape(action_label)}</button>
  </form>
</div>"""


def render_file_editor(content_type: str, name: str, raw: str, path: Path, scope: str, installed: bool) -> str:
    label = "JSON" if path.suffix == ".json" else "contents"
    section_class = "editor full" if content_type == "harnesses" else "editor"
    status_panel = render_harness_status_panel(name, raw, scope) if content_type == "harnesses" else ""
    return f"""<section class="{section_class}">
  <span data-editor-type="{escape(content_type)}"></span>
  {render_editor_header(content_type, name, path, scope, "file", installed)}
  {status_panel}
  <form class="edit-form" action="/save" method="post">
    <input type="hidden" name="type" value="{content_type}">
    <input type="hidden" name="original_name" value="{escape(name)}">
    <input type="hidden" name="original_suffix" value="{escape(path.suffix)}">
    <input type="hidden" name="scope" value="{escape(scope)}" data-scope-hidden>
    <input type="hidden" name="editor_view" value="file">
    <label>
      <span>file name</span>
      <input name="name" value="{escape(name)}" required data-name-input>
    </label>
    <label class="wide">
      <span>{label}</span>
      <textarea class="file-editor" name="raw" rows="32" spellcheck="false">{escape(raw)}</textarea>
    </label>
  </form>
</section>"""


def render_external_editor(content_type: str, harness: str, raw_path: str, scope: str) -> str:
    item = external_item_from_path(content_type, harness, raw_path, scope)
    path = Path(str(item["path"]))
    raw = path.read_text(encoding="utf-8")
    name = str(item.get("name") or external_name_from_path(harness, path))
    harness_label = str(item.get("harness_label") or harness)
    label = path.suffix.upper().lstrip(".") or "contents"
    return f"""<section class="editor external-editor">
  <span data-editor-type="{escape(content_type)}"></span>
  <div class="editor-head">
    <div>
      <h2>{escape(name)}</h2>
    </div>
  </div>
  <form class="edit-form" action="/save-external" method="post">
    <input type="hidden" name="type" value="{escape(content_type)}">
    <input type="hidden" name="name" value="{escape(name)}">
    <input type="hidden" name="harness" value="{escape(harness)}">
    <input type="hidden" name="path" value="{escape(path)}">
    <input type="hidden" name="scope" value="{escape(scope)}" data-scope-hidden>
    <label class="wide">
      <span>{escape(label)}</span>
      <textarea class="file-editor" name="raw" rows="32" spellcheck="false">{escape(raw)}</textarea>
    </label>
  </form>
</section>"""


def render_sync_output(code: int, output: str) -> str:
    status = "completed" if code == 0 else "failed"
    return page("agents", "", "global", f"""<section class="editor full">
  <div class="editor-head"><div><h2>Sync {status}</h2><p>Exit code {code}</p></div></div>
  <pre class="preview filled">{escape(output)}</pre>
  <p><a class="button" href="/">Back</a></p>
</section>""")


def render_error(message: str) -> str:
    return page("agents", "", "global", f"""<section class="editor full">
  <div class="editor-head"><div><h2>Error</h2><p>The request could not be completed.</p></div></div>
  <pre class="preview filled">{escape(message)}</pre>
  <p><a class="button" href="/">Back</a></p>
</section>""")


STYLES = """
:root {
  color-scheme: light dark;
  --bg: #edf2f7;
  --surface: #ffffff;
  --surface-2: #f6f8fc;
  --surface-3: #e8eef7;
  --surface-raised: #fbfdff;
  --chrome: #111827;
  --chrome-2: #172033;
  --chrome-3: #202b3d;
  --chrome-text: #f8fafc;
  --chrome-muted: #9aa8bd;
  --text: #111827;
  --muted: #64748b;
  --line: #d7e0ec;
  --line-strong: #aebbd0;
  --primary: #2557e7;
  --primary-hover: #1d4ed8;
  --primary-text: #ffffff;
  --accent: #06b6d4;
  --accent-soft: #cffafe;
  --danger: #b42318;
  --external: #b7791f;
  --external-strong: #d97706;
  --template: #0f766e;
  --template-strong: #14b8a6;
  --focus: #22d3ee;
  --radius-sm: 6px;
  --radius-md: 8px;
  --shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
  --shadow-sm: 0 1px 2px rgba(15, 23, 42, 0.08);
  --shadow-md: 0 12px 30px rgba(15, 23, 42, 0.12);
  --shadow-lg: 0 24px 70px rgba(15, 23, 42, 0.26);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0b1020;
    --surface: #111827;
    --surface-2: #172033;
    --surface-3: #202b3d;
    --surface-raised: #151e2f;
    --chrome: #070b14;
    --chrome-2: #0d1424;
    --chrome-3: #172033;
    --chrome-text: #f8fafc;
    --chrome-muted: #9aa8bd;
    --text: #e5edf8;
    --muted: #98a6ba;
    --line: #293548;
    --line-strong: #3d4b62;
    --primary: #60a5fa;
    --primary-hover: #93c5fd;
    --primary-text: #06111f;
    --accent: #22d3ee;
    --accent-soft: #083344;
    --external: #fbbf24;
    --external-strong: #f59e0b;
    --template: #2dd4bf;
    --template-strong: #5eead4;
    --shadow: none;
    --shadow-sm: none;
    --shadow-md: 0 18px 42px rgba(0, 0, 0, 0.34);
    --shadow-lg: 0 28px 80px rgba(0, 0, 0, 0.48);
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 14px;
  line-height: 1.45;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
a { color: inherit; text-decoration: none; }
.topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  min-height: 48px;
  display: grid;
  grid-template-columns: minmax(220px, 320px) minmax(0, 1fr);
  align-items: center;
  gap: 14px;
  padding: 8px 14px;
  background: linear-gradient(180deg, var(--chrome-2), var(--chrome));
  color: var(--chrome-text);
  border-bottom: 1px solid color-mix(in srgb, var(--accent) 36%, var(--chrome-3));
  box-shadow: 0 10px 28px rgba(2, 6, 23, 0.22);
}
.topbar-brand {
  min-width: 0;
}
.topbar-brand h1::before {
  content: "";
  width: 9px;
  height: 9px;
  display: inline-block;
  margin-right: 9px;
  border-radius: 999px;
  background: var(--accent);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent) 16%, transparent);
  vertical-align: 2px;
}
h1, h2 { margin: 0; letter-spacing: 0; }
h1 { font-size: 18px; }
h2 { font-size: 16px; }
p { margin: 4px 0 0; color: var(--muted); }
.layout {
  display: grid;
  grid-template-columns: 220px minmax(220px, 320px) minmax(0, 1fr);
  min-height: calc(100vh - 49px);
}
.rail, .list-pane, .editor {
  min-width: 0;
  border-right: 1px solid var(--line);
}
.rail {
  display: flex;
  flex-direction: column;
  padding: 12px;
  background: linear-gradient(180deg, var(--chrome), var(--chrome-2));
  border-right-color: color-mix(in srgb, var(--accent) 20%, var(--chrome-3));
}
.rail a {
  display: block;
  min-height: 36px;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  color: var(--chrome-muted);
}
.rail a.active, .rail a:hover {
  background: color-mix(in srgb, var(--accent) 12%, var(--chrome-3));
  color: var(--chrome-text);
  box-shadow: inset 3px 0 0 var(--accent);
}
.rail-divider {
  height: 1px;
  margin: 14px 0;
  background: color-mix(in srgb, var(--chrome-muted) 20%, transparent);
}
.rail-divider.small {
  margin: 9px 4px;
  opacity: 0.75;
}
.project-nav {
  position: relative;
}
.project-nav-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}
.project-nav h2 {
  margin: 0;
  min-width: 0;
  padding: 0;
  color: var(--chrome-muted);
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
}
.rail-section-toggle {
  min-height: 30px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 4px;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  text-transform: inherit;
}
.rail-section-toggle:hover,
.rail-section-toggle:focus-visible {
  color: var(--chrome-text);
}
.rail-caret {
  width: 12px;
  display: inline-flex;
  justify-content: center;
  transform: rotate(90deg);
  transition: transform 120ms ease;
}
.project-nav[data-collapsed="true"] .rail-caret {
  transform: rotate(0deg);
}
.rail-section-body[hidden] {
  display: none;
}
.project-entry {
  margin-bottom: 6px;
}
.project-entry span {
  display: block;
  font-weight: 650;
  overflow-wrap: anywhere;
}
.project-entry small {
  display: block;
  margin-top: 2px;
  color: color-mix(in srgb, var(--chrome-muted) 86%, transparent);
  font-size: 11px;
  line-height: 1.25;
  overflow-wrap: anywhere;
}
.rail-show-others-button {
  width: 100%;
  min-height: 32px;
  margin-top: 4px;
  padding: 7px 10px;
  border: 1px solid color-mix(in srgb, var(--chrome-muted) 22%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--chrome-3) 58%, transparent);
  color: var(--chrome-muted);
  font-size: 12px;
  font-weight: 700;
  text-align: left;
}
.rail-show-others-button:hover,
.rail-show-others-button:focus-visible {
  border-color: color-mix(in srgb, var(--accent) 45%, var(--chrome-muted));
  color: var(--chrome-text);
  background: color-mix(in srgb, var(--accent) 12%, var(--chrome-3));
}
.harness-other-list {
  margin-top: 6px;
}
.list-pane {
  grid-column: 2;
  display: flex;
  flex-direction: column;
  background: var(--surface);
}
.type-tabs {
  display: grid;
  grid-template-columns: repeat(8, minmax(82px, 1fr));
  gap: 0;
  min-width: 0;
  min-height: 40px;
  padding: 3px;
  border: 1px solid color-mix(in srgb, var(--chrome-muted) 24%, transparent);
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--chrome-3) 72%, transparent);
  overflow-x: auto;
}
.type-tabs a {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 32px;
  padding: 6px 10px;
  border-radius: var(--radius-sm);
  color: var(--chrome-muted);
  white-space: nowrap;
  text-align: center;
}
.type-tabs a.active,
.type-tabs a:hover {
  background: linear-gradient(180deg, color-mix(in srgb, var(--accent) 20%, var(--chrome-3)), var(--chrome-3));
  color: var(--chrome-text);
  box-shadow: inset 0 -2px 0 var(--accent);
}
.rail-sync-form {
  margin-top: auto;
  padding-top: 14px;
  border-top: 1px solid color-mix(in srgb, var(--chrome-muted) 20%, transparent);
}
.rail-sync-form button {
  flex: 1;
  min-width: 0;
}
.pane-head, .editor-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--line);
}
.item-list {
  flex: 1;
  min-height: 0;
  max-height: none;
  overflow: auto;
}
.item {
  display: block;
  padding: 11px 16px;
  border-bottom: 1px solid var(--line);
}
.item span {
  display: block;
  font-weight: 650;
  overflow-wrap: anywhere;
}
.item small {
  display: block;
  margin-top: 2px;
  color: var(--muted);
  overflow-wrap: anywhere;
}
.item.active, .item:hover { background: var(--surface-2); }
.editor {
  background: var(--surface);
  border-right: 0;
  overflow: auto;
}
.editor.full { grid-column: 2 / -1; }
.selection-page {
  grid-column: 2 / -1;
  min-width: 0;
  min-height: calc(100vh - 49px);
  display: flex;
  flex-direction: column;
  overflow: auto;
  background: var(--surface);
}
.selection-summary-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  padding: 14px 16px 0;
}
.selection-bottom-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
  padding: 14px 16px 0;
}
.selection-action-buttons {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.selection-bottom-actions .button {
  min-height: 32px;
  padding: 6px 10px;
}
.source-mode-form {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-left: auto;
}
.hide-global-loaded-option {
  min-height: 32px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 650;
  white-space: nowrap;
}
.hide-global-loaded-option input {
  width: 15px;
  height: 15px;
  margin: 0;
  accent-color: var(--primary);
}
.hide-global-loaded-option:hover {
  color: var(--text);
}
.hide-global-loaded-option:has(input:disabled) {
  opacity: 0.5;
}
.source-mode-group {
  display: inline-flex;
  align-items: center;
  min-height: 32px;
  margin: 0;
  padding: 0;
  border: 0;
}
.source-mode-option {
  display: inline-flex;
  min-width: 0;
}
.source-mode-option input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}
.source-mode-option span {
  min-height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 6px 10px;
  border: 1px solid var(--line);
  border-left-width: 0;
  background: var(--surface);
  color: var(--muted);
  font-size: 12px;
  font-weight: 650;
  line-height: 1;
  white-space: nowrap;
  cursor: pointer;
}
.source-mode-option:first-child span {
  border-left-width: 1px;
  border-radius: 6px 0 0 6px;
}
.source-mode-option:last-child span {
  border-radius: 0 6px 6px 0;
}
.source-mode-option input:checked + span {
  border-color: var(--primary);
  background: var(--primary);
  color: var(--primary-text);
}
.source-mode-option:hover span,
.source-mode-option input:focus-visible + span {
  border-color: var(--primary);
  color: var(--text);
}
.source-mode-option input:checked + span {
  color: var(--primary-text);
}
.source-mode-option input:disabled + span {
  opacity: 0.5;
  cursor: default;
}
.selection-summary {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
  font-weight: 650;
}
.selection-summary-controls {
  display: flex;
  flex: 1;
  flex-wrap: wrap;
  justify-content: flex-end;
  align-items: center;
  gap: 10px;
}
.selection-summary-controls label,
.selection-summary-controls .control-field {
  display: flex;
  grid-template-columns: none;
  align-items: center;
  gap: 7px;
  min-width: 0;
  white-space: nowrap;
}
.selection-summary-controls .selection-search {
  flex: 1 1 260px;
  min-width: 220px;
}
.selection-summary-controls label span,
.selection-summary-controls .control-field > span {
  color: var(--muted);
  font-size: 12px;
  font-weight: 650;
}
.selection-summary-controls > label input,
.selection-summary-controls > label select,
.selection-summary-controls > .control-field > .harness-multiselect summary {
  width: 100%;
  min-height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 5px 8px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  font-size: 12px;
  font-weight: 650;
}
.selection-summary-controls > label input:hover,
.selection-summary-controls > label input:focus,
.selection-summary-controls > label select:hover,
.selection-summary-controls > label select:focus,
.selection-summary-controls > .control-field > .harness-multiselect summary:hover,
.selection-summary-controls > .control-field > .harness-multiselect summary:focus-visible {
  border-color: var(--primary);
  background-color: var(--surface-2);
  outline: none;
}
.selection-summary-controls > label input {
  justify-content: flex-start;
  font-weight: 500;
}
.selection-summary-controls > label input::placeholder {
  color: var(--muted);
  font-weight: 500;
}
.selection-summary-controls > label select {
  appearance: none;
  padding-right: 26px;
  background-image: linear-gradient(45deg, transparent 50%, var(--muted) 50%), linear-gradient(135deg, var(--muted) 50%, transparent 50%);
  background-position: calc(100% - 13px) 50%, calc(100% - 8px) 50%;
  background-size: 5px 5px, 5px 5px;
  background-repeat: no-repeat;
}
.harness-filter-field,
.group-filter-field,
.sort-filter-field {
  overflow: visible;
}
.selection-summary-controls .filter-multiselect {
  width: 170px;
}
.selection-grid {
  flex: 1 0 auto;
  align-content: start;
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 14px;
  padding: 16px;
}
.selection-card {
  position: relative;
  isolation: isolate;
  height: 220px;
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 16px;
  border: 1px solid color-mix(in srgb, var(--line) 82%, var(--primary));
  border-radius: var(--radius-md);
  background: linear-gradient(180deg, var(--surface-raised), var(--surface));
  box-shadow: var(--shadow-sm);
  transition: border-color 140ms ease, background 140ms ease, box-shadow 140ms ease, transform 140ms ease;
  overflow: visible;
}
.selection-card::after {
  content: "";
  position: absolute;
  inset: -1px -1px auto -1px;
  height: 4px;
  border-radius: var(--radius-md) var(--radius-md) 0 0;
  background: linear-gradient(90deg, var(--primary), var(--accent));
  opacity: 0.9;
  pointer-events: none;
}
.selection-card-edit {
  flex: 0 0 30px;
  width: 30px;
  height: 30px;
  min-height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: transparent;
  font-size: 0;
}
.selection-card-edit::before {
  content: "\\270E";
  color: var(--text);
  font-size: 14px;
  line-height: 1;
}
.selection-card-edit:hover,
.selection-card-edit:focus-visible {
  border-color: var(--primary);
  background: var(--surface-2);
}
.selection-card:hover,
.selection-card:focus-within {
  border-color: color-mix(in srgb, var(--primary) 70%, var(--accent));
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}
.selection-card[data-selection-preview-card],
.selection-card[data-external-preview-card] {
  cursor: pointer;
}
.external-selection-card {
  border: 1.5px dashed var(--external);
  background: var(--surface);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--external) 12%, transparent);
}
.external-selection-card::after {
  background: var(--external);
  opacity: 0.65;
}
.external-selection-card:hover,
.external-selection-card:focus-within {
  border-color: var(--external-strong);
  background: color-mix(in srgb, var(--external) 4%, var(--surface));
}
.template-selection-card {
  border-color: color-mix(in srgb, var(--template) 42%, var(--line));
}
.template-selection-card::after {
  background: linear-gradient(90deg, var(--template), var(--template-strong), var(--accent));
  opacity: 0.9;
}
.template-selection-card:hover,
.template-selection-card:focus-within {
  border-color: var(--template);
  background: color-mix(in srgb, var(--template) 4%, var(--surface));
}
.global-loaded-selection-card {
  border: 1.5px solid color-mix(in srgb, var(--primary) 84%, var(--line));
  background: linear-gradient(90deg, color-mix(in srgb, var(--primary) 13%, var(--surface)) 0, var(--surface) 42%);
  box-shadow: inset 4px 0 0 var(--primary), inset 0 0 0 1px color-mix(in srgb, var(--primary) 18%, transparent), var(--shadow-sm);
}
.global-loaded-selection-card:hover,
.global-loaded-selection-card:focus-within {
  border-color: var(--primary);
  background: linear-gradient(90deg, color-mix(in srgb, var(--primary) 18%, var(--surface)) 0, var(--surface) 46%);
}
.selection-card span {
  display: block;
  color: var(--text);
  font-weight: 700;
  overflow-wrap: anywhere;
}
.selection-card small {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  height: 48.6px;
  max-height: 48.6px;
  overflow: hidden;
  color: var(--muted);
  font-size: 12px;
  line-height: 16.2px;
  overflow-wrap: anywhere;
}
.selection-card-new {
  border-style: dashed;
  background: var(--bg);
}
.selection-card-new span {
  color: var(--primary);
}
.selection-card-main {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.selection-card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.selection-card-title > .selection-card-name {
  min-width: 0;
  flex: 1 1 auto;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.selection-card .selection-card-scope-icons {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
}
.selection-card .selection-card-scope-indicator {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  min-height: 30px;
  color: var(--primary);
  font-weight: 700;
  overflow: visible;
  white-space: nowrap;
}
.selection-card .scope-indicator-icon {
  width: 30px;
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid color-mix(in srgb, var(--primary) 70%, var(--line));
  border-radius: 5px;
  background: color-mix(in srgb, var(--primary) 13%, var(--surface));
  color: var(--primary);
}
.selection-card .scope-indicator-icon svg {
  width: 15px;
  height: 15px;
  display: block;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.selection-card-scope-indicator:hover .scope-indicator-icon {
  border-color: var(--primary);
  background: color-mix(in srgb, var(--primary) 18%, var(--surface));
}
.selection-card .scope-tooltip,
.selection-card .selection-card-scope-indicator::before {
  position: absolute;
  right: 0;
  opacity: 0;
  pointer-events: none;
  transform: translateY(4px);
  transition: opacity 140ms ease, transform 140ms ease;
  z-index: 40;
}
.selection-card .scope-tooltip {
  display: none;
  top: calc(100% + 8px);
  min-width: 180px;
  max-width: 260px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface-2);
  color: var(--text);
  box-shadow: var(--shadow);
  font-size: 11px;
  font-weight: 500;
  line-height: 1.35;
  text-align: left;
  white-space: normal;
}
.scope-tooltip-title {
  display: block;
  margin-bottom: 5px;
  color: var(--text);
  font-size: 11px;
  font-weight: 750;
  line-height: 1.2;
}
.selection-card .scope-tooltip ul {
  display: grid;
  gap: 3px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.selection-card .scope-tooltip li {
  color: var(--muted);
  font-size: 11px;
  font-weight: 500;
  line-height: 1.25;
}
.selection-card .selection-card-scope-indicator::before {
  content: "";
  top: calc(100% + 4px);
  width: 8px;
  height: 8px;
  margin-right: 11px;
  border-left: 1px solid var(--line);
  border-top: 1px solid var(--line);
  background: var(--surface-2);
  rotate: 45deg;
}
.selection-card .selection-card-scope-indicator:hover .scope-tooltip,
.selection-card .selection-card-scope-indicator:hover::before,
.selection-card .selection-card-scope-indicator:focus-visible .scope-tooltip,
.selection-card .selection-card-scope-indicator:focus-visible::before {
  opacity: 1;
  transform: translateY(0);
}
.selection-card .selection-card-scope-indicator:hover .scope-tooltip,
.selection-card .selection-card-scope-indicator:focus-visible .scope-tooltip {
  display: block;
}
.selection-card .selection-card-scope-indicator:focus-visible .scope-indicator-icon {
  outline: 2px solid color-mix(in srgb, var(--primary) 42%, transparent);
  outline-offset: 2px;
}
.selection-card-main small {
  flex: 0 0 48.6px;
}
.selection-card-meta {
  display: grid;
  gap: 4px;
  margin: 2px 0 1px;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
}
.selection-card-meta p {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
  margin: 0;
}
.selection-card-meta span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}
.selection-card-counts span {
  color: var(--text);
  font-weight: 650;
}
.selection-card-dates span {
  color: color-mix(in srgb, var(--muted) 78%, var(--surface));
  font-weight: 400;
}
.selection-card-meta span:last-child {
  text-align: right;
}
.selection-card-actions {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
}
.selection-card-update-form {
  grid-column: 1 / -1;
  width: 100%;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  min-width: 0;
}
.selection-card-actions .button,
.selection-card-actions button,
.harness-multiselect summary {
  width: 100%;
  min-height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 6px 8px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  font-size: 12px;
  font-weight: 650;
  cursor: pointer;
}
.selection-card-actions .button:hover,
.selection-card-actions .button:focus-visible,
.selection-card-actions button:hover,
.selection-card-actions button:focus-visible,
.harness-multiselect summary:hover,
.harness-multiselect summary:focus-visible {
  border-color: var(--primary);
  background: var(--surface-2);
}
.harness-multiselect {
  position: relative;
  min-width: 0;
}
.harness-multiselect[open] {
  z-index: 30;
}
.harness-multiselect summary {
  gap: 8px;
  justify-content: space-between;
  list-style: none;
}
.harness-multiselect [data-harness-summary-text] {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.multiselect-caret {
  width: 10px;
  height: 10px;
  flex: 0 0 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--muted);
  transition: transform 120ms ease;
}
.multiselect-caret::before {
  content: "";
  width: 10px;
  height: 10px;
  display: block;
  background-image: linear-gradient(45deg, transparent 50%, var(--muted) 50%), linear-gradient(135deg, var(--muted) 50%, transparent 50%);
  background-position: 0 50%, 5px 50%;
  background-size: 5px 5px, 5px 5px;
  background-repeat: no-repeat;
}
.harness-multiselect[open] .multiselect-caret {
  transform: rotate(180deg);
}
.harness-multiselect summary::-webkit-details-marker {
  display: none;
}
.harness-multiselect .harness-menu-options {
  position: absolute;
  left: 0;
  bottom: calc(100% + 8px);
  width: min(240px, 78vw);
  max-height: min(320px, calc(100vh - 160px));
  display: grid;
  gap: 10px;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  box-shadow: 0 12px 36px rgba(15, 23, 42, 0.18);
}
.filter-multiselect .harness-menu-options,
.harness-filter-multiselect .harness-menu-options {
  top: calc(100% + 8px);
  bottom: auto;
}
.harness-menu-options {
  display: grid;
  gap: 6px;
  margin: 0;
  padding: 0;
  border: 0;
}
.harness-menu-options legend {
  margin: 0 0 2px;
  color: var(--muted);
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
}
.harness-menu-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--line);
}
.harness-menu-actions button {
  min-height: 28px;
  padding: 5px 7px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  font-size: 11px;
  font-weight: 650;
  cursor: pointer;
}
.harness-menu-actions button:hover,
.harness-menu-actions button:focus-visible {
  border-color: var(--primary);
  background: var(--surface-2);
}
.harness-option {
  display: flex;
  grid-template-columns: none;
  align-items: center;
  gap: 8px;
  min-height: 28px;
  color: var(--text);
  font-weight: 500;
}
.harness-option input {
  width: auto;
  margin: 0;
}
.harness-option span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  text-transform: none;
}
.harness-option-none {
  padding-bottom: 6px;
  border-bottom: 1px solid var(--line);
}
.selection-card-actions button.selection-card-action-update {
  border-color: var(--primary);
  background: var(--primary);
  color: var(--primary-text);
  font-weight: 650;
  min-width: 76px;
}
.selection-card-actions button.selection-card-action-update:hover,
.selection-card-actions button.selection-card-action-update:focus-visible {
  border-color: var(--primary);
  background: var(--primary);
  color: var(--primary-text);
}
.selection-card-form {
  min-width: 0;
}
.external-import-form {
  grid-column: 1 / -1;
  display: block;
}
.external-preview-path {
  margin: -4px 0 12px;
  color: var(--muted);
  font-size: 12px;
  overflow-wrap: anywhere;
}
button:disabled {
  opacity: 0.48;
  cursor: default;
}
.pagination-footer {
  display: grid;
  grid-template-columns: minmax(160px, 1fr) auto minmax(160px, 1fr);
  align-items: center;
  gap: 12px;
  margin: auto 16px 0;
  padding: 22px 8px 18px;
  border-top: 1px solid var(--line);
  text-align: center;
}
.pagination-footer .selection-summary {
  justify-self: end;
  text-align: right;
}
.pagination {
  grid-column: 2;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 6px;
}
.page-link {
  min-width: 36px;
  min-height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 6px 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--muted);
  font-weight: 650;
}
.page-link.active {
  border-color: var(--primary);
  background: var(--primary);
  color: var(--primary-text);
}
.page-link.disabled {
  opacity: 0.5;
  cursor: default;
}
.page-link:not(.disabled):not(.active):hover {
  border-color: var(--primary);
  color: var(--text);
}
.edit-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(180px, 1fr));
  gap: 14px;
  padding: 16px;
}
.fields {
  display: contents;
}
.checkbox-field {
  min-height: 38px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  align-self: end;
  padding: 9px 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
  font-size: 13px;
  font-weight: 650;
}
.checkbox-field input {
  width: auto;
  margin: 0;
}
.mapping-editor-note {
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--bg);
  color: var(--muted);
  font-size: 12px;
}
.harness-status-panel {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--bg);
}
.harness-status-panel div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.harness-status-panel span {
  color: var(--muted);
  font-size: 12px;
}
.harness-status-panel form {
  margin: 0;
}
.harness-structured-editor .edit-form {
  grid-template-columns: 1fr;
}
.harness-form-section {
  display: grid;
  gap: 12px;
  margin: 0;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background:
    linear-gradient(180deg, rgba(96, 165, 250, 0.08), transparent 120px),
    var(--surface);
}
.harness-form-section legend {
  padding: 0 5px;
  color: var(--text);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.02em;
}
.harness-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(220px, 1fr));
  gap: 12px;
}
.harness-form-grid.compact {
  grid-template-columns: repeat(3, minmax(180px, 1fr));
}
.harness-form-grid .wide {
  grid-column: 1 / -1;
}
.mapping-contract-summary {
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--bg);
}
.mapping-contract-summary table {
  width: 100%;
  border-collapse: collapse;
}
.mapping-contract-summary th,
.mapping-contract-summary td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--line);
  color: var(--text);
  font-size: 12px;
  text-align: left;
  vertical-align: top;
}
.mapping-contract-summary th {
  color: var(--muted);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.mapping-contract-summary tr:last-child td {
  border-bottom: 0;
}
.mapping-contract-summary td:last-child {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.mapping-contract-summary code {
  display: inline-flex;
  max-width: 100%;
  padding: 2px 6px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  font-size: 11px;
  overflow-wrap: anywhere;
}
.mapping-contract-empty {
  padding: 10px 12px;
  border: 1px dashed var(--line);
  border-radius: 8px;
  color: var(--muted);
  font-size: 12px;
}
.harness-json-field textarea {
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  font-size: 12px;
  line-height: 1.5;
}
.body-section-editor {
  display: grid;
  gap: 12px;
  margin: 0;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--bg);
}
.body-section-editor legend {
  padding: 0 4px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}
.body-template-row {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) auto auto;
  gap: 10px;
  align-items: end;
}
.body-template-row label {
  min-width: 0;
}
.body-template-row select {
  width: 100%;
}
.body-template-row button {
  min-height: 36px;
  white-space: nowrap;
}
.body-section-list {
  display: grid;
  gap: 10px;
}
.body-section {
  display: grid;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}
.body-section-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 116px auto auto auto auto auto;
  gap: 10px;
  align-items: end;
}
.body-section-head label {
  min-width: 0;
}
.body-section-head input,
.body-section-head select {
  width: 100%;
}
.body-section-content-label {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}
.body-section-content-label small {
  color: var(--muted);
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.body-section-remove,
.body-section-move,
.body-section-preview-toggle,
.body-section-collapse {
  min-height: 36px;
  white-space: nowrap;
}
.body-section[data-collapsed="true"] {
  background: color-mix(in srgb, var(--surface) 72%, var(--bg));
}
.body-section-undo {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px dashed var(--line-strong);
  border-radius: 8px;
  background: color-mix(in srgb, var(--surface) 80%, var(--bg));
  color: var(--muted);
  font-size: 12px;
  font-weight: 650;
}
.body-section-undo button {
  min-height: 30px;
}
.body-section-preview {
  max-height: 280px;
  overflow: auto;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--bg);
  color: var(--text);
}
.body-section-preview :first-child {
  margin-top: 0;
}
.body-section-preview :last-child {
  margin-bottom: 0;
}
.body-section-preview p,
.body-section-preview ul,
.body-section-preview pre {
  margin: 0 0 10px;
}
.body-section-preview ul {
  padding-left: 20px;
}
.body-section-preview h3,
.body-section-preview h4,
.body-section-preview h5,
.body-section-preview h6 {
  margin: 0 0 8px;
  font-size: 13px;
}
.body-section-preview pre {
  padding: 10px;
  border-radius: 6px;
  background: #0c111b;
  color: #d9e2f1;
  overflow: auto;
}
.body-section-preview code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}
.body-section-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  justify-content: flex-start;
}
.body-section-actions select {
  width: min(260px, 100%);
}
.body-section-actions button {
  min-width: 118px;
}
.template-section-editor,
.template-field-section-editor {
  display: grid;
  gap: 12px;
  margin: 0;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--bg);
}
.template-field-preset-editor {
  display: grid;
  gap: 12px;
  margin: 0;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--bg);
}
.template-section-editor legend,
.template-field-section-editor legend {
  padding: 0 4px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}
.template-field-preset-editor legend {
  padding: 0 4px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}
.template-field-preset-note {
  color: var(--muted);
  font-size: 12px;
}
.template-field-section-note {
  color: var(--muted);
  font-size: 12px;
}
.template-section-list {
  display: grid;
  gap: 10px;
}
.template-field-section-group-list,
.template-field-section-list {
  display: grid;
  gap: 10px;
}
.template-section-row {
  display: grid;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}
.template-field-section-row {
  display: grid;
  gap: 10px;
  padding: 12px;
  border: 1px solid color-mix(in srgb, var(--primary) 24%, var(--line));
  border-radius: 8px;
  background: color-mix(in srgb, var(--primary) 4%, var(--surface));
}
.template-field-section-list {
  padding: 2px 0 0 10px;
  border-left: 1px solid color-mix(in srgb, var(--primary) 24%, var(--line));
}
.template-field-section-head {
  display: grid;
  grid-template-columns: minmax(150px, 0.35fr) minmax(180px, 1fr) auto auto;
  gap: 10px;
  align-items: end;
}
.template-field-section-head label {
  min-width: 0;
}
.template-field-section-head input {
  width: 100%;
}
.template-section-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 116px auto auto auto;
  gap: 10px;
  align-items: end;
}
.template-section-head label {
  min-width: 0;
}
.template-section-head input,
.template-section-head select {
  width: 100%;
}
.template-section-move,
.template-section-remove {
  min-height: 36px;
  white-space: nowrap;
}
.template-section-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.template-section-actions button {
  min-width: 118px;
}
.extra-fields-editor {
  display: grid;
  gap: 12px;
  margin: 0;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--bg);
}
.extra-fields-editor legend {
  padding: 0 4px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}
.extra-fields-list {
  display: grid;
  gap: 10px;
}
.extra-field-row {
  display: grid;
  grid-template-columns: minmax(140px, 0.38fr) minmax(110px, 0.18fr) minmax(0, 1fr) auto;
  gap: 10px;
  align-items: end;
}
.extra-field-row label {
  min-width: 0;
}
.extra-field-row[data-field-invalid="true"],
.mapping-field-row[data-field-invalid="true"],
.template-section-row[data-field-invalid="true"] {
  padding: 8px;
  border: 1px solid color-mix(in srgb, var(--danger) 72%, var(--line));
  border-radius: 8px;
  background: color-mix(in srgb, var(--danger) 8%, var(--surface));
}
.extra-field-remove {
  min-height: 36px;
  white-space: nowrap;
}
.extra-fields-actions {
  display: flex;
  justify-content: flex-start;
}
.extra-fields-actions button {
  min-width: 104px;
}
.list-field-editor {
  display: grid;
  gap: 12px;
  margin: 0;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--bg);
}
.list-field-editor legend {
  padding: 0 4px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}
.list-field-list {
  display: grid;
  gap: 10px;
  max-height: 300px;
  overflow: auto;
  padding-right: 2px;
}
.list-field-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: end;
}
.list-field-row label {
  min-width: 0;
}
.list-field-remove {
  min-height: 36px;
  white-space: nowrap;
}
.list-field-actions {
  display: flex;
  justify-content: flex-start;
}
.list-field-actions button {
  min-width: 96px;
}
.mapping-field-editor {
  display: grid;
  gap: 12px;
  margin: 0;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--bg);
}
.mapping-field-editor legend {
  padding: 0 4px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}
.mapping-field-list {
  display: grid;
  gap: 10px;
  max-height: 320px;
  overflow: auto;
  padding-right: 2px;
}
.mapping-field-row {
  display: grid;
  grid-template-columns: minmax(140px, 0.38fr) minmax(110px, 0.18fr) minmax(0, 1fr) auto;
  gap: 10px;
  align-items: end;
}
.mapping-field-row label {
  min-width: 0;
}
.mapping-field-remove {
  min-height: 36px;
  white-space: nowrap;
}
.mapping-field-actions {
  display: flex;
  justify-content: flex-start;
}
.mapping-field-actions button {
  min-width: 104px;
}
.agent-model-fields,
.agent-reasoning-fields {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--bg);
}
.agent-model-fields legend,
.agent-reasoning-fields legend {
  padding: 0 4px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}
.agent-model-grid,
.agent-reasoning-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}
.agent-harness-settings {
  display: grid;
  gap: 10px;
  min-width: 0;
}
.agent-harness-settings h4 {
  margin: 0;
  overflow: hidden;
  color: var(--text);
  font-size: 13px;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.agent-model-grid label,
.agent-reasoning-grid label {
  min-width: 0;
}
.agent-model-grid select,
.agent-reasoning-grid select {
  width: 100%;
}
.agent-capability-fields {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--bg);
}
.agent-capability-fields legend {
  padding: 0 4px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}
.agent-capability-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 12px;
}
.capability-group {
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  overflow: hidden;
}
.capability-group-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
}
.capability-group-head h4 {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  color: var(--text);
  font-size: 13px;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.capability-group-head span {
  flex: 0 0 auto;
  color: var(--muted);
  font-size: 12px;
}
.capability-support {
  margin: 0;
  padding: 8px 12px;
  border-bottom: 1px solid var(--line);
  color: var(--muted);
  font-size: 12px;
  line-height: 1.35;
}
.capability-list {
  display: grid;
  max-height: 280px;
  overflow: auto;
}
.capability-option {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-height: 44px;
  padding: 9px 12px;
  border-bottom: 1px solid var(--line);
  color: var(--text);
  font-weight: 500;
}
.capability-option:last-child {
  border-bottom: 0;
}
.capability-option:hover {
  background: var(--bg);
}
.capability-option input {
  width: auto;
}
.capability-option-text {
  display: grid;
  min-width: 0;
  gap: 2px;
}
.capability-option-text strong,
.capability-option-text small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.capability-option-text strong {
  color: var(--text);
  font-size: 13px;
}
.capability-option-text small {
  color: var(--muted);
  font-size: 12px;
}
.capability-source {
  flex: 0 0 auto;
  color: var(--muted);
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
}
.capability-empty {
  padding: 14px 12px;
  color: var(--muted);
  font-size: 13px;
}
label {
  display: grid;
  gap: 6px;
  color: var(--muted);
  font-weight: 600;
}
[hidden] {
  display: none !important;
}
label span { font-size: 12px; text-transform: uppercase; letter-spacing: 0; }
input, textarea {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: var(--text);
  padding: 9px 10px;
  font: inherit;
}
select {
  min-height: 36px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: var(--text);
  padding: 7px 34px 7px 10px;
  font: inherit;
}
textarea {
  resize: vertical;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
}
input:focus,
textarea:focus,
select:focus,
button:focus-visible,
a:focus-visible,
summary:focus-visible {
  outline: none;
  border-color: var(--focus);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--focus) 24%, transparent);
}
.wide, .form-actions, .preview { grid-column: 1 / -1; }
button, .button {
  min-height: 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--primary);
  border-radius: var(--radius-sm);
  padding: 8px 12px;
  background: linear-gradient(180deg, color-mix(in srgb, var(--primary) 92%, white), var(--primary));
  color: var(--primary-text);
  font-weight: 650;
  box-shadow: 0 1px 0 rgba(255,255,255,0.18) inset;
  cursor: pointer;
}
button:hover,
.button:hover {
  border-color: var(--primary-hover);
  background: var(--primary-hover);
}
button.secondary, .button.secondary {
  border-color: var(--line);
  background: var(--surface-raised);
  color: var(--text);
}
button.secondary:hover,
.button.secondary:hover {
  border-color: color-mix(in srgb, var(--primary) 55%, var(--line));
  background: color-mix(in srgb, var(--primary) 7%, var(--surface));
}
.project-nav .add-project-button,
.icon-button {
  width: 30px;
  height: 30px;
  min-height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 1px solid var(--line);
  border-radius: 6px;
  border-color: var(--line);
  background: var(--surface);
  color: var(--text);
  font-size: 18px;
  font-weight: 700;
  line-height: 1;
}
.icon-button {
  transform: rotate(45deg);
}
.modal-backdrop[hidden] {
  display: none;
}
.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(7, 11, 20, 0.68);
  backdrop-filter: blur(10px);
}
.modal {
  width: min(680px, 100%);
  max-height: min(760px, calc(100vh - 48px));
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--accent) 28%, var(--line));
  border-radius: var(--radius-md);
  background: var(--surface);
  box-shadow: var(--shadow-lg);
}
.modal::before {
  content: "";
  height: 4px;
  flex: 0 0 auto;
  background: linear-gradient(90deg, var(--primary), var(--accent), var(--template-strong));
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--line);
  background: linear-gradient(180deg, var(--surface-raised), var(--surface));
}
.modal-title-group {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.modal-title-group h2 {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.modal-head-actions {
  flex: 0 0 auto;
}
.modal-head-actions .modal-action-bar {
  padding: 0;
}
.modal-form {
  display: grid;
  gap: 14px;
  padding: 16px;
  overflow: auto;
}
.content-modal {
  width: min(1040px, 100%);
}
.content-modal-body {
  min-height: 0;
  overflow: auto;
}
.content-modal-body .editor {
  border: 0;
  overflow: visible;
}
.content-modal-body .editor.full {
  grid-column: auto;
}
.content-modal-body .editor-head {
  padding: 12px 16px;
}
.modal-preview-output,
.modal-error,
.modal-loading {
  margin: 0;
  padding: 16px;
}
.modal-preview-output,
.modal-error {
  min-height: 420px;
  overflow: auto;
  white-space: pre-wrap;
  color: var(--text);
  background: var(--bg);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}
.modal-error {
  min-height: auto;
  margin: 16px 16px 0;
  border: 1px solid var(--line);
  border-radius: 6px;
}
.modal-action-bar {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 16px 0;
}
.import-source-group {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0;
  margin: 0;
  padding: 0;
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
}
.import-source-group legend {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
}
.import-source-group label {
  min-height: 38px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 10px;
  border-right: 1px solid var(--line);
  background: var(--surface);
  color: var(--muted);
  font-size: 12px;
  font-weight: 750;
  cursor: pointer;
}
.import-source-group label:last-child {
  border-right: 0;
}
.import-source-group input {
  width: auto;
  margin: 0;
}
.import-source-group label:has(input:checked) {
  background: color-mix(in srgb, var(--primary) 12%, var(--surface));
  color: var(--text);
}
.preview-harness-row {
  padding: 12px 16px;
  border-bottom: 1px solid var(--line);
}
.preview-harness-row label {
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: 360px;
}
.preview-harness-row span {
  color: var(--muted);
  font-size: 12px;
  font-weight: 650;
}
.preview-harness-row select {
  min-width: 180px;
  min-height: 32px;
  padding: 5px 8px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  font-size: 12px;
  font-weight: 650;
}
.preview-harness-row select:hover,
.preview-harness-row select:focus-visible {
  border-color: var(--primary);
  outline: none;
}
.confirm-copy {
  margin: 0;
  color: var(--text);
}
button.danger,
.button.danger {
  border-color: #dc2626;
  color: #b91c1c;
}
button.danger:hover,
button.danger:focus-visible,
.button.danger:hover,
.button.danger:focus-visible {
  background: color-mix(in srgb, #ef4444 12%, var(--surface));
}
.rendered-preview {
  display: grid;
  gap: 16px;
  padding: 16px;
}
.rendered-preview-section {
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--bg);
}
.rendered-preview-section > h3 {
  margin: 0;
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
  font-size: 13px;
}
.rendered-markdown {
  padding: 14px;
  color: var(--text);
}
.rendered-markdown h1,
.rendered-markdown h2,
.rendered-markdown h3,
.rendered-markdown h4,
.rendered-markdown h5,
.rendered-markdown h6 {
  margin: 14px 0 8px;
}
.rendered-markdown h1:first-child,
.rendered-markdown h2:first-child,
.rendered-markdown h3:first-child {
  margin-top: 0;
}
.rendered-markdown p,
.rendered-markdown li,
.rendered-markdown blockquote {
  color: var(--text);
}
.rendered-markdown p {
  margin: 0 0 10px;
}
.rendered-markdown ul {
  margin: 0 0 12px 20px;
  padding: 0;
}
.rendered-markdown blockquote {
  margin: 0 0 12px;
  padding: 8px 12px;
  border-left: 3px solid var(--line);
  background: var(--surface);
}
.rendered-markdown code {
  padding: 2px 4px;
  border-radius: 4px;
  background: var(--surface-2);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.92em;
}
.rendered-markdown a {
  color: var(--primary);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.rendered-frontmatter {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: 6px 12px;
  margin: 0 0 14px;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
}
.rendered-frontmatter dt {
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}
.rendered-frontmatter dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
}
.rendered-structured {
  display: grid;
  gap: 14px;
  padding: 14px;
}
.rendered-structured-fields {
  display: grid;
  grid-template-columns: minmax(120px, max-content) minmax(0, 1fr);
  gap: 8px 14px;
  margin: 0;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
}
.rendered-structured-fields dt {
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}
.rendered-structured-fields dd {
  min-width: 0;
  margin: 0;
  color: var(--text);
  overflow-wrap: anywhere;
}
.rendered-structured-fields code {
  padding: 2px 4px;
  border-radius: 4px;
  background: var(--surface-2);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.92em;
}
.rendered-value-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.rendered-value-pill {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 3px 7px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--surface-2);
  color: var(--text);
  font-size: 12px;
  font-weight: 650;
}
.rendered-muted {
  color: var(--muted);
}
.rendered-yaml-value {
  max-height: 220px;
  margin: 0;
  padding: 10px;
  overflow: auto;
  border-radius: 6px;
  background: var(--bg);
  color: var(--text);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre;
}
.rendered-instructions {
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
}
.rendered-instructions > h4 {
  margin: 0;
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
  color: var(--text);
  font-size: 13px;
}
.rendered-code {
  min-height: 120px;
  max-height: 520px;
  margin: 0;
  padding: 14px;
  overflow: auto;
  color: var(--text);
  background: var(--bg);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre;
}
.rendered-html-frame {
  width: 100%;
  min-height: 560px;
  display: block;
  border: 0;
  background: white;
}
.rendered-empty {
  margin: 0;
  padding: 14px;
  color: var(--muted);
}
.path-input-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
}
.path-browser {
  min-height: 220px;
  max-height: 320px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--bg);
}
.browser-current {
  position: sticky;
  top: 0;
  padding: 9px 10px;
  border-bottom: 1px solid var(--line);
  background: var(--bg);
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  overflow-wrap: anywhere;
}
.browser-row {
  width: 100%;
  min-height: 34px;
  justify-content: flex-start;
  border: 0;
  border-bottom: 1px solid var(--line);
  border-radius: 0;
  background: transparent;
  color: var(--text);
  font-weight: 500;
}
.browser-row:hover {
  background: var(--surface-2);
}
.form-actions, .actions, .sync-form {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.view-toggle {
  display: inline-flex;
  align-items: center;
  padding: 2px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--bg);
}
.view-toggle a {
  min-height: 30px;
  display: inline-flex;
  align-items: center;
  padding: 5px 10px;
  border-radius: 4px;
  color: var(--muted);
  font-weight: 650;
}
.view-toggle a.active {
  background: var(--surface);
  color: var(--text);
  box-shadow: var(--shadow);
}
.sync-form label {
  display: inline-flex;
  grid-template-columns: none;
  align-items: center;
  gap: 6px;
  color: var(--text);
  font-weight: 500;
}
.sync-form label span {
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
}
.sync-form input { width: auto; }
.preview {
  margin: 0 16px 16px;
  padding: 12px;
  min-height: 180px;
  overflow: auto;
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 6px;
  color: var(--text);
  font-size: 12px;
}
.preview.filled { margin-top: 16px; white-space: pre-wrap; }
.file-editor {
  min-height: 520px;
  white-space: pre;
  tab-size: 2;
}
.raw-snapshot {
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--bg);
}
.raw-snapshot summary {
  min-height: 36px;
  display: flex;
  align-items: center;
  padding: 8px 10px;
  cursor: pointer;
  color: var(--muted);
  font-weight: 650;
}
.raw-snapshot pre {
  max-height: 280px;
  margin: 0;
  padding: 12px;
  overflow: auto;
  border-top: 1px solid var(--line);
  color: var(--text);
  font-size: 12px;
  white-space: pre-wrap;
}
.empty {
  padding: 16px;
  color: var(--muted);
}
.empty.compact {
  padding: 8px 4px;
  font-size: 12px;
}
@media (max-width: 1320px) {
  .selection-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}
@media (max-width: 1120px) {
  .selection-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
@media (max-width: 860px) {
  .topbar {
    grid-template-columns: 1fr;
    align-items: stretch;
  }
  .type-tabs { padding: 4px 0 0; }
  .layout { grid-template-columns: 1fr; }
  .rail {
    display: block;
    gap: 6px;
    overflow-x: auto;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }
  .project-entry {
    display: inline-flex;
    min-width: 180px;
    vertical-align: top;
  }
  .project-entry span,
  .project-entry small {
    display: block;
  }
  .project-nav h2 {
    display: inline-flex;
    align-items: center;
    min-height: 36px;
    margin-right: 8px;
  }
  .list-pane { border-right: 0; border-bottom: 1px solid var(--line); }
  .item-list { max-height: 240px; }
  .selection-summary-row {
    align-items: stretch;
    flex-direction: column;
  }
  .selection-summary-controls {
    display: grid;
    grid-template-columns: 1fr;
  }
  .selection-summary-controls .filter-multiselect {
    width: 100%;
  }
  .selection-bottom-actions {
    align-items: stretch;
  }
  .selection-action-buttons {
    width: 100%;
  }
  .selection-bottom-actions .button {
    flex: 1;
  }
  .source-mode-form {
    margin-left: 0;
  }
  .selection-grid {
    grid-template-columns: 1fr;
  }
  .pagination-footer {
    grid-template-columns: 1fr;
  }
  .pagination {
    grid-column: auto;
  }
  .pagination-footer .selection-summary {
    justify-self: center;
    text-align: center;
  }
  .edit-form { grid-template-columns: 1fr; }
  .body-section-head { grid-template-columns: 1fr; }
  .body-template-row { grid-template-columns: 1fr; }
  .body-template-row button { width: 100%; }
  .body-section-actions { align-items: stretch; flex-direction: column; }
  .body-section-actions select { width: 100%; }
  .body-section-remove,
  .body-section-move,
  .body-section-preview-toggle,
  .body-section-collapse { width: 100%; }
  .template-section-head { grid-template-columns: 1fr; }
  .template-section-actions { align-items: stretch; flex-direction: column; }
  .template-section-move,
  .template-section-remove { width: 100%; }
  .extra-field-row { grid-template-columns: 1fr; }
  .extra-field-remove { width: 100%; }
  .list-field-row { grid-template-columns: 1fr; }
  .list-field-remove { width: 100%; }
  .mapping-field-row { grid-template-columns: 1fr; }
  .mapping-field-remove { width: 100%; }
  .harness-form-grid,
  .harness-form-grid.compact { grid-template-columns: 1fr; }
  .editor.full { grid-column: auto; }
}
"""
