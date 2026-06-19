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

import yaml

from .agent_variants import agent_variants_from_fields, materialize_agent_variant, variant_output_name
from .utils import ALL_HARNESSES, ALL_HARNESS_DEFINITIONS, CONFIGURED_HARNESSES, HARNESS_SET, CONTENT_ROOT, CORE_SOURCE_DIR, MCP_SOURCE_EXTENSIONS, content_source_dir

# ── Harness definitions ──────────────────────────────────────────

# Per-harness field schemas for AGENTS (strict whitelist).
# Sources of truth (verified May 2026):
#   - Claude Code:   https://docs.claude.com/claude-code/ (subagents reference)
#   - Copilot CLI:   https://docs.github.com/en/copilot/reference/custom-agents-configuration
#   - Codex CLI:     https://developers.openai.com/codex/subagents (TOML, not MD!)
#   - Gemini CLI:    https://github.com/google-gemini/gemini-cli/blob/main/docs/core/subagents.md
AGENT_SCHEMAS = {
    "copilot": [
        "name", "description", "model", "tools",
        "mcp-servers", "user-invocable", "disable-model-invocation",
        "target", "metadata",
    ],
    "claude": [
        "name", "description", "model", "effort",
        "tools", "disallowedTools", "permissionMode", "skills", "color",
    ],
    "codex": [
        # NOTE: emitted as TOML, not Markdown frontmatter (see build_codex_agent_toml).
        "name", "description", "model",
        "model_reasoning_effort", "sandbox_mode",
        "skills", "mcp_servers", "nickname_candidates",
        "developer_instructions",
    ],
    "gemini": [
        "name", "description", "model",
        "kind", "tools", "temperature", "max_turns",
        "thinkingLevel", "thinkingBudget", "thinkingConfig",
    ],
}

# Per-harness field schemas for SKILLS (what goes in SKILL.md frontmatter).
# Copilot CLI's SKILL.md frontmatter is intentionally minimal (no model field).
SKILL_SCHEMAS = {
    "copilot": ["name", "description", "license", "allowed-tools"],
    "claude": [
        "name", "description", "allowed-tools", "model", "effort",
        "argument-hint", "disable-model-invocation",
    ],
    "codex": ["name", "description"],
    "gemini": ["name", "description"],
}

# Per-harness field schemas for RULES.
# Most harnesses treat rules as plain markdown; `globs`/`alwaysApply` are
# Claude-style frontmatter and ignored elsewhere — kept as a lowest-common
# superset since unknown fields pass through harmlessly in YAML.
RULE_SCHEMAS = {
    "copilot": ["name", "description", "applyTo"],
    "claude": ["name", "description", "paths", "globs", "alwaysApply"],
    "codex": ["name", "description"],
    "gemini": ["name", "description"],
}

# Per-harness field schemas for WORKFLOWS.
# Claude treats workflow .md files as slash commands.
WORKFLOW_SCHEMAS = {
    "copilot": ["name", "description"],
    "claude": ["name", "description", "model", "argument-hint", "allowed-tools"],
    "codex": ["name", "description"],
    "gemini": ["name", "description"],
}

for harness_name, harness_def in ALL_HARNESS_DEFINITIONS.items():
    schemas = harness_def.get("schemas") if isinstance(harness_def, dict) else None
    if not isinstance(schemas, dict):
        continue
    if isinstance(schemas.get("agents"), list):
        AGENT_SCHEMAS[harness_name] = schemas["agents"]
    if isinstance(schemas.get("skills"), list):
        SKILL_SCHEMAS[harness_name] = schemas["skills"]
    if isinstance(schemas.get("rules"), list):
        RULE_SCHEMAS[harness_name] = schemas["rules"]
    if isinstance(schemas.get("workflows"), list):
        WORKFLOW_SCHEMAS[harness_name] = schemas["workflows"]

# MCP: all fields pass through (no schema restriction) minus display/override fields
# Hooks: pass through as-is (no build transform)

# Fields that are display-only (never exported to any harness)
DISPLAY_FIELDS = {"color", "emoji", "vibe"}

OMIT_SENTINEL = "__omit__"

# Default model tiers that get resolved from defaults.conf.
# default-small/default-large are legacy aliases kept for existing source files.
DEFAULT_TIER_ALIASES = {
    "default-small": "default-low",
    "default-large": "default-high",
}
DEFAULT_TIERS = {"default-low", "default", "default-high", *DEFAULT_TIER_ALIASES}

