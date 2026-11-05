"""Property tests for merge order: random dependency graphs, random interleavings of merge-go and merge-done.

Skipped unless hypothesis is importable (pip install -r requirements-dev.txt)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final
import unittest.mock as mock

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lanes.merge import merge_done, merge_go, merge_sequence, record_plan  # noqa: E402
from lanes.phases import transition  # noqa: E402
from state_io import HARNESS  # noqa: E402

try:
    from hypothesis import HealthCheck, given, settings
    from hypothesis import strategies as st
    HAVE_HYPOTHESIS = True
except ImportError:  # pragma: no cover - depends on the environment
    HAVE_HYPOTHESIS = False

STAMP: Final[str] = "20261105-8"
BASE: Final[str] = "abc1234"
HEAD: Final[str] = "def5678"
INTEGRATION: Final[str] = "integration"
MAX_EXAMPLES: Final[int] = 40
MIN_LANES: Final[int] = 2
MAX_LANES: Final[int] = 6
MAX_OPS: Final[int] = 40
AUDIT_OK: Final[dict[str, Any]] = {"ok": True, "violations": [], "changed": []}


def build_manifest(edges: list[list[bool]]) -> dict[str, Any]:
    """Lane n depends on lane m (m < n) where edges[n][m] is set, so every draw is a DAG."""
    lanes: list[dict[str, Any]] = [
        {"id": f"l{n}", "item": f"S{n}", "files": [f"src/l{n}/f.py"], "ids": {}, "tier": "standard",
         "depends_on": [f"l{m}" for m in range(n) if edges[n][m]]}
        for n in range(len(edges))]
    return {"stamp": STAMP, "base": BASE, "scope": "single", "lanes": lanes}


def read_state(runs: Path) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads((runs / STAMP / "merge-order.json").read_text(encoding="utf-8"))
    return parsed


def needs_of(manifest: dict[str, Any], integration: bool) -> dict[str, set[str]]:
    needs: dict[str, set[str]] = {str(lane["id"]): {str(d) for d in lane["depends_on"]} for lane in manifest["lanes"]}
    if integration:
        needs[INTEGRATION] = set(needs)
    return needs


def check_order(testcase: unittest.TestCase, needs: dict[str, set[str]], state: dict[str, Any]) -> None:
    merged: list[str] = state["merged"]
    testcase.assertEqual(len(merged), len(set(merged)), merged)
    for index, lane_id in enumerate(merged):
        testcase.assertTrue(needs[lane_id] <= set(merged[:index]), (lane_id, merged))  # prefix-consistent topological order
    current: Any = state["current"]
    testcase.assertTrue(current is None or (isinstance(current, str) and current not in merged), state)


def play(testcase: unittest.TestCase, manifest: dict[str, Any], integration: bool, ops: list[tuple[str, int]]) -> list[str]:
    repo = Path(tempfile.mkdtemp(prefix="dts2-hyp-merge-"))
    runs = repo / HARNESS / "runs"
    ids: list[str] = [str(lane["id"]) for lane in manifest["lanes"]]
    for lane_id in ids:
        transition(runs, STAMP, lane_id, "pr-open")
    if integration:
        testcase.assertTrue(record_plan(manifest, runs, merge_sequence(manifest), ["package-lock.json"]))
    candidates: list[str] = [*ids, *([INTEGRATION] if integration else [])]
    needs = needs_of(manifest, integration)
    with mock.patch.object(sys.modules["lanes.merge"], "lane_audit", return_value=AUDIT_OK), \
            mock.patch.object(sys.modules["lanes.merge"], "inside_son", return_value=False):
        for kind, pick in ops:
            before = read_state(runs) if (runs / STAMP / "merge-order.json").exists() else {"merged": [], "current": None}
            lane_id = candidates[pick % len(candidates)]
            if kind == "go":
                result = merge_go(manifest, runs, lane_id, HEAD, repo, BASE)
                if result["ok"]:
                    testcase.assertIsNone(before["current"], "a grant while another lane held the merge")
                    testcase.assertTrue(needs[lane_id] <= set(before["merged"]), (lane_id, before["merged"]))
                    testcase.assertNotIn(lane_id, before["merged"])
                    if lane_id == INTEGRATION:
                        testcase.assertEqual(set(before["merged"]), set(ids))  # integration is granted last
                    testcase.assertEqual(read_state(runs)["current"], lane_id)
                elif (runs / STAMP / "merge-order.json").exists():
                    testcase.assertEqual(read_state(runs)["current"], before["current"])
            else:
                target = before["current"] if kind == "finish" and before["current"] else lane_id
                result = merge_done(manifest, runs, target)
                testcase.assertEqual(result["ok"], before["current"] == target, (target, before))
            check_order(testcase, needs, read_state(runs) if (runs / STAMP / "merge-order.json").exists() else before)
        # drain what is left: granting the next lane and finishing it must always make progress until every lane merged
        for _ in range(2 * len(candidates) + 1):
            state = read_state(runs) if (runs / STAMP / "merge-order.json").exists() else {"merged": [], "current": None}
            if state["current"]:
                testcase.assertTrue(merge_done(manifest, runs, state["current"])["ok"])
                continue
            remaining = [c for c in candidates if c not in state["merged"]]
            if not remaining:
                break
            granted = [c for c in remaining if merge_go(manifest, runs, c, HEAD, repo, BASE)["ok"]]
            testcase.assertEqual(len(granted), 1, (remaining, state))
        final = read_state(runs)
    check_order(testcase, needs, final)
    testcase.assertEqual(sorted(final["merged"]), sorted(candidates))
    return final["merged"]


if HAVE_HYPOTHESIS:
    SCENARIOS = st.integers(MIN_LANES, MAX_LANES).flatmap(lambda n: st.tuples(
        st.lists(st.lists(st.booleans(), min_size=n, max_size=n), min_size=n, max_size=n),
        st.booleans(),
        st.lists(st.tuples(st.sampled_from(["go", "go", "done", "finish"]), st.integers(0, n)), min_size=1, max_size=MAX_OPS)))

    class MergeOrderProperties(unittest.TestCase):
        @settings(max_examples=MAX_EXAMPLES, deadline=None, suppress_health_check=list(HealthCheck))
        @given(SCENARIOS)
        def test_random_interleavings_keep_the_merge_order_sound(self, scenario: tuple[list[list[bool]], bool, list[tuple[str, int]]]) -> None:
            edges, integration, ops = scenario
            merged = play(self, build_manifest(edges), integration, ops)
            if integration:
                self.assertEqual(merged[-1], INTEGRATION)

else:

    @unittest.skip("hypothesis is not installed; see requirements-dev.txt")
    class MergeOrderProperties(unittest.TestCase):
        def test_requires_hypothesis(self) -> None:
            pass


if __name__ == "__main__":
    unittest.main()
