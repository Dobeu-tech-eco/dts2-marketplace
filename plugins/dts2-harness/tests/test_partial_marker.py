"""Text contract: the turn-cap partial-output marker is defined and handled."""
from __future__ import annotations

import re
import unittest
from typing import Final

from helpers import PLUGIN_ROOT

MARKER: Final[str] = "PARTIAL: hit turn cap at <step>"
AGENT_NAMES: Final[tuple[str, ...]] = tuple(sorted(p.stem for p in (PLUGIN_ROOT / "agents").glob("*.md")))
DISPATCH_FILES: Final[tuple[str, ...]] = (
    "skills/run/phase-0-size.md",
    "skills/run/phase-1-plan.md",
    "skills/run/phase-2-build.md",
    "skills/run/phase-3-review.md",
    "skills/run/phase-4-ship.md",
    "skills/autopilot/SKILL.md",
    "skills/feature/SKILL.md",
    "skills/ship/SKILL.md",
    "skills/gtm/SKILL.md",
    "skills/setup/SKILL.md",
)


def _read(rel: str) -> str:
    return (PLUGIN_ROOT / rel).read_text(encoding="utf-8")


class PartialMarkerContract(unittest.TestCase):
    def test_every_agent_defines_marker(self) -> None:
        self.assertTrue(AGENT_NAMES)
        for name in AGENT_NAMES:
            with self.subTest(agent=name):
                text = _read(f"agents/{name}.md")
                self.assertIn(MARKER, text)
                self.assertIn("## Turn cap", text)
                self.assertIn("first line", text)

    def test_every_marker_spelling_is_exact(self) -> None:
        for path in sorted(PLUGIN_ROOT.rglob("*.md")):
            for found in re.findall(r"PARTIAL:[^`\n]*", path.read_text(encoding="utf-8")):
                with self.subTest(file=str(path.relative_to(PLUGIN_ROOT))):
                    self.assertEqual(found, MARKER)

    def test_every_dispatching_file_handles_marker(self) -> None:
        for rel in DISPATCH_FILES:
            with self.subTest(file=rel):
                self.assertIn(MARKER, _read(rel))

    def test_discipline_rule_handles_marker(self) -> None:
        text = _read("templates/discipline.md")
        self.assertIn(MARKER, text)
        self.assertIn("Partial output is not done", text)
        self.assertIn("re-dispatch", text)

    def test_ship_treats_marker_as_not_passed(self) -> None:
        text = _read("skills/ship/SKILL.md")
        self.assertIn(MARKER, text)
        self.assertIn("has not passed", text)

    def test_machine_prep_treats_marker_as_incomplete(self) -> None:
        text = _read("skills/machine-prep/SKILL.md")
        self.assertIn(MARKER, text)
        self.assertIn("incomplete", text)


if __name__ == "__main__":
    unittest.main()
