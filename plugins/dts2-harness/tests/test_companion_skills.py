"""Companion skills from mattpocock/skills (3.4.0): discipline, setup, run, lead, keep template."""
from __future__ import annotations

import unittest
from typing import Final

from helpers import PLUGIN_ROOT

INSTALL_PATTERN: Final[str] = "`npx skills add https://github.com/mattpocock/skills --skill <name>`"
SKILLS: Final[tuple[str, ...]] = (
    "grill-me", "improve-codebase-architecture", "writing-for-agents",
    "pr", "resolving-merge-conflicts", "ask-matt", "research", "diagnosing-bugs",
)
SETUP_PHRASES: Final[tuple[str, ...]] = (
    "4c. Grill the draft", "5b. Architecture pass", "5c. Agent-friendly rewrite",
    "/grill-me", "/improve-codebase-architecture", "/writing-for-agents",
    "Apply these architecture amendments?", ".harness/plan-style.md",
    "## Questions from the user", "/ask-matt", "/research",
)
RUN_PHRASES: Final[tuple[str, ...]] = (
    "/pr", "/resolving-merge-conflicts", "PR body written by /pr",
    "## Questions from the user", "/ask-matt", "/research", "/diagnosing-bugs",
)


def read(relative: str) -> str:
    return (PLUGIN_ROOT / relative).read_text(encoding="utf-8")


class CompanionSkills(unittest.TestCase):
    def test_discipline_defines_pattern_once_and_lists_skills(self) -> None:
        text: str = read("templates/discipline.md")
        self.assertEqual(text.count(INSTALL_PATTERN), 1)
        self.assertIn("## Companion skills", text)
        for name in SKILLS:
            self.assertIn(f"`{name}`", text)
        for slash in ("/ask-matt", "/research", "/diagnosing-bugs"):
            self.assertIn(slash, text)

    def test_setup_phrases(self) -> None:
        text: str = read("skills/setup/SKILL.md")
        for phrase in SETUP_PHRASES:
            self.assertIn(phrase, text)

    def test_run_phrases(self) -> None:
        text: str = read("skills/run/SKILL.md")
        for phrase in RUN_PHRASES:
            self.assertIn(phrase, text)

    def test_lead_reads_plan_style(self) -> None:
        self.assertIn("plan-style.md", read("agents/lead.md"))

    def test_keep_template_examples(self) -> None:
        text: str = read("templates/keep.yaml")
        for name in SKILLS:
            self.assertIn(f"--skill {name}", text)

    def test_onboard_mentions_companions(self) -> None:
        self.assertIn("mattpocock/skills", read("skills/onboard/SKILL.md"))

    def test_no_personal_names_in_plugin(self) -> None:
        for path in PLUGIN_ROOT.rglob("*"):
            if path.is_file() and "tests" not in path.parts and path.suffix in {".md", ".yaml", ".json", ".py", ".sh"}:
                self.assertNotIn("Jeremy", path.read_text(encoding="utf-8", errors="ignore"), str(path))


if __name__ == "__main__":
    unittest.main()
