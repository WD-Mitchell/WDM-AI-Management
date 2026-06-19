from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

import yaml

from helpers import TempWDMTestCase


class WebCrudImportAndPreviewTests(TempWDMTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.write_projects(("Test Project", self.project))
        self.web = self.load_web()

    def test_save_agent_from_form_normalizes_models_capabilities_and_body(self) -> None:
        self.write_skill("api-design")
        self.write_mcp("filesystem", "---\nname: filesystem\ncommand: npx\n---\n")

        name = self.web.save_item(
            {
                "type": "agents",
                "name": "api-agent",
                "field_name": "api-agent",
                "field_description": "Designs APIs",
                "field_codex_model": "gpt-5",
                "field_codex_model_reasoning_effort": "high",
                "field_agent_skills": ["api-design"],
                "field_agent_mcp_servers": ["filesystem"],
                "body": "## Mission\nDesign consistent REST APIs.\n",
            }
        )
        path, raw, fields, body = self.web.read_item("agents", name)

        self.assertEqual(self.content_root / "agents" / "core" / "api-agent.md", path)
        self.assertIn("## Mission", body)
        self.assertEqual("gpt-5", fields["codex_model"])
        self.assertEqual("high", fields["codex_model_reasoning_effort"])
        self.assertEqual(["api-design"], fields["skills"])
        self.assertEqual(["filesystem"], fields["mcp_servers"])
        self.assertIn("description: Designs APIs", raw)

    def test_save_rename_removes_old_source_file(self) -> None:
        self.write_agent("old-name")

        self.web.save_item(
            {
                "type": "agents",
                "original_name": "old-name",
                "name": "new-name",
                "field_name": "new-name",
                "field_description": "Renamed",
                "body": "Body\n",
            }
        )

        self.assertFalse((self.content_root / "agents" / "core" / "old-name.md").exists())
        self.assertTrue((self.content_root / "agents" / "core" / "new-name.md").exists())

    def test_save_skill_hook_mcp_template_and_harness_files(self) -> None:
        self.web.save_item(
            {
                "type": "skills",
                "name": "docs",
                "field_name": "docs",
                "field_description": "Write docs",
                "body": "Document the project.\n",
            }
        )
        self.web.save_item(
            {
                "type": "hooks",
                "name": "pre-commit",
                "hook_shebang": "#!/usr/bin/env bash",
                "hook_description": "Run checks",
                "hook_script": "echo ok",
            }
        )
        self.web.save_item(
            {
                "type": "mcp",
                "name": "filesystem",
                "mcp_format": "json",
                "raw": json.dumps({"name": "filesystem", "command": "npx"}),
            }
        )
        self.web.save_item(
            {
                "type": "templates",
                "name": "agent-lite",
                "template_type": "agents",
                "template_description": "Small agent template",
                "template_fields": "description: Starter\n",
                "template_sections": json.dumps([{"title": "Mission", "level": 2, "content": "Do the work."}]),
                "template_field_sections": json.dumps({"developer_instructions": {"label": "Bad", "sections": [{"title": "Bad"}]}}),
            }
        )
        self.web.save_item(
            {
                "type": "harnesses",
                "name": "testharness",
                "original_raw": "{}",
                "harness_label": "Test Harness",
                "harness_default_enabled": "true",
                "harness_schema_agents": "name, description, instructions",
                "harness_field_mappings_json": json.dumps({"agents": {"body": "instructions"}}),
            }
        )

        self.assertTrue((self.content_root / "skills" / "core" / "docs" / "SKILL.md").exists())
        self.assertEqual("#!/usr/bin/env bash\n# Run checks\necho ok\n", (self.content_root / "hooks" / "core" / "pre-commit").read_text(encoding="utf-8"))
        self.assertEqual("npx", json.loads((self.content_root / "mcp" / "core" / "filesystem.json").read_text(encoding="utf-8"))["command"])

        template = yaml.safe_load((self.content_root / "templates" / "core" / "agent-lite.template").read_text(encoding="utf-8"))
        self.assertEqual("agents", template["type"])
        self.assertNotIn("developer_instructions", template["field_sections"])

        harness = json.loads((self.content_root / "harnesses" / "core" / "testharness.json").read_text(encoding="utf-8"))
        self.assertTrue(harness["default_enabled"])
        self.assertEqual({"agents": {"body": "instructions"}}, harness["field_mappings"])

    def test_group_form_renders_sections_and_saves_checked_memberships(self) -> None:
        self.write_agent("alpha", "Alpha agent")
        self.write_agent("beta", "Beta agent")
        self.write_skill("docs", "Docs skill")
        self.write_group("core", "# Core tools\n\n[agents]\nalpha\nmissing-agent\n\n[skills]\ndocs\n")

        rendered = self.web.render_editor("groups", "core", set(), "global", "form")
        self.assertIn('data-group-type-section data-group-type="agents"', rendered)
        self.assertIn('name="group_items_agents" value="alpha" checked', rendered)
        self.assertIn("missing-agent", rendered)
        self.assertIn("group-item-badge", rendered)
        self.assertIn('data-group-type-filter', rendered)
        self.assertIn('data-group-item-filter', rendered)

        saved = self.web.save_item(
            {
                "type": "groups",
                "name": "platform",
                "editor_view": "form",
                "group_description": "Platform group",
                "group_items_agents": ["alpha", "beta"],
                "group_items_skills": ["docs"],
            }
        )

        self.assertEqual("platform", saved)
        raw = (self.content_root / "groups" / "platform.group").read_text(encoding="utf-8")
        self.assertEqual("# Platform group\n\n[agents]\nalpha\nbeta\n\n[skills]\ndocs\n", raw)

    def test_agent_variant_names_are_listed_and_installable(self) -> None:
        agent_dir = self.content_root / "agents" / "core"
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "frontend-developer.md").write_text(
            """---
name: frontend-developer
description: Base frontend developer
variants:
  - name: react-developer
    description: React frontend developer
    skills:
      - react-development
    context: React-specific context.
---

Build frontend interfaces.
""",
            encoding="utf-8",
        )

        self.assertIn("frontend-developer--react-developer", self.web.list_names("agents"))
        summary = self.web.item_summary("agents", "frontend-developer--react-developer")
        self.assertEqual("frontend-developer", summary["variant_base"])
        rendered = self.web.render_selection_card(
            "agents",
            summary,
            set(),
            "global",
            1,
            self.web.normalize_selection_filters({}, []),
        )
        self.assertIn("selection-card-variant-badge", rendered)
        self.assertIn('data-edit-name="frontend-developer"', rendered)

        page = self.web.render_selection_page(
            "agents",
            [self.web.item_summary("agents", name) for name in self.web.list_names("agents")],
            set(),
            "global",
            1,
            {},
        )
        self.assertIn("agent-variant-group", page)
        self.assertIn('<details class="agent-variant-details">', page)
        self.assertNotIn('<details class="agent-variant-details" open>', page)
        self.assertIn("agent-variant-list", page)
        self.assertIn("agent-base-panel", page)
        self.assertIn("agent-variant-row", page)
        self.assertIn("frontend-developer--react-developer", page)
        self.assertIn('name="names" value="frontend-developer--react-developer"', page)

        result = self.web.validation_result("agents", "frontend-developer--react-developer", "codex")
        self.assertTrue(result["ok"], result)

    def test_agent_variant_index_is_cached_and_invalidates_on_source_change(self) -> None:
        agent_dir = self.content_root / "agents" / "core"
        agent_dir.mkdir(parents=True, exist_ok=True)
        source = agent_dir / "frontend-developer.md"
        source.write_text(
            """---
name: frontend-developer
description: Base frontend developer
variants:
  - name: react-developer
    description: React frontend developer
  - name: nextjs-developer
    description: Next.js frontend developer
---

Build frontend interfaces.
""",
            encoding="utf-8",
        )

        from ai_management import agent_variants

        agent_variants._agent_variant_index_cached.cache_clear()
        original_parse = agent_variants.parse_markdown_frontmatter
        parse_calls = 0

        def counting_parse(raw: str):
            nonlocal parse_calls
            parse_calls += 1
            return original_parse(raw)

        agent_variants.parse_markdown_frontmatter = counting_parse
        try:
            names = self.web.list_names("agents")
            for name in names:
                self.web.item_summary("agents", name)
            self.assertEqual(1, parse_calls)

            source.write_text(
                source.read_text(encoding="utf-8").replace(
                    "React frontend developer",
                    "React specialist frontend developer",
                ),
                encoding="utf-8",
            )
            summary = self.web.item_summary("agents", "frontend-developer--react-developer")
            self.assertEqual("React specialist frontend developer", summary["description"])
            self.assertEqual(2, parse_calls)
        finally:
            agent_variants.parse_markdown_frontmatter = original_parse
            agent_variants._agent_variant_index_cached.cache_clear()

    def test_browser_disconnect_during_get_does_not_raise_traceback(self) -> None:
        class BrokenPipeWriter:
            def write(self, data: bytes) -> int:
                raise BrokenPipeError("client disconnected")

            def flush(self) -> None:
                pass

        handler = object.__new__(self.web.ManagementHandler)
        handler.path = "/?type=agents"
        handler.command = "GET"
        handler.request_version = "HTTP/1.1"
        handler.requestline = "GET /?type=agents HTTP/1.1"
        handler.client_address = ("127.0.0.1", 0)
        handler.server = None
        handler.close_connection = True
        handler.rfile = None
        handler.wfile = BrokenPipeWriter()
        handler.log_message = lambda *args: None
        handler.headers = {}

        handler.do_GET()

    def test_group_form_post_preserves_repeated_checkbox_values(self) -> None:
        self.write_agent("alpha")
        self.write_agent("beta")

        status, _, headers = self.post_form(
            self.web,
            "/save",
            [
                ("type", "groups"),
                ("name", "route-group"),
                ("editor_view", "form"),
                ("scope", "global"),
                ("group_description", "Route group"),
                ("group_items_agents", "alpha"),
                ("group_items_agents", "beta"),
            ],
        )

        self.assertEqual(303, status)
        self.assertIn("type=groups", urllib.parse.unquote(headers["location"]))
        raw = (self.content_root / "groups" / "route-group.group").read_text(encoding="utf-8")
        self.assertIn("[agents]\nalpha\nbeta\n", raw)

    def test_validation_rejects_invalid_form_backed_files(self) -> None:
        with self.assertRaisesRegex(ValueError, "name must be valid YAML"):
            self.web.validate_form_state({"type": "mcp", "name": "bad", "original_suffix": ".json", "target_view": "form", "field_name": "[not-json"})

        with self.assertRaisesRegex(ValueError, "Harness config"):
            self.web.validate_form_state({"type": "harnesses", "name": "bad", "target_view": "form", "editor_view": "file", "raw": "[]"})

        with self.assertRaisesRegex(ValueError, "Template needs"):
            self.web.validate_form_state({"type": "templates", "name": "bad", "target_view": "form", "template_type": "agents", "template_sections": "[]"})

    def test_import_paste_path_duplicate_and_delete_update_source_and_installed_state(self) -> None:
        imported = self.web.import_item(
            {
                "type": "agents",
                "import_source": "paste",
                "import_file_name": "Pasted Agent.md",
                "import_raw": "---\nname: pasted-agent\ndescription: Pasted\n---\nBody\n",
            }
        )
        self.assertEqual("pasted-agent", imported)

        source = self.base / "source-agent.md"
        source.write_text("---\nname: path-agent\ndescription: From path\n---\nPath body\n", encoding="utf-8")
        path_import = self.web.import_item({"type": "agents", "import_source": "path", "import_path": str(source)})
        self.assertEqual("source-agent", path_import)

        duplicate = self.web.duplicate_item("agents", imported)
        self.assertEqual("pasted-agent-copy", duplicate)
        self.assertTrue((self.content_root / "agents" / "core" / "pasted-agent-copy.md").exists())

        self.web.save_installed_type("agents", [imported, duplicate])
        self.web.delete_item("agents", imported)
        self.assertFalse((self.content_root / "agents" / "core" / "pasted-agent.md").exists())
        self.assertNotIn(imported, self.web.load_installed_type("agents"))
        self.assertIn(duplicate, self.web.load_installed_type("agents"))

    def test_import_rejects_empty_and_oversized_content(self) -> None:
        with self.assertRaisesRegex(ValueError, "empty"):
            self.web.import_item({"type": "agents", "import_source": "paste", "import_raw": "  "})

        too_large = self.base / "too-large.md"
        too_large.write_bytes(b"x" * (self.web.IMPORT_MAX_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "larger than 3MB"):
            self.web.import_item({"type": "agents", "import_source": "path", "import_path": str(too_large)})

    def test_save_template_from_item_extracts_body_sections_and_fields(self) -> None:
        result = self.web.save_template_from_item(
            {
                "type": "agents",
                "name": "api-agent",
                "template_name": "API Template",
                "field_description": "Reusable description",
                "body": "## Mission\nBuild APIs.\n\n## Output\nReturn OpenAPI.\n",
            }
        )
        template = yaml.safe_load((self.content_root / "templates" / "core" / "api-template.template").read_text(encoding="utf-8"))

        self.assertEqual("api-template", result["name"])
        self.assertEqual(["Mission", "Output"], [section["title"] for section in template["sections"]])
        self.assertEqual("Reusable description", template["fields"]["description"])

    def test_harness_toggle_updates_file_and_runtime(self) -> None:
        harness_path = self.content_root / "harnesses" / "core" / "toggleme.json"
        harness_path.parent.mkdir(parents=True, exist_ok=True)
        harness_path.write_text(json.dumps({"name": "toggleme", "label": "Toggle Me", "enabled": True}), encoding="utf-8")
        self.web.refresh_harness_runtime()

        self.assertIn("toggleme", self.web.ALL_HARNESSES)
        self.web.set_harness_enabled("toggleme", False)

        self.assertFalse(json.loads(harness_path.read_text(encoding="utf-8"))["enabled"])
        self.assertNotIn("toggleme", self.web.ALL_HARNESSES)

    def test_external_agent_candidates_edit_import_and_preview(self) -> None:
        cursor_harness = self.content_root / "harnesses" / "core" / "cursor.json"
        cursor_harness.parent.mkdir(parents=True, exist_ok=True)
        cursor_harness.write_text(
            json.dumps(
                {
                    "name": "cursor",
                    "label": "Cursor",
                    "default_enabled": True,
                    "sync": {"paths": {"project": {"agents": ".cursor/agents/{name}.md"}}},
                }
            ),
            encoding="utf-8",
        )
        self.web.refresh_harness_runtime()
        external = self.project / ".codex" / "agents" / "outside.toml"
        external.parent.mkdir(parents=True, exist_ok=True)
        external.write_text(
            'name = "outside"\ndescription = "External codex agent"\ndeveloper_instructions = "## Mission\\nUse **markdown**."\n',
            encoding="utf-8",
        )
        nested_codex = self.project / ".codex" / "agents" / "team" / "nested-codex.toml"
        nested_codex.parent.mkdir(parents=True, exist_ok=True)
        nested_codex.write_text('name = "nested-codex"\ndescription = "Nested codex agent"\n', encoding="utf-8")
        nested_claude = self.project / ".claude" / "agents" / "platform" / "nested-claude.md"
        nested_claude.parent.mkdir(parents=True, exist_ok=True)
        nested_claude.write_text("---\nname: nested-claude\ndescription: Nested claude agent\n---\n\nBody\n", encoding="utf-8")
        nested_copilot = self.project / ".github" / "agents" / "teams" / "nested-copilot.agent.md"
        nested_copilot.parent.mkdir(parents=True, exist_ok=True)
        nested_copilot.write_text("---\nname: nested-copilot\ndescription: Nested copilot agent\n---\n\nBody\n", encoding="utf-8")
        nested_cursor = self.project / ".cursor" / "agents" / "team" / "nested-cursor.md"
        nested_cursor.parent.mkdir(parents=True, exist_ok=True)
        nested_cursor.write_text("---\nname: nested-cursor\ndescription: Nested cursor agent\n---\n\nBody\n", encoding="utf-8")
        nested_gemini = self.project / ".gemini" / "agents" / "ops" / "nested-gemini.md"
        nested_gemini.parent.mkdir(parents=True, exist_ok=True)
        nested_gemini.write_text("---\nname: nested-gemini\ndescription: Nested gemini agent\n---\n\nBody\n", encoding="utf-8")
        managed_source = self.write_agent("managed-external")
        managed_link = self.project / ".codex" / "agents" / "managed" / "managed-external.toml"
        managed_link.parent.mkdir(parents=True, exist_ok=True)
        managed_link.symlink_to(managed_source)

        candidates = self.web.external_item_candidates("agents", self.project_scope)
        names = [item["name"] for item in candidates]
        self.assertEqual(["nested-claude", "nested-codex", "outside", "nested-copilot", "nested-cursor", "nested-gemini"], names)
        self.assertNotIn("managed-external", names)
        by_name = {item["name"]: item for item in candidates}
        self.assertEqual("External codex agent", by_name["outside"]["description"])
        self.assertEqual(nested_codex.resolve(), Path(by_name["nested-codex"]["path"]).resolve())
        self.assertEqual(nested_copilot.resolve(), Path(by_name["nested-copilot"]["path"]).resolve())
        self.assertEqual(nested_cursor.resolve(), Path(by_name["nested-cursor"]["path"]).resolve())

        self.web.save_external_item(
            {
                "type": "agents",
                "harness": "codex",
                "path": str(external),
                "scope": self.project_scope,
                "raw": 'name = "outside"\ndescription = "Edited"\ndeveloper_instructions = "Body"\n',
            }
        )
        self.assertIn('description = "Edited"', external.read_text(encoding="utf-8"))

        imported = self.web.import_external_item(
            {
                "type": "agents",
                "harness": "codex",
                "path": str(external),
                "scope": self.project_scope,
                "name": "outside-managed",
            }
        )
        self.assertEqual("outside-managed", imported)
        managed = self.content_root / "agents" / "core" / "outside-managed.md"
        self.assertTrue(managed.exists())
        self.assertIn("imported_harness: codex", managed.read_text(encoding="utf-8"))
        self.assertIn("imported_source_sha256:", managed.read_text(encoding="utf-8"))
        self.assertIn("outside-managed", self.web.load_installed_type("agents"))

        candidates = self.web.external_item_candidates("agents", self.project_scope)
        outside = next(item for item in candidates if item["name"] == "outside")
        self.assertTrue(outside["source_exists"])
        self.assertEqual("outside-managed", outside["managed_name"])
        self.assertEqual("up-to-date", outside["sync_status"])
        card = self.web.render_external_card("agents", outside, self.project_scope, 1, {"source_mode": "combined"})
        self.assertIn("data-edit-name=\"outside-managed\"", card)
        self.assertIn(">Managed</button>", card)
        self.assertIn("Managed: outside-managed", card)
        self.assertIn("Up to date", card)

        external.write_text(
            'name = "outside"\ndescription = "Changed external"\ndeveloper_instructions = "Body"\n',
            encoding="utf-8",
        )
        outside = next(item for item in self.web.external_item_candidates("agents", self.project_scope) if item["name"] == "outside")
        self.assertEqual("out-of-date", outside["sync_status"])
        stale_card = self.web.render_external_card("agents", outside, self.project_scope, 1, {"source_mode": "combined"})
        self.assertIn('action="/sync-external"', stale_card)
        self.assertIn("Out of date", stale_card)

        status, _, _ = self.post_form(
            self.web,
            "/sync-external",
            {
                "type": "agents",
                "name": "outside",
                "managed_name": "outside-managed",
                "harness": "codex",
                "path": str(external),
                "scope": self.project_scope,
                "return_to": "/?type=agents&source=combined",
            },
        )
        self.assertEqual(303, status)
        self.assertIn("Changed external", managed.read_text(encoding="utf-8"))
        outside = next(item for item in self.web.external_item_candidates("agents", self.project_scope) if item["name"] == "outside")
        self.assertEqual("up-to-date", outside["sync_status"])

        rendered = self.web.rendered_preview_external_item("agents", "codex", str(external), self.project_scope)
        self.assertIn("rendered-structured-fields", rendered)
        self.assertIn("Changed external", rendered)

    def test_rendered_preview_handles_markdown_toml_json_and_html(self) -> None:
        self.write_agent("codex-preview", body="## Mission\nUse **markdown**.\n")
        codex = self.web.rendered_preview_item("agents", "codex-preview", "global", "codex")
        markdown = self.web.render_preview_content("---\ntitle: Example\n---\n# Heading\n\n- item\n", "markdown")
        json_preview = self.web.render_preview_content('{"b": 1, "a": 2}', "json")
        html_preview = self.web.render_preview_content("<html><body><h1>Hello</h1></body></html>", "html")

        self.assertIn("rendered-structured-fields", codex)
        self.assertIn("<h2>Mission</h2>", codex)
        self.assertIn("rendered-frontmatter", markdown)
        self.assertIn("<h1>Heading</h1>", markdown)
        self.assertIn("&quot;b&quot;: 1", json_preview)
        self.assertIn("iframe", html_preview)

    def test_validate_item_for_harness_reports_success_and_failure(self) -> None:
        self.write_agent("valid-codex", body="## Mission\nUse **markdown**.\n")
        valid = self.web.validation_result("agents", "valid-codex", "codex")
        self.assertTrue(valid["ok"])
        self.assertEqual("codex", valid["harness"])

        self.write_agent("invalid-codex", description="", body="## Mission\nNo description.\n")
        invalid = self.web.validation_result("agents", "invalid-codex", "codex")
        self.assertFalse(invalid["ok"])
        self.assertIn("description", invalid["error"])
        self.assertIn("failed validation", self.web.render_validation_notice(invalid))

    def test_post_routes_save_import_duplicate_delete_and_harness_toggle(self) -> None:
        status, _, headers = self.post_form(
            self.web,
            "/save",
            {
                "type": "agents",
                "name": "route-agent",
                "field_name": "route-agent",
                "field_description": "Saved over route",
                "body": "Route body\n",
                "scope": "global",
            },
        )
        self.assertEqual(303, status)
        self.assertIn("name=route-agent", urllib.parse.unquote(headers["location"]))
        self.assertTrue((self.content_root / "agents" / "core" / "route-agent.md").exists())

        status, body, _ = self.post_form(
            self.web,
            "/duplicate",
            {"type": "agents", "name": "route-agent"},
            accept_json=True,
        )
        self.assertEqual(200, status)
        payload = json.loads(body)
        self.assertTrue(payload["ok"])
        self.assertEqual("route-agent-copy", payload["name"])

        status, body, _ = self.post_form(
            self.web,
            "/import-item",
            {
                "type": "agents",
                "import_source": "paste",
                "import_file_name": "route-import.md",
                "import_raw": "---\nname: route-import\ndescription: Imported\n---\nBody\n",
            },
            accept_json=True,
        )
        self.assertEqual(200, status)
        self.assertEqual("route-import", json.loads(body)["name"])

        harness_path = self.content_root / "harnesses" / "core" / "routeharness.json"
        harness_path.parent.mkdir(parents=True, exist_ok=True)
        harness_path.write_text(json.dumps({"name": "routeharness", "enabled": False}), encoding="utf-8")
        status, _, _ = self.post_form(self.web, "/harnesses/toggle", {"name": "routeharness", "action": "enable"})
        self.assertEqual(303, status)
        self.assertTrue(json.loads(harness_path.read_text(encoding="utf-8"))["enabled"])

        status, _, _ = self.post_form(self.web, "/delete", {"type": "agents", "name": "route-agent-copy"})
        self.assertEqual(303, status)
        self.assertFalse((self.content_root / "agents" / "core" / "route-agent-copy.md").exists())
