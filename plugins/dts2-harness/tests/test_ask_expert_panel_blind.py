"""ask_expert.py panel: votes by blind option label, and verbatim plans and votes in the recorded council entries."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, make_tmp_home

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "ask_expert.py"
COUNCIL: Final[Path] = PLUGIN_ROOT / "scripts" / "council.py"
SEATS: Final[tuple[str, ...]] = ("a", "b", "c")
DISTINCT: Final[str] = "The salvage list is the quartz-lantern module only."
# Per voter: which plan stem sits behind each label.
KEY: Final[dict[str, dict[str, str]]] = {
    "a": {"A": "plan-b", "B": "plan-a", "C": "plan-c"},
    "b": {"A": "plan-c", "B": "plan-a", "C": "plan-b"},
    "c": {"A": "plan-c", "B": "plan-b", "C": "plan-a"},
}


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def run(script: Path, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["python3", "-I", str(script), *args], capture_output=True, text=True, check=False, cwd=str(cwd), env=dict(os.environ))


class BlindCase(unittest.TestCase):
    def setUp(self) -> None:
        self.dir: Path = make_tmp_home()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.plans: list[str] = [
            f"{s}={write(self.dir / 'round-1' / f'plan-{s}.md', f'VERDICT: ARCHIVE{chr(10)}{DISTINCT} ({s}){chr(10)}')}" for s in SEATS]
        self.key: Path = write(self.dir / "blind" / "blind-key.json", json.dumps({"seed": "s", "key": KEY}))

    def votes(self, per_seat: dict[str, str]) -> list[str]:
        return [f"{s}={write(self.dir / 'round-1' / f'vote-{s}.md', text + chr(10))}" for s, text in per_seat.items()]

    def tally(self, votes: list[str], key: Path | None, *extra: str) -> tuple[int, dict[str, Any]]:
        argv: list[str] = ["panel-tally", "--plans", *self.plans, "--votes", *votes]
        if key is not None:
            argv += ["--blind-key", str(key)]
        done = run(SCRIPT, *argv, *extra, cwd=self.dir)
        return done.returncode, json.loads(done.stdout)

    def good_votes(self) -> dict[str, str]:
        # Each voter's own option is the label that maps to its own plan; the other two are voted on.
        return {"a": "VOTE Option A: AGREE\nVOTE Option C: AGREE\n- finding", "b": "VOTE Option A: AGREE\nVOTE Option B: AGREE",
                "c": "VOTE Option B: AGREE\nVOTE Option C: AGREE"}

    def test_labels_translate_to_seats_and_pass(self) -> None:
        code, out = self.tally(self.votes(self.good_votes()), self.key)
        self.assertEqual((code, out["agree"], out["disagree"], out["selfVotesIgnored"], out["pass"]), (0, 6, 0, 0, True), out)

    def test_bare_letter_is_accepted(self) -> None:
        votes = self.good_votes()
        votes["a"] = "VOTE A: AGREE\nVOTE c: DISAGREE"
        code, out = self.tally(self.votes(votes), self.key)
        self.assertEqual((code, out["disagree"], out["pass"]), (0, 1, False), out)

    def test_vote_on_own_option_is_ignored_and_counted(self) -> None:
        votes = self.good_votes()
        votes["a"] += "\nVOTE Option B: DISAGREE"  # B is plan-a on voter a's ballot
        code, out = self.tally(self.votes(votes), self.key)
        self.assertEqual((code, out["selfVotesIgnored"], out["disagree"], out["pass"]), (0, 1, 0, True), out)

    def test_unknown_label_is_a_problem(self) -> None:
        votes = self.good_votes()
        votes["a"] = "VOTE Option A: AGREE\nVOTE Option Z: AGREE"
        code, out = self.tally(self.votes(votes), self.key)
        self.assertEqual(code, 2)
        self.assertFalse(out["ok"])

    def test_voter_missing_from_key_is_a_problem(self) -> None:
        short = write(self.dir / "blind" / "short.json", json.dumps({"seed": "s", "key": {s: KEY[s] for s in ("a", "b")}}))
        code, out = self.tally(self.votes(self.good_votes()), short)
        self.assertEqual(code, 2)
        self.assertFalse(out["ok"])
        self.assertTrue(any("'c'" in p for p in out["problems"]), out)

    def test_missing_other_option_is_a_problem(self) -> None:
        votes = self.good_votes()
        votes["b"] = "VOTE Option A: AGREE"
        self.assertEqual(self.tally(self.votes(votes), self.key)[0], 2)

    def test_seat_name_mode_unchanged_without_a_key(self) -> None:
        votes = {"a": "VOTE b: AGREE\nVOTE c: AGREE", "b": "VOTE a: AGREE\nVOTE c: AGREE", "c": "VOTE a: AGREE\nVOTE b: AGREE"}
        code, out = self.tally(self.votes(votes), None)
        self.assertEqual((code, out["agree"], out["selfVotesIgnored"], out["pass"]), (0, 6, 0, True), out)


class RecordCase(BlindCase):
    def record(self, number: int, folder: Path) -> dict[str, Any]:
        votes = self.good_votes()
        votes["a"] = "VOTE Option A: DISAGREE\nVOTE Option C: AGREE"
        code, out = self.tally(self.votes(votes), self.key, "--record", str(folder), "--round", str(number))
        self.assertEqual(code, 0, out)
        return out

    def test_entries_carry_verbatim_plan_and_votes(self) -> None:
        folder: Path = self.dir / "run"
        out = self.record(1, folder)
        self.assertEqual(len(out["recorded"]), 3)
        first: str = Path(out["recorded"][0]).read_text(encoding="utf-8")
        self.assertEqual(first.splitlines()[0], "VOTE: REJECT")
        self.assertIn("## Plan (verbatim)", first)
        self.assertIn(f"{DISTINCT} (a)", first)
        self.assertIn("## Cross-review votes (verbatim)", first)
        self.assertIn("VOTE Option A: DISAGREE", first)

    def test_entries_carry_each_voters_option_legend(self) -> None:
        out = self.record(1, self.dir / "run")
        first: str = Path(out["recorded"][0]).read_text(encoding="utf-8")
        self.assertIn("## Option labels on this ballot", first)
        self.assertIn("- Option A = plan of b", first)
        self.assertIn("- Option B = plan of a", first)
        self.assertIn("- Option C = plan of c", first)

    def test_dossier_includes_plan_text_and_council_still_eligible(self) -> None:
        folder: Path = self.dir / "run"
        for number in (1, 2, 3):
            self.record(number, folder)
        done = run(COUNCIL, "eligible", "--votes-dir", str(folder), cwd=self.dir)
        self.assertTrue(json.loads(done.stdout)["eligible"], done.stdout)
        dossier: Path = self.dir / "dossier.md"
        done = run(COUNCIL, "dossier", "--votes-dir", str(folder), "--out", str(dossier), cwd=self.dir)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        text: str = dossier.read_text(encoding="utf-8")
        self.assertIn(DISTINCT, text)
        self.assertIn("VOTE Option A: DISAGREE", text)


if __name__ == "__main__":
    unittest.main()
