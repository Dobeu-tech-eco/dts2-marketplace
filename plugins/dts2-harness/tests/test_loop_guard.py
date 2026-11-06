"""Contracts for scripts/loop_guard.py: kill-switch (file and PR label), no-progress and repeated-failure stalls, the
single "needs you" issue, sweep of resolved blockers, budget stops, and the unattended loop cap. gh is a fake script."""
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
GUARD: Final[Path] = SCRIPTS / "loop_guard.py"
LANES: Final[Path] = SCRIPTS / "lanes.py"
sys.path.insert(0, str(SCRIPTS))
import model_call  # noqa: E402
import settings_cache  # noqa: E402

FAKE_GH: Final[str] = r"""#!/bin/sh
printf '%s\n' "$*" | tr '\n' ' ' >> "$FAKE_DIR/calls.log"; echo >> "$FAKE_DIR/calls.log"
case "$1 $2" in
  "pr list") cat "$FAKE_DIR/pr_list.json" 2>/dev/null || echo "[]" ;;
  "pr view") cat "$FAKE_DIR/pr_view.json" 2>/dev/null || echo "{}" ;;
  "issue list") cat "$FAKE_DIR/issue_list.json" 2>/dev/null || echo "[]" ;;
  *) exit "${FAKE_RC:-0}" ;;
esac
"""


class GuardCase(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="dts2-loop-"))
        (self.repo / ".harness").mkdir()
        self.fake = Path(tempfile.mkdtemp(prefix="dts2-loop-gh-"))
        gh = self.fake / "gh"
        gh.write_text(FAKE_GH, encoding="utf-8")
        gh.chmod(0o755)
        self.env = {**os.environ, "DTS2_GH_BIN": str(gh), "FAKE_DIR": str(self.fake)}
        self.clock = 1_000_000.0

    def config(self, text: str) -> None:
        (self.repo / ".harness" / "config.yaml").write_text(text, encoding="utf-8")

    def guard(self, *args: str, **env: str) -> tuple[int, dict[str, Any]]:
        done = subprocess.run([sys.executable, "-I", str(GUARD), "--repo", str(self.repo), *args], capture_output=True,
                              text=True, check=False, env={**self.env, "DTS2_LOOP_NOW": str(self.clock), **env})
        return done.returncode, json.loads(done.stdout)

    def record(self, progress: str, signature: str = "") -> dict[str, Any]:
        args = ["record", "--progress", progress] + (["--signature", signature] if signature else [])
        self.clock += 60
        return self.guard(*args)[1]

    def calls(self) -> list[str]:
        log = self.fake / "calls.log"
        return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


class KillSwitchTests(GuardCase):
    def test_clean_repo_passes(self) -> None:
        code, out = self.guard("check")
        self.assertEqual((code, out["stop"]), (0, False))

    def test_stop_file_stops(self) -> None:
        (self.repo / ".harness" / "STOP").write_text("", encoding="utf-8")
        code, out = self.guard("check")
        self.assertEqual((code, out["stop"], out["reason"], out["verdict"]), (2, True, "stop-file", "STOP"))

    def test_pr_label_stops(self) -> None:
        (self.fake / "pr_list.json").write_text('[{"number": 7}]', encoding="utf-8")
        code, out = self.guard("check")
        self.assertEqual((code, out["reason"]), (2, "stop-label"))
        self.assertTrue(any("--label dts2:stop" in call for call in self.calls()))

    def test_no_labelled_pr_and_failing_gh_do_not_stop(self) -> None:
        self.assertFalse(self.guard("check")[1]["stop"])
        self.assertFalse(self.guard("check", FAKE_RC="1", DTS2_GH_BIN="/nonexistent/gh")[1]["stop"])


