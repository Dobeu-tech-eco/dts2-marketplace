"""Merge order, merge target, merge-go grants and merge-done."""
from __future__ import annotations

import contextlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Iterator

from son_launch import SON_MARKER, merge_config
from state_io import atomic_write

from .common import LaneError, MERGE_GO_NAME, MERGE_ORDER_NAME, MERGE_PENDING_NAME, PHASE_BLOCKED, PHASE_INCOMPLETE, PHASE_PR_OPEN, PROTECTED_DEFAULTS, RUN_NAME, STATUS_NAME, binary, find_lane, run
from .leases import lane_lock
from .runstate import merge_json, read_json_object


def merge_sequence(manifest: dict[str, Any]) -> list[str]:
    """Dependency order first, then manifest lane order (a stable topological sort). A cycle is a manifest error."""
    ids: list[str] = [str(lane["id"]) for lane in manifest["lanes"]]
    needs: dict[str, set[str]] = {str(lane["id"]): {str(d) for d in (lane.get("depends_on") or []) if str(d) in ids}
                                  for lane in manifest["lanes"]}
    ordered: list[str] = []
    while len(ordered) < len(ids):
        ready: list[str] = [i for i in ids if i not in ordered and needs[i] <= set(ordered)]
        if not ready:
            raise LaneError("depends_on has a cycle; no merge order exists")
        ordered.append(ready[0])
    return ordered


def unmerged_needs(manifest: dict[str, Any], lane_id: str, merged: list[str]) -> list[str]:
    """Lanes `lane_id` depends on, directly or through others, that have not merged yet (manifest order)."""
    direct: dict[str, list[str]] = {str(lane["id"]): [str(d) for d in (lane.get("depends_on") or [])]
                                    for lane in manifest["lanes"]}
    seen: set[str] = set()
    pending: list[str] = list(direct.get(lane_id, []))
    while pending:
        dep: str = pending.pop()
        if dep not in seen and dep in direct:
            seen.add(dep)
            pending.extend(direct[dep])
    return [i for i in direct if i in seen and i not in merged]


