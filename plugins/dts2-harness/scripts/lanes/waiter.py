"""G-58: `lanes.py wait <stamp> --timeout N`. The head calls it once instead of polling `status`: it returns as soon as a
lane's phase changes or a son writes its exit.json, or at the hard deadline. It sleeps on inotify when the kernel has it
(Linux, through libc) and otherwise on a sleep-backoff loop; both end at the same deadline."""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import select
import time
from pathlib import Path
from typing import Any, Callable, Final

from proc import EXIT_FILE

from .common import STATUS_NAME
from .records import read_json_object

DEFAULT_TIMEOUT_S: Final[float] = 600.0
MAX_TIMEOUT_S: Final[float] = 3600.0
BACKOFF_START_S: Final[float] = 0.2
BACKOFF_CAP_S: Final[float] = 5.0
BACKOFF_FACTOR: Final[float] = 1.5
INOTIFY_SLICE_S: Final[float] = 1.0  # re-read the state at least this often, so a missed event costs a second at most
IN_CLOSE_WRITE: Final[int] = 0x00000008
IN_MOVED_TO: Final[int] = 0x00000080
IN_CREATE: Final[int] = 0x00000100
IN_NONBLOCK: Final[int] = 0o4000
WATCH_MASK: Final[int] = IN_CLOSE_WRITE | IN_MOVED_TO | IN_CREATE
NO_INOTIFY_ENV: Final[str] = "DTS2_NO_INOTIFY"
METHOD_INOTIFY: Final[str] = "inotify"
METHOD_POLL: Final[str] = "poll"
Snapshot = dict[str, tuple[Any, bool]]


def snapshot(runs_dir: Path, stamp: str) -> Snapshot:
    """lane -> (phase, whether exit.json exists)."""
    found: Snapshot = {}
    for status in sorted((runs_dir / stamp).glob(f"*/{STATUS_NAME}")):
        found[status.parent.name] = (read_json_object(status).get("status"), (status.parent / EXIT_FILE).is_file())
    for exit_file in sorted((runs_dir / stamp).glob(f"*/{EXIT_FILE}")):
        found.setdefault(exit_file.parent.name, (None, True))
    return found


def changed_lanes(before: Snapshot, after: Snapshot) -> list[str]:
    return sorted(lane for lane in set(before) | set(after) if before.get(lane) != after.get(lane))


def pending_exits(state: Snapshot) -> list[str]:
    """Lanes whose son has exited but whose phase was not moved off `starting` yet: news the head has not seen."""
    return sorted(lane for lane, (phase, exited) in state.items() if exited and phase in (None, "starting"))


class Inotify:
    """The few libc calls needed to watch directories for new or rewritten files."""

    def __init__(self) -> None:
        name: str | None = ctypes.util.find_library("c")
        libc: Any = ctypes.CDLL(name, use_errno=True)
        self.fd: int = libc.inotify_init1(IN_NONBLOCK)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1 failed")
        self.libc: Any = libc

    def watch(self, folder: Path) -> bool:
        return bool(self.libc.inotify_add_watch(self.fd, os.fsencode(folder), WATCH_MASK) >= 0)

    def wait(self, seconds: float) -> None:
        ready, _w, _x = select.select([self.fd], [], [], max(seconds, 0.0))
        if ready:
            try:
                os.read(self.fd, 65536)
            except BlockingIOError:
                pass

    def close(self) -> None:
        os.close(self.fd)


def open_watch(runs_dir: Path, stamp: str) -> Inotify | None:
    """An inotify watch on the run folder and every lane folder, or None when this system has none."""
    if os.environ.get(NO_INOTIFY_ENV) or os.name != "posix":
        return None
    try:
        watch: Inotify = Inotify()
    except (OSError, AttributeError, TypeError):
        return None
    folders: list[Path] = [runs_dir / stamp, *sorted(p for p in (runs_dir / stamp).glob("*") if p.is_dir())]
    if not all(watch.watch(folder) for folder in folders):
        watch.close()
        return None
    return watch


def wait_for_change(runs_dir: Path, stamp: str, timeout_s: float, sleep: Callable[[float], None] = time.sleep,
                    clock: Callable[[], float] = time.monotonic, inotify: bool = True) -> dict[str, Any]:
    """Block until a lane's phase or exit.json changes (or already shows an unseen exit), or `timeout_s` passes."""
    limit: float = min(max(timeout_s, 0.0), MAX_TIMEOUT_S)
    started: float = clock()
    deadline: float = started + limit
    before: Snapshot = snapshot(runs_dir, stamp)
    watch: Inotify | None = open_watch(runs_dir, stamp) if inotify else None
    delay: float = BACKOFF_START_S
    try:
        while True:
            state: Snapshot = snapshot(runs_dir, stamp)
            moved: list[str] = changed_lanes(before, state) or pending_exits(state)
            left: float = deadline - clock()
            if moved or left <= 0:
                return {"ok": True, "stamp": stamp, "changed": moved, "timed_out": not moved,
                        "waited_s": round(clock() - started, 3), "method": METHOD_INOTIFY if watch else METHOD_POLL,
                        "lanes": {lane: {"phase": phase, "exited": exited} for lane, (phase, exited) in state.items()}}
            if watch is not None:
                watch.wait(min(left, INOTIFY_SLICE_S))
                continue
            sleep(min(delay, left))
            delay = min(delay * BACKOFF_FACTOR, BACKOFF_CAP_S)
    finally:
        if watch is not None:
            watch.close()
