"""Run state the head owns: status, heartbeat, send-backs, fold, stop-check, report-check and the budget counter."""
from __future__ import annotations

import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Final

from contracts import Invalid, parse_report
from model_call import (
    is_overload, parse_result, read_budget, read_supervisor,
)
from state_io import atomic_write

from .common import BUDGET_NAME, DEFAULT_TIMEOUT_MIN, LANE_SECTIONS, LEASE_NAME, LEDGER_NAME, LEDGER_ROW, LaneError, MAX_DIFF_BYTES, MAX_SEND_BACKS, PHASE_BLOCKED, PHASE_INCOMPLETE, PHASE_PR_OPEN, PID_KEYS, REASON_STALLED, RESERVED_KEY, RUN_SECTIONS, SECONDS_PER_MINUTE, SEND_BACK_GLOB, SEND_BACK_NAME, SETTLED_PHASES, STATUS_CLOSED, STATUS_NAME, TERMINAL_PHASES, TIMEOUT_FIELD, UNREPORTED_KEY, WILDCARD_LANE, binary, norm, run
from .leases import busy, epoch_refusal, lease_epoch, stale_epoch
from .journal import done_groups, group_key, note_fold_plan
from .phases import heartbeat, transition  # noqa: F401 - heartbeat is re-exported for callers of this module
from .planner import read_checkin, read_setting
from .records import append_ledger, lane_lock, ledger_emitter, merge_json, read_json_object  # noqa: F401 - re-exported


def read_status_files(runs_dir: Path, stamp: str) -> list[tuple[Path, dict[str, Any]]]:
    run_dir: Path = runs_dir / stamp
    if not run_dir.is_dir():
        raise LaneError(f"no run at {run_dir}")
    found: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(run_dir.glob(f"*/{STATUS_NAME}")):
        try:
            data: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise LaneError(f"unreadable {path}: {exc}") from exc
        found.append((path, data if isinstance(data, dict) else {}))
    return found


def stale_after(cwd: Path) -> int:
    raw: str = read_setting(cwd, TIMEOUT_FIELD, str(DEFAULT_TIMEOUT_MIN))
    minutes: int = int(raw) if raw.isdigit() else DEFAULT_TIMEOUT_MIN
    return minutes * SECONDS_PER_MINUTE


