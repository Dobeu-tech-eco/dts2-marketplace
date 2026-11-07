from __future__ import annotations

import unittest

import importlib.util

from helpers import PLUGIN_ROOT, make_tmp_home, run_script


def default_count() -> int:
    spec = importlib.util.spec_from_file_location("ensure_ignored_count", PLUGIN_ROOT / "scripts" / "ensure-ignored.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return len(module.IGNORED_PATHS)


class EnsureIgnoredTest(unittest.TestCase):
    def test_adds_all_defaults_once(self) -> None:
        repo = make_tmp_home()
        first = run_script("ensure-ignored.py", str(repo))
        self.assertEqual(len(first["added"]), default_count())
        second = run_script("ensure-ignored.py", str(repo))
        self.assertEqual(second["added"], [])
        self.assertEqual(len(second["present"]), default_count())

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
