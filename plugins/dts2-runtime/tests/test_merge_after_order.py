"""merge_after edges (provides/consumes with stubbed_on) are honored by the merge order, not only depends_on."""
from __future__ import annotations

import sys
import unittest
from typing import Any, Final

from helpers import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
from lanes.common import LaneError  # noqa: E402
from lanes.merge import merge_sequence, unmerged_needs, valid_order  # noqa: E402

STAMP: Final[str] = "20261105-2"


def lane(lane_id: str, **extra: Any) -> dict[str, Any]:
    return {"id": lane_id, "item": f"S{lane_id}", "files": [f"src/{lane_id}.py"], "ids": {"D": []}, "depends_on": [],
            "tier": "standard", **extra}


def manifest(lanes: list[dict[str, Any]]) -> dict[str, Any]:
    return {"stamp": STAMP, "base": "abc1234", "scope": "single", "lanes": lanes}


def stubbed() -> dict[str, Any]:
    """a consumes 'api' (stubbed, so it starts at once) from c, which comes later in manifest order: a merges after c."""
    return manifest([lane("a", consumes=["api"], stubbed_on=["api"]), lane("b"), lane("c", provides=["api"])])


class MergeAfterOrderTests(unittest.TestCase):
    def test_valid_order_rejects_violation(self) -> None:
        self.assertFalse(valid_order(stubbed(), ["a", "b", "c"]))
        self.assertTrue(valid_order(stubbed(), ["c", "a", "b"]))
        self.assertTrue(valid_order(stubbed(), ["b", "c", "a"]))

    def test_merge_sequence_puts_provider_first(self) -> None:
        self.assertEqual(merge_sequence(stubbed()), ["b", "c", "a"])

    def test_unmerged_needs_reports_provider(self) -> None:
        m = stubbed()
        self.assertEqual(unmerged_needs(m, "a", []), ["c"])
        self.assertEqual(unmerged_needs(m, "a", ["c"]), [])
        self.assertEqual(unmerged_needs(m, "a", [], frozenset({"c"})), [])

    def test_unmerged_needs_is_transitive(self) -> None:
        m = manifest([lane("a", merge_after=["b"]), lane("b", depends_on=["c"]), lane("c")])
        self.assertEqual(unmerged_needs(m, "a", []), ["b", "c"])

    def test_cycle_message_mentions_merge_after(self) -> None:
        m = manifest([lane("a", merge_after=["b"]), lane("b", depends_on=["a"])])
        with self.assertRaises(LaneError) as caught:
            merge_sequence(m)
        self.assertIn("merge_after", str(caught.exception))

    def test_depends_on_only_manifest_unchanged(self) -> None:
        m = manifest([lane("a", depends_on=["b"]), lane("b"), lane("c")])
        self.assertEqual(merge_sequence(m), ["b", "a", "c"])
        self.assertTrue(valid_order(m, ["b", "a", "c"]))
        self.assertFalse(valid_order(m, ["a", "b", "c"]))
        self.assertEqual(unmerged_needs(m, "a", []), ["b"])
        self.assertEqual(unmerged_needs(m, "c", []), [])


if __name__ == "__main__":
    unittest.main()
