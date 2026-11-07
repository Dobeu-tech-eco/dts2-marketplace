"""Batch 13 follow-ups: a parked lane does not hold up the merge order of others."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Final
from unittest import mock

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lanes.merge import merge_go, merge_order, unmerged_needs  # noqa: E402
from lanes.phases import transition  # noqa: E402

STAMP: Final[str] = "20261105-9"
MANIFEST: Final = {"stamp": STAMP, "base": "abc1234", "scope": "single", "lanes": [
    {"id": "a", "item": "Sa", "files": ["src/a/x.py"], "ids": {}, "depends_on": [], "tier": "standard"},
    {"id": "b", "item": "Sb", "files": ["src/b/y.py"], "ids": {}, "depends_on": ["a"], "tier": "standard"}]}


class ParkedNeedsTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(sys.modules["lanes.merge"], "lane_audit", return_value={"ok": True, "violations": [], "changed": []})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_unmerged_needs_skips_parked_lanes(self) -> None:
        self.assertEqual(unmerged_needs(MANIFEST, "b", []), ["a"])
        self.assertEqual(unmerged_needs(MANIFEST, "b", [], frozenset({"a"})), [])

    def test_a_blocked_dependency_does_not_stop_the_next_merge(self) -> None:
        for phase, reason in (("incomplete", "timeout"), ("blocked", "waiting")):
            with self.subTest(phase=phase):
                repo = Path(tempfile.mkdtemp(prefix="dts2-fu-"))
                runs = repo / ".harness" / "runs"
                transition(runs, STAMP, "a", phase, reason=reason)
                transition(runs, STAMP, "b", "pr-open")
                self.assertEqual(merge_order(MANIFEST, runs)["next"], "b")
                self.assertTrue(merge_go(MANIFEST, runs, "b", "f" * 40, repo, "abc1234")["ok"])

    def test_a_running_dependency_still_holds_the_order(self) -> None:
        repo = Path(tempfile.mkdtemp(prefix="dts2-fu-"))
        runs = repo / ".harness" / "runs"
        transition(runs, STAMP, "a", "starting")
        transition(runs, STAMP, "b", "pr-open")
        self.assertIsNone(merge_order(MANIFEST, runs)["next"])
        self.assertFalse(merge_go(MANIFEST, runs, "b", "f" * 40, repo, "abc1234")["ok"])


if __name__ == "__main__":
    unittest.main()
