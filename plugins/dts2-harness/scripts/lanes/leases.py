"""Lane leases: the lock, the epoch fence and lease/close."""
from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path
from typing import Any, Final, Iterator

from state_io import atomic_write

from .common import LEASE_NAME, STATUS_ACTIVE, find_lane, lane_files, lane_ids
from .conflicts import check


def read_lease(path: Path) -> dict[str, Any] | None:
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
LOCK_TRIES: Final[int] = 50
LOCK_WAIT_SEC: Final[float] = 0.1
LOCK_MODE: Final[int] = 0o600
LOCK_STALE_SEC: Final[float] = 60.0  # a lock is held for one read-compare-write; older than this means its writer died


@contextlib.contextmanager
def lane_lock(lease_path: Path) -> Iterator[bool]:
    """Per-lane exclusive lock around a lease read-compare-write; yields False when it cannot be taken."""
    lock_path: Path = lease_path.with_suffix(".json.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    held: bool = False
    for _ in range(LOCK_TRIES):
        try:
            os.close(os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, LOCK_MODE))
        except FileExistsError:
            clear_stale_lock(lock_path)
            time.sleep(LOCK_WAIT_SEC)
            continue
        held = True
        break
    try:
        yield held
    finally:
        if held:
            lock_path.unlink(missing_ok=True)


def clear_stale_lock(lock_path: Path) -> None:
    """Remove a lock left by a crashed writer, so one crash cannot block a lane forever."""
    try:
        if time.time() - lock_path.stat().st_mtime > LOCK_STALE_SEC:
            lock_path.unlink(missing_ok=True)
    except OSError:
        pass  # lock vanished or is unreadable: the O_EXCL create in lane_lock decides who wins


def busy(lane_id: str) -> dict[str, Any]:
    return {"ok": False, "lane": lane_id, "lease": None, "conflicts": [], "detail": "lease busy"}


def lease_epoch(record: dict[str, Any] | None) -> int:
    value: Any = (record or {}).get("epoch", 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def epoch_refusal(lane_id: str, given: int, stored: int) -> dict[str, Any]:
    return {"ok": False, "lane": lane_id, "lease": None, "conflicts": [],
            "detail": f"stale epoch {given} is older than the stored lease epoch {stored}; the lease is unchanged"}


def lease(manifest: dict[str, Any], lane_id: str, runs_dir: Path, cwd: Path, with_prs: bool,
          epoch: int | None = None) -> dict[str, Any]:
    lane: dict[str, Any] = find_lane(manifest, lane_id)
    result: dict[str, Any] = check(manifest, runs_dir, cwd, with_prs)
    blocking: list[dict[str, Any]] = [c for c in result["conflicts"] if lane_id in (c["lane"], c["with"])]
    if blocking:
        return {"ok": False, "lane": lane_id, "lease": None, "conflicts": blocking}
    stamp: str = str(manifest.get("stamp"))
    path: Path = runs_dir / stamp / lane_id / LEASE_NAME
    with lane_lock(path) as held:
        if not held:
            return busy(lane_id)
        return write_lease(manifest, lane, path, epoch)


def write_lease(manifest: dict[str, Any], lane: dict[str, Any], path: Path, epoch: int | None) -> dict[str, Any]:
    lane_id: str = str(lane["id"])
    previous: dict[str, Any] | None = read_lease(path)
    if previous is None and path.exists():
        return {"ok": False, "lane": lane_id, "lease": None, "conflicts": [],
                "detail": f"unreadable lease at {path}; refusing to overwrite"}
    stored: int = lease_epoch(previous)
    if epoch is not None and epoch < stored:
        return epoch_refusal(lane_id, epoch, stored)
    new_epoch: int = stored + 1
    record: dict[str, Any] = {"stamp": str(manifest.get("stamp")), "lane": lane_id, "status": STATUS_ACTIVE,
                              "created": int(time.time()), "epoch": new_epoch, "base": manifest.get("base"),
                              "files": sorted(lane_files(lane)), "ids": sorted(lane_ids(lane))}
    atomic_write(path, json.dumps(record, indent=2) + "\n")
    return {"ok": True, "lane": lane_id, "lease": str(path), "epoch": new_epoch, "conflicts": []}
