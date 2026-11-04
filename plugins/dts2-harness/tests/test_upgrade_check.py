"""scripts/upgrade-check.py and the upgrade flow in the run Pre-check."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "upgrade-check.py"
PLUGIN_JSON: Final[Path] = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
RELEASE: Final[str] = "3.7.0"


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("upgrade_check_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    sys.modules["upgrade_check_under_test"] = module
    spec.loader.exec_module(module)
    return module


def description_of(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("description:"):
            return line[len("description:"):].strip()
    return ""


def run_cli(*args: str) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True, check=True,
    )
    parsed: dict[str, Any] = json.loads(result.stdout)
    return parsed


class CompareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod: ModuleType = load_module()

    def test_read_version(self) -> None:
        self.assertEqual(self.mod.read_version(PLUGIN_JSON), RELEASE)

    def test_advanced(self) -> None:
        self.assertTrue(self.mod.compare("3.4.0", "3.5.0")["advanced"])
        self.assertTrue(self.mod.compare("3.9.0", "3.10.0")["advanced"])

    def test_same(self) -> None:
        result: dict[str, Any] = self.mod.compare("3.5.0", "3.5.0")
        self.assertTrue(result["same"])
        self.assertFalse(result["advanced"])

    def test_downgrade_is_not_advanced(self) -> None:
        result: dict[str, Any] = self.mod.compare("3.5.0", "3.4.0")
        self.assertFalse(result["advanced"])
        self.assertFalse(result["same"])

    def test_non_numeric_never_raises(self) -> None:
        for pair in (("3.5.0-beta", "3.5.0"), ("abc", "3.5.0"), ("", "3.5.0"), ("3.5", "3.5.0")):
            result: dict[str, Any] = self.mod.compare(*pair)
            self.assertEqual(set(result), {"from", "to", "advanced", "same"})

    def test_short_and_long_versions_compare_equal(self) -> None:
        self.assertTrue(self.mod.compare("3.5", "3.5.0")["same"])


class CliTests(unittest.TestCase):
    def write(self, text: str) -> str:
        path: Path = Path(tempfile.mkdtemp(prefix="dts2-upgrade-")) / "upgrade-from.txt"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_advanced_from_file(self) -> None:
        data: dict[str, Any] = run_cli("--from-file", self.write("3.4.0\n"))
        self.assertEqual(data, {"from": "3.4.0", "to": RELEASE, "advanced": True, "same": False})

    def test_same_from_file(self) -> None:
        data: dict[str, Any] = run_cli("--from-file", self.write(RELEASE))
        self.assertTrue(data["same"])
        self.assertFalse(data["advanced"])

    def test_missing_from_file(self) -> None:
        missing: str = str(Path(tempfile.mkdtemp()) / "nope.txt")
        data: dict[str, Any] = run_cli("--from-file", missing)
        self.assertIsNone(data["from"])
        self.assertFalse(data["advanced"])

    def test_plugin_json_override(self) -> None:
        other: Path = Path(tempfile.mkdtemp()) / "plugin.json"
        other.write_text(json.dumps({"version": "9.0.0"}), encoding="utf-8")
        data: dict[str, Any] = run_cli("--from-file", self.write("3.5.0"), "--plugin-json", str(other))
        self.assertEqual(data["to"], "9.0.0")
        self.assertTrue(data["advanced"])


class PrecheckUpgradeTests(unittest.TestCase):
    """The upgrade flow lives in the run Pre-check; there is no standalone upgrade skill."""

    def test_no_standalone_upgrade_skill(self) -> None:
        self.assertFalse((PLUGIN_ROOT / "skills" / "upgrade").exists())

    def test_precheck_owns_the_upgrade_steps(self) -> None:
        text: str = (PLUGIN_ROOT / "skills" / "run" / "SKILL.md").read_text(encoding="utf-8")
        for needle in (
            "### Pre-check (every run command)", "skills-check.py", ".harness/upgrade-from.txt",
            ".harness/handoff/latest.md", "claude plugin update dts2-harness@dts2", "/plugin marketplace update dts2",
            "/plugin install dts2-harness@dts2", "cannot run `/plugin`", "/reload-plugins", "Upgrade re-entry",
            "the upgrade finishes itself", "Do not start the task on the old version",
        ):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
