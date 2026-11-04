"""Branch naming and version preflight for lanes.py branch-check, against a real temp repo."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "lanes.py"
STAMP: Final[str] = "20261104-1"
OLD_GIT: Final[str] = """#!/usr/bin/env python3
import sys
if "--version" in sys.argv:
    print("git version 2.30.0")
"""
GARBLED_GIT: Final[str] = """#!/usr/bin/env python3
print("not a version")
"""
IDENTITY: Final[tuple[str, ...]] = ("-c", "user.name=t", "-c", "user.email=t@example.invalid")
REF_KINDS: Final[tuple[str, ...]] = ("main", "lane-a", "lane-a-b1", "main-b1")


class BranchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dts2-branches-"))
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.vcs("init", "-q")
        self.vcs(*IDENTITY, "commit", "-q", "--allow-empty", "-m", "init")

    def vcs(self, *args: str) -> str:
        done = subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True, check=True)
        return done.stdout

    def branch_check(self, bin_path: str | None = None) -> dict[str, Any]:
        env = {k: v for k, v in os.environ.items() if k != "DTS2_GIT_BIN"}
        if bin_path:
            env["DTS2_GIT_BIN"] = bin_path
        done = subprocess.run([sys.executable, "-I", str(SCRIPT), "--cwd", str(self.repo), "branch-check", STAMP,
                               "--lanes", "a"], capture_output=True, text=True, env=env, check=False)
        return json.loads(done.stdout)

    def fake(self, name: str, text: str) -> str:
        path: Path = self.root / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_all_ref_kinds_coexist_and_check_passes(self) -> None:
        clean = self.branch_check()
        self.assertTrue(clean["ok"], clean)
        self.assertEqual(clean["planned"], [f"dts2/{STAMP}/main", f"dts2/{STAMP}/lane-a"])
        for kind in REF_KINDS:
            self.vcs("branch", f"dts2/{STAMP}/{kind}")
        listed = self.vcs("for-each-ref", "--format=%(refname:short)", f"refs/heads/dts2/{STAMP}").split()
        self.assertEqual(sorted(listed), sorted(f"dts2/{STAMP}/{kind}" for kind in REF_KINDS))

    def test_plain_stamp_branch_collides(self) -> None:
        self.vcs("branch", f"dts2/{STAMP}")
        result = self.branch_check()
        self.assertFalse(result["ok"])
        self.assertIn(f"dts2/{STAMP}/main", {c["planned"] for c in result["collisions"]})

    def test_old_version_fails_preflight(self) -> None:
        result = self.branch_check(self.fake("old_bin.py", OLD_GIT))
        self.assertFalse(result["ok"])
        self.assertIn("merge-tree --write-tree", result["error"])
        self.assertIn("2.30", result["error"])

    def test_unparseable_version_fails_closed(self) -> None:
        result = self.branch_check(self.fake("odd_bin.py", GARBLED_GIT))
        self.assertFalse(result["ok"])
        self.assertIn("cannot read the git version", result["error"])


if __name__ == "__main__":
    unittest.main()
