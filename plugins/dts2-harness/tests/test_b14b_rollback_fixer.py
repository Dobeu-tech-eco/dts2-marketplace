"""AA-10 (base ref and Rollback line) and AA-4 (escalation seat, fixer agent, round-2 hypothesis step)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, read_run_skill

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import delegate  # noqa: E402
import rollback_ref  # noqa: E402
from profiles import Profiles  # noqa: E402

STAMP: Final[str] = "20261105-101500"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def make_repo() -> Path:
    repo = Path(tempfile.mkdtemp(prefix="dts2-rb-"))
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("one\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    return repo


class RollbackRefTests(unittest.TestCase):
    def test_create_pins_the_ref_at_head_and_is_idempotent(self) -> None:
        repo = make_repo()
        base = git(repo, "rev-parse", "HEAD")
        first = rollback_ref.create_ref(str(repo), STAMP)
        self.assertEqual((first["ok"], first["sha"], first["ref"]), (True, base, f"refs/dts2/{STAMP}/base"))
        self.assertEqual(git(repo, "rev-parse", f"refs/dts2/{STAMP}/base"), base)
        (repo / "f.txt").write_text("two\n", encoding="utf-8")
        git(repo, "commit", "-qam", "work")
        again = rollback_ref.create_ref(str(repo), STAMP, base)
        self.assertTrue(again["ok"])

    def test_an_existing_ref_at_another_commit_is_never_moved(self) -> None:
        repo = make_repo()
        base = git(repo, "rev-parse", "HEAD")
        rollback_ref.create_ref(str(repo), STAMP)
        (repo / "f.txt").write_text("two\n", encoding="utf-8")
        git(repo, "commit", "-qam", "work")
        moved = rollback_ref.create_ref(str(repo), STAMP)
        self.assertFalse(moved["ok"])
        self.assertEqual(git(repo, "rev-parse", f"refs/dts2/{STAMP}/base"), base)

    def test_bad_stamp_and_bad_sha_are_refused(self) -> None:
        repo = make_repo()
        with self.assertRaises(ValueError):
            rollback_ref.ref_name("../escape")
        self.assertFalse(rollback_ref.create_ref(str(repo), STAMP, "nonexistent")["ok"])

    def test_the_line_restores_the_base_tree_when_a_human_runs_it(self) -> None:
        repo = make_repo()
        rollback_ref.create_ref(str(repo), STAMP)
        (repo / "f.txt").write_text("two\n", encoding="utf-8")
        (repo / "new.txt").write_text("added\n", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "work")
        sha = git(repo, "rev-parse", f"refs/dts2/{STAMP}/base")
        line = rollback_ref.rollback_line(STAMP, sha)
        self.assertTrue(line.startswith("Rollback (human-run, never run by the harness): git restore --source="))
        command = line.split(": ", 1)[1].split(" (base ")[0]
        subprocess.run(command, shell=True, cwd=repo, check=True, capture_output=True)
        self.assertEqual((repo / "f.txt").read_text(encoding="utf-8"), "one\n")
        self.assertFalse((repo / "new.txt").exists())
        self.assertIn(f"Roll back run {STAMP}", git(repo, "log", "-1", "--format=%s"))

    def test_cli_create_and_line(self) -> None:
        repo = make_repo()
        done = subprocess.run([sys.executable, "-I", str(SCRIPTS / "rollback_ref.py"), "create", "--stamp", STAMP, "--repo", str(repo)],
                              capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        line = subprocess.run([sys.executable, "-I", str(SCRIPTS / "rollback_ref.py"), "line", "--stamp", STAMP, "--repo", str(repo)],
                              capture_output=True, text=True, check=False)
        self.assertTrue(json.loads(line.stdout)["line"].startswith("Rollback (human-run"))
        missing = subprocess.run([sys.executable, "-I", str(SCRIPTS / "rollback_ref.py"), "line", "--stamp", "20261105-9", "--repo", str(repo)],
                                 capture_output=True, text=True, check=False)
        self.assertEqual(missing.returncode, 1)

    def test_handoff_carries_the_rollback_line(self) -> None:
        from _load import load
        handoff: Any = load("handoff-write")
        receipt = f"### Rollback point\n\nabc123\n{rollback_ref.rollback_line(STAMP, 'a' * 40)}\n"
        self.assertTrue(handoff.rollback_line(receipt).startswith("Rollback (human-run"))
        self.assertEqual(handoff.rollback_line("### Rollback point\nabc\n"), "Rollback: none recorded")

    def test_run_text_creates_the_ref_and_writes_the_line(self) -> None:
        text = read_run_skill()
        self.assertIn("rollback_ref.py", text)
        self.assertIn("create --stamp", text)
        self.assertIn("refs/dts2/<stamp>/base", text)
        self.assertIn("line --stamp", text)


class EscalationSeatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.claude: dict[str, Any] = Profiles.load(PLUGIN_ROOT / "profiles" / "agents").as_dict()["claude"]

    def test_escalation_is_frontier_at_high_effort(self) -> None:
        for complexity in ("mechanical", "normal", "design"):
            result = delegate.delegate(self.claude, "escalation", complexity)
            self.assertEqual((result["tier"], result["effort"]), ("frontier", "high"), complexity)
            self.assertEqual(result["model"], self.claude["models"]["frontier"])

    def test_escalation_is_not_an_execution_violation_and_does_not_follow_the_lead(self) -> None:
        self.assertFalse(delegate.violates_execution_policy("escalation", "frontier"))
        profiles = Profiles.load(PLUGIN_ROOT / "profiles" / "agents").as_dict()
        other = next(n for n in profiles if n != "claude" and profiles[n].get("models", {}).get("frontier"))
        result = delegate.delegate(profiles[other], "escalation", "normal", lead_provider="claude", profiles=profiles)
        self.assertEqual(result["agent"], other)

    def test_builders_still_never_get_frontier(self) -> None:
        for complexity in ("mechanical", "normal", "design"):
            self.assertNotEqual(delegate.delegate(self.claude, "execution", complexity)["tier"], "frontier")

    def test_cli_accepts_the_seat(self) -> None:
        done = subprocess.run([sys.executable, "-I", str(SCRIPTS / "delegate.py"), "--agent", "claude", "--seat", "escalation",
                               "--complexity", "normal"], capture_output=True, text=True, check=False)
        self.assertEqual(json.loads(done.stdout)["effort"], "high")


class FixerTextTests(unittest.TestCase):
    def test_fixer_agent_is_a_fresh_builder_contract_at_high_effort(self) -> None:
        text = (PLUGIN_ROOT / "agents" / "fixer.md").read_text(encoding="utf-8")
        front = text.split("---")[1]
        self.assertIn("name: fixer", front)
        self.assertIn("effort: high", front)
        self.assertIn("model: sonnet", front)
        self.assertRegex(front, r"maxTurns: \d+")
        for needle in ("PARTIAL: hit turn cap at", "FLAGS:", "Worker contract (Rule 9.5)", "Never push", "Never spawn subagents",
                       "HYPOTHESIS REFUTED", "escalation"):
            self.assertIn(needle, text)

    def test_hypothesis_scouts_are_read_only(self) -> None:
        text = (PLUGIN_ROOT / "agents" / "scout.md").read_text(encoding="utf-8")
        self.assertIn("## Hypothesis mode", text)
        self.assertIn("`Mode: hypothesis`", text)
        self.assertIn("you never fix", text.lower())

    def test_fix_round_two_runs_scouts_then_lead_pick_then_fixer(self) -> None:
        text = (PLUGIN_ROOT / "skills" / "run" / "phase-2-build.md").read_text(encoding="utf-8")
        step = text[text.index("7. A builder failing on the same error"):text.index("8. Run the integration task")]
        for needle in ("2-3 candidate causes", "`Mode: hypothesis`", "The lead (`dts2:lead`) picks", "`dts2:fixer`",
                       "--seat escalation", "`effort: high`", "`.harness/state.md`", "`(escalation)`", "round 2 goes to the fixer"):
            self.assertIn(needle, step)
        self.assertIn("/diagnosing-bugs", step)
        self.assertIsNotNone(re.search(r"scout` per hypothesis in a single message", step))


if __name__ == "__main__":
    unittest.main()
