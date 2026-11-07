"""Review follow-ups: reconcile records merges and skips impossible orphan moves, grouping, lease files, digest, merge_after."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import findings  # noqa: E402
import plan_graph  # noqa: E402
import review_split  # noqa: E402
from lanes.merge import merge_state, next_to_merge  # noqa: E402
from lanes.mergeplan import PROBE_CONFLICT, reorder  # noqa: E402
from lanes.reconcile import ORPHANABLE, reconcile  # noqa: E402

STAMP: Final[str] = "20261105-9"
LATER: Final[int] = 4_000_000_000


def manifest(*lanes: dict[str, Any]) -> dict[str, Any]:
    return {"stamp": STAMP, "lanes": [{"tier": "standard", "ids": {}, **lane} for lane in lanes]}


class ReconcileMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runs = Path(tempfile.mkdtemp(prefix="dts2-fu2-")) / "runs"

    def seed(self, lane: str, phase: str, **more: Any) -> None:
        path = self.runs / STAMP / lane / "status.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"lane": lane, "status": phase, **more}), encoding="utf-8")

    def test_github_merged_lane_is_recorded_so_next_to_merge_moves_on(self) -> None:
        man = manifest({"id": "a", "files": ["a.py"]}, {"id": "b", "files": ["b.py"], "depends_on": ["a"]})
        self.seed("a", "pr-open")
        self.seed("b", "pr-open")
        merged_pr = [{"number": 7, "state": "MERGED", "url": "u"}]
        ask = lambda _c, branch: (merged_pr if branch.endswith("a") else [], None)  # noqa: E731
        out = reconcile(self.runs, STAMP, self.runs, now=LATER, ask=ask, dirty=lambda _w: False)
        self.assertEqual(out["actions"]["a"], "merged")
        state = merge_state(self.runs, man)
        self.assertEqual(state["merged"], ["a"])
        self.assertEqual(next_to_merge(self.runs, STAMP, state, man), "b")
        again = reconcile(self.runs, STAMP, self.runs, now=LATER, ask=ask, dirty=lambda _w: False)
        self.assertTrue(again["ok"])
        self.assertEqual(merge_state(self.runs, man)["merged"], ["a"], "recorded once")

    def test_empty_phase_is_not_orphanable_and_resume_count_is_untouched(self) -> None:
        self.assertNotIn("", ORPHANABLE)
        self.assertNotIn(None, ORPHANABLE)
        self.seed("a", "", worktree=str(self.runs))
        out = reconcile(self.runs, STAMP, self.runs, now=LATER, ask=lambda _c, _b: ([], None), dirty=lambda _w: True)
        self.assertNotIn(out["actions"]["a"], ("resume", "park"))
        saved = json.loads((self.runs / STAMP / "a" / "status.json").read_text(encoding="utf-8"))
        self.assertNotIn("resume_count", saved)


class SmallFixTests(unittest.TestCase):
    def test_path_group_uses_the_folder_not_the_file(self) -> None:
        self.assertEqual(review_split.path_group("src/app.py"), "src")
        self.assertEqual(review_split.path_group("README.md"), ".")
        self.assertEqual(review_split.path_group("a/b/c/d.py"), "a/b")

    def test_graph_lease_records_implied_lockfiles(self) -> None:
        lane = {"id": "a", "files": ["web/package.json", "web/src/x.ts"]}
        owned = plan_graph.owned_entries(lane)
        man = manifest(lane)
        tmp = Path(tempfile.mkdtemp(prefix="dts2-fu2-"))
        out = plan_graph.graph_lease(man, "a", tmp / "runs", tmp, False)
        self.assertTrue(out["ok"], out)
        record = json.loads(Path(out["lease"]).read_text(encoding="utf-8"))
        self.assertEqual(record["files"], sorted(owned))
        self.assertGreater(len(owned), 2, "the manifest's lockfile is owned")
        self.assertTrue(any("lock" in f for f in record["files"]))

    def test_digest_says_how_many_lines_it_dropped(self) -> None:
        many = [findings.Finding(f"f{i}.py", i, "HIGH", f"t{i}", ("x",)) for i in range(40)]
        text = findings.digest(many, "")
        self.assertIn("more line(s) not shown", text)
        self.assertIn("... 18 more", text)
        few = findings.digest(many[:3], "")
        self.assertNotIn("not shown", few)

    def test_reorder_respects_merge_after(self) -> None:
        man = manifest({"id": "a"}, {"id": "b", "merge_after": ["a"]}, {"id": "c"})
        order = reorder(man, {"a": PROBE_CONFLICT})
        self.assertLess(order.index("a"), order.index("b"))
        order2 = reorder(man, {"a": PROBE_CONFLICT, "c": PROBE_CONFLICT})
        self.assertLess(order2.index("a"), order2.index("b"))


if __name__ == "__main__":
    unittest.main()
