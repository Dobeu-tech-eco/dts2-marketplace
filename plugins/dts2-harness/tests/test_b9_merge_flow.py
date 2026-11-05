"""B6: integration-lane routing, the five-task bundle cap, the merge-tree probe and the merge plan."""
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
STAMP: Final[str] = "20261105-1"
FAKE_GH: Final[str] = """#!/usr/bin/env python3
import os, sys
if "api" in sys.argv:
    print(os.environ.get("FAKE_RULES", "[]"))
else:
    print("[]")
"""


def lane(lane_id: str, files: list[str], tasks: list[str] | None = None, depends_on: list[str] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {"id": lane_id, "item": f"S{lane_id}", "files": files, "ids": {"D": []},
                            "depends_on": depends_on or [], "tier": "standard"}
    if tasks is not None:
        data["tasks"] = tasks
    return data


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="dts2-b9-"))
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.fake = self.root / "fake"
        self.fake.mkdir()
        (self.fake / "gh.py").write_text(FAKE_GH, encoding="utf-8")

    def run_cmd(self, *args: str, rules: str = "[]", extra_env: dict[str, str] | None = None) -> dict[str, Any]:
        env = {**os.environ, "DTS2_GH_BIN": str(self.fake / "gh.py"), "FAKE_RULES": rules, **(extra_env or {})}
        done = subprocess.run([sys.executable, "-I", str(SCRIPT), "--cwd", str(self.repo), *args],
                              capture_output=True, text=True, env=env, check=False)
        parsed: dict[str, Any] = json.loads(done.stdout)
        parsed["_code"] = done.returncode
        return parsed

    def manifest(self, lanes: list[dict[str, Any]]) -> str:
        path = self.root / "m.json"
        path.write_text(json.dumps({"stamp": STAMP, "base": "abc1234", "scope": "single", "lanes": lanes}), encoding="utf-8")
        return str(path)

    def config(self, text: str) -> None:
        (self.repo / ".harness").mkdir(exist_ok=True)
        (self.repo / ".harness" / "config.yaml").write_text(text, encoding="utf-8")


class IntegrationRoutingTests(Base):
    def test_lockfile_and_migration_conflict_is_routed_not_blocking(self) -> None:
        lanes = [lane("a", ["src/a/x.py", "package-lock.json"]), lane("b", ["src/b/y.py", "db/migrations/0002_b.sql"])]
        result = self.run_cmd("check", self.manifest(lanes))
        self.assertEqual([c["kind"] for c in result["conflicts"]], ["schema"])
        self.assertEqual(result["conflicts"][0]["routed"], "integration")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["integration"]["lane"], "integration")
        self.assertEqual(sorted(result["integration"]["files"]), ["db/migrations/0002_b.sql", "package-lock.json"])
        self.assertEqual(result["integration"]["routed"]["a"][0], {"file": "package-lock.json", "kind": "lockfile"})
        self.assertEqual(result["integration"]["routed"]["b"][0]["kind"], "migration")

    def test_shared_barrel_and_route_table_route_to_integration(self) -> None:
        lanes = [lane("a", ["src/a/x.py", "src/index.ts", "src/routes.ts"]),
                 lane("b", ["src/b/y.py", "src/index.ts", "src/routes.ts"])]
        result = self.run_cmd("check", self.manifest(lanes))
        self.assertTrue(result["ok"], result)
        self.assertEqual([c["kind"] for c in result["conflicts"]], ["files"])
        self.assertEqual(result["conflicts"][0]["routed"], "integration")
        kinds = {row["file"]: row["kind"] for row in result["integration"]["routed"]["a"]}
        self.assertEqual(kinds, {"src/index.ts": "barrel", "src/routes.ts": "route-table"})

    def test_routed_files_do_not_cause_area_conflicts(self) -> None:
        lanes = [lane("a", ["src/api/users.py", "src/api/index.ts"]), lane("b", ["src/web/page.py", "src/api/index.ts"])]
        result = self.run_cmd("check", self.manifest(lanes))
        self.assertTrue(result["ok"], result)
        self.assertNotIn("area", [c["kind"] for c in result["conflicts"]])

    def test_ordinary_overlap_still_blocks(self) -> None:
        lanes = [lane("a", ["src/a/x.py", "src/shared/util.py"]), lane("b", ["src/b/y.py", "src/shared/util.py"])]
        result = self.run_cmd("check", self.manifest(lanes))
        self.assertFalse(result["ok"])
        self.assertNotIn("routed", result["conflicts"][0])
        self.assertEqual(result["integration"]["files"], [])

    def test_mixed_overlap_is_not_routed(self) -> None:
        lanes = [lane("a", ["src/a/x.py", "src/index.ts", "src/shared/util.py"]),
                 lane("b", ["src/b/y.py", "src/index.ts", "src/shared/util.py"])]
        result = self.run_cmd("check", self.manifest(lanes))
        self.assertFalse(result["ok"])
        self.assertNotIn("routed", result["conflicts"][0])


