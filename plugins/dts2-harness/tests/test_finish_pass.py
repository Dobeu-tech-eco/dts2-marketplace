"""Contracts for the code finish pass (Phase 3c) and the stack blueprint."""
from __future__ import annotations

import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT

LAYERS: Final[tuple[str, ...]] = (
    "data model", "api surface", "screens/routes", "auth",
    "infra/deploy", "observability", "background jobs",
)


def read(rel: str) -> str:
    path: Path = PLUGIN_ROOT / rel
    return path.read_text(encoding="utf-8")


class FinishPassTests(unittest.TestCase):
    def test_run_phase_3c_after_3b_before_4(self) -> None:
        text: str = read("skills/run/SKILL.md")
        positions: list[int] = [text.find(h) for h in ("## Phase 3b", "## Phase 3c", "## Phase 4")]
        self.assertNotIn(-1, positions)
        self.assertEqual(positions, sorted(positions))

    def test_run_phase_3c_rules(self) -> None:
        text: str = read("skills/run/SKILL.md")
        section: str = text[text.find("## Phase 3c"):text.find("## Phase 4")]
        for phrase in ("simplify", "optimize", "Coverage:", "3-round cap", "never speculative"):
            self.assertIn(phrase, section)

    def test_plan_checkpoint_blueprint_rule(self) -> None:
        text: str = read("skills/run/SKILL.md")
        for phrase in ("Blueprint coverage", "unmapped", "Blueprint layer <x> unmapped"):
            self.assertIn(phrase, text)

    def test_reviewer_axes(self) -> None:
        text: str = read("agents/reviewer.md")
        for phrase in ("`simplify`", "`optimize`", "never speculative"):
            self.assertIn(phrase, text)

    def test_verifier_coverage_line(self) -> None:
        text: str = read("agents/verifier.md")
        self.assertIn("Coverage: <file> (no test)", text)
        self.assertIn("Coverage: all changed files tested", text)

    def test_lead_blueprint_coverage(self) -> None:
        text: str = read("agents/lead.md")
        for phrase in ("## Blueprint coverage", "Builder N", "unchanged"):
            self.assertIn(phrase, text)

    def test_end_state_blueprint_layers(self) -> None:
        text: str = read("templates/end-state.md")
        self.assertIn("## Blueprint", text)
        self.assertIn("| layer | choice | status |", text)
        for layer in LAYERS:
            self.assertIn(f"| {layer} |", text)

    def test_setup_topology_records_blueprint(self) -> None:
        text: str = read("skills/setup/SKILL.md")
        round3: str = text[text.find("### Round 3"):text.find("### Round 4")]
        self.assertIn("## Blueprint", round3)
        for layer in LAYERS:
            self.assertIn(layer, round3)


if __name__ == "__main__":
    unittest.main()
