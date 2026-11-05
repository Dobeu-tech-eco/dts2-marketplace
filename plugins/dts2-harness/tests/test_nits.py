"""Review nits from #32: lock safety in state_io, portable SIGKILL, finite floats."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import miniyaml  # noqa: E402
import state_io  # noqa: E402

TARGET: Final[str] = "state/file.txt"
STALE_S: Final[float] = 10.0


class FakeClock:
    def __init__(self) -> None:
        self.now: float = 1000.0

    def __call__(self) -> float:
        return self.now


class LockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = FakeClock()
        self.store = state_io.FileStore(self.tmp.name, clock=self.clock, sleep=lambda _s: None)

    def lock_path(self) -> Path:
        return self.store.lock_file(TARGET)

    def test_drop_does_not_free_successor(self) -> None:
        self.assertTrue(self.store.lock_create(TARGET, "old"))
        self.lock_path().unlink()
        self.assertTrue(self.store.lock_create(TARGET, "new"))
        self.store.lock_drop(TARGET, "old")
        self.assertEqual(json.loads(self.lock_path().read_text())["token"], "new")
        self.assertEqual([p.name for p in self.lock_path().parent.iterdir()], [self.lock_path().name])

    def test_drop_removes_own_lock(self) -> None:
        self.store.lock_create(TARGET, "me")
        self.store.lock_drop(TARGET, "me")
        self.assertFalse(self.lock_path().exists())
        self.store.lock_drop(TARGET, "me")  # idempotent

    def test_touch_only_for_owner(self) -> None:
        self.store.lock_create(TARGET, "me")
        self.clock.now += 1
        self.assertFalse(self.store.lock_touch(TARGET, "other"))
        self.assertTrue(self.store.lock_touch(TARGET, "me"))
        self.lock_path().unlink()
        self.assertFalse(self.store.lock_touch(TARGET, "me"))

    def test_reclaim_on_last_try_still_acquires(self) -> None:
        self.store.lock_create(TARGET, "dead")
        import os
        os.utime(self.lock_path(), (0, 0))
        with self.store.lock(TARGET, tries=1, stale_s=STALE_S) as held:
            self.assertEqual(json.loads(self.lock_path().read_text())["token"], held.token)
        self.assertFalse(self.lock_path().exists())

    def test_live_lock_still_busy(self) -> None:
        self.store.lock_create(TARGET, "live")
        import os
        os.utime(self.lock_path(), (self.clock.now, self.clock.now))
        with self.assertRaises(state_io.LockBusy):
            with self.store.lock(TARGET, tries=2, stale_s=STALE_S):
                pass

    def test_memory_store_last_try_reclaim(self) -> None:
        mem = state_io.MemoryStore(clock=self.clock)
        mem.sleep = lambda _s: None  # type: ignore[method-assign,assignment]
        mem.lock_create(TARGET, "dead")
        self.clock.now += STALE_S + 1
        with mem.lock(TARGET, tries=1, stale_s=STALE_S):
            pass


class MiscTests(unittest.TestCase):
    def test_get_float_rejects_non_finite(self) -> None:
        for word in ("nan", "inf", "-inf"):
            self.assertEqual(miniyaml.get_float({"a": word}, "a", 1.5), 1.5)
        self.assertEqual(miniyaml.get_float({"a": "2.5"}, "a", 1.5), 2.5)

    def test_proc_imports_without_sigkill(self) -> None:
        import importlib
        import signal
        import proc
        saved = signal.SIGKILL
        try:
            del signal.SIGKILL
            importlib.reload(proc)
        finally:
            signal.SIGKILL = saved  # type: ignore[misc]
            importlib.reload(proc)


if __name__ == "__main__":
    unittest.main()
