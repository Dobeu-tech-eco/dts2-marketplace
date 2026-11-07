"""Wiring: roster treats exit 143 as a timeout; council substitutes timed-out seats and notes identical rounds via seat_swap."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, isolate_agent_status

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import council  # noqa: E402
import roster  # noqa: E402
import seat_swap  # noqa: E402

SEATS_DOC: Final[dict[str, Any]] = {
    "seats": [{"seat": "s1", "provider": "claude", "model": "m1"}, {"seat": "s2", "provider": "codex", "model": "m2"}],
    "bench": [{"seat": "b1", "provider": "gemini", "model": "m3"}],
}
FINDINGS: Final[str] = "VOTE: REJECT\n\n## Findings\n- Missing test\n- Bad name\n"


class RosterTimeoutTest(unittest.TestCase):
    def setUp(self) -> None:
        isolate_agent_status(self)

    def test_constant_matches_seat_swap(self) -> None:
        self.assertEqual(roster.TIMEOUT_EXIT_CODE, seat_swap.TIMEOUT_EXIT)

    def test_exit_143_is_timeout_seat_failure(self) -> None:
        out: dict[str, Any] = roster.classify_dispatch("codex", "reviewer", "", roster.TIMEOUT_EXIT_CODE)
        self.assertEqual(out["outcome"], "timeout")
        self.assertTrue(out["seatFailed"])
        self.assertFalse(out["dropForRun"])
        self.assertTrue(seat_swap.is_timeout(out))

    def test_other_nonzero_still_failed(self) -> None:
        out: dict[str, Any] = roster.classify_dispatch("codex", "reviewer", "", 1)
        self.assertEqual(out["outcome"], "failed")


class CouncilWiringTest(unittest.TestCase):
    def test_substitute_seat_swaps_and_ledgers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger: Path = Path(tmp) / "ledger.jsonl"
            result: dict[str, Any] = council.substitute_seat(SEATS_DOC, "s2", ledger, "step-1")
            self.assertTrue(result["ok"])
            self.assertEqual([s["seat"] for s in result["seats"]], ["s1", "b1"])
            self.assertIn("seat-swap", ledger.read_text(encoding="utf-8"))

    def test_substitute_unknown_seat_not_ok(self) -> None:
        self.assertFalse(council.substitute_seat(SEATS_DOC, "zz", None, "")["ok"])

    def test_swap_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            seats: Path = Path(tmp) / "seats.json"
            seats.write_text(json.dumps(SEATS_DOC), encoding="utf-8")
            done = subprocess.run([sys.executable, "-I", str(PLUGIN_ROOT / "scripts" / "council.py"), "swap",
                                   "--seats", str(seats), "--failed", "s1"],
                                  capture_output=True, text=True, check=True, cwd=str(PLUGIN_ROOT))
            self.assertEqual(json.loads(done.stdout)["swap"]["to"], "b1")

    def test_identical_cli_notes_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            votes: Path = Path(tmp) / "votes"
            votes.mkdir()
            for n in (1, 2):
                (votes / f"1-plan-r{n}-claude.md").write_text(FINDINGS, encoding="utf-8")
            ledger: Path = Path(tmp) / "ledger.jsonl"
            done = subprocess.run([sys.executable, "-I", str(PLUGIN_ROOT / "scripts" / "council.py"), "identical",
                                   "--votes-dir", str(votes), "--ledger", str(ledger), "--step", "s",
                                   "--prev", "1", "--curr", "2"],
                                  capture_output=True, text=True, check=True, cwd=str(PLUGIN_ROOT))
            self.assertTrue(json.loads(done.stdout)["identical"])
            self.assertIn("identical-findings", ledger.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
