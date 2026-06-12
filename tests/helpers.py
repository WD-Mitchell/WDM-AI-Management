from __future__ import annotations

import importlib
import io
import json
import os
import sys
import tempfile
import urllib.parse
import unittest
from email.message import Message
from pathlib import Path


def clear_ai_management_modules() -> None:
    for module_name in list(sys.modules):
        if module_name == "ai_management" or module_name.startswith("ai_management."):
            del sys.modules[module_name]


def load_module_with_home(module_name: str, content_root: Path, home: Path):
    os.environ["AI_MANAGEMENT_HOME"] = str(content_root)
    os.environ["HOME"] = str(home)
    clear_ai_management_modules()
    return importlib.import_module(module_name)


class TempWDMTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.content_root = self.base / ".wdm"
        self.home = self.base / "home"
        self.project = self.base / "project"
        self.home.mkdir(parents=True)
        self.project.mkdir(parents=True)

    def tearDown(self) -> None:
        clear_ai_management_modules()
        self.tmp.cleanup()

    @property
    def project_scope(self) -> str:
        return f"project:{self.project}"

    def load(self, module_name: str):
        return load_module_with_home(module_name, self.content_root, self.home)

    def load_web(self):
        return self.load("ai_management.web")

    def write_projects(self, *projects: tuple[str, Path]) -> None:
        self.content_root.mkdir(parents=True, exist_ok=True)
        payload = [{"label": label, "root": str(root)} for label, root in projects]
        (self.content_root / "projects.json").write_text(json.dumps(payload), encoding="utf-8")

    def write_agent(self, name: str, description: str = "Smoke test agent", body: str = "Do the smoke test.\n") -> Path:
        path = self.content_root / "agents" / "core" / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\nname: {name}\ndescription: {description}\n---\n\n{body}", encoding="utf-8")
        return path

    def write_skill(self, name: str, description: str = "Smoke test skill", body: str = "Use this skill.\n") -> Path:
        path = self.content_root / "skills" / "core" / name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\nname: {name}\ndescription: {description}\n---\n\n{body}", encoding="utf-8")
        return path

    def write_mcp(self, name: str, raw: str) -> Path:
        path = self.content_root / "mcp" / "core" / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw, encoding="utf-8")
        return path

    def write_group(self, name: str, raw: str) -> Path:
        path = self.content_root / "groups" / f"{name}.group"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw, encoding="utf-8")
        return path

    def write_template(self, name: str, raw: str) -> Path:
        path = self.content_root / "templates" / "core" / f"{name}.template"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw, encoding="utf-8")
        return path

    def post_form(self, web, path: str, payload: list[tuple[str, str]] | dict[str, str], *, accept_json: bool = False) -> tuple[int, str, dict[str, str]]:
        if isinstance(payload, dict):
            payload = list(payload.items())
        data = urllib.parse.urlencode(payload).encode("utf-8")

        handler = object.__new__(web.ManagementHandler)
        handler.path = path
        handler.command = "POST"
        handler.request_version = "HTTP/1.1"
        handler.requestline = f"POST {path} HTTP/1.1"
        handler.client_address = ("127.0.0.1", 0)
        handler.server = None
        handler.close_connection = True
        handler.rfile = io.BytesIO(data)
        handler.wfile = io.BytesIO()
        handler.log_message = lambda *args: None
        headers = Message()
        headers["Content-Length"] = str(len(data))
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        if accept_json:
            headers["Accept"] = "application/json"
            headers["X-Requested-With"] = "fetch"
        handler.headers = headers

        handler.do_POST()
        response = handler.wfile.getvalue().decode("iso-8859-1")
        status_line = response.splitlines()[0]
        status = int(status_line.split()[1])
        response_headers: dict[str, str] = {}
        header_block = response.split("\r\n\r\n", 1)[0]
        for line in header_block.splitlines()[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                response_headers[key.lower()] = value.strip()
        body = response.split("\r\n\r\n", 1)[1] if "\r\n\r\n" in response else ""
        return status, body, response_headers
