"""Contracts for task-ledger.py: the final ledger of open PRs and the user-input items that block them."""
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

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "task-ledger.py"
STAMP: Final[str] = "20261104-9"
FAKE_GH: Final[str] = """#!/usr/bin/env python3
import os
print(os.environ.get("FAKE_PRS", "[]"))
"""
ITEMS: Final[str] = """# Action items

## Secrets

| name | unlocks | consumed in | how to add | status | owner | added |
| --- | --- | --- | --- | --- | --- | --- |
| TASK_A1_S1-stripe secret | billing | billing.py | dashboard | {s1} |  | 2026-11-04 |

## Decisions

| question | options | default | status | owner | added |
| --- | --- | --- | --- | --- | --- |
| TASK_B2_D1-pick region | us/eu | us | {d1} |  | 2026-11-04 |
"""


def status(lane: str, pr: int, tasks: list[str], blocked_by: list[str], state: str = "blocked") -> dict[str, Any]:
    return {"lane": lane, "status": state, "pr": pr, "branch": f"dts2/{STAMP}/{lane}",
            "tasks": tasks, "blocked_by": blocked_by}


class TaskLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dts2-ledger-"))
        self.fake = self.root / "gh.py"
        self.fake.write_text(FAKE_GH, encoding="utf-8")
        self.runs = self.root / ".harness" / "runs" / STAMP
        self.runs.mkdir(parents=True)
        self.items = self.root / ".harness" / "action-items.md"

    def write_items(self, s1: str = "open", d1: str = "open") -> None:
        self.items.write_text(ITEMS.format(s1=s1, d1=d1), encoding="utf-8")

    def write_lane(self, data: dict[str, Any]) -> None:
        folder: Path = self.runs / data["lane"]
        folder.mkdir()
        (folder / "status.json").write_text(json.dumps(data), encoding="utf-8")

    def run_ledger(self, *args: str, prs: list[dict[str, Any]]) -> dict[str, Any]:
        env = {**os.environ, "DTS2_GH_BIN": str(self.fake), "FAKE_PRS": json.dumps(prs)}
        done = subprocess.run([sys.executable, "-I", str(SCRIPT), "--cwd", str(self.root), STAMP, *args],
                              capture_output=True, text=True, env=env, check=False)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        parsed: dict[str, Any] = json.loads(done.stdout)
        return parsed

    def test_ledger_lists_open_pr_with_blocking_item(self) -> None:
        self.write_items()
        self.write_lane(status("a", 41, ["A1"], ["S1"]))
        result = self.run_ledger(prs=[{"number": 41, "headRefName": f"dts2/{STAMP}/a"}])
        self.assertEqual([pr["pr"] for pr in result["open_prs"]], [41])
        self.assertEqual(result["blocking_items"], ["S1"])
        ledger: str = (self.runs / "task-ledger.md").read_text(encoding="utf-8")
        self.assertIn("| 41 |", ledger)
        self.assertIn("TASK_A1_S1-stripe secret", ledger)
        self.assertIn("1 open PRs, 1 blocking items", ledger)

    def test_ledger_bundles_tasks_under_one_pr(self) -> None:
        self.write_items()
        self.write_lane(status("a", 41, ["A1", "B2"], ["S1", "D1"]))
        result = self.run_ledger(prs=[{"number": 41, "headRefName": f"dts2/{STAMP}/a"}])
        self.assertEqual(len(result["open_prs"]), 1)
        self.assertEqual(result["open_prs"][0]["tasks"], ["A1", "B2"])
        self.assertEqual(result["blocking_items"], ["D1", "S1"])
        ledger: str = (self.runs / "task-ledger.md").read_text(encoding="utf-8")
        self.assertIn("1 open PRs, 2 blocking items", ledger)

    def test_resolved_lists_pr_when_all_items_done(self) -> None:
        self.write_items(s1="done", d1="open")
        self.write_lane(status("a", 41, ["A1"], ["S1"]))
        self.write_lane(status("b", 42, ["B2"], ["D1"]))
        prs = [{"number": 41, "headRefName": f"dts2/{STAMP}/a"}, {"number": 42, "headRefName": f"dts2/{STAMP}/b"}]
        result = self.run_ledger("--resolved", prs=prs)
        self.assertEqual([pr["pr"] for pr in result["resolved"]], [41])
        self.assertEqual([pr["pr"] for pr in result["open_prs"]], [41, 42])


if __name__ == "__main__":
    unittest.main()