# Content types that use schema-based filtering
SCHEMA_MAP = {
    "agents": AGENT_SCHEMAS,
    "skills": SKILL_SCHEMAS,
    "rules": RULE_SCHEMAS,
    "workflows": WORKFLOW_SCHEMAS,
}


def field_mappings_for(harness: str, content_type: str) -> dict[str, list[str]]:
    """
    Return canonical WDM field -> harness output field mappings.

    Harness configs own this contract. Values may be a string or list of
    strings so one canonical field can feed multiple harness-native names.
    """
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
            outputs = [output_fields]
        elif isinstance(output_fields, list):
            outputs = output_fields
        else:
            continue
        values = [str(item).strip() for item in outputs if str(item).strip()]
        if values:
            normalized[source] = values
    return normalized


def mapped_source_fields(harness: str, content_type: str, output_field: str) -> list[str]:
    sources = []
    for source_field, output_fields in field_mappings_for(harness, content_type).items():
        if output_field in output_fields:
            sources.append(source_field)
    return sources


# ── Defaults loading ────────────────────────────────────────────

def canonical_default_tier(tier: str) -> str:
    return DEFAULT_TIER_ALIASES.get(tier, tier)


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
                tier = canonical_default_tier(tier)
                if tier not in defaults[harness]:
                    defaults[harness][tier] = {}
                defaults[harness][tier][field] = value
            else:
                # tier = model-name
                key = canonical_default_tier(key)
                if key not in defaults[harness]:
                    defaults[harness][key] = {}
                defaults[harness][key]["model"] = value

    return defaults


