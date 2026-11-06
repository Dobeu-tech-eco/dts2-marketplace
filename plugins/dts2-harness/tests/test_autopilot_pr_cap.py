"""Autopilot open-PR cap and end-of-run pr-sweep are written into the phase files."""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT

DIR: Final[Path] = PLUGIN_ROOT / "skills" / "autopilot"
SWEEP: Final[str] = "/dts2:pr-sweep --run <stamp>"


def _read(name: str) -> str:
    return (DIR / name).read_text(encoding="utf-8")


class AutopilotPrCapTests(unittest.TestCase):
    def test_cap_and_mid_run_sweep(self) -> None:
        text = _read("phase-0-preflight.md") + _read("phase-2-step.md")
        self.assertIn("open_pr_cap", text)
        self.assertIn(SWEEP, text)

    def test_end_of_run_sweep(self) -> None:
        self.assertIn(SWEEP, _read("phase-4-report.md"))

    def test_skill_guardrail(self) -> None:
        self.assertIn("open_pr_cap", _read("SKILL.md"))

    def test_never_auto_merge(self) -> None:
        for path in sorted(DIR.glob("*.md")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if re.search(r"--auto\b", line):
                    self.assertRegex(line, r"(?i)\bnever\b", f"{path.name}: {line[:80]}")
            self.assertNotRegex(path.read_text(encoding="utf-8"), r"gh pr merge[^\n`]*--auto")


if __name__ == "__main__":
    unittest.main()
