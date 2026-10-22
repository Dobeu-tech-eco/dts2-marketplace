"""Contracts for Rule 9 (orchestration) and Rule 10 (branches, worktrees, PRs)."""
from __future__ import annotations

import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT

DISCIPLINE: Final[Path] = PLUGIN_ROOT / "templates" / "discipline.md"
RUN_SKILL: Final[Path] = PLUGIN_ROOT / "skills" / "run" / "SKILL.md"
BUILDER: Final[Path] = PLUGIN_ROOT / "agents" / "builder.md"
LEAD: Final[Path] = PLUGIN_ROOT / "agents" / "lead.md"
LOCAL_TEMPLATE: Final[Path] = PLUGIN_ROOT / "templates" / "dts2-harness.local.md"
ONBOARD: Final[Path] = PLUGIN_ROOT / "skills" / "onboard" / "SKILL.md"
PERSONAL_STRINGS: Final[tuple[str, ...]] = (
    "Jeremy", "Neptune", "07753", "Composio", "Baldor", "Unique Staffing", "Dobeu Tech Solutions LLC",
)
# Prose and rule files only: profiles/blueprint.json names the third-party Composio plugin as data.
SUFFIXES: Final[frozenset[str]] = frozenset({".md"})


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class OrchestrationRulesTests(unittest.TestCase):
    def assert_contains(self, path: Path, phrases: list[str]) -> None:
        text: str = _read(path)
        for phrase in phrases:
            self.assertIn(phrase, text, f"{path.name} is missing: {phrase}")

    def test_discipline_rules(self) -> None:
        self.assert_contains(DISCIPLINE, [
            "Rule 9", "Rule 10", "Lead thinks, workers type", "Worker contract",
            "Ruling: <what> — <why> — <cost if wrong>", "review-pr", "git worktree remove",
        ])

    def test_run_skill_isolation_and_review_mode(self) -> None:
        self.assert_contains(RUN_SKILL, [
            "## Isolation (Rule 10)", "dts2/<stamp>/b<n>", ".harness/wt/<n>/",
            "## review-pr mode", "gh pr checkout", "one tier up",
            "Every dispatch names a model AND an effort (Rule 9.2).",
        ])

    def test_agents_and_template(self) -> None:
        self.assert_contains(BUILDER, ["Worker contract"])
        self.assert_contains(LEAD, ["Rules: follow .harness/discipline.md"])
        self.assert_contains(LOCAL_TEMPLATE, ["one worktree per builder"])
        self.assert_contains(ONBOARD, ["review-pr"])

    def test_no_person_specific_content(self) -> None:
        for path in PLUGIN_ROOT.rglob("*"):
            if not path.is_file() or path.suffix not in SUFFIXES or path.name == Path(__file__).name:
                continue
            text: str = path.read_text(encoding="utf-8", errors="ignore")
            for needle in PERSONAL_STRINGS:
                self.assertNotIn(needle, text, f"{path} contains {needle}")


if __name__ == "__main__":
    unittest.main()