def resolve_defaults(resolved: dict, harness: str, defaults: dict) -> dict:
    """
    Replace default tier tokens in resolved fields with harness-specific values.

    If model value is 'default-low', 'default', or 'default-high':
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

    tier = canonical_default_tier(model_val)
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


def gemini_wrap_thinking(resolved: dict) -> dict:
    """
    Gemini CLI does NOT support a flat `thinkingLevel` field. The real config
    shape is `thinkingConfig: { thinkingBudget: <int> }`. Accept flat
    `thinkingBudget` / legacy `thinkingLevel` in source frontmatter and wrap.
    """
    if "thinkingBudget" in resolved:
        budget = resolved.pop("thinkingBudget")
        try:
            budget = int(budget)
        except (TypeError, ValueError):
            pass
        existing = resolved.get("thinkingConfig")
        if isinstance(existing, dict):
            existing.setdefault("thinkingBudget", budget)
        else:
            resolved["thinkingConfig"] = {"thinkingBudget": budget}
    if "thinkingLevel" in resolved:
        # Translate legacy LOW/MEDIUM/HIGH tokens to coarse budget hints.
        level = str(resolved.pop("thinkingLevel")).strip().upper()
        budget_map = {"LOW": 1024, "MEDIUM": 4096, "HIGH": 16384}
        if level in budget_map and "thinkingConfig" not in resolved:
            resolved["thinkingConfig"] = {"thinkingBudget": budget_map[level]}
    return resolved


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

    try:
        loaded = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        return {}, body
    if not isinstance(loaded, dict):
        return {}, body
    return loaded, body


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


def resolve_output_field(fields: dict, harness: str, content_type: str, output_field: str, body: str = "") -> object:
    """
    Resolve a harness-native output field from canonical WDM source fields.

    Explicit harness-native overrides remain supported for migration and
    exceptional cases, but the preferred path is:
      canonical field -> harness field_mappings -> output field.
    """
    value = resolve_field(fields, harness, output_field)
    if value is not None:
        return value
    for source_field in mapped_source_fields(harness, content_type, output_field):
        if source_field == "body":
            body_value = body.strip()
            if body_value:
                return body_value
            continue
        value = resolve_field(fields, harness, source_field)
        if value is not None:
            return value
    return None


def body_is_mapped(harness: str, content_type: str, schema: list[str] | None) -> bool:
    if not schema:
        return False
    for output_field in schema:
        if "body" in mapped_source_fields(harness, content_type, output_field):
            return True
    return False


def is_override_key(key: str) -> bool:
    """Check if a key is a harness/global override (should be stripped from output)."""
    targets, _ = parse_key_prefix(key)
    return len(targets) > 0


# ── Output serialization ─────────────────────────────────────────

def dump_yaml_mapping(value: dict) -> str:
    dumped = yaml.safe_dump(value, sort_keys=False, allow_unicode=False, default_flow_style=False).strip()
    return re.sub(r"\n\.\.\.\s*$", "", dumped)


def build_frontmatter(resolved: dict) -> str:
    """Serialize resolved fields back to YAML frontmatter."""
    return f"---\n{dump_yaml_mapping(resolved)}\n---"


# ── Content type builders ────────────────────────────────────────

def build_md_file(fields: dict, body: str, harness: str, schema: list[str] | None, defaults: dict = None, content_type: str = "") -> str | None:
    """
    Build a harness-specific .md file.

    If schema is provided, only whitelisted fields are included.
    If schema is None, all non-display/non-override fields pass through.
    Defaults resolution replaces tier tokens (default-low/default/default-high)
    with harness-specific model values.
    """
    resolved = {}

    if schema:
        # Schema-based: only include whitelisted fields
        for field_name in schema:
            value = resolve_output_field(fields, harness, content_type, field_name, body)
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

    # Gemini: wrap flat thinkingBudget / thinkingLevel into thinkingConfig
    if harness == "gemini":
        resolved = gemini_wrap_thinking(resolved)

    output_body = "" if body_is_mapped(harness, content_type, schema) else body

    if resolved:
        frontmatter = build_frontmatter(resolved)
        return f"{frontmatter}\n\n{output_body}"
    else:
        return output_body


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

def build_output_root(source_dir: Path) -> Path:
    """Generated harness folders are siblings of `core/`, not children of it."""
    return source_dir.parent if source_dir.name == CORE_SOURCE_DIR else source_dir


def output_extension(harness: str, content_type: str, default: str) -> str:
    definition = ALL_HARNESS_DEFINITIONS.get(harness, {})
    outputs = definition.get("outputs", {}) if isinstance(definition, dict) else {}
    output = outputs.get(content_type, {}) if isinstance(outputs, dict) else {}
    if isinstance(output, dict) and output.get("extension"):
        return str(output["extension"])
    return default

def _toml_escape(value: str) -> str:
    """Escape a string for TOML basic-string output."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _toml_value(value) -> str:
    """Serialize a Python value as a TOML scalar/array."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        # Inline table
        parts = [f"{k} = {_toml_value(v)}" for k, v in value.items()]
        return "{ " + ", ".join(parts) + " }"
    sv = str(value)
    if "\n" in sv:
        # Multi-line basic string
        return '"""\n' + sv.replace("\\", "\\\\").replace('"""', '\\"\\"\\"') + '\n"""'
    return '"' + _toml_escape(sv) + '"'


def _codex_skill_config(value):
    """
    Convert WDM's portable agent skill list to Codex's SkillsConfig shape.

    Codex agent role files parse `skills` as a config table:
      skills = { config = [{ name = "skill-name", enabled = true }] }
    """
    if isinstance(value, dict):
        return value
    if not isinstance(value, list):
        return value

    entries = []
    for item in value:
        if isinstance(item, dict):
            entry = dict(item)
            entry.setdefault("enabled", True)
            entries.append(entry)
            continue
        name = str(item or "").strip()
        if name:
            entries.append({"name": name, "enabled": True})
    return {"config": entries} if entries else {"config": []}


