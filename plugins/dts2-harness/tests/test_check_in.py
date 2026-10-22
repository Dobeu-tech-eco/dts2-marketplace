"""scripts/check-in.py and the check-in skill: complete versus outstanding against the end state."""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "check-in.py"
SKILL: Final[Path] = PLUGIN_ROOT / "skills" / "check-in" / "SKILL.md"
EXPECTED_PERCENT: Final[int] = 66
END_STATE: Final[str] = """# End state

## Sections
| # | section | serves component | files / area | depends on | complexity | status |
|---|---|---|---|---|---|---|
| 1 | data model | api | db/ | - | normal | done |
| 2 | payments webhook (S2) | api | pay/ | 1 | design | blocked |
| 3 | ui shell | web | web/ | 1 | normal | todo |
Status values: todo | in-progress | blocked | done.

## Acceptance criteria

### api

- [x] migrations apply
- [ ] webhook verifies signatures
- [ ] <criterion>

## Assumptions

- [ ] not an acceptance box
"""


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_in_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    sys.modules["check_in_under_test"] = module
    spec.loader.exec_module(module)
    return module


def item(name: str, status: str) -> dict[str, str]:
    return {"name": name, "status": status}


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True, check=False,
    )


class SummarizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod: ModuleType = load_module()

    def test_two_complete_one_outstanding(self) -> None:
        summary: dict[str, Any] = self.mod.summarize(
            [item("a", "complete"), item("b", "complete"), item("c", "outstanding")],
        )
        self.assertEqual(
            (summary["total"], summary["complete"], summary["outstanding"], summary["percent"]),
            (3, 2, 1, EXPECTED_PERCENT),
        )
        self.assertEqual(summary["complete_items"], ["a", "b"])
        self.assertEqual(summary["outstanding_items"], ["c"])

    def test_empty_list_has_no_divide_by_zero(self) -> None:
        summary: dict[str, Any] = self.mod.summarize([])
        self.assertEqual((summary["total"], summary["complete"], summary["percent"]), (0, 0, 0))

    def test_all_complete_is_one_hundred_percent(self) -> None:
        self.assertEqual(self.mod.summarize([item("a", "complete")])["percent"], 100)

    def test_bad_status_or_shape_raises(self) -> None:
        for bad in ([item("a", "nope")], [{"status": "complete"}], ["a"]):
            with self.assertRaises(ValueError):
                self.mod.summarize(bad)


class RenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod: ModuleType = load_module()

    def test_render_has_header_and_both_checkbox_kinds(self) -> None:
        text: str = self.mod.render(self.mod.summarize([item("a", "complete"), item("b", "outstanding")]))
        self.assertTrue(text.startswith("1 of 2 complete (50%)"))
        self.assertIn("[x] a", text)
        self.assertIn("[ ] b", text)

    def test_render_empty_is_zero_of_zero(self) -> None:
        self.assertIn("0 of 0 complete (0%)", self.mod.render(self.mod.summarize([])))


class EndStateParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod: ModuleType = load_module()

    def test_sections_and_acceptance_boxes_become_items(self) -> None:
        summary: dict[str, Any] = self.mod.summarize(self.mod.items_from_end_state(END_STATE))
        self.assertIn("section 1: data model", summary["complete_items"])
        self.assertIn("section 2: payments webhook", summary["outstanding_items"])
        self.assertIn("section 3: ui shell", summary["outstanding_items"])
        self.assertIn("acceptance: migrations apply", summary["complete_items"])
        self.assertIn("acceptance: webhook verifies signatures", summary["outstanding_items"])
        self.assertEqual(summary["total"], 5)

    def test_template_placeholders_and_other_checkboxes_are_ignored(self) -> None:
        text: str = (PLUGIN_ROOT / "templates" / "end-state.md").read_text(encoding="utf-8")
        self.assertEqual(self.mod.items_from_end_state(text), [])


class CliTests(unittest.TestCase):
    def test_items_flag_prints_rendered_view(self) -> None:
        payload: str = json.dumps([item("a", "complete"), item("b", "complete"), item("c", "outstanding")])
        result = run_cli("--items", payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("2 of 3 complete (66%)"))

    def test_from_flag_reads_end_state_and_json_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            md: Path = Path(tmp) / "end-state.md"
            md.write_text(END_STATE, encoding="utf-8")
            js: Path = Path(tmp) / "status.json"
            js.write_text(json.dumps([item("x", "complete")]), encoding="utf-8")
            self.assertIn("2 of 5 complete (40%)", run_cli("--from", str(md)).stdout)
            self.assertIn("1 of 1 complete (100%)", run_cli("--from", str(js)).stdout)

    def test_json_flag_and_errors(self) -> None:
        data: dict[str, Any] = json.loads(run_cli("--items", "[]", "--json").stdout)
        self.assertEqual(data["total"], 0)
        self.assertEqual(run_cli("--items", "{nope").returncode, 2)
        self.assertEqual(run_cli("--items", '[{"name":"a","status":"x"}]').returncode, 2)
        self.assertEqual(run_cli("--from", "/nonexistent/status.md").returncode, 2)
        self.assertNotEqual(run_cli().returncode, 0)


class SkillTests(unittest.TestCase):
    def test_skill_exists_with_plain_description(self) -> None:
        self.assertTrue(SKILL.is_file())
        text: str = SKILL.read_text(encoding="utf-8")
        self.assertIn("name: check-in", text)
        match: re.Match[str] | None = re.search(r"^description: (.+)$", text, re.MULTILINE)
        self.assertIsNotNone(match)
        description: str = match.group(1) if match else ""
        self.assertNotIn("<", description)
        self.assertNotIn(">", description)

    def test_skill_calls_script_and_marks(self) -> None:
        text: str = SKILL.read_text(encoding="utf-8")
        for phrase in ("scripts/check-in.py", "[x]", "[ ]", "N of M complete", "end-state.md"):
            self.assertIn(phrase, text)

    def test_wired_into_onboard_and_readmes(self) -> None:
        self.assertIn("/dts2-harness:check-in", (PLUGIN_ROOT / "skills" / "onboard" / "SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("check-in", (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn("/dts2-harness:check-in", (PLUGIN_ROOT.parent.parent / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
