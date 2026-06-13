from __future__ import annotations

import importlib
import io
import json
import os
import shutil
import sys
import tempfile
from email.message import Message
import urllib.parse
import unittest
from pathlib import Path


def load_web_with_home(content_root: Path, home: Path):
    os.environ["AI_MANAGEMENT_HOME"] = str(content_root)
    os.environ["HOME"] = str(home)
    for module_name in list(sys.modules):
        if module_name == "ai_management" or module_name.startswith("ai_management."):
            del sys.modules[module_name]
    return importlib.import_module("ai_management.web")


class WebHarnessUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.content_root = self.base / ".wdm"
        self.home = self.base / "home"
        self.project = self.base / "project"
        self.home.mkdir(parents=True)
        self.project.mkdir(parents=True)
        self.web = load_web_with_home(self.content_root, self.home)
        self.write_project("Test Project", self.project)
        self.write_agent("smoke")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @property
    def project_scope(self) -> str:
        return f"project:{self.project}"

    def write_project(self, label: str, root: Path) -> None:
        self.content_root.mkdir(parents=True, exist_ok=True)
        (self.content_root / "projects.json").write_text(
            json.dumps([{"label": label, "root": str(root)}]),
            encoding="utf-8",
        )

    def write_agent(self, name: str, description: str = "Smoke test agent") -> None:
        agent_dir = self.content_root / "agents" / "core"
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / f"{name}.md").write_text(
            f"---\nname: {name}\ndescription: {description}\n---\n\nDo the smoke test.\n",
            encoding="utf-8",
        )

    def read_project_installed(self) -> str:
        path = self.project / ".wdm" / "installed" / "agents.conf"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def post_install(self, targets: list[str]) -> None:
        payload: list[tuple[str, str]] = [
            ("type", "agents"),
            ("name", "smoke"),
            ("action", "install"),
            ("harness_update", "1"),
            ("scope", self.project_scope),
            ("return_to", "/?type=agents"),
        ]
        payload.extend(("targets", target) for target in targets)
        data = urllib.parse.urlencode(payload).encode("utf-8")

        handler = object.__new__(self.web.ManagementHandler)
        handler.path = "/install"
        handler.command = "POST"
        handler.request_version = "HTTP/1.1"
        handler.requestline = "POST /install HTTP/1.1"
        handler.client_address = ("127.0.0.1", 0)
        handler.server = None
        handler.close_connection = True
        handler.rfile = io.BytesIO(data)
        handler.wfile = io.BytesIO()
        handler.log_message = lambda *args: None
        headers = Message()
        headers["Content-Length"] = str(len(data))
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        handler.headers = headers

        handler.do_POST()
        response = handler.wfile.getvalue().decode("iso-8859-1")
        self.assertIn("303", response)

    def post_bulk_install(self, names: list[str], targets: list[str]) -> None:
        payload: list[tuple[str, str]] = [
            ("type", "agents"),
            ("scope", self.project_scope),
            ("return_to", "/?type=agents"),
        ]
        payload.extend(("names", name) for name in names)
        payload.extend(("targets", target) for target in targets)
        data = urllib.parse.urlencode(payload).encode("utf-8")

        handler = object.__new__(self.web.ManagementHandler)
        handler.path = "/bulk-install"
        handler.command = "POST"
        handler.request_version = "HTTP/1.1"
        handler.requestline = "POST /bulk-install HTTP/1.1"
        handler.client_address = ("127.0.0.1", 0)
        handler.server = None
        handler.close_connection = True
        handler.rfile = io.BytesIO(data)
        handler.wfile = io.BytesIO()
        handler.log_message = lambda *args: None
        headers = Message()
        headers["Content-Length"] = str(len(data))
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        handler.headers = headers

        handler.do_POST()
        response = handler.wfile.getvalue().decode("iso-8859-1")
        self.assertIn("303", response)

    def test_project_update_creates_selected_harness_symlinks_and_marker(self) -> None:
        self.web.update_harness_installation("agents", "smoke", self.project_scope, ["codex", "claude", "copilot"])

        self.assertTrue((self.project / ".codex" / "agents" / "smoke.toml").is_symlink())
        self.assertTrue((self.project / ".claude" / "agents" / "smoke.md").is_symlink())
        self.assertTrue((self.project / ".github" / "agents" / "smoke.agent.md").is_symlink())
        self.assertIn("smoke", self.read_project_installed())

        statuses = self.web.harness_item_statuses("agents", "smoke", self.project_scope)
        self.assertTrue(statuses["codex"]["checked"])
        self.assertTrue(statuses["claude"]["checked"])
        self.assertTrue(statuses["copilot"]["checked"])

    def test_install_post_preserves_multiple_harness_targets(self) -> None:
        self.post_install(["codex", "claude"])

        self.assertTrue((self.project / ".codex" / "agents" / "smoke.toml").is_symlink())
        self.assertTrue((self.project / ".claude" / "agents" / "smoke.md").is_symlink())

    def test_install_post_with_no_targets_removes_existing_harnesses(self) -> None:
        self.web.update_harness_installation("agents", "smoke", self.project_scope, ["codex", "claude"])

        self.post_install([])

        self.assertFalse((self.project / ".codex" / "agents" / "smoke.toml").exists())
        self.assertFalse((self.project / ".claude" / "agents" / "smoke.md").exists())
        self.assertEqual("", self.read_project_installed())

    def test_project_update_removes_only_deselected_harness_symlink(self) -> None:
        self.web.update_harness_installation("agents", "smoke", self.project_scope, ["codex", "claude"])
        self.web.update_harness_installation("agents", "smoke", self.project_scope, ["claude"])

        self.assertFalse((self.project / ".codex" / "agents" / "smoke.toml").exists())
        self.assertTrue((self.project / ".claude" / "agents" / "smoke.md").is_symlink())
        self.assertIn("smoke", self.read_project_installed())

    def test_project_update_with_no_targets_removes_all_managed_symlinks_and_marker(self) -> None:
        self.web.update_harness_installation("agents", "smoke", self.project_scope, ["codex", "claude"])
        self.web.update_harness_installation("agents", "smoke", self.project_scope, [])

        self.assertFalse((self.project / ".codex" / "agents" / "smoke.toml").exists())
        self.assertFalse((self.project / ".claude" / "agents" / "smoke.md").exists())
        self.assertEqual("", self.read_project_installed())

    def test_bulk_update_sets_selected_harnesses_for_multiple_items(self) -> None:
        self.write_agent("alpha")
        self.write_agent("beta")
        self.web.bulk_update_harness_installation("agents", ["alpha", "beta"], self.project_scope, ["codex", "claude"])

        self.assertTrue((self.project / ".codex" / "agents" / "alpha.toml").is_symlink())
        self.assertTrue((self.project / ".claude" / "agents" / "alpha.md").is_symlink())
        self.assertTrue((self.project / ".codex" / "agents" / "beta.toml").is_symlink())
        self.assertTrue((self.project / ".claude" / "agents" / "beta.md").is_symlink())

        self.web.bulk_update_harness_installation("agents", ["alpha", "beta"], self.project_scope, ["claude"])

        self.assertFalse((self.project / ".codex" / "agents" / "alpha.toml").exists())
        self.assertTrue((self.project / ".claude" / "agents" / "alpha.md").is_symlink())
        self.assertFalse((self.project / ".codex" / "agents" / "beta.toml").exists())
        self.assertTrue((self.project / ".claude" / "agents" / "beta.md").is_symlink())

    def test_bulk_install_post_updates_selected_items(self) -> None:
        self.write_agent("alpha")
        self.write_agent("beta")

        self.post_bulk_install(["alpha", "beta"], ["codex"])

        self.assertTrue((self.project / ".codex" / "agents" / "alpha.toml").is_symlink())
        self.assertTrue((self.project / ".codex" / "agents" / "beta.toml").is_symlink())
        installed = set(self.read_project_installed().splitlines())
        self.assertEqual({"alpha", "beta"}, installed)

    def test_global_update_uses_fake_home_and_global_installed_marker(self) -> None:
        self.web.update_harness_installation("agents", "smoke", "global", ["codex"])

        self.assertTrue((self.home / ".codex" / "agents" / "smoke.toml").is_symlink())
        self.assertIn("smoke", set(self.web.load_installed_type("agents")))

        self.web.update_harness_installation("agents", "smoke", "global", [])
        self.assertFalse((self.home / ".codex" / "agents" / "smoke.toml").exists())
        self.assertNotIn("smoke", set(self.web.load_installed_type("agents")))

    def test_deselect_does_not_delete_external_real_files(self) -> None:
        external = self.project / ".claude" / "agents" / "smoke.md"
        external.parent.mkdir(parents=True, exist_ok=True)
        external.write_text("external agent\n", encoding="utf-8")

        self.web.update_harness_installation("agents", "smoke", self.project_scope, [])

        self.assertTrue(external.exists())
        self.assertFalse(external.is_symlink())
        self.assertEqual("external agent\n", external.read_text(encoding="utf-8"))

    def test_project_installed_marker_merges_legacy_installed_file(self) -> None:
        legacy = self.project / ".ai-management" / "installed" / "agents.conf"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text("legacy-agent\n", encoding="utf-8")

        self.web.update_harness_installation("agents", "smoke", self.project_scope, ["claude"])

        installed = set(self.read_project_installed().splitlines())
        self.assertEqual({"legacy-agent", "smoke"}, installed)

    def test_selection_card_posts_harness_update_marker(self) -> None:
        item = {
            "name": "smoke",
            "description": "Smoke test agent",
            "path": str(self.content_root / "agents" / "core" / "smoke.md"),
            "groups": [],
            "created_at": "1 Jun 26 10:00",
            "modified_at": "1 Jun 26 10:00",
            "install_count": 0,
            "harness_statuses": self.web.harness_item_statuses("agents", "smoke", self.project_scope),
        }

        html = self.web.render_selection_card("agents", item, set(), self.project_scope, 1, {})

        self.assertIn('name="harness_update" value="1"', html)
        self.assertIn('name="targets"', html)
        self.assertIn('form="bulk-harness-update-form"', html)
        self.assertIn('data-bulk-card-selection', html)

    def test_selection_page_renders_bulk_update_form_for_content_types(self) -> None:
        html = self.web.render_selection_page(
            "agents",
            [self.web.item_summary("agents", "smoke")],
            set(),
            self.project_scope,
            1,
            {},
        )

        self.assertIn('action="/bulk-install"', html)
        self.assertIn("Select visible", html)
        self.assertIn("Update selected", html)
        self.assertIn('action="/validate-all"', html)
        self.assertIn("Validate all Agents", html)
        self.assertIn("split-dropdown", html)

        paged = self.web.render_bulk_update_form("agents", self.project_scope, {"sort": "name-desc"}, 3)
        self.assertIn("page=3", paged)
        self.assertIn("sort=name-desc", paged)

    def test_preview_actions_include_validate_button(self) -> None:
        html = self.web.page("agents", None, self.project_scope, "")

        self.assertIn("data-preview-validate", html)
        self.assertIn("/validate-item", html)

    def test_unknown_item_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown agents item"):
            self.web.update_harness_installation("agents", "missing", self.project_scope, ["codex"])

    def test_bulk_update_requires_selection(self) -> None:
        with self.assertRaisesRegex(ValueError, "Select at least one item"):
            self.web.bulk_update_harness_installation("agents", [], self.project_scope, ["codex"])


if __name__ == "__main__":
    unittest.main()
