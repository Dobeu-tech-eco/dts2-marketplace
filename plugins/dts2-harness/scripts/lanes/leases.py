"""Lane leases: the epoch fence, expiry and the locked check-and-lease step."""
from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path
from typing import Any, Final, Iterator

from model_call import read_budget
from state_io import StaleEpoch, atomic_write, epoch_of, require_epoch

from .common import LEASE_NAME, LEASE_TTL_FACTOR, PID_KEYS, SECONDS_PER_MINUTE, STATUS_ACTIVE, STATUS_CLOSED, STATUS_NAME, find_lane, lane_files, lane_ids, lease_live
from .conflicts import check
from .gitrefs import gh_down
from .records import lane_lock

SESSION_ENV: Final[str] = "CLAUDE_SESSION_ID"
ADMISSION_NAME: Final[str] = ".admission"  # one lock per runs folder: a lease check and its write are a single step
POLICY_NAME: Final[str] = "policy.json"  # G-50: plan records `ask_each_lane` here; the lease reads it
APPROVED_NAME: Final[str] = "approved-lanes.json"  # G-50: lanes the user said yes to (lanes.py approve-lane)


def read_lease(path: Path) -> dict[str, Any] | None:
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


@contextlib.contextmanager
def admission_lock(runs_dir: Path) -> Iterator[bool]:
    """Serialises lease admission across every run in this folder; yields False when it cannot be taken."""
    with lane_lock(runs_dir / ADMISSION_NAME) as held:
        yield held


def busy(lane_id: str) -> dict[str, Any]:
    return {"ok": False, "lane": lane_id, "lease": None, "conflicts": [], "detail": "lease busy"}


def held_items(runs_dir: Path, now: int | None = None) -> dict[str, str]:
    """G-47: check-in item -> `<stamp>/<lane>` for every live lease in the runs folder that recorded one."""
    clock: int = int(time.time()) if now is None else now
    held: dict[str, str] = {}
    for path in sorted(runs_dir.glob(f"*/*/{LEASE_NAME}")):
        record: dict[str, Any] | None = read_lease(path)
        if record is not None and record.get("item") and lease_live(record, clock):
            held.setdefault(str(record["item"]), f"{path.parent.parent.name}/{path.parent.name}")
    return held


def read_names(path: Path) -> list[str]:
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [str(i) for i in data.get("lanes", [])] if isinstance(data, dict) else []


def admission_refusal(runs_dir: Path, stamp: str, lane_id: str, item: str) -> str | None:
    """Why this lane may not take a lease, or None. G-47: its check-in item is held by another live lease. G-50: the run
    asks before each new lane (dpp-full outside autopilot) and the user has not approved this one."""
    holder: str | None = held_items(runs_dir).get(item) if item else None
    if holder is not None and holder != f"{stamp}/{lane_id}":
        return f"item {item!r} is held by the live lease of lane {holder}"
    policy: dict[str, Any] = read_lease(runs_dir / stamp / POLICY_NAME) or {}
    if policy.get("ask_each_lane") and lane_id not in read_names(runs_dir / stamp / APPROVED_NAME):
        return f"lane {lane_id} needs the user's yes first (dpp_full_ask_each_lane); record it with `lanes.py approve-lane`"
    return None


def refused(lane_id: str, detail: str) -> dict[str, Any]:
    return {"ok": False, "lane": lane_id, "lease": None, "conflicts": [], "detail": detail}


def lease_epoch(record: dict[str, Any] | None) -> int:
    return epoch_of(record)


def epoch_refusal(lane_id: str, given: int, stored: int) -> dict[str, Any]:
    return {"ok": False, "lane": lane_id, "lease": None, "conflicts": [],
            "detail": f"stale epoch {given} is older than the stored lease epoch {stored}; the lease is unchanged"}


def stale_epoch(given: int | None, stored: int) -> bool:
    """True when the caller's epoch is older than the stored one. No epoch given means 'whatever is stored'."""
    try:
        require_epoch(stored if given is None else given, stored)
    except StaleEpoch:
        return True
    return False


def lease_ttl_s(cwd: Path) -> int:
    """How long a new lease lives: LEASE_TTL_FACTOR x max_wall_minutes. A heartbeat renews it, a crashed run's expires."""
    return int(read_budget(cwd)["max_wall_minutes"] * SECONDS_PER_MINUTE * LEASE_TTL_FACTOR)


