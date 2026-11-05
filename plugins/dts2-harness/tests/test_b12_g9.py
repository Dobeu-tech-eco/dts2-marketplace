"""G-9: every record carries "v": 1; migrate() walks a table of upgrades; migrate-all upgrades a whole .harness/ tree."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import state_io  # noqa: E402
from state_io import FileStore, MemoryStore, State, StateError  # noqa: E402

LEASE: Final[str] = ".harness/runs/20261104-1/a/lease.json"
STATUS: Final[str] = ".harness/runs/20261104-1/a/status.json"


def register_supervisor_kinds() -> None:
    """lanes.py owns these files and registers them with the port; the tests do it here."""
    for name, kind in (("run.json", "run"), ("budget.json", "budget"), ("merge-order.json", "merge-order")):
        state_io.register_kind(name, kind)
    state_io.register_rows("model-ledger.jsonl")


class VersionTests(unittest.TestCase):
    def setUp(self) -> None:
        register_supervisor_kinds()

    def test_writes_carry_the_current_version(self) -> None:
        state = State(MemoryStore())
        state.write_record(LEASE, {"epoch": 2})
        self.assertEqual(json.loads(state.store.read_text(LEASE))["v"], state_io.RECORD_VERSION)
        self.assertEqual(state_io.RECORD_VERSION, 1)

    def test_reading_an_old_record_upgrades_it_in_memory_only(self) -> None:
        store = MemoryStore({LEASE: '{"epoch": 3}'})
        record = State(store).read_record(LEASE)
        self.assertEqual(record, {"epoch": 3, "v": 1})
        self.assertEqual(store.read_text(LEASE), '{"epoch": 3}')

    def test_kinds_come_from_the_file_name(self) -> None:
        self.assertEqual(state_io.kind_of(LEASE), "lease")
        self.assertEqual(state_io.kind_of(STATUS), "status")
        self.assertEqual(state_io.kind_of(".harness/runs/s/run.json"), "run")
        self.assertEqual(state_io.kind_of(".harness/runs/s/budget.json"), "budget")
        self.assertEqual(state_io.kind_of(".harness/runs/s/merge-order.json"), "merge-order")
        self.assertIsNone(state_io.kind_of(".harness/random.json"))

    def test_an_unregistered_file_is_never_migrated(self) -> None:
        store = MemoryStore({".harness/runs/s/other.json": '{"a": 1}'})
        self.assertEqual(state_io.migrate_all(store)["migrated"], [])
        self.assertEqual(store.read_text(".harness/runs/s/other.json"), '{"a": 1}')


class MigrateTableTests(unittest.TestCase):
    def test_upgrades_run_in_order_from_the_stored_version(self) -> None:
        def rename(record: dict[str, Any]) -> dict[str, Any]:
            record["renamed"] = record.pop("old")
            return {**record, "v": 2}

        table = {"lease": {0: lambda r: {**r, "v": 1}, 1: rename}}
        out = state_io.migrate("lease", {"old": "x"}, table=table, target=2)
        self.assertEqual(out, {"v": 2, "renamed": "x"})
        out = state_io.migrate("lease", {"v": 1, "old": "y"}, table=table, target=2)
        self.assertEqual(out["renamed"], "y")

    def test_a_record_from_the_future_is_refused_not_downgraded(self) -> None:
        with self.assertRaises(StateError):
            state_io.migrate("lease", {"v": 9})

    def test_a_missing_step_is_an_error(self) -> None:
        with self.assertRaises(StateError):
            state_io.migrate("lease", {"v": 0}, table={"lease": {}}, target=1)

    def test_unknown_kinds_pass_through(self) -> None:
        self.assertEqual(state_io.migrate("mystery", {"a": 1}), {"a": 1})

    def test_input_is_not_mutated(self) -> None:
        original = {"epoch": 1}
        state_io.migrate("lease", original)
        self.assertEqual(original, {"epoch": 1})


class MigrateAllTests(unittest.TestCase):
    def setUp(self) -> None:
        register_supervisor_kinds()
        self.store = MemoryStore({
            LEASE: '{"epoch": 1}',
            STATUS: '{"status": "done", "v": 1}',
            ".harness/runs/20261104-1/run.json": '{"cli": "2.1.0"}',
            ".harness/runs/20261104-1/model-ledger.jsonl": '{"event": "retry"}\n{torn\n{"event": "x", "v": 1}\n',
            ".harness/runs/20261104-1/ledger.jsonl": '{"kind": "check"}\n',
            ".harness/runs/20261104-1/a/lease.json.lock": "pid",
            ".harness/runs/20261104-1/a/brief.md": "text",
        })

    def test_upgrades_records_and_rows_and_leaves_the_rest(self) -> None:
        report = state_io.migrate_all(self.store)
        self.assertEqual(json.loads(self.store.read_text(LEASE)), {"epoch": 1, "v": 1})
        self.assertEqual(json.loads(self.store.read_text(".harness/runs/20261104-1/run.json"))["v"], 1)
        rows = self.store.read_text(".harness/runs/20261104-1/model-ledger.jsonl").splitlines()
        self.assertEqual(json.loads(rows[0]), {"event": "retry", "v": 1})
        self.assertEqual(rows[1], "{torn")
        self.assertEqual(self.store.read_text(".harness/runs/20261104-1/a/brief.md"), "text")
        self.assertIn(LEASE, report["migrated"])
        self.assertNotIn(STATUS, report["migrated"])
        self.assertEqual(report["errors"], [])

    def test_idempotent(self) -> None:
        state_io.migrate_all(self.store)
        snapshot = dict(self.store.files)
        again = state_io.migrate_all(self.store)
        self.assertEqual(again["migrated"], [])
        self.assertEqual(self.store.files, snapshot)

    def test_future_versions_are_reported_not_touched(self) -> None:
        self.store.write_text(LEASE, '{"v": 7}')
        report = state_io.migrate_all(self.store)
        self.assertEqual(self.store.read_text(LEASE), '{"v": 7}')
        self.assertEqual([e["path"] for e in report["errors"]], [LEASE])

    def test_cli_migrate_all(self) -> None:
        repo = Path(tempfile.mkdtemp(prefix="b12-"))
        store = FileStore(repo)
        store.write_text(LEASE, '{"epoch": 4}')
        done = subprocess.run([sys.executable, "-I", str(SCRIPTS / "state_io.py"), "migrate-all", str(repo)],
                              capture_output=True, text=True, check=True)
        out: dict[str, Any] = json.loads(done.stdout)
        self.assertEqual(out["migrated"], [LEASE])
        self.assertEqual(json.loads(store.read_text(LEASE)), {"epoch": 4, "v": 1})


if __name__ == "__main__":
    unittest.main()
