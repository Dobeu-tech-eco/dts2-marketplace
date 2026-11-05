"""agent-memory.py: a pre-4.0 managed block (dts2-harness markers) is migrated in place, never duplicated."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import Final

from test_agent_memory import END, START, load_module

OLD_START: Final[str] = "<!-- dts2-harness:start -->"
OLD_END: Final[str] = "<!-- dts2-harness:end -->"
OLD_BODY: Final[str] = "- Harness state: .harness/handoff/latest.md (resume with /dts2-harness:run resume)."
OLD_BLOCK: Final[str] = f"{OLD_START}\n# Project memory: proj\n\n{OLD_BODY}\n{OLD_END}\n"
BEFORE: Final[str] = "# My rules\n\nKeep it small.\n\n"
AFTER: Final[str] = "\n## Notes\n\nUser text after the block.\n"


def seeded_file(content: str) -> Path:
    folder: Path = Path(tempfile.mkdtemp(prefix="dts2-legacy-"))
    path: Path = folder / "AGENTS.md"
    path.write_text(content, encoding="utf-8")
    return path


class LegacyMarkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod: ModuleType = load_module()

    def test_legacy_block_migrates_to_exactly_one_new_block(self) -> None:
        path: Path = seeded_file(BEFORE + OLD_BLOCK + AFTER)
        self.assertEqual(self.mod.sync_file(path, "proj"), "migrated")
        text: str = path.read_text(encoding="utf-8")
        self.assertEqual(text.count(START), 1)
        self.assertEqual(text.count(END), 1)
        self.assertNotIn("dts2-harness", text)
        self.assertTrue(text.startswith(BEFORE + START))
        self.assertTrue(text.endswith(END + "\n" + AFTER))
        self.assertEqual(text, BEFORE + self.mod.managed_block("proj") + AFTER)

    def test_second_sync_is_unchanged(self) -> None:
        path: Path = seeded_file(BEFORE + OLD_BLOCK + AFTER)
        self.mod.sync_file(path, "proj")
        first: bytes = path.read_bytes()
        self.assertEqual(self.mod.sync_file(path, "proj"), "unchanged")
        self.assertEqual(path.read_bytes(), first)

    def test_legacy_block_at_end_without_trailing_newline(self) -> None:
        path: Path = seeded_file(BEFORE + OLD_START + "\nold\n" + OLD_END)
        self.assertEqual(self.mod.sync_file(path, "proj"), "migrated")
        text: str = path.read_text(encoding="utf-8")
        self.assertEqual(text.count(START), 1)
        self.assertTrue(text.startswith(BEFORE + START))

    def test_legacy_start_without_end_is_untouched(self) -> None:
        original: str = BEFORE + OLD_START + "\nhand-written, never closed\n"
        path: Path = seeded_file(original)
        self.assertEqual(self.mod.sync_file(path, "proj"), "unchanged")
        self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_legacy_end_before_start_is_untouched(self) -> None:
        original: str = f"{OLD_END}\n{OLD_START}\ntext\n"
        path: Path = seeded_file(original)
        self.assertEqual(self.mod.sync_file(path, "proj"), "unchanged")
        self.assertEqual(path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
