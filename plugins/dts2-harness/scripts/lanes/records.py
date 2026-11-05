"""Low-level state reads and writes the other lanes modules share: one JSON object under its lock (through the state port),
the run's model-call ledger and the lock itself. Nothing here knows a lane's lifecycle."""
from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path
from typing import Any, Final, Iterator

from son_launch import SON_MARKER
from state_io import FileStore, LockBusy, State

from .common import MODEL_LEDGER_NAME, LaneError


def state_for(path: Path) -> State:
    """The state port rooted at the file's folder, so the file is addressed by its name alone."""
    return State(FileStore(path.parent))


@contextlib.contextmanager
def lane_lock(path: Path) -> Iterator[bool]:
    """Exclusive lock around a read-compare-write of `path` (taken by the port: `<path>.lock`, reclaimed when stale).
    Yields False, rather than raising, when it cannot be taken."""
    with contextlib.ExitStack() as stack:
        held: bool = True
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            stack.enter_context(FileStore(path.parent).lock(path.name))
        except LockBusy:
            held = False
        yield held


def read_json_object(path: Path) -> dict[str, Any]:
    return state_for(path).read_record(path.name) or {}


def merge_json(path: Path, changes: dict[str, Any]) -> dict[str, Any]:
    """Read-merge-write one JSON object under its lock; the merged object. Raises LaneError when the lock is busy."""
    try:
        return state_for(path).update_record(path.name, changes)
    except LockBusy as exc:
        raise LaneError(f"lock busy for {path}") from exc


def append_ledger(runs_dir: Path, stamp: str, record: dict[str, Any]) -> None:
    """Add one line to the run's model-call ledger (retries, fallbacks, parks, version checks)."""
    path: Path = runs_dir / stamp / MODEL_LEDGER_NAME
    line: str = json.dumps({"t": int(time.time()), **record}, sort_keys=True) + "\n"
    state_for(path).store.append_text(path.name, line)  # one O_APPEND write: concurrent writers never drop a line


def ledger_emitter(runs_dir: Path, stamp: str, lane_id: str) -> Any:
    return lambda event: append_ledger(runs_dir, stamp, {"lane": lane_id, **event})


ROLE_ENV: Final[str] = "DTS2_ROLE"
NON_HEAD_ROLES: Final[frozenset[str]] = frozenset({"son", "vote", "voter", "council"})  # roles that never publish or merge


def inside_son() -> bool:
    """True in a son's process: the marker its env carries, its lane branch prefix, or the role `son`."""
    return bool(os.environ.get(SON_MARKER) or os.environ.get("DTS2_SON_BRANCH_PREFIX") or os.environ.get(ROLE_ENV, "").lower() == "son")


def non_head_role() -> bool:
    """True for a son, a voter or a council seat: none of them publishes a lane, whatever markers the env carries."""
    return inside_son() or os.environ.get(ROLE_ENV, "").lower() in NON_HEAD_ROLES


def son_refusal(what: str) -> dict[str, Any]:
    return {"ok": False, "detail": f"{what} is the head's alone; a son never grants its own merge or changes the merge state"}
