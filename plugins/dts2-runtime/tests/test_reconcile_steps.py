"""Standalone autopilot steps: `reconcile --step` finds the PR for dts2/<stamp>/step-<step> from GitHub alone."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final
from unittest import mock

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lanes.reconcile import reconcile_step  # noqa: E402

# The package exports a `reconcile` function that shadows the submodule name, and
# Python 3.10's mock.patch resolves dotted strings through it; patch the module object.
RECONCILE_MODULE = sys.modules["lanes.reconcile"]

CLI: Final[Path] = SCRIPTS / "lanes.py"
STAMP: Final[str] = "20261105-7"
FAKE_GH: Final[str] = """#!/usr/bin/env python3
import os, sys
if os.environ.get("FAKE_DOWN"):
    sys.exit(1)
open(os.environ["FAKE_LOG"], "a").write(" ".join(sys.argv[1:]) + "\\n")
print(os.environ.get("FAKE_PRS", "[]"))
"""


class StepReconcileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="dts2-rstep-"))
        self.prs: dict[str, list[dict[str, Any]]] = {}
        self.asked: list[str] = []

    def ask(self, _cwd: Path, branch: str) -> tuple[list[dict[str, Any]] | None, str | None]:
        self.asked.append(branch)
        return self.prs.get(branch, []), None

    def go(self, step: str = "3") -> dict[str, Any]:
        return reconcile_step(STAMP, step, self.repo, ask=self.ask)

    def test_a_merged_step_pr_means_do_not_merge_again(self) -> None:
        self.prs[f"dts2/{STAMP}/step-3"] = [{"number": 7, "state": "MERGED", "url": "u"}]
        out = self.go()
        self.assertEqual((out["ok"], out["action"], out["pr"]["number"]), (True, "merged", 7))
        self.assertEqual(self.asked, [f"dts2/{STAMP}/step-3"])

    def test_an_open_step_pr_is_adopted(self) -> None:
        self.prs[f"dts2/{STAMP}/step-3"] = [{"number": 9, "state": "OPEN", "url": "u9"}]
        out = self.go()
        self.assertEqual((out["action"], out["pr"]["number"]), ("adopt-pr", 9))
        self.assertIn("do not create another", out["detail"])

    def test_no_pr_may_create_one_and_other_steps_are_not_confused(self) -> None:
        self.prs[f"dts2/{STAMP}/step-4"] = [{"number": 5, "state": "OPEN", "url": "u"}]
        self.assertEqual(self.go("3")["action"], "create-pr")
        self.assertEqual(self.go("4")["action"], "adopt-pr")

    def test_merged_wins_over_an_older_open_pr(self) -> None:
        self.prs[f"dts2/{STAMP}/step-3"] = [{"number": 8, "state": "OPEN"}, {"number": 7, "state": "MERGED"}]
        self.assertEqual(self.go()["action"], "merged")

    def test_github_down_fails_closed(self) -> None:
        out = reconcile_step(STAMP, "3", self.repo, ask=lambda _c, _b: (None, "gh exited 1"))
        self.assertFalse(out["ok"])
        self.assertNotIn("action", out)

    def test_an_unsafe_step_name_is_refused(self) -> None:
        with self.assertRaises(Exception):
            self.go("../x")

    def test_a_son_is_refused(self) -> None:
        with mock.patch.object(RECONCILE_MODULE, "inside_son", return_value=True):
            out = self.go()
        self.assertFalse(out["ok"])
        self.assertEqual(self.asked, [])


class StepCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="dts2-rstepcli-"))
        gh = self.repo / "gh"
        gh.write_text(FAKE_GH, encoding="utf-8")
        gh.chmod(0o755)
        self.log = self.repo / "gh.log"

    def run_cli(self, prs: list[dict[str, Any]], down: bool = False) -> dict[str, Any]:
        env = {**os.environ, "DTS2_GH_BIN": str(self.repo / "gh"), "FAKE_PRS": json.dumps(prs), "FAKE_LOG": str(self.log)}
        env.pop("DTS2_SON", None)
        env.pop("DTS2_SON_BRANCH_PREFIX", None)
        if down:
            env["FAKE_DOWN"] = "1"
        done = subprocess.run([sys.executable, str(CLI), "reconcile", STAMP, "--step", "3"], cwd=self.repo, env=env,
                              capture_output=True, text=True, check=False)
        out: dict[str, Any] = json.loads(done.stdout)
        return out

    def test_cli_asks_for_the_step_branch(self) -> None:
        out = self.run_cli([{"number": 12, "state": "OPEN", "url": "u"}])
        self.assertEqual((out["action"], out["step"]), ("adopt-pr", "3"))
        self.assertIn(f"--head dts2/{STAMP}/step-3", self.log.read_text(encoding="utf-8"))

    def test_cli_fails_closed_when_gh_is_down(self) -> None:
        self.assertFalse(self.run_cli([], down=True)["ok"])


if __name__ == "__main__":
    unittest.main()
