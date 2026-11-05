"""Batch 19: regression tests for the bot-review findings on the lifecycle and mailbox rounds."""
from __future__ import annotations

import importlib.util
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

import proc  # noqa: E402
import son_stream  # noqa: E402
from lanes import mailbox, planner, policy  # noqa: E402
from lanes.leases import lease_epoch, read_lease, write_lease  # noqa: E402
from lanes.phases import heartbeat  # noqa: E402
from lanes.records import read_json_object  # noqa: E402
from state_io import RUNS_REL  # noqa: E402

STAMP: Final[str] = "20261105-19"
DRAIN_LIMIT_S: Final[float] = 4.0
SLOW_CHILD_S: Final[int] = 12
LONG_OBSERVATION: Final[int] = 3000
TTL_S: Final[int] = 3600


class RunOnceDeadlineTests(unittest.TestCase):
    def test_streaming_run_is_not_held_by_a_descendant_that_keeps_the_pipes(self) -> None:
        started = time.monotonic()
        done = proc.run_once(["bash", "-c", f"sleep {SLOW_CHILD_S} & echo hi; sleep 0.2"], ".", 1, on_line=lambda line: False)
        self.assertLess(time.monotonic() - started, DRAIN_LIMIT_S)
        self.assertEqual(done["stdout"], "hi\n")

    def test_plain_streaming_run_still_returns_all_output(self) -> None:
        done = proc.run_once(["bash", "-c", "echo a; echo b"], ".", 5, on_line=lambda line: False)
        self.assertEqual((done["code"], done["stdout"], done["timed_out"]), (0, "a\nb\n", False))


class StuckDigestTests(unittest.TestCase):
    @staticmethod
    def events(observations: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for index, text in enumerate(observations):
            out.append({"message": {"content": [{"type": "tool_use", "id": f"t{index}", "name": "Bash", "input": {"c": "x"}}]}})
            out.append({"message": {"content": [{"type": "tool_result", "tool_use_id": f"t{index}", "content": text}]}})
        return out

    def test_results_that_differ_only_after_the_old_truncation_are_not_stuck(self) -> None:
        texts = ["a" * LONG_OBSERVATION + str(n) for n in range(son_stream.STUCK_SAME)]
        self.assertIsNone(son_stream.detect_stuck(self.events(texts)))

    def test_identical_long_results_are_still_stuck(self) -> None:
        texts = ["a" * LONG_OBSERVATION] * son_stream.STUCK_SAME
        self.assertIn("same action and observation", son_stream.detect_stuck(self.events(texts)) or "")


class LaneCase(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="dts2-b19-"))
        self.runs = self.repo / RUNS_REL
        (self.runs / STAMP / "a").mkdir(parents=True)

    def lease(self, bumps: int = 1) -> Path:
        path = self.runs / STAMP / "a" / "lease.json"
        for _ in range(bumps):
            write_lease({"stamp": STAMP, "base": "abc"}, {"id": "a", "item": "Sa", "files": []}, path, None, TTL_S)
        return path


class MailboxStaleParkTests(LaneCase):
    def test_a_timed_out_question_parks_the_lane_it_was_asked_in(self) -> None:
        self.lease()
        asked = mailbox.ask(self.runs, STAMP, "a", "which?", self.repo, now=1000)
        out = mailbox.check(self.runs, STAMP, "a", asked["id"], now=10 ** 9)
        self.assertEqual((out["state"], out["parked"]), ("expired", True))

    def test_a_stale_question_does_not_park_a_re_leased_lane(self) -> None:
        self.lease()
        asked = mailbox.ask(self.runs, STAMP, "a", "which?", self.repo, now=1000)
        self.lease()  # the lane was re-leased: its epoch moved on
        out = mailbox.check(self.runs, STAMP, "a", asked["id"], now=10 ** 9)
        self.assertEqual((out["state"], out["parked"]), ("stale", False))
        status = read_json_object(self.runs / STAMP / "a" / "status.json")
        self.assertNotEqual(status.get("status"), "incomplete")


class HeartbeatFenceTests(LaneCase):
    def test_a_stale_heartbeat_neither_writes_nor_renews_the_lease(self) -> None:
        path = self.lease(bumps=2)
        before = read_lease(path)
        out = heartbeat(self.runs, STAMP, "a", 1, epoch=lease_epoch(before) - 1)
        self.assertTrue(out.get("stale"), out)
        self.assertEqual(read_lease(path), before)
        self.assertFalse((self.runs / STAMP / "a" / "status.json").exists())

    def test_a_current_heartbeat_still_stamps_the_lane(self) -> None:
        path = self.lease()
        out = heartbeat(self.runs, STAMP, "a", 2, epoch=lease_epoch(read_lease(path)))
        self.assertTrue(out["ok"], out)
        self.assertEqual(read_json_object(self.runs / STAMP / "a" / "status.json")["turn"], 2)


