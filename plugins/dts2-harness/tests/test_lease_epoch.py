"""Lease epochs in lanes.py: they increment per lease, and a stale epoch cannot overwrite a newer lease."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "lanes.py"
STAMP: Final[str] = "20261104-1"


class LeaseEpochTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dts2-epoch-"))
        self.repo = self.root / "repo"
        self.repo.mkdir()
        data = {"stamp": STAMP, "base": "abc", "scope": "single",
                "lanes": [{"id": "a", "item": "Sa", "files": ["src/a.py"], "ids": {}, "depends_on": [],
                           "tier": "standard"}]}
        self.manifest = self.root / "m.json"
        self.manifest.write_text(json.dumps(data), encoding="utf-8")
        self.lease_file = self.repo / ".harness" / "runs" / STAMP / "a" / "lease.json"

    def cmd(self, *args: str) -> dict[str, Any]:
        done = subprocess.run([sys.executable, "-I", str(SCRIPT), "--cwd", str(self.repo), "--no-prs", *args],
                              capture_output=True, text=True, check=False)
        return json.loads(done.stdout)

    def lease(self, *extra: str) -> dict[str, Any]:
        return self.cmd("lease", str(self.manifest), "--lane", "a", *extra)

    def test_epochs_increment(self) -> None:
        first = self.lease()
        second = self.lease()
        self.assertEqual((first["epoch"], second["epoch"]), (1, 2))
        self.assertEqual(json.loads(self.lease_file.read_text(encoding="utf-8"))["epoch"], 2)

    def test_older_epoch_cannot_overwrite_newer_lease(self) -> None:
        self.lease()
        self.lease()
        before = self.lease_file.read_text(encoding="utf-8")
        claim = self.lease("--epoch", "1")
        self.assertFalse(claim["ok"])
        self.assertIn("epoch 1", claim["detail"])
        self.assertIn("epoch 2", claim["detail"])
        self.assertEqual(self.lease_file.read_text(encoding="utf-8"), before)
        release = self.cmd("release", STAMP, "--lane", "a", "--epoch", "1")
        self.assertFalse(release["ok"])
        self.assertIn("epoch 1", release["detail"])
        self.assertIn("epoch 2", release["detail"])
        self.assertEqual(self.lease_file.read_text(encoding="utf-8"), before)

    def test_stale_lock_from_crashed_writer_is_cleared(self) -> None:
        lock = self.lease_file.with_suffix(".json.lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("", encoding="utf-8")
        old = time.time() - 3600
        os.utime(lock, (old, old))
        claim = self.lease()
        self.assertTrue(claim["ok"], claim)
        self.assertFalse(lock.exists())

    def test_fresh_lock_still_blocks(self) -> None:
        lock = self.lease_file.with_suffix(".json.lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("", encoding="utf-8")
        claim = self.lease()
        self.assertFalse(claim["ok"])
        self.assertEqual(claim["detail"], "lease busy")
        self.assertTrue(lock.exists())

    def test_equal_epoch_succeeds(self) -> None:
        self.lease()
        again = self.lease("--epoch", "1")
        self.assertTrue(again["ok"], again)
        self.assertEqual(again["epoch"], 2)
        released = self.cmd("release", STAMP, "--lane", "a", "--epoch", "2")
        self.assertTrue(released["ok"], released)
        record = json.loads(self.lease_file.read_text(encoding="utf-8"))
        self.assertEqual((record["status"], record["epoch"]), ("closed", 2))

    def test_omitted_epoch_keeps_old_behaviour(self) -> None:
        self.lease()
        self.assertTrue(self.cmd("release", STAMP, "--lane", "a")["ok"])

    def test_corrupt_lease_is_not_overwritten(self) -> None:
        self.lease_file.parent.mkdir(parents=True)
        self.lease_file.write_text("garbage", encoding="utf-8")
        result = self.lease("--epoch", "1")
        self.assertFalse(result["ok"])
        self.assertIn("unreadable lease", result["detail"])
        self.assertEqual(self.lease_file.read_text(encoding="utf-8"), "garbage")


if __name__ == "__main__":
    unittest.main()
