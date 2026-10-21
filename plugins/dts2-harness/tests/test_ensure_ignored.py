from __future__ import annotations

import unittest

from helpers import make_tmp_home, run_script


class EnsureIgnoredTest(unittest.TestCase):
    def test_adds_all_defaults_once(self) -> None:
        repo = make_tmp_home()
        first = run_script("ensure-ignored.py", str(repo))
        self.assertEqual(len(first["added"]), 7)
        second = run_script("ensure-ignored.py", str(repo))
        self.assertEqual(second["added"], [])
        self.assertEqual(len(second["present"]), 7)

    def test_preserves_missing_trailing_newline(self) -> None:
        repo = make_tmp_home()
        (repo / ".gitignore").write_text("node_modules")
        run_script("ensure-ignored.py", str(repo))
        lines = (repo / ".gitignore").read_text().splitlines()
        self.assertEqual(lines[:2], ["node_modules", ".harness/runs/"])

    def test_extra_paths_appended(self) -> None:
        repo = make_tmp_home()
        run_script("ensure-ignored.py", str(repo), "--extra", ".omc/screens/")
        self.assertIn(".omc/screens/", (repo / ".gitignore").read_text().splitlines())


if __name__ == "__main__":
    unittest.main()
