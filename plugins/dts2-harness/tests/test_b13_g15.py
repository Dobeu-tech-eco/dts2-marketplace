"""G-15: the per-run merge journal; fold and merge resume mid-way; a failed walkthrough files one revert action item."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lanes.journal import fold_done, journal_events, note, resume_state, walkthrough_failed  # noqa: E402
from lanes.merge import merge_go, merge_order  # noqa: E402
from lanes.mergeresume import merge_resume  # noqa: E402
from lanes.phases import transition  # noqa: E402
from lanes.runstate import fold  # noqa: E402

STAMP: Final[str] = "20261105-6"
BASE: Final[str] = "abc1234"


def manifest() -> dict[str, Any]:
    lanes = [{"id": x, "item": f"S{x}", "files": [f"src/{x}/f.py"], "ids": {}, "depends_on": [], "tier": "standard"} for x in "ab"]
    return {"stamp": STAMP, "base": BASE, "scope": "single", "lanes": lanes}


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="dts2-g15-"))
        self.runs = self.repo / ".harness" / "runs"

    def grant(self, lane: str) -> None:
        transition(self.runs, STAMP, lane, "pr-open")
        merge_order(manifest(), self.runs)
        result = merge_go(manifest(), self.runs, lane, "f" * 40, self.repo, BASE)
        self.assertTrue(result["ok"], result)

    def kinds(self) -> list[str]:
        return [e["kind"] for e in journal_events(self.runs, STAMP)]


class JournalTests(Base):
    def test_note_is_deduped_by_step(self) -> None:
        self.assertTrue(note(self.runs, STAMP, "x", lane="a", key=1))
        self.assertFalse(note(self.runs, STAMP, "x", lane="a", key=1))
        self.assertTrue(note(self.runs, STAMP, "x", lane="a", key=2))

    def test_a_bad_stamp_never_breaks_the_caller(self) -> None:
        self.assertFalse(note(self.runs, "None", "x"))

    def test_grant_and_done_are_journaled(self) -> None:
        from lanes.merge import merge_done
        self.grant("a")
        self.assertEqual(self.kinds(), ["merge-granted"])
        self.assertEqual(journal_events(self.runs, STAMP)[0]["head"], "f" * 40)
        merge_done(manifest(), self.runs, "a")
        merge_done(manifest(), self.runs, "a")
        self.assertEqual(self.kinds(), ["merge-granted", "merge-done"])
        self.assertEqual(resume_state(self.runs, STAMP)["merged"], ["a"])


class FoldResumeTests(Base):
    def blocked(self) -> None:
        for lane, f in (("a", "x.py"), ("b", "x.py"), ("c", "y.py")):
            transition(self.runs, STAMP, lane, "blocked", reason="r")
            path = self.runs / STAMP / lane / "status.json"
            path.write_text(json.dumps({**json.loads(path.read_text(encoding="utf-8")), "files": [f]}), encoding="utf-8")

    def test_fold_names_its_groups_and_remembers_which_shipped(self) -> None:
        self.blocked()
        first = fold(self.runs, STAMP)
        keys = [g["key"] for g in first["groups"]]
        self.assertEqual(keys, ["a+c", "b"])
        self.assertEqual(first["remaining"], keys)
        self.assertTrue(fold_done(self.runs, STAMP, "a+c", 11)["recorded"])
        self.assertFalse(fold_done(self.runs, STAMP, "a+c", 11)["recorded"])
        again = fold(self.runs, STAMP)
        self.assertEqual([(g["key"], g["done"]) for g in again["groups"]], [("a+c", True), ("b", False)])
        self.assertEqual(again["remaining"], ["b"])
        self.assertEqual(resume_state(self.runs, STAMP)["fold"], {"planned": keys, "done": ["a+c"], "remaining": ["b"]})
        self.assertEqual(self.kinds().count("fold-planned"), 1)


class MergeResumeTests(Base):
    def test_a_merge_that_landed_while_the_head_was_dead_is_recorded(self) -> None:
        self.grant("a")
        out = merge_resume(manifest(), self.runs, self.repo, ask=lambda _c, _b: ([{"number": 1, "state": "MERGED"}], None))
        self.assertEqual((out["action"], out["recovered"], out["merged"]), ("recovered", "a", ["a"]))
        self.assertIn("merge-recovered", self.kinds())
        again = merge_resume(manifest(), self.runs, self.repo, ask=lambda _c, _b: ([], None))
        self.assertIsNone(again["in_flight"])

    def test_a_merge_that_never_happened_is_released_for_a_fresh_grant(self) -> None:
        self.grant("a")
        out = merge_resume(manifest(), self.runs, self.repo, ask=lambda _c, _b: ([{"number": 1, "state": "OPEN"}], None))
        self.assertEqual(out["action"], "regrant")
        self.assertFalse((self.runs / STAMP / "a" / "merge-go.md").exists())
        self.assertTrue(merge_go(manifest(), self.runs, "a", "e" * 40, self.repo, BASE)["ok"])

    def test_no_pr_or_no_github_changes_nothing(self) -> None:
        self.grant("a")
        none = merge_resume(manifest(), self.runs, self.repo, ask=lambda _c, _b: ([], None))
        self.assertFalse(none["ok"])
        down = merge_resume(manifest(), self.runs, self.repo, ask=lambda _c, _b: (None, "gh exited 1"))
        self.assertFalse(down["ok"])
        self.assertTrue((self.runs / STAMP / "a" / "merge-go.md").exists())

    def test_nothing_in_flight(self) -> None:
        out = merge_resume(manifest(), self.runs, self.repo, ask=lambda _c, _b: self.fail("asked"))  # type: ignore[arg-type,return-value]
        self.assertEqual((out["ok"], out["in_flight"], out["action"]), (True, None, None))


class WalkthroughTests(Base):
    def test_failed_walkthrough_files_one_revert_item(self) -> None:
        (self.repo / ".harness").mkdir()
        first = walkthrough_failed(self.runs, STAMP, "a", "login 500s", self.repo)
        self.assertEqual((first["recorded"], first["revert_item_filed"]), (True, True))
        second = walkthrough_failed(self.runs, STAMP, "a", "login 500s", self.repo)
        self.assertEqual((second["recorded"], second["revert_item_filed"]), (False, False))
        items = (self.repo / ".harness" / "action-items.md").read_text(encoding="utf-8")
        self.assertEqual(items.count("Revert the merge of lane a"), 1)
        self.assertEqual(resume_state(self.runs, STAMP)["walkthrough_failed"], ["a"])


if __name__ == "__main__":
    unittest.main()