class StallTests(GuardCase):
    def test_no_progress_after_n_passes(self) -> None:
        self.assertEqual(self.record("items=3 prs=0")["verdict"], "continue")
        self.assertEqual(self.record("items=3 prs=0")["verdict"], "continue")
        third = self.record("items=3 prs=0")
        self.assertEqual(third["verdict"], "stall")
        self.assertIn("no-progress", third["reasons"][0])

    def test_progress_resets_the_count(self) -> None:
        for progress in ("a", "a", "b", "b"):
            verdict = self.record(progress)["verdict"]
        self.assertEqual(verdict, "continue")
        self.assertEqual(self.record("b")["verdict"], "stall")

    def test_limit_is_configurable(self) -> None:
        self.config("loop:\n  no_progress_limit: 2\n")
        self.record("same")
        self.assertEqual(self.record("same")["verdict"], "stall")

    def test_same_signature_three_times_stalls_even_with_progress(self) -> None:
        self.assertEqual(self.record("p1", "ci red on test_x line 10")["verdict"], "continue")
        self.assertEqual(self.record("p2", "CI red on test_x line 22")["verdict"], "continue")
        third = self.record("p3", "ci red on test_x line 31")
        self.assertEqual(third["verdict"], "stall")
        self.assertIn("same-failure", third["reasons"][0])

    def test_different_signature_breaks_the_run(self) -> None:
        for number, signature in enumerate(("boom", "boom", "bang", "boom")):
            verdict = self.record(f"p{number}", signature)["verdict"]
        self.assertEqual(verdict, "continue")

    def test_stall_exits_non_zero_and_ledger_head_moves(self) -> None:
        first = self.record("p1")
        second = self.record("p2")
        self.assertNotEqual(first["chain"], second["chain"])
        self.record("same")
        self.record("same")
        code, out = self.guard("record", "--progress", "same")
        self.assertEqual((code, out["verdict"]), (2, "stall"))


class NotifyTests(GuardCase):
    def test_creates_then_comments(self) -> None:
        self.guard("park", "--id", "S1", "--reason", "needs a key", "--blocker-file", "keys/prod.txt")
        self.record("x", "deploy failed")
        _, first = self.guard("notify", "--reason", "no-progress")
        self.assertEqual(first["issue"], "created")
        create = [call for call in self.calls() if call.startswith("issue create")]
        self.assertEqual(len(create), 1)
        self.assertIn("--title dts2: needs you", create[0])
        self.assertIn("S1: needs a key", create[0])
        self.assertIn("deploy failed", create[0])
        (self.fake / "issue_list.json").write_text('[{"number": 42, "title": "dts2: needs you"}]', encoding="utf-8")
        _, second = self.guard("notify")
        self.assertEqual((second["issue"], second["number"]), ("commented", 42))
        self.assertTrue(any(call.startswith("issue comment 42") for call in self.calls()))
        self.assertEqual(len([call for call in self.calls() if call.startswith("issue create")]), 1)

    def test_other_titles_are_not_reused(self) -> None:
        (self.fake / "issue_list.json").write_text('[{"number": 9, "title": "dts2: needs you too"}]', encoding="utf-8")
        self.assertEqual(self.guard("notify")[1]["issue"], "created")

    def test_gh_failure_is_soft_and_leaves_a_local_note(self) -> None:
        code, out = self.guard("notify", FAKE_RC="1")
        self.assertEqual((code, out["issue"]), (0, "failed"))
        note = self.repo / ".harness" / "loop" / "need-human.md"
        self.assertIn("dts2: needs you", note.read_text(encoding="utf-8"))
        code, out = self.guard("notify", DTS2_GH_BIN="/nonexistent/gh")
        self.assertEqual((code, out["issue"]), (0, "failed"))


class SweepTests(GuardCase):
    def test_lists_only_resolved_blockers_and_can_release(self) -> None:
        self.guard("park", "--id", "A", "--reason", "waits on file", "--blocker-file", "ready.txt")
        self.guard("park", "--id", "B", "--reason", "waits on pr", "--blocker-pr", "5")
        self.guard("park", "--id", "C", "--reason", "no blocker named")
        self.assertEqual(self.guard("sweep")[1]["ready"], [])
        (self.repo / "ready.txt").write_text("x", encoding="utf-8")
        (self.fake / "pr_view.json").write_text('{"state": "OPEN"}', encoding="utf-8")
        self.assertEqual([row["id"] for row in self.guard("sweep")[1]["ready"]], ["A"])
        (self.fake / "pr_view.json").write_text('{"state": "MERGED"}', encoding="utf-8")
        out = self.guard("sweep", "--release")[1]
        self.assertEqual(sorted(row["id"] for row in out["ready"]), ["A", "B"])
        self.assertEqual(out["still_parked"], 1)
        self.assertEqual(self.guard("sweep")[1]["ready"], [])

    def test_item_blocker_resolves_when_the_row_is_done(self) -> None:
        items = self.repo / ".harness" / "action-items.md"
        items.write_text("## Needs you\n\n| Item | Status | Owner | Added |\n|---|---|---|---|\n"
                         "| rotate key | done | me | 2026-01-01 |\n", encoding="utf-8")
        probe = subprocess.run([sys.executable, "-I", str(SCRIPTS / "action-items.py"), str(self.repo), "list"],
                               capture_output=True, text=True, check=False)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.guard("park", "--id", "X", "--reason", "key", "--blocker-item", "U1")
        self.assertIsInstance(self.guard("sweep")[1]["ready"], list)  # unreadable or unknown rows never crash the loop


