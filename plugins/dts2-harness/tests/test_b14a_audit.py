"""G-24 + AA-1: shared ownership audit and the thin builder-audit CLI."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT

SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import ownership_audit  # noqa: E402

HEAD: Final[str] = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"


def codes(result: dict[str, object]) -> list[str]:
    return [v["code"] for v in result["violations"]]  # type: ignore[index]


class AuditCoreTests(unittest.TestCase):
    def test_clean_audit_passes(self) -> None:
        result = ownership_audit.audit(["src/a.py", "src/sub/b.py"], ["src/"], HEAD[:7], head=HEAD)
        self.assertTrue(result["ok"])
        self.assertEqual(result["violations"], [])

    def test_empty_diff_with_done_fails(self) -> None:
        result = ownership_audit.audit([], ["src/"], HEAD, head=HEAD, status="DONE")
        self.assertFalse(result["ok"])
        self.assertEqual(codes(result), ["empty_diff"])

    def test_empty_diff_without_done_is_not_flagged(self) -> None:
        self.assertTrue(ownership_audit.audit([], ["src/"], None, head=HEAD, status="BLOCKED")["ok"])

    def test_file_outside_owned_set_fails(self) -> None:
        result = ownership_audit.audit(["src/a.py", "docs/x.md"], ["src/a.py"], HEAD, head=HEAD)
        self.assertEqual(codes(result), ["outside_owned"])
        self.assertIn("docs/x.md", result["violations"][0]["detail"])

    def test_owned_forms_exact_prefix_and_glob(self) -> None:
        owned = ["one.py", "pkg/", "tests/test_*.py"]
        diff = ["one.py", "pkg/deep/f.py", "tests/test_a.py"]
        self.assertTrue(ownership_audit.audit(diff, owned, None, head=HEAD)["ok"])
        self.assertFalse(ownership_audit.audit(["one.pyc"], owned, None, head=HEAD)["ok"])
        self.assertFalse(ownership_audit.audit(["package/x.py"], owned, None, head=HEAD)["ok"])

    def test_claimed_commit_must_be_head(self) -> None:
        result = ownership_audit.audit(["src/a.py"], ["src/"], "deadbee", head=HEAD)
        self.assertEqual(codes(result), ["claimed_not_head"])

    def test_all_violations_reported_together(self) -> None:
        result = ownership_audit.audit(["x.py"], ["src/"], "deadbee", head=HEAD)
        self.assertEqual(codes(result), ["outside_owned", "claimed_not_head"])

    def test_redispatch_once_then_blocked(self) -> None:
        bad = ownership_audit.audit([], ["src/"], None, head=HEAD)
        self.assertEqual(ownership_audit.next_action(bad, 0), "redispatch")
        self.assertEqual(ownership_audit.next_action(bad, 1), "blocked")
        good = ownership_audit.audit(["src/a.py"], ["src/"], None, head=HEAD)
        self.assertEqual(ownership_audit.next_action(good, 0), "accept")


class BuilderAuditCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="b14a-audit-"))
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@t")
        self.git("config", "user.name", "t")
        (self.repo / "seed.txt").write_text("s", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "seed")
        self.base = self.git("rev-parse", "HEAD").strip()

    def git(self, *args: str) -> str:
        return subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True, check=True).stdout

    def commit_file(self, rel: str) -> str:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", rel)
        return self.git("rev-parse", "HEAD").strip()

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", "-I", str(SCRIPTS / "builder-audit.py"), "--repo", str(self.repo), "--base", self.base, *args],
            capture_output=True, text=True,
        )

    def test_pass_exits_zero(self) -> None:
        sha = self.commit_file("src/a.py")
        proc = self.run_cli("--owned", "src/", "--claimed-sha", sha[:8], "--status", "DONE")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["ok"])

    def test_outside_file_exits_one_with_action(self) -> None:
        sha = self.commit_file("other/a.py")
        proc = self.run_cli("--owned", "src/", "--claimed-sha", sha, "--attempt", "0")
        self.assertEqual(proc.returncode, 1)
        out = json.loads(proc.stdout)
        self.assertEqual(out["action"], "redispatch")
        self.assertEqual(json.loads(self.run_cli("--owned", "src/", "--claimed-sha", sha, "--attempt", "1").stdout)["action"], "blocked")

    def test_empty_diff_with_done_exits_one(self) -> None:
        proc = self.run_cli("--owned", "src/", "--status", "DONE")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(json.loads(proc.stdout)["violations"][0]["code"], "empty_diff")

    def test_stale_claim_exits_one(self) -> None:
        self.commit_file("src/a.py")
        proc = self.run_cli("--owned", "src/", "--claimed-sha", self.base)
        self.assertEqual(proc.returncode, 1)


class PlanWiringTests(unittest.TestCase):
    def test_build_phase_runs_the_audit_after_each_builder(self) -> None:
        text = (PLUGIN_ROOT / "skills" / "run" / "phase-2-build.md").read_text(encoding="utf-8")
        self.assertIn("builder-audit.py", text)
        self.assertIn("re-dispatch once", text)


if __name__ == "__main__":
    unittest.main()
