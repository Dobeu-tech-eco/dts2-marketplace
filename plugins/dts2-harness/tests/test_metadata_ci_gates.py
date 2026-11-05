"""Review fixes for batch 5M: the size and read-only gates must fail closed on folded, block-list and flow-list frontmatter,
and changelog-join must be a no-op without fragments and report `#...` prose instead of dropping it."""
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from types import ModuleType

import test_metadata_ci as base
from helpers import PLUGIN_ROOT, make_tmp_home

JOIN: Path = PLUGIN_ROOT / "scripts" / "changelog-join.py"


def write_skill(root: Path, description_lines: str) -> None:
    skill: Path = root / "skills" / "a" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(f"---\nname: a\n{description_lines}---\nbody\n", encoding="utf-8")


class ContextTaxFailsClosed(unittest.TestCase):
    def setUp(self) -> None:
        self.mod: ModuleType = base.load_script("context-tax")
        self.root: Path = make_tmp_home()

    def test_folded_description_is_measured_whole_and_flagged(self) -> None:
        write_skill(self.root, "description: >-\n" + "".join("  " + "word " * 10 + "\n" for _ in range(40)))
        result = self.mod.report(self.root, 6000, 300)
        self.assertFalse(result["ok"])
        self.assertGreater(result["entries"][0]["chars"], 1500)
        self.assertTrue(any("over 300" in p for p in result["problems"]), result["problems"])
        self.assertTrue(any("`description` is written as" in p for p in result["problems"]), result["problems"])

    def test_block_scalar_and_flow_markers_are_problems_even_when_short(self) -> None:
        for value in ("description: |\n  short text\n", "description: [a, b]\n", "description:\n  short text\n"):
            write_skill(self.root, value)
            self.assertFalse(self.mod.report(self.root, 6000, 300)["ok"], value)

    def test_cli_exits_one_for_folded_description(self) -> None:
        write_skill(self.root, "description: >-\n  " + "x" * 2000 + "\n")
        proc = subprocess.run(["python3", "-I", str(PLUGIN_ROOT / "scripts" / "context-tax.py"), "--root", str(self.root)],
                              capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 1)
        self.assertGreaterEqual(json.loads(proc.stdout)["entries"][0]["chars"], 2000)

    def test_plain_one_line_values_still_pass(self) -> None:
        write_skill(self.root, "description: " + "d" * 40 + "\n")
        self.assertTrue(self.mod.report(self.root, 6000, 300)["ok"])


class ReadOnlyCheckParsesLists(unittest.TestCase):
    def parse(self, frontmatter: str) -> dict[str, str]:
        path: Path = make_tmp_home() / "agent.md"
        path.write_text(f"---\nname: agent\n{frontmatter}---\nbody\n", encoding="utf-8")
        return base.frontmatter_map(path)

    def test_block_list_tools_with_write_fails(self) -> None:
        meta = self.parse("tools:\n  - Read\n  - Write\n")
        self.assertEqual(base.tool_names(meta["tools"]), {"Read", "Write"})
        self.assertEqual(base.read_only_violations(meta), ["Write"])

    def test_flow_list_tools_with_write_fails(self) -> None:
        meta = self.parse("tools: [Read, Write]\n")
        self.assertEqual(base.tool_names(meta["tools"]), {"Read", "Write"})
        self.assertEqual(base.read_only_violations(meta), ["Write"])

    def test_clean_lists_and_csv_pass(self) -> None:
        for text in ("tools: Read, Grep\n", "tools: [Read, Grep]\n", "tools:\n  - Read\n  - Grep\n"):
            self.assertEqual(base.read_only_violations(self.parse(text)), [], text)

    def test_deny_list_must_cover_every_write_tool(self) -> None:
        self.assertEqual(base.read_only_violations(self.parse("disallowedTools: Write, Edit\n")), ["NotebookEdit"])
        self.assertEqual(base.read_only_violations(self.parse("disallowedTools: [Write, Edit, NotebookEdit]\n")), [])

    def test_empty_declaration_fails(self) -> None:
        self.assertEqual(base.read_only_violations(self.parse("tools:\n")), ["declares neither tools nor disallowedTools"])


class ChangelogJoinReview(unittest.TestCase):
    README: str = "# T\n\n## Changelog\n\n## Unreleased\n\n- newest line\n- 3.1.0 history entry\n- 2.0.0: first release.\n"

    def setUp(self) -> None:
        self.mod: ModuleType = base.load_script("changelog-join")
        self.root: Path = make_tmp_home()
        (self.root / "changelog.d").mkdir()
        self.readme: Path = self.root / "README.md"
        self.readme.write_text(self.README, encoding="utf-8")

    def test_apply_with_no_fragments_is_a_byte_identical_noop_and_idempotent(self) -> None:
        for _ in range(2):
            out = self.mod.run(self.root, None, True, "2026-11-04")
            self.assertTrue(out["applied"])
            self.assertEqual(self.readme.read_text(encoding="utf-8"), self.README)

    def test_release_with_nothing_after_ends_with_single_newline(self) -> None:
        (self.root / "changelog.d" / "batch-1.md").write_text("- one\n", encoding="utf-8")
        self.mod.run(self.root, "3.10.0", True, "2026-11-04")
        text: str = self.readme.read_text(encoding="utf-8")
        self.assertTrue(text.endswith("first release.\n") and not text.endswith("\n\n"), repr(text[-30:]))
        self.assertIn("## 3.10.0 (2026-11-04)\n\n- one\n- newest line\n\n- 3.1.0", text)

    def test_hash_prose_is_reported_not_silently_dropped(self) -> None:
        (self.root / "changelog.d" / "batch-1.md").write_text("# Real heading\n## Another\n- one\n#15 broke on squash\n#tag\n", encoding="utf-8")
        dry = self.mod.run(self.root, None, False, "2026-11-04")
        self.assertEqual(dry["dropped"], ["batch-1.md: #15 broke on squash", "batch-1.md: #tag"])
        refused = self.mod.run(self.root, None, True, "2026-11-04")
        self.assertIn("error", refused)
        self.assertEqual(self.readme.read_text(encoding="utf-8"), self.README)
        self.assertTrue((self.root / "changelog.d" / "batch-1.md").exists())

    def test_real_headings_are_still_skipped(self) -> None:
        (self.root / "changelog.d" / "batch-1.md").write_text("# Heading\n- one\n", encoding="utf-8")
        self.assertEqual(self.mod.run(self.root, None, False, "2026-11-04")["dropped"], [])


if __name__ == "__main__":
    unittest.main()
