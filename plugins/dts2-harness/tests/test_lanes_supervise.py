"""Contracts for the dpp head's supervision helpers in lanes.py: status, sendback, release, fold, stop-check, and 3.9.1."""
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
from test_lanes import FAKE_GH, FAKE_GIT, lane, manifest
from test_text_contracts import ReleaseContract
from test_upgrade_check import RELEASE

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "lanes.py"
REPO_ROOT: Final[Path] = PLUGIN_ROOT.parent.parent
VERSION: Final[str] = "3.10.0"
STAMP: Final[str] = "20261104-7"
STALE_AGE_S: Final[int] = 4000
SETTING_TIMEOUT_MIN: Final[int] = 1
SETTING_AGE_S: Final[int] = 120
MAX_SEND_BACKS: Final[int] = 2
NEW_SKILLS: Final[tuple[str, ...]] = ("dpp", "dpp-full", "fullauto")


class SuperviseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dts2-supervise-"))
        self.repo = self.root / "repo"
        self.runs = self.repo / ".harness" / "runs" / STAMP
        self.runs.mkdir(parents=True)
        self.fake = self.root / "fake"
        self.fake.mkdir()
        (self.fake / "gh.py").write_text(FAKE_GH, encoding="utf-8")
        (self.fake / "git.py").write_text(FAKE_GIT, encoding="utf-8")

    def run_cmd(self, *args: str) -> dict[str, Any]:
        env = {**os.environ, "DTS2_GH_BIN": str(self.fake / "gh.py"), "DTS2_GIT_BIN": str(self.fake / "git.py"),
               "FAKE_PRS": "[]", "FAKE_REFS": ""}
        done = subprocess.run([sys.executable, "-I", str(SCRIPT), "--cwd", str(self.repo), *args],
                              capture_output=True, text=True, env=env, check=False)
        parsed: dict[str, Any] = json.loads(done.stdout)
        parsed["_code"] = done.returncode
        return parsed

    def write_status(self, lane_id: str, age_s: int = 0, **fields: Any) -> Path:
        folder: Path = self.runs / lane_id
        folder.mkdir(exist_ok=True)
        path: Path = folder / "status.json"
        path.write_text(json.dumps({"lane": lane_id, "status": "building", **fields}), encoding="utf-8")
        if age_s:
            stamp: float = time.time() - age_s
            os.utime(path, (stamp, stamp))
        return path

    def write_json(self, name: str, data: Any) -> str:
        path: Path = self.root / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return str(path)

    def lanes_by_id(self, result: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {entry["lane"]: entry for entry in result["lanes"]}

    def test_stale_status_marks_incomplete(self) -> None:
        self.write_status("a", age_s=STALE_AGE_S)
        self.write_status("b")
        self.write_status("c", age_s=STALE_AGE_S, status="done")
        lanes = self.lanes_by_id(self.run_cmd("status", STAMP))
        self.assertTrue(lanes["a"]["stale"])
        self.assertEqual(lanes["a"]["incomplete_reason"], "stalled")
        self.assertFalse(lanes["b"]["stale"])
        self.assertIsNone(lanes["b"]["incomplete_reason"])
        self.assertFalse(lanes["c"]["stale"], "a finished lane is never stalled")
        self.assertEqual(lanes["c"]["phase"], "done")

    def test_stale_threshold_follows_builder_timeout_setting(self) -> None:
        settings: Path = self.repo / ".claude" / "dts2-harness.local.md"
        settings.parent.mkdir(parents=True)
        settings.write_text(f"---\nbuilder_timeout_min: {SETTING_TIMEOUT_MIN}\n---\n", encoding="utf-8")
        self.write_status("a", age_s=SETTING_AGE_S)
        lanes = self.lanes_by_id(self.run_cmd("status", STAMP))
        self.assertTrue(lanes["a"]["stale"])

    def test_sendback_refuses_third(self) -> None:
        self.write_status("a")
        for n in range(1, MAX_SEND_BACKS + 1):
            result = self.run_cmd("sendback", STAMP, "--lane", "a", "--reason", f"fix {n}")
            self.assertTrue(result["ok"], result)
            self.assertEqual(Path(result["path"]).name, f"send-back-{n}.md")
            self.assertIn(f"fix {n}", Path(result["path"]).read_text(encoding="utf-8"))
        third = self.run_cmd("sendback", STAMP, "--lane", "a", "--reason", "fix 3")
        self.assertFalse(third["ok"])
        self.assertEqual(third["_code"], 2)
        self.assertEqual(third["count"], MAX_SEND_BACKS)
        self.assertEqual(len(list((self.runs / "a").glob("send-back-*.md"))), MAX_SEND_BACKS)

    def test_head_redispatches_after_done(self) -> None:
        draft_a = self.write_json("draft-a.json", manifest([lane("a", ["src/a.py"])], stamp=STAMP))
        self.assertTrue(self.run_cmd("lease", draft_a, "--lane", "a")["ok"])
        checkin = self.write_json("check-in.json", {"outstanding_items": ["Sb"], "complete_items": ["Sa"]})
        draft_b = self.write_json("draft-b.json", manifest([lane("b", ["src/a.py"])], stamp=STAMP))
        blocked = self.run_cmd("plan", "--from-checkin", checkin, "--draft", draft_b, "--stamp", STAMP)
        self.assertFalse(blocked["ok"], blocked)
        self.assertEqual(blocked["feasibility"]["conflicts"][0]["with"], f"lane {STAMP}/a")
        released = self.run_cmd("release", STAMP, "--lane", "a")
        self.assertTrue(released["ok"], released)
        self.assertEqual(json.loads((self.runs / "a" / "lease.json").read_text(encoding="utf-8"))["status"], "closed")
        again = self.run_cmd("plan", "--from-checkin", checkin, "--draft", draft_b, "--stamp", STAMP)
        self.assertTrue(again["ok"], again)

    def test_delegation_scan_respects_overlap_and_scope(self) -> None:
        delegated_overlap = {**lane("q1", ["src/a/a.py"]), "source": "delegation"}
        delegated_outside = {**lane("q2", ["../other/x.py"]), "source": "delegation"}
        draft = self.write_json("draft.json", manifest([lane("a", ["src/a/a.py"]), delegated_overlap, delegated_outside],
                                                       stamp=STAMP, scope_root="src"))
        checkin = self.write_json("check-in.json", {"outstanding_items": ["Sa"], "complete_items": []})
        result = self.run_cmd("plan", "--from-checkin", checkin, "--draft", draft, "--full")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["refused"], [])
        self.assertEqual([ln["id"] for ln in result["manifest"]["lanes"]], ["a"])
        reported = {r["lane"]: r["reasons"] for r in result["reported"]}
        self.assertEqual(set(reported), {"q1", "q2"})
        self.assertTrue(any("files" in reason for reason in reported["q1"]), reported)
        self.assertTrue(any("scope" in reason for reason in reported["q2"]), reported)

    def test_report_requires_post_merge_section(self) -> None:
        report: Path = self.root / "dpp-report.md"
        report.write_text("## Lane a\n### Item\nx\n## Spend\nx\n## Task ledger\nx\n", encoding="utf-8")
        result = self.run_cmd("report-check", str(report), "--lanes", "a")
        self.assertFalse(result["ok"])
        self.assertIn({"lane": "a", "section": "Post-merge walkthrough"}, result["missing"])

    def test_head_folds_blocked_lanes_into_fewest_prs(self) -> None:
        self.write_status("a", status="blocked", pr=11, files=["src/a.py"], tasks=["A1"], blocked_by=["S1"])
        self.write_status("b", status="blocked", pr=12, files=["src/b.py"], tasks=["B1"], blocked_by=["D1"])
        self.write_status("c", status="blocked", pr=13, files=["src/a.py"], tasks=["C1"], blocked_by=["S2"])
        self.write_status("d", status="done", pr=14, files=["src/d.py"], tasks=["D9"])
        result = self.run_cmd("fold", STAMP)
        self.assertTrue(result["ok"], result)
        self.assertEqual([g["lanes"] for g in result["groups"]], [["a", "b"], ["c"]])
        self.assertEqual(result["groups"][0]["tasks"], ["A1", "B1"])
        self.assertEqual(result["groups"][0]["blocked_by"], ["D1", "S1"])
        self.assertEqual(result["groups"][0]["prs"], [11, 12])
        self.assertEqual(result["open_prs"], 2)

    def test_fullauto_stops_with_blocked_lanes_in_ledger(self) -> None:
        self.write_status("a", status="done", pr=11)
        self.write_status("b", status="blocked", pr=12, blocked_by=["S1"])
        quiet = self.write_json("quiet.json", {"outstanding_items": [], "complete_items": ["Sa", "Sb"]})
        before = self.run_cmd("stop-check", STAMP, "--from-checkin", quiet)
        self.assertFalse(before["stop"], before)
        self.assertEqual(before["blocked_without_ledger"], ["b"])
        (self.runs / "task-ledger.md").write_text("# Task ledger\n\n| PR | branch | tasks | blocked by |\n"
                                                  "| --- | --- | --- | --- |\n| 12 | dts2/x/b | B1 | S1 x |\n\n"
                                                  "1 open PRs, 1 blocking items\n", encoding="utf-8")
        after = self.run_cmd("stop-check", STAMP, "--from-checkin", quiet)
        self.assertTrue(after["stop"], after)
        self.assertTrue(after["ok"])
        busy = self.write_json("busy.json", {"outstanding_items": ["Sc"], "complete_items": ["Sa", "Sb"]})
        self.assertFalse(self.run_cmd("stop-check", STAMP, "--from-checkin", busy)["stop"])
        self.write_status("e", status="building")
        self.assertFalse(self.run_cmd("stop-check", STAMP, "--from-checkin", quiet)["stop"])


class ReleaseTests(unittest.TestCase):
    def test_version_is_3_9_1_everywhere(self) -> None:
        plugin = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        market = json.loads((REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual(plugin["version"], VERSION)
        self.assertEqual([p["version"] for p in market["plugins"]], [VERSION])
        self.assertEqual(ReleaseContract.VERSION, VERSION)
        self.assertEqual(RELEASE, VERSION)
        readme: str = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
        changelog: str = (PLUGIN_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")  # released sections moved here (D3)
        self.assertIn(f"## [{VERSION}]", changelog)
        self.assertLess(changelog.index(f"## [{VERSION}]"), changelog.index("## [3.8.0]"))
        onboard: str = (PLUGIN_ROOT / "skills" / "onboard" / "SKILL.md").read_text(encoding="utf-8")
        for skill in NEW_SKILLS:
            self.assertTrue((PLUGIN_ROOT / "skills" / skill / "SKILL.md").is_file(), skill)
            self.assertIn(f"| `{skill}` |", readme)
            self.assertIn(f"| `{skill}` |", onboard)
        self.assertIn("check-in, ship, feature, autopilot, dpp, dpp-full, fullauto", readme)


if __name__ == "__main__":
    unittest.main()
