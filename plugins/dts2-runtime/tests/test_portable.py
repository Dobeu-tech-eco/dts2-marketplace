"""portable.py: real POSIX behavior, plus the Windows branches driven through mocks so they run on any platform."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import portable  # noqa: E402

ON_WINDOWS = os.name == "nt"
WAIT_S = 5.0
LOCK_KEY = 4242


def wait_until(check, timeout: float = WAIT_S) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.05)
    return check()


@unittest.skipIf(ON_WINDOWS, "uses sleep and POSIX groups")
class PosixGroups(unittest.TestCase):
    def spawn(self) -> subprocess.Popen:
        return subprocess.Popen(["sleep", "30"], **portable.new_group_popen_kwargs())

    def test_kwargs(self) -> None:
        self.assertEqual(portable.new_group_popen_kwargs(), {"start_new_session": True})

    def test_kill_group_ends_group(self) -> None:
        child = self.spawn()
        try:
            self.assertTrue(portable.group_alive(child.pid))
            self.assertTrue(portable.pid_alive(child.pid))
            self.assertEqual(portable.group_of(child.pid), child.pid)
            portable.kill_group(child.pid)
            child.wait(timeout=WAIT_S)
            self.assertTrue(wait_until(lambda: not portable.group_alive(child.pid)))
            self.assertFalse(portable.pid_alive(child.pid))
        finally:
            child.kill()
            child.wait()

    def test_interrupt_and_terminate(self) -> None:
        for send, code in ((portable.interrupt_group, -signal.SIGINT), (portable.terminate_group, -signal.SIGTERM)):
            child = self.spawn()
            self.assertTrue(send(child.pid))
            self.assertEqual(child.wait(timeout=WAIT_S), code)

    def test_missing_group_is_ignored(self) -> None:
        child = self.spawn()
        child.kill()
        child.wait()
        self.assertFalse(portable.interrupt_group(child.pid))
        self.assertFalse(portable.group_alive(child.pid))

    def test_own_group(self) -> None:
        self.assertEqual(portable.own_group(), os.getpgid(0))


class WindowsBranches(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(portable, "IS_WINDOWS", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_kwargs(self) -> None:
        flag = 0x200
        with mock.patch.object(subprocess, "CREATE_NEW_PROCESS_GROUP", flag, create=True):
            self.assertEqual(portable.new_group_popen_kwargs(), {"creationflags": flag})

    def fake_kernel32(self, handle: int, ok: bool, exit_code: int) -> mock.MagicMock:
        kernel32 = mock.MagicMock()
        kernel32.OpenProcess.return_value = handle

        def fill(_h, ref):
            ref._obj.value = exit_code  # ctypes.byref -> CArgObject
            return ok

        kernel32.GetExitCodeProcess.side_effect = fill
        return kernel32

    def test_pid_alive_states(self) -> None:
        cases = ((1, True, portable.STILL_ACTIVE, True), (1, True, 0, False), (0, True, 0, False), (1, False, 0, False))
        for handle, ok, code, expected in cases:
            kernel32 = self.fake_kernel32(handle, ok, code)
            windll = types.SimpleNamespace(kernel32=kernel32)
            with mock.patch("ctypes.windll", windll, create=True), mock.patch.object(os, "kill") as kill:
                self.assertEqual(portable.pid_alive(77), expected, (handle, ok, code))
                kill.assert_not_called()
            if handle:
                kernel32.CloseHandle.assert_called_once_with(handle)
            kernel32.OpenProcess.assert_called_with(portable.PROCESS_QUERY_LIMITED_INFORMATION, False, 77)

    def test_group_alive_uses_leader(self) -> None:
        with mock.patch.object(portable, "windows_pid_alive", return_value=True) as probe, mock.patch.object(os, "killpg", create=True) as killpg:
            self.assertTrue(portable.group_alive(9))
            probe.assert_called_once_with(9)
            killpg.assert_not_called()

    def test_group_ids(self) -> None:
        self.assertEqual(portable.group_of(31), 31)
        self.assertEqual(portable.own_group(), portable.NO_GROUP)

    def test_interrupt_and_terminate_send_ctrl_break(self) -> None:
        with mock.patch.object(signal, "CTRL_BREAK_EVENT", 1, create=True), mock.patch.object(os, "kill") as kill:
            self.assertTrue(portable.interrupt_group(5))
            self.assertTrue(portable.terminate_group(6))
            self.assertEqual(kill.call_args_list, [mock.call(5, 1), mock.call(6, 1)])
            kill.side_effect = ProcessLookupError
            self.assertFalse(portable.interrupt_group(5))

    def test_kill_group_runs_taskkill(self) -> None:
        with mock.patch.object(subprocess, "run") as run:
            self.assertTrue(portable.kill_group(123))
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["taskkill", "/T", "/F", "/PID", "123"])
        self.assertTrue(kwargs["capture_output"])

    def test_kill_group_ignores_failure(self) -> None:
        with mock.patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 128)):
            self.assertTrue(portable.kill_group(1))

    def fake_msvcrt(self) -> mock.MagicMock:
        module = mock.MagicMock()
        module.LK_LOCK, module.LK_NBLCK, module.LK_UNLCK = 1, 2, 0
        return module

    def test_lock_modes_and_contention(self) -> None:
        module = self.fake_msvcrt()
        handle = mock.MagicMock()
        handle.fileno.return_value = 9
        with mock.patch.dict(sys.modules, {"msvcrt": module}):
            portable.lock_exclusive(handle, blocking=False)
            module.locking.assert_called_with(9, module.LK_NBLCK, portable.LOCK_BYTES)
            portable.lock_exclusive(handle, blocking=True)
            module.locking.assert_called_with(9, module.LK_LOCK, portable.LOCK_BYTES)
            handle.seek.assert_called_with(0)
            module.locking.side_effect = OSError("locked")
            with self.assertRaises(BlockingIOError):
                portable.lock_exclusive(handle, blocking=False)
            module.locking.side_effect = None
            portable.unlock(handle)
            module.locking.assert_called_with(9, module.LK_UNLCK, portable.LOCK_BYTES)


@unittest.skipIf(ON_WINDOWS, "fcntl flock semantics; Windows covered by mocks")
class PosixLocks(unittest.TestCase):
    def test_contention_between_handles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "slot.lock"
            first, second = open(path, "a+"), open(path, "a+")
            try:
                portable.lock_exclusive(first, blocking=False)
                with self.assertRaises(BlockingIOError):
                    portable.lock_exclusive(second, blocking=False)
                portable.unlock(first)
                portable.lock_exclusive(second, blocking=False)
                portable.unlock(second)
            finally:
                first.close()
                second.close()

    def test_pid_alive_posix(self) -> None:
        self.assertTrue(portable.pid_alive(os.getpid()))
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        self.assertFalse(portable.pid_alive(child.pid))


if __name__ == "__main__":
    unittest.main()
