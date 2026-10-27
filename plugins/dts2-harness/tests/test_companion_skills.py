"""Companion skills from mattpocock/skills (3.4.0, extended in 3.5.0; request-refactor-plan retired and diagnose renamed upstream, fixed in 3.6.2): discipline, setup, run, lead, keep template."""
from __future__ import annotations

import unittest
from typing import Final

from helpers import PLUGIN_ROOT

INSTALL_PATTERN: Final[str] = "`npx skills add https://github.com/mattpocock/skills --skill <name>`"
SKILLS: Final[tuple[str, ...]] = (
    "grill-me", "improve-codebase-architecture", "writing-for-agents",
    "pr", "resolving-merge-conflicts", "ask-matt", "research", "diagnosing-bugs",
    "loop-me", "setup-pre-commit", "code-review",
)
RETIRED: Final[tuple[str, ...]] = ("request-refactor-plan", "diagnose")
INSTALL: Final[str] = "npx skills add https://github.com/mattpocock/skills --skill"
MOMENTS: Final[dict[str, str]] = {
    "improve-codebase-architecture": "finalization pass before tests are written",
    "diagnosing-bugs": "hard 3-round cap, bugs still failing",
    "loop-me": "on /dts2-harness:run trigger — check in with the user",
    "setup-pre-commit": "before every commit",
    "code-review": "first contact — repo the harness has never been in",
}
SETUP_PHRASES: Final[tuple[str, ...]] = (
    "First contact (code-review, once per repo)", ".harness/seen",
    "4c. Grill the draft", "5b. Architecture pass", "5c. Agent-friendly rewrite",
    "/grill-me", "/improve-codebase-architecture", "/writing-for-agents",
    "Apply these architecture amendments?", ".harness/plan-style.md",
    "## Questions from the user", "/ask-matt", "/research",
)
RUN_PHRASES: Final[tuple[str, ...]] = (
    "/pr", "/resolving-merge-conflicts", "PR body written by /pr",
    "## Questions from the user", "/ask-matt", "/research", "/diagnosing-bugs",
    "Finalization before tests", "Run-trigger check-in (loop-me)", "First contact (code-review, once per repo)",
    "BEFORE writing any tests", "hard round-3 cap", "last gate before `git commit`", ".harness/seen",
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

    def test_new_hooks_have_moment_and_command_in_discipline(self) -> None:
        text: str = read("templates/discipline.md")
        for name, moment in MOMENTS.items():
            self.assertIn(moment, text, name)
            self.assertIn(f"{INSTALL} {name}`", text, name)

    def test_hard_cap_reruns_diagnosing_bugs_fresh(self) -> None:
        for relative in ("templates/discipline.md", "skills/run/SKILL.md"):
            text: str = read(relative)
            self.assertIn(f"{INSTALL} diagnosing-bugs`", text, relative)
            self.assertIn("fresh `/diagnosing-bugs` pass", text, relative)
            self.assertNotIn("/diagnose`", text, relative)

    def test_run_wires_each_new_hook_with_its_command(self) -> None:
        text: str = read("skills/run/SKILL.md")
        for name in ("improve-codebase-architecture", "diagnosing-bugs", "loop-me", "setup-pre-commit", "code-review"):
            self.assertIn(f"{INSTALL} {name}`", text, name)

    def test_setup_runs_code_review_once_on_first_contact(self) -> None:
        text: str = read("skills/setup/SKILL.md")
        self.assertIn(f"{INSTALL} code-review`", text)
        self.assertIn("once per repo", text)

    def test_exactly_eleven_companion_skills(self) -> None:
        self.assertEqual(len(SKILLS), 11)
        self.assertEqual(len(set(SKILLS)), 11)

    def test_retired_upstream_skills_are_not_referenced(self) -> None:
        for path in PLUGIN_ROOT.rglob("*"):
            if path.is_file() and "tests" not in path.parts and path.suffix in {".md", ".yaml", ".json", ".py", ".sh"}:
                text: str = path.read_text(encoding="utf-8", errors="ignore")
                for name in RETIRED:
                    self.assertNotIn(f"--skill {name}", text, str(path))

    def test_finalization_has_manual_fallback(self) -> None:
        text: str = read("skills/run/SKILL.md")
        self.assertIn("manual scoped simplification pass", text)

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
