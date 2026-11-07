"""Merge order, merge target, merge-go grants and merge-done."""
from __future__ import annotations

import contextlib
import json
import re
import time
from pathlib import Path
from typing import Any, Final, Iterator

from son_launch import merge_config
from state_io import atomic_write

from .common import LEASE_NAME, MERGE_GO_JSON_NAME, MESSAGE_VERSION, LaneError, MERGE_GO_NAME, MERGE_ORDER_NAME, MERGE_PENDING_NAME, PHASE_BLOCKED, PHASE_INCOMPLETE, PHASE_PR_OPEN, PROTECTED_DEFAULTS, STATUS_NAME, binary, find_lane, run
from .audit import lane_audit
from .integration import INTEGRATION_LANE
from .journal import KIND_GRANTED, KIND_MERGED, note
from .leases import lease_epoch, read_lease
from .records import inside_son, lane_lock, read_json_object, son_refusal
from .runrecord import read_run, update_run

REVERT_STEP_PREFIX: Final[str] = "revert-"  # the step `open_revert_pr` tells the head to grant


def merge_needs(manifest: dict[str, Any]) -> dict[str, set[str]]:
    """Per lane, the lanes that must merge before it: depends_on plus the merge_after edges plan_graph derives from
    provides/consumes (the same edges merge-plan orders by). Ids that are not lanes of the manifest are ignored."""
    from plan_graph import contract_edges  # local: plan_graph imports this package
    ids: set[str] = {str(lane["id"]) for lane in manifest["lanes"]}
    _, merge_after, _ = contract_edges(manifest)
    return {str(lane["id"]): ({str(d) for d in (lane.get("depends_on") or [])} | merge_after.get(str(lane["id"]), set())) & ids
            for lane in manifest["lanes"]}


def merge_sequence(manifest: dict[str, Any]) -> list[str]:
    """Prerequisite order first (depends_on and merge_after), then manifest lane order (a stable topological sort). A cycle is a manifest error."""
    ids: list[str] = [str(lane["id"]) for lane in manifest["lanes"]]
    needs: dict[str, set[str]] = merge_needs(manifest)
    ordered: list[str] = []
    while len(ordered) < len(ids):
        ready: list[str] = [i for i in ids if i not in ordered and needs[i] <= set(ordered)]
        if not ready:
            raise LaneError("depends_on or merge_after has a cycle; no merge order exists")
        ordered.append(ready[0])
    return ordered


def unmerged_needs(manifest: dict[str, Any], lane_id: str, merged: list[str],
                   parked: frozenset[str] = frozenset()) -> list[str]:
    """Lanes `lane_id` must wait for (depends_on or merge_after), directly or through others, that have not merged yet
    (manifest order). A lane parked incomplete or blocked (`parked`) is not waited for: it does not hold up the merge order
    of the lanes behind it."""
    direct: dict[str, set[str]] = merge_needs(manifest)
    seen: set[str] = set()
    pending: list[str] = list(direct.get(lane_id, ()))
    while pending:
        dep: str = pending.pop()
        if dep not in seen and dep in direct:
            seen.add(dep)
            pending.extend(direct[dep])
    return [i for i in direct if i in seen and i not in merged and i not in parked]


def parked_lanes(runs_dir: Path, stamp: str, manifest: dict[str, Any]) -> frozenset[str]:
    """Lanes of the manifest whose son parked them incomplete or blocked."""
    ids: list[str] = [str(lane["id"]) for lane in manifest["lanes"]]
    return frozenset(i for i in ids if lane_phase(runs_dir, stamp, i) in (PHASE_INCOMPLETE, PHASE_BLOCKED))


def valid_order(manifest: dict[str, Any], order: Any) -> bool:
    """True when `order` lists every lane exactly once and puts each lane after the lanes it depends on or must merge after."""
    ids: list[str] = [str(lane["id"]) for lane in manifest["lanes"]]
    if not isinstance(order, list) or sorted(str(i) for i in order) != sorted(ids):
        return False
    position: dict[str, int] = {str(i): n for n, i in enumerate(order)}
    return all(position[d] < position[lane_id] for lane_id, needs in merge_needs(manifest).items() for d in needs if d in position)


