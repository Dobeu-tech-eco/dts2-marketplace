"""Scope check script, context guard hook, and the text contracts that tie them to the skills."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, make_tmp_home

SCOPE_SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "scope-check.py"
GUARD_HOOK: Final[Path] = PLUGIN_ROOT / "hooks" / "context-guard.sh"
MANIFEST: Final[str] = ".harness-workspace.yaml"
SETTINGS_REL: Final[str] = ".claude/dts2-harness.local.md"
TOOL_LINE: Final[str] = '{"type":"assistant","message":{"content":[{"type": "tool_use","name":"Bash"}]}}\n'
SMALL_THRESHOLD: Final[int] = 3


def scope_of(path: Path) -> dict[str, Any]:
    out: subprocess.CompletedProcess[str] = subprocess.run(
        ["python3", "-I", str(SCOPE_SCRIPT), str(path)], capture_output=True, text=True, check=False)
    return json.loads(out.stdout)


def make_workspace() -> tuple[Path, Path]:
    root: Path = make_tmp_home().resolve()
    (root / MANIFEST).write_text("repos: []\n", encoding="utf-8")
    member: Path = root / "api"
    member.mkdir()
    return root, member


def write_settings(cwd: Path, body: str) -> None:
    (cwd / ".claude").mkdir(exist_ok=True)
    (cwd / SETTINGS_REL).write_text(f"---\n{body}\n---\n", encoding="utf-8")


def make_transcript(cwd: Path, calls: int) -> Path:
    path: Path = cwd / "transcript.jsonl"
    path.write_text(TOOL_LINE * calls, encoding="utf-8")
    return path


def run_guard(cwd: Path, transcript: Path, session: str, tmp: Path) -> subprocess.CompletedProcess[str]:
    payload: str = json.dumps({"transcript_path": str(transcript), "session_id": session, "cwd": str(cwd)})
    env: dict[str, str] = {**os.environ, "TMPDIR": str(tmp)}
    return subprocess.run(["bash", str(GUARD_HOOK)], input=payload, cwd=str(cwd), env=env,
                          capture_output=True, text=True, check=False)


class ScopeCheckTests(unittest.TestCase):
    def test_workspace_root(self) -> None:
        root, _ = make_workspace()
        data: dict[str, Any] = scope_of(root)
        self.assertEqual(data["scope"], "workspace-root")
        self.assertEqual(data["workspaceRoot"], str(root))
        self.assertEqual(data["manifest"], str(root / MANIFEST))

    def test_member_without_own_harness(self) -> None:
        root, member = make_workspace()
        data: dict[str, Any] = scope_of(member)
        self.assertEqual(data["scope"], "workspace-member")
        self.assertEqual(data["workspaceRoot"], str(root))
        self.assertIn(f"Run from {root}", data["advice"])

    def test_member_with_own_harness_is_still_member(self) -> None:
        root, member = make_workspace()
        (member / ".harness").mkdir()
        (member / ".harness" / "config.yaml").write_text("project: api\n", encoding="utf-8")
        data: dict[str, Any] = scope_of(member)
        self.assertEqual(data["scope"], "workspace-member")
        self.assertEqual(data["repoConfig"], str(member / ".harness" / "config.yaml"))

    def test_single_repo(self) -> None:
        repo: Path = make_tmp_home().resolve()
        (repo / ".harness").mkdir()
        (repo / ".harness" / "config.yaml").write_text("project: x\n", encoding="utf-8")
        data: dict[str, Any] = scope_of(repo)
        self.assertEqual(data["scope"], "single")
        self.assertIsNone(data["workspaceRoot"])
        self.assertFalse(data["endState"])

    def test_none(self) -> None:
        data: dict[str, Any] = scope_of(make_tmp_home().resolve())
        self.assertEqual(data["scope"], "none")
        self.assertIn("/dts2-harness:setup", data["advice"])

    def test_end_state_flag_uses_effective_root(self) -> None:
        root, member = make_workspace()
        self.assertFalse(scope_of(member)["endState"])
        (root / ".harness").mkdir()
        (root / ".harness" / "end-state.md").write_text("x\n", encoding="utf-8")
        self.assertTrue(scope_of(member)["endState"])
        self.assertTrue(scope_of(root)["endState"])


class ContextGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp: Path = Path(tempfile.mkdtemp())
        self.cwd: Path = make_tmp_home().resolve()

    def test_below_thresholds_is_silent(self) -> None:
        result = run_guard(self.cwd, make_transcript(self.cwd, 2), "s1", self.tmp)
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_spike_fires_once(self) -> None:
        write_settings(self.cwd, f"context_guard_tool_calls: {SMALL_THRESHOLD}")
        transcript: Path = make_transcript(self.cwd, SMALL_THRESHOLD)
        first = run_guard(self.cwd, transcript, "s2", self.tmp)
        self.assertEqual(first.returncode, 0)
        payload: dict[str, Any] = json.loads(first.stdout)
        text: str = payload["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(payload["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        self.assertIn("CONTEXT GUARD (spike)", text)
        self.assertIn("with no plan checkpoint reached", text)
        self.assertEqual(run_guard(self.cwd, transcript, "s2", self.tmp).stdout, "")

    def test_plan_checkpoint_suppresses_spike(self) -> None:
        write_settings(self.cwd, f"context_guard_tool_calls: {SMALL_THRESHOLD}")
        plan_dir: Path = self.cwd / ".harness" / "runs" / "x"
        plan_dir.mkdir(parents=True)
        (self.cwd / ".harness" / "config.yaml").write_text("project: x\n", encoding="utf-8")
        (plan_dir / "plan.md").write_text("plan\n", encoding="utf-8")
        result = run_guard(self.cwd, make_transcript(self.cwd, 5), "s3", self.tmp)
        self.assertEqual(result.stdout, "")

    def test_misplaced_fires_in_member(self) -> None:
        root, member = make_workspace()
        result = run_guard(member, make_transcript(member, 1), "s4", self.tmp)
        self.assertIn("CONTEXT GUARD (misplaced)", result.stdout)
        self.assertIn(str(root), result.stdout)

    def test_disabled_is_silent(self) -> None:
        write_settings(self.cwd, f"context_guard: false\ncontext_guard_tool_calls: {SMALL_THRESHOLD}")
        result = run_guard(self.cwd, make_transcript(self.cwd, 5), "s5", self.tmp)
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_bad_input_exits_zero(self) -> None:
        env: dict[str, str] = {**os.environ, "TMPDIR": str(self.tmp)}
        result = subprocess.run(["bash", str(GUARD_HOOK)], input="not json", cwd=str(self.cwd), env=env,
                                capture_output=True, text=True, check=False)
        self.assertEqual((result.returncode, result.stdout), (0, ""))


def read(rel: str) -> str:
    return (PLUGIN_ROOT / rel).read_text(encoding="utf-8")


class ScopeTextContracts(unittest.TestCase):
    def test_run_skill(self) -> None:
        text: str = read("skills/run/SKILL.md")
        for needle in ("## Context guard and pivot", "Pivot: <repo> belongs to workspace", "scope-check.py",
                       "Context guard fired (<trigger>): stopping all agents and re-running setup.", "- Context guard:"):
            self.assertIn(needle, text)
        self.assertLess(text.find("## Context guard and pivot"), text.find("## Guardrails"))

    def test_setup_skill(self) -> None:
        self.assertIn("Run setup at the workspace root instead?", read("skills/setup/SKILL.md"))

    def test_discipline_and_templates(self) -> None:
        self.assertIn("Scope before spend", read("templates/discipline.md"))
        self.assertIn("context_guard_tool_calls", read("templates/dts2-harness.local.md"))

    def test_hooks_json_and_session_hook(self) -> None:
        self.assertIn("context-guard.sh", read("hooks/hooks.json"))
        self.assertIn("scope-check.py", read("hooks/session-lessons.sh"))
        self.assertIn("run pivots there automatically", read("hooks/session-lessons.sh"))

    def test_onboard_mentions_pivot(self) -> None:
        self.assertIn("context guard", read("skills/onboard/SKILL.md"))


if __name__ == "__main__":
    unittest.main()
