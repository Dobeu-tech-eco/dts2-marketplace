"""B14B text contracts: the run phases, the lead, the reviewer and the dpp skill describe the new scripts, and the scripts exist."""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT, read_run_skill

RUN: Final[Path] = PLUGIN_ROOT / "skills" / "run"
DPP: Final[Path] = PLUGIN_ROOT / "skills" / "dpp" / "SKILL.md"
ARCH: Final[Path] = PLUGIN_ROOT / "ARCHITECTURE.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class LeadBriefTextTests(unittest.TestCase):
    def test_phase_one_hands_the_lead_one_page(self) -> None:
        text = read(RUN / "phase-1-plan.md")
        self.assertIn("briefs.py\" lead-brief --stamp <stamp> --task-file", text)
        self.assertIn("Never paste the roster, probe or ledger JSON", text)
        self.assertNotIn("the roster JSON, the probe JSON", text)

    def test_lead_agent_expects_the_brief(self) -> None:
        text = read(PLUGIN_ROOT / "agents" / "lead.md")
        self.assertIn("lead brief (`briefs.py lead-brief`)", text)
        self.assertIn("It is not a data dump", text)

    def test_lead_prefers_vertical_slices_and_declares_contracts(self) -> None:
        for text in (read(PLUGIN_ROOT / "agents" / "lead.md"), read(RUN / "phase-1-plan.md")):
            self.assertIn("vertical slices", text)
            self.assertIn("`provides:`", text)
            self.assertIn("`stubbed_on:`", text)
        self.assertIn("provides: <contract names or none>", read(PLUGIN_ROOT / "agents" / "lead.md"))

    def test_plan_checkpoint_shows_the_critical_path(self) -> None:
        self.assertIn("critical_path_line", read(RUN / "phase-1-plan.md"))

    def test_single_mode_run_text_never_says_lane(self) -> None:
        for name in ("phase-1-plan.md", "phase-2-build.md", "phase-3-review.md", "phase-4-ship.md", "SKILL.md"):
            self.assertNotIn("lane", read(RUN / name).lower(), name)


class DppTextTests(unittest.TestCase):
    def test_plan_section_covers_the_graph_and_amend(self) -> None:
        text = read(DPP)
        for needle in ("`provides`, `consumes` and `stubbed_on`", "graph.critical_path_line", "`stubbed_on`", "package roots",
                       "lanes.py amend <manifest> --lane <id>", "rewrites the lane's `brief.md`"):
            self.assertIn(needle, text)

    def test_start_sons_section_has_the_son_brief(self) -> None:
        text = read(DPP)
        section = text[text.index("## 4. Start sons"):text.index("## 5. Supervise")]
        for needle in ("briefs.py", "son-brief <manifest> --lane <id> --epoch <epoch> --out", "templates/son-brief.md", "dry-run", "prefix"):
            self.assertIn(needle, section)

    def test_merge_section_has_provider_first(self) -> None:
        text = read(DPP)
        section = text[text.index("## 6. Merge order"):text.index("## 7.")]
        self.assertIn("plan_graph.py", section)
        self.assertIn("provider-first", section)


class ReviewTextTests(unittest.TestCase):
    def test_phase_three_partitions_and_digests(self) -> None:
        text = read(RUN / "phase-3-review.md")
        for needle in ("review_split.py", "`split: true`", "one reviewer per `slices` entry", "findings.py", "digest", "diff stat"):
            self.assertIn(needle, text)

    def test_phase_four_merges_with_the_findings_script(self) -> None:
        text = read(RUN / "phase-4-ship.md")
        self.assertIn("findings.py", text)
        self.assertIn("deduped by file:line keeping the higher severity", text)

    def test_reviewer_knows_the_calibration_and_slices(self) -> None:
        text = read(PLUGIN_ROOT / "agents" / "reviewer.md")
        for needle in ("## Calibration (Q-21)", "## Slice and final review (AA-7)", "cannot be CRITICAL or HIGH", "hides a defect"):
            self.assertIn(needle, text)


class ScriptsExistTests(unittest.TestCase):
    def test_every_script_the_run_text_names_exists(self) -> None:
        text = read_run_skill() + read(DPP)
        for name in set(re.findall(r"scripts/([\w-]+\.py)", text)):
            self.assertTrue((PLUGIN_ROOT / "scripts" / name).is_file(), name)

    def test_architecture_names_the_new_scripts_and_the_fixer(self) -> None:
        body = read(ARCH)
        for name in ("plan_graph.py", "scripts/lanes/amend.py", "findings.py", "review_split.py", "rollback_ref.py"):
            self.assertIn(name, body)
        self.assertIn("| fixer |", body)


if __name__ == "__main__":
    unittest.main()
