"""Contracts for lanes.py: lane overlap check, leases, and branch-name collisions."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "lanes.py"
FAKE_GH: Final[str] = """#!/usr/bin/env python3
import json, os, sys
print(os.environ.get("FAKE_PRS", "[]"))
"""
FAKE_GIT: Final[str] = """#!/usr/bin/env python3
import os, sys
if "--version" in sys.argv:
    print("git version 2.40.0")
else:
    print(os.environ.get("FAKE_REFS", ""))
"""


def lane(lane_id: str, files: list[str], ids: list[str] | None = None, depends_on: list[str] | None = None) -> dict[str, Any]:
    return {"id": lane_id, "item": f"S{lane_id}", "files": files, "ids": {"D": ids or []},
            "depends_on": depends_on or [], "tier": "standard"}


def manifest(lanes: list[dict[str, Any]], stamp: str = "20261104-1", scope_root: str | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {"stamp": stamp, "base": "655d4f8", "scope": "single", "lanes": lanes}
    if scope_root:
        data["scope_root"] = scope_root
    return data


class LanesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dts2-lanes-"))
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.fake = self.root / "fake"
        self.fake.mkdir()
        (self.fake / "gh.py").write_text(FAKE_GH, encoding="utf-8")
        (self.fake / "git.py").write_text(FAKE_GIT, encoding="utf-8")

    def run_cmd(self, *args: str, prs: str = "[]", refs: str = "") -> dict[str, Any]:
        env = {**os.environ, "DTS2_GH_BIN": str(self.fake / "gh.py"), "DTS2_GIT_BIN": str(self.fake / "git.py"),
               "FAKE_PRS": prs, "FAKE_REFS": refs}
        done = subprocess.run([sys.executable, "-I", str(SCRIPT), "--cwd", str(self.repo), *args],
                              capture_output=True, text=True, env=env, check=False)
        parsed: dict[str, Any] = json.loads(done.stdout)
        parsed["_code"] = done.returncode
        return parsed

    def write_manifest(self, data: dict[str, Any], name: str = "m.json") -> str:
        path: Path = self.root / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return str(path)

    def kinds(self, result: dict[str, Any]) -> list[str]:
        return [c["kind"] for c in result["conflicts"]]

    def test_check_clean_five_lanes(self) -> None:
        lanes = [lane(x, [f"src/{x}/{x}.py", f"tests/{x}/test_{x}.py"], [f"D{n}"]) for n, x in enumerate("abcde", 10)]
        result = self.run_cmd("check", self.write_manifest(manifest(lanes)))
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["lanes"], 5)
        self.assertTrue(result["prs_checked"])

    def test_check_flags_file_overlap_with_alternative(self) -> None:
        lanes = [lane("a", ["src/a/x.py", "src/shared/util.py"]), lane("b", ["src/b/y.py", "src/shared/util.py"])]
        result = self.run_cmd("check", self.write_manifest(manifest(lanes)))
        self.assertFalse(result["ok"])
        self.assertIn("files", self.kinds(result))
        found = next(c for c in result["conflicts"] if c["kind"] == "files")
        self.assertEqual((found["lane"], found["with"]), ("a", "b"))
        self.assertIn("src/shared/util.py", found["alternative"])
        self.assertEqual(result["_code"], 2)

    def test_check_flags_lockfile_share(self) -> None:
        lanes = [lane("a", ["src/a/x.py", "package-lock.json"]), lane("b", ["src/b/y.py", "db/migrations/0002_b.sql"])]
        result = self.run_cmd("check", self.write_manifest(manifest(lanes)))
        self.assertEqual(self.kinds(result), ["schema"])
        self.assertIn("serialize", result["conflicts"][0]["alternative"])

    def test_check_flags_id_overlap(self) -> None:
        lanes = [lane("a", ["src/a/x.py"], ["D63", "D64"]), lane("b", ["src/b/y.py"], ["D64"])]
        result = self.run_cmd("check", self.write_manifest(manifest(lanes)))
        self.assertEqual(self.kinds(result), ["ids"])
        self.assertIn("D64", result["conflicts"][0]["detail"])

    def test_check_flags_depends_on(self) -> None:
        lanes = [lane("a", ["src/a/x.py"]), lane("b", ["src/b/y.py"], depends_on=["a"])]
        result = self.run_cmd("check", self.write_manifest(manifest(lanes)))
        self.assertEqual(self.kinds(result), ["depends_on"])
        self.assertEqual(result["conflicts"][0]["lane"], "b")

    def test_check_flags_same_area(self) -> None:
        lanes = [lane("a", ["src/api/users.py"]), lane("b", ["src/api/orders.py"])]
        result = self.run_cmd("check", self.write_manifest(manifest(lanes)))
        self.assertEqual(self.kinds(result), ["area"])
        self.assertIn("src/api", result["conflicts"][0]["detail"])

    def test_check_flags_file_outside_scope_root(self) -> None:
        lanes = [lane("a", ["src/a/x.py", "../other/x.py"])]
        result = self.run_cmd("check", self.write_manifest(manifest(lanes, scope_root=str(self.repo))))
        self.assertEqual(self.kinds(result), ["scope"])
        self.assertEqual(result["conflicts"][0]["with"], "scope_root")

    def test_check_flags_open_pr_files(self) -> None:
        lanes = [lane("a", ["src/a/x.py"])]
        prs = json.dumps([{"number": 12, "files": [{"path": "src/a/x.py"}]}])
        result = self.run_cmd("check", self.write_manifest(manifest(lanes)), prs=prs)
        self.assertEqual(self.kinds(result), ["files"])
        self.assertEqual(result["conflicts"][0]["with"], "pr#12")

    def test_check_without_gh_reports_prs_unchecked(self) -> None:
        lanes = [lane("a", ["src/a/x.py"])]
        env_bin = str(self.fake / "missing.py")
        (self.fake / "missing.py").write_text("import sys; sys.exit(1)\n", encoding="utf-8")
        env = {**os.environ, "DTS2_GH_BIN": env_bin}
        done = subprocess.run([sys.executable, "-I", str(SCRIPT), "--cwd", str(self.repo), "check",
                               self.write_manifest(manifest(lanes))], capture_output=True, text=True, env=env)
        result = json.loads(done.stdout)
        self.assertTrue(result["ok"])
        self.assertFalse(result["prs_checked"])

    def test_lease_refuses_overlap_with_active_run(self) -> None:
        runs: Path = self.repo / ".harness" / "runs"
        older: dict[str, Any] = manifest([lane("z", ["src/a/x.py"])], stamp="20261104-0")
        (runs / "20261104-0").mkdir(parents=True)
        (runs / "20261104-0" / "lanes.json").write_text(json.dumps(older), encoding="utf-8")
        path = self.write_manifest(manifest([lane("a", ["src/a/x.py"]), lane("b", ["src/b/y.py"])]))
        refused = self.run_cmd("lease", path, "--lane", "a")
        self.assertFalse(refused["ok"])
        self.assertEqual(refused["conflicts"][0]["with"], "run:20261104-0")
        self.assertFalse((runs / "20261104-1" / "a" / "lease.json").exists())
        granted = self.run_cmd("lease", path, "--lane", "b")
        self.assertTrue(granted["ok"], granted)
        record = json.loads((runs / "20261104-1" / "b" / "lease.json").read_text(encoding="utf-8"))
        self.assertEqual((record["lane"], record["status"], record["files"]), ("b", "active", ["src/b/y.py"]))

    def test_lease_ignores_closed_runs(self) -> None:
        runs: Path = self.repo / ".harness" / "runs"
        closed: dict[str, Any] = {**manifest([lane("z", ["src/a/x.py"])], stamp="20261104-0"), "status": "closed"}
        (runs / "20261104-0").mkdir(parents=True)
        (runs / "20261104-0" / "lanes.json").write_text(json.dumps(closed), encoding="utf-8")
        result = self.run_cmd("lease", self.write_manifest(manifest([lane("a", ["src/a/x.py"])])), "--lane", "a")
        self.assertTrue(result["ok"], result)

    def test_branch_check_detects_prefix_collision(self) -> None:
        result = self.run_cmd("branch-check", "20261104-1", "--lanes", "a,b", refs="main\ndts2/20261104-1\n")
        self.assertFalse(result["ok"])
        self.assertEqual(result["planned"], ["dts2/20261104-1/main", "dts2/20261104-1/lane-a", "dts2/20261104-1/lane-b"])
        self.assertEqual({c["existing"] for c in result["collisions"]}, {"dts2/20261104-1"})
        clean = self.run_cmd("branch-check", "20261104-1", "--lanes", "a,b", refs="main\norigin/dts2/20261104-0/a\n")
        self.assertTrue(clean["ok"], clean)

    def test_no_fixed_lane_cap(self) -> None:
        # A9/A7 ruling: the old five-lane limit is gone; the model-call limit throttles instead.
        lanes = [lane(x, [f"src/{x}/x.py"]) for x in "abcdef"]
        result = self.run_cmd("check", self.write_manifest(manifest(lanes)))
        self.assertNotIn("error", result)


if __name__ == "__main__":
    unittest.main()
