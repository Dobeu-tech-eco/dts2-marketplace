"""Tests for scripts/release-gate.py: a shipped runtime change needs a plugin.json version bump."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

PLUGIN_ROOT: Path = Path(__file__).resolve().parent.parent
SCRIPT: Path = PLUGIN_ROOT / "scripts" / "release-gate.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("release_gate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LOG_530: str = "# Changelog\n\n## [5.3.0]\n\n_Released 2026-11-16_\n"


class EvaluateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod: ModuleType = load()

    def test_no_runtime_change_passes(self) -> None:
        result = self.mod.evaluate(
            ["README.md", "plugins/dts2-harness/x.md"], "5.2.0", "5.2.0", "## [5.2.0]"
        )
        self.assertEqual(result["verdict"], "pass")

    def test_tests_and_fragments_are_not_shipped(self) -> None:
        changed = [
            "plugins/dts2-runtime/tests/test_x.py",
            "plugins/dts2-runtime/changelog.d/a.md",
        ]
        self.assertEqual(
            self.mod.evaluate(changed, "5.2.0", "5.2.0", "## [5.2.0]")["verdict"],
            "pass",
        )

    def test_runtime_change_without_bump_fails(self) -> None:
        result = self.mod.evaluate(
            ["plugins/dts2-runtime/scripts/x.py"], "5.2.0", "5.2.0", "## [5.2.0]"
        )
        self.assertEqual(result["verdict"], "fail")

    def test_runtime_change_with_bump_passes(self) -> None:
        result = self.mod.evaluate(
            ["plugins/dts2-runtime/scripts/x.py"], "5.2.0", "5.3.0", "## [5.3.0]"
        )
        self.assertEqual(result["verdict"], "pass")

    def test_version_compare_is_numeric(self) -> None:
        self.assertEqual(
            self.mod.evaluate(
                ["plugins/dts2-runtime/a"], "5.9.0", "5.10.0", "## [5.10.0]"
            )["verdict"],
            "pass",
        )
        self.assertEqual(
            self.mod.evaluate(
                ["plugins/dts2-runtime/a"], "5.10.0", "5.9.0", "## [5.9.0]"
            )["verdict"],
            "fail",
        )

    def test_bump_without_changelog_entry_fails(self) -> None:
        result = self.mod.evaluate(
            ["plugins/dts2-runtime/scripts/x.py"], "5.2.0", "5.3.0", "## [5.2.0]\n"
        )
        self.assertEqual(result["verdict"], "fail")
        self.assertIn("5.3.0", str(result["reason"]))

    def test_changelog_entry_must_be_a_heading(self) -> None:
        self.assertFalse(self.mod.has_entry("see [5.3.0] notes", "5.3.0"))
        self.assertTrue(self.mod.has_entry(LOG_530, "5.3.0"))
        self.assertFalse(self.mod.has_entry("## [5.3.01]", "5.3.0"))

    def test_bad_version_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.mod.evaluate(["plugins/dts2-runtime/a"], "5.2", "5.3.0", "## [5.3.0]")


class CliTests(unittest.TestCase):
    def _git(self, repo: Path, *args: str) -> None:
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }
        subprocess.run(
            ["git", *args], cwd=repo, check=True, capture_output=True, env=env
        )

    def _write(self, repo: Path, rel: str, text: str) -> None:
        path: Path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _run(self, repo: Path) -> tuple[int, dict[str, object]]:
        done = subprocess.run(
            [sys.executable, str(SCRIPT), "--base", "base"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        return done.returncode, json.loads(done.stdout)

    def _repo(self, tmp: str) -> Path:
        repo: Path = Path(tmp)
        self._git(repo, "init", "-q")
        self._write(
            repo,
            "plugins/dts2-runtime/.claude-plugin/plugin.json",
            json.dumps({"version": "1.0.0"}),
        )
        self._write(repo, "plugins/dts2-runtime/scripts/a.py", "x = 1\n")
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "-qm", "base")
        self._git(repo, "branch", "base")
        return repo

    def test_cli_fails_without_bump(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            self._write(repo, "plugins/dts2-runtime/scripts/a.py", "x = 2\n")
            self._git(repo, "commit", "-qam", "change")
            code, out = self._run(repo)
            self.assertEqual((code, out["verdict"]), (1, "fail"))

    def test_cli_passes_with_bump(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            self._write(repo, "plugins/dts2-runtime/scripts/a.py", "x = 2\n")
            self._write(
                repo,
                "plugins/dts2-runtime/.claude-plugin/plugin.json",
                json.dumps({"version": "1.1.0"}),
            )
            self._write(
                repo, "plugins/dts2-runtime/CHANGELOG.md", "# Changelog\n\n## [1.1.0]\n"
            )
            self._git(repo, "add", "-A")
            self._git(repo, "commit", "-qm", "change")
            code, out = self._run(repo)
            self.assertEqual((code, out["verdict"]), (0, "pass"))

    def test_cli_fails_with_bump_but_no_changelog_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            self._write(repo, "plugins/dts2-runtime/scripts/a.py", "x = 2\n")
            self._write(
                repo,
                "plugins/dts2-runtime/.claude-plugin/plugin.json",
                json.dumps({"version": "1.1.0"}),
            )
            self._git(repo, "commit", "-qam", "change")
            code, out = self._run(repo)
            self.assertEqual((code, out["verdict"]), (1, "fail"))


if __name__ == "__main__":
    unittest.main()
