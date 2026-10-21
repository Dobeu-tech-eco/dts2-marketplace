"""Sections map and continuous dispatch (3.3.0): template, skills, agent, discipline, settings, handoff."""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT, make_tmp_home

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "handoff-write.py"
SECTION_COLUMNS: Final[str] = "| # | section | serves component | files / area | depends on | complexity | status |"
STATUS_LINE: Final[str] = "Status values: todo | in-progress | blocked | done."
BLOCKED_ROW: Final[str] = "| 1 | payments webhook (S1) | billing | src/pay | - | normal | blocked |"
EXPECTED_LINE: Final[str] = "section 1 payments webhook — blocked (S1)"


def read(relative: str) -> str:
    return (PLUGIN_ROOT / relative).read_text(encoding="utf-8")


def render_handoff(end_state: str) -> str:
    repo: Path = make_tmp_home()
    harness: Path = repo / ".harness"
    harness.mkdir()
    (harness / "end-state.md").write_text(end_state, encoding="utf-8")
    subprocess.run(["python3", "-I", str(SCRIPT), str(repo)], capture_output=True, text=True, check=True)
    return (harness / "handoff" / "latest.md").read_text(encoding="utf-8")


class SectionsTemplateTests(unittest.TestCase):
    def test_end_state_has_sections_block_after_blueprint(self) -> None:
        text: str = read("templates/end-state.md")
        self.assertIn("## Sections", text)
        self.assertLess(text.index("## Blueprint"), text.index("## Sections"))
        self.assertLess(text.index("## Sections"), text.index("## Goal"))
        self.assertIn(SECTION_COLUMNS, text)
        self.assertIn(STATUS_LINE, text)

    def test_local_template_has_dispatch_settings(self) -> None:
        text: str = read("templates/dts2-harness.local.md")
        self.assertIn("continuous_dispatch: true", text)
        self.assertIn("builder_timeout_min: 20", text)

    def test_discipline_has_never_idle_rule(self) -> None:
        self.assertIn("Never idle, never collide", read("templates/discipline.md"))


class SectionsSkillTests(unittest.TestCase):
    def test_setup_has_round_3b(self) -> None:
        text: str = read("skills/setup/SKILL.md")
        self.assertIn("3b. Sections", text)
        self.assertIn("Edit, or approve?", text)
        self.assertLess(text.index("### Round 3"), text.index("3b. Sections"))
        self.assertLess(text.index("3b. Sections"), text.index("### Round 4 "))

    def test_lead_has_ready_queue(self) -> None:
        text: str = read("agents/lead.md")
        self.assertIn("## Ready queue", text)
        self.assertIn("## Sections", text)

    def test_run_has_continuous_dispatch(self) -> None:
        text: str = read("skills/run/SKILL.md")
        for phrase in ("## Continuous dispatch (never idle)", "builder_timeout_min", "Sections this run:", "park", "continuous_dispatch"):
            self.assertIn(phrase, text)
        self.assertLess(text.index("## Phase 2"), text.index("## Continuous dispatch (never idle)"))
        self.assertLess(text.index("## Continuous dispatch (never idle)"), text.index("## Phase 3 "))
        self.assertIn("Never idle while a ready, non-conflicting section exists", text)

    def test_action_items_and_onboard_mention_sections(self) -> None:
        self.assertIn("## Sections", read("skills/action-items/SKILL.md"))
        self.assertIn("sections", read("skills/onboard/SKILL.md"))


class SectionsHandoffTests(unittest.TestCase):
    def test_blocked_section_listed_in_open_items(self) -> None:
        end_state: str = f"# End state: x\n\n## Sections\n\n{SECTION_COLUMNS}\n|---|---|---|---|---|---|---|\n{BLOCKED_ROW}\n| 2 | api | billing | src/api | 1 | normal | todo |\n"
        text: str = render_handoff(end_state)
        self.assertIn(EXPECTED_LINE, text)
        self.assertNotIn("section 2", text)

    def test_no_blocked_sections_leaves_none(self) -> None:
        text: str = render_handoff("# End state: x\n\n## Sections\n\n| 1 | api | b | src | - | normal | done |\n")
        self.assertNotIn("section 1", text)


if __name__ == "__main__":
    unittest.main()
