"""G-16: leases carry `expires_at`, expired or closed leases stop blocking other runs, a heartbeat renews, and the check
and the lease are one locked step."""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Final
from unittest import mock

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lanes import leases  # noqa: E402
from lanes.common import lease_live  # noqa: E402
from lanes.conflicts import active_run_files  # noqa: E402
from lanes.leases import lease, lease_ttl_s, renew_lease  # noqa: E402
from lanes.phases import transition  # noqa: E402
from lanes.planner import active_lease_files  # noqa: E402

NEW: Final[str] = "20261105-2"
OLD: Final[str] = "20261105-1"
NOW: Final[int] = int(time.time())


def manifest(stamp: str, files: list[str], lane_id: str = "a") -> dict[str, Any]:
    return {"stamp": stamp, "base": "abc", "scope": "single",
            "lanes": [{"id": lane_id, "item": "S1", "files": files, "ids": {}, "depends_on": [], "tier": "standard"}]}


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="dts2-g16-"))
        self.runs = self.repo / ".harness" / "runs"

    def other_run(self, files: list[str], lease_record: dict[str, Any] | None) -> None:
        """A second, unclosed run whose manifest is on disk, with the given lease for its lane (None: no lease yet)."""
        folder = self.runs / OLD
        (folder / "a").mkdir(parents=True)
        (folder / "lanes.json").write_text(json.dumps(manifest(OLD, files)), encoding="utf-8")
        if lease_record is not None:
            (folder / "a" / "lease.json").write_text(json.dumps(lease_record), encoding="utf-8")


class LeaseLiveTests(unittest.TestCase):
    def test_live_means_active_and_not_expired(self) -> None:
        self.assertTrue(lease_live({"status": "active", "expires_at": NOW + 1}, NOW))
        self.assertFalse(lease_live({"status": "active", "expires_at": NOW}, NOW))
        self.assertFalse(lease_live({"status": "closed", "expires_at": NOW + 99}, NOW))
        self.assertTrue(lease_live({"status": "active"}, NOW), "a lease from before G-16 has no expiry and never lapses")
        self.assertFalse(lease_live(None, NOW))


class ExpiryTests(Base):
    def test_a_new_lease_records_its_expiry_and_ttl(self) -> None:
        result = lease(manifest(NEW, ["src/a.py"]), "a", self.runs, self.repo, False)
        self.assertTrue(result["ok"], result)
        record = json.loads((self.runs / NEW / "a" / "lease.json").read_text(encoding="utf-8"))
        ttl = lease_ttl_s(self.repo)
        self.assertEqual(record["ttl_s"], ttl)
        self.assertEqual(record["expires_at"], record["created"] + ttl)
        self.assertEqual(result["expires_at"], record["expires_at"])

    def test_ttl_follows_the_wall_clock_cap(self) -> None:
        (self.repo / ".harness").mkdir()
        (self.repo / ".harness" / "config.yaml").write_text("budget:\n  max_wall_minutes: 30\n", encoding="utf-8")
        self.assertEqual(lease_ttl_s(self.repo), 30 * 60 * 2)

    def test_another_runs_live_lease_blocks(self) -> None:
        self.other_run(["src/a.py"], {"status": "active", "expires_at": NOW + 600, "files": ["src/a.py"]})
        self.assertEqual([label for label, _files in active_run_files(self.runs, NEW, NOW)], [f"run:{OLD}"])
        self.assertEqual(active_run_files(self.runs, NEW, NOW)[0][1], {"src/a.py"})
        refused = lease(manifest(NEW, ["src/a.py"]), "a", self.runs, self.repo, False)
        self.assertFalse(refused["ok"])

    def test_another_runs_expired_lease_is_skipped(self) -> None:
        self.other_run(["src/a.py"], {"status": "active", "expires_at": NOW - 1})
        self.assertEqual(active_run_files(self.runs, NEW, NOW)[0][1], set())
        granted = lease(manifest(NEW, ["src/a.py"]), "a", self.runs, self.repo, False)
        self.assertTrue(granted["ok"], granted)

    def test_another_runs_closed_lease_is_skipped(self) -> None:
        self.other_run(["src/a.py"], {"status": "closed", "expires_at": NOW + 600})
        self.assertEqual(active_run_files(self.runs, NEW, NOW)[0][1], set())

    def test_a_lane_with_no_lease_counts_until_its_manifest_is_old(self) -> None:
        self.other_run(["src/a.py"], None)
        self.assertEqual(active_run_files(self.runs, NEW, int(time.time()))[0][1], {"src/a.py"})
        later = int(time.time()) + 10 * 24 * 3600
        self.assertEqual(active_run_files(self.runs, NEW, later)[0][1], set())

    def test_this_runs_expired_lease_no_longer_holds_files_for_plan(self) -> None:
        folder = self.runs / NEW / "b"
        folder.mkdir(parents=True)
        (folder / "lease.json").write_text(json.dumps({"status": "active", "lane": "b", "expires_at": NOW - 5,
                                                       "files": ["src/b.py"]}), encoding="utf-8")
        self.assertEqual(active_lease_files(self.runs, NEW, NOW), [])
        (folder / "lease.json").write_text(json.dumps({"status": "active", "lane": "b", "expires_at": NOW + 5,
                                                       "files": ["src/b.py"]}), encoding="utf-8")
        self.assertEqual(active_lease_files(self.runs, NEW, NOW), [(f"lane {NEW}/b", {"src/b.py"})])