class FrozenScopePlanTests(LaneCase):
    @staticmethod
    def lane(lane_id: str) -> dict[str, Any]:
        return {"id": lane_id, "item": f"S{lane_id}", "files": [f"src/{lane_id}.py"], "ids": {}, "depends_on": [], "tier": "standard"}

    def plan(self, frozen: set[str] | None) -> dict[str, Any]:
        draft = {"stamp": STAMP, "base": "abc", "scope": "single", "lanes": [self.lane("a"), self.lane("b")]}
        return planner.plan(draft, {"Sa", "Sb"}, "", True, 1, self.runs, self.repo, False, frozen)

    def test_an_in_scope_lane_is_picked_when_the_first_candidate_is_out_of_scope(self) -> None:
        result = self.plan({"Sb"})
        self.assertEqual([lane["id"] for lane in result["manifest"]["lanes"]], ["b"])
        self.assertEqual(result["out_of_scope"], ["Sa"])

    def test_without_a_frozen_scope_the_first_candidate_wins(self) -> None:
        result = self.plan(None)
        self.assertEqual([lane["id"] for lane in result["manifest"]["lanes"]], ["a"])
        self.assertNotIn("out_of_scope", result)

    def test_out_of_scope_items_are_recorded_as_pending(self) -> None:
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude" / "dts2-harness.local.md").write_text("---\nfullauto_freeze_scope: true\n---\n", encoding="utf-8")
        policy.apply_policy({"stamp": STAMP, "ok": True, "manifest": {"lanes": [self.lane("b")]}}, self.runs, self.repo,
                            full=True, fullauto=True, autopilot=True)
        frozen = policy.frozen_items(self.runs, STAMP, self.repo, True)
        self.assertEqual(frozen, {"Sb"})
        result = policy.apply_policy({**self.plan(frozen), "stamp": STAMP}, self.runs, self.repo, full=True, fullauto=True, autopilot=True)
        self.assertEqual(result["pending"], ["Sa"])
        self.assertEqual([lane["id"] for lane in result["manifest"]["lanes"]], ["b"])


class SonContractTextTests(unittest.TestCase):
    def test_the_contract_reports_pr_open_before_waiting_for_the_grant(self) -> None:
        text = (PLUGIN_ROOT / "skills" / "autopilot" / "son-contract.md").read_text(encoding="utf-8")
        self.assertNotIn("Before it reports `pr-open` as ready", text)
        line = next(row for row in text.splitlines() if row.startswith("- **Merge needs the exact head.**"))
        self.assertLess(line.index("reports `pr-open` first"), line.index("merge-go-check"))
        self.assertIn("then waits for the grant", line)


def load_guard() -> Any:
    spec = importlib.util.spec_from_file_location("context_guard_b19", SCRIPTS / "context-guard.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ActiveRunPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guard = load_guard()
        self.repo = Path(tempfile.mkdtemp(prefix="dts2-b19g-"))
        for stamp, has_plan in (("20260101-1", True), ("20260202-2", False)):
            folder = self.repo / RUNS_REL / stamp
            folder.mkdir(parents=True)
            if has_plan:
                (folder / "plan.md").write_text("plan\n", encoding="utf-8")
        (self.repo / ".git").mkdir()

    def on_branch(self, branch: str) -> None:
        (self.repo / ".git" / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")

    def test_the_active_stamp_comes_from_the_run_branch(self) -> None:
        self.on_branch("dts2/20260202-2/main")
        self.assertEqual(self.guard.active_stamp(self.repo), "20260202-2")
        self.on_branch("main")
        self.assertIsNone(self.guard.active_stamp(self.repo))

    def test_an_older_runs_plan_does_not_count_for_the_active_run(self) -> None:
        self.on_branch("dts2/20260202-2/main")
        self.assertFalse(self.guard.has_plan(self.repo, self.guard.active_stamp(self.repo)))

    def test_the_active_runs_own_plan_counts(self) -> None:
        self.on_branch("dts2/20260101-1/main")
        self.assertTrue(self.guard.has_plan(self.repo, self.guard.active_stamp(self.repo)))

    def test_with_no_active_run_any_plan_counts(self) -> None:
        self.on_branch("main")
        self.assertTrue(self.guard.has_plan(self.repo, self.guard.active_stamp(self.repo)))


class SonApprovalKeyTests(LaneCase):
    def test_a_son_may_not_write_the_human_approval_file(self) -> None:
        import son_launch
        worktree = self.repo / "wt"
        worktree.mkdir()
        _allow, deny = son_launch.write_scope({"stamp": STAMP}, "a", self.repo, worktree)
        self.assertIn(str(self.repo.resolve() / ".claude" / "settings.local.json"), deny)
        self.assertIn(str(worktree.resolve() / ".claude" / "settings.local.json"), deny)


if __name__ == "__main__":
    unittest.main()
