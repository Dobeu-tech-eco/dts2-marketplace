"""G-29: lanes.py amend re-checks the manifest, bumps the epoch and rewrites the son's brief."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "lanes.py"
STAMP: Final[str] = "20261105-2"


def lane(lane_id: str, files: list[str]) -> dict[str, Any]:
    return {"id": lane_id, "item": f"S{lane_id}", "files": files, "ids": {}, "depends_on": [], "tier": "standard"}


class AmendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dts2-amend-"))
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.manifest = self.root / "m.json"
        data = {"stamp": STAMP, "base": "abc1234", "scope": "single",
                "lanes": [lane("a", ["src/a/x.py"]), lane("b", ["src/b/y.py"])]}
        self.manifest.write_text(json.dumps(data), encoding="utf-8")
        self.run_dir = self.repo / ".harness" / "runs" / STAMP

    def cmd(self, *args: str) -> tuple[int, dict[str, Any]]:
        done = subprocess.run([sys.executable, "-I", str(SCRIPT), "--cwd", str(self.repo), "--no-prs", *args],
                              capture_output=True, text=True, check=False)
        return done.returncode, json.loads(done.stdout)

    def files_of(self, lane_id: str) -> list[str]:
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        return next(x["files"] for x in data["lanes"] if x["id"] == lane_id)

    def lease_a(self) -> dict[str, Any]:
        return self.cmd("lease", str(self.manifest), "--lane", "a")[1]

    def test_amend_rechecks_bumps_the_epoch_and_rewrites_the_brief(self) -> None:
        self.assertEqual(self.lease_a()["epoch"], 1)
        code, out = self.cmd("amend", str(self.manifest), "--lane", "a", "--add-files", "src/a/z.py,tests/a/test_z.py", "--remove-files", "src/a/x.py")
        self.assertEqual((code, out["ok"]), (0, True), out)
        self.assertEqual((out["epoch"], out["previous_epoch"]), (2, 1))
        self.assertEqual(self.files_of("a"), ["src/a/z.py", "tests/a/test_z.py"])
        lease = json.loads((self.run_dir / "a" / "lease.json").read_text(encoding="utf-8"))
        self.assertEqual((lease["epoch"], lease["files"]), (2, ["src/a/z.py", "tests/a/test_z.py"]))
        brief = (self.run_dir / "a" / "brief.md").read_text(encoding="utf-8")
        self.assertIn("epoch: 2", brief)
        self.assertIn("src/a/z.py", brief)
        self.assertIn("## Amended", brief)
        self.assertIn("Removed: src/a/x.py", brief)

    def test_old_epoch_release_is_refused_after_an_amend(self) -> None:
        self.lease_a()
        self.cmd("amend", str(self.manifest), "--lane", "a", "--add-files", "src/a/z.py")
        code, out = self.cmd("release", STAMP, "--lane", "a", "--epoch", "1")
        self.assertFalse(out["ok"])
        self.assertIn("epoch 1", out["detail"])

    def test_a_conflicting_amend_changes_nothing(self) -> None:
        self.lease_a()
        before = self.manifest.read_text(encoding="utf-8")
        code, out = self.cmd("amend", str(self.manifest), "--lane", "a", "--add-files", "src/b/y.py")
        self.assertEqual((code, out["ok"]), (2, False))
        self.assertEqual([c["kind"] for c in out["conflicts"]], ["files"])
        self.assertEqual(self.manifest.read_text(encoding="utf-8"), before)
        self.assertEqual(json.loads((self.run_dir / "a" / "lease.json").read_text(encoding="utf-8"))["epoch"], 1)
        self.assertFalse((self.run_dir / "a" / "brief.md").exists())

    def test_an_amend_that_empties_the_lane_or_adds_a_cycle_is_refused(self) -> None:
        code, out = self.cmd("amend", str(self.manifest), "--lane", "a", "--set-files", "")
        self.assertFalse(out["ok"])
        self.assertEqual(out["conflicts"][0]["kind"], "owners")
        self.cmd("amend", str(self.manifest), "--lane", "b", "--depends-on", "a")
        code, out = self.cmd("amend", str(self.manifest), "--lane", "a", "--depends-on", "b")
        self.assertFalse(out["ok"])

    def test_a_prefix_amend_that_overlaps_a_sibling_is_refused(self) -> None:
        code, out = self.cmd("amend", str(self.manifest), "--lane", "a", "--add-files", "src/b/")
        self.assertFalse(out["ok"])
        self.assertIn("owners", [c["kind"] for c in out["conflicts"]])

    def test_a_settled_lane_cannot_be_amended(self) -> None:
        self.lease_a()
        status = self.run_dir / "a" / "status.json"
        status.write_text(json.dumps({"status": "done"}), encoding="utf-8")
        code, out = self.cmd("amend", str(self.manifest), "--lane", "a", "--add-files", "src/a/z.py")
        self.assertFalse(out["ok"])
        self.assertIn("done or parked", out["detail"])

    def test_nothing_to_amend_and_unknown_lane_are_errors(self) -> None:
        code, out = self.cmd("amend", str(self.manifest), "--lane", "a")
        self.assertEqual((code, out["ok"]), (1, False))
        code, out = self.cmd("amend", str(self.manifest), "--lane", "zz", "--add-files", "q.py")
        self.assertEqual((code, out["ok"]), (1, False))

    def test_contract_fields_are_amendable(self) -> None:
        code, out = self.cmd("amend", str(self.manifest), "--lane", "a", "--provides", "Api")
        self.assertTrue(out["ok"], out)
        code, out = self.cmd("amend", str(self.manifest), "--lane", "b", "--consumes", "Api", "--stubbed-on", "Api")
        self.assertTrue(out["ok"], out)
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(next(x for x in data["lanes"] if x["id"] == "b")["stubbed_on"], ["Api"])


if __name__ == "__main__":
    unittest.main()
