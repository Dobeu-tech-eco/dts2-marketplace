"""Batch 20: regression tests for the bot-review findings on PR 54 (wave 2a)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import agent_events  # noqa: E402
import checks  # noqa: E402
import council  # noqa: E402
import head_publish  # noqa: E402
import receipts_sign  # noqa: E402
from lanes import journal, mergecomp  # noqa: E402
from lanes.merge import merge_go_step  # noqa: E402
from lanes.runstate import report_check  # noqa: E402
from test_batch9_merge import STAMP, TIP, Base  # noqa: E402
from test_batch11_report import make_run  # noqa: E402
from test_batch19_review_fixes import PublishCase, StopHookCase  # noqa: E402
from lanes.common import LANE_SECTIONS, RUN_SECTIONS  # noqa: E402

OLD_STAMP: Final[str] = "20260101-000000"
NEW_STAMP: Final[str] = "20260102-000000"
HEAD: Final[str] = "f" * 40


def write_ledger(repo: Path, stamp: str, names: tuple[str, ...]) -> None:
    path = repo / checks.RUNS_DIR / stamp / checks.LEDGER_NAME
    for name in names:
        checks.append_ledger(path, {"kind": "check", "name": name, "status": "pass"})


class VerifierLedgerScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)

    def test_a_run_without_a_ledger_is_missing_every_check_even_when_an_older_run_is_complete(self) -> None:
        write_ledger(self.repo, OLD_STAMP, checks.EXPECTED_CHECKS)
        (self.repo / checks.RUNS_DIR / NEW_STAMP).mkdir(parents=True)
        self.assertEqual(agent_events.missing_check_lines(self.repo), list(checks.EXPECTED_CHECKS))

    def test_the_current_runs_own_ledger_decides(self) -> None:
        write_ledger(self.repo, OLD_STAMP, checks.EXPECTED_CHECKS)
        write_ledger(self.repo, NEW_STAMP, checks.EXPECTED_CHECKS)
        self.assertEqual(agent_events.missing_check_lines(self.repo), [])

    def test_no_run_at_all_holds_nobody(self) -> None:
        self.assertEqual(agent_events.missing_check_lines(self.repo), [])


class MergeGoStepGateTests(Base):
    def red_base(self) -> None:
        red = json.dumps({"check_runs": [{"name": "ci", "status": "completed", "conclusion": "failure"}]})
        with mock.patch.dict(os.environ, {"FAKE_CHECKS": red}):
            mergecomp.base_health(self.runs, STAMP, self.repo)

    def test_a_red_base_refuses_an_autopilot_step(self) -> None:
        self.red_base()
        refused = merge_go_step(self.runs, STAMP, "s1", HEAD, self.repo, TIP)
        self.assertFalse(refused["ok"])
        self.assertIn("not green", refused["detail"])
        self.assertFalse((self.runs / STAMP / "s1" / "merge-go.md").exists())

    def test_another_lanes_mutex_refuses_a_step(self) -> None:
        mergecomp.merge_mutex(self.runs, STAMP, "a", "acquire", self.repo)
        self.assertIn("mutex", merge_go_step(self.runs, STAMP, "s1", HEAD, self.repo, TIP)["detail"])

    def test_without_records_the_step_is_granted(self) -> None:
        self.assertTrue(merge_go_step(self.runs, STAMP, "s1", HEAD, self.repo, TIP)["ok"])

    def test_the_revert_step_acts_for_the_mutex_holder_and_is_not_held_by_the_red_base_it_repairs(self) -> None:
        self.red_base()
        mergecomp.merge_mutex(self.runs, STAMP, "a", "acquire", self.repo)
        self.assertTrue(merge_go_step(self.runs, STAMP, "revert-a", HEAD, self.repo, TIP)["ok"])
        self.assertFalse(merge_go_step(self.runs, STAMP, "revert-b", HEAD, self.repo, TIP)["ok"])


class SignedKeyFailsClosedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_unset_is_unsigned_mode(self) -> None:
        self.assertIsNone(receipts_sign.read_key({}))

    def test_a_configured_key_that_is_missing_or_empty_raises(self) -> None:
        empty = self.dir / "empty"
        empty.write_text("\n", encoding="utf-8")
        for path in (self.dir / "absent", empty):
            with self.assertRaises(receipts_sign.KeyUnreadable):
                receipts_sign.read_key({receipts_sign.KEY_FILE_VAR: str(path)})

    def test_the_cli_refuses_to_append_or_verify_with_an_unreadable_key(self) -> None:
        journal_path = self.dir / "j.jsonl"
        env = {receipts_sign.KEY_FILE_VAR: str(self.dir / "absent")}
        for argv in (["append", str(journal_path), "{}"], ["verify", str(journal_path)]):
            with mock.patch.dict(os.environ, env), mock.patch.object(sys, "argv", ["receipts_sign.py", *argv]):
                self.assertEqual(receipts_sign.main(), receipts_sign.EXIT_BAD)
        self.assertFalse(journal_path.exists())


class RevertBranchRetryTests(Base):
    def test_the_branch_is_reset_not_created_so_a_retry_works(self) -> None:
        folder = self.runs / STAMP / "revert-a"
        self.assertIsNone(journal.build_revert_branch("c" * 40, "revert/x-a", "main", folder, self.repo))
        add = self.calls("git", "worktree", "add")[0]
        self.assertIn("-B", add)
        self.assertNotIn("-b", add)
        self.assertIn("--force-with-lease", self.calls("git", "push")[0])


class CheckRunsPaginationTests(Base):
    def test_every_page_is_merged(self) -> None:
        pages = json.dumps([{"check_runs": [{"name": "a", "status": "completed", "conclusion": "success"}]},
                            {"check_runs": [{"name": "b", "status": "completed", "conclusion": "failure"}]}])
        with mock.patch.dict(os.environ, {"FAKE_CHECKS": pages}):
            runs, _ = mergecomp.check_runs(TIP, self.repo)
        self.assertEqual([r["name"] for r in runs or []], ["a", "b"])
        self.assertIn("--paginate", self.calls("gh", "api", "--paginate")[0])
        self.assertEqual(mergecomp.judge_checks(runs or [])[0], ["b"])

    def test_one_unreadable_page_is_not_green(self) -> None:
        with mock.patch.dict(os.environ, {"FAKE_CHECKS": json.dumps([{"check_runs": []}, {"oops": 1}])}):
            self.assertIsNone(mergecomp.check_runs(TIP, self.repo)[0])


class CouncilInstanceTests(unittest.TestCase):
    def test_a_later_round_never_reuses_an_instance_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            votes = Path(tmp)
            first = council.next_round(votes, "s3", "plan")
            for order, seat in enumerate(("a", "b", "c"), 1):
                name = f"{order:02d}-plan-r1-{seat}.md"
                (votes / name).write_text("VOTE: REJECT\n", encoding="utf-8")
            second = council.next_round(votes, "s3", "plan")
            third = council.next_round(votes, "s3", "build")
        ids = [first["instance"], second["instance"], third["instance"]]
        self.assertEqual(len(set(ids)), 3, ids)


class ReportPrBoundaryTests(unittest.TestCase):
    def test_pr_7_is_not_found_in_pr_70(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runs = make_run(Path(tmp))
            report = Path(tmp) / "r.md"
            body = "## Lane a\n" + "".join(f"### {s}\nx\n" for s in LANE_SECTIONS) + "".join(f"## {s}\nx\n" for s in RUN_SECTIONS)
            report.write_text(body + "PR #70\n", encoding="utf-8")
            self.assertEqual(report_check(report, ["a"], runs, OLD_STAMP)["unreferenced_prs"], [{"lane": "a", "pr": 7}])
            report.write_text(body + "PR #7.\n", encoding="utf-8")
            self.assertTrue(report_check(report, ["a"], runs, OLD_STAMP)["ok"])


class SonSkipIsNotGreenTests(StopHookCase):
    def test_checks_still_run_for_the_head_after_a_son_skipped_the_same_tree(self) -> None:
        self.tsc(f"echo run >> '{self.runs_log}'\n")
        self.stop(DTS2_SON="1")
        self.stop()
        self.assertEqual(self.runs_log.read_text(encoding="utf-8").split(), ["run"])

    def test_the_branch_prefix_alone_also_skips(self) -> None:
        self.tsc(f"echo run >> '{self.runs_log}'\n")
        self.assertIn("skipped: son", self.stop(DTS2_SON_BRANCH_PREFIX="dts2/").stderr)
        self.assertFalse(self.runs_log.exists())


class HeadPublishSonPredicateTests(PublishCase):
    def test_the_branch_prefix_alone_marks_a_son(self) -> None:
        clean = {k: v for k, v in os.environ.items() if not k.startswith("DTS2_SON")}
        with mock.patch.dict(os.environ, {**clean, "DTS2_SON_BRANCH_PREFIX": "dts2/s/"}, clear=True):
            self.assertFalse(self.publish()["ok"])
            self.assertFalse(head_publish.merge_pr(self.repo, "5", True, "main", False, self.runner)["merged"])
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
