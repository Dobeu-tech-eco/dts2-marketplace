"""Tests for the pure functions in sdk/dts2-run.py."""
from __future__ import annotations

import argparse
import importlib.util
import os
import unittest
from pathlib import Path
from types import ModuleType
from typing import Final
from unittest import mock

RUNNER: Final[Path] = Path(__file__).resolve().parent.parent / "sdk" / "dts2-run.py"
BRANCH: Final[str] = "feat/x"
VERIFY: Final[str] = (
    "| Check | Result | Notes |\n|---|---|---|\n| Tests | PASS | 12 passed, 0 failed |\n"
    "| Lint | PASS | ok |\n| Walkthrough | FAIL | x |\n\n### Verdict: VERIFIED\n"
)


def load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("dts2_run", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Dts2RunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.run_mod: ModuleType = load_runner()

    def test_receipt_has_heading_and_counts(self) -> None:
        review: str = "### Verdict: APPROVE\n"
        text: str = self.run_mod.build_receipt(VERIFY, review, "approver-name", "abc123")
        self.assertIn("## Change receipt", text)
        self.assertIn("| 2 | 1 | 0 |", text)
        self.assertIn("approver-name", text)
        self.assertIn("abc123", text)
        self.assertIn("approved", text)
        self.assertIn("- Production: not deployed yet", text)
        self.assertIn("none recorded (headless run)", text)
        self.assertIn("see 3-review.md", text)

    def test_blocker_word_is_not_a_block(self) -> None:
        text: str = self.run_mod.build_receipt(VERIFY, "Not a BLOCKer\n### Verdict: APPROVE", "x", "r")
        self.assertIn("approved (reviewer", text)
        blocked: str = self.run_mod.build_receipt(VERIFY, "### Verdict: BLOCK", "x", "r")
        self.assertIn("changes requested", blocked)

    def test_verdict_of(self) -> None:
        self.assertEqual(self.run_mod.verdict_of(VERIFY), "VERIFIED")
        self.assertEqual(self.run_mod.verdict_of("no verdict"), "")

    def test_has_done(self) -> None:
        self.assertTrue(self.run_mod.has_done("## Done\n\n- tests pass\n"))
        self.assertFalse(self.run_mod.has_done("## Done\n\nnothing listed\n"))
        self.assertFalse(self.run_mod.has_done("## Plan\n- a step\n"))

    def test_ship_allowed_needs_flag_and_env(self) -> None:
        on = argparse.Namespace(ship=True)
        off = argparse.Namespace(ship=False)
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(self.run_mod.ship_allowed(on, BRANCH))
        with mock.patch.dict(os.environ, {"DTS2_SHIP_BRANCH": BRANCH}, clear=True):
            self.assertTrue(self.run_mod.ship_allowed(on, BRANCH))
            self.assertFalse(self.run_mod.ship_allowed(off, BRANCH))
            self.assertFalse(self.run_mod.ship_allowed(on, "other"))
        with mock.patch.dict(os.environ, {"DTS2_SHIP_BRANCH": "main"}, clear=True):
            self.assertFalse(self.run_mod.ship_allowed(on, "main"))

    def test_handoff_lanes_from_plan(self) -> None:
        plan: str = "### Builder 1 (claude)\n### Builder 2 (cursor)\n### Builder 3 (cursor)\n"
        self.assertEqual(self.run_mod.handoff_lanes(plan), ["cursor"])
        self.assertEqual(self.run_mod.handoff_lanes("### Builder 1 (claude)\n"), [])
        self.assertEqual(self.run_mod.handoff_lanes("no builders"), [])

    def test_is_secret_path(self) -> None:
        for path in (".env", "app/.env", ".env.local"):
            self.assertTrue(self.run_mod.is_secret_path(path), path)
        for path in (".env.example", "src/env.py", "app/.envrc"):
            self.assertFalse(self.run_mod.is_secret_path(path), path)

    def test_auth_flags_api_key_mode(self) -> None:
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}, clear=True):
            self.assertTrue(self.run_mod.resolve_auth(None).startswith("api-key (pay-per-use) from"))
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.run_mod.resolve_auth(None), "subscription (existing Claude Code login)")

    def test_second_opinion_closes_stdin(self) -> None:
        done = mock.Mock(stdout="ok", stderr="")
        with mock.patch.object(self.run_mod.shutil, "which", return_value="/bin/codex"), \
                mock.patch.object(self.run_mod.subprocess, "run", return_value=done) as run:
            self.run_mod.second_opinion("codex", "diff", Path("."))
        self.assertIs(run.call_args.kwargs["stdin"], self.run_mod.subprocess.DEVNULL)

    def gemini_call(self, argv: list[str] | None) -> tuple[list[str], dict, str]:
        seen: dict = {}

        def fake_run(cmd: list[str], **kwargs: object) -> mock.Mock:
            folder: Path = Path(cmd[cmd.index("--add-dir") + 1])
            seen["files"] = {f.name: f.read_text(encoding="utf-8") for f in folder.iterdir()}
            seen["cmd"], seen["kwargs"] = cmd, kwargs
            return mock.Mock(stdout="findings", stderr="")

        lookup = mock.patch.object(self.run_mod, "profile_command", return_value=argv) if argv \
            else mock.patch.object(self.run_mod, "profile_command", side_effect=RuntimeError("no roster"))
        with lookup, mock.patch.object(self.run_mod.shutil, "which", return_value="/bin/agy"), \
                mock.patch.object(self.run_mod.subprocess, "run", side_effect=fake_run):
            out: str = self.run_mod.second_opinion("gemini", "DIFF-BODY", Path("/repo"))
        self.assertEqual(out, "findings")
        return seen["cmd"], seen["kwargs"], next(iter(seen["files"].values()))

    def test_gemini_second_opinion_uses_profile_reviewer_command(self) -> None:
        template: list[str] = [
            "agy", "-p", "{prompt}", "--mode", "plan", "--model", "gemini-3.8-flash-medium",
            "--print-timeout", "15m", "--add-dir", "{addDir}",
        ]
        cmd, kwargs, diff_file = self.gemini_call(template)
        self.assertEqual(cmd[0], "agy")
        self.assertEqual(cmd[cmd.index("--mode") + 1], "plan")
        self.assertEqual(cmd[cmd.index("--model") + 1], "gemini-3.8-flash-medium")
        self.assertNotIn("{prompt}", cmd)
        self.assertNotIn("{addDir}", cmd)
        self.assertNotIn("DIFF-BODY", cmd[2])
        self.assertIn("do not run commands", cmd[2])
        self.assertEqual(diff_file, "DIFF-BODY")
        self.assertEqual(kwargs["cwd"], Path("/repo"))
        self.assertIs(kwargs["stdin"], self.run_mod.subprocess.DEVNULL)

    def test_gemini_second_opinion_falls_back_to_plan_mode_agy(self) -> None:
        cmd, kwargs, _ = self.gemini_call(None)
        self.assertEqual(cmd[:2], ["agy", "-p"])
        self.assertEqual(cmd[3:7], ["--mode", "plan", "--print-timeout", "9m"])
        self.assertEqual(cmd[7], "--add-dir")
        self.assertIs(kwargs["stdin"], self.run_mod.subprocess.DEVNULL)

    def print_timeout_s(self, argv: list[str]) -> int:
        value: str = argv[argv.index("--print-timeout") + 1]
        self.assertTrue(value.endswith("m"), value)
        return int(value[:-1]) * 60

    def test_agy_print_timeout_fires_before_subprocess_timeout(self) -> None:
        limit: int = self.run_mod.SECOND_OPINION_TIMEOUT_S
        self.assertLess(self.print_timeout_s(self.run_mod.GEMINI_FALLBACK), limit)
        self.assertLess(self.print_timeout_s(self.run_mod.profile_command("gemini", "second-opinion")), limit)

    def timed_out(self, backend: str) -> str:
        expired = self.run_mod.subprocess.TimeoutExpired(["x"], 600)
        with mock.patch.object(self.run_mod, "profile_command", side_effect=RuntimeError("no roster")), \
                mock.patch.object(self.run_mod.shutil, "which", return_value="/bin/x"), \
                mock.patch.object(self.run_mod.subprocess, "run", side_effect=expired):
            return self.run_mod.second_opinion(backend, "diff", Path("."))

    def test_gemini_timeout_is_a_note(self) -> None:
        self.assertIn("second opinion timed out", self.timed_out("gemini"))

    def test_codex_timeout_is_a_note(self) -> None:
        self.assertIn("second opinion timed out", self.timed_out("codex"))

    def test_profile_command_reads_roster(self) -> None:
        argv: list[str] = self.run_mod.profile_command("gemini", "second-opinion")
        self.assertEqual(argv[:3], ["agy", "-p", "{prompt}"])
        self.assertIn("{addDir}", argv)

    def test_no_bare_gemini_binary(self) -> None:
        self.assertNotIn("gemini", self.run_mod.SECOND_OPINION_COMMANDS)


if __name__ == "__main__":
    unittest.main()
