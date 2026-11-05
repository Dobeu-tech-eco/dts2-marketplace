"""G-17: a typed run.json for run and autopilot, and builders.jsonl rows that `run resume` reads."""
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
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lanes.common import LaneError  # noqa: E402
from lanes.runrecord import (  # noqa: E402
    RunRecord, builder_rows, confirm_sha, init_run, latest_rows, read_run, record_builder, resume_view, update_run,
)

CLI: Final[Path] = SCRIPTS / "lanes.py"
STAMP: Final[str] = "20261105-4"
GIT_ENV: Final[dict[str, str]] = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                                  "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="dts2-g17-"))
        self.runs = self.repo / ".harness" / "runs"

    def git(self, *args: str) -> str:
        done = subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True, check=True,
                              env={**os.environ, **GIT_ENV})
        return done.stdout.strip()

    def make_repo(self) -> tuple[str, str]:
        """(base sha, branch tip sha) of a repo where branch `dts2/x/lane-a` is one commit ahead of main."""
        self.git("init", "-q", "-b", "main")
        (self.repo / "f.txt").write_text("one", encoding="utf-8")
        self.git("add", "f.txt")
        self.git("commit", "-q", "-m", "base")
        base = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "-b", "dts2/x/lane-a")
        (self.repo / "g.txt").write_text("two", encoding="utf-8")
        self.git("add", "g.txt")
        self.git("commit", "-q", "-m", "work")
        return base, self.git("rev-parse", "HEAD")

    def cli(self, *args: str) -> tuple[int, dict[str, Any]]:
        done = subprocess.run([sys.executable, "-I", str(CLI), "--cwd", str(self.repo), *args],
                              capture_output=True, text=True, check=False)
        return done.returncode, json.loads(done.stdout)


class RunRecordTests(Base):
    def test_a_missing_run_json_reads_as_the_defaults(self) -> None:
        record = read_run(self.runs, STAMP)
        self.assertEqual((record.kind, record.preflight_ok, record.claude_version, record.problems), ("run", False, None, ()))

    def test_init_opens_the_record_once_for_run_or_autopilot(self) -> None:
        first = init_run(self.runs, STAMP, "autopilot", now=100)
        again = init_run(self.runs, STAMP, "run", now=999)
        self.assertEqual((first.kind, first.started, again.kind, again.started), ("autopilot", 100, "autopilot", 100))

    def test_update_checks_named_fields_before_writing_anything(self) -> None:
        init_run(self.runs, STAMP, now=1)
        before = (self.runs / STAMP / "run.json").read_text(encoding="utf-8")
        for field, value in (("preflight_ok", "yes"), ("started", "soon"), ("claude_version", 2), ("kind", "batch"),
                             ("problems", "none"), ("default_branch_yes", 1), ("started", True)):
            with self.subTest(field=field, value=value), self.assertRaises(LaneError):
                update_run(self.runs, STAMP, {field: value})
        self.assertEqual((self.runs / STAMP / "run.json").read_text(encoding="utf-8"), before)

    def test_update_merges_and_keeps_fields_it_does_not_know(self) -> None:
        update_run(self.runs, STAMP, {"claude_version": "2.1.0", "preflight_ok": True, "gc_auto_prior": None, "note": "x"})
        record = update_run(self.runs, STAMP, {"merge_target": "dev"})
        self.assertEqual((record.claude_version, record.preflight_ok, record.merge_target, record.extra), ("2.1.0", True, "dev", {"note": "x"}))
        self.assertEqual(record.to_dict()["note"], "x")

    def test_a_hand_edited_bad_value_is_an_error_not_a_guess(self) -> None:
        (self.runs / STAMP).mkdir(parents=True)
        (self.runs / STAMP / "run.json").write_text(json.dumps({"preflight_ok": "true"}), encoding="utf-8")
        with self.assertRaises(LaneError):
            read_run(self.runs, STAMP)

    def test_preflight_and_merge_target_state_use_the_typed_record(self) -> None:
        code, out = self.cli("merge-target", STAMP, "--set", "dev")
        self.assertEqual((code, out["target"]), (0, "dev"))
        self.assertEqual(read_run(self.runs, STAMP), RunRecord(stamp=STAMP, merge_target="dev"))
        code, out = self.cli("run-record", STAMP, "--init", "--kind", "autopilot")
        self.assertEqual((code, out["run"]["kind"], out["run"]["merge_target"]), (0, "autopilot", "dev"))


