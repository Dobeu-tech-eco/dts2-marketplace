"""claude-md-rules.py: plan never writes, apply is idempotent and keeps the user's text."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "claude-md-rules.py"
START: Final[str] = "<!-- dts2-plan-rules:start -->"
USER_TEXT: Final[str] = "# My rules\n\n- Keep it short.\n"


def run(home: Path, command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), command, "--claude-home", str(home)],
        capture_output=True, text=True, check=False,
    )


class ClaudeMdRules(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.target = self.home / "CLAUDE.md"
        self.target.write_text(USER_TEXT, encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_plan_shows_a_diff_and_writes_nothing(self) -> None:
        result = run(self.home, "plan")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("+" + START, result.stdout)
        self.assertEqual(self.target.read_text(encoding="utf-8"), USER_TEXT)
        self.assertFalse((self.home / "backups").exists())

    def test_apply_keeps_user_text_and_backs_up(self) -> None:
        self.assertEqual(run(self.home, "apply").returncode, 0)
        text = self.target.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(USER_TEXT))
        self.assertIn("Merge danger", text)
        backups = list((self.home / "backups").glob("CLAUDE.md.*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), USER_TEXT)

    def test_rerun_is_a_no_op_with_one_block(self) -> None:
        run(self.home, "apply")
        first = self.target.read_text(encoding="utf-8")
        result = run(self.home, "apply")
        self.assertIn("already current", result.stdout)
        self.assertEqual(self.target.read_text(encoding="utf-8"), first)
        self.assertEqual(first.count(START), 1)
        self.assertEqual(run(self.home, "check").returncode, 0)

    def test_stale_block_is_replaced_in_place(self) -> None:
        stale = USER_TEXT + "\n" + START + "\nold rule\n<!-- dts2-plan-rules:end -->\n\n## After\n"
        self.target.write_text(stale, encoding="utf-8")
        self.assertEqual(run(self.home, "check").returncode, 1)
        run(self.home, "apply")
        text = self.target.read_text(encoding="utf-8")
        self.assertNotIn("old rule", text)
        self.assertEqual(text.count(START), 1)
        self.assertTrue(text.rstrip().endswith("## After"))

    def test_missing_file_is_created(self) -> None:
        self.target.unlink()
        self.assertEqual(run(self.home, "check").returncode, 1)
        run(self.home, "apply")
        self.assertTrue(self.target.read_text(encoding="utf-8").startswith(START))


if __name__ == "__main__":
    unittest.main()
