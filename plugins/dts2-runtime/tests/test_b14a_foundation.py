"""AA-3: mandatory ## Foundation section (wave: 0) and wave-0-first dispatch."""
from __future__ import annotations

import unittest

from helpers import PLUGIN_ROOT


def read(rel: str) -> str:
    return (PLUGIN_ROOT / rel).read_text(encoding="utf-8")


class FoundationTests(unittest.TestCase):
    def test_lead_output_format_has_foundation_with_wave_zero(self) -> None:
        lead = read("agents/lead.md")
        fmt = lead[lead.index("## Output format"):]
        self.assertIn("## Foundation", fmt)
        self.assertIn("wave: 0", fmt)
        self.assertLess(fmt.index("## Foundation"), fmt.index("### Builder 1"))

    def test_lead_makes_foundation_mandatory(self) -> None:
        lead = read("agents/lead.md")
        self.assertRegex(lead, r"(?i)mandatory `## Foundation`")
        for needle in ("shared types", "config", "`wave: 0`", "none needed"):
            self.assertIn(needle, lead)

    def test_foundation_files_are_never_given_to_other_builders(self) -> None:
        self.assertIn("Foundation files belong to wave 0 only", read("agents/lead.md"))

    def test_build_phase_runs_wave_zero_merges_then_releases_queue(self) -> None:
        build = read("skills/run/phase-2-build.md")
        self.assertIn("Wave 0 (Foundation)", build)
        block = build[build.index("Wave 0 (Foundation)"):]
        self.assertLess(block.index("dispatch"), block.index("merge"))
        self.assertLess(block.index("merge"), block.index("release"))
        self.assertIn("Ready queue", block)

    def test_plan_checkpoint_requires_foundation(self) -> None:
        self.assertIn("## Foundation", read("skills/run/phase-1-plan.md"))


if __name__ == "__main__":
    unittest.main()