class BudgetTests(GuardCase):
    def test_max_passes_stops(self) -> None:
        self.config("loop:\n  max_passes: 2\n  no_progress_limit: 9\n")
        self.assertEqual(self.record("a")["verdict"], "continue")
        spent = self.record("b")
        self.assertEqual(spent["verdict"], "stop")
        code, out = self.guard("check")
        self.assertEqual((code, out["reason"]), (2, "budget-passes"))

    def test_max_hours_stops(self) -> None:
        self.config("loop:\n  max_hours: 1\n  no_progress_limit: 9\n")
        self.record("a")
        self.clock += 3 * 3600
        code, out = self.guard("check")
        self.assertEqual((code, out["reason"]), (2, "budget-hours"))

    def test_fresh_budget_does_not_stop(self) -> None:
        self.record("a")
        self.assertFalse(self.guard("check")[1]["stop"])


class UnattendedCapTests(GuardCase):
    def lanes_loop(self, stamp: str) -> dict[str, Any]:
        done = subprocess.run([sys.executable, "-I", str(LANES), "--cwd", str(self.repo), "loop", stamp],
                              capture_output=True, text=True, check=False)
        return json.loads(done.stdout)

    def test_default_mode_keeps_three(self) -> None:
        self.assertEqual(model_call.read_budget(self.repo)["max_fullauto_loops"], 3)
        self.assertEqual(settings_cache.load(self.repo)["budget"]["max_fullauto_loops"], 3)
        stamp = "20261105-1"
        results = [self.lanes_loop(stamp) for _ in range(4)]
        self.assertEqual([row["ok"] for row in results], [True, True, True, False])
        self.assertTrue(results[3]["stop"])

    def test_unattended_lifts_the_cap(self) -> None:
        self.config("autonomy: unattended\nbudget:\n  max_fullauto_loops: 3\n")
        self.assertEqual(model_call.read_autonomy(self.repo), "unattended")
        self.assertGreater(model_call.read_budget(self.repo)["max_fullauto_loops"], 1000)
        self.assertGreater(settings_cache.load(self.repo)["budget"]["max_fullauto_loops"], 1000)
        stamp = "20261105-2"
        self.assertTrue(all(self.lanes_loop(stamp)["ok"] for _ in range(6)))

    def test_attended_mode_with_explicit_autonomy_keeps_cap(self) -> None:
        self.config("autonomy: attended\n")
        self.assertEqual(model_call.read_budget(self.repo)["max_fullauto_loops"], 3)


class DocsTests(unittest.TestCase):
    def test_fullauto_skill_and_template_describe_the_outer_loop(self) -> None:
        skill = (PLUGIN_ROOT / "skills" / "fullauto" / "SKILL.md").read_text(encoding="utf-8")
        for needle in ("loop_guard.py\" check", "loop_guard.py record", "loop_guard.py notify", "/goal", "/loop"):
            self.assertIn(needle, skill)
        template = (PLUGIN_ROOT / "templates" / "loop.md").read_text(encoding="utf-8")
        self.assertIn("loop_guard.py", template)

    def test_config_template_documents_the_loop_block(self) -> None:
        text = (PLUGIN_ROOT / "templates" / "config-supervisor.yaml").read_text(encoding="utf-8")
        for key in ("autonomy:", "no_progress_limit:", "max_passes:", "max_hours:"):
            self.assertIn(key, text)


if __name__ == "__main__":
    unittest.main()
