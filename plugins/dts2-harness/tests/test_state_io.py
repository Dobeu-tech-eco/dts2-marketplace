"""atomic_write: parents created, content replaced, no temp litter, modes kept, failures leave the original alone."""
from __future__ import annotations

import importlib.util
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import Final
from unittest import mock

STATE_IO: Final[Path] = Path(__file__).resolve().parent.parent / "scripts" / "state_io.py"
EXISTING_MODE: Final[int] = 0o640
TEST_UMASK: Final[int] = 0o022
NEW_FILE_MODE: Final[int] = 0o644
PRIVATE_MODE: Final[int] = 0o600
TEMP_MARKER: Final[str] = ".tmp-"


def load_state_io() -> ModuleType:
    spec = importlib.util.spec_from_file_location("state_io_under_test", STATE_IO)
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def leftovers(folder: Path) -> list[str]:
    return [p.name for p in folder.iterdir() if TEMP_MARKER in p.name]


class AtomicWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state_io: ModuleType = load_state_io()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root: Path = Path(self._tmp.name)

    def test_creates_parent_folders(self) -> None:
        target: Path = self.root / "a" / "b" / "state.md"
        returned: Path = self.state_io.atomic_write(target, "hello\n")
        self.assertEqual(returned, target)
        self.assertEqual(target.read_text(encoding="utf-8"), "hello\n")

    def test_accepts_string_path(self) -> None:
        target: Path = self.root / "s.txt"
        self.state_io.atomic_write(str(target), "x")
        self.assertEqual(target.read_text(encoding="utf-8"), "x")

    def test_replaces_content_and_leaves_no_temp_files(self) -> None:
        target: Path = self.root / "state.md"
        target.write_text("old", encoding="utf-8")
        self.state_io.atomic_write(target, "new")
        self.assertEqual(target.read_text(encoding="utf-8"), "new")
        self.assertEqual(leftovers(self.root), [])

    def test_newline_empty_keeps_crlf_bytes(self) -> None:
        target: Path = self.root / "crlf.yaml"
        self.state_io.atomic_write(target, "a\r\nb\r\n", newline="")
        self.assertEqual(target.read_bytes(), b"a\r\nb\r\n")

    def test_keeps_existing_file_mode(self) -> None:
        target: Path = self.root / "state.md"
        target.write_text("old", encoding="utf-8")
        os.chmod(target, EXISTING_MODE)
        self.state_io.atomic_write(target, "new")
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), EXISTING_MODE)

    def test_new_file_honors_umask(self) -> None:
        target: Path = self.root / "fresh.md"
        previous: int = os.umask(TEST_UMASK)
        try:
            self.state_io.atomic_write(target, "new")
        finally:
            os.umask(previous)
        mode: int = stat.S_IMODE(target.stat().st_mode)
        self.assertEqual(mode, NEW_FILE_MODE)
        self.assertNotEqual(mode, PRIVATE_MODE)

    def test_failed_replace_keeps_original_and_removes_temp(self) -> None:
        target: Path = self.root / "state.md"
        target.write_text("original", encoding="utf-8")
        with mock.patch.object(self.state_io.os, "replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                self.state_io.atomic_write(target, "replacement")
        self.assertEqual(target.read_text(encoding="utf-8"), "original")
        self.assertEqual(leftovers(self.root), [])


if __name__ == "__main__":
    unittest.main()
