"""Batch 6 (round 2): G-72 retryable ballots, G-73 agent tools, G-74 event hooks."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Final

PLUGIN: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN / "scripts"))
import council  # noqa: E402

AGENTS: Final[Path] = PLUGIN / "agents"
HOOKS: Final[Path] = PLUGIN / "hooks"
EXPECTED_TOOLS: Final[dict[str, str]] = {
    "auditor": "Read, Grep, Glob, Bash",
    "builder": "Read, Write, Edit, Grep, Glob, Bash",
    "fixer": "Read, Write, Edit, Grep, Glob, Bash",
    "incident-reviewer": "Read, Grep, Glob, Bash",
    "lead": "Read, Grep, Glob",
    "reviewer": "Read, Grep, Glob",
    "scout": "Read, Grep, Glob, Bash",
    "verifier": "Read, Grep, Glob, Bash",
}
CHECKS: Final[tuple[str, ...]] = ("test", "typecheck", "lint", "secret-scan", "scope-check")


def vote(votes: Path, order: int, kind: str, rnd: int, seat: str, text: str) -> None:
    (votes / f"{order:02d}-{kind}-r{rnd}-{seat}.md").write_text(text, encoding="utf-8")


def run_hook(name: str, cwd: Path, payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(HOOKS / name)], cwd=str(cwd), input=json.dumps(payload), capture_output=True, text=True,
                          check=False, env={"PATH": "/usr/bin:/bin:/usr/local/bin", "CLAUDE_PLUGIN_ROOT": str(PLUGIN)})


class NextRoundTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.votes = Path(self.tmp.name) / "votes"
        self.votes.mkdir()
        self.addCleanup(self.tmp.cleanup)

    def test_retryable_reasons(self) -> None:
        for reason in ("dispatch exited 1", "malformed ballot", "HTTP 429", "rate limit hit", "timed out"):
            self.assertTrue(council.is_retryable(reason), reason)
        self.assertFalse(council.is_retryable("VOTE: REJECT with findings"))

    def test_retry_keeps_round_and_raises_attempt(self) -> None:
        first = council.next_round(self.votes, "s3", "plan")
        again = council.next_round(self.votes, "s3", "plan", retry="HTTP 429")
        self.assertEqual((first["instance"], first["round"]), ("s3+1", 1))
        self.assertEqual((again["instance"], again["round"], again["opensRound"]), ("s3+2", 1, False))

    def test_malformed_ballot_does_not_open_a_failed_round(self) -> None:
        for order, seat in enumerate(("a", "b", "c"), 1):
            vote(self.votes, order, "plan", 1, seat, "no vote line here\n")
        self.assertEqual(council.eligibility(self.votes)["failedRounds"], 0)
        self.assertEqual(council.next_round(self.votes, "s3", "plan", retry="malformed ballot")["round"], 1)

    def test_complete_round_advances_the_round(self) -> None:
        for order, seat in enumerate(("a", "b", "c"), 1):
            vote(self.votes, order, "build", 1, seat, "VOTE: REJECT\n")
        self.assertEqual(council.next_round(self.votes, "s3", "build")["round"], 2)

    def test_postmerge_revote_has_its_own_instance(self) -> None:
        for order, seat in enumerate(("a", "b", "c"), 1):
            vote(self.votes, order, "build", 1, seat, "VOTE: REJECT\n")
        revote = council.next_round(self.votes, "s3", "build", revote=True)
        self.assertEqual((revote["instance"], revote["round"]), ("s3@postmerge+1", 1))
        self.assertEqual(council.eligibility(self.votes)["failedRounds"], 1)

    def test_cli(self) -> None:
        done = subprocess.run([sys.executable, "-I", str(PLUGIN / "scripts" / "council.py"), "next-round", "--votes-dir", str(self.votes),
                               "--step", "s9", "--kind", "plan"], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(done.stdout)["instance"], "s9+1")


class AgentToolsTests(unittest.TestCase):
    def test_each_agent_tools_line(self) -> None:
        for name, tools in EXPECTED_TOOLS.items():
            text = (AGENTS / f"{name}.md").read_text(encoding="utf-8")
            match = re.search(r"^tools:\s*(.+)$", text, re.MULTILINE)
            self.assertIsNotNone(match, name)
            assert match is not None
            self.assertEqual(match.group(1).strip(), tools, name)

    def test_every_agent_is_pinned(self) -> None:
        self.assertEqual({p.stem for p in AGENTS.glob("*.md")}, set(EXPECTED_TOOLS))

    def test_reviewer_has_no_bash(self) -> None:
        text = (AGENTS / "reviewer.md").read_text(encoding="utf-8")
        self.assertNotIn("Bash is for read-only", text)


class EventHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        (self.repo / ".harness" / "runs" / "20260101-000000").mkdir(parents=True)
        self.addCleanup(self.tmp.cleanup)

    def ledger(self, names: tuple[str, ...]) -> None:
        path = self.repo / ".harness" / "runs" / "20260101-000000" / "ledger.jsonl"
        path.write_text("".join(json.dumps({"kind": "check", "name": n, "status": "pass"}) + "\n" for n in names), encoding="utf-8")

    def test_hooks_json_registers_events(self) -> None:
        hooks = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        self.assertIn("StopFailure", hooks)
        self.assertIn("PermissionDenied", hooks)
        self.assertIn("dt:verifier", [m.get("matcher") for m in hooks["SubagentStop"]])
        self.assertIn("pre-compact.sh", json.dumps(hooks["PreCompact"]))

    def test_verifier_blocked_without_check_lines(self) -> None:
        self.ledger(CHECKS[:3])
        done = run_hook("subagent-stop.sh", self.repo, {"agent_type": "dt:verifier", "cwd": str(self.repo)})
        out = json.loads(done.stdout)
        self.assertEqual(out["decision"], "block")
        self.assertIn("secret-scan", out["reason"])
        self.assertIn("scope-check", out["reason"])

    def test_verifier_passes_with_all_lines_or_active_hook(self) -> None:
        self.ledger(CHECKS)
        self.assertEqual(run_hook("subagent-stop.sh", self.repo, {"agent_type": "dt:verifier", "cwd": str(self.repo)}).stdout, "")
        self.ledger(CHECKS[:1])
        active = {"agent_type": "dt:verifier", "cwd": str(self.repo), "stop_hook_active": True}
        self.assertEqual(run_hook("subagent-stop.sh", self.repo, active).stdout, "")

    def test_stop_failure_appends_once(self) -> None:
        payload = {"cwd": str(self.repo), "session_id": "s1", "error": "rate_limit", "error_details": "429 Bearer abc123def"}
        for _ in range(2):
            self.assertEqual(run_hook("stop-failure.sh", self.repo, payload).returncode, 0)
        text = (self.repo / ".harness" / "action-items.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("StopFailure rate_limit"), 1)
        self.assertNotIn("abc123def", text)

    def test_permission_denied_appends(self) -> None:
        payload = {"cwd": str(self.repo), "session_id": "s2", "tool_name": "Bash", "reason": "git push denied"}
        self.assertEqual(run_hook("permission-denied.sh", self.repo, payload).returncode, 0)
        text = (self.repo / ".harness" / "action-items.md").read_text(encoding="utf-8")
        self.assertIn("PermissionDenied for Bash", text)

    def test_no_harness_dir_is_a_noop(self) -> None:
        with tempfile.TemporaryDirectory() as bare:
            done = run_hook("stop-failure.sh", Path(bare), {"cwd": bare, "error": "overloaded"})
            self.assertEqual(done.returncode, 0)
            self.assertFalse((Path(bare) / ".harness").exists())


if __name__ == "__main__":
    unittest.main()
