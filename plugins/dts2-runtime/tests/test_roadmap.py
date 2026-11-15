"""scripts/roadmap.py: the scope hash, the approval status and the deterministic Markdown view."""
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
import roadmap  # noqa: E402

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "roadmap.py"
KEY_LENGTH: Final[int] = 12
END_STATE: Final[str] = """# End state

- status: approved

## Sections
| # | section | serves component | files / area | depends on | complexity | status |
|---|---|---|---|---|---|---|
| 1 | data model | api | db/ | - | normal | done |
| 2 | payments   webhook (S2) | api | pay/ | 1 | design | blocked |
| 3 | ui shell | web | web/ | 1 | normal | todo |
| 4 | <placeholder> | web | web/ | 1 | normal | todo |
Status values: todo | in-progress | blocked | done.

## Acceptance criteria

### api

- [x] migrations apply
- [ ] webhook   verifies signatures
- [ ] <criterion>

## Assumptions

- [ ] not an acceptance box
"""
TEMPLATE_REL: Final[Path] = Path("templates") / "end-state.md"


def make_repo(end_state: str | None = END_STATE) -> Path:
    repo: Path = Path(tempfile.mkdtemp(prefix="dts2-roadmap-"))
    if end_state is not None:
        write(repo / ".harness" / "end-state.md", end_state)
    return repo


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def approve(repo: Path, key: str) -> None:
    table: dict[str, Any] = {"dts2_approvals": {"roadmap": [key]}}
    write(repo / ".claude" / "settings.local.json", json.dumps(table))


def run_cli(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--repo", str(repo), *args],
        capture_output=True, text=True, check=False,
    )


class ScopeTests(unittest.TestCase):
    def test_lines_are_sections_then_acceptance_with_clean_whitespace(self) -> None:
        self.assertEqual(roadmap.scope_lines(END_STATE), [
            "section|1|data model",
            "section|2|payments webhook",
            "section|3|ui shell",
            "acceptance|migrations apply",
            "acceptance|webhook verifies signatures",
        ])

    def test_placeholders_and_other_checkboxes_are_ignored(self) -> None:
        template: str = (PLUGIN_ROOT / TEMPLATE_REL).read_text(encoding="utf-8")
        self.assertEqual(roadmap.scope_lines(template), [])
        self.assertIsNone(roadmap.scope_hash(template))

    def test_text_without_the_headings_has_no_scope(self) -> None:
        self.assertEqual(roadmap.scope_lines("# nothing here\n"), [])
        self.assertIsNone(roadmap.scope_hash(""))

    def test_hash_ignores_status_changes(self) -> None:
        finished: str = END_STATE.replace("| todo |\n| 4", "| done |\n| 4").replace("- [ ] webhook", "- [x] webhook")
        self.assertNotEqual(finished, END_STATE)
        self.assertEqual(roadmap.scope_hash(finished), roadmap.scope_hash(END_STATE))

    def test_hash_changes_when_a_section_is_added_or_renamed(self) -> None:
        added: str = END_STATE.replace("| 4 | <placeholder>", "| 4 | docs site")
        renamed: str = END_STATE.replace("ui shell", "ui kit")
        base: str | None = roadmap.scope_hash(END_STATE)
        self.assertNotEqual(roadmap.scope_hash(added), base)
        self.assertNotEqual(roadmap.scope_hash(renamed), base)

    def test_hash_changes_when_a_criterion_is_added_or_removed(self) -> None:
        added: str = END_STATE.replace("- [ ] <criterion>", "- [ ] audit log exists")
        removed: str = END_STATE.replace("- [x] migrations apply\n", "")
        base: str | None = roadmap.scope_hash(END_STATE)
        self.assertNotEqual(roadmap.scope_hash(added), base)
        self.assertNotEqual(roadmap.scope_hash(removed), base)


