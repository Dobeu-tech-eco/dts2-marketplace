"""Property tests for the council tally (scripts/council.py tally), read-only use as a black box.

Skipped unless hypothesis is importable (pip install -r requirements-dev.txt)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

try:
    from hypothesis import HealthCheck, given, settings
    from hypothesis import strategies as st
    HAVE_HYPOTHESIS = True
except ImportError:  # pragma: no cover - depends on the environment
    HAVE_HYPOTHESIS = False

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "council.py"
SEATS: Final[int] = 5
BRIEF: Final[str] = "\n## Dissent brief\nThe race in queue.ts needs a lock.\n"
MAX_EXAMPLES: Final[int] = 40

if HAVE_HYPOTHESIS:
    # each ballot: (vote, has a dissent brief); a vote of None is a ballot with no valid first line
    BALLOT = st.tuples(st.sampled_from(["APPROVE", "REJECT", None]), st.booleans())
    BALLOTS = st.lists(BALLOT, min_size=1, max_size=7)


def tally(ballots: list[tuple[str | None, bool]]) -> dict[str, Any]:
    folder = Path(tempfile.mkdtemp(prefix="dts2-hyp-council-"))
    paths: list[str] = []
    for index, (vote, brief) in enumerate(ballots):
        head = f"VOTE: {vote}\n" if vote else "no vote line here\n"
        path = folder / f"seat{index}.md"
        path.write_text(head + "- HIGH a.ts:1 — x — y\n" + (BRIEF if brief else ""), encoding="utf-8")
        paths.append(str(path))
    done = subprocess.run([sys.executable, "-I", str(SCRIPT), "tally", *paths], capture_output=True, text=True,
                          check=True)
    parsed: dict[str, Any] = json.loads(done.stdout)
    return parsed


if HAVE_HYPOTHESIS:
    class CouncilTallyProperties(unittest.TestCase):
        @settings(max_examples=MAX_EXAMPLES, deadline=None, suppress_health_check=list(HealthCheck))
        @given(BALLOTS)
        def test_tally_matches_the_model(self, ballots: list[tuple[str | None, bool]]) -> None:
            result = tally(ballots)
            valid = [(i, v, b) for i, (v, b) in enumerate(ballots) if v]
            approve = sum(1 for _, v, _ in valid if v == "APPROVE")
            reject = len(valid) - approve
            majority = "APPROVE" if approve > reject else "REJECT"
            dissenters = [f"seat{i}" for i, v, _ in valid if v != majority]
            missing = [f"seat{i}" for i, v, b in valid if v != majority and not b]
            self.assertEqual((result["approve"], result["reject"]), (approve, reject))
            self.assertEqual(result["approve"] + result["reject"], len(valid))
            self.assertEqual(result["majority"], majority)
            self.assertEqual(result["dissenters"], dissenters)
            self.assertEqual(result["unanimous"], not dissenters)
            self.assertEqual(result["missingBrief"], missing)
            self.assertEqual(result["invalid"], [f"seat{i}" for i, (v, _) in enumerate(ballots) if not v])
            self.assertEqual(result["ok"], len(valid) == SEATS and not missing)
            self.assertEqual(bool(result["problems"]), not result["ok"])

        @settings(max_examples=MAX_EXAMPLES, deadline=None, suppress_health_check=list(HealthCheck))
        @given(st.lists(BALLOT, min_size=SEATS, max_size=SEATS), st.randoms(use_true_random=False))
        def test_counts_ignore_ballot_order(self, ballots: list[tuple[str | None, bool]], rng: Any) -> None:
            shuffled = list(ballots)
            rng.shuffle(shuffled)
            first, second = tally(ballots), tally(shuffled)
            for key in ("approve", "reject", "majority", "unanimous"):
                self.assertEqual(first[key], second[key])
            self.assertEqual(len(first["dissenters"]), len(second["dissenters"]))

        @settings(max_examples=MAX_EXAMPLES, deadline=None, suppress_health_check=list(HealthCheck))
        @given(st.sampled_from(["APPROVE", "REJECT"]))
        def test_unanimous_five_needs_no_briefs(self, vote: str) -> None:
            result = tally([(vote, False)] * SEATS)
            self.assertTrue(result["ok"])
            self.assertTrue(result["unanimous"])
            self.assertEqual(result["majority"], vote)

else:

    @unittest.skip("hypothesis is not installed; see requirements-dev.txt")
    class CouncilTallyProperties(unittest.TestCase):
        def test_requires_hypothesis(self) -> None:
            pass


if __name__ == "__main__":
    unittest.main()
