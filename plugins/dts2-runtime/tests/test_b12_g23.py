"""G-23: one event shape {v, ts, run, lane, kind, id}; an explicit id makes an append idempotent."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import checks  # noqa: E402
import state_io  # noqa: E402
from state_io import FileStore, MemoryStore, State  # noqa: E402

STAMP: Final[str] = "20261104-1"
LEDGER: Final[str] = f".harness/runs/{STAMP}/ledger.jsonl"
SHAPE: Final[set[str]] = {"v", "ts", "run", "lane", "kind", "id"}


class EventShapeTests(unittest.TestCase):
    def test_shape(self) -> None:
        event = state_io.make_event("check", run=STAMP, lane="a", name="lint")
        self.assertLessEqual(SHAPE, set(event))
        self.assertEqual((event["v"], event["run"], event["lane"], event["kind"], event["name"]), (1, STAMP, "a", "check", "lint"))
        self.assertIsInstance(event["ts"], int)
        self.assertTrue(event["id"])

    def test_run_level_events_use_a_dash_for_the_lane_and_run(self) -> None:
        event = state_io.make_event("env")
        self.assertEqual((event["run"], event["lane"]), ("-", "-"))

    def test_ids_are_unique_unless_given(self) -> None:
        self.assertNotEqual(state_io.make_event("x")["id"], state_io.make_event("x")["id"])
        self.assertEqual(state_io.make_event("x", id="same")["id"], "same")

    def test_event_id_is_deterministic(self) -> None:
        self.assertEqual(state_io.event_id("ballot", "s", "a"), state_io.event_id("ballot", "s", "a"))
        self.assertNotEqual(state_io.event_id("ballot", "s", "a"), state_io.event_id("ballot", "s", "b"))
        self.assertNotEqual(state_io.event_id("a", "bc"), state_io.event_id("ab", "c"))

    def test_the_shape_keys_cannot_be_overridden_by_fields(self) -> None:
        event = state_io.make_event("check", run=STAMP, lane="a", **{"v": 9})
        self.assertEqual((event["v"], event["kind"]), (1, "check"))

    def test_bad_run_or_lane_is_refused(self) -> None:
        with self.assertRaises(state_io.InvalidId):
            state_io.make_event("x", run="../..")
        with self.assertRaises(state_io.InvalidId):
            state_io.make_event("x", lane="a/b")


class AppendTests(unittest.TestCase):
    def stores(self) -> list[state_io.Store]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return [MemoryStore(), FileStore(tmp.name)]

    def test_explicit_id_is_idempotent(self) -> None:
        for store in self.stores():
            state = State(store)
            event = state_io.make_event("ballot", run=STAMP, id=state_io.event_id("ballot", "seed1"))
            self.assertTrue(state.append_event(LEDGER, event))
            self.assertFalse(state.append_event(LEDGER, dict(event)))
            self.assertEqual(len(state.read_rows(LEDGER)), 1)

    def test_racing_writers_with_one_id_write_one_row(self) -> None:
        for store in self.stores():
            state = State(store)
            wins: list[bool] = []
            guard = threading.Lock()

            def go() -> None:
                got = state.append_event(LEDGER, state_io.make_event("ballot", id="only"))
                with guard:
                    wins.append(got)

            threads = [threading.Thread(target=go) for _ in range(8)]
            [t.start() for t in threads]
            [t.join() for t in threads]
            self.assertEqual(wins.count(True), 1)
            self.assertEqual(len(state.read_rows(LEDGER)), 1)

    def test_generated_ids_append_without_reading_the_file(self) -> None:
        store = MemoryStore()
        state = State(store)
        for _ in range(3):
            state.append_event(LEDGER, state_io.make_event("check", run=STAMP, name="lint"))
        self.assertEqual(len(state.read_rows(LEDGER)), 3)
        self.assertEqual(store.locks, {})

    def test_events_filter(self) -> None:
        state = State(MemoryStore())
        state.append_event(LEDGER, state_io.make_event("check", run=STAMP, lane="a"))
        state.append_event(LEDGER, state_io.make_event("ballot", run=STAMP, lane="b"))
        self.assertEqual([e["kind"] for e in state.events(LEDGER, kind="ballot")], ["ballot"])
        self.assertEqual([e["lane"] for e in state.events(LEDGER, lane="a")], ["a"])

    def test_append_text_is_still_there_for_plain_logs(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="b12-"))
        state_io.append_text(tmp / "x.log", "one\n")
        state_io.append_text(tmp / "x.log", "two\n")
        self.assertEqual((tmp / "x.log").read_text(), "one\ntwo\n")


class ConsumerTests(unittest.TestCase):
    def test_checks_ledger_rows_carry_the_shape_and_still_work(self) -> None:
        folder = Path(tempfile.mkdtemp(prefix="b12-")) / ".harness" / "runs" / STAMP
        path = folder / "ledger.jsonl"
        checks.append_ledger(path, {"kind": "check", "name": "lint", "status": "fail", "head": "abc"})
        checks.append_ledger(path, {"kind": "check", "name": "lint", "status": "pass", "head": "abc"})
        rows = checks.read_ledger(path)
        self.assertTrue(all(SHAPE <= set(r) for r in rows))
        self.assertEqual(rows[0]["run"], STAMP)
        self.assertEqual(checks.latest_checks(rows)["lint"]["status"], "pass")
        self.assertEqual(len({r["id"] for r in rows}), 2)

    def test_a_ledger_row_with_an_id_is_written_once(self) -> None:
        path = Path(tempfile.mkdtemp(prefix="b12-")) / "runs" / STAMP / "ledger.jsonl"
        for _ in range(2):
            checks.append_ledger(path, {"kind": "ballot", "id": "b-1", "seed": "s"})
        self.assertEqual(len(checks.read_ledger(path)), 1)

    def test_blind_ballots_twice_with_one_seed_write_one_ledger_row(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="b12-"))
        proposals = tmp / "p"
        proposals.mkdir()
        (proposals / "one.md").write_text("# one\nsome text\n")
        (proposals / "two.md").write_text("# two\nother text\n")
        ledger = tmp / ".harness" / "runs" / STAMP / "ledger.jsonl"
        for _ in range(2):
            subprocess.run([sys.executable, "-I", str(SCRIPTS / "council.py"), "blind", "--proposals", str(proposals),
                            "--out", str(tmp / "out"), "--voters", "a,b,c", "--seed", "s1", "--ledger", str(ledger)],
                           capture_output=True, text=True, check=True)
        rows = [json.loads(line) for line in ledger.read_text().splitlines()]
        self.assertEqual([r["kind"] for r in rows], ["ballot"])

    def test_metrics_rows_use_the_shape_and_a_stamp_is_recorded_once(self) -> None:
        repo = Path(tempfile.mkdtemp(prefix="b12-"))
        for _ in range(2):
            subprocess.run([sys.executable, "-I", str(SCRIPTS / "metrics.py"), str(repo), "append", "--stamp", STAMP,
                            "--rounds", "2", "--duration", "9", "--verdict", "VERIFIED"],
                           capture_output=True, text=True, check=True)
        rows = [json.loads(line) for line in (repo / ".harness" / "metrics.jsonl").read_text().splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertLessEqual(SHAPE, set(rows[0]))
        self.assertEqual((rows[0]["kind"], rows[0]["rounds"], rows[0]["stamp"]), ("metrics", 2, STAMP))


if __name__ == "__main__":
    unittest.main()
