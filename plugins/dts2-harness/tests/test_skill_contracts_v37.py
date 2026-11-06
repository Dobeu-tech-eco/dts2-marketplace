"""Text contracts for 3.7.0: ship, feature, autopilot, the pre-check, check-in and the evolve sweep."""
from __future__ import annotations

import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT
from test_text_contracts import TextContractMixin

SKILLS: Final[Path] = PLUGIN_ROOT / "skills"
PRECHECK: Final[str] = "Pre-check (every run command)"


def description(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("description:"):
            return line[len("description:"):].strip()
    return ""


class NewSkillsContract(TextContractMixin):
    def test_new_skills_exist_with_clean_descriptions(self) -> None:
        for name in ("ship", "feature", "autopilot"):
            path = SKILLS / name / "SKILL.md"
            self.assertTrue(path.is_file(), name)
            self.assert_contains(path, [f"name: {name}"])
            text = description(path)
            self.assertTrue(text, name)
            self.assertNotIn("<", text, name)
            self.assertNotIn(">", text, name)

    def test_every_entry_point_runs_the_precheck(self) -> None:
        for name in ("ship", "feature", "autopilot"):
            self.assert_contains(SKILLS / name, [PRECHECK])

    def test_ship(self) -> None:
        self.assert_contains(SKILLS / "ship" / "SKILL.md", [
            "Never merges", "gitleaks", "do_not_touch", "dt:verifier", "dt:reviewer",
            "templates/receipt.md", "templates/pr-template.md", ".github/pull_request_template.md",
            "/pr", "gh pr create --base", "gh pr checks", "only `main` and `dev` remain",
            "foldable PR", "redundant PR", "stale branch", "Apply this cleanup?", "cleanup.md",
            "never `--force`", "/resolve-merge-conflicts", "evolve sweep",
        ])

    def test_feature(self) -> None:
        self.assert_contains(SKILLS / "feature" / "SKILL.md", [
            "clarity-score.py", "end_state_threshold", "Round 3b", "Round 4 — Question loop",
            "Round 4c", "/grill-me", "5b. Architecture pass", "/improve-codebase-architecture",
            "5c. Agent-friendly rewrite", "/writing-for-agents", "dt:lead", "## Sections",
            "PLAN.md", "ROADMAP.md", "STATUS.md", "action-items.py", "/dt:ship",
            "never renumbered", "Continue anyway",
        ])

    def test_autopilot(self) -> None:
        self.assert_contains(SKILLS / "autopilot", [
            "three frontier", "model: fable", "Fable 5.1", "tiebreaker", "never sits on the panel",
            "Falling back to the normal human checkpoints", "VOTE: APPROVE", "VOTE: REJECT",
            "3-0 APPROVE", "2-1 APPROVE", "Split", "roster.py command", "--tier frontier",
            "--squash --delete-branch", "never `--admin`", "required_linear_history",
            "gh pr comment", ".harness/autopilot/latest.md", "autopilot resume", "park",
            "Never build on a previous step's unmerged branch", "3-round cap",
        ])
        self.assert_absent(SKILLS / "autopilot", ["--merge --admin", "force-push to"])


class WiringContract(TextContractMixin):
    def test_run_precheck_and_sweep(self) -> None:
        self.assert_contains(SKILLS / "run", [
            PRECHECK, "skills-check.py", "-a claude-code --copy -y", "lessons-inbox.md",
            "Harness sweep (evolve)", "Harness lessons", "Never push, deploy, or merge to main",
        ])

    def test_check_in_shows_autopilot(self) -> None:
        self.assert_contains(SKILLS / "check-in" / "SKILL.md", [".harness/autopilot/latest.md", "autopilot resume"])

    def test_evolve_is_swept_automatically(self) -> None:
        self.assert_contains(SKILLS / "evolve" / "SKILL.md", ["automatically after every ship"])

    def test_discipline_points_to_precheck(self) -> None:
        self.assert_contains(PLUGIN_ROOT / "templates" / "discipline.md", [
            "skills-check.py", "-a claude-code --copy -y", "warpdotdev/common-skills@resolve-merge-conflicts",
        ])

    def test_pr_template_keeps_receipt_marker_once(self) -> None:
        text = (PLUGIN_ROOT / "templates" / "pr-template.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("## Change receipt"), 1)
        for heading in ("## Linked work", "## Pre-checks", "## Consensus (autopilot only)"):
            self.assertIn(heading, text)


if __name__ == "__main__":
    unittest.main()
