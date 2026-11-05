"""G-11: the lock lives inside the port (reclaim by rename, renew), epochs are mandatory, send-backs count atomically."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Callable, Final

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import state_io  # noqa: E402
from state_io import EpochRequired, FileStore, LockBusy, MemoryStore, StaleEpoch, State, Store  # noqa: E402

STAMP: Final[str] = "20261104-1"
TARGET: Final[str] = ".harness/runs/20261104-1/a/lease.json"


class LockContract:
    def make(self, clock: Callable[[], float] | None = None) -> Store:
        raise NotImplementedError

    def age(self, store: Store, path: str, seconds: float) -> None:
        raise NotImplementedError

    def test_lock_is_exclusive_across_threads(self) -> None:
        store = self.make()
        shared = {"n": 0}

        def work() -> None:
            for _ in range(15):
                with store.lock(TARGET, tries=2000, wait=0.001):
                    value = shared["n"]
                    time.sleep(0.0005)
                    shared["n"] = value + 1

        threads = [threading.Thread(target=work) for _ in range(5)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(shared["n"], 75)

    def test_busy_lock_raises_after_the_tries_run_out(self) -> None:
        store = self.make()
        with store.lock(TARGET):
            with self.assertRaises(LockBusy):
                with store.lock(TARGET, tries=3, wait=0.001):
                    self.fail("must not enter")

    def test_released_lock_can_be_retaken(self) -> None:
        store = self.make()
        with store.lock(TARGET):
            pass
        with store.lock(TARGET, tries=1):
            pass

    def test_stale_lock_is_reclaimed(self) -> None:
        store = self.make()
        with store.lock(TARGET) as dead:
            self.age(store, TARGET, 3600)
            with store.lock(TARGET, tries=3, wait=0.001, stale_s=60) as taken:
                self.assertNotEqual(taken.token, dead.token)

    def test_fresh_lock_is_not_reclaimed(self) -> None:
        store = self.make()
        with store.lock(TARGET):
            self.age(store, TARGET, 5)
            with self.assertRaises(LockBusy):
                with store.lock(TARGET, tries=3, wait=0.001, stale_s=60):
                    pass

    def test_an_old_holder_cannot_release_the_new_owners_lock(self) -> None:
        store = self.make()
        first = store.lock(TARGET)
        old = first.__enter__()
        self.age(store, TARGET, 3600)
        with store.lock(TARGET, tries=3, wait=0.001, stale_s=60):
            first.__exit__(None, None, None)  # the dead holder wakes up and releases
            with self.assertRaises(LockBusy):  # the new owner still holds it
                with store.lock(TARGET, tries=2, wait=0.001, stale_s=60):
                    pass
        self.assertFalse(old.renew())

    def test_renew_keeps_a_long_job_alive(self) -> None:
        store = self.make()
        with store.lock(TARGET) as held:
            self.age(store, TARGET, 50)
            self.assertTrue(held.renew())
            with self.assertRaises(LockBusy):
                with store.lock(TARGET, tries=2, wait=0.001, stale_s=40):
                    pass

    def test_many_reclaimers_never_overlap(self) -> None:
        store = self.make()
        with store.lock(TARGET):
            self.age(store, TARGET, 3600)
            inside = {"now": 0, "max": 0}
            guard = threading.Lock()

            def work() -> None:
                with store.lock(TARGET, tries=3000, wait=0.001, stale_s=60):
                    with guard:
                        inside["now"] += 1
                        inside["max"] = max(inside["max"], inside["now"])
                    time.sleep(0.002)
                    with guard:
                        inside["now"] -= 1

            threads = [threading.Thread(target=work) for _ in range(6)]
            [t.start() for t in threads]
            [t.join() for t in threads]
        self.assertEqual(inside["max"], 1)


class FileLocks(LockContract, unittest.TestCase):
    def make(self, clock: Callable[[], float] | None = None) -> Store:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return FileStore(tmp.name)

    def age(self, store: Store, path: str, seconds: float) -> None:
        lock = store.resolve(path + ".lock")  # type: ignore[attr-defined]
        then = time.time() - seconds
        os.utime(lock, (then, then))


class MemoryLocks(LockContract, unittest.TestCase):
    def make(self, clock: Callable[[], float] | None = None) -> Store:
        return MemoryStore()

    def age(self, store: Store, path: str, seconds: float) -> None:
        store.locks[path][1] -= seconds  # type: ignore[attr-defined]


class EpochTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = State(MemoryStore())

    def test_epoch_is_mandatory(self) -> None:
        with self.assertRaises(TypeError):
            self.state.acquire_lease(STAMP, "a")  # type: ignore[call-arg]
        with self.assertRaises(EpochRequired):
            self.state.acquire_lease(STAMP, "a", epoch=None)  # type: ignore[arg-type]
        with self.assertRaises(EpochRequired):
            self.state.release_lease(STAMP, "a", epoch=None)  # type: ignore[arg-type]
        with self.assertRaises(EpochRequired):
            self.state.acquire_lease(STAMP, "a", epoch=True)  # type: ignore[arg-type]

    def test_acquire_bumps_the_epoch_and_refuses_an_older_caller(self) -> None:
        first = self.state.acquire_lease(STAMP, "a", epoch=0, fields={"base": "abc"})
        self.assertEqual((first["epoch"], first["status"], first["base"]), (1, "active", "abc"))
        second = self.state.acquire_lease(STAMP, "a", epoch=1)
        self.assertEqual(second["epoch"], 2)
        with self.assertRaises(StaleEpoch):
            self.state.acquire_lease(STAMP, "a", epoch=1)
        self.assertEqual(self.state.lease(STAMP, "a")["epoch"], 2)

    def test_release_closes_and_checks_the_epoch(self) -> None:
        self.state.acquire_lease(STAMP, "a", epoch=0)
        self.state.acquire_lease(STAMP, "a", epoch=1)
        with self.assertRaises(StaleEpoch):
            self.state.release_lease(STAMP, "a", epoch=1)
        closed = self.state.release_lease(STAMP, "a", epoch=2)
        self.assertEqual(closed["status"], "closed")
        self.assertIn("released", closed)

    def test_an_unreadable_lease_is_never_overwritten(self) -> None:
        self.state.store.write_text(TARGET, "{torn")
        with self.assertRaises(state_io.StateError):
            self.state.acquire_lease(STAMP, "a", epoch=0)
        self.assertEqual(self.state.store.read_text(TARGET), "{torn")

    def test_racing_acquires_get_distinct_epochs(self) -> None:
        results: list[int] = []

        def grab() -> None:
            try:
                results.append(self.state.acquire_lease(STAMP, "a", epoch=0)["epoch"])
            except state_io.StateError:
                pass

        threads = [threading.Thread(target=grab) for _ in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(len(results), len(set(results)))
        self.assertEqual(self.state.lease(STAMP, "a")["epoch"], max(results))


class SendbackTests(unittest.TestCase):
    def run_threads(self, state: State) -> list[int | None]:
        out: list[int | None] = []
        guard = threading.Lock()

        def go(n: int) -> None:
            got = state.sendback(STAMP, "a", f"fix {n}", limit=2)
            with guard:
                out.append(got)

        threads = [threading.Thread(target=go, args=(n,)) for n in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        return out

    def test_counter_is_atomic_on_disk(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        state = State(FileStore(tmp.name))
        out = self.run_threads(state)
        self.assertEqual(sorted(x for x in out if x is not None), [1, 2])
        self.assertEqual(out.count(None), 6)
        self.assertEqual(len(state.store.list(state_io.lane_rel(STAMP, "a"), "send-back-*.md")), 2)

    def test_counter_is_atomic_in_memory(self) -> None:
        out = self.run_threads(State(MemoryStore()))
        self.assertEqual(sorted(x for x in out if x is not None), [1, 2])

    def test_text_names_the_lane(self) -> None:
        state = State(MemoryStore())
        state.sendback(STAMP, "a", "tighten the test")
        text = state.store.read_text(state_io.lane_rel(STAMP, "a", "send-back-1.md"))
        self.assertIn("lane a", text)
        self.assertIn("tighten the test", text)


class LockedMergeTests(unittest.TestCase):
    def test_update_record_does_not_lose_concurrent_changes(self) -> None:
        state = State(MemoryStore())
        path = state_io.lane_rel(STAMP, "a", "status.json")

        def bump(key: str) -> None:
            for i in range(10):
                state.update_record(path, {key: i})

        threads = [threading.Thread(target=bump, args=(k,)) for k in "xyz"]
        [t.start() for t in threads]
        [t.join() for t in threads]
        record = state.read_record(path)
        self.assertEqual({k: record[k] for k in "xyz"}, {"x": 9, "y": 9, "z": 9})
        self.assertEqual(json.loads(state.store.read_text(path))["v"], 1)


if __name__ == "__main__":
    unittest.main()
