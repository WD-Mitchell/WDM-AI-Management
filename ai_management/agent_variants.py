from __future__ import annotations

from functools import lru_cache
import re
from pathlib import Path
from typing import Any

import yaml


VARIANT_SEPARATOR = "--"
VARIANTS_FIELD = "variants"
VARIANT_CONTEXT_FIELDS = ("context", "additional_context", "instructions", "body")
VARIANT_LIST_FIELDS = ("skills", "mcp_servers", "mcp-servers")


def slugify_variant_name(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip().lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-._")
    return slug


def parse_markdown_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    if not raw.startswith("---"):
        return {}, raw
    end = raw.find("\n---", 3)
    if end == -1:
        return {}, raw
    fm_text = raw[4:end]
    body = raw[end + 4 :]
    if body.startswith("\n"):
        body = body[1:]
    try:
        loaded = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        return {}, body
    return loaded if isinstance(loaded, dict) else {}, body


def load_agent_source(path: Path) -> tuple[dict[str, Any], str]:
    return parse_markdown_frontmatter(path.read_text(encoding="utf-8"))


def agent_variants_from_fields(fields: dict[str, Any]) -> list[dict[str, Any]]:
    raw = fields.get(VARIANTS_FIELD)
    variants: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                variants.append(dict(item))
    elif isinstance(raw, dict):
        for key, item in raw.items():
            if isinstance(item, dict):
                variant = dict(item)
            else:
                variant = {"description": str(item)}
            variant.setdefault("name", str(key))
            variants.append(variant)
    return [
        variant
        for variant in variants
        if slugify_variant_name(str(variant.get("name") or variant.get("slug") or ""))
    ]


def variant_slug(variant: dict[str, Any]) -> str:
    return slugify_variant_name(str(variant.get("slug") or variant.get("name") or ""))


def variant_output_name(base_name: str, variant: dict[str, Any]) -> str:
    return f"{base_name}{VARIANT_SEPARATOR}{variant_slug(variant)}"


def agent_source_signature(source_dir: Path) -> tuple[tuple[str, int, int], ...]:
    if not source_dir.exists():
        return ()
    signature: list[tuple[str, int, int]] = []
    for path in sorted(source_dir.glob("*.md")):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        signature.append((path.name, int(stat.st_mtime_ns), int(stat.st_size)))
    return tuple(signature)


@lru_cache(maxsize=32)
def _agent_variant_index_cached(
    source_dir_text: str,
    signature: tuple[tuple[str, int, int], ...],
) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    source_dir = Path(source_dir_text)
    for file_name, _, _ in signature:
        path = source_dir / file_name
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        fields, body = parse_markdown_frontmatter(raw)
        base_name = str(fields.get("name") or path.stem).strip() or path.stem
        for variant in agent_variants_from_fields(fields):
            name = variant_output_name(base_name, variant)
            index[name] = {
                "name": name,
                "base_name": base_name,
                "source_path": path,
                "raw": raw,
                "base_fields": fields,
                "base_body": body,
                "variant": variant,
            }
    return index


def copy_variant_entry(entry: dict[str, Any]) -> dict[str, Any]:
    copied = dict(entry)
    if isinstance(copied.get("base_fields"), dict):
        copied["base_fields"] = dict(copied["base_fields"])
    if isinstance(copied.get("variant"), dict):
        copied["variant"] = dict(copied["variant"])
    return copied


def agent_variant_index(source_dir: Path) -> dict[str, dict[str, Any]]:
    signature = agent_source_signature(source_dir)
    if not signature:
        return {}
    source_dir_text = str(source_dir.resolve() if source_dir.exists() else source_dir)
    return {
        name: copy_variant_entry(entry)
        for name, entry in _agent_variant_index_cached(source_dir_text, signature).items()
    }


def agent_variant_entry(source_dir: Path, name: str) -> dict[str, Any] | None:
    return agent_variant_index(source_dir).get(name)


def is_agent_variant_name(source_dir: Path, name: str) -> bool:
    return name in agent_variant_index(source_dir)


def agent_source_exists(source_dir: Path, name: str) -> bool:
    return (source_dir / f"{name}.md").exists() or is_agent_variant_name(source_dir, name)


def dedupe_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def field_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def materialize_agent_variant(
    base_fields: dict[str, Any],
    base_body: str,
    variant: dict[str, Any],
    base_name: str,
) -> tuple[dict[str, Any], str]:
    fields = {key: value for key, value in base_fields.items() if key != VARIANTS_FIELD}
    generated_name = variant_output_name(base_name, variant)
    fields["name"] = generated_name

    variant_description = str(variant.get("description") or "").strip()
    if variant_description:
        fields["description"] = variant_description

    for list_field in VARIANT_LIST_FIELDS:
        combined = field_list(fields.get(list_field)) + field_list(variant.get(list_field))
        if combined:
            fields[list_field] = dedupe_list(combined)

    ignored = {
        "name",
        "slug",
        "description",
        *VARIANT_LIST_FIELDS,
        *VARIANT_CONTEXT_FIELDS,
    }
    for key, value in variant.items():
        if key not in ignored:
            fields[key] = value

    context = ""
    for field in VARIANT_CONTEXT_FIELDS:
        if str(variant.get(field) or "").strip():
            context = str(variant[field]).strip()
            break

    body = base_body.rstrip()
    if context:
        title = str(variant.get("name") or variant_slug(variant)).strip()
        body = f"{body}\n\n## Variant Context: {title}\n\n{context}".strip() + "\n"
    elif body:
        body += "\n"
    return fields, body
