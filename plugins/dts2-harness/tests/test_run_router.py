"""Structure contract for the run skill: a short router plus phase files read on demand."""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Final

from helpers import RUN_SKILL_DIR, read_run_skill

ROUTER: Final[Path] = RUN_SKILL_DIR / "SKILL.md"
MAX_ROUTER_LINES: Final[int] = 90
ORIGINAL_HEADINGS: Final[tuple[str, ...]] = (
    "## Preflight", "### Pre-check (every run command)",
    "## Phase 0 — Size and Budget check", "## Phase 1 — Plan (lead)", "## Phase 2 — Build (parallel builders)",
    "### Secrets", "## Continuous dispatch (never idle)", "## Phase 3 — Review and verify",
    "## Phase 3b — Finish pass", "## Phase 3c — Code finish pass", "## Phase 4 — Ship checkpoint",
    "## After ship", "## Deployment verification", "## Add secret mode", "## Status lines",
    "## Isolation (Rule 10)", "## Lead stall and failover (Rule 8.7)", "## review-pr mode",
    "## Context guard and pivot", "## Questions from the user", "## Guardrails",
)


def phase_files() -> list[Path]:
    return sorted(p for p in RUN_SKILL_DIR.glob("*.md") if p.name != "SKILL.md")


class RunRouterTests(unittest.TestCase):
    def test_router_is_short(self) -> None:
        lines: int = len(ROUTER.read_text(encoding="utf-8").splitlines())
        self.assertLessEqual(lines, MAX_ROUTER_LINES)

    def test_every_phase_file_is_named_in_router(self) -> None:
        router: str = ROUTER.read_text(encoding="utf-8")
        self.assertGreaterEqual(len(phase_files()), 5)
        for path in phase_files():
            self.assertIn(f"`{path.name}`", router, path.name)

    def test_every_file_named_in_router_exists(self) -> None:
        router: str = ROUTER.read_text(encoding="utf-8")
        named: set[str] = set(re.findall(r"`([a-z0-9-]+\.md)`", router))
        self.assertTrue(named)
        for name in named:
            self.assertTrue((RUN_SKILL_DIR / name).is_file(), name)

    def test_phase_files_have_no_frontmatter(self) -> None:
        for path in phase_files():
            text: str = path.read_text(encoding="utf-8")
            self.assertFalse(text.startswith("---"), path.name)
            self.assertTrue(text.startswith("# run — "), path.name)

    def test_each_original_heading_appears_exactly_once(self) -> None:
        lines: list[str] = read_run_skill().splitlines()
        for heading in ORIGINAL_HEADINGS:
            self.assertEqual(lines.count(heading), 1, heading)

    def test_companion_protocol_is_defined_once_in_router(self) -> None:
        router: str = ROUTER.read_text(encoding="utf-8")
        self.assertEqual(router.count("\n## Companion skills\n"), 1)
        self.assertIn("`npx skills add` command its entry in Companion skills", router)


if __name__ == "__main__":
    unittest.main()
