#!/usr/bin/env python3
"""
Build harness-specific files from universal source definitions.

Supports all content types: agents, skills, rules, workflows, mcp, hooks.
Resolves per-harness fields using the priority chain:
  {harness}_{field} > multi-prefix ({h1}_{h2}_{field}) > global_{field} > {field}

Multi-prefix example:
  codex_copilot_description → applies to both codex and copilot harnesses

Usage:
    python3 build.py <source_dir> --type agents [--harness copilot,claude,codex,gemini]
    python3 build.py <source_dir> --type skills [--harness copilot,claude,codex,gemini]
    python3 build.py <source_dir> --type mcp    [--harness copilot,claude,codex,gemini]
"""

import os
import sys
import re
import json
import argparse
import shutil
import tempfile
from pathlib import Path
from configparser import ConfigParser

# ── Harness definitions ──────────────────────────────────────────

ALL_HARNESSES = ["copilot", "claude", "codex", "gemini"]
HARNESS_SET = set(ALL_HARNESSES)

# Per-harness field schemas for AGENTS (strict whitelist)
AGENT_SCHEMAS = {
    "copilot": ["name", "description", "model", "reasoning_effort"],
    "claude": ["name", "description", "model", "effort"],
    "codex": [
        "name", "description", "model",
        "model_reasoning_effort", "sandbox_mode",
        "mcp_servers", "nickname_candidates",
        "developer_instructions",
    ],
    "gemini": ["name", "description", "model", "thinkingLevel"],
}

# Per-harness field schemas for SKILLS (what goes in SKILL.md frontmatter)
SKILL_SCHEMAS = {
    "copilot": ["name", "description", "model"],
    "claude": ["name", "description", "model"],
    "codex": ["name", "description", "model"],
    "gemini": ["name", "description", "model"],
}

# Per-harness field schemas for RULES
RULE_SCHEMAS = {
    "copilot": ["name", "description", "globs", "alwaysApply"],
    "claude": ["name", "description", "globs", "alwaysApply"],
    "codex": ["name", "description", "globs", "alwaysApply"],
    "gemini": ["name", "description", "globs", "alwaysApply"],
}

# Per-harness field schemas for WORKFLOWS
WORKFLOW_SCHEMAS = {
    "copilot": ["name", "description", "model"],
    "claude": ["name", "description", "model"],
    "codex": ["name", "description", "model"],
    "gemini": ["name", "description", "model"],
}

# MCP: all fields pass through (no schema restriction) minus display/override fields
# Hooks: pass through as-is (no build transform)

# Fields that are display-only (never exported to any harness)
DISPLAY_FIELDS = {"color", "emoji", "vibe"}

OMIT_SENTINEL = "__omit__"

# Default model tiers that get resolved from defaults.conf
DEFAULT_TIERS = {"default", "default-small", "default-large"}

# Content types that use schema-based filtering
SCHEMA_MAP = {
    "agents": AGENT_SCHEMAS,
    "skills": SKILL_SCHEMAS,
    "rules": RULE_SCHEMAS,
    "workflows": WORKFLOW_SCHEMAS,
}


# ── Defaults loading ────────────────────────────────────────────

def load_defaults(defaults_path: Path | None) -> dict:
    """
    Load model defaults from an INI-style config file.

    Returns a nested dict:
      {harness: {tier: {"model": str, extra_field: str, ...}}}

    Format:
      [harness]
      tier = model-name
      tier.field = value  (additional fields set when that tier is used)
    """
    if not defaults_path or not defaults_path.exists():
        return {}

    config = ConfigParser()
    config.optionxform = str  # Preserve case in keys (e.g., thinkingLevel)
    config.read(str(defaults_path))

    defaults = {}
    for section in config.sections():
        harness = section.lower()
        if harness not in HARNESS_SET:
            continue
        defaults[harness] = {}
        for key, value in config.items(section):
            if "." in key:
                # tier.field = value → extra field for that tier
                tier, field = key.split(".", 1)
                if tier not in defaults[harness]:
                    defaults[harness][tier] = {}
                defaults[harness][tier][field] = value
            else:
                # tier = model-name
                if key not in defaults[harness]:
                    defaults[harness][key] = {}
                defaults[harness][key]["model"] = value

    return defaults


