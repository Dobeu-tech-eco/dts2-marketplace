"""Regression tests for the review of the B6 lanes package: routed conflicts do not block leases, merge-go follows the
probe-planned order, and the integration lane goes through the normal merge lifecycle."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Final

import test_b9_merge_flow as b9

PASSTHROUGH_GIT: Final[str] = """#!/usr/bin/env python3
import subprocess, sys
if "--name-only" in sys.argv:
    sys.exit(0)  # the lane ownership audit: no changed files
sys.exit(subprocess.run(["git", *sys.argv[1:]], check=False).returncode)
"""
HEAD: Final[str] = "aaaaaaa1"
BASE_SHA: Final[str] = "bbbbbbb2"


class RoutedLeaseTests(b9.Base):
    def test_lease_is_granted_when_the_only_conflict_is_routed(self) -> None:
        lanes = [b9.lane("a", ["src/a/x.py", "package-lock.json"]), b9.lane("b", ["src/b/y.py", "package-lock.json"])]
        path = self.manifest(lanes)
        self.assertTrue(self.run_cmd("check", path)["ok"])
        for lane_id in ("a", "b"):
            granted = self.run_cmd("lease", path, "--lane", lane_id)
            self.assertTrue(granted["ok"], granted)

    def test_lease_still_refuses_an_unrouted_conflict(self) -> None:
        lanes = [b9.lane("a", ["src/a/x.py", "src/shared/util.py"]), b9.lane("b", ["src/b/y.py", "src/shared/util.py"])]
        refused = self.run_cmd("lease", self.manifest(lanes), "--lane", "a")
        self.assertFalse(refused["ok"])
        self.assertTrue(refused["conflicts"])


class PlannedMergeOrderTests(b9.Base):
    make_repo = b9.MergePlanTests.make_repo

    def status(self, lane_id: str, phase: str = "pr-open") -> None:
        folder: Path = self.repo / ".harness" / "runs" / b9.STAMP / lane_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "status.json").write_text(json.dumps({"status": phase}), encoding="utf-8")

    def go(self, path: str, lane_id: str) -> dict[str, Any]:
        wrapper: Path = self.fake / "git.py"
        wrapper.write_text(PASSTHROUGH_GIT, encoding="utf-8")
        return self.run_cmd("merge-go", path, "--lane", lane_id, "--head", HEAD, "--base", BASE_SHA,
                            extra_env={"DTS2_GIT_BIN": str(wrapper)})

    def done(self, path: str, lane_id: str) -> dict[str, Any]:
        return self.run_cmd("merge-done", path, "--lane", lane_id)

    def test_merge_go_follows_the_probe_planned_order(self) -> None:
        self.make_repo()
        path = self.manifest([b9.lane("a", ["f.txt"]), b9.lane("b", ["g.txt"])])
        plan = self.run_cmd("merge-plan", path, "--base", "main")
        self.assertEqual(plan["order"], ["b", "a"])
        self.assertTrue(plan["recorded"])
        self.status("a")
        self.status("b")
        self.assertFalse(self.go(path, "a")["ok"])
        self.assertEqual(self.run_cmd("merge-order", path)["next"], "b")
        self.assertTrue(self.go(path, "b")["ok"])
        self.assertTrue(self.done(path, "b")["ok"])
        self.assertTrue(self.go(path, "a")["ok"])

    def test_integration_lane_is_registered_and_merges_last(self) -> None:
        self.make_repo()
        lanes = [b9.lane("a", ["f.txt", "package-lock.json"]), b9.lane("b", ["g.txt", "package-lock.json"])]
        path = self.manifest(lanes)
        plan = self.run_cmd("merge-plan", path, "--base", "main")
        self.assertEqual(plan["order"], ["b", "a", "integration"])
        self.status("a")
        self.status("b")
        self.assertEqual(self.run_cmd("merge-order", path)["order"], ["b", "a", "integration"])
        refused_early = self.go(path, "integration")
        self.assertFalse(refused_early["ok"])
        self.assertEqual(sorted(refused_early["waiting_on"]), ["a", "b"])
        for lane_id in ("b", "a"):
            self.assertTrue(self.go(path, lane_id)["ok"])
            finished = self.done(path, lane_id)
            self.assertTrue(finished["ok"])
            self.assertFalse(finished["all_merged"], finished)
        granted = self.go(path, "integration")
        self.assertTrue(granted["ok"], granted)
        last = self.done(path, "integration")
        self.assertTrue(last["ok"], last)
        self.assertTrue(last["all_merged"])
        pending = self.repo / ".harness" / "runs" / b9.STAMP / "merge-pending.txt"
        self.assertEqual(pending.read_text(encoding="utf-8").strip(), "")

    def test_replanning_keeps_merged_lanes_in_front(self) -> None:
        self.make_repo()
        path = self.manifest([b9.lane("a", ["f.txt"]), b9.lane("b", ["g.txt"])])
        self.run_cmd("merge-plan", path, "--base", "main")
        self.status("b")
        self.assertTrue(self.go(path, "b")["ok"])
        self.done(path, "b")
        again = self.run_cmd("merge-plan", path, "--base", "main")
        self.assertTrue(again["recorded"])
        order = self.run_cmd("merge-order", path)
        self.assertEqual(order["order"][0], "b")
        self.assertEqual(order["merged"], ["b"])


if __name__ == "__main__":
    unittest.main()
