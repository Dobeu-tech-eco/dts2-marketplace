"""Text contract: the turn-cap partial-output marker is defined and handled."""
from __future__ import annotations

import unittest
from typing import Final

from helpers import PLUGIN_ROOT

MARKER: Final[str] = "PARTIAL: hit turn cap at <step>"
AGENT_NAMES: Final[tuple[str, ...]] = ("auditor", "builder", "lead", "reviewer", "scout", "verifier")


def _read(rel: str) -> str:
    return (PLUGIN_ROOT / rel).read_text(encoding="utf-8")


class PartialMarkerContract(unittest.TestCase):
    def test_every_agent_defines_marker(self) -> None:
        for name in AGENT_NAMES:
            with self.subTest(agent=name):
                self.assertIn(MARKER, _read(f"agents/{name}.md"))

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
