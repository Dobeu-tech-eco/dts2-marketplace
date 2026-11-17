"""D62: the two gate-seat failures. A seat that puts words before its `VOTE:` line (grok), and a seat that ends with no vote
after a headless shell-permission denial (gemini). The answers live in tests/fixtures/ballots (see its README: the originals
were not available, so those are reconstructions and simulations). No real agent CLI runs here."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
FIXTURES: Final[Path] = Path(__file__).resolve().parent / "fixtures" / "ballots"
sys.path.insert(0, str(SCRIPTS))
import ballot_dispatch  # noqa: E402
import contracts  # noqa: E402
import council  # noqa: E402
import roster  # noqa: E402

EXPECTED: Final[dict[str, str | None]] = {"approve": "APPROVE", "reject": "REJECT", "none": None}
SEAT_SCRIPT: Final[str] = "import sys\nsys.stdin.read()\nsys.stdout.write(open(sys.argv[1], encoding='utf-8').read())\n"


def cases() -> list[tuple[str, str, str | None]]:
    """(case name, the seat's raw answer, the verdict recover_ballot must find or None) for every fixture file."""
    found: list[tuple[str, str, str | None]] = []
    for path in sorted(FIXTURES.glob("*.txt")):
        if path.name == "README.txt":
            continue
        case, expect = path.stem.rsplit(".", 1)
        found.append((case, path.read_bytes().decode("utf-8").replace("\r\n", "\n"), EXPECTED[expect]))
    return found


class RecoverBallotTests(unittest.TestCase):
    def test_every_fixture_reads_as_its_name_says(self) -> None:
        self.assertGreaterEqual(len(cases()), 8)
        for case, raw, expect in cases():
            recovered = contracts.recover_ballot(raw)
            if expect is None:
                self.assertIsNone(recovered, case)
                continue
            self.assertIsNotNone(recovered, case)
            parsed = contracts.parse_ballot(str(recovered), "seat")
            self.assertIsInstance(parsed, contracts.Ballot, case)
            self.assertEqual(parsed.vote, expect, case)

    def test_the_preamble_is_kept_as_the_seats_reasons(self) -> None:
        raw = dict((c, r) for c, r, _ in cases())["reconstructed-grok-preamble-inline"]
        parsed = contracts.parse_ballot(str(contracts.recover_ballot(raw)), "seat")
        self.assertIn("Reviewed the diff and the verifier table", parsed.reasons)
        self.assertIn("HIGH scripts/queue.py:41", parsed.reasons)

    def test_the_tally_itself_stays_strict(self) -> None:
        """Recovery is the dispatcher's job: a preamble ballot dropped straight into the tally is still no vote."""
        for case in ("reconstructed-grok-preamble-inline", "reconstructed-grok-preamble-lines"):
            raw = dict((c, r) for c, r, _ in cases())[case]
            self.assertIsInstance(contracts.parse_ballot(raw, "seat"), contracts.Invalid, case)
        self.assertIsInstance(contracts.parse_ballot("Sure! VOTE: APPROVE\n", "seat"), contracts.Invalid)

    def test_a_verdict_far_down_or_a_second_verdict_is_not_recovered(self) -> None:
        late = "a\nb\nc\nd\ne\nVOTE: APPROVE\n"
        self.assertIsNone(contracts.recover_ballot(late))
        self.assertIsNone(contracts.recover_ballot("VOTE: APPROVE\nfine\nVOTE: REJECT\n"))
        self.assertIsNone(contracts.recover_ballot("note VOTE: APPROVE\nand also VOTE: REJECT\n"))
        self.assertEqual(contracts.recover_ballot("VOTE: APPROVE\nfine\n"), "VOTE: APPROVE\nfine\n")

    def test_unable_line_is_read_only_on_the_first_line(self) -> None:
        self.assertEqual(contracts.seat_unable("UNABLE: no shell\n"), "no shell")
        self.assertIsNone(contracts.seat_unable("VOTE: APPROVE\nUNABLE: x\n"))
        self.assertIsNone(contracts.seat_unable(""))


class DispatchTests(unittest.TestCase):
    """The council path: ballot_dispatch.dispatch_seat with a fake seat CLI that prints a fixture."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="dts2-d62-"))
        self.script = self.folder / "seat.py"
        self.script.write_text(SEAT_SCRIPT, encoding="utf-8")

    def run_seat(self, case: str, seat: str = "s1") -> dict[str, Any]:
        fixture = FIXTURES / next(p.name for p in FIXTURES.glob(f"{case}.*.txt"))
        argv = [sys.executable, str(self.script), str(fixture)]
        return ballot_dispatch.dispatch_seat(seat, argv, "m", "the ballot prompt", self.folder / "out", False, self.folder)

    def test_a_grok_preamble_ballot_dispatches_as_a_strict_counted_ballot(self) -> None:
        for case in ("reconstructed-grok-preamble-inline", "reconstructed-grok-preamble-lines"):
            result = self.run_seat(case, seat=case.rsplit("-", 1)[1])
            self.assertTrue(result["ok"], result)
            self.assertTrue(result["normalized"])
            ballot = Path(result["ballot"])
            self.assertEqual(ballot.read_text(encoding="utf-8").splitlines()[0], "VOTE: REJECT")
            self.assertIsNone(ballot_dispatch.provenance_problem(ballot))
            self.assertEqual(council.read_ballot(ballot)["vote"], "REJECT")
            record = json.loads(ballot_dispatch.record_path(ballot).read_text(encoding="utf-8"))
            raw = ballot.with_name(ballot.name + ballot_dispatch.RAW_SUFFIX).read_text(encoding="utf-8")
            self.assertEqual(record["raw_sha256"], ballot_dispatch.sha256_text(raw))

    def test_a_strict_ballot_is_not_rewritten(self) -> None:
        result = self.run_seat("strict")
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["normalized"])
        self.assertFalse(Path(result["ballot"]).with_name("s1.md" + ballot_dispatch.RAW_SUFFIX).exists())

    def test_gemini_shapes_without_a_vote_are_surfaced_never_silent(self) -> None:
        expect = {"synthetic-gemini-silent": "no-vote", "synthetic-gemini-denial-text": "no-vote",
                  "synthetic-gemini-unable": "unable", "echoed-instruction": "no-vote"}
        for case, outcome in expect.items():
            result = self.run_seat(case)
            self.assertFalse(result["ok"], case)
            self.assertEqual(result["outcome"], outcome, case)
            self.assertTrue(result["reason"], case)
            self.assertFalse((self.folder / "out" / "s1.md").exists(), case)
        denial = self.run_seat("synthetic-gemini-denial-text")
        self.assertIn("denied", denial["excerpt"])
        self.assertIn("shell access was denied", self.run_seat("synthetic-gemini-unable")["reason"])

    def test_a_seat_that_exits_non_zero_after_a_denial_says_why(self) -> None:
        script = self.folder / "dies.py"
        script.write_text("import sys\nsys.stdin.read()\nsys.stderr.write('command permission denied (headless)\\n')\nsys.exit(1)\n",
                          encoding="utf-8")
        result = ballot_dispatch.dispatch_seat("s9", [sys.executable, str(script)], "m", "p", self.folder / "out", False, self.folder)
        self.assertEqual((result["ok"], result["outcome"]), (False, "failed"))
        self.assertIn("exited 1", result["reason"])
        self.assertIn("permission denied", result["excerpt"])


class ClassifyBallotTests(unittest.TestCase):
    """The gate path: `roster.py classify --ballot <voter output file>` on what `lanes.py call --out` saved."""

    def classify(self, raw: str, exit_code: int = 0, agent: str = "gemini") -> tuple[dict[str, Any], Path]:
        folder = Path(tempfile.mkdtemp(prefix="dts2-d62c-"))
        ballot = folder / "vote.md"
        ballot.write_text(raw, encoding="utf-8")
        done = subprocess.run(
            [sys.executable, "-I", str(SCRIPTS / "roster.py"), "classify", "--agent", agent, "--role", "second-opinion",
             "--exit-code", str(exit_code), "--ballot", str(ballot)],
            input=raw, capture_output=True, text=True, check=False, encoding="utf-8")
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout), ballot

    def test_grok_preamble_is_recovered_and_the_file_rewritten_strict(self) -> None:
        raw = dict((c, r) for c, r, _ in cases())["reconstructed-grok-preamble-inline"]
        result, ballot = self.classify(raw, agent="grok")
        self.assertEqual((result["outcome"], result["vote"], result["normalized"], result["seatFailed"]), ("ok", "REJECT", True, False))
        self.assertEqual(ballot.read_text(encoding="utf-8").splitlines()[0], "VOTE: REJECT")
        self.assertEqual(ballot.with_name("vote.md" + roster.BALLOT_RAW_SUFFIX).read_text(encoding="utf-8"), raw)

    def test_gemini_exit_zero_with_no_vote_is_a_failed_seat_with_a_reason(self) -> None:
        expect = {"synthetic-gemini-silent": "no-vote", "synthetic-gemini-denial-text": "no-vote",
                  "synthetic-gemini-unable": "unable"}
        raws = dict((c, r) for c, r, _ in cases())
        for case, outcome in expect.items():
            result, ballot = self.classify(raws[case])
            self.assertEqual((result["outcome"], result["seatFailed"]), (outcome, True), case)
            self.assertTrue(result["reason"] and result["excerpt"], case)
            self.assertEqual(ballot.read_text(encoding="utf-8"), raws[case], case)  # the voter's own file is never touched
        self.assertIn("denied", self.classify(raws["synthetic-gemini-denial-text"])[0]["excerpt"])

    def test_without_ballot_an_empty_answer_still_classifies_ok(self) -> None:
        """Only gate voters pass --ballot: a second opinion that carries no VOTE: line is not a failed seat."""
        self.assertEqual(roster.classify_dispatch("gemini", "second-opinion", "", 0)["outcome"], "ok")

    def test_a_failed_dispatch_keeps_its_own_classification(self) -> None:
        result, _ = self.classify("", exit_code=1)
        self.assertEqual((result["outcome"], result["seatFailed"]), ("failed", True))


class SeatContractTests(unittest.TestCase):
    def command(self, agent: str, role: str) -> list[str]:
        prompt = Path(tempfile.mkdtemp(prefix="dts2-d62p-")) / "ballot.md"
        prompt.write_text("x", encoding="utf-8")
        return roster.resolve_command(roster.load_profiles()[agent], role, "frontier", prompt_file=prompt)["argv"]

    def test_the_gemini_gate_seat_is_told_to_run_no_command_and_how_to_say_it_cannot(self) -> None:
        argv = self.command("gemini", "second-opinion")
        pointer = argv[argv.index("-p") + 1]
        self.assertIn("run no shell command", pointer)
        self.assertIn("UNABLE:", pointer)
        self.assertTrue(pointer.startswith("Read the instructions in "))

    def test_other_roles_keep_the_plain_pointer(self) -> None:
        argv = self.command("gemini", "reviewer")
        self.assertNotIn("UNABLE", argv[argv.index("-p") + 1])


if __name__ == "__main__":
    unittest.main()
