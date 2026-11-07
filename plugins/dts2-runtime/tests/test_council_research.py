"""council.py: the ask-expert-only DECISION: RESEARCH."""
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, make_tmp_home

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "council.py"
BRIEF: Final[str] = "## Head of council brief\nThe panel split on market size.\n\n## History considered\nEntries reviewed: 4\n"
RESEARCH_BRIEF: Final[str] = "\n## Research brief\n- How big is the template market?\n- Who are the direct competitors?\n"


def council(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["python3", "-I", str(SCRIPT), *args], capture_output=True, text=True, check=False, cwd=str(PLUGIN_ROOT))


class ResearchDecisionCase(unittest.TestCase):
    def setUp(self) -> None:
        self.dir: Path = make_tmp_home()
        self.tally: Path = self.dir / "tally.json"
        self.tally.write_text(json.dumps({"dissenters": []}), encoding="utf-8")

    def decision(self, text: str) -> Path:
        path: Path = self.dir / "decision.md"
        path.write_text(text, encoding="utf-8")
        return path

    def check(self, text: str, *flags: str) -> dict[str, Any]:
        done = council("check-decision", str(self.decision(text)), "--tally", str(self.tally), "--entries", "4", *flags)
        return json.loads(done.stdout)

    def test_rejected_without_flag(self) -> None:
        out = self.check("DECISION: RESEARCH\n\n" + BRIEF + RESEARCH_BRIEF)
        self.assertFalse(out["ok"])
        self.assertIsNone(out["decision"])
        self.assertIn("first line is not 'DECISION: APPROVE|FIX|STRIKE'", out["problems"])

    def test_accepted_with_flag_and_brief(self) -> None:
        out = self.check("DECISION: RESEARCH\n\n" + BRIEF + RESEARCH_BRIEF, "--allow-research")
        self.assertEqual((out["ok"], out["decision"], out["problems"]), (True, "RESEARCH", []))

    def test_rejected_with_empty_or_missing_brief(self) -> None:
        for extra in ("", "\n## Research brief\n\n", "\n## Research brief\n"):
            out = self.check("DECISION: RESEARCH\n\n" + BRIEF + extra, "--allow-research")
            self.assertFalse(out["ok"], repr(extra))
            self.assertTrue(any("Research brief" in p for p in out["problems"]))

    def test_flag_does_not_change_other_decisions(self) -> None:
        fix = "DECISION: FIX\n\n" + BRIEF + "\n## Fixes\n- do it\n"
        self.assertEqual(self.check(fix), self.check(fix, "--allow-research"))
        self.assertTrue(self.check(fix)["ok"])

    def test_route_rejects_research_without_flag(self) -> None:
        ledger: Path = self.dir / "ledger.jsonl"
        ledger.write_text("", encoding="utf-8")
        done = council("route", "--ledger", str(ledger), "--decision", "RESEARCH")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("invalid choice", done.stderr)

    def test_route_research_with_flag(self) -> None:
        ledger: Path = self.dir / "ledger.jsonl"
        ledger.write_text("", encoding="utf-8")
        out = json.loads(council("route", "--ledger", str(ledger), "--decision", "RESEARCH", "--allow-research").stdout)
        self.assertEqual(out["action"], "research", out)
        self.assertTrue(out["ok"])


if __name__ == "__main__":
    unittest.main()
