"""scripts/ship_links.py: the linked-work check, the open-PR cap and the CLI."""
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
import ship_links  # noqa: E402

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "ship_links.py"
END_STATE: Final[str] = """# End state

## Sections
| # | section | serves component | files / area | depends on | complexity | status |
|---|---|---|---|---|---|---|
| 1 | first part | api | src/ | - | normal | todo |
| 2 | second part | api | src/ | - | normal | todo |
| 3 | <placeholder> | api | src/ | - | normal | todo |
"""
ACTION_ITEMS: Final[str] = """## Decisions

| item | context | status | owner | added |
|---|---|---|---|---|
| pick a name | - | open | | 2026-01-01 |
| pick a color | - | done | | 2026-01-01 |
"""
OPEN_ACTIONS: Final[set[str]] = {"D1"}
SHIP_CONFIG: Final[str] = "ship:\n  open_pr_cap: 3\nautopilot:\n  open_pr_cap: 9\n"
AUTOPILOT_CONFIG: Final[str] = "autopilot:\n  open_pr_cap: 9\n"
CUSTOM_CAP: Final[int] = 3
AUTOPILOT_CAP: Final[int] = 9


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def run_cli(repo: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--repo", str(repo), *args],
        capture_output=True, text=True, check=False, input=stdin,
    )


class CheckTests(unittest.TestCase):
    def verdict(self, body: str, actions: set[str] | None = None) -> dict[str, Any]:
        return ship_links.check(body, END_STATE, OPEN_ACTIONS if actions is None else actions)

    def test_real_section_number_is_ok(self) -> None:
        result: dict[str, Any] = self.verdict("Closes section 2 of the end state.")
        self.assertEqual(result, {"ok": True, "linked": ["2"], "reason": ""})

    def test_real_open_action_id_is_ok(self) -> None:
        result: dict[str, Any] = self.verdict("Resolves D1.")
        self.assertEqual(result, {"ok": True, "linked": ["D1"], "reason": ""})

    def test_feature_slug_is_ok(self) -> None:
        result: dict[str, Any] = self.verdict("Branch feature/ship-gate-2 lands here.")
        self.assertTrue(result["ok"])
        self.assertEqual(result["linked"], ["feature/ship-gate-2"])

    def test_missing_section_number_is_not_ok(self) -> None:
        result: dict[str, Any] = self.verdict("Closes section 9.")
        self.assertFalse(result["ok"])
        self.assertEqual(result["linked"], [])
        self.assertEqual(result["reason"], ship_links.MISSING_REASON)

    def test_placeholder_section_is_not_real(self) -> None:
        self.assertFalse(self.verdict("Closes section 3.")["ok"])

    def test_action_id_that_is_not_open_is_not_ok(self) -> None:
        self.assertFalse(self.verdict("Resolves D2.")["ok"])
        self.assertFalse(self.verdict("Resolves D1.", actions=set())["ok"])

    def test_empty_body_is_not_ok(self) -> None:
        result: dict[str, Any] = self.verdict("")
        self.assertEqual(result, {"ok": False, "linked": [], "reason": ship_links.MISSING_REASON})

    def test_only_resolved_tokens_are_listed(self) -> None:
        result: dict[str, Any] = self.verdict("section 1, section 9, D1, D7")
        self.assertEqual(result["linked"], ["1", "D1"])

    def test_links_in_body_returns_raw_tokens(self) -> None:
        body: str = "see section 4, A1 and feature/x.y-z"
        self.assertEqual(ship_links.links_in_body(body), {"4", "A1", "feature/x.y-z"})

    def test_section_ids_skips_placeholders_and_bad_input(self) -> None:
        self.assertEqual(ship_links.section_ids(END_STATE), {"1", "2"})
        self.assertEqual(ship_links.section_ids("no sections here"), set())


