from __future__ import annotations

import contextlib
import io
import json
import os
import tomllib
from pathlib import Path

import yaml

from helpers import TempWDMTestCase


class GroupsInstallAndBuildTests(TempWDMTestCase):
    def test_group_parser_strips_comments_and_expands_wildcards(self) -> None:
        self.write_agent("alpha")
        self.write_agent("beta")
        group = self.write_group(
            "core",
            """# Core tools
[agents]
alpha # keep this
*
alpha

[skills]
missing-skill
""",
        )
        groups = self.load("ai_management.groups")

        description, sections = groups.parse_section_file(group)

        self.assertEqual("Core tools", description)
        self.assertEqual(["alpha", "*", "alpha"], sections["agents"])
        self.assertEqual(["alpha", "beta"], groups.parse_group_section(group, "agents"))

    def test_get_all_type_discovers_each_supported_source_shape(self) -> None:
        self.write_agent("agent-one")
        self.write_skill("skill-one")
        (self.content_root / "hooks" / "core").mkdir(parents=True)
        (self.content_root / "hooks" / "core" / "pre-commit").write_text("#!/bin/sh\n", encoding="utf-8")
        (self.content_root / "mcp" / "core").mkdir(parents=True)
        (self.content_root / "mcp" / "core" / "server.json").write_text("{}", encoding="utf-8")
        groups = self.load("ai_management.groups")

        self.assertEqual(["agent-one"], groups.get_all_type("agents"))
        self.assertEqual(["skill-one"], groups.get_all_type("skills"))
        self.assertEqual(["pre-commit"], groups.get_all_type("hooks"))
        self.assertEqual(["server"], groups.get_all_type("mcp"))

    def test_resolve_selection_paths_expands_wildcard_and_dedupes(self) -> None:
        self.write_agent("alpha")
        self.write_agent("beta")
        groups = self.load("ai_management.groups")

        paths = groups.resolve_selection_paths("agents", ["alpha", "*", "alpha"])

        self.assertEqual(
            [self.content_root / "agents" / "core" / "alpha.md", self.content_root / "agents" / "core" / "beta.md"],
            paths,
        )

    def test_install_state_load_save_install_uninstall_and_group(self) -> None:
        self.write_agent("alpha")
        self.write_agent("beta")
        self.write_group("core", "[agents]\nalpha\nbeta\n")
        install = self.load("ai_management.install")

        install.save_installed_type("agents", ["alpha", "alpha", ""])
        self.assertEqual(["alpha"], install.load_installed_type("agents"))

        install.install_type("agents", ["beta", "missing"])
        self.assertEqual(["alpha", "beta"], install.load_installed_type("agents"))

        install.uninstall_type("agents", ["alpha"])
        self.assertEqual(["beta"], install.load_installed_type("agents"))

        install.uninstall_type("agents", ["beta"])
        install.install_group("core", only_type="agents")
        self.assertEqual(["alpha", "beta"], install.load_installed_type("agents"))

    def test_show_installed_reports_global_and_project_scopes(self) -> None:
        install = self.load("ai_management.install")
        install.save_installed_type("agents", ["global-marker"])

        project_installed = self.project / ".wdm" / "installed" / "agents.conf"
        project_installed.parent.mkdir(parents=True)
        project_installed.write_text("project-marker\n", encoding="utf-8")

        global_built = self.content_root / "agents" / "claude" / "global-loaded.md"
        global_built.parent.mkdir(parents=True, exist_ok=True)
        global_built.write_text("global", encoding="utf-8")
        global_dest = self.home / ".claude" / "agents" / "global-loaded.md"
        global_dest.parent.mkdir(parents=True)
        os.symlink(global_built, global_dest)

        project_built = self.content_root / "agents" / "codex" / "project-loaded.toml"
        project_built.parent.mkdir(parents=True, exist_ok=True)
        project_built.write_text('name = "project-loaded"\n', encoding="utf-8")
        project_dest = self.project / ".codex" / "agents" / "project-loaded.toml"
        project_dest.parent.mkdir(parents=True)
        os.symlink(project_built, project_dest)
        (self.project / ".github" / "agents").mkdir(parents=True)
        (self.project / ".github" / "dependabot.yml").write_text("version: 2\n", encoding="utf-8")

        old_cwd = Path.cwd()
        output = io.StringIO()
        try:
            os.chdir(self.project)
            with contextlib.redirect_stdout(output):
                install.show_installed()
        finally:
            os.chdir(old_cwd)

        rendered = output.getvalue()
        self.assertIn("agents:\n", rendered)
        self.assertIn("  Global:\n", rendered)
        self.assertIn("    global-loaded\n", rendered)
        self.assertIn("    global-marker\n", rendered)
        self.assertIn("  Project:\n", rendered)
        self.assertIn("    project-loaded\n", rendered)
        self.assertIn("    project-marker\n", rendered)
        self.assertNotIn("rules:\n", rendered)

    def test_parse_frontmatter_valid_missing_and_invalid(self) -> None:
        build = self.load("ai_management.build")

        fields, body = build.parse_frontmatter("---\nname: alpha\n---\n\nBody\n")
        self.assertEqual({"name": "alpha"}, fields)
        self.assertEqual("Body", body.strip())

        self.assertEqual(({}, "Plain body"), build.parse_frontmatter("Plain body"))

        fields, body = build.parse_frontmatter("---\nname: [\n---\nBody\n")
        self.assertEqual({}, fields)
        self.assertEqual("Body", body.strip())

    def test_field_resolution_prefers_single_then_multi_then_global_then_base(self) -> None:
        build = self.load("ai_management.build")
        fields = {
            "description": "base",
            "global_description": "global",
            "codex_copilot_description": "multi",
            "codex_description": "single",
            "claude_description": build.OMIT_SENTINEL,
        }

        self.assertEqual("single", build.resolve_field(fields, "codex", "description"))
        self.assertEqual("multi", build.resolve_field(fields, "copilot", "description"))
        self.assertEqual("global", build.resolve_field(fields, "gemini", "description"))
        self.assertIsNone(build.resolve_field(fields, "claude", "description"))

    def test_defaults_preserve_case_and_inject_reasoning(self) -> None:
        defaults = self.content_root / "defaults.conf"
        defaults.parent.mkdir(parents=True, exist_ok=True)
        defaults.write_text(
            """[codex]
default-low = gpt-5-mini
default-low.model_reasoning_effort = low
default = gpt-5
default.model_reasoning_effort = medium
default-high = gpt-5.5
default-high.model_reasoning_effort = high

[claude]
default-large = claude-opus-4.6
default-large.effort = high

[gemini]
default = gemini-pro
default.thinkingBudget = 4096
""",
            encoding="utf-8",
        )
        build = self.load("ai_management.build")

        loaded = build.load_defaults(defaults)

        self.assertEqual("gpt-5", loaded["codex"]["default"]["model"])
        self.assertEqual("medium", loaded["codex"]["default"]["model_reasoning_effort"])
        self.assertEqual("gpt-5-mini", loaded["codex"]["default-low"]["model"])
        self.assertEqual("gpt-5.5", loaded["codex"]["default-high"]["model"])
        self.assertEqual("claude-opus-4.6", loaded["claude"]["default-high"]["model"])
        self.assertEqual("4096", loaded["gemini"]["default"]["thinkingBudget"])
        self.assertEqual(
            {"model": "gpt-5", "model_reasoning_effort": "medium"},
            build.resolve_defaults({"model": "default"}, "codex", loaded),
        )
        self.assertEqual(
            {"model": "gpt-5.5", "model_reasoning_effort": "high"},
            build.resolve_defaults({"model": "default-high"}, "codex", loaded),
        )
        self.assertEqual(
            {"model": "claude-opus-4.6", "effort": "high"},
            build.resolve_defaults({"model": "default-large"}, "claude", loaded),
        )

    def test_build_all_loads_root_defaults_and_never_exports_default_tier_to_codex(self) -> None:
        self.content_root.mkdir(parents=True, exist_ok=True)
        (self.content_root / "defaults.conf").write_text(
            """[codex]
default = gpt-5.5
default.model_reasoning_effort = high
""",
            encoding="utf-8",
        )
        source_dir = self.content_root / "agents" / "core"
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "agent.md").write_text(
            """---
name: agent
description: Test agent
model: default
---

Do the work.
""",
            encoding="utf-8",
        )
        build = self.load("ai_management.build")

        build.build_all(["codex"], quiet=True)

        rendered = (self.content_root / "agents" / "codex" / "agent.toml").read_text(encoding="utf-8")
        self.assertIn('model = "gpt-5.5"', rendered)
        self.assertIn('model_reasoning_effort = "high"', rendered)
        self.assertNotIn('model = "default"', rendered)

    def test_markdown_builder_filters_schema_applies_mapping_and_wraps_gemini_reasoning(self) -> None:
        harness_dir = self.content_root / "harnesses" / "core"
        harness_dir.mkdir(parents=True, exist_ok=True)
        (harness_dir / "custom.json").write_text(
            json.dumps(
                {
                    "name": "custom",
                    "enabled": True,
                    "schemas": {"agents": ["name", "instructions"]},
                    "field_mappings": {"agents": {"body": "instructions"}},
                }
            ),
            encoding="utf-8",
        )
        build = self.load("ai_management.build")

        custom = build.build_md_file(
            {"name": "mapper", "description": "ignored"},
            "Mapped body\n",
            "custom",
            ["name", "instructions"],
            content_type="agents",
        )
        fields, body = build.parse_frontmatter(custom)
        self.assertEqual({"name": "mapper", "instructions": "Mapped body"}, fields)
        self.assertEqual("", body.strip())

        gemini = build.build_md_file(
            {"name": "g", "description": "d", "thinkingLevel": "HIGH"},
            "Body\n",
            "gemini",
            build.AGENT_SCHEMAS["gemini"],
            content_type="agents",
        )
        fields, _ = build.parse_frontmatter(gemini)
        self.assertEqual({"thinkingBudget": 16384}, fields["thinkingConfig"])
        self.assertNotIn("thinkingLevel", fields)

    def test_codex_agent_builder_outputs_toml_and_requires_body_description_name(self) -> None:
        build = self.load("ai_management.build")

        raw = build.build_codex_agent_toml(
            {
                "name": "api-designer",
                "description": "Design APIs",
                "model": "gpt-5",
                "model_reasoning_effort": "high",
                "skills": ["api-design"],
            },
            "## Mission\nBuild reliable APIs.",
        )
        data = tomllib.loads(raw)

        self.assertEqual("api-designer", data["name"])
        self.assertEqual("gpt-5", data["model"])
        self.assertEqual("high", data["model_reasoning_effort"])
        self.assertEqual([{"name": "api-design", "enabled": True}], data["skills"]["config"])
        self.assertIn("## Mission", data["developer_instructions"])

        with self.assertRaisesRegex(ValueError, "description"):
            build.build_codex_agent_toml({"name": "missing-description"}, "Body")

    def test_json_builder_applies_overrides_and_omit_sentinel(self) -> None:
        build = self.load("ai_management.build")
        content = """---
name: shared
codex_command: __omit__
gemini_url: https://example.test/mcp
extra: kept
---
{"command": "run-server", "url": "https://old.test"}
"""

        codex = json.loads(build.build_json_file(content, "codex"))
        gemini = json.loads(build.build_json_file(content, "gemini"))

        self.assertNotIn("command", codex)
        self.assertEqual("https://old.test", codex["url"])
        self.assertEqual("https://example.test/mcp", gemini["url"])
        self.assertEqual("kept", gemini["extra"])

    def test_mcp_builder_shapes_match_harness_contracts(self) -> None:
        build = self.load("ai_management.build")
        fields = {
            "name": "filesystem",
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem"],
            "env": {"ROOT": "/tmp"},
            "env_vars": ["TOKEN"],
            "tools": ["read_file"],
            "bearer_token_env_var": "TOKEN",
        }

        claude = build.build_mcp_entry(dict(fields), "claude")
        copilot = build.build_mcp_entry(dict(fields), "copilot")
        codex = build.build_mcp_entry(dict(fields), "codex")
        gemini = build.build_mcp_entry(dict(fields), "gemini")

        self.assertNotIn("type", claude)
        self.assertEqual("local", copilot["type"])
        self.assertEqual(["read_file"], copilot["tools"])
        self.assertEqual(["TOKEN"], codex["env_vars"])
        self.assertNotIn("tools", codex)
        self.assertNotIn("bearer_token_env_var", gemini)

    def test_builders_emit_files_for_agents_skills_rules_workflows_hooks_and_mcp(self) -> None:
        self.write_agent("agent-one")
        self.write_skill("skill-one")
        (self.content_root / "rules" / "core").mkdir(parents=True)
        (self.content_root / "rules" / "core" / "rule-one.md").write_text("---\nname: rule-one\n---\nRule body\n", encoding="utf-8")
        (self.content_root / "workflows" / "core").mkdir(parents=True)
        (self.content_root / "workflows" / "core" / "flow-one.md").write_text("---\nname: flow-one\n---\nFlow body\n", encoding="utf-8")
        (self.content_root / "hooks" / "core").mkdir(parents=True)
        (self.content_root / "hooks" / "core" / "pre-commit").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.write_mcp("filesystem", "---\nname: filesystem\ncommand: npx\n---\n")
        build = self.load("ai_management.build")

        self.assertEqual({"codex": 1, "claude": 1}, build.build_agents(self.content_root / "agents" / "core", ["codex", "claude"]))
        self.assertEqual({"codex": 1}, build.build_skills(self.content_root / "skills" / "core", ["codex"]))
        self.assertEqual({"claude": 1}, build.build_rules(self.content_root / "rules" / "core", ["claude"]))
        self.assertEqual({"claude": 1}, build.build_workflows(self.content_root / "workflows" / "core", ["claude"]))
        self.assertEqual({"codex": 1}, build.build_hooks(self.content_root / "hooks" / "core", ["codex"]))
        self.assertEqual({"codex": 1, "claude": 1}, build.build_mcp(self.content_root / "mcp" / "core", ["codex", "claude"]))

        self.assertTrue((self.content_root / "agents" / "codex" / "agent-one.toml").exists())
        self.assertTrue((self.content_root / "agents" / "claude" / "agent-one.md").exists())
        self.assertTrue((self.content_root / "skills" / "codex" / "skill-one" / "SKILL.md").exists())
        self.assertTrue((self.content_root / "rules" / "claude" / "rule-one.md").exists())
        self.assertTrue((self.content_root / "workflows" / "claude" / "flow-one.md").exists())
        self.assertTrue((self.content_root / "hooks" / "codex" / "pre-commit").exists())
        self.assertTrue((self.content_root / "mcp" / "codex" / "filesystem.toml").exists())
        self.assertTrue((self.content_root / "mcp" / "claude" / "filesystem.json").exists())

        data = yaml.safe_load((self.content_root / "agents" / "claude" / "agent-one.md").read_text(encoding="utf-8").split("---", 2)[1])
        self.assertEqual("agent-one", data["name"])

    def test_agent_variants_build_as_generated_specialisations(self) -> None:
        agent_dir = self.content_root / "agents" / "core"
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "frontend-developer.md").write_text(
            """---
name: frontend-developer
description: Base frontend developer
skills:
  - frontend-design
variants:
  - name: react-developer
    description: React frontend developer
    skills:
      - react-development
    context: |
      Use React component, hook, and state management patterns.
---

Build frontend interfaces.
""",
            encoding="utf-8",
        )
        build = self.load("ai_management.build")

        self.assertEqual({"codex": 2, "claude": 2}, build.build_agents(agent_dir, ["codex", "claude"]))

        codex_variant = (self.content_root / "agents" / "codex" / "frontend-developer--react-developer.toml").read_text(encoding="utf-8")
        self.assertIn('name = "frontend-developer--react-developer"', codex_variant)
        self.assertIn('skills = { config = [{ name = "frontend-design", enabled = true }, { name = "react-development", enabled = true }] }', codex_variant)
        self.assertIn("Variant Context: react-developer", codex_variant)

        claude_variant = yaml.safe_load(
            (self.content_root / "agents" / "claude" / "frontend-developer--react-developer.md")
            .read_text(encoding="utf-8")
            .split("---", 2)[1]
        )
        self.assertEqual("frontend-developer--react-developer", claude_variant["name"])
        self.assertEqual(["frontend-design", "react-development"], claude_variant["skills"])
