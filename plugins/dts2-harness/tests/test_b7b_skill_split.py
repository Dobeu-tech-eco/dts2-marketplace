"""Q-10: autopilot and setup are a short router SKILL.md plus phase files read on demand."""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT

SKILLS: Final[Path] = PLUGIN_ROOT / "skills"
ROUTER_MAX_BYTES: Final[int] = 6000
TABLE_ROW: Final[re.Pattern[str]] = re.compile(r"^\| `([\w.-]+\.md)` \|", re.MULTILINE)


class SkillSplitTests(unittest.TestCase):
    def check(self, name: str) -> None:
        folder: Path = SKILLS / name
        router: str = (folder / "SKILL.md").read_text(encoding="utf-8")
        self.assertLessEqual(len(router.encode()), ROUTER_MAX_BYTES, f"{name} router is not short")
        self.assertTrue(router.startswith(f"---\nname: {name}\n"))
        listed: list[str] = TABLE_ROW.findall(router)
        phase_files: list[str] = sorted(f.name for f in folder.glob("*.md") if f.name != "SKILL.md")
        self.assertEqual(sorted(listed), phase_files, f"{name}: the router table and the phase files differ")
        for file in phase_files:
            self.assertIn(f"Read `{file}` (same folder)", router)
            self.assertGreater(len((folder / file).read_text(encoding="utf-8")), 200)

    def test_autopilot_is_a_router(self) -> None:
        self.check("autopilot")
        self.assertIn("## Guardrails", (SKILLS / "autopilot" / "SKILL.md").read_text(encoding="utf-8"))

    def test_setup_is_a_router(self) -> None:
        self.check("setup")

    def test_a_son_reads_only_its_brief_and_the_son_file(self) -> None:
        router: str = (SKILLS / "autopilot" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("A son reads its `brief.md` and this file, and no other phase file", router)
        son: str = (SKILLS / "autopilot" / "son-mode.md").read_text(encoding="utf-8")
        self.assertIn("## 6. Son mode", son)
        self.assertIn("briefs.py", son)

    def test_numbered_sections_survive_in_order(self) -> None:
        text: str = "\n".join(f.read_text(encoding="utf-8") for f in sorted((SKILLS / "autopilot").glob("*.md")) if f.name != "SKILL.md")
        marks: list[str] = ["## 0. Pre-check", "## 1. The consensus gate", "## 1b. The council", "## 2. Per step", "## 3. Per step",
                            "## 4. Parking", "## 5a. Adjudication", "## 5. Final report", "## 6. Son mode"]
        positions: list[int] = [text.find(m) for m in marks]
        self.assertNotIn(-1, positions)
        self.assertEqual(positions, sorted(positions))


if __name__ == "__main__":
    unittest.main()
