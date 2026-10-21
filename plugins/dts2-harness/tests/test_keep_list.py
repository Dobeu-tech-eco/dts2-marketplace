"""Project keep list (.harness/keep.yaml) contracts."""
from __future__ import annotations

import importlib.util
import unittest
from typing import Final

from helpers import PLUGIN_ROOT

REQUIRED_KEYS: Final[tuple[str, ...]] = ("plugins:", "skills:", "agents:")


def read(rel: str) -> str:
    return (PLUGIN_ROOT / rel).read_text(encoding="utf-8")


class KeepListTests(unittest.TestCase):
    def test_template_has_three_keys(self) -> None:
        text: str = read("templates/keep.yaml")
        for key in REQUIRED_KEYS:
            self.assertIn(key, text)

    def test_setup_run_machine_prep_mention_keep(self) -> None:
        setup: str = read("skills/setup/SKILL.md")
        self.assertIn("keep.yaml", setup)
        self.assertIn("never re-ask", setup)
        self.assertIn("keep.yaml", read("skills/run/SKILL.md"))
        self.assertIn("keep.yaml", read("skills/machine-prep/SKILL.md"))

    def test_keep_yaml_is_not_ignored(self) -> None:
        spec = importlib.util.spec_from_file_location("ensure_ignored", PLUGIN_ROOT / "scripts" / "ensure-ignored.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertFalse(any("keep.yaml" in entry for entry in module.IGNORED_PATHS))


if __name__ == "__main__":
    unittest.main()