def lease(manifest: dict[str, Any], lane_id: str, runs_dir: Path, cwd: Path, with_prs: bool,
          epoch: int | None = None) -> dict[str, Any]:
    """Check the manifest's conflicts and write the lane's lease as one step under the admission lock, so two heads can never
    both pass the check and then both lease. Fails closed when the open-PR check was asked for and gh could not answer."""
    lane: dict[str, Any] = find_lane(manifest, lane_id)
    path: Path = runs_dir / str(manifest.get("stamp")) / lane_id / LEASE_NAME
    with admission_lock(runs_dir) as admitted:
        if not admitted:
            return busy(lane_id)
        result: dict[str, Any] = check(manifest, runs_dir, cwd, with_prs)
        if with_prs and not result["prs_checked"]:
            return {"ok": False, "lane": lane_id, "lease": None, "conflicts": [], "detail": gh_down("lease")}
        blocking: list[dict[str, Any]] = [c for c in result["conflicts"]
                                          if lane_id in (c["lane"], c["with"]) and not c.get("routed")]
        if blocking:
            return {"ok": False, "lane": lane_id, "lease": None, "conflicts": blocking}
        why: str | None = admission_refusal(runs_dir, str(manifest.get("stamp")), lane_id, str(lane.get("item") or ""))
        if why is not None:
            return refused(lane_id, why)
        with lane_lock(path) as held:
            if not held:
                return busy(lane_id)
            return write_lease(manifest, lane, path, epoch, lease_ttl_s(cwd))


def write_lease(manifest: dict[str, Any], lane: dict[str, Any], path: Path, epoch: int | None,
                ttl_s: int, now: int | None = None, files: set[str] | None = None) -> dict[str, Any]:
    lane_id: str = str(lane["id"])
    previous: dict[str, Any] | None = read_lease(path)
    if previous is None and path.exists():
        return {"ok": False, "lane": lane_id, "lease": None, "conflicts": [],
                "detail": f"unreadable lease at {path}; refusing to overwrite"}
    stored: int = lease_epoch(previous)
    if stale_epoch(epoch, stored):
        return epoch_refusal(lane_id, int(epoch or 0), stored)
    created: int = int(time.time()) if now is None else now
    record: dict[str, Any] = {"stamp": str(manifest.get("stamp")), "lane": lane_id, "status": STATUS_ACTIVE,
                              "created": created, "expires_at": created + ttl_s, "ttl_s": ttl_s, "epoch": stored + 1,
                              "base": manifest.get("base"), "item": lane.get("item"), "files": sorted(lane_files(lane) if files is None else files), "ids": sorted(lane_ids(lane))}
    session: str = os.environ.get(SESSION_ENV, "").strip()
    if session:  # the SessionEnd hook releases only leases carrying the ending session's id
        record["session_id"] = session
    atomic_write(path, json.dumps(record, indent=2) + "\n")
    return {"ok": True, "lane": lane_id, "lease": str(path), "epoch": stored + 1, "expires_at": record["expires_at"],
            "conflicts": []}


def renew_lease(path: Path, now: int) -> bool:
    """Push an active lease's expiry out by its own ttl (a heartbeat renews it). False when there is nothing to renew."""
    with lane_lock(path) as held:
        record: dict[str, Any] | None = read_lease(path)
        ttl: Any = (record or {}).get("ttl_s")
        if not held or record is None or record.get("status") != STATUS_ACTIVE or not isinstance(ttl, int):
            return False
        atomic_write(path, json.dumps({**record, "expires_at": now + ttl}, indent=2) + "\n")
    return True


def process_running(pid: Any) -> bool:
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


def expired_orphan(path: Path, now: int) -> bool:
    """An active lease past its expiry whose lane has no running spawn or son: the mark a crashed run leaves."""
    record: dict[str, Any] | None = read_lease(path)
    if record is None or record.get("status") != STATUS_ACTIVE or lease_live(record, now):
        return False
    status: dict[str, Any] = read_lease(path.parent / STATUS_NAME) or {}
    return not any(process_running(status.get(key)) for key in PID_KEYS)


def gc_leases(runs_dir: Path, now: int) -> list[str]:
    """G-55: close every expired lease of a lane nobody is running (a crashed run's), in every run under `runs_dir`. A live
    lease, a lease with no expiry and a lease whose lane still has a process are left alone. The `stamp/lane` closed."""
    closed: list[str] = []
    for path in sorted(runs_dir.glob(f"*/*/{LEASE_NAME}")):
        if not expired_orphan(path, now):
            continue
        with lane_lock(path) as held:
            record: dict[str, Any] | None = read_lease(path)
            if not held or record is None or not expired_orphan(path, now):
                continue
            atomic_write(path, json.dumps({**record, "status": STATUS_CLOSED, "released": now, "gc": True}, indent=2) + "\n")
        closed.append(f"{path.parent.parent.name}/{path.parent.name}")
    return closed