class StatusTests(unittest.TestCase):
    def test_counts_and_key(self) -> None:
        info: dict[str, Any] = roadmap.status(make_repo())
        self.assertEqual(set(info), {
            "end_state", "sections", "sections_outstanding", "acceptance", "acceptance_outstanding",
            "hash", "key", "approved", "approve_with",
        })
        self.assertEqual((info["sections"], info["sections_outstanding"]), (3, 2))
        self.assertEqual((info["acceptance"], info["acceptance_outstanding"]), (2, 1))
        self.assertEqual(info["key"], info["hash"][:KEY_LENGTH])
        self.assertTrue(info["end_state"])

    def test_not_approved_tells_the_person_what_to_add(self) -> None:
        info: dict[str, Any] = roadmap.status(make_repo())
        self.assertFalse(info["approved"])
        expected: str = json.dumps({"dts2_approvals": {"roadmap": [info["key"]]}})
        self.assertEqual(info["approve_with"], expected)

    def test_approved_only_when_the_key_is_in_the_human_file(self) -> None:
        repo: Path = make_repo()
        key: str = roadmap.status(repo)["key"]
        approve(repo, "000000000000")
        self.assertFalse(roadmap.status(repo)["approved"])
        approve(repo, key)
        info: dict[str, Any] = roadmap.status(repo)
        self.assertTrue(info["approved"])
        self.assertIsNone(info["approve_with"])

    def test_an_agent_file_elsewhere_does_not_approve(self) -> None:
        repo: Path = make_repo()
        key: str = roadmap.status(repo)["key"]
        write(repo / ".harness" / "approvals.json", json.dumps({"roadmap": [key]}))
        self.assertFalse(roadmap.status(repo)["approved"])

    def test_missing_end_state(self) -> None:
        info: dict[str, Any] = roadmap.status(make_repo(None))
        self.assertFalse(info["end_state"])
        self.assertEqual((info["sections"], info["acceptance"]), (0, 0))
        self.assertEqual((info["hash"], info["key"], info["approve_with"]), (None, None, None))
        self.assertFalse(info["approved"])

    def test_status_change_keeps_the_key(self) -> None:
        repo: Path = make_repo()
        before: str = roadmap.status(repo)["key"]
        write(repo / ".harness" / "end-state.md", END_STATE.replace("| todo |\n| 4", "| done |\n| 4"))
        after: dict[str, Any] = roadmap.status(repo)
        self.assertEqual(after["key"], before)
        self.assertEqual(after["sections_outstanding"], 1)


class RenderTests(unittest.TestCase):
    def test_render_layout(self) -> None:
        repo: Path = make_repo()
        key: str = roadmap.status(repo)["key"]
        lines: list[str] = roadmap.render(repo).splitlines()
        self.assertEqual(lines[0], "# Roadmap")
        self.assertIn(f"- scope key: {key}", lines)
        self.assertIn("- approved: no", lines)
        self.assertIn("## Sections", lines)
        self.assertIn("| # | section | status |", lines)
        self.assertIn("| 2 | payments webhook | blocked |", lines)
        self.assertIn("## Acceptance criteria", lines)
        self.assertIn("- [x] migrations apply", lines)
        self.assertIn("- [ ] webhook verifies signatures", lines)
        self.assertNotIn("<placeholder>", "\n".join(lines))

    def test_render_shows_approval(self) -> None:
        repo: Path = make_repo()
        approve(repo, roadmap.status(repo)["key"])
        self.assertIn("- approved: yes", roadmap.render(repo).splitlines())

    def test_render_is_deterministic(self) -> None:
        repo: Path = make_repo()
        self.assertEqual(roadmap.render(repo), roadmap.render(repo))


class CliTests(unittest.TestCase):
    def test_status_prints_json(self) -> None:
        repo: Path = make_repo()
        result = run_cli(repo, "status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), roadmap.status(repo))

    def test_hash_prints_the_full_digest(self) -> None:
        repo: Path = make_repo()
        result = run_cli(repo, "hash")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), roadmap.status(repo)["hash"])

    def test_hash_without_scope_prints_nothing_and_exits_one(self) -> None:
        for repo in (make_repo(None), make_repo("# End state\n")):
            result = run_cli(repo, "hash")
            self.assertEqual((result.returncode, result.stdout), (1, ""))

    def test_build_twice_gives_identical_files(self) -> None:
        repo: Path = make_repo()
        target: Path = repo / ".harness" / "roadmap.md"
        first = run_cli(repo, "build")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(json.loads(first.stdout), {"written": str(target)})
        text: str = target.read_text(encoding="utf-8")
        self.assertEqual(run_cli(repo, "build").returncode, 0)
        self.assertEqual(target.read_text(encoding="utf-8"), text)
        self.assertEqual(text, roadmap.render(repo))

    def test_build_without_end_state_fails(self) -> None:
        repo: Path = make_repo(None)
        result = run_cli(repo, "build")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout), {"error": "no end state"})
        self.assertFalse((repo / ".harness" / "roadmap.md").exists())

    def test_unknown_subcommand_is_a_usage_error(self) -> None:
        self.assertNotEqual(run_cli(make_repo(), "nope").returncode, 0)


if __name__ == "__main__":
    unittest.main()
