"""scripts/bump-version.py keeps the four version locations in step."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "bump-version.py"
REPO_ROOT: Final[Path] = PLUGIN_ROOT.parent.parent
PLUGIN_JSON: Final[Path] = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
LOCATIONS: Final[tuple[str, ...]] = (
    ".claude-plugin/marketplace.json",
    "plugins/dts2-harness/.claude-plugin/plugin.json",
    "plugins/dts2-harness/tests/test_text_contracts.py",
    "plugins/dts2-harness/tests/test_upgrade_check.py",
)


def run(*args: str) -> tuple[int, dict[str, Any]]:
    result = subprocess.run(["python3", "-I", str(SCRIPT), *args], capture_output=True, text=True)
    return result.returncode, json.loads(result.stdout)


def temp_copy() -> Path:
    root = Path(tempfile.mkdtemp(prefix="dts2-bump-"))
    for rel in LOCATIONS:
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, dest)
    return root


def snapshot(root: Path) -> dict[str, str]:
    return {rel: (root / rel).read_text(encoding="utf-8") for rel in LOCATIONS}


class BumpVersionTests(unittest.TestCase):
    def test_real_locations_match(self) -> None:
        version = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))["version"]
        code, out = run(version, "--root", str(REPO_ROOT), "--check")
        self.assertEqual(code, 0, out)
        self.assertTrue(out["ok"])

    def test_bump_updates_all_four(self) -> None:
        root = temp_copy()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        code, out = run("9.9.9", "--root", str(root))
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(out["files"]), sorted(LOCATIONS))
        after = snapshot(root)
        for rel, text in after.items():
            self.assertIn("9.9.9", text, rel)
        self.assertTrue(after[LOCATIONS[0]].endswith("}\n"))
        code, out = run("9.9.9", "--root", str(root), "--check")
        self.assertEqual(code, 0, out)
        self.assertTrue(out["ok"])

    def test_invalid_version_refused(self) -> None:
        root = temp_copy()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        before = snapshot(root)
        for bad in ("1.2", "v1.2.3", "1.2.x", "1.2.3.4"):
            code, out = run(bad, "--root", str(root))
            self.assertEqual(code, 1, bad)
            self.assertFalse(out["ok"])
        self.assertEqual(snapshot(root), before)

    def test_check_reports_mismatch(self) -> None:
        root = temp_copy()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        target = root / LOCATIONS[2]
        current = json.loads((root / LOCATIONS[1]).read_text(encoding="utf-8"))["version"]
        text = target.read_text(encoding="utf-8")
        target.write_text(text.replace(f'"{current}"', '"0.0.1"', 1), encoding="utf-8")
        code, out = run(current, "--root", str(root), "--check")
        self.assertEqual(code, 1)
        self.assertFalse(out["ok"])
        self.assertEqual(out["files"], [LOCATIONS[2]])

    def test_default_root_is_repo_root(self) -> None:
        version = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))["version"]
        code, out = run(version, "--check")
        self.assertEqual(code, 0, out)
        self.assertTrue(out["ok"])

    def test_missing_location_writes_nothing(self) -> None:
        root = temp_copy()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        target = root / LOCATIONS[3]
        lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
        target.write_text("".join(x for x in lines if "RELEASE" not in x), encoding="utf-8")
        before = snapshot(root)
        code, out = run("9.9.9", "--root", str(root))
        self.assertEqual(code, 1, out)
        self.assertFalse(out["ok"])
        self.assertEqual(out["files"], [LOCATIONS[3]])
        self.assertEqual(snapshot(root), before)

    def test_bump_keeps_file_mode(self) -> None:
        root = temp_copy()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        for rel in LOCATIONS:
            os.chmod(root / rel, 0o644)
        code, out = run("9.9.9", "--root", str(root))
        self.assertEqual(code, 0, out)
        for rel in LOCATIONS:
            self.assertEqual((root / rel).stat().st_mode & 0o777, 0o644, rel)


if __name__ == "__main__":
    unittest.main()
