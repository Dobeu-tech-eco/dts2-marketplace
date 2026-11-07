"""G-13: the graceful-shutdown step. One call at the end of a run, or when it is aborted: every lane still running is
parked incomplete (reason `shutdown`) through `transition`, its son is asked to stop (SIGTERM to its process group, SIGKILL
after a grace period), the lane's lease is closed and its budget share returned, and git's gc setting is put back. A lane
that already finished (done or blocked) is left exactly as it is."""
from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path
from typing import Any, Callable, Final

from state_io import atomic_write

from .common import LEASE_NAME, PHASE_INCOMPLETE, PID_KEYS, REASON_SHUTDOWN, SETTLED_PHASES, STATUS_ACTIVE, STATUS_CLOSED
from .merge import inside_son, son_refusal
from .phases import transition
from .records import append_ledger, lane_lock, merge_json
from .runstate import pid_alive, read_status_files, release_share
from .supervisor import gc_restore

GRACE_S: Final[float] = 10.0
POLL_S: Final[float] = 0.2

Signaller = Callable[[int, int], None]


def signal_group(pid: int, sig: int) -> None:
    """Send `sig` to the son's process group (a son is its own session leader). Never signals this process or its group."""
    if pid == os.getpid() or pid <= 0:
        return
    try:
        group: int = os.getpgid(pid)
        if group == os.getpgid(0):
            os.kill(pid, sig)
        else:
            os.killpg(group, sig)
    except (ProcessLookupError, PermissionError):
        pass  # already gone, or not ours to signal


def son_pids(data: dict[str, Any]) -> list[int]:
    return [int(data[key]) for key in PID_KEYS if pid_alive(data.get(key)) and data.get(key) != os.getpid()]


def stop_sons(pids: list[int], grace_s: float, sleep: Callable[[float], None], clock: Callable[[], float],
              signaller: Signaller) -> list[int]:
    """SIGTERM every pid, wait up to `grace_s` for them to go, SIGKILL the rest. The pids that needed the SIGKILL."""
    for pid in pids:
        signaller(pid, signal.SIGTERM)
    deadline: float = clock() + grace_s
    while any(pid_alive(pid) for pid in pids) and clock() < deadline:
        sleep(POLL_S)
    stubborn: list[int] = [pid for pid in pids if pid_alive(pid)]
    for pid in stubborn:
        signaller(pid, signal.SIGKILL)
    return stubborn


def close_active_lease(path: Path, now: int) -> bool:
    """Close the lane's lease if it is active; False when there was none to close."""
    with lane_lock(path) as held:
        try:
            record: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if not held or not isinstance(record, dict) or record.get("status") != STATUS_ACTIVE:
            return False
        atomic_write(path, json.dumps({**record, "status": STATUS_CLOSED, "released": now}, indent=2) + "\n")
    return True


def shutdown_lane(runs_dir: Path, stamp: str, path: Path, data: dict[str, Any], now: int, grace_s: float,
                  sleep: Callable[[float], None], clock: Callable[[], float], signaller: Signaller) -> dict[str, Any]:
    lane: str = str(data.get("lane") or path.parent.name)
    phase: str = str(data.get("status", ""))
    settled: bool = phase in SETTLED_PHASES
    parked: bool = False
    if not settled:  # park first, so the exit the kill causes is not recorded as a timeout
        parked = bool(transition(runs_dir, stamp, lane, PHASE_INCOMPLETE, reason=REASON_SHUTDOWN,
                                 extra={"parked_at": now, "detail": "run shut down"}, actor="head")["ok"])
    pids: list[int] = [] if settled else son_pids(data)
    stubborn: list[int] = stop_sons(pids, grace_s, sleep, clock, signaller) if pids else []
    merge_json(path, dict.fromkeys(PID_KEYS))
    release_share(runs_dir, stamp, lane)
    closed: bool = close_active_lease(path.parent / LEASE_NAME, now)
    return {"lane": lane, "was": phase or None, "parked": parked, "stopped": pids, "killed": stubborn, "lease_closed": closed}


def shutdown(runs_dir: Path, stamp: str, cwd: Path, grace_s: float = GRACE_S,
             sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
             signaller: Signaller = signal_group) -> dict[str, Any]:
    """Wind the run down. Safe to call twice. A son is refused: ending the run is the head's."""
    if inside_son():
        return son_refusal("shutdown")
    now: int = int(time.time())
    lanes: list[dict[str, Any]] = [shutdown_lane(runs_dir, stamp, path, data, now, grace_s, sleep, clock, signaller)
                                   for path, data in read_status_files(runs_dir, stamp)]
    restored: dict[str, Any] = gc_restore(runs_dir, stamp, cwd)
    append_ledger(runs_dir, stamp, {"lane": "-", "event": "shutdown", "lanes": [row["lane"] for row in lanes]})
    return {"ok": True, "stamp": stamp, "lanes": lanes, "gc_restored": bool(restored.get("restored"))}
