"""gap_research.py: ledger rows, escalation, and applying suggestions to the end state."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import gap_research  # noqa: E402
import roadmap  # noqa: E402

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "gap_research.py"
END_STATE: Final[str] = """# End state

## Sections
| # | section | serves component | files / area | depends on | complexity | status |
|---|---|---|---|---|---|---|
| 1 | data model | api | src/db | - | normal | done |
| 2 | login page | web | src/web | 1 | normal | todo |
Status values: todo | in-progress | blocked | done.

## Acceptance criteria

### api

- [x] records persist across restarts

### web

- [ ] users can sign in

## Assumptions

- one region
"""


class GapResearchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp: tempfile.TemporaryDirectory[str] = tempfile.TemporaryDirectory()
        self.repo: Path = Path(self.tmp.name)
        (self.repo / ".harness").mkdir()
        (self.repo / ".harness" / "end-state.md").write_text(END_STATE, encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def end_state(self) -> str:
        return (self.repo / ".harness" / "end-state.md").read_text(encoding="utf-8")

    def add(self, kind: str, lane: str, text: str, why: str = "", needs: bool = False) -> dict[str, Any]:
        return gap_research.add(self.repo, kind, lane, text, why, "loop", needs)

    def test_add_assigns_ids_and_is_idempotent(self) -> None:
        first: dict[str, Any] = self.add("criterion", "web", "users can reset a password")
        second: dict[str, Any] = self.add("section", "web", "password reset flow")
        again: dict[str, Any] = self.add("criterion", "web", "Users can reset a  password")
        self.assertEqual((first["id"], second["id"]), ("G-1", "G-2"))
        self.assertEqual(again["id"], "G-1")
        self.assertEqual(first["status"], gap_research.STATUS_PROPOSED)
        self.assertEqual(len(gap_research.read_rows(self.repo)), 2)

    def test_service_suggestion_is_escalated_and_cannot_be_applied(self) -> None:
        row: dict[str, Any] = self.add("section", "api", "send receipts", why="needs a paid email API key")
        self.assertEqual(row["status"], gap_research.STATUS_ESCALATED)
        items: str = (self.repo / ".harness" / "action-items.md").read_text(encoding="utf-8")
        self.assertIn("Gap research G-1", items)
        with self.assertRaises(gap_research.GapError):
            gap_research.apply(self.repo, "G-1")
        self.assertEqual(self.end_state(), END_STATE)

    def test_needs_service_flag_escalates_plain_text(self) -> None:
        row: dict[str, Any] = self.add("criterion", "web", "dark mode", needs=True)
        self.assertEqual(row["status"], gap_research.STATUS_ESCALATED)

    def test_apply_criterion_under_existing_lane_changes_key(self) -> None:
        self.add("criterion", "web", "users can reset a password")
        result: dict[str, Any] = gap_research.apply(self.repo, "G-1")
        text: str = self.end_state()
        self.assertIn("- [ ] users can sign in\n- [ ] users can reset a password\n", text)
        self.assertNotEqual(result["key_before"], result["key_after"])
        self.assertEqual(result["key_after"], gap_research.scope_key(text))
        self.assertIn("acceptance|users can reset a password", roadmap.scope_lines(text))
        self.assertEqual(gap_research.read_rows(self.repo)[0]["status"], gap_research.STATUS_APPLIED)

    def test_apply_criterion_creates_missing_lane(self) -> None:
        self.add("criterion", "billing", "invoices show tax")
        gap_research.apply(self.repo, "G-1")
        text: str = self.end_state()
        self.assertIn("### billing\n\n- [ ] invoices show tax\n\n## Assumptions", text)
        self.assertIn("acceptance|invoices show tax", roadmap.scope_lines(text))

    def test_apply_section_adds_numbered_todo_row(self) -> None:
        self.add("section", "web", "password reset flow")
        gap_research.apply(self.repo, "G-1")
        text: str = self.end_state()
        self.assertIn("| 3 | password reset flow | web | - | - | normal | todo |", text)
        self.assertIn("section|3|password reset flow", roadmap.scope_lines(text))
        self.assertIn("Status values:", text)

    def test_apply_refuses_duplicates_and_second_apply(self) -> None:
        self.add("criterion", "web", "users can sign in")
        with self.assertRaises(gap_research.GapError):
            gap_research.apply(self.repo, "G-1")
        self.add("criterion", "web", "users can sign out")
        gap_research.apply(self.repo, "G-2")
        with self.assertRaises(gap_research.GapError):
            gap_research.apply(self.repo, "G-2")

    def test_reject_records_reason_and_refuses_applied(self) -> None:
        self.add("criterion", "web", "users can sign out")
        self.add("criterion", "web", "users can export data")
        row: dict[str, Any] = gap_research.reject(self.repo, "G-2", "out of scope")
        self.assertEqual((row["status"], row["reason"]), (gap_research.STATUS_REJECTED, "out of scope"))
        gap_research.apply(self.repo, "G-1")
        with self.assertRaises(gap_research.GapError):
            gap_research.reject(self.repo, "G-1", "late")

    def test_table_pipes_are_neutralised(self) -> None:
        row: dict[str, Any] = self.add("section", "web", "a | b")
        self.assertEqual(row["text"], "a / b")

    def test_cli_list_and_error_exit(self) -> None:
        self.add("criterion", "web", "users can sign out")
        listed = subprocess.run([sys.executable, "-I", str(SCRIPT), str(self.repo), "list", "--status", "proposed"],
                                capture_output=True, text=True, check=True)
        self.assertEqual([row["id"] for row in json.loads(listed.stdout)], ["G-1"])
        missing = subprocess.run([sys.executable, "-I", str(SCRIPT), str(self.repo), "apply", "G-9"],
                                 capture_output=True, text=True)
        self.assertEqual(missing.returncode, gap_research.EXIT_FAILURE)
        self.assertIn("no suggestion G-9", json.loads(missing.stdout)["error"])


if __name__ == "__main__":
    unittest.main()
