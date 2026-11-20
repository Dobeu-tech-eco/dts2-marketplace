"""Process-group, liveness and file-lock primitives that behave the same on POSIX and native Windows.

POSIX uses sessions, killpg and flock. Windows uses CREATE_NEW_PROCESS_GROUP, console control events, taskkill, the
kernel32 process API and msvcrt.locking. Windows branches are selected by `IS_WINDOWS` at call time so tests can
exercise them on any platform."""
from __future__ import annotations

import os
import signal
import subprocess
from typing import Any, Final

IS_WINDOWS: bool = os.name == "nt"

PROCESS_QUERY_LIMITED_INFORMATION: Final[int] = 0x1000
STILL_ACTIVE: Final[int] = 259
NO_GROUP: Final[int] = -1  # a group id that never equals a real one
LOCK_BYTES: Final[int] = 1


def new_group_popen_kwargs() -> dict[str, Any]:
    """Popen kwargs that make the child the leader of its own process group."""
    if IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def windows_pid_alive(pid: int) -> bool:
    import ctypes
    kernel32: Any = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle: Any = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def pid_alive(pid: int) -> bool:
    """True when a process with this pid exists. Never uses os.kill on Windows (there it would terminate the process)."""
    if IS_WINDOWS:
        return windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def group_alive(pgid: int) -> bool:
    """True when the group exists. On Windows the group is its leader process."""
    if IS_WINDOWS:
        return windows_pid_alive(pgid)
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def group_of(pid: int) -> int:
    """The process group of `pid`; on Windows a spawned son is its own group, so the pid itself."""
    if IS_WINDOWS:
        return pid
    return os.getpgid(pid)


def own_group() -> int:
    """This process's group, or NO_GROUP where groups are not ids (Windows)."""
    if IS_WINDOWS:
        return NO_GROUP
    return os.getpgid(0)


def send_group(pgid: int, posix_sig: int) -> bool:
    """Signal a group; False when it is gone or not ours. On Windows the signal is always CTRL_BREAK_EVENT."""
    try:
        if IS_WINDOWS:
            os.kill(pgid, signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]  # a console event for the group
        else:
            os.killpg(pgid, posix_sig)
    except (ProcessLookupError, PermissionError, OSError):
        return False
    return True


def interrupt_group(pgid: int) -> bool:
    return send_group(pgid, signal.SIGINT)


def terminate_group(pgid: int) -> bool:
    return send_group(pgid, signal.SIGTERM)


def kill_group(pgid: int) -> bool:
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pgid)], capture_output=True, check=False)
        return True
    return send_group(pgid, signal.SIGKILL)


def lock_exclusive(fh: Any, blocking: bool) -> None:
    """Take an exclusive lock on an open file. Non-blocking contention raises BlockingIOError on every platform."""
    if IS_WINDOWS:
        import msvcrt
        fh.seek(0)
        mode: int = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK  # type: ignore[attr-defined]
        try:
            msvcrt.locking(fh.fileno(), mode, LOCK_BYTES)  # type: ignore[attr-defined]
        except OSError as exc:
            raise BlockingIOError(str(exc)) from exc
        return
    import fcntl
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))


def unlock(fh: Any) -> None:
    if IS_WINDOWS:
        import msvcrt
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, LOCK_BYTES)  # type: ignore[attr-defined]
        return
    import fcntl
    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