class ActionItemTests(unittest.TestCase):
    def test_open_ids_come_from_the_action_items_file(self) -> None:
        repo: Path = Path(tempfile.mkdtemp(prefix="dts2-ship-repo-"))
        write(repo / ".harness" / "action-items.md", ACTION_ITEMS)
        self.assertEqual(ship_links.open_action_item_ids(repo), {"D1"})

    def test_missing_file_gives_an_empty_set(self) -> None:
        repo: Path = Path(tempfile.mkdtemp(prefix="dts2-ship-repo-"))
        self.assertEqual(ship_links.open_action_item_ids(repo), set())


class CapTests(unittest.TestCase):
    def test_ship_key_wins(self) -> None:
        self.assertEqual(ship_links.cap_from_config(SHIP_CONFIG), CUSTOM_CAP)

    def test_falls_back_to_autopilot_then_default(self) -> None:
        self.assertEqual(ship_links.cap_from_config(AUTOPILOT_CONFIG), AUTOPILOT_CAP)
        self.assertEqual(ship_links.cap_from_config(""), ship_links.DEFAULT_CAP)
        self.assertEqual(ship_links.cap_from_config("", default=7), 7)

    def test_non_integer_value_falls_back_to_default(self) -> None:
        self.assertEqual(ship_links.cap_from_config("ship:\n  open_pr_cap: many\n"), ship_links.DEFAULT_CAP)

    def test_exceeded_at_below_and_above_the_cap(self) -> None:
        self.assertTrue(ship_links.cap_exceeded(5, 5))
        self.assertFalse(ship_links.cap_exceeded(4, 5))
        self.assertTrue(ship_links.cap_exceeded(6, 5))


class CliTests(unittest.TestCase):
    def fixture(self) -> Path:
        repo: Path = Path(tempfile.mkdtemp(prefix="dts2-ship-repo-"))
        write(repo / ".harness" / "end-state.md", END_STATE)
        write(repo / ".harness" / "action-items.md", ACTION_ITEMS)
        return repo

    def test_check_ok_from_a_body_file(self) -> None:
        repo: Path = self.fixture()
        body: Path = write(repo / "body.md", "Closes section 1.")
        result = run_cli(repo, "check", "--body", str(body))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"ok": True, "linked": ["1"], "reason": ""})

    def test_check_refuses_an_unlinked_body(self) -> None:
        repo: Path = self.fixture()
        body: Path = write(repo / "body.md", "Closes section 9.")
        result = run_cli(repo, "check", "--body", str(body))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(json.loads(result.stdout)["ok"])

    def test_check_reads_stdin_and_an_open_action_item(self) -> None:
        repo: Path = self.fixture()
        result = run_cli(repo, "check", "--body", "-", stdin="Resolves D1.")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["linked"], ["D1"])

    def test_check_honours_an_end_state_flag(self) -> None:
        repo: Path = Path(tempfile.mkdtemp(prefix="dts2-ship-repo-"))
        end_state: Path = write(repo / "other.md", END_STATE)
        result = run_cli(repo, "check", "--end-state", str(end_state), stdin="section 2")
        self.assertEqual(result.returncode, 0, result.stderr)
        missing = run_cli(repo, "check", stdin="section 2")
        self.assertEqual(missing.returncode, 1, missing.stderr)

    def test_cap_under_and_at_the_cap(self) -> None:
        repo: Path = self.fixture()
        config: Path = write(repo / "config.yaml", SHIP_CONFIG)
        under = run_cli(repo, "cap", "--config", str(config), "--open", "2")
        self.assertEqual(under.returncode, 0, under.stderr)
        self.assertEqual(json.loads(under.stdout), {"cap": CUSTOM_CAP, "exceeded": False})
        at = run_cli(repo, "cap", "--config", str(config), "--open", "3")
        self.assertEqual(at.returncode, 1, at.stderr)
        self.assertEqual(json.loads(at.stdout), {"cap": CUSTOM_CAP, "exceeded": True})

    def test_cap_with_a_missing_config_uses_the_default(self) -> None:
        repo: Path = self.fixture()
        result = run_cli(repo, "cap", "--config", str(repo / "absent.yaml"), "--open", "0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"cap": ship_links.DEFAULT_CAP, "exceeded": False})


if __name__ == "__main__":
    unittest.main()
