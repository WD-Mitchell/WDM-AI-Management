from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from .utils import CONTENT_ROOT, CONTENT_TYPES, GROUPS_DIR, MCP_SOURCE_EXTENSIONS, TEMPLATES_DIR, dedupe, strip_inline_comment


def parse_section_file(path: Path) -> Tuple[str, Dict[str, List[str]]]:
    description = ""
    sections: Dict[str, List[str]] = {}
    current = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not description and stripped.startswith("#"):
            description = stripped.lstrip("# ").strip()
        line = strip_inline_comment(raw)
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip().lower()
            sections.setdefault(current, [])
            continue
        if current:
            sections.setdefault(current, []).append(line)
    return description, sections


def group_description(path: Path) -> str:
    return parse_section_file(path)[0]


def template_description(path: Path) -> str:
    return parse_section_file(path)[0]


def get_all_type(content_type: str) -> List[str]:
    base = CONTENT_ROOT / content_type
    if not base.exists():
        return []
    items: List[str] = []
    if content_type == "skills":
        for child in sorted(base.iterdir()):
            if child.is_dir() and not child.name.startswith(".") and (child / "SKILL.md").exists():
                items.append(child.name)
    elif content_type == "hooks":
        for child in sorted(base.iterdir()):
            if not child.name.startswith("."):
                items.append(child.name)
    elif content_type == "mcp":
        for child in sorted(base.iterdir()):
            if child.is_file() and child.suffix.lower() in MCP_SOURCE_EXTENSIONS:
                items.append(child.stem)
    else:
        for child in sorted(base.glob("*.md")):
            if child.is_file():
                items.append(child.stem)
    return dedupe(items)


def resolve_item_path(content_type: str, name: str) -> Path:
    base = CONTENT_ROOT / content_type
    if content_type == "skills":
        return base / name
    if content_type == "hooks":
        return base / name
    if content_type == "mcp":
        for suffix in MCP_SOURCE_EXTENSIONS:
            path = base / f"{name}{suffix}"
            if path.exists():
                return path
        return base / f"{name}.md"
    return base / f"{name}.md"


def parse_group_section(group_file: Path, section: str) -> List[str]:
    _, sections = parse_section_file(group_file)
    values = sections.get(section, [])
    expanded: List[str] = []
    for value in values:
        if value == "*":
            expanded.extend(get_all_type(section))
        else:
            expanded.append(value)
    return sorted(dedupe(expanded))


def parse_group(group_file: Path) -> List[str]:
    return parse_group_section(group_file, "skills")


def skill_description(name: str) -> str:
    skill_dir = CONTENT_ROOT / "skills" / name
    for file_name in ("SKILL.md", "skill.md"):
        path = skill_dir / file_name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        in_frontmatter = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped == "---":
                in_frontmatter = not in_frontmatter
                continue
            if in_frontmatter and stripped.startswith("description:"):
                return stripped.split(":", 1)[1].strip().strip('"\'')[:70]
        return ""
    return ""


def group_path(name: str) -> Path:
    return GROUPS_DIR / f"{name}.group"


def template_path(name: str) -> Path:
    return TEMPLATES_DIR / f"{name}.template"


def apply_template_sections(template_file: Path, raw: Dict[str, List[str]], group_names: List[str]) -> None:
    _, sections = parse_section_file(template_file)
    group_names.extend(sections.get("groups", []))
    for content_type in CONTENT_TYPES:
        raw[content_type].extend(sections.get(content_type, []))


def apply_group_sections(group_file: Path, raw: Dict[str, List[str]]) -> None:
    _, sections = parse_section_file(group_file)
    for content_type in CONTENT_TYPES:
        raw[content_type].extend(sections.get(content_type, []))


def resolve_selection_paths(content_type: str, names: Sequence[str]) -> List[Path]:
    expanded: List[str] = []
    for name in names:
        if name == "*":
            expanded.extend(get_all_type(content_type))
        else:
            expanded.append(name)
    return [resolve_item_path(content_type, name) for name in dedupe(item.strip() for item in expanded if item.strip())]
