"""The skills that drive parallel runs call the lanes.py lifecycle commands, and every `lanes.py <sub>` a skill names is real."""
from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT

CLI: Final[Path] = PLUGIN_ROOT / "scripts" / "lanes.py"
SKILLS: Final[Path] = PLUGIN_ROOT / "skills"
LIFECYCLE: Final[tuple[str, ...]] = (
    "transition", "shutdown", "reconcile", "run-record", "builder", "run-resume", "fold-done", "merge-resume",
    "walkthrough-failed", "report",
)
OWNED: Final[tuple[str, ...]] = ("dpp", "autopilot", "fullauto")
CALL: Final[re.Pattern[str]] = re.compile(r"lanes\.py\"?\s+([a-z][a-z-]*)")


def subcommands() -> frozenset[str]:
    out: str = subprocess.run([sys.executable, str(CLI), "--help"], capture_output=True, text=True, check=True).stdout
    match = re.search(r"\{([a-z][a-z,-]+)\}", out)
    assert match is not None, out
    return frozenset(match.group(1).split(","))


def owned_text() -> str:
    return "\n".join(p.read_text() for name in OWNED for p in sorted((SKILLS / name).rglob("*.md")))


class SkillsWiringTests(unittest.TestCase):
    def test_lifecycle_commands_are_real(self) -> None:
        self.assertLessEqual(frozenset(LIFECYCLE), subcommands())

    def test_every_lifecycle_command_is_called_by_an_owned_skill(self) -> None:
        text: str = owned_text()
        called: frozenset[str] = frozenset(CALL.findall(text))
        for name in LIFECYCLE:
            with self.subTest(command=name):
                self.assertIn(name, called)

    def test_every_named_subcommand_exists(self) -> None:
        real: frozenset[str] = subcommands()
        for path in sorted(SKILLS.rglob("*.md")):
            for sub in CALL.findall(path.read_text()):
                with self.subTest(file=str(path.relative_to(SKILLS)), sub=sub):
                    self.assertIn(sub, real)


if __name__ == "__main__":
    unittest.main()
