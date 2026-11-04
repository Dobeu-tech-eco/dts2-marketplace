"""Review fixes for the supervisor: a lane is never parked or resumed under a running son, a JSON-reported 429 on a
retried attempt is not unknown spend, and a resumed son's dollar flag is the lane's share. Every
model is a fake DTS2_CLAUDE_BIN script; nothing real runs."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
from typing import Any, Final

import test_supervisor as base
from test_supervisor_fixes import FixBase, result

STAMP: Final[str] = base.STAMP


class RunningSonTests(FixBase):
    def status_file(self) -> dict[str, Any]:
        data: dict[str, Any] = json.loads((self.lane_dir / "status.json").read_text(encoding="utf-8"))
        return data

    def start_slow_son(self) -> subprocess.Popen[str]:
        self.preflight()
        env = {**os.environ, **self.env, **self.say({"sleep": 6, "stdout": result(0.5, "S1")})}
        proc = subprocess.Popen([sys.executable, "-I", str(base.LANES), "--cwd", str(self.repo), "--no-prs", "spawn",
                                 str(self.manifest), "--lane", "a", "--worktree", str(self.worktree)],
                                env=env, stdout=subprocess.PIPE, text=True)
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                if self.status_file().get("son_pid"):
                    return proc
            except (OSError, ValueError):
                pass
            time.sleep(0.1)
        proc.kill()
        self.fail("the son never recorded its pid")

    def age_status(self) -> None:
        path = self.lane_dir / "status.json"
        old = int(time.time()) - 3600
        path.write_text(json.dumps({**self.status_file(), "heartbeat": old, "worktree": str(self.worktree)}))
        os.utime(path, (old, old))

    def test_stale_lane_with_a_running_son_is_not_parked_or_resumed(self) -> None:
        proc = self.start_slow_son()
        try:
            self.age_status()
            row = self.lanes("status", STAMP)["lanes"][0]
            self.assertTrue(row["stale"])
            self.assertTrue(row["alive"])
            self.assertIsNone(row["incomplete_reason"])
            self.assertIsNotNone(row["snapshot"])
            self.assertNotEqual(self.status_file()["status"], "incomplete")
            refused = self.spawn("--resume")
            self.assertFalse(refused["ok"])
            self.assertEqual(refused["reason"], "running")
            self.assertNotEqual(self.status_file()["status"], "incomplete")
            self.assertEqual(len(self.son_calls()), 1, "no second son started")
        finally:
            proc.communicate(timeout=60)
        after = self.status_file()
        self.assertFalse(after.get("son_pid"))
        self.assertFalse(after.get("spawn_pid"))

    def test_pids_are_recorded_while_the_son_runs(self) -> None:
        proc = self.start_slow_son()
        try:
            data = self.status_file()
            self.assertEqual(data["spawn_pid"], proc.pid)
            self.assertNotEqual(data["son_pid"], proc.pid)
        finally:
            proc.communicate(timeout=60)

    def test_stale_lane_whose_process_is_gone_is_still_marked_incomplete(self) -> None:
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait()
        path = self.lane_dir / "status.json"
        old = int(time.time()) - 3600
        path.write_text(json.dumps({"lane": "a", "status": "building", "heartbeat": old, "son_pid": gone.pid,
                                    "worktree": str(self.worktree)}))
        os.utime(path, (old, old))
        row = self.lanes("status", STAMP)["lanes"][0]
        self.assertFalse(row["alive"])
        self.assertEqual(self.status_file()["status"], "incomplete")

    def test_dead_recorded_pids_do_not_block_a_spawn(self) -> None:
        self.preflight()
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait()
        self.lane_dir.joinpath("status.json").write_text(json.dumps({"lane": "a", "status": "done", "son_pid": gone.pid,
                                                                     "spawn_pid": gone.pid}))
        out = self.spawn(**self.say({"stdout": result(0.5, "S1")}))
        self.assertTrue(out["ok"], out)


class JsonReported429Tests(FixBase):
    def setUp(self) -> None:
        super().setUp()
        self.config("budget:\n  max_usd: 10\nsupervisor:\n  backoff_base_s: 0\n  retry_max: 2\n")

    @staticmethod
    def refusal() -> dict[str, Any]:
        return {"type": "result", "is_error": True, "total_cost_usd": 0, "session_id": "X1",
                "result": "API Error: 429"}

    def test_costless_429_on_a_retried_attempt_is_zero_spend(self) -> None:
        first = self.call("voter", **self.say({"code": 1, "stdout": self.refusal()}, {"stdout": result(0.5, "S2")}))
        self.assertTrue(first["ok"], first)
        self.assertEqual(first["retries"], 1)
        budget = self.budget()
        self.assertEqual((budget["unknown_calls"], budget["spent_usd"]), (0, 0.5))
        self.assertEqual(budget["lanes"]["call:voter"]["rounds"], 1)
        second = self.call("again", **self.say({"stdout": result(0.5, "S3")}))
        self.assertTrue(second["ok"], second)

    def test_the_final_attempt_keeps_the_unknown_rule(self) -> None:
        self.call("voter", **self.say({"code": 1, "stdout": self.refusal()}))
        self.assertEqual(self.budget()["unknown_calls"], 1)

    def test_a_429_that_ran_several_turns_is_still_unknown(self) -> None:
        ran = {**self.refusal(), "num_turns": 5}
        self.call("voter", **self.say({"code": 1, "stdout": ran}, {"stdout": result(0.5, "S2")}))
        self.assertEqual(self.budget()["unknown_calls"], 1)

    def test_a_non_overload_error_is_not_retried_and_its_missing_cost_is_unknown(self) -> None:
        broken = {**self.refusal(), "result": "boom"}
        self.call("voter", **self.say({"code": 1, "stdout": broken}, {"stdout": result(0.5, "S2")}))
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(self.budget()["unknown_calls"], 1)


class ResumeBudgetTests(FixBase):
    def test_resumed_flag_is_the_lanes_share_only(self) -> None:
        self.config("budget:\n  max_usd: 10\n")
        self.preflight()
        first = self.spawn(**self.say({"stdout": result(1.0, "S1")}))
        self.assertEqual(first["charged_usd"], 1.0)
        self.spawn("--resume", **self.say({"stdout": result(1.5, "S1")}))
        calls = self.son_calls()
        first_cap = float(calls[0][calls[0].index("--max-budget-usd") + 1])
        argv = calls[1]
        cap = float(argv[argv.index("--max-budget-usd") + 1])
        share = round(10.0 - 1.0, 2)
        self.assertEqual(first_cap, 10.0)
        self.assertEqual(cap, share)
        self.assertEqual(argv[argv.index("--resume") + 1], "S1")
        self.assertEqual(self.budget()["spent_usd"], 1.5)

    def test_fallback_flag_is_a_chain_passed_once(self) -> None:
        self.config("supervisor:\n  fallback_models: sonnet, haiku\n")
        self.preflight()
        self.spawn(**self.say({"stdout": result(0.1, "S1")}))
        argv = self.son_calls()[0]
        self.assertEqual(argv[argv.index("--fallback-model") + 1], "sonnet,haiku")
        self.assertEqual(argv.count("--fallback-model"), 1)


class ParkedLaneLifecycleTests(FixBase):
    def write_status(self, data: dict[str, Any], age: int = 0) -> None:
        path = self.lane_dir / "status.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
        old = int(time.time()) - age
        os.utime(path, (old, old))

    def test_pr_open_lane_with_an_old_heartbeat_is_not_parked(self) -> None:
        self.preflight()
        self.write_status({"lane": "a", "status": "pr-open", "heartbeat": int(time.time()) - 700}, age=3600)
        rows = self.lanes("status", STAMP)["lanes"]
        self.assertEqual(rows[0]["phase"], "pr-open")
        self.assertFalse(rows[0]["stale"])
        self.assertEqual(json.loads((self.lane_dir / "status.json").read_text())["status"], "pr-open")
        manifest = json.loads(self.manifest.read_text())
        self.assertEqual(manifest["lanes"][0]["id"], "a")
        self.assertTrue(self.lanes("merge-go", str(self.manifest), "--lane", "a", "--head", "abc")["ok"])

    def test_resume_of_a_parked_lane_resets_its_phase(self) -> None:
        self.preflight()
        first = self.spawn(**self.say({"code": 1, "stdout": result(0.5, "S1", True, "boom")}))
        self.assertFalse(first["ok"])
        parked = self.status_json()
        self.assertEqual((parked["status"], parked["reason"]), ("incomplete", "error"))
        resumed = self.spawn("--resume", **self.say({"stdout": result(0.8, "S1")}))
        self.assertFalse(resumed["ok"], resumed)
        self.assertEqual(resumed["reason"], "no-final-status")
        now = self.status_json()
        self.assertEqual(now["status"], "incomplete")
        self.assertEqual(now["reason"], "no-final-status")

    def test_stale_live_lane_is_snapshotted_once_per_stall_window(self) -> None:
        self.preflight()
        self.write_status({"lane": "a", "status": "building", "heartbeat": int(time.time()) - 3600,
                           "son_pid": os.getpid(), "worktree": str(self.worktree)}, age=3600)
        for _ in range(3):
            self.assertTrue(self.lanes("status", STAMP)["lanes"][0]["alive"])
        self.assertEqual(len(list(self.lane_dir.glob("stall-*.diff"))), 1)


class MergeOrderLockTests(base.SupervisorBase):
    def test_merge_commands_leave_no_lock_behind(self) -> None:
        for lane_id in ("a",):
            (self.runs / lane_id).mkdir(exist_ok=True)
        self.lane_dir.joinpath("status.json").write_text(json.dumps({"lane": "a", "status": "pr-open"}))
        self.assertTrue(self.lanes("merge-order", str(self.manifest))["ok"])
        self.assertTrue(self.lanes("merge-go", str(self.manifest), "--lane", "a", "--head", "abc")["ok"])
        self.assertTrue(self.lanes("merge-done", str(self.manifest), "--lane", "a")["ok"])
        self.assertEqual(list(self.runs.glob("*.lock")), [])
        self.assertEqual(self.json_file("merge-order.json")["merged"], ["a"])


if __name__ == "__main__":
    unittest.main()
