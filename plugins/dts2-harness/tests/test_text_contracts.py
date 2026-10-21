"""Text contracts for prompt and skill files: required phrases present, retired phrases absent.

Add one TestCase class per file under test. Each class mixes in TextContractMixin and calls
self.assert_contains(path, phrases) / self.assert_absent(path, phrases).
"""
from __future__ import annotations

import unittest
from pathlib import Path
from typing import Final, Sequence

from helpers import PLUGIN_ROOT

AGENTS: Final[Path] = PLUGIN_ROOT / "agents"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TextContractMixin(unittest.TestCase):
    """Base with phrase assertions; not collected on its own because it defines no tests."""

    def assert_contains(self, path: Path, phrases: Sequence[str]) -> None:
        text: str = _read(path)
        missing: list[str] = [p for p in phrases if p not in text]
        self.assertEqual(missing, [], f"{path.name} is missing required phrases")

    def assert_absent(self, path: Path, phrases: Sequence[str]) -> None:
        text: str = _read(path)
        present: list[str] = [p for p in phrases if p in text]
        self.assertEqual(present, [], f"{path.name} contains retired phrases")


class LeadAgentTests(TextContractMixin):
    PATH: Final[Path] = AGENTS / "lead.md"

    def test_required_phrases(self) -> None:
        self.assert_contains(self.PATH, [
            "## Done", "Axes", "Skills table", "separate file sets", "### Builder 1",
            ".harness/end-state.md", ".harness/discipline.md", "roster.py", "coexist",
            "Team: <n> builders on separate file sets",
        ])

    def test_retired_phrases(self) -> None:
        self.assert_absent(self.PATH, ["Lane A", "Lane", "lane", "worktree", "Tier/Lanes"])


class ReviewerAgentTests(TextContractMixin):
    PATH: Final[Path] = AGENTS / "reviewer.md"

    def test_required_phrases(self) -> None:
        self.assert_contains(self.PATH, [
            "#### Preserve", "#### Fix", "#### Open questions", "0–4", "Never write fixes",
            "critique", "walkthrough-findings", "### Priorities", ".harness/review/screens/",
            "Impeccable critique report path", ".harness/review/critique-<stamp>.md",
            "The caller supplies the run stamp", "date +%Y%m%d-%H%M%S",
            "npm audit --json", "pip-audit --format json", "Issue / Impact / Evidence / Fix / Priority",
        ])


class VerifierAgentTests(TextContractMixin):
    PATH: Final[Path] = AGENTS / "verifier.md"

    def test_required_phrases(self) -> None:
        self.assert_contains(self.PATH, [
            "Walkthrough", ".harness/review/screens/", "no browser available", "dev_server",
            "ready_pattern", "python3 -m playwright", "npx playwright",
            "Walkthrough | SKIP | no browser available",
            "The caller supplies the run stamp", "date +%Y%m%d-%H%M%S",
        ])

    def test_inherits_all_tools(self) -> None:
        self.assert_absent(self.PATH, ["tools:"])


class ScoutAgentTests(TextContractMixin):
    PATH: Final[Path] = AGENTS / "scout.md"

    def test_retired_phrases(self) -> None:
        self.assert_absent(self.PATH, ["Worktrees:"])

    def test_required_phrases(self) -> None:
        self.assert_contains(self.PATH, [
            "Harnesses:", "Marketing surface:", ".omc", ".flow", ".beads", ".conductor",
            ".agent", ".impeccable", ".agents", "AGENTS.md", "CLAUDE.md",
        ])


if __name__ == "__main__":
    unittest.main()
