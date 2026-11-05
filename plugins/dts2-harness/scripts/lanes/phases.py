"""G-13: the one writer of a lane's phase. `transition` is the only code that changes `status` in status.json; it checks the
move against the LEGAL table, stamps the heartbeat, renews the lane's lease and writes a ledger line. The head's own
changes (starting a son, parking one, marking one stalled or orphaned) and a son's report (pr-open, done, blocked,
incomplete) all go through it; a son may only use the phases it reports, never the head's."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Final

from state_ids import REJECTED_WORDS

from .common import (
    HEARTBEAT_PHASES, LEASE_NAME, LaneError, PHASE_BLOCKED, PHASE_DONE, PHASE_INCOMPLETE, PHASE_ORPHANED,
    PHASE_PR_OPEN, PHASE_STARTING, STATUS_NAME,
)
from .leases import renew_lease
from .merge import inside_son
from .records import append_ledger, lane_lock, merge_json, read_json_object, state_for

ACTOR_HEAD: Final[str] = "head"
ACTOR_SON: Final[str] = "son"
ALL_PHASES: Final[tuple[str, ...]] = (PHASE_STARTING, PHASE_PR_OPEN, PHASE_DONE, PHASE_BLOCKED, PHASE_INCOMPLETE, PHASE_ORPHANED)
# The head's moves a son must never make: it starts a son, and a stalled lane is the head's to call orphaned.
HEAD_ONLY: Final[frozenset[str]] = frozenset({PHASE_STARTING, PHASE_ORPHANED})
# from-phase -> phases it may move to (staying put is always allowed: that is a heartbeat). None is "no status.json yet".
LEGAL: Final[dict[str | None, frozenset[str]]] = {
    None: frozenset({PHASE_STARTING, PHASE_PR_OPEN, PHASE_DONE, PHASE_BLOCKED, PHASE_INCOMPLETE}),
    PHASE_STARTING: frozenset({PHASE_PR_OPEN, PHASE_DONE, PHASE_BLOCKED, PHASE_INCOMPLETE, PHASE_ORPHANED}),
    PHASE_PR_OPEN: frozenset({PHASE_STARTING, PHASE_DONE, PHASE_BLOCKED, PHASE_INCOMPLETE}),
    PHASE_BLOCKED: frozenset({PHASE_STARTING, PHASE_DONE, PHASE_INCOMPLETE}),
    PHASE_INCOMPLETE: frozenset({PHASE_STARTING, PHASE_DONE, PHASE_BLOCKED, PHASE_ORPHANED}),
    PHASE_ORPHANED: frozenset({PHASE_STARTING, PHASE_DONE, PHASE_INCOMPLETE}),
    PHASE_DONE: frozenset(),
}
SEGMENT: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
# A move to `starting` is a fresh attempt: what the last one recorded about why it stopped is cleared.
FRESH_START: Final[tuple[str, ...]] = ("reason", "detail", "parked_at", "stalled_at")


def lane_path(runs_dir: Path, stamp: str, lane_id: str) -> Path:
    """The lane's status.json. Stamp and lane id must each be one plain path segment (no `..`, no `None` from a missing
    value), so nothing resolves outside the run."""
    for kind, value in (("stamp", stamp), ("lane id", lane_id)):
        if SEGMENT.fullmatch(str(value)) is None or str(value).lower() in REJECTED_WORDS:
            raise LaneError(f"not a valid {kind}: {value!r}")
    return runs_dir / stamp / lane_id / STATUS_NAME


def refusal(lane_id: str, current: str | None, to: str, detail: str) -> dict[str, Any]:
    return {"ok": False, "lane": lane_id, "from": current, "to": to, "detail": detail}


def blocked_move(lane_id: str, current: str | None, to: str, actor: str) -> dict[str, Any] | None:
    """Why this move is not allowed, as a refusal, or None when it is."""
    if actor == ACTOR_SON and to in HEAD_ONLY:
        return refusal(lane_id, current, to, f"{to} is the head's move; a son reports {', '.join(HEARTBEAT_PHASES)}")
    if current == to or (current is not None and current not in LEGAL):
        return None  # a heartbeat, or a phase written before the table existed: let the lane move on
    if to in LEGAL[current]:
        return None
    legal: str = ", ".join(sorted(LEGAL[current])) or "nothing (it is final)"
    return refusal(lane_id, current, to, f"illegal move {current} -> {to}; from {current} a lane may go to {legal}")


def transition(runs_dir: Path, stamp: str, lane_id: str, to: str, *, reason: str | None = None,
               blocked_by: list[str] | None = None, turn: int | None = None, extra: dict[str, Any] | None = None,
               actor: str | None = None, now: int | None = None) -> dict[str, Any]:
    """Move the lane to phase `to` if the LEGAL table allows it, stamping the heartbeat in the same write. The refusal
    (ok false) names the legal moves. `extra` carries the fields that go with the move (a park's detail, a stall's snapshot)."""
    if to not in ALL_PHASES:
        raise LaneError(f"--to must be one of {', '.join(ALL_PHASES)}")
    path: Path = lane_path(runs_dir, stamp, lane_id)
    who: str = actor or (ACTOR_SON if inside_son() else ACTOR_HEAD)
    stamped_at: int = int(time.time()) if now is None else now
    with lane_lock(path) as held:
        if not held:
            raise LaneError(f"lock busy for {path}")
        current: Any = read_json_object(path).get("status") or None
        no: dict[str, Any] | None = blocked_move(lane_id, current, to, who)
        if no is not None:
            return no
        changes: dict[str, Any] = {"lane": lane_id, "status": to, "heartbeat": stamped_at}
        if to == PHASE_STARTING:
            changes.update(dict.fromkeys(FRESH_START))
        changes.update({k: v for k, v in (("turn", turn), ("reason", reason)) if v is not None})
        if blocked_by:
            changes["blocked_by"] = blocked_by
        state_for(path).merge_record(path.name, {**changes, **(extra or {})})
    renew_lease(path.parent / LEASE_NAME, stamped_at)
    if current != to:
        append_ledger(runs_dir, stamp, {"lane": lane_id, "event": "transition", "from": current, "to": to, "actor": who,
                                        "reason": reason})
    return {"ok": True, "lane": lane_id, "from": current, "to": to, "status": to, "heartbeat": stamped_at}


def heartbeat(runs_dir: Path, stamp: str, lane_id: str, turn: int | None, phase: str | None = None,
              reason: str | None = None, blocked_by: list[str] | None = None) -> dict[str, Any]:
    """Stamp the lane's status.json at a turn boundary; creates it when the son has not written one yet. A son sets its
    phase (pr-open, done, blocked, incomplete) and an optional reason through here or `transition`, never by writing the file."""
    if phase is not None:
        if phase not in HEARTBEAT_PHASES:
            raise LaneError(f"--status must be one of {', '.join(HEARTBEAT_PHASES)}")
        moved: dict[str, Any] = transition(runs_dir, stamp, lane_id, phase, reason=reason, blocked_by=blocked_by, turn=turn)
        return moved if not moved["ok"] else {"ok": True, "lane": lane_id, "heartbeat": moved["heartbeat"], "status": phase}
    path: Path = lane_path(runs_dir, stamp, lane_id)
    now: int = int(time.time())
    changes: dict[str, Any] = {"lane": lane_id, "heartbeat": now}
    changes.update({k: v for k, v in (("turn", turn), ("reason", reason)) if v is not None})
    if blocked_by:
        changes["blocked_by"] = blocked_by
    merged: dict[str, Any] = merge_json(path, changes)
    renew_lease(path.parent / LEASE_NAME, now)
    return {"ok": True, "lane": lane_id, "heartbeat": now, "status": merged.get("status")}
