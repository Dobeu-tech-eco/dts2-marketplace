"""B15B: Q-8 subagent report check, Q-16 SessionEnd lease release, spawn dry-run hook."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, make_tmp_home

HOOKS: Final[Path] = PLUGIN_ROOT / "hooks"
STAMP: Final[str] = "20261104-090000"
SESSION: Final[str] = "sess-1"
GOOD_BUILDER: Final[str] = "## Files changed\n- a\n\n## Commands run\n- t\n\n## Concerns\nnone\n"


def run_hook(name: str, payload: dict[str, Any], *args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(HOOKS / name), *args], input=json.dumps(payload), capture_output=True, text=True,
                          cwd=str(cwd or make_tmp_home()), env={**os.environ, **(env or {})}, check=False)


def stop(agent: str, text: str, **extra: Any) -> dict[str, Any]:
    out = run_hook("subagent-report.sh", {"agent_type": agent, "last_assistant_message": text, **extra}, "stop")
    return json.loads(out.stdout) if out.stdout.strip() else {}


class RegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hooks = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))["hooks"]

    def test_events_registered(self) -> None:
        self.assertIn("builder", self.hooks["SubagentStop"][0]["matcher"])
        self.assertIn("SessionEnd", self.hooks)
        self.assertIn("SubagentHandback", [g.get("matcher") for g in self.hooks["PostToolUse"]])
        self.assertIn("Agent", [g.get("matcher") for g in self.hooks["PreToolUse"]])

    def test_scripts_exist_and_are_executable(self) -> None:
        for name in ("subagent-report.sh", "session-end.sh", "spawn-dry-run.sh"):
            self.assertTrue(os.access(HOOKS / name, os.X_OK), name)


class SubagentReportTests(unittest.TestCase):
    def test_complete_report_passes(self) -> None:
        self.assertEqual(stop("dt:builder", GOOD_BUILDER), {})

    def test_missing_sections_block_with_exact_names(self) -> None:
        result = stop("dt:builder", "## Files changed\n- a\n")
        self.assertEqual(result["decision"], "block")
        self.assertIn("'commands run', 'concerns'", result["reason"])
        self.assertNotIn("'files changed'", result["reason"])

    def test_stop_hook_active_is_skipped(self) -> None:
        self.assertEqual(stop("dt:builder", "nothing", stop_hook_active=True), {})

    def test_other_agents_and_partial_reports_pass(self) -> None:
        self.assertEqual(stop("dt:scout", "nothing"), {})
        self.assertEqual(stop("dt:reviewer", "PARTIAL: hit turn cap at review\n"), {})

    def test_reviewer_needs_findings_and_verdict(self) -> None:
        self.assertIn("'findings', 'verdict'", stop("dt:reviewer", "looks fine")["reason"])

    def test_handback_blocks_once_per_agent(self) -> None:
        tmp = tempfile.mkdtemp(prefix="dts2-tmpdir-")
        payload = {"tool_name": "SubagentHandback", "agent_type": "dt:verifier", "agent_id": "a1", "session_id": "s",
                   "tool_input": {"message": "## Results\nok\n"}}
        first = run_hook("subagent-report.sh", payload, "handback", env={"TMPDIR": tmp})
        self.assertEqual(json.loads(first.stdout)["decision"], "block")
        self.assertIn("'verdict'", json.loads(first.stdout)["reason"])
        self.assertEqual(run_hook("subagent-report.sh", payload, "handback", env={"TMPDIR": tmp}).stdout.strip(), "")

    def test_handback_ignores_other_tools_and_disabled_setting(self) -> None:
        other = {"tool_name": "Bash", "agent_type": "dt:verifier", "tool_input": {"message": "x"}}
        self.assertEqual(run_hook("subagent-report.sh", other, "handback").stdout.strip(), "")
        repo = make_tmp_home()
        (repo / ".claude").mkdir()
        (repo / ".claude" / "dts2-harness.local.md").write_text("---\nsubagent_report_check: false\n---\n", encoding="utf-8")
        out = run_hook("subagent-report.sh", {"agent_type": "dt:builder", "last_assistant_message": "x"}, "stop", cwd=repo)
        self.assertEqual(out.stdout.strip(), "")


def lease(repo: Path, lane: str, **fields: Any) -> Path:
    path = repo / ".harness" / "runs" / STAMP / lane / "lease.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"stamp": STAMP, "lane": lane, "status": "active", "epoch": 2, **fields}), encoding="utf-8")
    return path


def status_of(path: Path) -> str:
    return str(json.loads(path.read_text(encoding="utf-8"))["status"])


class SessionEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = make_tmp_home()
        self.mine = lease(self.repo, "mine", session_id=SESSION)
        self.theirs = lease(self.repo, "theirs", session_id="other")
        self.unowned = lease(self.repo, "unowned")

    def end(self, reason: str) -> subprocess.CompletedProcess[str]:
        return run_hook("session-end.sh", {"session_id": SESSION, "reason": reason, "cwd": str(self.repo)}, cwd=self.repo)

    def test_releases_only_this_sessions_lease(self) -> None:
        self.assertEqual(self.end("logout").returncode, 0)
        self.assertEqual(status_of(self.mine), "closed")
        self.assertEqual(status_of(self.theirs), "active")
        self.assertEqual(status_of(self.unowned), "active")

    def test_runs_the_handoff_write(self) -> None:
        self.end("prompt_input_exit")
        self.assertTrue((self.repo / ".harness" / "handoff" / "latest.md").is_file())

    def test_other_reasons_do_nothing(self) -> None:
        for reason in ("clear", "resume"):
            self.end(reason)
        self.assertEqual(status_of(self.mine), "active")
        self.assertFalse((self.repo / ".harness" / "handoff" / "latest.md").exists())

    def test_reason_other_releases_and_bad_payload_never_fails(self) -> None:
        self.end("other")
        self.assertEqual(status_of(self.mine), "closed")
        junk = subprocess.run(["bash", str(HOOKS / "session-end.sh")], input="not json", capture_output=True, text=True, cwd=str(self.repo), check=False)
        self.assertEqual(junk.returncode, 0)


class SpawnDryRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = make_tmp_home()
        (self.repo / ".harness" / "runs" / "s1").mkdir(parents=True)
        (self.repo / "wt").mkdir()
        self.fake = self.repo / "claude.py"
        self.fake.write_text("#!/usr/bin/env python3\nimport pathlib, sys\npathlib.Path(sys.argv[0]).with_suffix('.ran').write_text('x')\n", encoding="utf-8")
        (self.repo / "lanes.json").write_text(json.dumps({
            "stamp": "s1", "base": "abc", "scope": "single",
            "lanes": [{"id": "a", "item": "S1", "files": ["src/a.py"], "ids": {}, "depends_on": [], "tier": "standard"}]}), encoding="utf-8")

    def call(self, tool: str, tool_input: dict[str, Any], setting: bool = False) -> dict[str, Any]:
        if setting:
            (self.repo / ".claude").mkdir(exist_ok=True)
            (self.repo / ".claude" / "dts2-harness.local.md").write_text("---\nspawn_dry_run: true\n---\n", encoding="utf-8")
        out = run_hook("spawn-dry-run.sh", {"tool_name": tool, "tool_input": tool_input, "cwd": str(self.repo)}, cwd=self.repo,
                       env={"DTS2_CLAUDE_BIN": str(self.fake)})
        return json.loads(out.stdout) if out.stdout.strip() else {}

    def test_bash_dry_run_denies_and_prints_command_and_brief(self) -> None:
        result = self.call("Bash", {"command": "python3 scripts/lanes.py spawn lanes.json --lane a --worktree wt --dry-run"})
        decision = result["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "deny")
        reason = decision["permissionDecisionReason"]
        for needle in ("nothing was started", "--append-system-prompt", "env_allowlist", "--- brief.md ---", "S1"):
            self.assertIn(needle, reason)
        self.assertFalse(self.fake.with_suffix(".ran").exists())

    def test_real_spawn_and_unrelated_commands_pass_through(self) -> None:
        self.assertEqual(self.call("Bash", {"command": "python3 scripts/lanes.py spawn lanes.json --lane a --worktree wt"}), {})
        self.assertEqual(self.call("Bash", {"command": "ls --dry-run"}), {})

    def test_unknown_lane_reports_why_without_crashing(self) -> None:
        reason = self.call("Bash", {"command": "lanes.py spawn lanes.json --lane zz --worktree wt --dry-run"})["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("could not be composed", reason)

    def test_agent_dispatch_is_untouched_unless_the_setting_is_on(self) -> None:
        tool_input = {"subagent_type": "dt:builder", "prompt": "do the thing"}
        self.assertEqual(self.call("Agent", tool_input), {})
        reason = self.call("Agent", tool_input, setting=True)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("do the thing", reason)
        self.assertIn("prompt bytes: 12", reason)


if __name__ == "__main__":
    unittest.main()