def valid_beat(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def pid_alive(pid: Any) -> bool:
    """True when a process with this pid exists (signal 0 sends nothing). Bad pids and missing processes are not alive."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def lane_alive(data: dict[str, Any]) -> bool:
    """Whether the spawn process or its son, as recorded in status.json, is still running."""
    return any(pid_alive(data.get(key)) for key in PID_KEYS)


def lane_status(path: Path, data: dict[str, Any], threshold: int, now: int, stall_s: int) -> dict[str, Any]:
    """A lane with a heartbeat is judged against stall_minutes from the later of its heartbeat and its status.json
    mtime (a son that keeps writing status.json is alive); otherwise the file's age against builder_timeout_min."""
    phase: str = str(data.get("status", ""))
    updated: int = int(path.stat().st_mtime)
    beat: int | None = valid_beat(data.get("heartbeat"))
    last_seen: int = max(beat, updated) if beat is not None else updated
    limit: int = stall_s if beat is not None else threshold
    stale: bool = phase not in TERMINAL_PHASES | {PHASE_PR_OPEN} and now - last_seen > limit
    alive: bool = lane_alive(data)
    return {"lane": str(data.get("lane") or path.parent.name), "phase": phase, "updated": updated,
            "heartbeat": beat, "last_seen": last_seen, "stale": stale, "alive": alive,
            "incomplete_reason": REASON_STALLED if stale and not alive else None, "snapshot": None}


def snapshot_stall(folder: Path, path: Path, data: dict[str, Any], now: int) -> str:
    """Keep the stalled lane's last status.json and `git diff` in its run dir; the diff file's path."""
    atomic_write(folder / f"stall-{now}-status.json", path.read_text(encoding="utf-8"))
    worktree: Any = data.get("worktree")
    code, out = (run([*binary("DTS2_GIT_BIN", "git"), "diff"], Path(worktree))
                 if isinstance(worktree, str) and Path(worktree).is_dir() else (1, ""))
    diff: Path = folder / f"stall-{now}.diff"
    atomic_write(diff, out[:MAX_DIFF_BYTES] if code == 0 else "")
    return str(diff)


def recent_snapshot(folder: Path, now: int, stall_s: int) -> str | None:
    """The newest stall diff in the lane's run dir when it is younger than stall_s, so polling a stale but live lane
    does not write a new snapshot every time."""
    diffs: list[Path] = sorted(folder.glob("stall-*.diff"), key=lambda p: p.stat().st_mtime)
    return str(diffs[-1]) if diffs and now - diffs[-1].stat().st_mtime < stall_s else None


def mark_stalled(runs_dir: Path, stamp: str, path: Path, data: dict[str, Any], row: dict[str, Any], now: int) -> None:
    row["snapshot"] = snapshot_stall(path.parent, path, data, now)
    transition(runs_dir, stamp, row["lane"], PHASE_INCOMPLETE, reason=REASON_STALLED,
               extra={"stalled_at": now, "snapshot": row["snapshot"]})
    append_ledger(runs_dir, stamp, {"lane": row["lane"], "event": "stalled", "last_seen": row["last_seen"],
                                    "snapshot": row["snapshot"]})


def status(runs_dir: Path, stamp: str, cwd: Path) -> dict[str, Any]:
    """Every son's phase from status.json. A lane with a heartbeat is stalled after stall_minutes without one, any other
    quiet non-terminal lane after builder_timeout_min (autopilot §4); a stalled lane is snapshotted and marked incomplete,
    unless its son process is still running: then it is reported `stale` and `alive`, snapshotted, and left as it is
    (the wall-clock deadline of `spawn` ends it), so a lane is never parked or resumed under a running son."""
    threshold: int = stale_after(cwd)
    stall_s: int = read_supervisor(cwd)["stall_minutes"] * SECONDS_PER_MINUTE
    now: int = int(time.time())
    rows: list[dict[str, Any]] = []
    for path, data in read_status_files(runs_dir, stamp):
        row: dict[str, Any] = lane_status(path, data, threshold, now, stall_s)
        if row["stale"] and row["alive"]:
            row["snapshot"] = recent_snapshot(path.parent, now, stall_s) or snapshot_stall(path.parent, path, data, now)
        elif row["stale"]:
            mark_stalled(runs_dir, stamp, path, data, row, now)
        rows.append(row)
    return {"ok": True, "stamp": stamp, "stale_after_s": threshold, "stall_after_s": stall_s, "lanes": rows}


def sendback(runs_dir: Path, stamp: str, lane_id: str, reason: str) -> dict[str, Any]:
    folder: Path = runs_dir / stamp / lane_id
    count: int = len(list(folder.glob(SEND_BACK_GLOB)))
    if count >= MAX_SEND_BACKS:
        return {"ok": False, "lane": lane_id, "count": count, "path": None,
                "detail": f"{MAX_SEND_BACKS} send-backs already used; the lane ends incomplete"}
    path: Path = folder / SEND_BACK_NAME.format(n=count + 1)
    atomic_write(path, f"# Send-back {count + 1} for lane {lane_id}\n\n{reason}\n")
    return {"ok": True, "lane": lane_id, "count": count + 1, "path": str(path)}


def release(runs_dir: Path, stamp: str, lane_id: str, epoch: int | None = None) -> dict[str, Any]:
    path: Path = runs_dir / stamp / lane_id / LEASE_NAME
    with lane_lock(path) as held:
        if not held:
            return busy(lane_id)
        return close_lease(path, lane_id, epoch)


def close_lease(path: Path, lane_id: str, epoch: int | None) -> dict[str, Any]:
    try:
        record: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LaneError(f"no lease at {path}: {exc}") from exc
    stored: int = lease_epoch(record)
    if stale_epoch(epoch, stored):
        return epoch_refusal(lane_id, int(epoch or 0), stored)
    closed: dict[str, Any] = {**record, "status": STATUS_CLOSED, "released": int(time.time())}
    atomic_write(path, json.dumps(closed, indent=2) + "\n")
    return {"ok": True, "lane": lane_id, "lease": str(path), "status": STATUS_CLOSED}


def add_to_group(group: dict[str, Any], data: dict[str, Any], files: set[str]) -> None:
    group["lanes"].append(str(data.get("lane")))
    group["tasks"].extend(str(t) for t in data.get("tasks", []))
    group["blocked_by"] = sorted(set(group["blocked_by"]) | {str(i) for i in data.get("blocked_by", [])})
    if isinstance(data.get("pr"), int):
        group["prs"].append(data["pr"])
    group["_files"] |= files


def fold(runs_dir: Path, stamp: str) -> dict[str, Any]:
    """Group blocked lanes with disjoint files so they ship on the fewest PRs; never splits a lane. Each group carries a
    stable `key` and whether `fold-done` already recorded its PR, so a fold run again after a crash resumes with the rest."""
    groups: list[dict[str, Any]] = []
    for _, data in read_status_files(runs_dir, stamp):
        if data.get("status") != PHASE_BLOCKED:
            continue
        files: set[str] = {norm(str(f)) for f in data.get("files", [])}
        target: dict[str, Any] | None = next((g for g in groups if not (g["_files"] & files)), None)
        if target is None:
            target = {"lanes": [], "tasks": [], "blocked_by": [], "prs": [], "_files": set()}
            groups.append(target)
        add_to_group(target, data, files)
    shipped: set[str] = done_groups(runs_dir, stamp)
    public: list[dict[str, Any]] = [{**{k: v for k, v in g.items() if not k.startswith("_")}, "key": group_key(g["lanes"]),
                                     "done": group_key(g["lanes"]) in shipped} for g in groups]
    if public:
        note_fold_plan(runs_dir, stamp, public)
    return {"ok": True, "stamp": stamp, "groups": public, "open_prs": len(public),
            "remaining": [g["key"] for g in public if not g["done"]]}


def ledger_prs(runs_dir: Path, stamp: str) -> set[int]:
    path: Path = runs_dir / stamp / LEDGER_NAME
    if not path.is_file():
        return set()
    return {int(m.group(1)) for m in LEDGER_ROW.finditer(path.read_text(encoding="utf-8"))}


def stop_check(runs_dir: Path, stamp: str, checkin: Path) -> dict[str, Any]:
    """fullauto may stop only when check-in has nothing outstanding and every lane is done or blocked in the ledger."""
    outstanding: list[str] = sorted(read_checkin(checkin))
    lanes: list[dict[str, Any]] = [d for _, d in read_status_files(runs_dir, stamp)]
    ledgered: set[int] = ledger_prs(runs_dir, stamp)
    blocked_without: list[str] = sorted(str(d.get("lane")) for d in lanes
                                        if d.get("status") == PHASE_BLOCKED and d.get("pr") not in ledgered)
    active: list[str] = sorted(str(d.get("lane")) for d in lanes if d.get("status") not in SETTLED_PHASES)
    stop: bool = not outstanding and not active and not blocked_without
    return {"ok": True, "stamp": stamp, "stop": stop, "outstanding": outstanding, "active": active,
            "blocked_without_ledger": blocked_without, "lanes": len(lanes)}


MISSING_ROW: Final[re.Pattern[str]] = re.compile(r"^(?:lane (\S+)|run): missing '(.+)'$")


def report_check(path: Path, lane_ids: list[str]) -> dict[str, Any]:
    try:
        text: str = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LaneError(f"cannot read report {path}: {exc}") from exc
    parsed = parse_report(text, lane_ids, LANE_SECTIONS, RUN_SECTIONS)
    rows = [MISSING_ROW.match(m) for m in (parsed.reasons if isinstance(parsed, Invalid) else ())]
    missing: list[dict[str, str]] = [{"lane": row.group(1) or WILDCARD_LANE, "section": row.group(2)} for row in rows if row]
    return {"ok": not missing, "report": str(path), "missing": missing}


def new_budget(now: int) -> dict[str, Any]:
    return {"started": now, "spent_usd": 0.0, "unknown_calls": 0, UNREPORTED_KEY: 0, "loops": 0, "lanes": {}}


def charge(budget: dict[str, Any], key: str, session: str | None, reported: float | None,
           new_round: bool = True, refused: bool = False) -> tuple[dict[str, Any], float | None]:
    """Add one call's spend to the counter. `reported` is what the CLI printed for the whole session, which is
    cumulative on a resumed session: charge only the part above what that session already reported. A missing or zero
    cost is unknown (counted in unknown_calls), never zero spend. A refused attempt (`reported` of 0.0 flagged by
    `refused`) cost nothing and counts as neither."""
    lanes: dict[str, Any] = {k: dict(v) for k, v in (budget.get("lanes") or {}).items()}
    entry: dict[str, Any] = lanes.setdefault(key, {"rounds": 0, "sessions": {}})
    entry["rounds"] = int(entry.get("rounds", 0)) + (1 if new_round else 0)
    if refused:
        return {**budget, "lanes": lanes}, 0.0
    if reported is None:
        return {**budget, "lanes": lanes, "unknown_calls": int(budget.get("unknown_calls", 0)) + 1}, None
    sessions: dict[str, float] = dict(entry.get("sessions") or {})
    previous: float = float(sessions.get(session or "", 0.0))
    delta: float = round(reported - previous if reported >= previous else reported, 6)
    sessions[session or ""] = reported
    entry["sessions"] = sessions
    entry["charged_usd"] = round(float(entry.get("charged_usd", 0.0)) + delta, 6)
    return {**budget, "lanes": lanes, "spent_usd": round(float(budget.get("spent_usd", 0.0)) + delta, 6)}, delta


def reserved_total(budget: dict[str, Any], skip: str | None = None) -> float:
    held: Any = budget.get(RESERVED_KEY)
    if not isinstance(held, dict):
        return 0.0
    return round(sum(float(v) for k, v in held.items() if k != skip and isinstance(v, (int, float))), 6)


def spend_state(runs_dir: Path, stamp: str, cwd: Path) -> dict[str, Any]:
    caps: dict[str, Any] = read_budget(cwd)
    budget: dict[str, Any] = read_json_object(runs_dir / stamp / BUDGET_NAME)
    spent: float = float(budget.get("spent_usd", 0.0))
    left: float | None = None if caps["max_usd"] is None else round(caps["max_usd"] - spent, 6)
    reserved: float = reserved_total(budget)
    return {"caps": caps, "budget": budget, "spent_usd": spent, "remaining_usd": left, "reserved_usd": reserved,
            "available_usd": None if left is None else round(left - reserved, 6),
            "spend_complete": int(budget.get("unknown_calls", 0)) == 0 and int(budget.get(UNREPORTED_KEY, 0)) == 0}


def budget_report(runs_dir: Path, stamp: str, cwd: Path) -> dict[str, Any]:
    state: dict[str, Any] = spend_state(runs_dir, stamp, cwd)
    elapsed: int = int(time.time()) - int(state["budget"].get("started", time.time()))
    return {"ok": True, "stamp": stamp, "caps": state["caps"], "spent_usd": state["spent_usd"],
            "remaining_usd": state["remaining_usd"], "reserved_usd": state["reserved_usd"],
            "spend_complete": state["spend_complete"],
            "unknown_calls": int(state["budget"].get("unknown_calls", 0)),
            UNREPORTED_KEY: int(state["budget"].get(UNREPORTED_KEY, 0)), "loops": int(state["budget"].get("loops", 0)),
            "elapsed_s": max(elapsed, 0), "lanes": state["budget"].get("lanes", {})}


def budget_refusal(state: dict[str, Any], lane_id: str | None, now: int) -> str | None:
    """Why no further model call may start, or None. Rounds count starts of one lane; wall time counts from the first.
    Only unknown_calls (a Claude call that should have reported a cost and did not) blocks a dollar cap; unreported_calls
    (a CLI that never reports one) are counted but their dollars are not part of max_usd."""
    caps: dict[str, Any] = state["caps"]
    if state["remaining_usd"] is not None and state["remaining_usd"] <= 0:
        return f"max_usd {caps['max_usd']} reached"
    unknown: int = int(state["budget"].get("unknown_calls", 0))
    if caps["max_usd"] is not None and unknown > 0:
        return f"spend unknown for {unknown} calls; max_usd cannot be enforced"
    started: Any = state["budget"].get("started")
    if isinstance(started, (int, float)) and now - started >= caps["max_wall_minutes"] * SECONDS_PER_MINUTE:
        return f"max_wall_minutes {caps['max_wall_minutes']} reached"
    rounds: int = int(((state["budget"].get("lanes") or {}).get(lane_id or "") or {}).get("rounds", 0))
    if lane_id and rounds >= caps["max_rounds"]:
        return f"max_rounds {caps['max_rounds']} reached for lane {lane_id}"
    return None


def refused_before_running(entry: dict[str, Any], parsed: dict[str, Any]) -> bool:
    """An attempt that reported a 429 as an error result with no cost and at most one turn never reached the model."""
    return (is_overload(int(entry.get("code", 1)), str(entry.get("stdout", "")), str(entry.get("stderr", "")))
            and parsed["is_error"] and not parsed["cost_usd"]
            and (parsed["num_turns"] is None or parsed["num_turns"] <= 1))


def attempt_usages(call: dict[str, Any]) -> list[dict[str, Any] | None]:
    """The parsed result of every attempt, in order. An earlier attempt that printed no result at all was refused before
    it ran (a bare 429) and costs nothing, and so does one whose JSON result is a costless 429 error on its first turn
    (marked `refused`); the last attempt always counts, so a missing cost there is unknown."""
    entries: list[dict[str, Any]] = call.get("results") or [{"stdout": call.get("stdout", "")}]
    parsed: list[dict[str, Any] | None] = [parse_result(str(e.get("stdout", ""))) for e in entries]
    last: int = len(parsed) - 1
    usages: list[dict[str, Any] | None] = []
    for n, (entry, result) in enumerate(zip(entries, parsed)):
        if n != last and result is not None and refused_before_running(entry, result):
            usages.append({"cost_usd": 0.0, "refused": True})
        elif result is not None or n == last:
            usages.append(result)
    return usages


def record_attempts(runs_dir: Path, stamp: str, key: str, usages: list[dict[str, Any] | None],
                    release: str | None = None) -> tuple[float | None, bool]:
    """Fold every attempt's usage into budget.json under one lock, counting one round for the call. Returns the total
    charged (None when no attempt had a known cost) and whether every attempt's cost was known. `release` drops that
    lane's reserved share in the same write."""
    path: Path = runs_dir / stamp / BUDGET_NAME
    with lane_lock(path) as held:
        if not held:
            raise LaneError("budget lock busy")
        budget: dict[str, Any] = read_json_object(path) or new_budget(int(time.time()))
        deltas: list[float | None] = []
        for n, parsed in enumerate(usages or [None]):
            budget, delta = charge(budget, key, (parsed or {}).get("session_id"), (parsed or {}).get("cost_usd"), n == 0,
                                   bool((parsed or {}).get("refused")))
            deltas.append(delta)
        if release and isinstance(budget.get(RESERVED_KEY), dict):
            budget = {**budget, RESERVED_KEY: {k: v for k, v in budget[RESERVED_KEY].items() if k != release}}
        atomic_write(path, json.dumps(budget, indent=2) + "\n")
    known: list[float] = [d for d in deltas if d is not None]
    return (round(sum(known), 6) if known else None), len(known) == len(deltas)


def record_unreported(runs_dir: Path, stamp: str, key: str) -> None:
    """Count one call to a CLI that never reports a cost (a non-Claude seat): one round under `key` and one unreported
    call, under the budget lock. It is never an unknown cost, so it does not stop a `max_usd` run."""
    path: Path = runs_dir / stamp / BUDGET_NAME
    with lane_lock(path) as held:
        if not held:
            raise LaneError("budget lock busy")
        budget: dict[str, Any] = read_json_object(path) or new_budget(int(time.time()))
        lanes: dict[str, Any] = {k: dict(v) for k, v in (budget.get("lanes") or {}).items()}
        entry: dict[str, Any] = lanes.setdefault(key, {"rounds": 0, "sessions": {}})
        entry["rounds"] = int(entry.get("rounds", 0)) + 1
        entry["unreported"] = int(entry.get("unreported", 0)) + 1
        atomic_write(path, json.dumps({**budget, "lanes": lanes, UNREPORTED_KEY: int(budget.get(UNREPORTED_KEY, 0)) + 1},
                                      indent=2) + "\n")


def record_spend(runs_dir: Path, stamp: str, key: str, parsed: dict[str, Any] | None) -> float | None:
    """Fold one call's usage into budget.json; the amount charged, or None when the cost is unknown."""
    return record_attempts(runs_dir, stamp, key, [parsed])[0]


def reserve_share(runs_dir: Path, stamp: str, cwd: Path, manifest: dict[str, Any], lane_id: str) -> tuple[float | None, str | None]:
    """Under the budget lock, set aside this son's share of what is left under max_usd: the unreserved remainder split
    over this lane and every lane not yet started and not holding a share. Returns (share, refusal); no cap gives
    (None, None). Parallel sons therefore never hold more than max_usd between them."""
    caps: dict[str, Any] = read_budget(cwd)
    if caps["max_usd"] is None:
        return None, None
    path: Path = runs_dir / stamp / BUDGET_NAME
    with lane_lock(path) as held:
        if not held:
            raise LaneError("budget lock busy")
        budget: dict[str, Any] = read_json_object(path) or new_budget(int(time.time()))
        reserved: dict[str, Any] = dict(budget.get(RESERVED_KEY) or {})
        available: float = caps["max_usd"] - float(budget.get("spent_usd", 0.0)) - reserved_total(budget, lane_id)
        started: dict[str, Any] = budget.get("lanes") or {}
        waiting: int = sum(1 for lane in manifest["lanes"] if str(lane["id"]) != lane_id and str(lane["id"]) not in reserved
                           and str(lane["id"]) not in started)
        share: float = math.floor(available / (1 + waiting) * 100) / 100
        if share < 0.01:
            return None, f"no unreserved max_usd {caps['max_usd']} left for lane {lane_id}"
        reserved[lane_id] = share
        atomic_write(path, json.dumps({**budget, RESERVED_KEY: reserved}, indent=2) + "\n")
    return share, None


def release_share(runs_dir: Path, stamp: str, lane_id: str) -> None:
    path: Path = runs_dir / stamp / BUDGET_NAME
    with lane_lock(path) as held:
        budget: dict[str, Any] = read_json_object(path)
        if held and isinstance(budget.get(RESERVED_KEY), dict) and lane_id in budget[RESERVED_KEY]:
            atomic_write(path, json.dumps({**budget, RESERVED_KEY: {k: v for k, v in budget[RESERVED_KEY].items()
                                                                     if k != lane_id}}, indent=2) + "\n")


def start_clock(runs_dir: Path, stamp: str) -> None:
    path: Path = runs_dir / stamp / BUDGET_NAME
    with lane_lock(path) as held:
        if held and not path.is_file():
            atomic_write(path, json.dumps(new_budget(int(time.time())), indent=2) + "\n")
