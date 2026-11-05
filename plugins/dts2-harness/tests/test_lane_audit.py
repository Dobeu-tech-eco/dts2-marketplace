"""Lane ownership gate: merge-go refuses a lane whose branch changed files outside its owned set, and `lanes.py audit` says why."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final
from unittest import mock

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lanes.audit import lane_audit  # noqa: E402
from lanes.merge import audit_lane, merge_done, merge_go, merge_order, record_plan  # noqa: E402
from lanes.phases import transition  # noqa: E402
from state_io import HARNESS  # noqa: E402

STAMP: Final[str] = "20261105-7"
CLI: Final[Path] = SCRIPTS / "lanes.py"
GIT_ENV: Final[dict[str, str]] = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                                  "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def lane(lane_id: str, files: list[str]) -> dict[str, Any]:
    return {"id": lane_id, "item": f"S{lane_id}", "files": files, "ids": {}, "depends_on": [], "tier": "standard"}


class AuditBase(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="dts2-audit-"))
        self.runs = self.repo / HARNESS / "runs"
        self.git("init", "-q", "-b", "main")
        self.write("src/a/keep.py", "x = 1\n")
        self.write(".git/info/exclude", f"{HARNESS}/\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.base = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "-b", "lane")

    def git(self, *args: str) -> str:
        done = subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True, check=True, env={**os.environ, **GIT_ENV})
        return done.stdout.strip()

    def write(self, rel: str, text: str) -> None:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self, *rels: str) -> str:
        for rel in rels:
            self.write(rel, f"changed {rel}\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "lane work")
        return self.git("rev-parse", "HEAD")

    def manifest(self, *lanes: dict[str, Any]) -> dict[str, Any]:
        return {"stamp": STAMP, "base": self.base, "scope": "single", "lanes": list(lanes)}

    def open_pr(self, lane_id: str) -> None:
        transition(self.runs, STAMP, lane_id, "pr-open")


class LaneAuditTests(AuditBase):
    def test_changes_inside_the_owned_set_pass(self) -> None:
        head = self.commit("src/a/new.py")
        result = lane_audit(self.manifest(lane("a", ["src/a/"])), "a", head, self.base, self.repo)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["changed"], ["src/a/new.py"])
        self.assertEqual(result["violations"], [])

    def test_changes_outside_the_owned_set_are_listed(self) -> None:
        head = self.commit("src/a/new.py", "src/b/other.py")
        result = lane_audit(self.manifest(lane("a", ["src/a/"])), "a", head, self.base, self.repo)
        self.assertFalse(result["ok"])
        self.assertIn("src/b/other.py", result["violations"][0]["detail"])
        self.assertNotIn("src/a/new.py", result["violations"][0]["detail"])

    def test_glob_patterns_own_matching_files(self) -> None:
        head = self.commit("docs/one.md", "docs/two.md")
        self.assertTrue(lane_audit(self.manifest(lane("a", ["docs/*.md"])), "a", head, self.base, self.repo)["ok"])
        self.assertFalse(lane_audit(self.manifest(lane("a", ["docs/*.txt"])), "a", head, self.base, self.repo)["ok"])

    def test_git_failure_fails_closed(self) -> None:
        self.commit("src/a/new.py")
        result = lane_audit(self.manifest(lane("a", ["src/a/"])), "a", "no-such-ref", self.base, self.repo)
        self.assertFalse(result["ok"])
        self.assertIn("git diff", result["detail"])
        with mock.patch.dict(os.environ, {"DTS2_GIT_BIN": str(self.repo / "missing-git")}):
            broken = lane_audit(self.manifest(lane("a", ["src/a/"])), "a", "HEAD", self.base, self.repo)
        self.assertFalse(broken["ok"])

    def test_a_base_that_is_not_a_sha_is_refused(self) -> None:
        result = lane_audit(self.manifest(lane("a", ["src/a/"])), "a", "HEAD", "--output=x", self.repo)
        self.assertFalse(result["ok"])

    def test_the_integration_lane_is_audited_against_the_integration_files(self) -> None:
        manifest = self.manifest(lane("a", ["src/a/"]))
        self.assertTrue(record_plan(manifest, self.runs, ["a"], ["package-lock.json"]))
        good = self.commit("package-lock.json")
        self.assertTrue(audit_lane(manifest, self.runs, "integration", good, self.repo, self.base)["ok"])
        bad = self.commit("src/a/new.py")
        result = audit_lane(manifest, self.runs, "integration", bad, self.repo, self.base)
        self.assertFalse(result["ok"])
        self.assertIn("src/a/new.py", result["violations"][0]["detail"])


class MergeGoGateTests(AuditBase):
    def grant(self, manifest: dict[str, Any], lane_id: str, head: str) -> dict[str, Any]:
        self.open_pr(lane_id)
        merge_order(manifest, self.runs)
        return merge_go(manifest, self.runs, lane_id, head, self.repo, self.base)

    def test_merge_go_grants_a_lane_that_stayed_inside(self) -> None:
        manifest = self.manifest(lane("a", ["src/a/"]))
        result = self.grant(manifest, "a", self.commit("src/a/new.py"))
        self.assertTrue(result["ok"], result)
        self.assertTrue((self.runs / STAMP / "a" / "merge-go.md").is_file())

    def test_merge_go_refuses_a_lane_that_changed_files_outside(self) -> None:
        manifest = self.manifest(lane("a", ["src/a/"]))
        result = self.grant(manifest, "a", self.commit("src/a/new.py", "README.md"))
        self.assertFalse(result["ok"])
        self.assertIn("lane a changed files outside its owned set", result["detail"])
        self.assertIn("README.md", result["detail"])
        self.assertTrue(result["violations"])
        self.assertFalse((self.runs / STAMP / "a" / "merge-go.md").exists())
        state = json.loads((self.runs / STAMP / "merge-order.json").read_text(encoding="utf-8"))
        self.assertIsNone(state["current"])

    def test_merge_go_refuses_when_git_cannot_answer(self) -> None:
        manifest = self.manifest(lane("a", ["src/a/"]))
        self.commit("src/a/new.py")
        result = self.grant(manifest, "a", "no-such-ref")
        self.assertFalse(result["ok"])
        self.assertFalse((self.runs / STAMP / "a" / "merge-go.md").exists())

    def test_integration_lane_merge_go_checks_integration_files(self) -> None:
        manifest = self.manifest(lane("a", ["src/a/"]))
        self.assertTrue(record_plan(manifest, self.runs, ["a"], ["package-lock.json"]))
        self.open_pr("a")
        self.assertTrue(merge_go(manifest, self.runs, "a", self.commit("src/a/new.py"), self.repo, self.base)["ok"])
        self.assertTrue(merge_done(manifest, self.runs, "a")["ok"])
        self.git("checkout", "-q", "-b", "integration", self.base)
        stray = self.commit("package-lock.json", "src/b/stray.py")
        refused = merge_go(manifest, self.runs, "integration", stray, self.repo, self.base)
        self.assertFalse(refused["ok"])
        self.assertIn("src/b/stray.py", refused["detail"])
        self.git("reset", "-q", "--hard", self.base)
        clean = self.commit("package-lock.json")
        self.assertTrue(merge_go(manifest, self.runs, "integration", clean, self.repo, self.base)["ok"])


class AuditCommandTests(AuditBase):
    def cli(self, *args: str) -> dict[str, Any]:
        done = subprocess.run([sys.executable, "-I", str(CLI), "--cwd", str(self.repo), "--no-prs", *args],
                              capture_output=True, text=True, check=False, env={**os.environ, **GIT_ENV})
        parsed: dict[str, Any] = json.loads(done.stdout)
        return parsed

    def test_audit_command_reports_violations(self) -> None:
        path = self.repo.parent / f"{self.repo.name}-lanes.json"
        path.write_text(json.dumps(self.manifest(lane("a", ["src/a/"]))), encoding="utf-8")
        inside = self.commit("src/a/new.py")
        self.assertTrue(self.cli("audit", str(path), "a", "--head", inside, "--base", self.base)["ok"])
        outside = self.commit("README.md")
        result = self.cli("audit", str(path), "a", "--head", outside, "--base", self.base)
        self.assertFalse(result["ok"])
        self.assertEqual(result["changed"], ["README.md", "src/a/new.py"])


if __name__ == "__main__":
    unittest.main()
