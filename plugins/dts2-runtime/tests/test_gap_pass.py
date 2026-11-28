"""gap_research.py pass and lock_block: the setup gap pass that gates the roadmap lock."""
from __future__ import annotations

import io
import os
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final
from unittest import mock

from helpers import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import approvals  # noqa: E402
import gap_research  # noqa: E402
import roadmap  # noqa: E402

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "gap_research.py"
GAPPY: Final[str] = """# End state

## Sections
| # | section | serves component | owner | depends on | complexity | status |
|---|---|---|---|---|---|---|
| 1 | data model | api | alice | - | normal | todo |
| 2 | login page | web | TBD | 1 | normal | todo |
| 3 | audit log | ops | - | 1 | normal | todo |
| 4 | export | web | ? | 1 | normal | todo |
| 5 | search | web |  | 1 | normal | todo |
| 6 | <placeholder> | web | - | 1 | normal | todo |

## Acceptance criteria

### api

- [ ] records persist

### reports

- [ ] reports render

## Notes

- Sends mail through a vendor API.
- Hosting service is free for the first year.
- Billing service costs $20 a month.
- We assume one region.
- The queue sizing is unverified.
- Region choice was verified with the owner. We assume nothing else.
"""


class FakeTerminal(io.StringIO):
    """A terminal that answers every prompt with `answer`."""

    def __init__(self, answer: str) -> None:
        super().__init__()
        self.answer: str = answer

    def readline(self, size: int | None = -1) -> str:  # noqa: ARG002 (matches the file API)
        return self.answer


def make_repo(text: str) -> Path:
    repo: Path = Path(tempfile.mkdtemp(prefix="dts2-gap-pass-"))
    path: Path = repo / ".harness" / "end-state.md"
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")
    return repo


def clean_pass(repo: Path) -> dict[str, Any]:
    """Run the setup gap pass and resolve whatever it found, so the roadmap lock gate is open for the current scope."""
    result: dict[str, Any] = gap_research.gap_pass(repo)
    for gap_id in result["open"]:
        gap_research.resolve(repo, gap_id, "test fixture: reviewed")
    return result


def texts(repo: Path, category: str) -> list[str]:
    return [str(row["text"]) for row in gap_research.read_rows(repo) if row.get("category") == category]


class PassTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo: Path = make_repo(GAPPY)
        self.result: dict[str, Any] = gap_research.gap_pass(self.repo)

    def test_owner_gaps_name_unset_cells_and_skip_placeholders(self) -> None:
        owners: list[str] = texts(self.repo, "owner")
        self.assertEqual(sorted(owners), ["audit log has no owner", "export has no owner", "login page has no owner", "search has no owner"])

    def test_section_gap_for_a_lane_no_section_serves(self) -> None:
        self.assertEqual(texts(self.repo, "section"), ["no section serves lane reports: reports render"])

    def test_dependency_gaps_skip_priced_lines(self) -> None:
        found: list[str] = texts(self.repo, "dependency")
        self.assertEqual(len(found), 1)
        self.assertIn("Sends mail through a vendor API.", found[0])

    def test_assumption_gaps_skip_verified_lines(self) -> None:
        found: list[str] = texts(self.repo, "assumption")
        self.assertEqual(len(found), 2)
        self.assertTrue(any("one region" in text for text in found))
        self.assertTrue(any("unverified" in text.lower() and "queue" in text for text in found))

    def test_rows_use_the_gap_kind_and_a_category(self) -> None:
        rows: list[dict[str, Any]] = gap_research.read_rows(self.repo)
        self.assertTrue(all(row["kind"] == "gap" and row["category"] in gap_research.CATEGORIES for row in rows))
        self.assertTrue(all(row["status"] == "proposed" and row["id"].startswith("G-") for row in rows))

    def test_result_is_written_with_the_scope_key_and_counts(self) -> None:
        recorded: dict[str, Any] = json.loads((self.repo / gap_research.PASS_REL).read_text(encoding="utf-8"))
        self.assertEqual(recorded, self.result)
        self.assertEqual(recorded["key"], roadmap.status(self.repo)["key"])
        self.assertEqual(recorded["found"], 8)
        self.assertEqual(recorded["counts"], {"owner": 4, "section": 1, "dependency": 1, "assumption": 2})
        self.assertEqual(recorded["open"], [f"G-{n}" for n in range(1, 9)])

    def test_second_pass_adds_nothing(self) -> None:
        again: dict[str, Any] = gap_research.gap_pass(self.repo)
        self.assertEqual(again["found"], 0)
        self.assertEqual(len(again["open"]), 8)
        self.assertEqual(len(gap_research.read_rows(self.repo)), 8)

    def test_neither_a_resolved_nor_a_rejected_gap_is_added_again(self) -> None:
        gap_research.resolve(self.repo, "G-1", "named an owner")
        gap_research.reject(self.repo, "G-2", "not needed")
        again: dict[str, Any] = gap_research.gap_pass(self.repo)
        self.assertEqual(again["found"], 0)
        self.assertNotIn("G-1", again["open"])
        self.assertNotIn("G-2", again["open"])

    def test_roadmap_view_is_scanned_when_present(self) -> None:
        key: str = str(roadmap.status(self.repo)["key"])
        (self.repo / ".harness" / "roadmap.md").write_text(
            f"# Roadmap\n\n- scope key: {key}\n- We assume the vendor stays up.\n", encoding="utf-8")
        again: dict[str, Any] = gap_research.gap_pass(self.repo)
        self.assertEqual(again["found"], 2)

    def test_stale_roadmap_view_is_not_scanned(self) -> None:
        (self.repo / ".harness" / "roadmap.md").write_text(
            "# Roadmap\n\n- scope key: deadbeef0000\n- We assume the vendor stays up.\n", encoding="utf-8")
        self.assertEqual(gap_research.gap_pass(self.repo)["found"], 0)

    def test_roadmap_view_without_a_scope_key_line_is_not_scanned(self) -> None:
        (self.repo / ".harness" / "roadmap.md").write_text("# Roadmap\n\n- We assume the vendor stays up.\n", encoding="utf-8")
        self.assertEqual(gap_research.gap_pass(self.repo)["found"], 0)

    def test_clean_end_state_finds_nothing(self) -> None:
        repo: Path = make_repo(GAPPY.split("## Notes")[0].replace("TBD", "bob").replace("| - |", "| carol |").replace("| ? |", "| dan |")
                               .replace("|  |", "| erin |").replace("### reports\n\n- [ ] reports render\n", ""))
        result: dict[str, Any] = gap_research.gap_pass(repo)
        self.assertEqual((result["found"], result["open"]), (0, []))
        self.assertIsNone(gap_research.lock_block(repo, str(result["key"])))

    def test_missing_end_state_is_an_error(self) -> None:
        with self.assertRaises(gap_research.GapError):
            gap_research.gap_pass(Path(tempfile.mkdtemp()))

    def test_cli_pass_prints_the_json(self) -> None:
        done = subprocess.run([sys.executable, "-I", str(SCRIPT), str(self.repo), "pass"], capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["found"], 0)


class LockBlockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo: Path = make_repo(GAPPY)
        self.key: str = str(roadmap.status(self.repo)["key"])

    def test_no_pass_blocks(self) -> None:
        reason: str | None = gap_research.lock_block(self.repo, self.key)
        self.assertIsNotNone(reason)
        self.assertTrue(str(reason).startswith("dt: gap pass"))
        self.assertIn("pass", str(reason))

    def test_open_gaps_block_and_are_named(self) -> None:
        gap_research.gap_pass(self.repo)
        reason: str = str(gap_research.lock_block(self.repo, self.key))
        self.assertTrue(reason.startswith("dt: gap pass"))
        self.assertIn("G-1", reason)
        self.assertIn("resolve", reason)

    def test_each_open_gap_must_be_dispositioned(self) -> None:
        gap_research.gap_pass(self.repo)
        for number in range(1, 8):
            gap_research.resolve(self.repo, f"G-{number}", "ok")
        self.assertIn("G-8", str(gap_research.lock_block(self.repo, self.key)))
        gap_research.reject(self.repo, "G-8", "not a gap")
        self.assertIsNone(gap_research.lock_block(self.repo, self.key))

    def test_pass_for_another_key_blocks(self) -> None:
        clean_pass(self.repo)
        self.assertIsNone(gap_research.lock_block(self.repo, self.key))
        reason: str = str(gap_research.lock_block(self.repo, "0" * 12))
        self.assertTrue(reason.startswith("dt: gap pass"))
        self.assertIn("again", reason)

    def test_changing_the_scope_after_a_pass_blocks_the_new_key(self) -> None:
        clean_pass(self.repo)
        path: Path = self.repo / ".harness" / "end-state.md"
        path.write_text(GAPPY.replace("| 5 | search |", "| 5 | search page |"), encoding="utf-8")
        self.assertNotEqual(roadmap.status(self.repo)["key"], self.key)
        self.assertIsNotNone(gap_research.lock_block(self.repo, str(roadmap.status(self.repo)["key"])))

    def test_unreadable_pass_file_blocks(self) -> None:
        path: Path = self.repo / gap_research.PASS_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        self.assertTrue(str(gap_research.lock_block(self.repo, self.key)).startswith("dt: gap pass"))

    def test_a_gap_added_after_the_pass_blocks(self) -> None:
        clean_pass(self.repo)
        rows: list[dict[str, Any]] = gap_research.read_rows(self.repo)
        rows.append({"id": "G-99", "kind": "gap", "category": "owner", "lane": "x", "text": "late", "status": "escalated"})
        gap_research.write_rows(self.repo, rows)
        self.assertIn("G-99", str(gap_research.lock_block(self.repo, self.key)))


class ApprovalsGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo: Path = make_repo(GAPPY)
        self.key: str = str(roadmap.status(self.repo)["key"])

    def terminal(self) -> Any:
        return FakeTerminal("yes")

    def test_owner_lock_is_refused_with_code_4_until_the_pass_is_clean(self) -> None:
        code, message = approvals.lock_roadmap(self.repo, self.key, terminal=self.terminal())
        self.assertEqual(code, 4)
        self.assertIn("dt: gap pass", message)
        self.assertFalse(roadmap.status(self.repo)["approved"])
        clean_pass(self.repo)
        code, message = approvals.lock_roadmap(self.repo, self.key, terminal=self.terminal())
        self.assertEqual(code, 0, message)
        self.assertTrue(roadmap.status(self.repo)["approved"])

    def test_chat_lock_says_why_and_grants_nothing(self) -> None:
        line: str = approvals.grant_from_prompt(json.dumps({"prompt": "lock it in"}), self.repo)
        self.assertIn("dt: gap pass", line)
        self.assertIn("nothing locked", line)
        self.assertFalse(roadmap.status(self.repo)["approved"])
        clean_pass(self.repo)
        self.assertIn("locked by the owner", approvals.grant_from_prompt(json.dumps({"prompt": "lock it in"}), self.repo))
        self.assertTrue(roadmap.status(self.repo)["approved"])

    def test_agent_route_hits_the_gate_first(self) -> None:
        with mock.patch.dict(os.environ, {"DTS2_SON": "1"}), \
                mock.patch.object(approvals, "agent_lock_roadmap", wraps=approvals.agent_lock_roadmap) as agent_lock:
            code, message = approvals.lock_roadmap(self.repo, self.key)
        self.assertEqual(code, 4)
        self.assertIn("dt: gap pass", message)
        agent_lock.assert_not_called()
        self.assertFalse(roadmap.status(self.repo)["approved"])

    def test_no_terminal_route_hits_the_gate_first(self) -> None:
        env: dict[str, str] = {k: v for k, v in os.environ.items() if k != "DTS2_SON"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(approvals, "agent_ancestor", return_value=None), \
                mock.patch.object(approvals, "open_terminal", return_value=None), \
                mock.patch.object(approvals, "no_terminal_lock", wraps=approvals.no_terminal_lock) as no_tty:
            code, message = approvals.lock_roadmap(self.repo, self.key)
            self.assertEqual(code, 4)
            self.assertIn("dt: gap pass", message)
            no_tty.assert_not_called()
            clean_pass(self.repo)
            code, _ = approvals.lock_roadmap(self.repo, self.key)
            self.assertNotEqual(code, 4)
            no_tty.assert_called_once()
        self.assertFalse(roadmap.status(self.repo)["approved"])


if __name__ == "__main__":
    unittest.main()
