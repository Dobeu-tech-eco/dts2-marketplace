"""G-78 and G-80: the merge loop's safety nets. A recorded base-health result and the repo-wide merge mutex gate `merge-go`;
integration-lane routing keeps showing the owner what was refused, why, the alternative and the override. The post-merge fix
cap and the revert PR live in `journal.py` (they extend the revert action item); the supersede close is there too."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Final

from state_io import atomic_write, harness_path

from .common import LaneError, binary, run
from .integration import INTEGRATION_LANE, route
from .journal import note
from .records import inside_son, lane_lock, read_json_object, son_refusal

BASE_HEALTH_NAME: Final[str] = "base-health.json"
ROUTING_NAME: Final[str] = "routing.json"
MUTEX_NAME: Final[str] = "merge-mutex.json"
MUTEX_TTL_S: Final[int] = 3600  # a holder that never released (a dead head) loses the mutex after an hour
KIND_BASE_HEALTH: Final[str] = "base-health"
KIND_MUTEX_TAKEN: Final[str] = "merge-mutex-taken"
KIND_MUTEX_RELEASED: Final[str] = "merge-mutex-released"
CHECK_OK: Final[frozenset[str]] = frozenset({"success", "neutral", "skipped"})
OP_ACQUIRE: Final[str] = "acquire"
OP_RELEASE: Final[str] = "release"
OP_STATUS: Final[str] = "status"
MUTEX_OPS: Final[tuple[str, ...]] = (OP_ACQUIRE, OP_RELEASE, OP_STATUS)
KIND_REASONS: Final[dict[str, str]] = {
    "lockfile": "every lane that adds a dependency rewrites it, so two lanes owning it always conflict",
    "migration": "migrations are numbered in one sequence; two lanes writing them collide",
    "schema": "the schema file is one source of truth for every lane",
    "route-table": "one route table lists every lane's routes",
    "barrel": "an index file re-exports every lane's modules",
    "shared": "the repo's `lanes: shared_files` setting lists it as shared",
}


def check_runs(sha: str, cwd: Path) -> tuple[list[dict[str, Any]] | None, str]:
    code, out = run([*binary("DTS2_GH_BIN", "gh"), "api", f"repos/:owner/:repo/commits/{sha}/check-runs"], cwd)
    try:
        data: Any = json.loads(out) if code == 0 else None
    except ValueError:
        data = None
    runs: Any = data.get("check_runs") if isinstance(data, dict) else None
    return (runs, "") if isinstance(runs, list) else (None, "gh could not list the check runs of the base commit")


def judge_checks(runs: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """(failing names, pending names) of a commit's check runs."""
    failing: list[str] = [str(r.get("name")) for r in runs if r.get("status") == "completed" and r.get("conclusion") not in CHECK_OK]
    pending: list[str] = [str(r.get("name")) for r in runs if r.get("status") != "completed"]
    return failing, pending


def base_health(runs_dir: Path, stamp: str, cwd: Path) -> dict[str, Any]:
    """G-78: is the fetched `origin/<base>` green? Records the answer in `base-health.json`; `merge-go` refuses while the
    record is red, or while the base moved since it was taken. A gh or git failure is a red (unknown) answer, never green."""
    from .merge import base_tip, merge_target_state  # noqa: PLC0415 - merge imports this module
    if inside_son():
        return son_refusal("base-health")
    target: str = merge_target_state(runs_dir, stamp, cwd)["target"]
    code, _ = run([*binary("DTS2_GIT_BIN", "git"), "fetch", "origin", target], cwd)
    sha: str | None = base_tip(cwd, target) if code == 0 else None
    runs, why = check_runs(sha, cwd) if sha else (None, f"cannot fetch origin/{target}")
    failing, pending = judge_checks(runs or [])
    healthy: bool = runs is not None and not failing and not pending
    record: dict[str, Any] = {"ok": healthy, "target": target, "sha": sha, "failing": failing, "pending": pending,
                              "at": int(time.time()), "detail": why}
    atomic_write(runs_dir / stamp / BASE_HEALTH_NAME, json.dumps(record, indent=2) + "\n")
    if sha:
        note(runs_dir, stamp, KIND_BASE_HEALTH, key=f"{sha}-{int(healthy)}", sha=sha, healthy=healthy)
    return {**record, "stamp": stamp}


def health_refusal(runs_dir: Path, stamp: str, target: str, sha: str) -> str | None:
    """Why `merge-go` must not grant, from a recorded base-health result; None when there is none or it is green and current."""
    record: dict[str, Any] = read_json_object(runs_dir / stamp / BASE_HEALTH_NAME)
    if not record or record.get("target") != target:
        return None
    if not record.get("ok"):
        names: str = ", ".join(record.get("failing") or record.get("pending") or []) or str(record.get("detail") or "unknown")
        return f"origin/{target} is not green ({names}); fix the base first, then run `lanes.py base-health` again"
    if record.get("sha") != sha:
        return f"origin/{target} moved since base-health; run `lanes.py base-health` again"
    return None


