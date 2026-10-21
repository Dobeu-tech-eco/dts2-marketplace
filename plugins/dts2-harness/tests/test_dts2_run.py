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


if __name__ == "__main__":
    unittest.main()