def resolve_defaults(resolved: dict, harness: str, defaults: dict) -> dict:
    """
    Replace default tier tokens in resolved fields with harness-specific values.

    If model value is 'default', 'default-small', or 'default-large':
      1. Replace model with harness-specific model from defaults
      2. Inject any additional fields defined for that tier (e.g., model_reasoning_effort)
         but only if not already explicitly set in the resolved dict.
    """
    if not defaults or harness not in defaults:
        return resolved

    harness_defaults = defaults[harness]
    model_val = resolved.get("model")

    if not isinstance(model_val, str) or model_val not in DEFAULT_TIERS:
        return resolved

    tier = model_val
    if tier not in harness_defaults:
        return resolved

    tier_config = harness_defaults[tier]
    result = dict(resolved)

    # Replace model with actual model name
    if "model" in tier_config:
        result["model"] = tier_config["model"]

    # Inject additional tier fields (only if not explicitly set)
    for field, value in tier_config.items():
        if field == "model":
            continue
        if field not in result:
            result[field] = value

    return result


# ── Frontmatter parsing ─────────────────────────────────────────

def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter and body from content."""
    if not content.startswith("---"):
        return {}, content

    end = content.find("\n---", 3)
    if end == -1:
        return {}, content

    fm_text = content[4:end]  # Skip opening ---\n
    body = content[end + 4:]  # Skip closing ---\n
    if body.startswith("\n"):
        body = body[1:]

    fields = {}
    lines = fm_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_.]*)\s*:\s*(.*)$", stripped)
        if match:
            key = match.group(1)
            value = match.group(2).strip()

            # Check for YAML block collection (key: with no value, followed by indented items)
            if not value:
                # Peek ahead to determine list vs map vs empty
                list_items = []
                map_items = {}
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    # Stop at non-indented lines (next top-level key or blank)
                    if next_line and not next_line[0].isspace():
                        break
                    next_stripped = next_line.strip()
                    if not next_stripped or next_stripped.startswith("#"):
                        j += 1
                        continue
                    list_match = re.match(r"^\s+-\s+(.+)$", next_line)
                    map_match = re.match(r"^\s+([a-zA-Z_][a-zA-Z0-9_.-]*)\s*:\s*(.+)$", next_line)
                    if list_match:
                        list_items.append(list_match.group(1).strip().strip("\"'"))
                        j += 1
                    elif map_match:
                        mk = map_match.group(1).strip()
                        mv = map_match.group(2).strip().strip("\"'")
                        map_items[mk] = mv
                        j += 1
                    else:
                        break
                if list_items:
                    fields[key] = list_items
                    i = j
                    continue
                elif map_items:
                    fields[key] = map_items
                    i = j
                    continue
                # Empty value, not a list or map
                fields[key] = ""
                i += 1
                continue

            # Handle quoted strings
            if (value.startswith('"') and value.endswith('"')) or \
               (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            # Handle inline YAML arrays: [item1, item2]
            elif value.startswith("[") and value.endswith("]"):
                items = [v.strip().strip("\"'") for v in value[1:-1].split(",")]
                value = items
            # Handle booleans
            if value == "true":
                value = True
            elif value == "false":
                value = False
            fields[key] = value
        i += 1

    return fields, body


# ── Multi-prefix field resolution ────────────────────────────────

def parse_key_prefix(key: str) -> tuple[set[str], str]:
    """
    Parse a frontmatter key into (target_harnesses, field_name).

    Uses greedy left-to-right matching of known harness names.
    Examples:
      "codex_copilot_description" → ({"codex","copilot"}, "description")
      "codex_model_reasoning_effort" → ({"codex"}, "model_reasoning_effort")
      "global_model" → ({"global"}, "model")
      "description" → (set(), "description")
    """
    parts = key.split("_")
    harnesses = set()
    i = 0

    while i < len(parts):
        segment = parts[i]
        if segment in HARNESS_SET or segment == "global":
            harnesses.add(segment)
            i += 1
        else:
            break

    if i == 0:
        return set(), key
    if i >= len(parts):
        # Entire key is harness names — treat as field name (no valid field)
        return set(), key

    field_name = "_".join(parts[i:])
    return harnesses, field_name


def resolve_field(fields: dict, harness: str, field_name: str) -> object:
    """
    Resolve a field value for a specific harness.

    Priority:
      1. Single harness match: {harness}_{field}
      2. Multi-prefix match containing this harness: {h1}_{h2}_{field}
      3. global_{field}
      4. {field} (base)

    Returns None if field should not be included.
    """
    # 1. Single harness exact match
    single_key = f"{harness}_{field_name}"
    if single_key in fields:
        val = fields[single_key]
        if val == OMIT_SENTINEL:
            return None
        return val

    # 2. Multi-prefix matches (keys with 2+ harness names that include this one)
    multi_matches = []
    for key, val in fields.items():
        targets, fname = parse_key_prefix(key)
        if fname == field_name and harness in targets and len(targets) >= 2 and "global" not in targets:
            multi_matches.append((len(targets), key, val))

    if multi_matches:
        # Prefer more specific (fewer targets = more specific)
        multi_matches.sort(key=lambda x: x[0])
        val = multi_matches[0][2]
        if val == OMIT_SENTINEL:
            return None
        return val

    # 3. Global override
    global_key = f"global_{field_name}"
    if global_key in fields:
        val = fields[global_key]
        if val == OMIT_SENTINEL:
            return None
        return val

    # 4. Base field
    if field_name in fields:
        return fields[field_name]

    return None


def is_override_key(key: str) -> bool:
    """Check if a key is a harness/global override (should be stripped from output)."""
    targets, _ = parse_key_prefix(key)
    return len(targets) > 0


# ── Output serialization ─────────────────────────────────────────

def build_frontmatter(resolved: dict) -> str:
    """Serialize resolved fields back to YAML frontmatter."""
    lines = ["---"]
    for key, value in resolved.items():
        if isinstance(value, list):
            lines.append(f"{key}: [{', '.join(str(v) for v in value)}]")
        elif isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        else:
            sv = str(value)
            if any(c in sv for c in ":#{}[]|>&*!%@`"):
                lines.append(f'{key}: "{sv}"')
            else:
                lines.append(f"{key}: {sv}")
    lines.append("---")
    return "\n".join(lines)


# ── Content type builders ────────────────────────────────────────

def build_md_file(fields: dict, body: str, harness: str, schema: list[str] | None, defaults: dict = None) -> str | None:
    """
    Build a harness-specific .md file.

    If schema is provided, only whitelisted fields are included.
    If schema is None, all non-display/non-override fields pass through.
    Defaults resolution replaces tier tokens (default/default-small/default-large)
    with harness-specific model values.
    """
    resolved = {}

    if schema:
        # Schema-based: only include whitelisted fields
        for field_name in schema:
            value = resolve_field(fields, harness, field_name)
            if value is not None:
                resolved[field_name] = value
    else:
        # Passthrough: include all base fields, resolve overrides
        base_fields = {k for k in fields.keys() if not is_override_key(k) and k not in DISPLAY_FIELDS}
        for field_name in base_fields:
            value = resolve_field(fields, harness, field_name)
            if value is not None:
                resolved[field_name] = value

    if not resolved and not body.strip():
        return None

    # Apply defaults resolution (replaces tier tokens with actual model names)
    if defaults:
        resolved = resolve_defaults(resolved, harness, defaults)

    if resolved:
        frontmatter = build_frontmatter(resolved)
        return f"{frontmatter}\n\n{body}"
    else:
        return body


def build_json_file(content: str, harness: str) -> str | None:
    """
    Build a harness-specific JSON file.

    If the source has YAML frontmatter (starts with ---), parse override fields
    and apply them to the JSON body. Otherwise, pass through as-is.
    """
    fields, body = parse_frontmatter(content)

    if not fields:
        # No frontmatter — pass through raw content
        return content.strip()

    # Body should be valid JSON
    body = body.strip()
    if not body:
        return None

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        # Can't parse body as JSON, pass through
        return content.strip()

    # Apply field overrides to the JSON object
    # Determine which keys in the JSON can be overridden
    for json_key in list(data.keys()):
        resolved = resolve_field(fields, harness, json_key)
        if resolved == OMIT_SENTINEL or resolved is None:
            # Check if this key should be omitted for this harness
            check_key = f"{harness}_{json_key}"
            if check_key in fields and fields[check_key] == OMIT_SENTINEL:
                del data[json_key]
        elif resolved is not None:
            data[json_key] = resolved

    # Also add fields from frontmatter that aren't overrides/display
    # and might be new keys for this harness
    for key in fields:
        if is_override_key(key) or key in DISPLAY_FIELDS:
            continue
        if key not in data:
            value = resolve_field(fields, harness, key)
            if value is not None and value != OMIT_SENTINEL:
                data[key] = value

    return json.dumps(data, indent=2)


def atomic_write(path: Path, content: str):
    """Write content atomically using temp file + rename."""
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        os.write(tmp_fd, content.encode("utf-8"))
        os.close(tmp_fd)
        os.replace(tmp_path, str(path))
    except Exception:
        os.close(tmp_fd)
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


# ── Type-specific build orchestration ────────────────────────────

def build_agents(source_dir: Path, harnesses: list[str], dry_run: bool = False, defaults: dict = None) -> dict:
    """Build harness-specific agent files."""
    stats = {h: 0 for h in harnesses}
    source_files = sorted(f for f in source_dir.glob("*.md") if f.is_file())

    for harness in harnesses:
        output_dir = source_dir / harness
        if not dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)
            for existing in output_dir.glob("*.md"):
                existing.unlink()

        schema = AGENT_SCHEMAS.get(harness, [])
        for source_file in source_files:
            content = source_file.read_text(encoding="utf-8")
            fields, body = parse_frontmatter(content)
            result = build_md_file(fields, body, harness, schema, defaults=defaults)
            if result is None:
                continue

            output_path = output_dir / source_file.name
            if dry_run:
                print(f"  [dry-run] {harness}/agents/{source_file.name}")
            else:
                atomic_write(output_path, result)
            stats[harness] += 1

    return stats


def build_skills(source_dir: Path, harnesses: list[str], dry_run: bool = False, defaults: dict = None) -> dict:
    """
    Build harness-specific skill directories.

    For each skill dir, transform SKILL.md (frontmatter resolution) and copy
    other files verbatim.
    """
    stats = {h: 0 for h in harnesses}
    # Skills are subdirectories (not harness subdirs)
    skill_dirs = sorted(
        d for d in source_dir.iterdir()
        if d.is_dir() and d.name not in HARNESS_SET and not d.name.startswith(".")
    )

    for harness in harnesses:
        harness_dir = source_dir / harness
        if not dry_run:
            harness_dir.mkdir(parents=True, exist_ok=True)
            # Clean existing built skills
            for existing in harness_dir.iterdir():
                if existing.is_dir():
                    shutil.rmtree(existing)
                else:
                    existing.unlink()

        schema = SKILL_SCHEMAS.get(harness)
        for skill_dir in skill_dirs:
            output_skill_dir = harness_dir / skill_dir.name
            if dry_run:
                print(f"  [dry-run] {harness}/skills/{skill_dir.name}/")
                stats[harness] += 1
                continue

            output_skill_dir.mkdir(parents=True, exist_ok=True)

            # Walk the skill directory
            for item in skill_dir.rglob("*"):
                if item.is_dir():
                    continue
                rel = item.relative_to(skill_dir)
                dest = output_skill_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)

                # Transform .md files with frontmatter
                if item.suffix == ".md":
                    content = item.read_text(encoding="utf-8")
                    fields, body = parse_frontmatter(content)
                    if fields:
                        result = build_md_file(fields, body, harness, schema, defaults=defaults)
                        if result:
                            atomic_write(dest, result)
                        else:
                            atomic_write(dest, body)
                    else:
                        # No frontmatter, copy as-is
                        shutil.copy2(item, dest)
                else:
                    # Non-md files: copy verbatim
                    shutil.copy2(item, dest)

            stats[harness] += 1

    return stats


def build_rules(source_dir: Path, harnesses: list[str], dry_run: bool = False, defaults: dict = None) -> dict:
    """Build harness-specific rule files."""
    stats = {h: 0 for h in harnesses}
    source_files = sorted(f for f in source_dir.glob("*.md") if f.is_file())

    for harness in harnesses:
        output_dir = source_dir / harness
        if not dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)
            for existing in output_dir.glob("*.md"):
                existing.unlink()

        schema = RULE_SCHEMAS.get(harness)
        for source_file in source_files:
            content = source_file.read_text(encoding="utf-8")
            fields, body = parse_frontmatter(content)

            if fields:
                result = build_md_file(fields, body, harness, schema, defaults=defaults)
                if result is None:
                    continue
            else:
                # No frontmatter = passthrough
                result = content

            output_path = output_dir / source_file.name
            if dry_run:
                print(f"  [dry-run] {harness}/rules/{source_file.name}")
            else:
                atomic_write(output_path, result)
            stats[harness] += 1

    return stats


def build_workflows(source_dir: Path, harnesses: list[str], dry_run: bool = False, defaults: dict = None) -> dict:
    """Build harness-specific workflow files."""
    stats = {h: 0 for h in harnesses}
    source_files = sorted(f for f in source_dir.glob("*.md") if f.is_file())

    for harness in harnesses:
        output_dir = source_dir / harness
        if not dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)
            for existing in output_dir.glob("*.md"):
                existing.unlink()

        schema = WORKFLOW_SCHEMAS.get(harness)
        for source_file in source_files:
            content = source_file.read_text(encoding="utf-8")
            fields, body = parse_frontmatter(content)

            if fields:
                result = build_md_file(fields, body, harness, schema, defaults=defaults)
                if result is None:
                    continue
            else:
                result = content

            output_path = output_dir / source_file.name
            if dry_run:
                print(f"  [dry-run] {harness}/workflows/{source_file.name}")
            else:
                atomic_write(output_path, result)
            stats[harness] += 1

    return stats


def build_mcp_entry(fields: dict, harness: str) -> dict | None:
    """
    Build a harness-specific MCP server config dict from resolved fields.

    Each harness needs a slightly different JSON structure:
      - copilot/claude/gemini: {"type": ..., "url": ...} or {"command": ..., "args": ...}
      - codex: {"transport": "stdio|http", "url"|"command": ..., ...}
    """
    # Resolve all non-display, non-override fields
    resolved = {}
    base_fields = {k for k in fields.keys() if not is_override_key(k) and k not in DISPLAY_FIELDS}
    for field_name in base_fields:
        value = resolve_field(fields, harness, field_name)
        if value is not None and value != OMIT_SENTINEL:
            resolved[field_name] = value

    if not resolved:
        return None

    transport = resolved.pop("transport", "http")

    if harness == "codex":
        return _mcp_for_codex(resolved, transport)
    elif harness == "gemini":
        return _mcp_for_gemini(resolved, transport)
    else:
        # copilot and claude use the same format
        return _mcp_for_copilot(resolved, transport)


def _mcp_for_copilot(resolved: dict, transport: str) -> dict:
    """Copilot/Claude MCP format: {type, url} or {command, args}."""
    out = {}
    if transport == "stdio":
        if "command" in resolved:
            out["command"] = resolved.pop("command")
        if "args" in resolved:
            out["args"] = resolved.pop("args")
        if "env" in resolved:
            out["env"] = resolved.pop("env")
    else:
        out["type"] = transport
        if "url" in resolved:
            out["url"] = resolved.pop("url")

    # Pass through remaining fields (description, tools, headers, etc.)
    resolved.pop("name", None)
    for k, v in resolved.items():
        out[k] = v
    return out


def _mcp_for_codex(resolved: dict, transport: str) -> dict:
    """Codex MCP format: TOML-style but output as JSON for individual files."""
    out = {}
    if transport == "stdio":
        out["transport"] = "stdio"
        if "command" in resolved:
            out["command"] = resolved.pop("command")
        if "args" in resolved:
            out["args"] = resolved.pop("args")
        if "env" in resolved:
            out["env"] = resolved.pop("env")
    else:
        out["transport"] = "http"
        if "url" in resolved:
            out["url"] = resolved.pop("url")

    # Pass through remaining fields
    resolved.pop("name", None)
    for k, v in resolved.items():
        if k in ("type",):
            continue  # codex doesn't use "type", it uses "transport"
        out[k] = v
    return out


def _mcp_for_gemini(resolved: dict, transport: str) -> dict:
    """Gemini MCP format: {command, args} for stdio, {url} for SSE, {httpUrl} for HTTP."""
    out = {}
    if transport == "stdio":
        if "command" in resolved:
            out["command"] = resolved.pop("command")
        if "args" in resolved:
            out["args"] = resolved.pop("args")
        if "env" in resolved:
            out["env"] = resolved.pop("env")
    elif transport == "sse":
        if "url" in resolved:
            out["url"] = resolved.pop("url")
    else:
        # http → Gemini uses httpUrl
        if "url" in resolved:
            out["httpUrl"] = resolved.pop("url")

    # Pass through remaining fields
    resolved.pop("name", None)
    for k, v in resolved.items():
        if k in ("type",):
            continue
        out[k] = v
    return out


def build_mcp(source_dir: Path, harnesses: list[str], dry_run: bool = False, defaults: dict = None) -> dict:
    """
    Build harness-specific MCP configs from universal .md source files.

    Source files use YAML frontmatter to define server config (transport, url,
    command, args, etc.) with optional harness-prefix overrides.
    Outputs individual JSON files per harness with harness-appropriate structure.
    """
    stats = {h: 0 for h in harnesses}
    source_files = sorted(
        f for f in source_dir.iterdir()
        if f.is_file() and f.suffix in (".json", ".md") and f.name not in HARNESS_SET
    )

    for harness in harnesses:
        output_dir = source_dir / harness
        if not dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)
            for existing in output_dir.glob("*"):
                if existing.is_file():
                    existing.unlink()

        for source_file in source_files:
            content = source_file.read_text(encoding="utf-8")
            out_name = source_file.stem + ".json"

            if source_file.suffix == ".md" or content.startswith("---"):
                fields, body = parse_frontmatter(content)
                if fields:
                    entry = build_mcp_entry(fields, harness)
                    if entry is None:
                        continue
                    result = json.dumps(entry, indent=2)
                else:
                    # No frontmatter in .md — skip
                    continue
            elif source_file.suffix == ".json":
                # Plain JSON passthrough
                result = content.strip()
                out_name = source_file.name
            else:
                continue

            output_path = output_dir / out_name
            if dry_run:
                print(f"  [dry-run] {harness}/mcp/{out_name}")
            else:
                atomic_write(output_path, result)
            stats[harness] += 1

    return stats


def build_hooks(source_dir: Path, harnesses: list[str], dry_run: bool = False, defaults: dict = None) -> dict:
    """
    Build harness-specific hooks.

    Hooks are shell scripts. If they contain comment-based frontmatter
    (# --- / # key: value / # ---), it's processed. Otherwise pass through.
    """
    stats = {h: 0 for h in harnesses}
    source_files = sorted(
        f for f in source_dir.iterdir()
        if f.is_file() and not f.name.startswith(".") and f.name not in HARNESS_SET
    )

    for harness in harnesses:
        output_dir = source_dir / harness
        if not dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)
            for existing in output_dir.glob("*"):
                if existing.is_file():
                    existing.unlink()

        for source_file in source_files:
            content = source_file.read_text(encoding="utf-8")

            # Check for comment-based frontmatter: # ---
            if content.startswith("# ---"):
                # Parse comment frontmatter
                lines = content.split("\n")
                fm_lines = []
                body_start = 0
                in_fm = False
                for idx, line in enumerate(lines):
                    if idx == 0 and line.strip() == "# ---":
                        in_fm = True
                        continue
                    if in_fm:
                        if line.strip() == "# ---":
                            body_start = idx + 1
                            break
                        # Strip leading "# " from frontmatter lines
                        fm_lines.append(re.sub(r"^#\s?", "", line))

                fm_content = "---\n" + "\n".join(fm_lines) + "\n---\n"
                fields, _ = parse_frontmatter(fm_content)
                body = "\n".join(lines[body_start:])

                # Check if this hook should be omitted for this harness
                harness_include = resolve_field(fields, harness, "include")
                if harness_include is False or harness_include == "false":
                    continue

                result = body
            else:
                result = content

            output_path = output_dir / source_file.name
            if dry_run:
                print(f"  [dry-run] {harness}/hooks/{source_file.name}")
            else:
                atomic_write(output_path, result)
                # Preserve executable permission
                if os.access(source_file, os.X_OK):
                    os.chmod(output_path, 0o755)
            stats[harness] += 1

    return stats


# ── Main ─────────────────────────────────────────────────────────

BUILDERS = {
    "agents": build_agents,
    "skills": build_skills,
    "rules": build_rules,
    "workflows": build_workflows,
    "mcp": build_mcp,
    "hooks": build_hooks,
}


def main():
    parser = argparse.ArgumentParser(description="Build harness-specific files from universal sources")
    parser.add_argument("source_dir", help="Path to source directory for the content type")
    parser.add_argument(
        "--type", "-t",
        required=True,
        choices=list(BUILDERS.keys()),
        help="Content type to build"
    )
    parser.add_argument(
        "--harness",
        default=",".join(ALL_HARNESSES),
        help=f"Comma-separated harnesses (default: all). Options: {','.join(ALL_HARNESSES)}"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress output")
    args = parser.parse_args()

    source_dir = Path(args.source_dir).resolve()
    if not source_dir.is_dir():
        # For symlinks, resolve and check
        if source_dir.is_symlink():
            source_dir = source_dir.resolve()
        if not source_dir.is_dir():
            print(f"Error: {source_dir} is not a directory", file=sys.stderr)
            sys.exit(1)

    harnesses = [h.strip() for h in args.harness.split(",")]
    for h in harnesses:
        if h not in ALL_HARNESSES:
            print(f"Error: unknown harness '{h}'. Options: {', '.join(ALL_HARNESSES)}", file=sys.stderr)
            sys.exit(1)

    builder = BUILDERS[args.type]

    # Auto-discover defaults.conf in the parent of source_dir (~/.wdm-agents/)
    defaults_path = source_dir.parent / "defaults.conf"
    defaults = load_defaults(defaults_path) if defaults_path.exists() else {}
    if defaults and not args.quiet:
        print(f"Loaded model defaults from {defaults_path}")

    stats = builder(source_dir, harnesses, dry_run=args.dry_run, defaults=defaults)

    if not args.quiet:
        label = args.type
        for harness, count in stats.items():
            print(f"{harness}: {count} {label} built")


if __name__ == "__main__":
    main()