def read_mutex(cwd: Path) -> dict[str, Any]:
    return read_json_object(harness_path(cwd, MUTEX_NAME))


def live_holder(record: dict[str, Any], now: int) -> bool:
    return bool(record.get("lane")) and now - int(record.get("at") or 0) < MUTEX_TTL_S


def mutex_refusal(cwd: Path, stamp: str, lane: str) -> str | None:
    """Why `lane` may not take its merge turn: another lane (or run) holds the repo-wide merge mutex. None when it is free or its own."""
    record: dict[str, Any] = read_mutex(cwd)
    if not live_holder(record, int(time.time())) or (record.get("stamp") == stamp and record.get("lane") == lane):
        return None
    return f"lane {record.get('lane')} of run {record.get('stamp')} holds the merge mutex until its post-merge walkthrough passes"


def merge_mutex(runs_dir: Path, stamp: str, lane: str, op: str, cwd: Path) -> dict[str, Any]:
    """G-78: the repo-wide merge mutex, held from the rebase until the post-merge walkthrough passes. `acquire` is refused while
    another live holder has it; `release` only by the holder; every take and release goes to the merge journal."""
    if inside_son():
        return son_refusal("merge-mutex")
    if op not in MUTEX_OPS:
        raise LaneError(f"--op is one of {', '.join(MUTEX_OPS)}")
    path: Path = harness_path(cwd, MUTEX_NAME)
    with lane_lock(path) as held:
        if not held:
            return {"ok": False, "lane": lane, "detail": "the merge mutex is busy; try again"}
        record: dict[str, Any] = read_json_object(path)
        mine: bool = record.get("stamp") == stamp and record.get("lane") == lane
        refusal: str | None = mutex_refusal(cwd, stamp, lane)
        if op == OP_STATUS:
            return {"ok": True, "lane": lane, "holder": record if live_holder(record, int(time.time())) else None}
        if op == OP_ACQUIRE and refusal:
            return {"ok": False, "lane": lane, "detail": refusal, "holder": record}
        if op == OP_RELEASE and record and not mine:
            return {"ok": False, "lane": lane, "detail": "only the holder releases the merge mutex", "holder": record}
        now: int = int(time.time())
        if op == OP_ACQUIRE:
            atomic_write(path, json.dumps({"stamp": stamp, "lane": lane, "at": now}, indent=2) + "\n")
            note(runs_dir, stamp, KIND_MUTEX_TAKEN, lane=lane, key=now)
        else:
            path.unlink(missing_ok=True)
            note(runs_dir, stamp, KIND_MUTEX_RELEASED, lane=lane, key=now)
    return {"ok": True, "lane": lane, "op": op}


def routing_records(integration: dict[str, Any]) -> list[dict[str, Any]]:
    """G-80: for each file the integration lane takes from a lane: what was refused, why, the alternative and the override."""
    rows: list[dict[str, Any]] = []
    for lane, files in sorted((integration.get("routed") or {}).items()):
        for item in files:
            kind: str = str(item.get("kind"))
            rows.append({"lane": lane, "file": item.get("file"), "kind": kind,
                         "refusal": f"lane {lane} may not own {item.get('file')}",
                         "reason": KIND_REASONS.get(kind, "every lane tends to touch it"),
                         "alternative": f"the {INTEGRATION_LANE} lane owns it and merges after the other lanes",
                         "override": f"lanes.py override {lane} --reason <why>; the owner's approval must be recorded first"})
    return rows


def record_routing(runs_dir: Path, stamp: str, manifest: dict[str, Any], shared: tuple[str, ...]) -> list[dict[str, Any]]:
    """Write the routing records of this manifest to `routing.json` (replacing the last set) and return them."""
    rows: list[dict[str, Any]] = routing_records(route(manifest, shared))
    if rows or (runs_dir / stamp / ROUTING_NAME).exists():
        atomic_write(runs_dir / stamp / ROUTING_NAME, json.dumps({"v": 1, "routing": rows}, indent=2) + "\n")
    return rows


def read_routing(runs_dir: Path, stamp: str) -> list[dict[str, Any]]:
    rows: Any = read_json_object(runs_dir / stamp / ROUTING_NAME).get("routing")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def routing_markdown(rows: list[dict[str, Any]]) -> str:
    """The routing records as the lines `report` prints under the table; empty when nothing was routed."""
    if not rows:
        return ""
    lines: list[str] = ["", "Integration routing", ""]
    lines.extend(f"- {r['refusal']} ({r['kind']}). Reason: {r['reason']}. Instead: {r['alternative']}. Override: {r['override']}."
                 for r in rows)
    return "\n".join(lines) + "\n"
