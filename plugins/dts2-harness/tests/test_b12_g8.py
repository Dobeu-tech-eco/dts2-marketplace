"""G-8: state_io is the only module that knows .harness/ paths; typed reads and writes; an in-memory fake store."""
from __future__ import annotations

import ast
import re
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import state_io  # noqa: E402
from state_io import FileStore, MemoryStore, State, StateError  # noqa: E402

# lanes.py is split by another worker (its constants move when it is re-pointed); ensure-ignored lists gitignore
# patterns and harness-lock names the protected shared records, neither of which reads or writes through a path.
ALLOWED: Final[frozenset[str]] = frozenset({"state_io.py", "lanes.py", "ensure-ignored.py", "harness-lock.py"})
HARNESS_PATH: Final[re.Pattern[str]] = re.compile(r"^\.harness(/|$)")


def code_strings(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(n.body[0].value) for n in ast.walk(tree)
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
        and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)
    }
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]


class StoreContract:
    """Run against FileStore and MemoryStore: the fake must behave like the disk."""

    def make(self) -> state_io.Store:
        raise NotImplementedError

    def test_write_read_exists_delete(self) -> None:
        s = self.make()
        self.assertIsNone(s.read_text(".harness/a.txt"))
        self.assertFalse(s.exists(".harness/a.txt"))
        s.write_text(".harness/a.txt", "one")
        s.write_text(".harness/a.txt", "two")
        self.assertEqual(s.read_text(".harness/a.txt"), "two")
        self.assertTrue(s.exists(".harness/a.txt"))
        s.delete(".harness/a.txt")
        s.delete(".harness/a.txt")  # deleting twice is fine
        self.assertFalse(s.exists(".harness/a.txt"))

    def test_append_keeps_every_line_and_writes_the_header_once(self) -> None:
        s = self.make()
        s.append_text(".harness/log.md", "a\n", header="# H\n")
        s.append_text(".harness/log.md", "b\n", header="# H\n")
        self.assertEqual(s.read_text(".harness/log.md"), "# H\na\nb\n")

    def test_create_exclusive_is_first_writer_wins(self) -> None:
        s = self.make()
        self.assertTrue(s.create_exclusive(".harness/x", "first"))
        self.assertFalse(s.create_exclusive(".harness/x", "second"))
        self.assertEqual(s.read_text(".harness/x"), "first")

    def test_list_and_dirs(self) -> None:
        s = self.make()
        for name in ("runs/r1/a.json", "runs/r1/b.json", "runs/r1/notes.md", "runs/r2/lane/x.json"):
            s.write_text(f".harness/{name}", "{}")
        self.assertEqual(s.list(".harness/runs/r1", "*.json"), [".harness/runs/r1/a.json", ".harness/runs/r1/b.json"])
        self.assertEqual(s.dirs(".harness/runs"), [".harness/runs/r1", ".harness/runs/r2"])
        self.assertEqual(s.list(".harness/nope"), [])
        self.assertEqual(s.dirs(".harness/nope"), [])


class FileStoreContract(StoreContract, unittest.TestCase):
    def make(self) -> state_io.Store:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return FileStore(tmp.name)

    def test_paths_cannot_escape_the_repo(self) -> None:
        with self.assertRaises(StateError):
            self.make().read_text(".harness/../../etc/passwd")


class MemoryStoreContract(StoreContract, unittest.TestCase):
    def make(self) -> state_io.Store:
        return MemoryStore()


class PathTests(unittest.TestCase):
    def test_names_are_built_in_one_place(self) -> None:
        self.assertEqual(state_io.rel("config.yaml"), ".harness/config.yaml")
        self.assertEqual(state_io.run_rel("20261104-1", "plan.md"), ".harness/runs/20261104-1/plan.md")
        self.assertEqual(state_io.lane_rel("20261104-1", "a", "lease.json"), ".harness/runs/20261104-1/a/lease.json")
        self.assertEqual(state_io.harness_path("/r", "x", "y.md"), Path("/r/.harness/x/y.md"))

    def test_no_other_script_hard_codes_a_harness_path(self) -> None:
        offenders = []
        for path in sorted(SCRIPTS.glob("*.py")):
            if path.name in ALLOWED:
                continue
            offenders += [f"{path.name}:{line} {value!r}" for line, value in code_strings(path) if HARNESS_PATH.match(value)]
        self.assertEqual(offenders, [])


class TypedStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = MemoryStore()
        self.state = State(self.store)

    def test_records_are_objects_or_none(self) -> None:
        self.assertIsNone(self.state.read_record(".harness/r.json"))
        self.store.write_text(".harness/r.json", "[1, 2]")
        self.assertIsNone(self.state.read_record(".harness/r.json"))
        self.store.write_text(".harness/r.json", "{torn")
        self.assertIsNone(self.state.read_record(".harness/r.json"))
        self.state.write_record(".harness/r.json", {"a": 1})
        self.assertEqual(self.state.read_record(".harness/r.json"), {"a": 1, "v": state_io.RECORD_VERSION})

    def test_merge_record(self) -> None:
        self.state.write_record(".harness/r.json", {"a": 1, "b": 2})
        merged = self.state.merge_record(".harness/r.json", {"b": 3, "c": 4})
        self.assertEqual({k: merged[k] for k in "abc"}, {"a": 1, "b": 3, "c": 4})

    def test_rows_skip_torn_and_non_object_lines(self) -> None:
        self.store.write_text(".harness/l.jsonl", '{"a": 1}\n{torn\n[1]\n{"b": 2}\n')
        self.assertEqual(self.state.read_rows(".harness/l.jsonl"), [{"a": 1}, {"b": 2}])
        self.state.append_row(".harness/l.jsonl", {"c": 3})
        self.assertEqual(self.state.read_rows(".harness/l.jsonl")[-1], {"c": 3, "v": 1})

    def test_named_records_and_listing(self) -> None:
        self.state.write_record(state_io.lane_rel("s1", "a", "lease.json"), {"epoch": 1})
        self.state.write_record(state_io.lane_rel("s1", "a", "status.json"), {"status": "pr-open"})
        self.assertEqual(self.state.lease("s1", "a")["epoch"], 1)
        self.assertEqual(self.state.status("s1", "a")["status"], "pr-open")
        self.assertIsNone(self.state.lease("s1", "zz"))
        self.assertEqual(self.state.runs(), ["s1"])
        self.assertEqual(self.state.lanes("s1"), ["a"])


if __name__ == "__main__":
    unittest.main()