def build_codex_agent_toml(fields: dict, body: str, defaults: dict = None, source_name: str = "") -> str | None:
    """
    Build a Codex `.toml` subagent file from universal source.

    Codex subagents live in ~/.codex/agents/ (or .codex/agents/) as standalone
    TOML files keyed by the `name` field. The markdown body becomes the
    `developer_instructions` multi-line string.
    """
    schema = AGENT_SCHEMAS["codex"]
    resolved = {}
    for field_name in schema:
        if field_name == "developer_instructions":
            continue  # filled from body below
        value = resolve_output_field(fields, "codex", "agents", field_name)
        if value is not None:
            resolved[field_name] = value

    if defaults:
        resolved = resolve_defaults(resolved, "codex", defaults)
    if "skills" in resolved:
        resolved["skills"] = _codex_skill_config(resolved["skills"])

    # The universal markdown body is Codex's developer_instructions field.
    # Do not let frontmatter create a second, divergent instruction source.
    instructions = body.strip()

    if not resolved.get("name") and not instructions:
        return None
    required = {
        "name": resolved.get("name"),
        "description": resolved.get("description"),
        "developer_instructions": instructions,
    }
    missing = [key for key, value in required.items() if not str(value or "").strip()]
    if missing:
        location = f" in {source_name}" if source_name else ""
        raise ValueError(
            "Codex custom agent files must define "
            f"{', '.join(missing)}{location}. "
            "OpenAI Codex requires standalone TOML agents with name, "
            "description, and developer_instructions."
        )

    lines = []
    # Preferred field ordering for readability
    preferred = [
        "name", "description", "model", "model_reasoning_effort",
        "sandbox_mode", "skills", "mcp_servers", "nickname_candidates",
    ]
    for key in preferred:
        if key in resolved:
            lines.append(f"{key} = {_toml_value(resolved[key])}")
    # Any remaining whitelisted fields not in preferred order
    for key, value in resolved.items():
        if key in preferred:
            continue
        lines.append(f"{key} = {_toml_value(value)}")
    if instructions:
        lines.append(f"developer_instructions = {_toml_value(instructions)}")
    return "\n".join(lines) + "\n"


def build_agents(source_dir: Path, harnesses: list[str], dry_run: bool = False, defaults: dict = None) -> dict:
    """Build harness-specific agent files.

    Codex emits standalone `.toml` files; all other harnesses emit `.md` with
    YAML frontmatter.
    """
    stats = {h: 0 for h in harnesses}
    source_files = sorted(f for f in source_dir.glob("*.md") if f.is_file())
    output_root = build_output_root(source_dir)

    for harness in harnesses:
        output_dir = output_root / harness
        suffix = output_extension(harness, "agents", ".toml" if harness == "codex" else ".md")
        if not dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)
            for existing in list(output_dir.glob("*.md")) + list(output_dir.glob("*.toml")):
                existing.unlink()

        schema = AGENT_SCHEMAS.get(harness, [])
        for source_file in source_files:
            content = source_file.read_text(encoding="utf-8")
            fields, body = parse_frontmatter(content)
            base_name = str(fields.get("name") or source_file.stem).strip() or source_file.stem

            if harness == "codex":
                result = build_codex_agent_toml(fields, body, defaults=defaults, source_name=str(source_file))
            else:
                result = build_md_file(fields, body, harness, schema, defaults=defaults, content_type="agents")
            if result is None:
                continue

            output_name = source_file.stem + suffix
            output_path = output_dir / output_name
            if dry_run:
                print(f"  [dry-run] {harness}/agents/{output_name}")
            else:
                atomic_write(output_path, result)
            stats[harness] += 1

            for variant in agent_variants_from_fields(fields):
                variant_fields, variant_body = materialize_agent_variant(fields, body, variant, base_name)
                if harness == "codex":
                    variant_result = build_codex_agent_toml(
                        variant_fields,
                        variant_body,
                        defaults=defaults,
                        source_name=f"{source_file}#{variant_output_name(base_name, variant)}",
                    )
                else:
                    variant_result = build_md_file(
                        variant_fields,
                        variant_body,
                        harness,
                        schema,
                        defaults=defaults,
                        content_type="agents",
                    )
                if variant_result is None:
                    continue
                variant_output = output_dir / (variant_output_name(base_name, variant) + suffix)
                if dry_run:
                    print(f"  [dry-run] {harness}/agents/{variant_output.name}")
                else:
                    atomic_write(variant_output, variant_result)
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
    output_root = build_output_root(source_dir)

    for harness in harnesses:
        harness_dir = output_root / harness
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
                        result = build_md_file(fields, body, harness, schema, defaults=defaults, content_type="skills")
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
    output_root = build_output_root(source_dir)

    for harness in harnesses:
        output_dir = output_root / harness
        extension = output_extension(harness, "rules", ".md")
        if not dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)
            for existing in output_dir.glob(f"*{extension}"):
                existing.unlink()

        schema = RULE_SCHEMAS.get(harness)
        for source_file in source_files:
            content = source_file.read_text(encoding="utf-8")
            fields, body = parse_frontmatter(content)

            if fields:
                result = build_md_file(fields, body, harness, schema, defaults=defaults, content_type="rules")
                if result is None:
                    continue
            else:
                # No frontmatter = passthrough
                result = content

            output_name = source_file.stem + extension
            output_path = output_dir / output_name
            if dry_run:
                print(f"  [dry-run] {harness}/rules/{output_name}")
            else:
                atomic_write(output_path, result)
            stats[harness] += 1

    return stats


