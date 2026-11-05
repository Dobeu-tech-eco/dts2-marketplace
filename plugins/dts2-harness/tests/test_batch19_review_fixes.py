"""Batch 19: regression tests for the bot-review findings on the lifecycle and mailbox rounds."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import proc  # noqa: E402
import head_publish  # noqa: E402
import protected  # noqa: E402
import son_launch  # noqa: E402
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
        worktree = self.repo / "wt"
        worktree.mkdir()
        _allow, deny = son_launch.write_scope({"stamp": STAMP}, "a", self.repo, worktree)
        self.assertIn(str(self.repo.resolve() / ".claude" / "settings.local.json"), deny)
        self.assertIn(str(worktree.resolve() / ".claude" / "settings.local.json"), deny)


GIT_ENV: Final[dict[str, str]] = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                                  "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def sh(repo: Path, *argv: str) -> None:
    subprocess.run(argv, cwd=repo, check=True, capture_output=True, env={**os.environ, **GIT_ENV})


class PublishCase(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="dts2-b19p-"))
        self.calls: list[list[str]] = []
        self.answers: dict[str, tuple[int, str]] = {}
        self.names: list[str] = ["src/a.py"]

    def runner(self, argv: list[str], cwd: Path) -> tuple[int, str]:
        self.calls.append(argv)
        if argv[1:2] == ["diff"]:
            return 0, "\n".join(self.names)
        for prefix, answer in self.answers.items():
            if " ".join(argv[1:4]).startswith(prefix):
                return answer
        return 0, ""

    def publish(self) -> dict[str, Any]:
        return head_publish.publish_lane(self.repo, "a", "dts2/s/lane-a", "main", "t", "b", self.runner)


class PublishRefusalTests(PublishCase):
    def test_a_son_cannot_publish_or_merge(self) -> None:
        old = os.environ.get("DTS2_SON")
        os.environ["DTS2_SON"] = "1"
        try:
            self.assertFalse(self.publish()["ok"])
            self.assertFalse(head_publish.merge_pr(self.repo, "5", True, "main", False, self.runner)["merged"])
        finally:
            os.environ.pop("DTS2_SON", None) if old is None else os.environ.update(DTS2_SON=old)
        self.assertEqual(self.calls, [])

    def test_the_diff_is_read_without_rename_detection(self) -> None:
        self.publish()
        self.assertIn("--no-renames", next(c for c in self.calls if c[1:2] == ["diff"]))

    def test_a_protected_file_renamed_out_of_its_folder_is_still_refused(self) -> None:
        sh(self.repo, "git", "init", "-q", "-b", "main")
        (self.repo / ".github" / "workflows").mkdir(parents=True)
        (self.repo / ".github" / "workflows" / "ci.yml").write_text("on: push\n" * 20, encoding="utf-8")
        sh(self.repo, "git", "add", "."), sh(self.repo, "git", "commit", "-q", "-m", "base")
        sh(self.repo, "git", "checkout", "-q", "-b", "lane")
        (self.repo / "docs").mkdir()
        sh(self.repo, "git", "mv", ".github/workflows/ci.yml", "docs/ci.yml"), sh(self.repo, "git", "commit", "-q", "-m", "mv")
        names = head_publish.diff_names(self.repo, "main", "lane")
        self.assertIn(".github/workflows/ci.yml", names or [])
        self.assertEqual(protected.diff_touches_protected(names or [], self.repo), [".github/workflows/ci.yml"])

    def test_the_approval_file_and_hooks_at_any_depth_are_protected(self) -> None:
        for name in (".claude/settings.local.json", "hooks/x.sh", "plugins/p/hooks/hooks.json", "a/b/hooks/y.sh"):
            self.assertTrue(protected.is_protected(name, self.repo), name)
        self.assertFalse(protected.is_protected("src/a.py", self.repo))

    def test_publish_refuses_a_diff_touching_the_approval_file(self) -> None:
        self.names = ["src/a.py", ".claude/settings.local.json"]
        self.assertFalse(self.publish()["ok"])
        self.assertFalse(any(c[1:2] == ["push"] for c in self.calls))


class PublishPrTests(PublishCase):
    def test_a_closed_pr_is_not_adopted(self) -> None:
        self.answers["pr list"] = (0, json.dumps([{"number": 3, "state": "CLOSED"}]))
        self.answers["pr create"] = (0, "https://github.com/o/r/pull/8\n")
        result = self.publish()
        self.assertEqual((result["pr"], result["adopted"]), ("8", False))
        self.assertIn("open", next(c for c in self.calls if c[1:3] == ["pr", "list"]))

    def test_the_default_branch_comes_from_the_merge_setting(self) -> None:
        (self.repo / ".harness").mkdir()
        (self.repo / ".harness" / "config.yaml").write_text("merge:\n  default_branch: trunk\n", encoding="utf-8")
        self.assertEqual(head_publish.default_branch_of(self.repo), "trunk")
        facts = {"base": "trunk", "checks": [{"conclusion": "SUCCESS"}], "required_checks": False, "review": None, "head": "abc", "readable": True}
        with unittest.mock.patch.object(head_publish, "pr_facts", return_value=facts):
            done = head_publish.merge_pr(self.repo, "5", True, None, False, self.runner)
        self.assertFalse(done["merged"])
        self.assertIn("trunk needs required checks", done["blockers"][0])

    def test_the_default_branch_falls_back_to_main(self) -> None:
        self.assertEqual(head_publish.default_branch_of(self.repo), "main")

    def test_a_same_size_lockfile_change_changes_the_stamp(self) -> None:
        (self.repo / "package-lock.json").write_text("aaaa", encoding="utf-8")
        before = head_publish.lockfile_stamp(self.repo)
        (self.repo / "package-lock.json").write_text("bbbb", encoding="utf-8")
        self.assertNotEqual(before, head_publish.lockfile_stamp(self.repo))
        self.assertIn(hashlib.sha256(b"bbbb").hexdigest(), head_publish.lockfile_stamp(self.repo))


class SonAllowlistTests(unittest.TestCase):
    def test_a_son_may_run_only_the_plugins_own_scripts(self) -> None:
        rules = son_launch.HARNESS_ALLOWED
        self.assertNotIn("Bash(python3 -I *scripts/*)", rules)
        self.assertIn(f"Bash(python3 -I {SCRIPTS}/*)", rules)

    def test_a_son_may_not_reach_head_publish(self) -> None:
        self.assertIn("Bash(*head_publish.py*)", son_launch.DISALLOWED)


class CouncilDispatchDocsTests(unittest.TestCase):
    def test_both_autopilot_docs_name_the_provenance_dispatcher(self) -> None:
        for name in ("phase-0-preflight.md", "phase-1-gate.md"):
            text = (PLUGIN_ROOT / "skills" / "autopilot" / name).read_text(encoding="utf-8")
            self.assertIn("ballot_dispatch.py", text, name)
            self.assertIn(".dispatch.json", text, name)


if __name__ == "__main__":
    unittest.main()