def merge_state(runs_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    path: Path = runs_dir / str(manifest["stamp"]) / MERGE_ORDER_NAME
    saved: dict[str, Any] = read_json_object(path)
    return {"order": merge_sequence(manifest), "merged": list(saved.get("merged") or []),
            "current": saved.get("current")}


def lane_phase(runs_dir: Path, stamp: str, lane_id: str) -> str:
    return str(read_json_object(runs_dir / stamp / lane_id / STATUS_NAME).get("status", ""))


@contextlib.contextmanager
def merge_lock(path: Path) -> Iterator[None]:
    """Hold merge-order.json's lock across a read-check-write, so two heads cannot both take the merge."""
    with lane_lock(path) as held:
        if not held:
            raise LaneError(f"lock busy for {path}")
        yield


def save_merge_state(path: Path, state: dict[str, Any]) -> None:
    """Write merge-order.json and, beside it, the list of lanes still to merge that the merge guard reads to tell an active run
    from a finished one."""
    atomic_write(path, json.dumps(state, indent=2) + "\n")
    pending: list[str] = [str(lane) for lane in state["order"] if lane not in state["merged"]]
    atomic_write(path.parent / MERGE_PENDING_NAME, "".join(f"{lane}\n" for lane in pending))


def merge_order(manifest: dict[str, Any], runs_dir: Path) -> dict[str, Any]:
    """Write merge-order.json (the order, which lanes merged, which one holds the merge) and say who is next."""
    stamp: str = str(manifest["stamp"])
    path: Path = runs_dir / stamp / MERGE_ORDER_NAME
    with merge_lock(path):
        state: dict[str, Any] = merge_state(runs_dir, manifest)
        save_merge_state(path, state)
    return {"ok": True, "stamp": stamp, **state, "next": next_to_merge(runs_dir, stamp, state, manifest)}


def next_to_merge(runs_dir: Path, stamp: str, state: dict[str, Any], manifest: dict[str, Any]) -> str | None:
    """The first unmerged lane in order that is waiting at pr-open; None while a merge is in flight or an earlier lane
    is still building (it keeps its place). A lane parked incomplete or blocked loses its turn, but only for lanes that
    do not depend on it: a lane whose dependency (direct or transitive) is unmerged is never next."""
    if state["current"]:
        return None
    for lane_id in state["order"]:
        phase: str = lane_phase(runs_dir, stamp, lane_id)
        if lane_id in state["merged"] or phase in (PHASE_INCOMPLETE, PHASE_BLOCKED):
            continue
        if unmerged_needs(manifest, lane_id, state["merged"]):
            continue
        return lane_id if phase == PHASE_PR_OPEN else None
    return None


def merge_target_state(runs_dir: Path, stamp: str, cwd: Path) -> dict[str, Any]:
    """The branch this run merges into and whether a recorded yes allows the repo's default branch."""
    saved: dict[str, Any] = read_json_object(runs_dir / stamp / RUN_NAME)
    config: dict[str, str] = merge_config(cwd)
    target: str = str(saved.get("merge_target") or config["target"])
    defaults: set[str] = {config["default_branch"], *PROTECTED_DEFAULTS}
    return {"target": target, "is_default": target in defaults, "default_ok": saved.get("default_branch_yes") is True}


def set_merge_target(runs_dir: Path, stamp: str, cwd: Path, branch: str | None, yes_default: bool) -> dict[str, Any]:
    """Record the run's merge target; `yes_default` is the explicit, recorded yes the default branch needs."""
    if inside_son():
        return son_refusal("merge-target")
    if branch is not None and not re.match(r"^[A-Za-z0-9._/-]+$", branch):
        raise LaneError(f"unsafe branch name {branch!r}")
    changes: dict[str, Any] = {**({"merge_target": branch} if branch else {}),
                               **({"default_branch_yes": True, "default_branch_yes_at": int(time.time())} if yes_default else {})}
    if changes:
        merge_json(runs_dir / stamp / RUN_NAME, changes)
    if branch:
        atomic_write(runs_dir / stamp / "merge-target.txt", branch + "\n")  # read by the merge guard, which never opens run state
    return {"ok": True, "stamp": stamp, **merge_target_state(runs_dir, stamp, cwd)}


def base_tip(cwd: Path, target: str) -> str | None:
    code, out = run([*binary("DTS2_GIT_BIN", "git"), "rev-parse", f"refs/remotes/origin/{target}"], cwd)
    return out.strip() if code == 0 and re.match(r"^[0-9a-f]{7,40}$", out.strip()) else None


def inside_son() -> bool:
    """True in a son's process: the marker its env carries, or its lane branch prefix."""
    return bool(os.environ.get(SON_MARKER) or os.environ.get("DTS2_SON_BRANCH_PREFIX"))


def son_refusal(what: str) -> dict[str, Any]:
    return {"ok": False, "detail": f"{what} is the head's alone; a son never grants its own merge or changes the merge state"}


def merge_go(manifest: dict[str, Any], runs_dir: Path, lane_id: str, head: str, cwd: Path = Path("."),
             base: str | None = None) -> dict[str, Any]:
    """Write the lane's merge-go.md, only when it is next in order, no other merge is in flight, the run's target is
    allowed and the base commit it was cleared against is known (recorded as `Base:` for the merge guard). A son is refused."""
    if inside_son():
        return {**son_refusal("merge-go"), "lane": lane_id}
    find_lane(manifest, lane_id)
    stamp: str = str(manifest["stamp"])
    state: dict[str, Any] = merge_target_state(runs_dir, stamp, cwd)
    if state["is_default"] and not state["default_ok"]:
        return {"ok": False, "lane": lane_id, "detail": f"{state['target']} is the default branch; a run may merge there only "
                "after `lanes.py merge-target --yes-default-branch` records an explicit yes"}
    sha: str | None = base or base_tip(cwd, state["target"])
    if sha is not None and not re.match(r"^[0-9a-f]{7,40}$", sha):
        return {"ok": False, "lane": lane_id, "detail": "--base must be a commit sha"}
    if sha is None:
        return {"ok": False, "lane": lane_id, "detail": f"cannot read origin/{state['target']}; fetch it or pass --base"}
    with merge_lock(runs_dir / stamp / MERGE_ORDER_NAME):
        return grant_merge(manifest, runs_dir, lane_id, head, state["target"], sha)


def merge_go_step(runs_dir: Path, stamp: str, step: str, head: str, cwd: Path, base: str | None = None) -> dict[str, Any]:
    """Head-only grant for one autopilot step: the same `Verified head:` and `Base:` lines as a lane's merge-go.md, written to
    `<stamp>/<step>/merge-go.md`, with no lane order to follow. Refused inside a son, for a head that is not a commit sha, and for
    the default branch unless this run recorded the yes (`merge-target --yes-default-branch`)."""
    if inside_son():
        return {**son_refusal("merge-go-step"), "step": step}
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", step):
        raise LaneError(f"unsafe step name {step!r}")
    if not re.match(r"^[0-9a-f]{7,40}$", head):
        return {"ok": False, "step": step, "detail": "--head must be a commit sha"}
    state: dict[str, Any] = merge_target_state(runs_dir, stamp, cwd)
    if state["is_default"] and not state["default_ok"]:
        return {"ok": False, "step": step, "detail": f"{state['target']} is the default branch; a run may merge there only "
                "after `lanes.py merge-target --yes-default-branch` records an explicit yes"}
    sha: str | None = base or base_tip(cwd, state["target"])
    if sha is None or not re.match(r"^[0-9a-f]{7,40}$", sha):
        return {"ok": False, "step": step, "detail": f"cannot read origin/{state['target']}; fetch it or pass a sha with --base"}
    path: Path = runs_dir / stamp / step / MERGE_GO_NAME
    atomic_write(path, f"# Merge go for step {step}\n\nVerified head: {head}\nBase: {state['target']} {sha}\n"
                       f"Granted: {int(time.time())}\n")
    return {"ok": True, "step": step, "path": str(path), "head": head, "target": state["target"], "base": sha}


def grant_merge(manifest: dict[str, Any], runs_dir: Path, lane_id: str, head: str, target: str,
                base: str) -> dict[str, Any]:
    stamp: str = str(manifest["stamp"])
    state: dict[str, Any] = merge_state(runs_dir, manifest)
    if state["current"]:
        return {"ok": False, "lane": lane_id, "detail": f"lane {state['current']} holds the merge; one merge at a time"}
    waiting_on: list[str] = unmerged_needs(manifest, lane_id, state["merged"])
    if waiting_on:
        return {"ok": False, "lane": lane_id, "next": next_to_merge(runs_dir, stamp, state, manifest),
                "waiting_on": waiting_on,
                "detail": f"{lane_id} depends on unmerged lane {', '.join(waiting_on)}"}
    expected: str | None = next_to_merge(runs_dir, stamp, state, manifest)
    if expected != lane_id:
        return {"ok": False, "lane": lane_id, "next": expected,
                "detail": f"{lane_id} is not next to merge ({expected or 'none is waiting at pr-open'})"}
    path: Path = runs_dir / stamp / lane_id / MERGE_GO_NAME
    atomic_write(path, f"# Merge go for lane {lane_id}\n\nVerified head: {head}\nBase: {target} {base}\n"
                       f"Granted: {int(time.time())}\n")
    save_merge_state(runs_dir / stamp / MERGE_ORDER_NAME, {**state, "current": lane_id})
    return {"ok": True, "lane": lane_id, "path": str(path), "head": head, "target": target, "base": base}


def merge_done(manifest: dict[str, Any], runs_dir: Path, lane_id: str) -> dict[str, Any]:
    with merge_lock(runs_dir / str(manifest["stamp"]) / MERGE_ORDER_NAME):
        return finish_merge(manifest, runs_dir, lane_id)


def finish_merge(manifest: dict[str, Any], runs_dir: Path, lane_id: str) -> dict[str, Any]:
    stamp: str = str(manifest["stamp"])
    state: dict[str, Any] = merge_state(runs_dir, manifest)
    if state["current"] != lane_id:
        return {"ok": False, "lane": lane_id, "detail": f"lane {lane_id} does not hold the merge"}
    done: dict[str, Any] = {**state, "merged": [*state["merged"], lane_id], "current": None}
    save_merge_state(runs_dir / stamp / MERGE_ORDER_NAME, done)
    return {"ok": True, "lane": lane_id, "merged": done["merged"], "all_merged": len(done["merged"]) >= len(done["order"])}
