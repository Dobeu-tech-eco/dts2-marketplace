"""Template existence and heading checks."""
from __future__ import annotations

import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT

TEMPLATES: Final[Path] = PLUGIN_ROOT / "templates"
RECEIPT_HEADINGS: Final[list[str]] = [
    "## Change receipt", "### Tests run", "### Review verdict", "### Approved by",
    "### Steps outside this change", "### Open risks", "### Rollback point",
]
EXPECTED: Final[dict[str, list[str]]] = {
    "discipline.md": [
        "Define done first", "End with a receipt", "Cap fix rounds at three",
        "Repeat mistake", "State outside the chat", "Auto-add the receipt",
        "Where it bites", "pr-receipt.sh",
    ],
    "receipt.md": RECEIPT_HEADINGS + ["| Command | Pass | Fail | Skip |"],
    "end-state.md": [
        "# End state: <project>", "rounds:", "clarity:", "threshold:", "thresholdSource:",
        "status: pending approval", "continuedAnyway:", "## Related repos", "## Other harnesses",
        "## Skills", "| skill | source | installed | serves component | phase | order |",
        "| url | role | tag | note |", "## Topology", "## Goal", "## Constraints", "## Non-goals",
        "## Acceptance criteria", "- [ ]", "## Assumptions", "## Open questions",
    ],
    "state.md": ["# Harness state", "## Decisions", "## Failures and escalations", "## Open items"],
    "pr-template.md": ["## Summary"] + RECEIPT_HEADINGS,
    "dts2-harness.local.md": [
        "end_state_threshold: 80", "config.yaml", "dev_server:", "# Learning", "auto_learn: true",
    ],
}


class TemplateTests(unittest.TestCase):
    def test_templates_contain_required_text(self) -> None:
        for name, needles in EXPECTED.items():
            path: Path = TEMPLATES / name
            self.assertTrue(path.is_file(), f"{name} missing")
            text: str = path.read_text(encoding="utf-8")
            for needle in needles:
                self.assertIn(needle, text, f"{name} lacks {needle!r}")


if __name__ == "__main__":
    unittest.main()
