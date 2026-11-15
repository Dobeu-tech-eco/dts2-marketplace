"""ship_links.py: the roadmap-link check and the open-PR cap."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import Final

from helpers import PLUGIN_ROOT

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "ship_links.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ship_links", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["ship_links"] = module
    spec.loader.exec_module(module)
    return module


ship_links: Final[ModuleType] = load()

END_STATE: Final[str] = """# End state

## Sections
| # | section | serves component | files / area | depends on | complexity | status |
|---|---|---|---|---|---|---|
| 1 | data model | api | db/ | - | normal | done |
| 2 | <placeholder> | api | x/ | - | normal | todo |

## Acceptance criteria

### api

- [ ] it works
"""
LINKED: Final[str] = "## Linked work\n\n{ref}\n"


class CheckTests(unittest.TestCase):
    def test_real_section_in_linked_work_is_ok(self) -> None:
        result = ship_links.check(LINKED.format(ref="section 1"), END_STATE, set(), True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["linked"], ["1"])

    def test_placeholder_section_number_is_not_real(self) -> None:
        # section 2 is a `<placeholder>` row, so citing it does not resolve.
        self.assertFalse(ship_links.check(LINKED.format(ref="section 2"), END_STATE, set(), True)["ok"])

    def test_open_action_item_is_ok(self) -> None:
        self.assertTrue(ship_links.check(LINKED.format(ref="S2"), END_STATE, {"S2"}, True)["ok"])

    def test_action_id_not_open_is_not_ok(self) -> None:
        self.assertFalse(ship_links.check(LINKED.format(ref="S2"), END_STATE, set(), True)["ok"])

    def test_feature_slug_without_end_state_is_ok(self) -> None:
        self.assertTrue(ship_links.check(LINKED.format(ref="feature/x"), "", set(), False)["ok"])

    def test_feature_slug_with_end_state_is_not_ok(self) -> None:
        # the bypass the reviewers found: an ordinary feature branch must not pass when an end state exists.
        self.assertFalse(ship_links.check(LINKED.format(ref="feature/unrelated"), END_STATE, set(), True)["ok"])

    def test_empty_body_is_not_ok(self) -> None:
        self.assertFalse(ship_links.check("", END_STATE, set(), True)["ok"])

    def test_subsection_does_not_match(self) -> None:
        self.assertFalse(ship_links.check(LINKED.format(ref="a subsection 1 note"), END_STATE, set(), True)["ok"])

    def test_hyphenated_token_does_not_match_action_id(self) -> None:
        self.assertFalse(ship_links.check(LINKED.format(ref="SOC2-D1 control"), END_STATE, {"D1"}, True)["ok"])

    def test_ref_outside_linked_region_is_ignored(self) -> None:
        body = "## Summary\n\nsection 1 of the readme\n\n## Linked work\n\nnothing here\n"
        self.assertFalse(ship_links.check(body, END_STATE, set(), True)["ok"])

    def test_no_linked_heading_falls_back_to_whole_body(self) -> None:
        self.assertTrue(ship_links.check("fixes section 1", END_STATE, set(), True)["ok"])


class CapTests(unittest.TestCase):
    def test_ship_key_wins(self) -> None:
        self.assertEqual(ship_links.cap_from_config("ship:\n  open_pr_cap: 3\nautopilot:\n  open_pr_cap: 9\n"), 3)

    def test_autopilot_fallback(self) -> None:
        self.assertEqual(ship_links.cap_from_config("autopilot:\n  open_pr_cap: 7\n"), 7)

    def test_default_when_absent(self) -> None:
        self.assertEqual(ship_links.cap_from_config("budget:\n  usd: 1\n"), ship_links.DEFAULT_CAP)

    def test_non_integer_gives_default(self) -> None:
        self.assertEqual(ship_links.cap_from_config("ship:\n  open_pr_cap: many\n"), ship_links.DEFAULT_CAP)

    def test_exceeded_at_and_above_cap(self) -> None:
        self.assertFalse(ship_links.cap_exceeded(4, 5))
        self.assertTrue(ship_links.cap_exceeded(5, 5))
        self.assertTrue(ship_links.cap_exceeded(6, 5))


class CliTests(unittest.TestCase):
    def run_cli(self, repo: Path, *args: str, text: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "--repo", str(repo), *args],
            capture_output=True, text=True, check=False, input=text,
        )

    def repo_with_end_state(self) -> Path:
        repo = Path(tempfile.mkdtemp(prefix="dts2-links-"))
        (repo / ".harness").mkdir()
        (repo / ".harness" / "end-state.md").write_text(END_STATE, encoding="utf-8")
        return repo

    def test_check_ok_exit_zero(self) -> None:
        repo = self.repo_with_end_state()
        body = repo / "body.md"
        body.write_text(LINKED.format(ref="section 1"), encoding="utf-8")
        result = self.run_cli(repo, "check", "--body", str(body))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])

    def test_check_refused_exit_one(self) -> None:
        repo = self.repo_with_end_state()
        result = self.run_cli(repo, "check", "--body", "-", text="no link here")
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)["ok"])

    def test_check_missing_body_file_exits_two(self) -> None:
        repo = self.repo_with_end_state()
        result = self.run_cli(repo, "check", "--body", str(repo / "nope.md"))
        self.assertEqual(result.returncode, 2)

    def test_cap_exceeded_exit_one(self) -> None:
        repo = self.repo_with_end_state()
        config = repo / "config.yaml"
        config.write_text("ship:\n  open_pr_cap: 5\n", encoding="utf-8")
        over = self.run_cli(repo, "cap", "--config", str(config), "--open", "5")
        self.assertEqual(over.returncode, 1)
        self.assertTrue(json.loads(over.stdout)["exceeded"])
        under = self.run_cli(repo, "cap", "--config", str(config), "--open", "2")
        self.assertEqual(under.returncode, 0)


if __name__ == "__main__":
    unittest.main()