class RenewTests(Base):
    def test_renew_pushes_the_expiry_out_by_the_ttl(self) -> None:
        lease(manifest(NEW, ["src/a.py"]), "a", self.runs, self.repo, False)
        path = self.runs / NEW / "a" / "lease.json"
        self.assertTrue(renew_lease(path, NOW))
        record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(record["expires_at"], NOW + record["ttl_s"])

    def test_nothing_to_renew_for_a_closed_or_missing_lease(self) -> None:
        path = self.runs / NEW / "a" / "lease.json"
        self.assertFalse(renew_lease(path, NOW))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"status": "closed", "ttl_s": 60}), encoding="utf-8")
        self.assertFalse(renew_lease(path, NOW))

    def test_a_heartbeat_keeps_a_lane_alive_past_its_original_expiry(self) -> None:
        lease(manifest(NEW, ["src/a.py"]), "a", self.runs, self.repo, False)
        path = self.runs / NEW / "a" / "lease.json"
        path.write_text(json.dumps({**json.loads(path.read_text(encoding="utf-8")), "expires_at": 5}), encoding="utf-8")
        transition(self.runs, NEW, "a", "starting", now=NOW)
        self.assertTrue(lease_live(json.loads(path.read_text(encoding="utf-8")), NOW))


class OneLockedStepTests(Base):
    def test_the_check_runs_while_the_admission_lock_is_held(self) -> None:
        seen: list[bool] = []
        real = leases.check

        def checking(*args: Any, **kwargs: Any) -> dict[str, Any]:
            seen.append((self.runs / f"{leases.ADMISSION_NAME}.lock").exists())
            return real(*args, **kwargs)

        with mock.patch.object(leases, "check", checking):
            result = lease(manifest(NEW, ["src/a.py"]), "a", self.runs, self.repo, False)
        self.assertTrue(result["ok"])
        self.assertEqual(seen, [True])
        self.assertFalse((self.runs / f"{leases.ADMISSION_NAME}.lock").exists(), "the lock is released afterwards")

    def test_a_stale_epoch_is_still_refused(self) -> None:
        lease(manifest(NEW, ["src/a.py"]), "a", self.runs, self.repo, False)
        lease(manifest(NEW, ["src/a.py"]), "a", self.runs, self.repo, False)
        refused = lease(manifest(NEW, ["src/a.py"]), "a", self.runs, self.repo, False, epoch=1)
        self.assertFalse(refused["ok"])
        self.assertIn("epoch 2", refused["detail"])


if __name__ == "__main__":
    unittest.main()


class SessionIdTests(Base):
    def test_lease_carries_the_session_id_when_known(self) -> None:
        import os
        path = self.runs / NEW / "a" / "lease.json"
        with mock.patch.dict(os.environ, {"CLAUDE_SESSION_ID": "sess-9"}):
            lease(manifest(NEW, ["src/a.py"]), "a", self.runs, self.repo, False)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["session_id"], "sess-9")
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_SESSION_ID"}
        with mock.patch.dict(os.environ, env, clear=True):
            lease(manifest(NEW, ["src/a.py"]), "a", self.runs, self.repo, False)
        self.assertNotIn("session_id", json.loads(path.read_text(encoding="utf-8")))