class BundleCapTests(Base):
    def test_six_tasks_in_one_lane_is_refused_with_a_split(self) -> None:
        tasks = [f"T{n}" for n in range(1, 7)]
        result = self.run_cmd("check", self.manifest([lane("a", ["src/a/x.py"], tasks)]))
        self.assertFalse(result["ok"])
        found = result["conflicts"][0]
        self.assertEqual(found["kind"], "bundle")
        self.assertIn("5", found["detail"])
        self.assertIn("one commit per task", found["alternative"])

    def test_five_tasks_pass(self) -> None:
        tasks = [f"T{n}" for n in range(1, 6)]
        result = self.run_cmd("check", self.manifest([lane("a", ["src/a/x.py"], tasks)]))
        self.assertTrue(result["ok"], result)


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True, env=env).stdout


class MergePlanTests(Base):
    def make_repo(self) -> None:
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "f.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
        (self.repo / "g.txt").write_text("g\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "init")
        for lane_id, name, body in (("a", "f.txt", "ONE\ntwo\nthree\n"), ("b", "g.txt", "g2\n")):
            git(self.repo, "checkout", "-q", "-b", f"dts2/{STAMP}/lane-{lane_id}", "main")
            (self.repo / name).write_text(body, encoding="utf-8")
            git(self.repo, "commit", "-q", "-am", f"lane {lane_id}")
        git(self.repo, "checkout", "-q", "main")
        (self.repo / "f.txt").write_text("uno\ntwo\nthree\n", encoding="utf-8")
        git(self.repo, "commit", "-q", "-am", "main moves")

    def test_probe_defers_the_conflicting_lane(self) -> None:
        self.make_repo()
        lanes = [lane("a", ["f.txt"]), lane("b", ["g.txt"])]
        result = self.run_cmd("merge-plan", self.manifest(lanes), "--base", "main")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["probe"], {"a": "conflict", "b": "clean"})
        self.assertEqual(result["order"], ["b", "a"])
        self.assertTrue(result["reordered"])

    def test_probe_never_breaks_dependency_order(self) -> None:
        self.make_repo()
        lanes = [lane("a", ["f.txt"]), lane("b", ["g.txt"], depends_on=["a"])]
        result = self.run_cmd("merge-plan", self.manifest(lanes), "--base", "main")
        self.assertEqual(result["order"], ["a", "b"])
        self.assertFalse(result["reordered"])

    def test_missing_branch_probes_unknown_and_keeps_order(self) -> None:
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "f.txt").write_text("x\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "init")
        result = self.run_cmd("merge-plan", self.manifest([lane("a", ["f.txt"]), lane("b", ["g.txt"])]), "--base", "main")
        self.assertEqual(result["probe"], {"a": "unknown", "b": "unknown"})
        self.assertEqual(result["order"], ["a", "b"])

    def test_serial_mode_without_a_merge_queue(self) -> None:
        self.make_repo()
        result = self.run_cmd("merge-plan", self.manifest([lane("a", ["f.txt"]), lane("b", ["g.txt"])]), "--base", "main")
        self.assertEqual(result["mode"], "serial")
        steps = [(s["lane"], s["do"]) for s in result["steps"]]
        self.assertIn(("b", "rebase"), steps)
        self.assertEqual([s["do"] for s in result["steps"] if s["lane"] == "b"], ["rebase", "test", "merge"])

    def test_queue_mode_when_the_target_has_a_merge_queue(self) -> None:
        self.make_repo()
        result = self.run_cmd("merge-plan", self.manifest([lane("a", ["f.txt"]), lane("b", ["g.txt"])]), "--base", "main",
                              rules=json.dumps([{"type": "pull_request"}, {"type": "merge_queue"}]))
        self.assertEqual(result["mode"], "queue")
        self.assertEqual({s["do"] for s in result["steps"]}, {"enqueue"})

    def test_integration_lane_merges_last(self) -> None:
        self.make_repo()
        lanes = [lane("a", ["f.txt", "package-lock.json"]), lane("b", ["g.txt", "package-lock.json"])]
        result = self.run_cmd("merge-plan", self.manifest(lanes), "--base", "main")
        self.assertEqual(result["order"][-1], "integration")
        self.assertEqual(result["integration"]["files"], ["package-lock.json"])
        self.assertEqual(result["steps"][-1]["lane"], "integration")


if __name__ == "__main__":
    unittest.main()