def with_integration(manifest: dict[str, Any], files: list[str]) -> dict[str, Any]:
    """The manifest plus the integration lane: it depends on every other lane, so it merges last and goes through the same
    grant/done lifecycle (the head opens its PR, so it has no son status file)."""
    lanes: list[dict[str, Any]] = list(manifest["lanes"])
    if any(lane.get("id") == INTEGRATION_LANE for lane in lanes):
        return manifest
    integration: dict[str, Any] = {"id": INTEGRATION_LANE, "item": INTEGRATION_LANE, "tier": "standard", "ids": {},
                                   "files": list(files), "depends_on": [str(lane["id"]) for lane in lanes]}
    return {**manifest, "lanes": [*lanes, integration]}


def effective_manifest(manifest: dict[str, Any], runs_dir: Path) -> dict[str, Any]:
    """with_integration when merge-plan recorded an integration lane for this run, else the manifest itself."""
    saved: dict[str, Any] = read_json_object(runs_dir / str(manifest["stamp"]) / MERGE_ORDER_NAME)
    return with_integration(manifest, list(saved.get("integration_files") or [])) if saved.get("integration") else manifest


def merge_state(runs_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """The saved order when merge-plan recorded a valid one (probe-planned), else dependency then manifest order."""
    path: Path = runs_dir / str(manifest["stamp"]) / MERGE_ORDER_NAME
    saved: dict[str, Any] = read_json_object(path)
    full: dict[str, Any] = effective_manifest(manifest, runs_dir)
    order: Any = saved.get("order")
    return {"order": [str(i) for i in order] if valid_order(full, order) else merge_sequence(full),
            "merged": list(saved.get("merged") or []), "current": saved.get("current"),
            "integration": bool(saved.get("integration")), "integration_files": list(saved.get("integration_files") or [])}


def record_plan(manifest: dict[str, Any], runs_dir: Path, planned: list[str], integration_files: list[str]) -> bool:
    """Persist merge-plan's probe-planned order (and the integration lane, when files route to it) in merge-order.json, so
    merge-go grants in that order. Merged lanes keep their place at the front. False when nothing was recorded."""
    if inside_son():
        return False
    path: Path = runs_dir / str(manifest["stamp"]) / MERGE_ORDER_NAME
    with merge_lock(path):
        saved: dict[str, Any] = read_json_object(path)
        merged: list[str] = [str(i) for i in saved.get("merged") or []]
        full: dict[str, Any] = with_integration(manifest, integration_files) if integration_files else manifest
        wanted: list[str] = [i for i in planned if i != INTEGRATION_LANE] + ([INTEGRATION_LANE] if integration_files else [])
        order: list[str] = [*[i for i in merged if i in wanted], *[i for i in wanted if i not in merged]]
        if not valid_order(full, order):
            return False
        save_merge_state(path, {**saved, "order": order, "merged": merged, "current": saved.get("current"),
                                "integration": bool(integration_files), "integration_files": list(integration_files)})
    return True


def lane_phase(runs_dir: Path, stamp: str, lane_id: str) -> str:
    if lane_id == INTEGRATION_LANE and not (runs_dir / stamp / lane_id / STATUS_NAME).exists():
        return PHASE_PR_OPEN  # the head opens the integration PR after the other lanes merge; no son reports a phase for it
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
    if not state["order"]:
        return  # no order known yet: leave the guard to the lanes' status files rather than claim nothing is pending
    pending: list[str] = [str(lane) for lane in state["order"] if lane not in state["merged"]]
    atomic_write(path.parent / MERGE_PENDING_NAME, "".join(f"{lane}\n" for lane in pending))


def merge_order(manifest: dict[str, Any], runs_dir: Path) -> dict[str, Any]:
    """Write merge-order.json (the order, which lanes merged, which one holds the merge) and say who is next."""
    stamp: str = str(manifest["stamp"])
    path: Path = runs_dir / stamp / MERGE_ORDER_NAME
    manifest = effective_manifest(manifest, runs_dir)
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
        if unmerged_needs(manifest, lane_id, state["merged"], parked_lanes(runs_dir, stamp, manifest)):
            continue
        return lane_id if phase == PHASE_PR_OPEN else None
    return None


def merge_target_state(runs_dir: Path, stamp: str, cwd: Path) -> dict[str, Any]:
    """The branch this run merges into and whether a recorded yes allows the repo's default branch."""
    saved = read_run(runs_dir, stamp)
    config: dict[str, str] = merge_config(cwd)
    target: str = str(saved.merge_target or config["target"])
    defaults: set[str] = {config["default_branch"], *PROTECTED_DEFAULTS}
    return {"target": target, "is_default": target in defaults, "default_ok": saved.default_branch_yes is True}


def set_merge_target(runs_dir: Path, stamp: str, cwd: Path, branch: str | None, yes_default: bool) -> dict[str, Any]:
    """Record the run's merge target; `yes_default` is the explicit, recorded yes the default branch needs."""
    if inside_son():
        return son_refusal("merge-target")
    if branch is not None and not re.match(r"^[A-Za-z0-9._/-]+$", branch):
        raise LaneError(f"unsafe branch name {branch!r}")
    changes: dict[str, Any] = {**({"merge_target": branch} if branch else {}),
                               **({"default_branch_yes": True, "default_branch_yes_at": int(time.time())} if yes_default else {})}
    if changes:
        update_run(runs_dir, stamp, changes)
    if branch:
        atomic_write(runs_dir / stamp / "merge-target.txt", branch + "\n")  # read by the merge guard, which never opens run state
    return {"ok": True, "stamp": stamp, **merge_target_state(runs_dir, stamp, cwd)}


def base_tip(cwd: Path, target: str) -> str | None:
    code, out = run([*binary("DTS2_GIT_BIN", "git"), "rev-parse", f"refs/remotes/origin/{target}"], cwd)
    return out.strip() if code == 0 and re.match(r"^[0-9a-f]{7,40}$", out.strip()) else None


def audit_lane(manifest: dict[str, Any], runs_dir: Path, lane_id: str, head: str, cwd: Path, base: str | None = None) -> dict[str, Any]:
    """The ownership check merge-go runs, on its own: `base` defaults to the tip of the run's merge target."""
    manifest = effective_manifest(manifest, runs_dir)
    find_lane(manifest, lane_id)
    sha: str | None = base or base_tip(cwd, merge_target_state(runs_dir, str(manifest["stamp"]), cwd)["target"])
    if sha is None:
        return {"ok": False, "lane": lane_id, "violations": [], "changed": [], "detail": "cannot read the merge target; fetch it or pass --base"}
    return lane_audit(manifest, lane_id, head, sha, cwd)


def merge_go(manifest: dict[str, Any], runs_dir: Path, lane_id: str, head: str, cwd: Path = Path("."),
             base: str | None = None) -> dict[str, Any]:
    """Write the lane's merge-go.md, only when it is next in order, no other merge is in flight, the run's target is
    allowed, the base commit it was cleared against is known (recorded as `Base:` for the merge guard) and the lane changed only
    files it owns (`lane_audit`). A son is refused."""
    if inside_son():
        return {**son_refusal("merge-go"), "lane": lane_id}
    manifest = effective_manifest(manifest, runs_dir)
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
    gate: str | None = merge_gate_refusal(runs_dir, stamp, lane_id, state["target"], sha, cwd)
    if gate:
        return {"ok": False, "lane": lane_id, "detail": gate}
    audit: dict[str, Any] = lane_audit(manifest, lane_id, head, sha, cwd)
    if not audit["ok"]:
        outside: list[str] = [str(v.get("detail", "")) for v in audit["violations"]] or [str(audit.get("detail", "audit failed"))]
        return {"ok": False, "lane": lane_id, "detail": f"lane {lane_id} changed files outside its owned set: {'; '.join(outside)}",
                "violations": audit["violations"]}
    with merge_lock(runs_dir / stamp / MERGE_ORDER_NAME):
        return grant_merge(manifest, runs_dir, lane_id, head, state["target"], sha)


def merge_gate_refusal(runs_dir: Path, stamp: str, lane_id: str, target: str, sha: str, cwd: Path) -> str | None:
    """G-78: why a grant waits. A recorded base-health result that is red or stale, or another lane holding the repo-wide
    merge mutex. Neither record exists until the head takes them (`base-health`, `merge-mutex`), so a run that skips them is unchanged."""
    from .mergecomp import health_refusal, mutex_refusal  # noqa: PLC0415 - mergecomp imports this module lazily
    return health_refusal(runs_dir, stamp, target, sha) or mutex_refusal(cwd, stamp, lane_id)


def step_gate_refusal(runs_dir: Path, stamp: str, step: str, target: str, sha: str, cwd: Path) -> str | None:
    """The merge-go gates for an autopilot step. A `revert-<lane>` step is the repair for a red base and acts for the lane that
    holds the mutex, so it is held to the mutex under that lane's name and not to the base-health record."""
    if not step.startswith(REVERT_STEP_PREFIX):
        return merge_gate_refusal(runs_dir, stamp, step, target, sha, cwd)
    from .mergecomp import mutex_refusal  # noqa: PLC0415 - mergecomp imports this module lazily
    return mutex_refusal(cwd, stamp, step.removeprefix(REVERT_STEP_PREFIX))


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
    gate: str | None = step_gate_refusal(runs_dir, stamp, step, state["target"], sha, cwd)
    if gate:
        return {"ok": False, "step": step, "detail": gate}
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
    waiting_on: list[str] = unmerged_needs(manifest, lane_id, state["merged"], parked_lanes(runs_dir, stamp, manifest))
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
    payload: dict[str, Any] = {"v": MESSAGE_VERSION, "kind": "merge-go", "lane": lane_id,
                               "epoch": lease_epoch(read_lease(path.parent / LEASE_NAME)), "verified_head_sha": head,
                               "base_sha": base}
    atomic_write(path.parent / MERGE_GO_JSON_NAME, json.dumps(payload, indent=2) + "\n")  # G-44: the son checks its HEAD against it
    save_merge_state(runs_dir / stamp / MERGE_ORDER_NAME, {**state, "current": lane_id})
    note(runs_dir, stamp, KIND_GRANTED, lane=lane_id, key=int(time.time() * 1000), head=head, base=base, target=target)
    return {"ok": True, "lane": lane_id, "path": str(path), "head": head, "target": target, "base": base,
            "epoch": payload["epoch"]}


def record_merged(runs_dir: Path, stamp: str, lane_id: str) -> bool:
    """Record a lane that GitHub shows merged in merge-order.json the way `merge-done` does (merged list, merge released,
    pending list rewritten), without needing the manifest. False when it was already recorded."""
    path: Path = runs_dir / stamp / MERGE_ORDER_NAME
    with merge_lock(path):
        saved: dict[str, Any] = read_json_object(path)
        merged: list[str] = [str(i) for i in saved.get("merged") or []]
        if lane_id in merged:
            return False
        state: dict[str, Any] = {**saved, "order": [str(i) for i in saved.get("order") or []], "merged": [*merged, lane_id],
                                 "current": None if saved.get("current") == lane_id else saved.get("current")}
        save_merge_state(path, state)
    note(runs_dir, stamp, KIND_MERGED, lane=lane_id, key="")
    return True


def merge_done(manifest: dict[str, Any], runs_dir: Path, lane_id: str) -> dict[str, Any]:
    manifest = effective_manifest(manifest, runs_dir)
    with merge_lock(runs_dir / str(manifest["stamp"]) / MERGE_ORDER_NAME):
        return finish_merge(manifest, runs_dir, lane_id)


def finish_merge(manifest: dict[str, Any], runs_dir: Path, lane_id: str) -> dict[str, Any]:
    stamp: str = str(manifest["stamp"])
    state: dict[str, Any] = merge_state(runs_dir, manifest)
    if state["current"] != lane_id:
        return {"ok": False, "lane": lane_id, "detail": f"lane {lane_id} does not hold the merge"}
    done: dict[str, Any] = {**state, "merged": [*state["merged"], lane_id], "current": None}
    save_merge_state(runs_dir / stamp / MERGE_ORDER_NAME, done)
    note(runs_dir, stamp, KIND_MERGED, lane=lane_id, key="")
    return {"ok": True, "lane": lane_id, "merged": done["merged"], "all_merged": len(done["merged"]) >= len(done["order"])}
