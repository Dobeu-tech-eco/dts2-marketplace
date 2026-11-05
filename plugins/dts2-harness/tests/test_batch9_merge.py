"""Batch 9 (round 2): G-78 (post-merge fix cap, revert PR, base-health gate, repo-wide merge mutex), G-79 (fold --apply records
supersession; fold-close closes the originals through the journal) and G-80 (integration routing keeps its refusal, reason,
alternative and override in a record that status and report print). gh and git are fakes (DTS2_GH_BIN, DTS2_GIT_BIN)."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Final
from unittest import mock

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lanes import journal, mergecomp  # noqa: E402
from lanes.merge import merge_go, merge_order  # noqa: E402
from lanes.phases import transition  # noqa: E402
from lanes.runstate import fold  # noqa: E402

STAMP: Final[str] = "20261105-9"
TIP: Final[str] = "a" * 40
FAKE_GH: Final[str] = '''#!/usr/bin/env python3
import json, os, sys
argv = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(["gh", *argv]) + "\\n")
if argv[:2] == ["pr", "view"]:
    print("c" * 40 if "mergeCommit" in argv else os.environ.get("FAKE_STATE", "OPEN"))
elif argv[:2] == ["pr", "list"]:
    print(os.environ.get("FAKE_LIST", "[]"))
elif argv[:2] == ["pr", "create"]:
    print("https://github.com/o/r/pull/99")
elif argv[:2] == ["pr", "close"]:
    sys.exit(int(os.environ.get("FAKE_CLOSE_RC", "0")))
elif argv[0] == "api":
    print(os.environ.get("FAKE_CHECKS", '{"check_runs": []}'))
'''
FAKE_GIT: Final[str] = '''#!/usr/bin/env python3
import json, os, sys
argv = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(["git", *argv]) + "\\n")
if argv and argv[0] == os.environ.get("FAKE_GIT_FAIL"):
    print("boom")
    sys.exit(1)
if argv[:2] == ["worktree", "add"]:
    os.makedirs(argv[-2], exist_ok=True)
if argv[:1] == ["rev-parse"]:
    print("a" * 40)
elif argv[:2] == ["rev-list", "--parents"]:
    print("c" * 40, "p" * 40, *([] if os.environ.get("FAKE_SQUASH") else ["q" * 40]))
'''


def manifest(files: tuple[str, str] = ("src/a/f.py", "src/b/f.py")) -> dict[str, Any]:
    lanes = [{"id": x, "item": f"S{x}", "files": [f], "ids": {}, "depends_on": [], "tier": "standard"} for x, f in zip("ab", files)]
    return {"stamp": STAMP, "base": "abc1234", "scope": "single", "lanes": lanes}


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="dts2-b9m-"))
        self.addCleanup(shutil.rmtree, self.repo, True)
        self.runs = self.repo / ".harness" / "runs"
        self.log = self.repo / "calls.jsonl"
        self.log.write_text("", encoding="utf-8")
        for name, text in (("gh.py", FAKE_GH), ("git.py", FAKE_GIT)):
            (self.repo / name).write_text(text, encoding="utf-8")
        env = {"DTS2_GH_BIN": str(self.repo / "gh.py"), "DTS2_GIT_BIN": str(self.repo / "git.py"), "FAKE_LOG": str(self.log)}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        audit = mock.patch.object(sys.modules["lanes.merge"], "lane_audit", return_value={"ok": True, "violations": [], "changed": []})
        audit.start()
        self.addCleanup(audit.stop)

    def calls(self, tool: str, *prefix: str) -> list[list[str]]:
        rows = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
        return [r for r in rows if r[0] == tool and r[1:1 + len(prefix)] == list(prefix)]

    def lane_pr(self, lane: str, pr: int, status: str = "pr-open", files: list[str] | None = None) -> None:
        transition(self.runs, STAMP, lane, status, reason="r" if status == "blocked" else None)
        path = self.runs / STAMP / lane / "status.json"
        data = {**json.loads(path.read_text(encoding="utf-8")), "pr": pr, **({"files": files} if files else {})}
        path.write_text(json.dumps(data), encoding="utf-8")

    def setting(self, line: str) -> None:
        (self.repo / ".claude").mkdir(exist_ok=True)
        (self.repo / ".claude" / "dts2-harness.local.md").write_text(f"---\n{line}\n---\n", encoding="utf-8")


class FixCapTests(Base):
    def test_two_fixes_then_one_revert_pr(self) -> None:
        self.lane_pr("a", 7)
        first = journal.fix_attempt(self.runs, STAMP, "a", "smoke failed", self.repo)
        second = journal.fix_attempt(self.runs, STAMP, "a", "smoke failed again", self.repo)
        self.assertEqual([first["action"], first["attempt"], second["attempt"], first["cap"]], ["fix", 1, 2, 2])
        third = journal.fix_attempt(self.runs, STAMP, "a", "still red", self.repo)
        self.assertEqual((third["action"], third["ok"], third["revert_pr"]), ("revert", True, 99), third)
        self.assertEqual(len(self.calls("git", "revert")), 1)
        self.assertIn("-m", self.calls("git", "revert")[0], "a merge commit reverts against its first parent")
        self.assertEqual(len(self.calls("git", "push")), 1)

    def test_a_squash_commit_reverts_without_a_mainline(self) -> None:
        self.lane_pr("a", 7)
        self.setting("post_merge_fix_attempts: 1")
        journal.fix_attempt(self.runs, STAMP, "a", "red", self.repo)
        with mock.patch.dict(os.environ, {"FAKE_SQUASH": "1"}):
            journal.fix_attempt(self.runs, STAMP, "a", "red", self.repo)
        self.assertNotIn("-m", self.calls("git", "revert")[0])

    def test_the_revert_pr_opens_once_however_often_it_is_asked(self) -> None:
        self.lane_pr("a", 7)
        for _ in range(5):
            result = journal.fix_attempt(self.runs, STAMP, "a", "red", self.repo)
        self.assertEqual(len(self.calls("gh", "pr", "create")), 1)
        self.assertTrue(result["already"])

    def test_the_cap_is_a_setting(self) -> None:
        self.lane_pr("a", 7)
        self.setting("post_merge_fix_attempts: 1")
        self.assertEqual(journal.fix_attempt(self.runs, STAMP, "a", "red", self.repo)["action"], "fix")
        self.assertEqual(journal.fix_attempt(self.runs, STAMP, "a", "red", self.repo)["action"], "revert")

    def test_a_failed_push_parks_with_the_revert_action_item(self) -> None:
        self.lane_pr("a", 7)
        self.setting("post_merge_fix_attempts: 1")
        journal.fix_attempt(self.runs, STAMP, "a", "red", self.repo)
        with mock.patch.dict(os.environ, {"FAKE_GIT_FAIL": "push"}), mock.patch.object(journal, "file_revert_item", return_value=True) as filed:
            result = journal.fix_attempt(self.runs, STAMP, "a", "red", self.repo)
        self.assertEqual((result["ok"], result["parked"], result["revert_item_filed"]), (False, True, True))
        filed.assert_called_once()
        self.assertEqual(self.calls("gh", "pr", "create"), [])

    def test_an_open_revert_pr_is_adopted_not_duplicated(self) -> None:
        self.lane_pr("a", 7)
        self.setting("post_merge_fix_attempts: 1")
        journal.fix_attempt(self.runs, STAMP, "a", "red", self.repo)
        with mock.patch.dict(os.environ, {"FAKE_LIST": json.dumps([{"number": 55, "url": "https://x/pull/55"}])}):
            result = journal.fix_attempt(self.runs, STAMP, "a", "red", self.repo)
        self.assertEqual(result["revert_pr"], 55)
        self.assertEqual(self.calls("gh", "pr", "create"), [])


class BaseHealthTests(Base):
    def grant(self, lane: str = "a") -> dict[str, Any]:
        transition(self.runs, STAMP, lane, "pr-open")
        merge_order(manifest(), self.runs)
        return merge_go(manifest(), self.runs, lane, "f" * 40, self.repo, TIP)

    def test_a_red_base_stops_the_grant_and_a_green_one_allows_it(self) -> None:
        red = json.dumps({"check_runs": [{"name": "ci", "status": "completed", "conclusion": "failure"}]})
        with mock.patch.dict(os.environ, {"FAKE_CHECKS": red}):
            health = mergecomp.base_health(self.runs, STAMP, self.repo)
        self.assertFalse(health["ok"])
        self.assertEqual(health["failing"], ["ci"])
        refused = self.grant()
        self.assertFalse(refused["ok"])
        self.assertIn("not green", refused["detail"])
        green = json.dumps({"check_runs": [{"name": "ci", "status": "completed", "conclusion": "success"}]})
        with mock.patch.dict(os.environ, {"FAKE_CHECKS": green}):
            self.assertTrue(mergecomp.base_health(self.runs, STAMP, self.repo)["ok"])
        self.assertTrue(self.grant()["ok"])

    def test_pending_checks_and_an_unreadable_answer_are_not_green(self) -> None:
        pending = json.dumps({"check_runs": [{"name": "ci", "status": "in_progress", "conclusion": None}]})
        with mock.patch.dict(os.environ, {"FAKE_CHECKS": pending}):
            self.assertFalse(mergecomp.base_health(self.runs, STAMP, self.repo)["ok"])
        with mock.patch.dict(os.environ, {"FAKE_CHECKS": "not json"}):
            self.assertFalse(mergecomp.base_health(self.runs, STAMP, self.repo)["ok"])

    def test_a_base_that_moved_since_the_check_needs_a_new_check(self) -> None:
        mergecomp.base_health(self.runs, STAMP, self.repo)
        transition(self.runs, STAMP, "a", "pr-open")
        merge_order(manifest(), self.runs)
        moved = merge_go(manifest(), self.runs, "a", "f" * 40, self.repo, "b" * 40)
        self.assertIn("moved", moved["detail"])

    def test_without_a_record_the_grant_is_unchanged(self) -> None:
        self.assertTrue(self.grant()["ok"])


class MutexTests(Base):
    def test_one_lane_holds_the_mutex_until_it_releases(self) -> None:
        self.assertTrue(mergecomp.merge_mutex(self.runs, STAMP, "a", "acquire", self.repo)["ok"])
        self.assertTrue(mergecomp.merge_mutex(self.runs, STAMP, "a", "acquire", self.repo)["ok"], "the holder may ask again")
        blocked = mergecomp.merge_mutex(self.runs, STAMP, "b", "acquire", self.repo)
        self.assertFalse(blocked["ok"])
        self.assertFalse(mergecomp.merge_mutex(self.runs, STAMP, "b", "release", self.repo)["ok"])
        transition(self.runs, STAMP, "b", "pr-open")
        merge_order(manifest(), self.runs)
        self.assertIn("mutex", merge_go(manifest(), self.runs, "b", "f" * 40, self.repo, TIP)["detail"])
        self.assertTrue(mergecomp.merge_mutex(self.runs, STAMP, "a", "release", self.repo)["ok"])
        self.assertTrue(mergecomp.merge_mutex(self.runs, STAMP, "b", "acquire", self.repo)["ok"])

    def test_every_take_and_release_is_in_the_journal(self) -> None:
        mergecomp.merge_mutex(self.runs, STAMP, "a", "acquire", self.repo)
        mergecomp.merge_mutex(self.runs, STAMP, "a", "release", self.repo)
        kinds = [e["kind"] for e in journal.journal_events(self.runs, STAMP)]
        self.assertEqual(kinds, [mergecomp.KIND_MUTEX_TAKEN, mergecomp.KIND_MUTEX_RELEASED])

    def test_a_dead_holder_loses_the_mutex_after_the_ttl(self) -> None:
        path = mergecomp.harness_path(self.repo, mergecomp.MUTEX_NAME)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"stamp": "20250101-1", "lane": "z", "at": int(time.time()) - mergecomp.MUTEX_TTL_S - 5}), encoding="utf-8")
        self.assertTrue(mergecomp.merge_mutex(self.runs, STAMP, "a", "acquire", self.repo)["ok"])


class FoldSupersedeTests(Base):
    def blocked(self) -> None:
        self.lane_pr("a", 11, "blocked", ["x.py"])
        self.lane_pr("b", 12, "blocked", ["y.py"])

    def test_apply_records_the_new_pr_on_each_original(self) -> None:
        self.blocked()
        key = fold(self.runs, STAMP)["groups"][0]["key"]
        result = fold(self.runs, STAMP, key, 40)
        self.assertEqual(sorted((r["original_pr"], r["new_pr"], r["superseded_by"]) for r in result["superseded"]),
                         sorted((pr, 40, key) for pr in (11, 12)))
        self.assertEqual(len(journal.journal_events(self.runs, STAMP, journal.KIND_SUPERSEDED)), 2)

    def test_apply_needs_a_known_group_and_the_new_pr(self) -> None:
        self.blocked()
        self.assertFalse(fold(self.runs, STAMP, "nope", 40)["ok"])
        self.assertFalse(fold(self.runs, STAMP, fold(self.runs, STAMP)["groups"][0]["key"], None)["ok"])

    def test_apply_is_refused_in_a_son(self) -> None:
        self.blocked()
        with mock.patch.dict(os.environ, {"DTS2_SON": "1"}):
            self.assertFalse(fold(self.runs, STAMP, "a", 40)["ok"])

    def test_close_comments_and_closes_each_original_once(self) -> None:
        self.blocked()
        fold(self.runs, STAMP, fold(self.runs, STAMP)["groups"][0]["key"], 40)
        first = journal.close_superseded(self.runs, STAMP, self.repo)
        self.assertTrue(first["ok"])
        closes = self.calls("gh", "pr", "close")
        self.assertEqual(sorted(c[3] for c in closes), ["11", "12"])
        self.assertTrue(all("#40" in c[-1] for c in closes), "the comment links the new PR")
        journal.close_superseded(self.runs, STAMP, self.repo)
        self.assertEqual(len(self.calls("gh", "pr", "close")), 2, "a second pass does nothing")

    def test_an_already_closed_original_is_noted_not_closed_again(self) -> None:
        self.blocked()
        fold(self.runs, STAMP, fold(self.runs, STAMP)["groups"][0]["key"], 40)
        with mock.patch.dict(os.environ, {"FAKE_STATE": "MERGED"}):
            self.assertTrue(journal.close_superseded(self.runs, STAMP, self.repo)["ok"])
        self.assertEqual(self.calls("gh", "pr", "close"), [])

    def test_a_failed_close_is_retried_next_time(self) -> None:
        self.blocked()
        fold(self.runs, STAMP, fold(self.runs, STAMP)["groups"][0]["key"], 40)
        with mock.patch.dict(os.environ, {"FAKE_CLOSE_RC": "1"}):
            self.assertFalse(journal.close_superseded(self.runs, STAMP, self.repo)["ok"])
        self.assertTrue(journal.close_superseded(self.runs, STAMP, self.repo)["ok"])


class RoutingRecordTests(Base):
    def test_a_routed_file_keeps_its_refusal_reason_alternative_and_override(self) -> None:
        m = manifest(("package-lock.json", "src/b/f.py"))
        rows = mergecomp.record_routing(self.runs, STAMP, m, ())
        self.assertEqual([r["lane"] for r in rows], ["a"])
        row = rows[0]
        for key in ("refusal", "reason", "alternative", "override"):
            self.assertTrue(row[key], key)
        self.assertIn("lanes.py override a", row["override"])
        self.assertEqual(mergecomp.read_routing(self.runs, STAMP), rows)

    def test_report_markdown_prints_the_record(self) -> None:
        rows = mergecomp.record_routing(self.runs, STAMP, manifest(("package-lock.json", "src/b/f.py")), ())
        text = mergecomp.routing_markdown(rows)
        for word in ("may not own package-lock.json", "Reason:", "Instead:", "Override:"):
            self.assertIn(word, text)
        self.assertEqual(mergecomp.routing_markdown([]), "")

    def test_status_and_report_commands_carry_the_record(self) -> None:
        import subprocess
        mergecomp.record_routing(self.runs, STAMP, manifest(("package-lock.json", "src/b/f.py")), ())
        transition(self.runs, STAMP, "a", "pr-open")
        base = [sys.executable, str(SCRIPTS / "lanes.py"), "--cwd", str(self.repo)]
        status = json.loads(subprocess.run([*base, "status", STAMP], capture_output=True, text=True, check=False).stdout)
        self.assertEqual(status["routing"][0]["lane"], "a")
        report = json.loads(subprocess.run([*base, "report", STAMP], capture_output=True, text=True, check=False).stdout)
        self.assertIn("Override:", report["markdown"])


if __name__ == "__main__":
    unittest.main()
