"""Text contracts for the v3 skills: learn auto mode and promotion, evolve, gtm, onboard, sdk."""
from __future__ import annotations

import unittest
from typing import Final

from helpers import PLUGIN_ROOT
from test_text_contracts import TextContractMixin

SKILLS: Final = PLUGIN_ROOT / "skills"
GTM_ORDER: Final[list[str]] = [
    "product-marketing-context", "competitor-profiling", "seo-audit", "page-cro",
    "copywriting", "copy-editing", "launch-strategy", "analytics-tracking",
]


class LearnV3Contract(TextContractMixin):
    def test_learn(self) -> None:
        self.assert_contains(SKILLS / "learn" / "SKILL.md", [
            "## Auto mode", "lives at", ".harness/checks.sh", "review-checklist.md",
            "seen twice", "Never edit plugin hooks", "auto_learn",
        ])


class EvolveContract(TextContractMixin):
    def test_evolve(self) -> None:
        self.assert_contains(SKILLS / "evolve" / "SKILL.md", [
            "name: evolve", "plugins/cache", "plugins/synced", "claude plugin validate plugins/dts2-harness",
            "claude plugin validate .", "git remote -v | grep dts2-marketplace", "~/.dts2/marketplace",
            "https://github.com/Dobeu-tech-eco/dts2-marketplace.git", "explicit yes",
            "/plugin marketplace update dts2", "restart", "python3 -m unittest discover -s plugins/dts2-harness/tests",
        ])


class GtmContract(TextContractMixin):
    def test_gtm(self) -> None:
        path = SKILLS / "gtm" / "SKILL.md"
        self.assert_contains(path, ["name: gtm", "readiness.md", ".harness/gtm/", "end-state.md",
                                    "ListPlugins", "area", "blocker", "owner"])
        text: str = path.read_text(encoding="utf-8")
        positions: list[int] = [text.find(f"/marketing-skills:{n}") for n in GTM_ORDER]
        self.assertNotIn(-1, positions)
        self.assertEqual(positions, sorted(positions))


class OnboardV3Contract(TextContractMixin):
    def test_onboard(self) -> None:
        path = SKILLS / "onboard" / "SKILL.md"
        self.assert_contains(path, ["twelve skills", "Plan checkpoint", "Ship checkpoint", "opencode",
                                    "run add secret NAME", "cost tier", "evolve", "gtm"])
        self.assert_absent(path, ["Worktrees |", "six skills"])


class SdkV3Contract(TextContractMixin):
    def test_sdk(self) -> None:
        path = SKILLS / "sdk" / "SKILL.md"
        self.assert_contains(path, ["--ship", "--live-only", "DTS2_SHIP_BRANCH", "receipt.md",
                                    "only the plan checkpoint", "handoff lane"])
        self.assert_absent(path, ["Never skip either gate"])


if __name__ == "__main__":
    unittest.main()
