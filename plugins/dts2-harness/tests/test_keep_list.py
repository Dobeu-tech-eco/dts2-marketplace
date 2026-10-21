"""Project keep list (.harness/keep.yaml) contracts."""
from __future__ import annotations

import importlib.util
from pathlib import Path
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


class MachinePrepKeepListTests(unittest.TestCase):
    def load(self):  # type: ignore[no-untyped-def]
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "machine_prep_under_test", PLUGIN_ROOT / "scripts" / "machine-prep.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_keep_list_plugins_merge_into_required_by_harness(self) -> None:
        import tempfile
        mod = self.load()
        project: Path = Path(tempfile.mkdtemp(prefix="dts2-keep-"))
        (project / ".harness").mkdir()
        (project / ".harness" / "keep.yaml").write_text(
            "plugins:\n  - dts2-harness@dts2\n  - impeccable@impeccable  # ui\nskills:\n  - name: x\n",
            encoding="utf-8",
        )
        self.assertEqual(
            mod.keep_list_plugins(project), ["dts2-harness@dts2", "impeccable@impeccable"]
        )
        merged: dict = mod.with_keep_list({"requiredByHarness": ["marketing-skills@synced"]}, project)
        self.assertEqual(
            merged["requiredByHarness"],
            ["marketing-skills@synced", "dts2-harness@dts2", "impeccable@impeccable"],
        )

    def test_no_keep_file_leaves_profile_unchanged(self) -> None:
        import tempfile
        mod = self.load()
        project: Path = Path(tempfile.mkdtemp(prefix="dts2-nokeep-"))
        profile: dict = {"requiredByHarness": ["a@b"]}
        self.assertIs(mod.with_keep_list(profile, project), profile)
