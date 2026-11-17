"""D62 replay: one build-vote panel round of the lane-d30 shape, driven through the real gate chain (`lanes.py call` for each
non-Claude voter, then `roster.py classify`, then the vote round count) with fake seat CLIs that print the recorded-or-
reconstructed answers in tests/fixtures/ballots. Two legs: the gate as it was (no `--ballot`) and the gate as it is now.

What this does not prove: no real `agy` or `grok` runs, and the answers are reconstructions (see the fixtures README), so the
replay shows the gate handles those shapes, not that the live seats now produce a vote."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any, Final

import test_supervisor as base
from helpers import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import council  # noqa: E402
import roster  # noqa: E402

FIXTURES: Final[Path] = Path(__file__).resolve().parent / "fixtures" / "ballots"
LANE: Final[Path] = FIXTURES / "lane-d30"
STAMP: Final[str] = base.STAMP
STEP: Final[str] = "d30"
SEAT_STUB: Final[str] = "import sys\nsys.stdin.read()\nsys.stdout.buffer.write(open(sys.argv[1], 'rb').read())\n"


class Lane30ReplayTests(base.SupervisorBase):
    def setUp(self) -> None:
        super().setUp()
        self.assertTrue(self.preflight()["ok"])
        (self.root / "seat.py").write_text(SEAT_STUB, encoding="utf-8")
        self.prompt = self.runs / "prompts" / f"vote-{STEP}-build.md"
        self.prompt.parent.mkdir(parents=True)
        self.prompt.write_bytes((LANE / "ballot-prompt.txt").read_bytes())
        self.votes = self.runs / "votes" / STEP
        self.votes.mkdir(parents=True)

    def seat(self, label: str, answer: Path, agent: str, ballot: bool) -> dict[str, Any]:
        """One non-Claude voter, exactly as phase-1-gate.md step 2 runs it. Returns the classification plus the saved file."""
        out = self.runs / "votes-raw" / f"{label}.md"
        out.parent.mkdir(exist_ok=True)
        called = self.lanes("call", STAMP, "--label", label, "--cost-source", "none", "--out", str(out),
                            "--prompt-file", str(self.prompt), "--", sys.executable, str(self.root / "seat.py"), str(answer))
        self.assertTrue(called["ok"], called)
        flags = ["--ballot", str(out)] if ballot else []
        done = subprocess.run([sys.executable, "-I", str(PLUGIN_ROOT / "scripts" / "roster.py"), "classify", "--agent", agent,
                               "--role", "second-opinion", "--exit-code", str(called["code"]), *flags],
                              input=out.read_bytes(), capture_output=True, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        return {**json.loads(done.stdout), "file": out}

    def save(self, order: int, seat: str, text: str) -> None:
        (self.votes / f"{order:02d}-build-r1-{seat}.md").write_text(text, encoding="utf-8", newline="\n")

    def round(self, grok: str, gemini: str, ballot: bool) -> dict[str, Any]:
        """Claude (Agent-tool voter, strict), grok, gemini; a seat the classifier fails is replaced once by codex."""
        self.save(1, "claude", (LANE / "claude.txt").read_text(encoding="utf-8"))
        seen: dict[str, Any] = {}
        for order, (seat, answer) in enumerate((("grok", FIXTURES / grok), ("gemini", FIXTURES / gemini)), start=2):
            result = self.seat(seat, answer, seat, ballot)
            seen[seat] = {k: v for k, v in result.items() if k != "file"}
            if result["seatFailed"] or result["outcome"] != "ok":
                result = self.seat("codex", LANE / "codex.txt", "codex", ballot)
                seen[seat]["replacedBy"] = "codex"
                self.save(order, "codex", result["file"].read_text(encoding="utf-8"))
            else:
                self.save(order, seat, result["file"].read_text(encoding="utf-8"))
        held = council.round_outcomes(self.votes)
        return {"seats": seen, "round": held[0] if held else None}

    def test_the_gate_as_it_was_never_completes_the_round(self) -> None:
        """Without --ballot: the grok preamble is no vote and the silent gemini seat classifies `ok`."""
        out = self.round("reconstructed-grok-preamble-inline.reject.txt", "synthetic-gemini-silent.none.txt", ballot=False)
        self.assertEqual(out["seats"]["gemini"]["outcome"], "ok")  # the silence: a seat with no answer passes the classifier
        self.assertEqual(out["round"]["votes"], ["APPROVE"])
        self.assertFalse(out["round"]["complete"])

    def test_the_gate_now_counts_the_recovered_grok_vote_and_replaces_the_silent_gemini_seat(self) -> None:
        out = self.round("reconstructed-grok-preamble-inline.reject.txt", "synthetic-gemini-silent.none.txt", ballot=True)
        self.assertEqual((out["seats"]["grok"]["outcome"], out["seats"]["grok"]["vote"], out["seats"]["grok"]["normalized"]),
                         ("ok", "REJECT", True))
        self.assertEqual((out["seats"]["gemini"]["outcome"], out["seats"]["gemini"]["seatFailed"]), ("no-vote", True))
        self.assertEqual(out["seats"]["gemini"]["replacedBy"], "codex")
        self.assertEqual(out["round"]["votes"], ["APPROVE", "REJECT", "APPROVE"])
        self.assertTrue(out["round"]["complete"])

    def test_every_failing_shape_completes_the_round_now(self) -> None:
        grok = ("reconstructed-grok-preamble-inline.reject.txt", "reconstructed-grok-preamble-lines.reject.txt")
        gemini = ("synthetic-gemini-silent.none.txt", "synthetic-gemini-denial-text.none.txt", "synthetic-gemini-unable.none.txt")
        for g in grok:
            for m in gemini:
                for stale in self.votes.glob("*.md"):
                    stale.unlink()
                out = self.round(g, m, ballot=True)
                self.assertTrue(out["round"]["complete"], (g, m, out))
                self.assertTrue(out["seats"]["gemini"]["seatFailed"], (g, m))
                self.assertTrue(out["seats"]["gemini"]["reason"] and out["seats"]["gemini"]["excerpt"], (g, m))

    def test_the_seat_invocations_replayed(self) -> None:
        """Part (a), the invocation: the argv a gate seat gets for this ballot file. Not a live run."""
        gem = roster.resolve_command(roster.load_profiles()["gemini"], "second-opinion", "frontier", prompt_file=self.prompt)["argv"]
        pointer = gem[gem.index("-p") + 1]
        self.assertIn("run no shell command", pointer)
        self.assertIn("UNABLE:", pointer)
        self.assertIn(str(self.prompt.resolve()), pointer)
        grok = roster.resolve_command(roster.load_profiles()["grok"], "second-opinion", "frontier", prompt_file=self.prompt)["argv"]
        self.assertEqual(grok[grok.index("--prompt-file") + 1], str(self.prompt.resolve()))


if __name__ == "__main__":
    unittest.main()