class BuilderRowTests(Base):
    def test_row_has_the_event_shape_and_the_builder_fields(self) -> None:
        record_builder(self.runs, STAMP, "a", section="auth", branch="dts2/x/lane-a", status="pr-open", round_no=1)
        row = builder_rows(self.runs, STAMP)[0]
        self.assertEqual((row["v"], row["run"], row["lane"], row["kind"]), (1, STAMP, "a", "builder"))
        self.assertEqual((row["section"], row["branch"], row["status"], row["round"], row["sha"], row["confirmed"]),
                         ("auth", "dts2/x/lane-a", "pr-open", 1, None, False))
        self.assertTrue(row["id"] and "ts" in row)

    def test_the_same_row_twice_is_one_row(self) -> None:
        for _ in range(2):
            result = record_builder(self.runs, STAMP, "a", section="s", branch="b", status="starting", round_no=0)
        self.assertFalse(result["recorded"])
        self.assertEqual(len(builder_rows(self.runs, STAMP)), 1)

    def test_bad_status_or_round_is_refused(self) -> None:
        with self.assertRaises(LaneError):
            record_builder(self.runs, STAMP, "a", section="s", branch="b", status="running", round_no=0)
        with self.assertRaises(LaneError):
            record_builder(self.runs, STAMP, "a", section="s", branch="b", status="done", round_no=-1)

    def test_sha_is_confirmed_only_against_the_branch_tip_and_diff(self) -> None:
        base, tip = self.make_repo()
        self.assertEqual(confirm_sha(self.repo, "dts2/x/lane-a", tip, base), (True, ""))
        self.assertEqual(confirm_sha(self.repo, "dts2/x/lane-a", base)[0], False)
        self.assertIn("not the tip", confirm_sha(self.repo, "dts2/x/lane-a", base)[1])
        self.assertIn("not a commit", confirm_sha(self.repo, "dts2/x/lane-a", "deadbeef")[1])
        self.assertIn("not found", confirm_sha(self.repo, "no-such-branch", tip)[1])
        self.assertIn("empty", confirm_sha(self.repo, "dts2/x/lane-a", tip, tip)[1])
        done = record_builder(self.runs, STAMP, "a", section="s", branch="dts2/x/lane-a", status="done", round_no=1,
                              sha=tip, cwd=self.repo, base=base)
        self.assertTrue(done["confirmed"])
        wrong = record_builder(self.runs, STAMP, "b", section="s", branch="dts2/x/lane-a", status="done", round_no=1,
                               sha=base, cwd=self.repo)
        self.assertFalse(wrong["confirmed"])
        self.assertIn("tip", wrong["unconfirmed_because"])


class ResumeTests(Base):
    def test_resume_reads_the_newest_row_of_each_step(self) -> None:
        base, tip = self.make_repo()
        record_builder(self.runs, STAMP, "a", section="auth", branch="dts2/x/lane-a", status="starting", round_no=0)
        record_builder(self.runs, STAMP, "a", section="auth", branch="dts2/x/lane-a", status="pr-open", round_no=1,
                       sha=tip, cwd=self.repo, base=base)
        record_builder(self.runs, STAMP, "b", section="api", branch="dts2/x/lane-b", status="done", round_no=2)
        record_builder(self.runs, STAMP, "c", section="ui", branch="dts2/x/lane-c", status="incomplete", round_no=1,
                       sha="abc1234", cwd=self.repo)
        init_run(self.runs, STAMP, "autopilot", now=5)
        view = resume_view(self.runs, STAMP)
        self.assertEqual(view["run"]["kind"], "autopilot")
        self.assertEqual(view["finished"], ["b/api"])
        todo = {row["lane"]: row for row in view["todo"]}
        self.assertEqual(set(todo), {"a", "c"})
        self.assertEqual((todo["a"]["status"], todo["a"]["round"], todo["a"]["from_sha"]), ("pr-open", 1, tip))
        self.assertIsNone(todo["c"]["from_sha"], "an unconfirmed sha is never offered to resume from")

    def test_latest_rows_keeps_first_seen_order(self) -> None:
        rows = [{"lane": "a", "section": "s", "n": 1}, {"lane": "b", "section": "s", "n": 2}, {"lane": "a", "section": "s", "n": 3}]
        self.assertEqual([r["n"] for r in latest_rows(rows)], [3, 2])

    def test_commands(self) -> None:
        code, out = self.cli("builder", STAMP, "--lane", "a", "--section", "auth", "--branch", "dts2/x/lane-a",
                             "--status", "blocked", "--round", "2")
        self.assertEqual((code, out["ok"], out["recorded"]), (0, True, True))
        code, view = self.cli("run-resume", STAMP)
        self.assertEqual((code, [r["lane"] for r in view["todo"]]), (0, ["a"]))
        bad = subprocess.run([sys.executable, "-I", str(CLI), "--cwd", str(self.repo), "builder", STAMP, "--lane", "a",
                              "--section", "s", "--branch", "b", "--status", "bogus"], capture_output=True, text=True, check=False)
        self.assertNotEqual(bad.returncode, 0)  # argparse rejects a status outside the choices


if __name__ == "__main__":
    unittest.main()
