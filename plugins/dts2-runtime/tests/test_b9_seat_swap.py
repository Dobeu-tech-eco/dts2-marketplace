"""B7: seat substitution on timeout and the identical-findings ledger note (scripts/seat_swap.py)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import seat_swap  # noqa: E402

CLI: Final[Path] = SCRIPTS / "seat_swap.py"


def seat(provider: str, model: str) -> dict[str, str]:
    return {"seat": f"{provider}-{model}", "provider": provider, "model": model, "via": "roster-command"}


SEATS: Final[list[dict[str, str]]] = [seat("claude", "opus"), seat("codex", "gpt-5"), seat("gemini", "pro"), seat("grok", "g4"),
                                      seat("cursor", "c1")]
BENCH: Final[list[dict[str, str]]] = [seat("codex", "mini"), seat("muse", "m1"), seat("claude", "sonnet")]


class IsTimeoutTests(unittest.TestCase):
    def test_timeout_shapes(self) -> None:
        self.assertTrue(seat_swap.is_timeout({"exit_code": 143}))
        self.assertTrue(seat_swap.is_timeout({"timed_out": True}))
        self.assertTrue(seat_swap.is_timeout({"outcome": "timeout"}))
        self.assertFalse(seat_swap.is_timeout({"exit_code": 1}))
        self.assertFalse(seat_swap.is_timeout({"exit_code": 0, "timed_out": False}))


class SwapTests(unittest.TestCase):
    def test_substitutes_the_next_provider_not_already_seated(self) -> None:
        result = seat_swap.swap_seat(SEATS, BENCH, "gemini-pro", now=100)
        self.assertTrue(result["ok"])
        self.assertEqual([s["seat"] for s in result["seats"]],
                         ["claude-opus", "codex-gpt-5", "muse-m1", "grok-g4", "cursor-c1"])
        self.assertEqual(result["swap"], {"from": "gemini-pro", "to": "muse-m1", "from_provider": "gemini", "to_provider": "muse",
                                          "reason": "timeout", "at": 100})
        self.assertEqual([s["seat"] for s in result["bench"]], ["codex-mini", "claude-sonnet"])

    def test_falls_back_to_a_seated_provider_when_the_bench_has_no_new_one(self) -> None:
        result = seat_swap.swap_seat(SEATS, [seat("codex", "mini")], "grok-g4", now=1)
        self.assertEqual(result["swap"]["to"], "codex-mini")
        self.assertEqual(result["bench"], [])

    def test_never_picks_the_failed_providers_own_model_first(self) -> None:
        result = seat_swap.swap_seat(SEATS, [seat("gemini", "flash"), seat("muse", "m1")], "gemini-pro", now=1)
        self.assertEqual(result["swap"]["to"], "muse-m1")

    def test_empty_bench_keeps_the_seats_and_says_so(self) -> None:
        result = seat_swap.swap_seat(SEATS, [], "gemini-pro", now=1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["seats"], SEATS)
        self.assertIsNone(result["swap"])
        self.assertIn("no substitute", result["detail"])

    def test_unknown_seat_is_refused(self) -> None:
        result = seat_swap.swap_seat(SEATS, BENCH, "nobody", now=1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["seats"], SEATS)

    def test_inputs_are_not_mutated(self) -> None:
        seats, bench = [dict(s) for s in SEATS], [dict(s) for s in BENCH]
        seat_swap.swap_seat(seats, bench, "gemini-pro", now=1)
        self.assertEqual((seats, bench), (SEATS, BENCH))


class FindingsTests(unittest.TestCase):
    def test_normalize_reads_the_findings_section(self) -> None:
        text = "# Review\n\nintro - not a finding\n\n## Findings\n\n- [HIGH] Missing null check in `a.py:12`.\n2. Race in lock  \n\n## Verdict\n\n- ok\n"
        self.assertEqual(seat_swap.normalize_findings(text), frozenset({"[high] missing null check in `a.py:12`", "race in lock"}))

    def test_without_a_section_every_bullet_counts(self) -> None:
        self.assertEqual(seat_swap.normalize_findings("- One\n* Two\nplain"), frozenset({"one", "two"}))

    def test_identical_ignores_case_order_and_bullets(self) -> None:
        self.assertTrue(seat_swap.identical_findings("## Findings\n- A thing\n- B thing\n", "## Findings\n1. b THING.\n2. a thing\n"))

    def test_different_or_empty_findings_are_not_identical(self) -> None:
        self.assertFalse(seat_swap.identical_findings("- a\n", "- a\n- b\n"))
        self.assertFalse(seat_swap.identical_findings("nothing here", "nothing here"))

    def test_round_findings_unions_the_seats_of_one_round(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            votes = Path(tmp)
            (votes / "01-build-r1-claude.md").write_text("## Findings\n- a\n", encoding="utf-8")
            (votes / "02-build-r1-codex.md").write_text("## Findings\n- b\n", encoding="utf-8")
            (votes / "03-build-r2-claude.md").write_text("## Findings\n- c\n", encoding="utf-8")
            (votes / "notes.md").write_text("- stray\n", encoding="utf-8")
            self.assertEqual(seat_swap.round_findings(votes, 1), frozenset({"a", "b"}))
            self.assertEqual(seat_swap.round_findings(votes, 2), frozenset({"c"}))
            self.assertEqual(seat_swap.round_findings(votes, 3), frozenset())


class LedgerTests(unittest.TestCase):
    def read(self, path: Path) -> list[dict[str, Any]]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def test_swap_is_recorded_as_a_ledger_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.jsonl"
            swap = seat_swap.swap_seat(SEATS, BENCH, "gemini-pro", now=5)["swap"]
            seat_swap.record_swap(ledger, "build-3", swap)
            rows = self.read(ledger)
            self.assertEqual(rows[0]["kind"], "note")
            self.assertEqual(rows[0]["event"], "seat-swap")
            self.assertEqual((rows[0]["step"], rows[0]["from"], rows[0]["to"]), ("build-3", "gemini-pro", "muse-m1"))

    def test_identical_rounds_write_a_note_and_nothing_else(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            votes, ledger = Path(tmp) / "votes", Path(tmp) / "ledger.jsonl"
            votes.mkdir()
            for n in (1, 2):
                (votes / f"0{n}-build-r{n}-claude.md").write_text("## Findings\n- same problem\n", encoding="utf-8")
            result = seat_swap.note_identical_rounds(votes, ledger, "build-3", 1, 2)
            self.assertTrue(result["identical"])
            self.assertEqual(result["findings"], 1)
            row = self.read(ledger)[0]
            self.assertEqual((row["kind"], row["event"], row["rounds"]), ("note", "identical-findings", [1, 2]))

    def test_differing_rounds_write_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            votes, ledger = Path(tmp) / "votes", Path(tmp) / "ledger.jsonl"
            votes.mkdir()
            (votes / "01-build-r1-claude.md").write_text("## Findings\n- a\n", encoding="utf-8")
            (votes / "02-build-r2-claude.md").write_text("## Findings\n- b\n", encoding="utf-8")
            self.assertFalse(seat_swap.note_identical_rounds(votes, ledger, "build-3", 1, 2)["identical"])
            self.assertFalse(ledger.exists())


class CliTests(unittest.TestCase):
    def test_swap_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "seats.json").write_text(json.dumps({"seats": SEATS, "bench": BENCH}), encoding="utf-8")
            done = subprocess.run([sys.executable, "-I", str(CLI), "swap", "--seats", str(root / "seats.json"), "--failed", "gemini-pro",
                                   "--ledger", str(root / "l.jsonl"), "--step", "build-3"], capture_output=True, text=True, check=False)
            out = json.loads(done.stdout)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(out["swap"]["to"], "muse-m1")
            self.assertTrue((root / "l.jsonl").is_file())


if __name__ == "__main__":
    unittest.main()
