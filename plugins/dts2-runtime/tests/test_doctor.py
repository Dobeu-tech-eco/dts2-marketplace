"""doctor.py: preflight table and JSON, driven with fake binaries (never the real claude or git)."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "doctor.py"
CLEARED: Final[tuple[str, ...]] = ("DTS2_CLAUDE_BIN", "DTS2_GH_BIN", "DTS2_NPX_BIN", "DTS2_GIT_BIN",
                                   "DTS2_GITLEAKS_BIN", "DTS2_TRUFFLEHOG_BIN", "DTS2_SANDBOX_BIN")


class DoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="dts2-doctor-"))
        self.empty_path = self.dir / "empty-bin"
        self.empty_path.mkdir()

    def fake(self, name: str, output: str, code: int = 0) -> str:
        path = self.dir / f"{name}.py"
        path.write_text(f"import sys\nprint({output!r})\nsys.exit({code})\n", encoding="utf-8")
        return str(path)

    def run_doctor(self, extra_env: dict[str, str], *args: str) -> tuple[int, str]:
        env = {k: v for k, v in os.environ.items() if k not in CLEARED}
        env["PATH"] = str(self.empty_path)
        env.update(extra_env)
        done = subprocess.run([sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True,
                              env=env, check=False)
        return done.returncode, done.stdout

    def report(self, extra_env: dict[str, str]) -> tuple[int, dict[str, Any]]:
        code, out = self.run_doctor(extra_env, "--json")
        return code, json.loads(out)

    @staticmethod
    def status(report: dict[str, Any], name: str) -> str:
        return next(c["status"] for c in report["checks"] if c["name"] == name)

    def healthy_env(self) -> dict[str, str]:
        return {"DTS2_GIT_BIN": self.fake("git", "git version 2.43.0"),
                "DTS2_CLAUDE_BIN": self.fake("claude", "2.1.100 (Claude Code)")}

    def test_all_pass_with_fake_binaries(self) -> None:
        code, report = self.report(self.healthy_env())
        self.assertEqual(code, 0)
        self.assertTrue(report["ok"])
        self.assertEqual([self.status(report, n) for n in ("python", "git", "claude")], ["pass"] * 3)

    def test_old_git_fails(self) -> None:
        env = {**self.healthy_env(), "DTS2_GIT_BIN": self.fake("oldgit", "git version 2.37.9")}
        code, report = self.report(env)
        self.assertEqual(code, 1)
        self.assertFalse(report["ok"])
        self.assertEqual(self.status(report, "git"), "fail")

    def test_boundary_git_version_passes(self) -> None:
        env = {**self.healthy_env(), "DTS2_GIT_BIN": self.fake("git238", "git version 2.38.0")}
        self.assertEqual(self.status(self.report(env)[1], "git"), "pass")

    def test_missing_claude_fails(self) -> None:
        env = {"DTS2_GIT_BIN": self.fake("git", "git version 2.43.0")}
        code, report = self.report(env)
        self.assertEqual(code, 1)
        self.assertEqual(self.status(report, "claude"), "fail")

    def test_claude_version_failure_fails(self) -> None:
        env = {**self.healthy_env(), "DTS2_CLAUDE_BIN": self.fake("badclaude", "boom", code=3)}
        self.assertEqual(self.status(self.report(env)[1], "claude"), "fail")

    def test_sandbox_tool_on_path_passes_and_absent_warns(self) -> None:
        env = self.healthy_env()
        self.assertEqual(self.status(self.report(env)[1], "sandbox"), "warn")
        tool = self.empty_path / "tool-x"
        tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        tool.chmod(tool.stat().st_mode | stat.S_IEXEC)
        env["DTS2_SANDBOX_BIN"] = "tool-x"
        self.assertEqual(self.status(self.report(env)[1], "sandbox"), "pass")

    def test_fake_binary_vars_are_reported_as_warning(self) -> None:
        report = self.report(self.healthy_env())[1]
        row = next(c for c in report["checks"] if c["name"] == "fake-binaries")
        self.assertEqual(row["status"], "warn")
        self.assertIn("DTS2_GIT_BIN", row["detail"])
        self.assertIn("DTS2_CLAUDE_BIN", row["detail"])
        self.assertTrue(report["ok"])

    def test_table_output_lists_every_check(self) -> None:
        code, out = self.run_doctor(self.healthy_env())
        self.assertEqual(code, 0)
        for name in ("python", "git", "claude", "sandbox", "fake-binaries"):
            self.assertIn(name, out)
        self.assertIn("PASS", out)

    def test_makefile_has_doctor_target(self) -> None:
        make = (PLUGIN_ROOT.parent.parent / "Makefile").read_text(encoding="utf-8")
        self.assertIn("doctor:", make)
        self.assertIn("scripts/doctor.py", make)


if __name__ == "__main__":
    unittest.main()
