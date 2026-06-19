from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

from helpers import TempWDMTestCase


class WebFiltersProjectsAndRenderingTests(TempWDMTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.write_projects(("Test Project", self.project))
        self.web = self.load_web()

    def test_project_add_choices_selection_and_browse_dirs(self) -> None:
        other = self.base / "other-project"
        other.mkdir()

        added = self.web.add_project("", str(other))
        choices = self.web.project_choices()

        self.assertEqual({"label": "other-project", "root": str(other.resolve())}, added)
        self.assertEqual("global", choices[0]["value"])
        self.assertEqual("Global", self.web.selected_project("global")["label"])
        self.assertEqual(str(other.resolve()), self.web.selected_project(f"project:{other}")["root"])
        self.assertEqual("Global", self.web.selected_project("project:/missing")["label"])

        listing = self.web.browse_dirs(str(self.base))
        self.assertEqual(str(self.base.resolve()), listing["path"])
        self.assertIn("other-project", {item["name"] for item in listing["dirs"]})

        with self.assertRaisesRegex(ValueError, "Project path is not a directory"):
            self.web.add_project("bad", str(self.base / "missing"))

    def test_update_status_detection_and_rendering(self) -> None:
        brew = self.web.detect_install_method("/opt/homebrew/bin/wdm-ai")
        self.assertEqual("Homebrew", brew["method"])
        self.assertEqual("brew update && brew upgrade wdm-ai-management", brew["command"])

        npm = self.web.detect_install_method("/Users/will/.npm-global/bin/wdm-ai")
        self.assertEqual("npm", npm["method"])
        self.assertEqual("npm update -g @wdm-uk/ai-management", npm["command"])

        self.assertLess(self.web.compare_versions("1.2.0", "1.2.1"), 0)
        self.assertEqual(0, self.web.compare_versions("1.2.0", "1.2"))
        self.assertGreater(self.web.compare_versions("1.3.0", "1.2.9"), 0)

        original_latest = self.web.latest_available_version
        original_brew_outdated = self.web.brew_outdated
        try:
            self.web.latest_available_version = lambda: self.fail("Normal page render should not probe latest version")
            self.assertEqual("Installed", self.web.update_status_info()["status_label"])
            self.web.UPDATE_STATUS_CACHE.clear()

            self.web.latest_available_version = lambda: "999.0.0"

            def fail_brew_outdated() -> str:
                self.fail("Homebrew outdated state should not drive update status")

            self.web.brew_outdated = fail_brew_outdated
            info = self.web.update_status_info(force=True)
        finally:
            self.web.latest_available_version = original_latest
            self.web.brew_outdated = original_brew_outdated
            self.web.UPDATE_STATUS_CACHE.clear()

        self.assertEqual("out-of-date", info["status"])
        self.assertEqual("999.0.0", info["latest"])

        original = self.web.update_status_info
        try:
            self.web.update_status_info = lambda: {
                "method": "Homebrew",
                "command": "brew update && brew upgrade wdm-ai-management",
                "status": "out-of-date",
                "status_label": "Out of date",
                "current": "1.2.0",
                "latest": "1.2.1",
            }
            html = self.web.render_update_status_panel()
        finally:
            self.web.update_status_info = original

        self.assertIn('data-update-status="out-of-date"', html)
        self.assertIn("Out of date", html)
        self.assertIn("Latest 1.2.1", html)
        self.assertIn("brew update &amp;&amp; brew upgrade wdm-ai-management", html)

        try:
            self.web.update_status_info = lambda: {
                "method": "Homebrew",
                "command": "brew update && brew upgrade wdm-ai-management",
                "status": "up-to-date",
                "status_label": "Up to date",
                "current": "1.2.1",
                "latest": "",
            }
            html = self.web.render_update_status_panel()
        finally:
            self.web.update_status_info = original

        self.assertIn('data-update-status="up-to-date"', html)
        self.assertIn("Up to date", html)
        self.assertNotIn("brew update", html)
        self.assertNotIn("<code>", html)

    def test_source_settings_page_and_form_persist_storage_choices(self) -> None:
        html = self.web.render_settings_page()
        self.assertIn("Settings", html)
        self.assertIn("Source folder", html)
        self.assertIn("Git repository URL", html)
        self.assertIn("Coming soon", html)
        self.assertIn("AI_MANAGEMENT_HOME", html)

        local_path = self.base / "custom-wdm"
        saved = self.web.save_source_settings_form({"source_mode": "local", "local_path": str(local_path)})
        self.assertEqual("local", saved["mode"])
        self.assertEqual(str(local_path), saved["local_path"])

        repo = self.web.save_source_settings_form(
            {
                "source_mode": "repo",
                "local_path": str(local_path),
                "repo_url": "https://github.com/example/private-wdm.git",
                "repo_token": "secret-token",
            }
        )
        self.assertEqual("repo", repo["mode"])
        self.assertEqual("secret-token", repo["repo_token"])
        self.assertIn("private-wdm", repo["repo_checkout_path"])

        retained = self.web.save_source_settings_form(
            {
                "source_mode": "repo",
                "local_path": str(local_path),
                "repo_url": "https://github.com/example/private-wdm.git",
                "repo_token_existing": "1",
            }
        )
        self.assertEqual("secret-token", retained["repo_token"])

        cleared = self.web.save_source_settings_form(
            {
                "source_mode": "repo",
                "local_path": str(local_path),
                "repo_url": "https://github.com/example/private-wdm.git",
                "repo_token_existing": "1",
                "repo_token_clear": "1",
            }
        )
        self.assertEqual("", cleared["repo_token"])

        with self.assertRaisesRegex(ValueError, "Git repository URL"):
            self.web.save_source_settings_form({"source_mode": "repo", "local_path": str(local_path), "repo_url": ""})

    def test_settings_post_route_saves_and_redirects(self) -> None:
        status, _, headers = self.post_form(
            self.web,
            "/settings",
            {
                "source_mode": "local",
                "local_path": str(self.base / "route-wdm"),
            },
        )

        self.assertEqual(303, status)
        self.assertEqual("/settings?saved=1", headers["location"])
        self.assertEqual(str(self.base / "route-wdm"), self.web.load_source_settings()["local_path"])

    def test_run_web_opens_existing_server_without_rebinding_port(self) -> None:
        class FakeResponse:
            headers = {"Server": "AIManagementWeb/1.0 Python/3.14.5"}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps({"version": self_web.APP_VERSION}).encode("utf-8")

        self_web = self.web
        opened: list[str] = []
        server_calls: list[object] = []
        original_urlopen = self.web.urllib.request.urlopen
        original_open = self.web.webbrowser.open
        original_server = self.web.ReloadableThreadingHTTPServer
        original_ensure = self.web.ensure_source_root
        try:
            self.web.urllib.request.urlopen = lambda request, timeout=0: FakeResponse()
            self.web.webbrowser.open = lambda url: opened.append(url)
            self.web.ReloadableThreadingHTTPServer = lambda *args, **kwargs: server_calls.append(args) or None
            self.web.ensure_source_root = lambda: None

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = self.web.run_web(host="0.0.0.0", port=8765, open_browser=True)

            self.assertEqual(0, result)
            self.assertIn("already running at http://127.0.0.1:8765/", output.getvalue())
            self.assertEqual(["http://127.0.0.1:8765/"], opened)
            self.assertEqual([], server_calls)
        finally:
            self.web.urllib.request.urlopen = original_urlopen
            self.web.webbrowser.open = original_open
            self.web.ReloadableThreadingHTTPServer = original_server
            self.web.ensure_source_root = original_ensure

    def test_run_web_reports_stale_or_unknown_server_when_bind_reports_port_in_use(self) -> None:
        opened: list[str] = []
        original_probe = self.web.web_server_responding
        original_open = self.web.webbrowser.open
        original_server = self.web.ReloadableThreadingHTTPServer
        original_ensure = self.web.ensure_source_root
        original_stop = self.web.stop_stale_ai_management_server
        try:
            self.web.web_server_responding = lambda host, port: False
            self.web.webbrowser.open = lambda url: opened.append(url)
            self.web.ensure_source_root = lambda: None
            self.web.stop_stale_ai_management_server = lambda host, port: False

            def busy_server(*args, **kwargs):
                raise OSError(self.web.errno.EADDRINUSE, "Address already in use")

            self.web.ReloadableThreadingHTTPServer = busy_server

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = self.web.run_web(host="127.0.0.1", port=8765, open_browser=True)

            self.assertEqual(0, result)
            self.assertIn("Port 127.0.0.1:8765 is already in use by another process", output.getvalue())
            self.assertEqual([], opened)
        finally:
            self.web.web_server_responding = original_probe
            self.web.webbrowser.open = original_open
            self.web.ReloadableThreadingHTTPServer = original_server
            self.web.ensure_source_root = original_ensure
            self.web.stop_stale_ai_management_server = original_stop

    def test_run_web_stops_stale_ai_management_server_and_starts_new_server(self) -> None:
        events: list[str] = []
        opened: list[str] = []
        original_probe = self.web.web_server_responding
        original_open = self.web.webbrowser.open
        original_server = self.web.ReloadableThreadingHTTPServer
        original_ensure = self.web.ensure_source_root
        original_stop = self.web.stop_stale_ai_management_server
        try:
            self.web.web_server_responding = lambda host, port: False
            self.web.webbrowser.open = lambda url: opened.append(url)
            self.web.ensure_source_root = lambda: None
            self.web.stop_stale_ai_management_server = lambda host, port: events.append(f"stop:{host}:{port}") or True

            class FakeServer:
                server_port = 8765

                def __init__(self, *args, **kwargs):
                    events.append("bind")

                def serve_forever(self):
                    events.append("serve")

                def server_close(self):
                    events.append("close")

            self.web.ReloadableThreadingHTTPServer = FakeServer

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = self.web.run_web(host="127.0.0.1", port=8765, open_browser=True)

            self.assertEqual(0, result)
            self.assertEqual(["stop:127.0.0.1:8765", "bind", "serve", "close"], events)
            self.assertIn("AI Management web UI running at http://127.0.0.1:8765/", output.getvalue())
            self.assertEqual([], opened)
        finally:
            self.web.web_server_responding = original_probe
            self.web.webbrowser.open = original_open
            self.web.ReloadableThreadingHTTPServer = original_server
            self.web.ensure_source_root = original_ensure
            self.web.stop_stale_ai_management_server = original_stop

    def test_legacy_ai_management_server_without_version_endpoint_is_detected(self) -> None:
        original_urlopen = self.web.urllib.request.urlopen
        try:
            def raise_legacy_404(request, timeout=0):
                raise self.web.urllib.error.HTTPError(
                    url="http://127.0.0.1:8765/api/app-version",
                    code=404,
                    msg="Not Found",
                    hdrs={"Server": "AIManagementWeb/1.0 Python/3.14.5"},
                    fp=None,
                )

            self.web.urllib.request.urlopen = raise_legacy_404

            is_wdm_server, version = self.web.running_ai_management_server("127.0.0.1", 8765)

            self.assertTrue(is_wdm_server)
            self.assertIsNone(version)
        finally:
            self.web.urllib.request.urlopen = original_urlopen

    def test_install_counts_global_and_project_markers(self) -> None:
        self.write_agent("alpha")
        self.write_agent("beta")
        self.web.save_installed_type("agents", ["alpha"])
        project_installed = self.project / ".wdm" / "installed" / "agents.conf"
        project_installed.parent.mkdir(parents=True)
        project_installed.write_text("alpha\nbeta\n", encoding="utf-8")

        self.assertEqual({"alpha": 2, "beta": 1}, self.web.install_counts("agents", ["alpha", "beta"]))

    def test_group_and_template_memberships_expand_wildcards(self) -> None:
        self.write_agent("alpha")
        self.write_agent("beta")
        self.write_group("core", "[agents]\nalpha\n")
        self.write_template(
            "agent-standard",
            "name: agent-standard\ntype: agents\ndescription: Agent template\nsections:\n  - title: Mission\nfields: {}\n",
        )
        self.write_template("agent-set", "# Agent set\n[agents]\n*\n[groups]\ncore\n")

        group_names, groups = self.web.group_memberships("agents")
        templates = self.web.template_memberships("agents")

        self.assertEqual(["core"], group_names)
        self.assertEqual(["core"], groups["alpha"])
        self.assertEqual(["agent-set"], templates["alpha"])
        self.assertEqual(["agent-set"], templates["beta"])

    def test_selection_filter_defaults_search_group_harness_and_hide_global(self) -> None:
        normalized = self.web.normalize_selection_filters({}, ["core"])
        self.assertEqual(["core"], normalized["groups"])
        self.assertTrue(normalized["group_none"])
        self.assertEqual(self.web.DEFAULT_SELECTION_SORT, normalized["sort"])
        self.assertEqual("20", normalized["per_page"])

        filtered = self.web.normalize_selection_filters(
            {
                "q": "api",
                "group_filter": "1",
                "group": ["core"],
                "harness_filter": "1",
                "harness": ["codex"],
                "hide_global_loaded": "1",
                "per_page": "500",
                "sort": "unknown",
                "source": "external",
            },
            ["core"],
        )
        self.assertEqual("api", filtered["q"])
        self.assertEqual(["core"], filtered["groups"])
        self.assertEqual(["codex"], filtered["harnesses"])
        self.assertEqual(str(self.web.MAX_SELECTION_ITEMS_PER_PAGE), filtered["per_page"])
        self.assertEqual(self.web.DEFAULT_SELECTION_SORT, filtered["sort"])
        self.assertEqual("external", filtered["source_mode"])

        items = [
            {
                "name": "api-agent",
                "description": "API work",
                "groups": ["core"],
                "path": "/tmp/api-agent.md",
                "global_loaded": True,
                "project_loaded": False,
                "harness_statuses": {"codex": {"checked": True}},
            },
            {
                "name": "project-api",
                "description": "API work",
                "groups": ["core"],
                "path": "/tmp/project-api.md",
                "global_loaded": True,
                "project_loaded": True,
                "harness_statuses": {"codex": {"checked": True}},
            },
            {
                "name": "other",
                "description": "No match",
                "groups": [],
                "path": "/tmp/other.md",
                "global_loaded": False,
                "project_loaded": False,
                "harness_statuses": {},
            },
        ]

        self.assertEqual(["project-api"], [item["name"] for item in self.web.filter_selection_items(items, filtered)])

    def test_external_filtering_sorting_and_query_params(self) -> None:
        filters = self.web.normalize_selection_filters(
            {"harness_filter": "1", "harness": ["codex"], "q": "external", "group_filter": "1", "group": [self.web.HARNESS_NONE_VALUE]},
            [],
        )
        items = [
            {"name": "external-alpha", "description": "External", "path": "/tmp/a", "harness": "codex", "harness_label": "Codex", "created_ts": "2", "modified_ts": "1"},
            {"name": "external-beta", "description": "External", "path": "/tmp/b", "harness": "claude", "harness_label": "Claude", "created_ts": "1", "modified_ts": "3"},
        ]

        filtered = self.web.filter_external_items(items, filters)
        self.assertEqual(["external-alpha"], [item["name"] for item in filtered])

        sorted_items = self.web.sort_external_items(items, "modified-desc")
        self.assertEqual(["external-beta", "external-alpha"], [item["name"] for item in sorted_items])

        query = self.web.selection_query_params({**filters, "source_mode": "combined", "template_type": "skills"})
        self.assertIn("q=external", query)
        self.assertIn("harness=codex", query)
        self.assertIn("source=combined", query)
        self.assertIn("template_type=skills", query)

    def test_sort_selection_items_all_sort_modes(self) -> None:
        items = [
            {"name": "beta", "install_count": "1", "created_ts": "2", "modified_ts": "3"},
            {"name": "alpha", "install_count": "3", "created_ts": "1", "modified_ts": "4"},
        ]

        self.assertEqual(["alpha", "beta"], [item["name"] for item in self.web.sort_selection_items(items, "name-asc")])
        self.assertEqual(["beta", "alpha"], [item["name"] for item in self.web.sort_selection_items(items, "name-desc")])
        self.assertEqual(["alpha", "beta"], [item["name"] for item in self.web.sort_selection_items(items, "installed-desc")])
        self.assertEqual(["beta", "alpha"], [item["name"] for item in self.web.sort_selection_items(items, "installed-asc")])
        self.assertEqual(["beta", "alpha"], [item["name"] for item in self.web.sort_selection_items(items, "created-desc")])
        self.assertEqual(["alpha", "beta"], [item["name"] for item in self.web.sort_selection_items(items, "modified-desc")])

    def test_template_definitions_body_sections_hooks_and_reasoning_helpers(self) -> None:
        definition = self.web.template_definition_from_raw(
            """
name: custom-agent
type: agents
description: Custom
fields:
  description: Starter
sections:
  - title: Mission
    level: 2
field_sections:
  developer_instructions:
    label: Should be removed
    sections:
      - title: Hidden
""",
            "custom-agent",
        )
        sanitized = self.web.sanitize_template_field_sections("agents", definition["field_sections"])
        self.assertNotIn("developer_instructions", sanitized)

        sections = self.web.split_body_sections("Intro\n\n## Mission\nBody\n\n```md\n# Not a heading\n```\n\n### Output\nDone\n")
        self.assertEqual(["Overview", "Mission", "Output"], [section["title"] for section in sections])

        parsed = self.web.parse_hook_script("#!/bin/sh\n# Runs checks\n# Before commit\n\necho ok\n")
        self.assertEqual("#!/bin/sh", parsed["shebang"])
        self.assertEqual("Runs checks\nBefore commit", parsed["description"])
        self.assertEqual("echo ok\n", parsed["script"])

        hook_dir = self.content_root / "hooks" / "core"
        hook_dir.mkdir(parents=True, exist_ok=True)
        (hook_dir / "node-test-pre-push").write_text("#!/usr/bin/env bash\n# Run Node tests before push\n\necho ok\n", encoding="utf-8")
        summary = self.web.item_summary("hooks", "node-test-pre-push")
        self.assertEqual("Run Node tests before push", summary["description"])
        card = self.web.render_selection_card(
            "hooks",
            summary,
            set(),
            "global",
            1,
            self.web.normalize_selection_filters({}, []),
        )
        self.assertIn("Run Node tests before push", card)
        self.assertNotIn("/hooks/core/node-test-pre-push", card)

        original_which = self.web.shutil.which
        try:
            self.web.shutil.which = lambda command: f"/usr/bin/{command}" if command in {"bash", "node"} else None
            interpreters = self.web.detected_hook_interpreters()
            self.assertEqual(["bash", "node"], [item["command"] for item in interpreters])
            detected_select = self.web.render_hook_interpreter_select("#!/usr/bin/env node")
            self.assertIn('<option value="#!/usr/bin/env node" selected>', detected_select)
            self.assertIn("data-hook-interpreter-custom hidden", detected_select)
            custom_select = self.web.render_hook_interpreter_select("#!/opt/custom/tool")
            self.assertIn('<option value="__custom__" selected>Custom</option>', custom_select)
            self.assertIn('value="#!/opt/custom/tool"', custom_select)
        finally:
            self.web.shutil.which = original_which

        custom_hook = self.web.serialize_hook_script(
            {
                "hook_shebang_choice": "__custom__",
                "hook_shebang_custom": "#!/opt/custom/tool",
                "hook_description": "Custom runtime",
                "hook_script": "echo ok",
            }
        )
        self.assertEqual("#!/opt/custom/tool\n# Custom runtime\necho ok\n", custom_hook)

        defaults = {"codex": {"default": {"model": "gpt-5", "model_reasoning_effort": "low"}}}
        self.assertEqual("low", self.web.default_reasoning_value("codex", "model_reasoning_effort", defaults))
        reasoning = self.web.render_reasoning_select("codex", "model_reasoning_effort", {}, defaults)
        self.assertIn("Default (Low)", reasoning)
        self.assertIn("<option value=\"medium\"", reasoning)

    def test_harness_destinations_statuses_and_scope_indicators(self) -> None:
        self.write_agent("alpha")
        self.web.update_harness_installation("agents", "alpha", self.project_scope, ["codex"])
        self.web.update_harness_installation("agents", "alpha", "global", ["claude"])

        project_statuses = self.web.harness_item_statuses("agents", "alpha", self.project_scope)
        global_statuses = self.web.harness_item_statuses("agents", "alpha", "global")

        self.assertTrue(project_statuses["codex"]["checked"])
        self.assertTrue(global_statuses["claude"]["checked"])
        self.assertTrue(self.web.is_loaded_globally("agents", "alpha", {"alpha"}, self.project_scope))

        global_harnesses = [name for name, status in global_statuses.items() if status["checked"]]
        project_harnesses = [name for name, status in project_statuses.items() if status["checked"]]
        icons = self.web.render_selection_scope_icons(global_harnesses, project_harnesses)
        self.assertIn("selection-card-scope-indicator global", icons)
        self.assertIn("selection-card-scope-indicator project", icons)
        self.assertIn("claude", icons)
        self.assertIn("codex", icons)

    def test_render_selection_page_combines_external_first_and_managed_under_pagination(self) -> None:
        self.write_agent("managed")
        external = self.project / ".codex" / "agents" / "external.toml"
        external.parent.mkdir(parents=True)
        external.write_text('name = "external"\ndescription = "External item"\ndeveloper_instructions = "Body"\n', encoding="utf-8")

        html = self.web.render_selection_page(
            "agents",
            [self.web.item_summary("agents", "managed")],
            set(),
            self.project_scope,
            1,
            {"source": "combined", "per_page": "1"},
        )

        self.assertIn("external-selection-card", html)
        self.assertIn("external", html)
        self.assertNotIn(">managed<", html)
        self.assertIn("Page 1 of 2", html)
