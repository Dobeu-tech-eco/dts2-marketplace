"""End-to-end fixture of the blocked-task flow: fold, ledger, items marked done, resume, stop-check. No network."""
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

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
LANES: Final[Path] = SCRIPTS / "lanes.py"
LEDGER: Final[Path] = SCRIPTS / "task-ledger.py"
ITEMS_CLI: Final[Path] = SCRIPTS / "action-items.py"
STAMP: Final[str] = "20261104-7"
PR_NUMBER: Final[int] = 41
OTHER_PR_NUMBER: Final[int] = 42
FAKE_GH: Final[str] = """#!/usr/bin/env python3
import os
print(os.environ.get("FAKE_PRS", "[]"))
"""
ITEMS: Final[str] = """# Action items

## Secrets

| name | unlocks | consumed in | how to add | status | owner | added |
| --- | --- | --- | --- | --- | --- | --- |
| TASK_A1_S1-stripe secret | billing | billing.py | dashboard | open |  | 2026-11-04 |

## Decisions

| question | options | default | status | owner | added |
| --- | --- | --- | --- | --- | --- |
| TASK_B2_D1-pick region | us/eu | us | open |  | 2026-11-04 |
"""


def lane_status(lane: str, task: str, item: str, path: str) -> dict[str, Any]:
    return {"lane": lane, "status": "blocked", "branch": f"dts2/{STAMP}/{lane}", "files": [path],
            "tasks": [task], "blocked_by": [item]}


class DppEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dts2-e2e-"))
        self.repo = self.root / "repo"
        self.runs = self.repo / ".harness" / "runs" / STAMP
        self.runs.mkdir(parents=True)
        (self.repo / ".harness" / "action-items.md").write_text(ITEMS, encoding="utf-8")
        self.fake = self.root / "gh.py"
        self.fake.write_text(FAKE_GH, encoding="utf-8")
        self.write_lane(lane_status("a", "A1", "S1", "src/a.py"))
        self.write_lane(lane_status("b", "B2", "D1", "src/b.py"))

    def write_lane(self, data: dict[str, Any]) -> None:
        folder: Path = self.runs / data["lane"]
        folder.mkdir(exist_ok=True)
        (folder / "status.json").write_text(json.dumps(data), encoding="utf-8")

    def set_pr(self, lane: str, pr: int) -> None:
        path: Path = self.runs / lane / "status.json"
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        data["pr"] = pr
        path.write_text(json.dumps(data), encoding="utf-8")

    def script(self, script: Path, *args: str, prs: list[int] | None = None) -> dict[str, Any]:
        numbers: list[int] = prs if prs is not None else [PR_NUMBER]
        env = {**os.environ, "DTS2_GH_BIN": str(self.fake),
               "FAKE_PRS": json.dumps([{"number": n, "headRefName": f"pr-{n}"} for n in numbers])}
        done = subprocess.run([sys.executable, "-I", str(script), *args], capture_output=True, text=True,
                              env=env, check=False)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        parsed: dict[str, Any] = json.loads(done.stdout)
        return parsed

    def ledger(self, prs: list[int] | None = None) -> dict[str, Any]:
        return self.script(LEDGER, "--cwd", str(self.repo), STAMP, "--resolved", prs=prs)

    def mark_done(self, row: str) -> None:
        self.script(ITEMS_CLI, str(self.repo), "done", row)

    def checkin(self, outstanding: list[str]) -> str:
        path: Path = self.root / "checkin.json"
        path.write_text(json.dumps({"outstanding_items": outstanding}), encoding="utf-8")
        return str(path)

    def stop_check(self) -> dict[str, Any]:
        return self.script(LANES, "--cwd", str(self.repo), "stop-check", STAMP, "--from-checkin", self.checkin([]))

    def ledger_text(self) -> str:
        return (self.runs / "task-ledger.md").read_text(encoding="utf-8")

    def test_fold_puts_two_blocked_lanes_on_one_pr(self) -> None:
        folded = self.script(LANES, "--cwd", str(self.repo), "fold", STAMP)
        self.assertEqual([g["lanes"] for g in folded["groups"]], [["a", "b"]])
        self.assertEqual(folded["open_prs"], 1)

    def test_ledger_has_one_row_for_a_folded_pr(self) -> None:
        self.set_pr("a", PR_NUMBER)
        self.set_pr("b", PR_NUMBER)
        result = self.ledger()
        self.assertEqual(len(result["open_prs"]), 1)
        row: dict[str, Any] = result["open_prs"][0]
        self.assertEqual((row["pr"], row["lanes"], row["tasks"]), (PR_NUMBER, ["a", "b"], ["A1", "B2"]))
        self.assertEqual(result["blocking_items"], ["D1", "S1"])
        self.assertEqual(result["resolved"], [])
        self.assertIn("1 open PRs, 2 blocking items", self.ledger_text())
        self.assertEqual(self.ledger_text().count(f"| {PR_NUMBER} |"), 1)

    def test_pr_resolves_only_when_every_lane_item_is_done(self) -> None:
        self.set_pr("a", PR_NUMBER)
        self.set_pr("b", PR_NUMBER)
        self.mark_done("S1")
        self.assertEqual(self.ledger()["resolved"], [])
        self.mark_done("D1")
        resolved: list[dict[str, Any]] = self.ledger()["resolved"]
        self.assertEqual([row["pr"] for row in resolved], [PR_NUMBER])

    def test_two_lanes_on_two_prs_give_two_rows(self) -> None:
        self.set_pr("a", PR_NUMBER)
        self.set_pr("b", OTHER_PR_NUMBER)
        self.mark_done("S1")
        result = self.ledger(prs=[PR_NUMBER, OTHER_PR_NUMBER])
        self.assertEqual([row["pr"] for row in result["open_prs"]], [PR_NUMBER, OTHER_PR_NUMBER])
        self.assertEqual([row["pr"] for row in result["resolved"]], [PR_NUMBER])
        self.assertIn("2 open PRs, 2 blocking items", self.ledger_text())

    def test_stop_check_needs_the_ledger_for_blocked_lanes(self) -> None:
        self.set_pr("a", PR_NUMBER)
        self.set_pr("b", PR_NUMBER)
        before = self.stop_check()
        self.assertFalse(before["stop"], before)
        self.assertEqual(before["blocked_without_ledger"], ["a", "b"])
        self.ledger()
        after = self.stop_check()
        self.assertTrue(after["stop"], after)
        self.assertEqual(after["blocked_without_ledger"], [])


if __name__ == "__main__":
    unittest.main()
