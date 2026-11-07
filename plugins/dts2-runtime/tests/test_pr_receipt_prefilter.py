"""The pr-receipt hook must not spawn python3 for Bash calls that cannot be a PR command."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT, make_tmp_home

HOOK: Final[Path] = PLUGIN_ROOT / "hooks" / "pr-receipt.sh"


class PrefilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir: Path = make_tmp_home()
        real = shutil.which("python3")
        assert real is not None
        bindir = self.dir / "bin"
        bindir.mkdir()
        py = bindir / "python3"
        py.write_text(f'#!/usr/bin/env bash\necho "$*" >> "{self.dir}/py.log"\nexec "{real}" "$@"\n', encoding="utf-8")
        py.chmod(0o755)
        gh = bindir / "gh"
        gh.write_text(f'#!/usr/bin/env bash\necho "$*" >> "{self.dir}/gh.log"\nexit 1\n', encoding="utf-8")
        gh.chmod(0o755)
        self.bindir: Path = bindir

    def run_hook(self, command: str, tool: str = "Bash") -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "PATH": f"{self.bindir}:{os.environ['PATH']}", "DTS2_GH_BIN": str(self.bindir / "gh"),
               "TMPDIR": str(self.dir)}
        payload = json.dumps({"session_id": "s", "tool_name": tool, "tool_input": {"command": command}})
        return subprocess.run(["bash", str(HOOK)], cwd=str(self.dir), input=payload, env=env,
                              capture_output=True, text=True, check=False)

    def read(self, name: str) -> str:
        path = self.dir / name
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def test_unrelated_bash_skips_python_and_gh(self) -> None:
        done = self.run_hook("ls -la")
        self.assertEqual(done.returncode, 0)
        self.assertEqual(self.read("py.log"), "")
        self.assertEqual(self.read("gh.log"), "")

    def test_non_bash_tool_skips_python(self) -> None:
        done = self.run_hook("Read file", tool="Read")
        self.assertEqual(done.returncode, 0)
        self.assertEqual(self.read("py.log"), "")

    def test_gh_api_without_pulls_skips_python(self) -> None:
        done = self.run_hook("gh api repos/o/r/issues")
        self.assertEqual(done.returncode, 0)
        self.assertEqual(self.read("py.log"), "")

    def test_gh_pr_view_reaches_python(self) -> None:
        done = self.run_hook("gh pr view 3")
        self.assertEqual(done.returncode, 0)
        self.assertNotEqual(self.read("py.log"), "")

    def test_gh_api_pulls_reaches_python(self) -> None:
        done = self.run_hook("gh api repos/o/r/pulls -X POST --input f.json")
        self.assertEqual(done.returncode, 0)
        self.assertNotEqual(self.read("py.log"), "")


if __name__ == "__main__":
    unittest.main()
