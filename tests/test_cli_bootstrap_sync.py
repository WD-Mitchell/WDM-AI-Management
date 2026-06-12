from __future__ import annotations

import contextlib
import io
import json
import os
import zipfile
from pathlib import Path

from helpers import TempWDMTestCase


class CliBootstrapAndSyncTests(TempWDMTestCase):
    def test_install_cli_dispatches_type_group_all_and_uninstall_commands(self) -> None:
        cli = self.load("ai_management.cli")
        calls: list[tuple[str, object, object]] = []
        cli.install_type = lambda content_type, names: calls.append(("install_type", content_type, names))
        cli.uninstall_type = lambda content_type, names: calls.append(("uninstall_type", content_type, names))
        cli.install_group = lambda group, only_type="": calls.append(("install_group", group, only_type))
        cli.install_all = lambda only_type="": calls.append(("install_all", only_type, None))

        self.assertEqual(0, cli.install_cli(["--install-agent", "alpha, beta"]))
        self.assertEqual(0, cli.install_cli(["--uninstall-skill", "docs,testing"]))
        self.assertEqual(0, cli.install_cli(["--install-group-mcp", "core"]))
        self.assertEqual(0, cli.install_cli(["--install-all-hooks"]))

        self.assertEqual(
            [
                ("install_type", "agents", ["alpha", "beta"]),
                ("uninstall_type", "skills", ["docs", "testing"]),
                ("install_group", "core", "mcp"),
                ("install_all", "hooks", None),
            ],
            calls,
        )

    def test_cli_rejects_old_wdm_entrypoint_and_unknown_options(self) -> None:
        cli = self.load("ai_management.cli")

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(1, cli.main(["sync"]))
        with self.assertRaisesRegex(cli.CLIError, "Unknown type"):
            cli.install_cli(["--install-all-unknown"])
        with self.assertRaisesRegex(cli.CLIError, "Provide names"):
            cli.install_cli(["--install-agent"])

    def test_web_cli_parses_host_port_open_reload_and_reports_bad_port(self) -> None:
        cli = self.load("ai_management.cli")
        import ai_management.web as web

        calls = []
        web.run_web = lambda **kwargs: calls.append(kwargs) or 42

        self.assertEqual(42, cli.web_cli(["--host", "0.0.0.0", "--port", "9000", "--open", "--reload"]))
        self.assertEqual(
            [{"host": "0.0.0.0", "port": 9000, "open_browser": True, "reload": True}],
            calls,
        )
        with self.assertRaisesRegex(cli.CLIError, "Port must be a number"):
            cli.web_cli(["--port", "not-a-port"])

    def test_bootstrap_cli_parses_flags_and_rejects_unknown_flags(self) -> None:
        cli = self.load("ai_management.cli")
        import ai_management.bootstrap as bootstrap

        calls = []
        bootstrap.bootstrap = lambda **kwargs: calls.append(kwargs)

        self.assertEqual(0, cli.bootstrap_cli(["--force", "--no-sync", "--quiet"]))
        self.assertEqual([{"force": True, "sync_skills": False, "quiet": True}], calls)
        with self.assertRaisesRegex(cli.CLIError, "Unknown bootstrap option"):
            cli.bootstrap_cli(["--bad"])

    def test_copy_missing_tree_respects_overwrite_and_skips_self_copy(self) -> None:
        bootstrap = self.load("ai_management.bootstrap")
        source = self.base / "source"
        dest = self.base / "dest"
        (source / "nested").mkdir(parents=True)
        (source / "nested" / "file.txt").write_text("new", encoding="utf-8")
        (dest / "nested").mkdir(parents=True)
        (dest / "nested" / "file.txt").write_text("old", encoding="utf-8")

        bootstrap.copy_missing_tree(source, dest, overwrite=False)
        self.assertEqual("old", (dest / "nested" / "file.txt").read_text(encoding="utf-8"))

        bootstrap.copy_missing_tree(source, dest, overwrite=True)
        self.assertEqual("new", (dest / "nested" / "file.txt").read_text(encoding="utf-8"))

        bootstrap.copy_missing_tree(dest, dest, overwrite=True)
        self.assertEqual("new", (dest / "nested" / "file.txt").read_text(encoding="utf-8"))

    def test_bootstrap_content_copies_defaults_templates_harnesses_and_cleans_legacy_skill_files(self) -> None:
        bootstrap = self.load("ai_management.bootstrap")

        legacy_skill = self.content_root / "skills" / "core" / "AI-Management"
        (legacy_skill / "ai_management").mkdir(parents=True, exist_ok=True)
        (legacy_skill / "install.sh").write_text("old installer", encoding="utf-8")
        (self.content_root / "skills" / "core" / "WDM-Agent-Management").mkdir(parents=True, exist_ok=True)

        bootstrap.bootstrap_content(overwrite=False)

        self.assertTrue((self.content_root / "defaults.conf").exists())
        self.assertTrue((self.content_root / "harnesses" / "core" / "codex.json").exists())
        self.assertTrue((self.content_root / "templates" / "core" / "agent-standard.template").exists())
        self.assertTrue((self.content_root / "skills" / "core" / "AI-Management" / "SKILL.md").exists())
        self.assertFalse((legacy_skill / "install.sh").exists())
        self.assertFalse((legacy_skill / "ai_management").exists())
        self.assertFalse((self.content_root / "skills" / "core" / "WDM-Agent-Management").exists())

    def test_install_bootstrap_skill_removes_legacy_and_preserves_existing(self) -> None:
        bootstrap = self.load("ai_management.bootstrap")

        class FakeInstall:
            saved: list[str] = []

            @staticmethod
            def load_installed_type(content_type: str) -> list[str]:
                self.assertEqual("skills", content_type)
                return ["Existing", "WDM-Agent-Management"]

            @staticmethod
            def save_installed_type(content_type: str, items: list[str]) -> None:
                self.assertEqual("skills", content_type)
                FakeInstall.saved = items

        bootstrap.install_bootstrap_skill(FakeInstall)
        self.assertEqual(["Existing", "AI-Management"], FakeInstall.saved)

    def test_sync_arg_parsing_and_runtime_paths(self) -> None:
        sync = self.load("ai_management.sync")

        options = sync.parse_sync_args(["codex", "claude", "--dry-run", "--refresh", "--group", "core", "--no-backup"])
        self.assertEqual(["codex", "claude"], options.targets)
        self.assertTrue(options.dry_run)
        self.assertTrue(options.refresh)
        self.assertFalse(options.backup)
        self.assertEqual(["core"], options.selected_groups)

        with self.assertRaisesRegex(sync.CLIError, "--group requires"):
            sync.parse_sync_args(["--group"])
        with self.assertRaisesRegex(sync.CLIError, "Unknown sync argument"):
            sync.parse_sync_args(["--bad"])

        global_options = sync.parse_sync_args(["codex", "--global"])
        sync.sync_init_runtime(global_options)
        self.assertEqual(self.home, global_options.target_root)
        self.assertEqual(self.home / ".codex" / "agents", global_options.codex_agents_dir)

    def test_generic_harness_paths_templates_skip_and_built_names(self) -> None:
        harness_dir = self.content_root / "harnesses" / "core"
        harness_dir.mkdir(parents=True, exist_ok=True)
        (harness_dir / "custom.json").write_text(
            json.dumps(
                {
                    "name": "custom",
                    "enabled": True,
                    "label": "Custom",
                    "sync": {
                        "paths": {
                            "project": {"agents": ".custom/agents/{output}", "mcp": ".custom/mcp.json"},
                            "global": {"agents": ".custom-global/agents/{output}"},
                        },
                        "skip": {"mcp_global": "No global MCP"},
                    },
                    "outputs": {"agents": {"extension": ".agent"}},
                }
            ),
            encoding="utf-8",
        )
        sync = self.load("ai_management.sync")
        options = sync.parse_sync_args(["custom"])
        options.target_root = self.project

        self.assertEqual({"agents": ".custom/agents/{output}", "mcp": ".custom/mcp.json"}, sync.generic_path_templates("custom", False))
        self.assertEqual("No global MCP", sync.generic_skip_reason(sync.ALL_HARNESS_DEFINITIONS["custom"], "mcp", True))
        self.assertEqual(self.project / ".custom" / "agents", sync.generic_managed_paths_for(options, "custom")["agents"])
        self.assertEqual("alpha.agent", sync.built_name_for("custom", "agents", Path("alpha.md")))
        self.assertEqual(Path(".custom/agents/alpha.md"), sync.format_harness_path(".custom/agents/{file}", Path("alpha.md")))

    def test_sync_resolve_selection_uses_installed_items_or_groups(self) -> None:
        self.write_agent("alpha")
        self.write_skill("docs")
        self.write_group("core", "[agents]\nalpha\n[skills]\ndocs\nmissing\n")
        install = self.load("ai_management.install")
        install.save_installed_type("agents", ["alpha"])
        sync = self.load("ai_management.sync")

        installed_options = sync.parse_sync_args(["codex"])
        sync.sync_resolve_selection(installed_options)
        self.assertEqual([self.content_root / "agents" / "core" / "alpha.md"], installed_options.resolved["agents"])

        group_options = sync.parse_sync_args(["codex", "--group", "core"])
        sync.sync_resolve_selection(group_options)
        self.assertEqual([self.content_root / "agents" / "core" / "alpha.md"], group_options.resolved["agents"])
        self.assertEqual([self.content_root / "skills" / "core" / "docs"], group_options.resolved["skills"])

        missing_group_options = sync.parse_sync_args(["codex", "--group", "missing"])
        with self.assertRaisesRegex(sync.CLIError, "Group file not found"):
            sync.sync_resolve_selection(missing_group_options)

    def test_make_link_purge_backup_and_restore_are_safe_in_temp_tree(self) -> None:
        sync = self.load("ai_management.sync")
        source = self.base / "built" / "agent.md"
        source.parent.mkdir(parents=True)
        source.write_text("agent", encoding="utf-8")
        dest = self.project / ".codex" / "agents" / "agent.md"

        sync.make_link(source, dest)
        self.assertTrue(dest.is_symlink())
        self.assertEqual(source.resolve(), dest.resolve())

        real_dir = self.project / ".codex" / "real-dir"
        real_dir.mkdir(parents=True)
        sync.make_link(source, real_dir)
        self.assertTrue(real_dir.is_dir())
        self.assertFalse(real_dir.is_symlink())

        sync.purge_symlinks_in(dest.parent)
        self.assertFalse(dest.exists())
        self.assertTrue(real_dir.exists())

        managed_file = self.project / ".codex" / "config.toml"
        managed_file.write_text("before", encoding="utf-8")
        managed_link = self.project / ".codex" / "linked.toml"
        os.symlink(str(source), managed_link)
        sync.backup_path("codex", "mcp", self.project / ".codex", self.project)
        backup_files = list((self.content_root / "backups").glob("codex_mcp_*.zip"))
        self.assertEqual(1, len(backup_files))
        managed_file.write_text("after", encoding="utf-8")
        managed_link.unlink()

        sync.restore_backup(backup_files[0], self.project)
        self.assertEqual("before", managed_file.read_text(encoding="utf-8"))
        self.assertTrue(managed_link.is_symlink())

    def test_mcp_sync_merges_codex_gemini_and_json_targets(self) -> None:
        sync = self.load("ai_management.sync")
        source = self.content_root / "mcp" / "core" / "filesystem.md"
        source.parent.mkdir(parents=True)
        source.write_text("---\nname: filesystem\ncommand: npx\n---\n", encoding="utf-8")
        for harness, suffix, raw in (
            ("claude", ".json", '{"command": "npx"}'),
            ("codex", ".toml", '[mcp_servers.filesystem]\ncommand = "npx"\n'),
            ("gemini", ".json", '{"command": "npx"}'),
        ):
            built = self.content_root / "mcp" / harness / f"filesystem{suffix}"
            built.parent.mkdir(parents=True, exist_ok=True)
            built.write_text(raw, encoding="utf-8")

        options = sync.parse_sync_args(["codex", "gemini", "claude"])
        options.target_root = self.project
        sync.sync_init_runtime(options)
        options.target_root = self.project
        options.codex_config_toml = self.project / ".codex" / "config.toml"
        options.gemini_settings_file = self.project / ".gemini" / "settings.json"
        options.resolved["mcp"] = [source]

        sync.sync_mcp_to("claude", "Claude", self.project / ".mcp.json", [source])
        self.assertEqual({"command": "npx"}, json.loads((self.project / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["filesystem"])

        options.codex_config_toml.parent.mkdir(parents=True, exist_ok=True)
        options.codex_config_toml.write_text('model = "gpt-5"\n\n# >>> ai-management mcp_servers (DO NOT EDIT) >>>\nold = "value"\n# <<< ai-management mcp_servers <<<\n', encoding="utf-8")
        sync.sync_codex_mcp(options)
        codex_text = options.codex_config_toml.read_text(encoding="utf-8")
        self.assertIn('model = "gpt-5"', codex_text)
        self.assertIn("[mcp_servers.filesystem]", codex_text)
        self.assertNotIn('old = "value"', codex_text)

        options.gemini_settings_file.parent.mkdir(parents=True, exist_ok=True)
        options.gemini_settings_file.write_text('{"theme": "dark"}', encoding="utf-8")
        sync.sync_gemini_mcp(options)
        gemini = json.loads(options.gemini_settings_file.read_text(encoding="utf-8"))
        self.assertEqual("dark", gemini["theme"])
        self.assertEqual({"command": "npx"}, gemini["mcpServers"]["filesystem"])

    def test_sync_items_and_copilot_rules_use_built_outputs(self) -> None:
        sync = self.load("ai_management.sync")
        source_agent = self.content_root / "agents" / "core" / "alpha.md"
        source_rule = self.content_root / "rules" / "core" / "secure.md"
        source_agent.parent.mkdir(parents=True)
        source_rule.parent.mkdir(parents=True)
        source_agent.write_text("source", encoding="utf-8")
        source_rule.write_text("rule source", encoding="utf-8")
        built_agent = self.content_root / "agents" / "codex" / "alpha.md"
        built_rule = self.content_root / "rules" / "copilot" / "secure.md"
        built_agent.parent.mkdir(parents=True, exist_ok=True)
        built_rule.parent.mkdir(parents=True, exist_ok=True)
        built_agent.write_text("built agent", encoding="utf-8")
        built_rule.write_text("Built rule body", encoding="utf-8")

        target_dir = self.project / ".codex" / "agents"
        sync.sync_items_to(target_dir, "codex", "agents", [source_agent], label="Codex")
        self.assertTrue((target_dir / "alpha.md").is_symlink())
        self.assertEqual(built_agent.resolve(), (target_dir / "alpha.md").resolve())

        options = sync.parse_sync_args(["copilot"])
        sync.sync_init_runtime(options)
        options.target_root = self.project
        options.copilot_rules_dir = self.project / ".github"
        options.resolved["rules"] = [source_rule]
        sync.sync_copilot_rules_project(options)
        output = (self.project / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")
        self.assertIn("MANAGED BY wdm-ai", output)
        self.assertIn("## secure", output)
        self.assertIn("Built rule body", output)