def build_workflows(source_dir: Path, harnesses: list[str], dry_run: bool = False, defaults: dict = None) -> dict:
    """Build harness-specific workflow files."""
    stats = {h: 0 for h in harnesses}
    source_files = sorted(f for f in source_dir.glob("*.md") if f.is_file())
    output_root = build_output_root(source_dir)

    for harness in harnesses:
        output_dir = output_root / harness
        extension = output_extension(harness, "workflows", ".md")
        if not dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)
            for existing in output_dir.glob(f"*{extension}"):
                existing.unlink()

        schema = WORKFLOW_SCHEMAS.get(harness)
        for source_file in source_files:
            content = source_file.read_text(encoding="utf-8")
            fields, body = parse_frontmatter(content)

            if fields:
                result = build_md_file(fields, body, harness, schema, defaults=defaults, content_type="workflows")
                if result is None:
                    continue
            else:
                result = content

            output_name = source_file.stem + extension
            output_path = output_dir / output_name
            if dry_run:
                print(f"  [dry-run] {harness}/workflows/{output_name}")
            else:
                atomic_write(output_path, result)
            stats[harness] += 1

    return stats


def build_mcp_entry(fields: dict, harness: str) -> dict | None:
    """
    Build a harness-specific MCP server config dict from resolved fields.

    Per-harness structure differences (verified May 2026):
      - Claude Code:    {"type": "http"|"sse"|"stdio", url|command|args|env|headers}
      - Copilot CLI:    {"type": "local"|"http"|"sse", command|args|env|tools|url|headers}
      - Codex CLI:      no `type`/`transport`; stdio inferred from `command`,
                        HTTP from `url`. Env-var list lives in `env_vars`.
      - Gemini CLI:     {command,args,env} | {url} (SSE) | {httpUrl} (HTTP)
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

    # `transport` is a source-side convenience; not all harnesses use it.
    transport = resolved.pop("transport", None)
    if transport is None:
        # Infer: stdio if a command is present, http otherwise.
        transport = "stdio" if "command" in resolved else "http"

    if harness == "codex":
        return _mcp_for_codex(resolved)
    if harness == "gemini":
        return _mcp_for_gemini(resolved, transport)
    if harness == "copilot":
        return _mcp_for_copilot(resolved, transport)
    return _mcp_for_claude(resolved, transport)


# Fields that belong to other harnesses' MCP schemas — never pass through.
_FOREIGN_MCP_FIELDS = {
    "env_vars", "bearer_token_env_var", "http_headers",
    "enabled_tools", "disabled_tools", "default_tools_approval_mode",
    "startup_timeout_sec", "tool_timeout_sec",
    "httpUrl",  # Gemini-only key; never emit for others
    "transport", "type",
}


def _passthrough_mcp(resolved: dict, out: dict, extra_allowed: set[str] = frozenset()) -> dict:
    """Copy remaining fields into `out`, dropping foreign-harness keys."""
    resolved.pop("name", None)
    for key, value in resolved.items():
        if key in _FOREIGN_MCP_FIELDS and key not in extra_allowed:
            continue
        out[key] = value
    return out


def _mcp_for_claude(resolved: dict, transport: str) -> dict:
    """Claude Code MCP format (placed in repo-root .mcp.json under mcpServers)."""
    out = {}
    if transport == "stdio":
        for k in ("command", "args", "env"):
            if k in resolved:
                out[k] = resolved.pop(k)
    else:
        out["type"] = transport
        if "url" in resolved:
            out["url"] = resolved.pop("url")
        if "headers" in resolved:
            out["headers"] = resolved.pop("headers")
    return _passthrough_mcp(resolved, out)


def _mcp_for_copilot(resolved: dict, transport: str) -> dict:
    """Copilot CLI MCP format (`~/.copilot/mcp-config.json`).

    `type` is one of `local` | `stdio` | `http` | `sse`. Docs use `local` as
    the canonical alias for stdio in Copilot CLI examples.
    """
    out = {}
    if transport == "stdio":
        out["type"] = "local"
        for k in ("command", "args", "env"):
            if k in resolved:
                out[k] = resolved.pop(k)
    else:
        out["type"] = transport
        if "url" in resolved:
            out["url"] = resolved.pop("url")
        if "headers" in resolved:
            out["headers"] = resolved.pop("headers")
    # Copilot allows a `tools` allowlist per server.
    return _passthrough_mcp(resolved, out, extra_allowed={"tools"})


def _mcp_for_codex(resolved: dict) -> dict:
    """Codex CLI MCP format (TOML `[mcp_servers.NAME]` block, see build_codex_mcp_toml).

    Codex infers transport from field presence and has no `type`/`transport`
    field. `env_vars` is a list of env-var NAMES to pass through; `env` is a
    map of name→value. We pass both through if provided.
    """
    out = {}
    if "command" in resolved:
        out["command"] = resolved.pop("command")
        for k in ("args", "env", "env_vars"):
            if k in resolved:
                out[k] = resolved.pop(k)
    elif "url" in resolved:
        out["url"] = resolved.pop("url")
        for k in ("bearer_token_env_var", "http_headers"):
            if k in resolved:
                out[k] = resolved.pop(k)
    # Common pass-through fields
    for k in (
        "enabled", "enabled_tools", "disabled_tools",
        "default_tools_approval_mode", "startup_timeout_sec",
        "tool_timeout_sec",
    ):
        if k in resolved:
            out[k] = resolved.pop(k)
    resolved.pop("name", None)
    resolved.pop("type", None)
    # Drop unknown Codex fields silently rather than emitting invalid TOML keys.
    return out


def _mcp_for_gemini(resolved: dict, transport: str) -> dict:
    """Gemini CLI MCP format (nested under `mcpServers` in settings.json)."""
    out = {}
    if transport == "stdio":
        for k in ("command", "args", "env", "cwd"):
            if k in resolved:
                out[k] = resolved.pop(k)
    elif transport == "sse":
        if "url" in resolved:
            out["url"] = resolved.pop("url")
        if "headers" in resolved:
            out["headers"] = resolved.pop("headers")
    else:
        # http → Gemini uses httpUrl
        if "url" in resolved:
            out["httpUrl"] = resolved.pop("url")
        if "headers" in resolved:
            out["headers"] = resolved.pop("headers")

    for k in ("timeout", "trust"):
        if k in resolved:
            out[k] = resolved.pop(k)

    # Drop foreign-harness fields like env_vars, bearer_token_env_var, etc.
    return _passthrough_mcp(resolved, out)


def build_codex_mcp_toml(name: str, entry: dict) -> str:
    """Render a Codex MCP entry as `[mcp_servers.NAME]` TOML block."""
    lines = [f"[mcp_servers.{name}]"]
    inline_env = entry.pop("env", None) if isinstance(entry.get("env"), dict) else None
    for key, value in entry.items():
        lines.append(f"{key} = {_toml_value(value)}")
    if inline_env:
        lines.append(f"[mcp_servers.{name}.env]")
        for k, v in inline_env.items():
            lines.append(f"{k} = {_toml_value(v)}")
    return "\n".join(lines) + "\n"


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
        if f.is_file() and f.suffix in MCP_SOURCE_EXTENSIONS and f.name not in HARNESS_SET
    )
    output_root = build_output_root(source_dir)

    for harness in harnesses:
        output_dir = output_root / harness
        if not dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)
            for existing in output_dir.glob("*"):
                if existing.is_file():
                    existing.unlink()

        for source_file in source_files:
            content = source_file.read_text(encoding="utf-8")
            server_name = source_file.stem
            # Codex emits TOML snippets; everyone else emits JSON.
            out_ext = output_extension(harness, "mcp", ".toml" if harness == "codex" else ".json")
            out_name = server_name + out_ext

            if source_file.suffix == ".md" or content.startswith("---"):
                fields, body = parse_frontmatter(content)
                if fields:
                    entry = build_mcp_entry(fields, harness)
                    if entry is None:
                        continue
                    # Honor an explicit `name` override; otherwise use filename stem.
                    name_override = resolve_field(fields, harness, "name")
                    final_name = str(name_override) if name_override else server_name
                    if harness == "codex":
                        result = build_codex_mcp_toml(final_name, entry)
                    else:
                        result = json.dumps(entry, indent=2)
                else:
                    # No frontmatter in .md — skip
                    continue
            elif source_file.suffix in {".yaml", ".yml"}:
                try:
                    fields = yaml.safe_load(content) or {}
                except yaml.YAMLError:
                    continue
                if not isinstance(fields, dict):
                    continue
                entry = build_mcp_entry(fields, harness)
                if entry is None:
                    continue
                name_override = resolve_field(fields, harness, "name")
                final_name = str(name_override) if name_override else server_name
                if harness == "codex":
                    result = build_codex_mcp_toml(final_name, entry)
                else:
                    result = json.dumps(entry, indent=2)
            elif source_file.suffix == ".json":
                if harness == "codex":
                    # Codex doesn't accept raw JSON — try to convert.
                    try:
                        data = json.loads(content)
                    except json.JSONDecodeError:
                        continue
                    result = build_codex_mcp_toml(server_name, data)
                else:
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
    output_root = build_output_root(source_dir)

    for harness in harnesses:
        output_dir = output_root / harness
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


def has_sources(content_type: str, source_dir: Path) -> bool:
    if not source_dir.exists():
        return False
    if content_type in {"agents", "rules", "workflows"}:
        return any(source_dir.glob("*.md"))
    if content_type == "skills":
        return any(child for child in source_dir.iterdir() if child.is_dir() and child.name not in HARNESS_SET and not child.name.startswith("."))
    if content_type == "mcp":
        return any(child for child in source_dir.iterdir() if child.is_file() and child.suffix in (".json", ".md"))
    if content_type == "hooks":
        return any(child for child in source_dir.iterdir() if child.is_file() and not child.name.startswith("."))
    return False


def defaults_path_for_source_dir(source_dir: Path) -> Path:
    """
    Locate defaults.conf for a managed source directory.

    Normal source dirs are shaped like CONTENT_ROOT/agents/core, so the defaults
    file is two levels up at CONTENT_ROOT/defaults.conf. Keep the one-level
    fallback for direct ad-hoc invocations.
    """
    candidates = (
        CONTENT_ROOT / "defaults.conf",
        source_dir.parent.parent / "defaults.conf",
        source_dir.parent / "defaults.conf",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return CONTENT_ROOT / "defaults.conf"


def build_all(harnesses, dry_run=False, quiet=False):
    all_stats = {}
    defaults_path = defaults_path_for_source_dir(CONTENT_ROOT / CORE_SOURCE_DIR)
    defaults = load_defaults(defaults_path) if defaults_path.exists() else {}
    for content_type in ["agents", "skills", "rules", "workflows", "mcp", "hooks"]:
        source_dir = content_source_dir(content_type)
        if not has_sources(content_type, source_dir):
            continue
        stats = BUILDERS[content_type](source_dir, harnesses, dry_run=dry_run, defaults=defaults)
        all_stats[content_type] = stats
        if not quiet and not dry_run:
            for harness, count in stats.items():
                print(f"{harness}: {count} {content_type} built")
    return all_stats


def main(argv=None):
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
        help=f"Comma-separated harnesses (default: enabled). Options: {','.join(CONFIGURED_HARNESSES)}"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress output")
    args = parser.parse_args(argv)

    source_dir = Path(args.source_dir).resolve()
    if not source_dir.is_dir():
        if source_dir.is_symlink():
            source_dir = source_dir.resolve()
        if not source_dir.is_dir():
            print(f"Error: {source_dir} is not a directory", file=sys.stderr)
            return 1

    harnesses = [h.strip() for h in args.harness.split(",")]
    for h in harnesses:
        if h not in CONFIGURED_HARNESSES:
            print(f"Error: unknown harness '{h}'. Options: {', '.join(CONFIGURED_HARNESSES)}", file=sys.stderr)
            return 1

    builder = BUILDERS[args.type]
    defaults_path = defaults_path_for_source_dir(source_dir)
    defaults = load_defaults(defaults_path) if defaults_path.exists() else {}
    if defaults and not args.quiet:
        print(f"Loaded model defaults from {defaults_path}")

    try:
        stats = builder(source_dir, harnesses, dry_run=args.dry_run, defaults=defaults)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if not args.quiet:
        for harness, count in stats.items():
            print(f"{harness}: {count} {args.type} built")
    return 0


if __name__ == "__main__":
    sys.exit(main())
