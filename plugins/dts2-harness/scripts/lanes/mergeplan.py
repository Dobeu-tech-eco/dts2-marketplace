"""B6 merge plan: enqueue into a merge queue when the target has one, else a serial rebase, test, merge loop. A `git merge-tree
--write-tree` probe of every lane against the base moves lanes that would conflict behind the ones that merge clean (never past
a lane they depend on), and the integration lane (lockfiles, migrations, route tables, barrels, shared files) merges last.
Nothing here merges anything: it reads git and gh, returns the plan and records its order (and the integration lane) in
merge-order.json so merge-go grants in that order; merge-go still grants every merge."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

from .common import LaneError, binary, run
from .gitrefs import git_version_error, lane_ref
from .integration import INTEGRATION_LANE, route, shared_patterns
from .merge import merge_target_state, record_plan

PROBE_CLEAN: Final[str] = "clean"
PROBE_CONFLICT: Final[str] = "conflict"
PROBE_UNKNOWN: Final[str] = "unknown"
MODE_QUEUE: Final[str] = "queue"
MODE_SERIAL: Final[str] = "serial"
SERIAL_STEPS: Final[tuple[tuple[str, str], ...]] = (
    ("rebase", "git rebase <base> in the lane's worktree; a conflict here stops the loop for that lane"),
    ("test", "run .harness/checks.sh and the full suite on the rebased head"),
    ("merge", "lanes.py merge-go for the new head, gh pr merge, then lanes.py merge-done"),
)
QUEUE_STEP: Final[str] = "gh pr merge <lane PR> --auto (the queue rebases and tests it); lanes.py merge-done once it lands"


def merge_queue_enabled(cwd: Path, target: str) -> bool:
    """True when the branch rules of `target` include a merge queue. A gh failure or odd answer means no queue (serial loop)."""
    code, out = run([*binary("DTS2_GH_BIN", "gh"), "api", f"repos/:owner/:repo/rules/branches/{target}"], cwd)
    if code != 0:
        return False
    try:
        rules: Any = json.loads(out)
    except ValueError:
        return False
    return isinstance(rules, list) and any(isinstance(r, dict) and r.get("type") == "merge_queue" for r in rules)


def probe_lane(cwd: Path, base: str, ref: str) -> str:
    """Would merging `ref` into `base` conflict? `git merge-tree --write-tree` exits 1 with CONFLICT lines when it would."""
    code, out = run([*binary("DTS2_GIT_BIN", "git"), "merge-tree", "--write-tree", "--name-only", base, ref], cwd)
    if code == 0:
        return PROBE_CLEAN
    return PROBE_CONFLICT if code == 1 and "CONFLICT" in out else PROBE_UNKNOWN


def probe_all(manifest: dict[str, Any], cwd: Path, base: str) -> dict[str, str]:
    stamp: str = str(manifest["stamp"])
    ids: list[str] = [str(lane["id"]) for lane in manifest["lanes"]]
    if git_version_error(cwd) is not None:
        return {i: PROBE_UNKNOWN for i in ids}
    return {i: probe_lane(cwd, base, lane_ref(stamp, i)) for i in ids}


def reorder(manifest: dict[str, Any], probes: dict[str, str]) -> list[str]:
    """Stable topological order that takes the first ready lane which probed clean (or unknown), else the first ready one."""
    ids: list[str] = [str(lane["id"]) for lane in manifest["lanes"]]
    needs: dict[str, set[str]] = {str(lane["id"]): {str(d) for d in (lane.get("depends_on") or []) if str(d) in ids}
                                  for lane in manifest["lanes"]}
    ordered: list[str] = []
    while len(ordered) < len(ids):
        ready: list[str] = [i for i in ids if i not in ordered and needs[i] <= set(ordered)]
        if not ready:
            raise LaneError("depends_on has a cycle; no merge order exists")
        ordered.append(next((i for i in ready if probes.get(i) != PROBE_CONFLICT), ready[0]))
    return ordered


def plan_steps(order: list[str], mode: str) -> list[dict[str, str]]:
    if mode == MODE_QUEUE:
        return [{"lane": lane_id, "do": "enqueue", "detail": QUEUE_STEP} for lane_id in order]
    return [{"lane": lane_id, "do": do, "detail": detail} for lane_id in order for do, detail in SERIAL_STEPS]


def merge_plan(manifest: dict[str, Any], runs_dir: Path, cwd: Path, base: str | None = None) -> dict[str, Any]:
    stamp: str = str(manifest["stamp"])
    target: str = merge_target_state(runs_dir, stamp, cwd)["target"]
    ref: str = base or f"origin/{target}"
    probes: dict[str, str] = probe_all(manifest, cwd, ref)
    original: list[str] = [str(lane["id"]) for lane in manifest["lanes"]]
    order: list[str] = reorder(manifest, probes)
    integration: dict[str, Any] = route(manifest, shared_patterns(cwd))
    mode: str = MODE_QUEUE if merge_queue_enabled(cwd, target) else MODE_SERIAL
    full: list[str] = [*order, INTEGRATION_LANE] if integration["files"] else order
    recorded: bool = record_plan(manifest, runs_dir, order, list(integration["files"]))
    result: dict[str, Any] = {"ok": True, "stamp": stamp, "mode": mode, "target": target, "base": ref, "probe": probes,
                              "order": full, "reordered": order != original, "integration": integration,
                              "steps": plan_steps(full, mode), "recorded": recorded}
    if mode == MODE_SERIAL:
        result["note"] = "run merge-plan again after each merge: a lane that conflicted may now be clean"
    return result
