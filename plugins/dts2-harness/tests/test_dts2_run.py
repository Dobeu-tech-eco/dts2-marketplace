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
        text: str = self.run_mod.build_receipt(VERIFY, "approved", "Jeremy", "abc123")
        self.assertIn("## Change receipt", text)
        self.assertIn("| 2 | 1 | 0 |", text)
        self.assertIn("Jeremy", text)
        self.assertIn("abc123", text)
        self.assertIn("approved", text)

    def test_ship_allowed_needs_flag_and_env(self) -> None:
        on = argparse.Namespace(ship=True)
        off = argparse.Namespace(ship=False)
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(self.run_mod.ship_allowed(on, BRANCH))
        with mock.patch.dict(os.environ, {"DTS2_SHIP_BRANCH": BRANCH}, clear=True):
            self.assertTrue(self.run_mod.ship_allowed(on, BRANCH))
            self.assertFalse(self.run_mod.ship_allowed(off, BRANCH))
            self.assertFalse(self.run_mod.ship_allowed(on, "other"))

    def test_handoff_lanes(self) -> None:
        roster = {"roster": [{"name": "claude"}, {"name": "cursor"}]}
        self.assertEqual(self.run_mod.handoff_lanes(roster), ["cursor"])
        self.assertEqual(self.run_mod.handoff_lanes({"roster": [{"name": "claude"}]}), [])
        explicit = {"roster": [{"name": "codex", "mode": "handoff"}]}
        self.assertEqual(self.run_mod.handoff_lanes(explicit), ["codex"])

    def test_parse_roster_modes(self) -> None:
        text = "roster:\n  - name: claude\n  - name: codex\n    mode: handoff\n"
        roster = self.run_mod.parse_roster_config(text)
        self.assertEqual(self.run_mod.handoff_lanes(roster), ["codex"])


if __name__ == "__main__":
    unittest.main()
