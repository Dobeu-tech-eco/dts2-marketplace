"""G-10: Stamp and LaneId value objects; no runs/None/ and no ../ traversal can reach a path."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import state_io  # noqa: E402
from state_ids import InvalidId, LaneId, Stamp  # noqa: E402

BAD: Final[list[object]] = [None, "", "None", "null", "../../x", "a/b", "..", ".", " a", "a b", "a\nb", "a\x00b", 7, b"x", "x" * 80]


class StampTests(unittest.TestCase):
    def test_accepts_run_stamps(self) -> None:
        for good in ("20261104-101500", "20261104-1", "20261104-7"):
            self.assertEqual(str(Stamp.parse(good)), good)

    def test_rejects_everything_else(self) -> None:
        for bad in [*BAD, "2026-11-04", "20261104", "abcdefgh-123456", "20261104-1234567", "20261104-12/34"]:
            with self.assertRaises(InvalidId, msg=repr(bad)):
                Stamp.parse(bad)

    def test_new_formats_the_clock(self) -> None:
        self.assertEqual(str(Stamp.new(datetime(2026, 11, 4, 10, 15, 0))), "20261104-101500")

    def test_value_semantics(self) -> None:
        self.assertEqual(Stamp.parse("20261104-1"), Stamp.parse("20261104-1"))
        self.assertEqual(len({Stamp.parse("20261104-1"), Stamp.parse("20261104-1")}), 1)
        self.assertIs(Stamp.coerce(Stamp.parse("20261104-1")).value, Stamp.parse("20261104-1").value)


class LaneIdTests(unittest.TestCase):
    def test_accepts_lane_names(self) -> None:
        for good in ("a", "lane-1", "A1", "backend_api", "x" * 32):
            self.assertEqual(str(LaneId.parse(good)), good)

    def test_rejects_everything_else(self) -> None:
        for bad in [*BAD, "-a", "_a", "a.b", "x" * 33]:
            with self.assertRaises(InvalidId, msg=repr(bad)):
                LaneId.parse(bad)


class PathsUseTheValueObjectsTests(unittest.TestCase):
    def test_run_and_lane_paths_validate(self) -> None:
        self.assertEqual(state_io.run_rel(Stamp.parse("20261104-1"), "plan.md"), ".harness/runs/20261104-1/plan.md")
        self.assertEqual(state_io.lane_rel("20261104-1", LaneId.parse("a"), "lease.json"), ".harness/runs/20261104-1/a/lease.json")

    def test_none_and_traversal_never_reach_a_path(self) -> None:
        with self.assertRaises(InvalidId):
            state_io.run_rel(None)
        with self.assertRaises(InvalidId):
            state_io.run_rel("../../etc")
        with self.assertRaises(InvalidId):
            state_io.lane_rel("20261104-1", "../x")
        with self.assertRaises(InvalidId):
            state_io.State(state_io.MemoryStore()).lease("20261104-1", None)


if __name__ == "__main__":
    unittest.main()
