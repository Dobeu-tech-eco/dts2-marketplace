"""G-14: `reconcile` asks GitHub before the head creates, merges or resumes; orphaned lanes get one resume."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lanes.phases import transition  # noqa: E402
from lanes.reconcile import reconcile  # noqa: E402

CLI: Final[Path] = SCRIPTS / "lanes.py"
STAMP: Final[str] = "20261105-5"
LATER: Final[int] = int(time.time()) + 100_000  # far past every stall window
FAKE_GH: Final[str] = """#!/usr/bin/env python3
import os, sys
if os.environ.get("FAKE_DOWN"):
    sys.exit(1)
print(os.environ.get("FAKE_PRS", "[]"))
"""


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="dts2-g14-"))
        self.runs = self.repo / ".harness" / "runs"
        self.prs: dict[str, list[dict[str, Any]]] = {}
        self.dirty = False

    def ask(self, _cwd: Path, branch: str) -> tuple[list[dict[str, Any]] | None, str | None]:
        return self.prs.get(branch.rsplit("lane-", 1)[-1], []), None

    def seed(self, lane: str, phase: str, **more: Any) -> Path:
        path = self.runs / STAMP / lane / "status.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"lane": lane, "status": phase, **more}), encoding="utf-8")
        return path

    def saved(self, lane: str) -> dict[str, Any]:
        data: dict[str, Any] = json.loads((self.runs / STAMP / lane / "status.json").read_text(encoding="utf-8"))
        return data

    def go(self) -> dict[str, Any]:
        return reconcile(self.runs, STAMP, self.repo, now=LATER, ask=self.ask, dirty=lambda _w: self.dirty)

    def row(self, lane: str) -> dict[str, Any]:
        return {r["lane"]: r for r in self.go()["lanes"]}[lane]


class DecisionTests(Base):
    def test_a_merged_pr_marks_the_lane_done_and_forbids_a_second_merge(self) -> None:
        self.seed("a", "pr-open")
        self.prs["a"] = [{"number": 7, "state": "MERGED", "url": "u"}]
        row = self.row("a")
        self.assertEqual((row["action"], row["pr"]["number"]), ("merged", 7))
        saved = self.saved("a")
        self.assertEqual((saved["status"], saved["pr"], saved["merged_on_github"]), ("done", 7, True))

    def test_an_open_pr_is_adopted_not_duplicated(self) -> None:
        self.seed("a", "starting")
        self.prs["a"] = [{"number": 9, "state": "OPEN", "url": "u9"}]
        row = self.row("a")
        self.assertEqual(row["action"], "adopt-pr")
        self.assertIn("do not create another", row["detail"])
        self.assertEqual(self.saved("a")["pr"], 9)

    def test_pr_open_with_no_pr_on_github_may_create_one(self) -> None:
        self.seed("a", "pr-open")
        self.assertEqual(self.row("a")["action"], "create-pr")

    def test_a_quiet_lane_with_a_report_and_no_pr_may_create_one(self) -> None:
        path = self.seed("a", "starting", son_pid=None)
        (path.parent / "report.md").write_text("done", encoding="utf-8")
        self.assertEqual(self.row("a")["action"], "create-pr")

    def test_a_healthy_lane_needs_nothing(self) -> None:
        path = self.seed("a", "starting", heartbeat=LATER)
        os.utime(path, (LATER, LATER))
        self.assertEqual(self.row("a")["action"], "none")

    def test_quiet_and_clean_without_a_report_is_plain_stalled(self) -> None:
        self.seed("a", "starting")
        self.assertEqual(self.row("a")["action"], "stalled")


class OrphanTests(Base):
    def test_orphan_gets_one_resume_then_is_parked(self) -> None:
        self.seed("a", "starting", worktree=str(self.repo))
        self.dirty = True
        first = self.row("a")
        self.assertEqual(first["action"], "resume")
        self.assertEqual((self.saved("a")["status"], self.saved("a")["resume_count"]), ("orphaned", 1))
        self.assertEqual(self.row("a")["action"], "resume", "asking again before the head acts grants no second resume")
        self.assertEqual(self.saved("a")["resume_count"], 1)
        transition(self.runs, STAMP, "a", "starting")  # the head resumed it
        self.seed("a", "incomplete", reason="stalled", worktree=str(self.repo), resume_count=1)
        again = self.row("a")
        self.assertEqual(again["action"], "park")
        saved = self.saved("a")
        self.assertEqual((saved["status"], saved["reason"]), ("incomplete", "orphaned"))

    def test_a_clean_worktree_or_a_report_is_not_orphaned(self) -> None:
        self.seed("a", "starting")
        self.dirty = False
        self.assertNotIn(self.row("a")["action"], ("resume", "park"))
        path = self.seed("b", "starting")
        (path.parent / "report.md").write_text("x", encoding="utf-8")
        self.dirty = True
        self.assertEqual(self.row("b")["action"], "create-pr")

    def test_a_running_process_is_never_orphaned(self) -> None:
        self.seed("a", "starting", son_pid=os.getpid())
        self.dirty = True
        row = self.row("a")
        self.assertTrue(row["alive"])
        self.assertEqual(row["action"], "none")


class FailClosedTests(Base):
    def test_when_github_cannot_be_asked_nothing_is_decided_or_changed(self) -> None:
        path = self.seed("a", "pr-open")
        before = path.read_text(encoding="utf-8")
        result = reconcile(self.runs, STAMP, self.repo, now=LATER, ask=lambda _c, _b: (None, "gh exited 1"))
        self.assertFalse(result["ok"])
        self.assertIn("fails closed", result["detail"])
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_a_son_may_not_reconcile(self) -> None:
        os.environ["DTS2_SON_BRANCH_PREFIX"] = "p"
        self.addCleanup(os.environ.pop, "DTS2_SON_BRANCH_PREFIX", None)
        self.seed("a", "starting")
        self.assertFalse(self.go()["ok"])


class CommandTests(Base):
    def test_reconcile_command_with_a_fake_gh(self) -> None:
        gh = self.repo / "gh.py"
        gh.write_text(FAKE_GH, encoding="utf-8")
        self.seed("a", "pr-open")
        env = {**os.environ, "DTS2_GH_BIN": str(gh), "FAKE_PRS": json.dumps([{"number": 3, "state": "OPEN", "url": "u"}])}
        done = subprocess.run([sys.executable, "-I", str(CLI), "--cwd", str(self.repo), "reconcile", STAMP],
                              capture_output=True, text=True, env=env, check=False)
        out = json.loads(done.stdout)
        self.assertEqual((done.returncode, out["actions"]), (0, {"a": "adopt-pr"}))
        down = subprocess.run([sys.executable, "-I", str(CLI), "--cwd", str(self.repo), "reconcile", STAMP],
                              capture_output=True, text=True, env={**env, "FAKE_DOWN": "1"}, check=False)
        self.assertEqual((down.returncode, json.loads(down.stdout)["ok"]), (2, False))


if __name__ == "__main__":
    unittest.main()
