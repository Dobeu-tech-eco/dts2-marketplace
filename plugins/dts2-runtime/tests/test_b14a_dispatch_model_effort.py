"""AA-8: every dispatch instruction names a model and an effort; mechanical work dispatches the builder on haiku/low."""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT

DISPATCH: Final[re.Pattern[str]] = re.compile(r"\b[Dd]ispatch(?:es|ed|ing)?\b")
AGENT_OBJECT: Final[re.Pattern[str]] = re.compile(r"\b(?:builders?|lead|reviewers?|verifier|scout)\b|dt:")
MODEL: Final[re.Pattern[str]] = re.compile(r"\bmodel\b", re.IGNORECASE)
EFFORT: Final[re.Pattern[str]] = re.compile(r"\beffort\b", re.IGNORECASE)
# Files owned by other workers in batch 14. Their dispatch lines are the follow-up to bring to model + effort;
# skills/autopilot is excluded for the same reason. Remove a name here when its file is fixed.
FOLLOW_UP: Final[frozenset[str]] = frozenset({
    "SKILL.md", "operations.md", "phase-0-size.md", "phase-3-review.md", "phase-4-ship.md",
})


def dispatch_files() -> list[Path]:
    return sorted((PLUGIN_ROOT / "skills" / "run").glob("*.md")) + sorted((PLUGIN_ROOT / "agents").glob("*.md"))


def dispatch_lines(path: Path) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.startswith("#"):
            continue
        if DISPATCH.search(line) and AGENT_OBJECT.search(line):
            found.append((number, line))
    return found


class DispatchNamesModelAndEffortTests(unittest.TestCase):
    def test_every_dispatch_instruction_names_model_and_effort(self) -> None:
        missing: list[str] = []
        checked: int = 0
        for path in dispatch_files():
            if path.name in FOLLOW_UP:
                continue
            for number, line in dispatch_lines(path):
                checked += 1
                if not (MODEL.search(line) and EFFORT.search(line)):
                    missing.append(f"{path.name}:{number}: {line[:100]}")
        self.assertGreater(checked, 4)
        self.assertEqual(missing, [])

    def test_follow_up_files_exist(self) -> None:
        for name in FOLLOW_UP:
            self.assertTrue((PLUGIN_ROOT / "skills" / "run" / name).exists(), name)

    def test_autopilot_is_not_scanned(self) -> None:
        self.assertNotIn("autopilot", {p.parent.name for p in dispatch_files()})


class MechanicalDispatchTests(unittest.TestCase):
    def test_mechanical_and_phase4_text_use_haiku_low_builder(self) -> None:
        text = (PLUGIN_ROOT / "skills" / "run" / "phase-2-build.md").read_text(encoding="utf-8")
        line = next(ln for ln in text.splitlines() if ln.startswith("**Mechanical dispatches"))
        for needle in ("`complexity: mechanical`", "notes", "PR body", "dt:builder", "model: haiku", "effort: low"):
            self.assertIn(needle, line)
        self.assertIn("no new agent", line.lower())

    def test_no_scribe_agent_was_added(self) -> None:
        names = sorted(p.stem for p in (PLUGIN_ROOT / "agents").glob("*.md"))
        self.assertEqual(names, ["auditor", "builder", "fixer", "incident-reviewer", "lead", "reviewer", "scout", "verifier"])


if __name__ == "__main__":
    unittest.main()
