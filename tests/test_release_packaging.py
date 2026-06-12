from __future__ import annotations

from pathlib import Path
import unittest


class ReleasePackagingTests(unittest.TestCase):
    def test_homebrew_formula_does_not_bootstrap_inside_install_sandbox(self) -> None:
        formula = Path("Formula/wdm-ai-management.rb").read_text(encoding="utf-8")

        self.assertNotIn("def post_install", formula)
        self.assertNotIn("bootstrap", formula)


if __name__ == "__main__":
    unittest.main()
