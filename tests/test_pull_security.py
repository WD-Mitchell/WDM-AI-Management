from __future__ import annotations

import io
import tarfile

from helpers import TempWDMTestCase


class PullSecurityTests(TempWDMTestCase):
    def test_safe_extract_tar_extracts_normal_members(self) -> None:
        pull = self.load("ai_management.pull")
        archive = self.base / "safe.tar.gz"
        destination = self.base / "extract"
        payload = b"hello"

        with tarfile.open(archive, "w:gz") as tar:
            info = tarfile.TarInfo("repo/agents/core/alpha.md")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))

        pull.safe_extract_tar(archive, destination)

        self.assertEqual("hello", (destination / "repo" / "agents" / "core" / "alpha.md").read_text(encoding="utf-8"))

    def test_safe_extract_tar_rejects_path_traversal(self) -> None:
        pull = self.load("ai_management.pull")
        archive = self.base / "unsafe.tar.gz"
        destination = self.base / "extract"
        payload = b"owned"

        with tarfile.open(archive, "w:gz") as tar:
            info = tarfile.TarInfo("../outside.txt")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))

        with self.assertRaisesRegex(pull.CLIError, "Unsafe tarball path"):
            pull.safe_extract_tar(archive, destination)

        self.assertFalse((self.base / "outside.txt").exists())

    def test_safe_extract_tar_rejects_symlink_members(self) -> None:
        pull = self.load("ai_management.pull")
        archive = self.base / "unsafe-link.tar.gz"
        destination = self.base / "extract"

        with tarfile.open(archive, "w:gz") as tar:
            info = tarfile.TarInfo("repo/link")
            info.type = tarfile.SYMTYPE
            info.linkname = "../../outside.txt"
            tar.addfile(info)

        with self.assertRaisesRegex(pull.CLIError, "Unsafe tarball link"):
            pull.safe_extract_tar(archive, destination)
