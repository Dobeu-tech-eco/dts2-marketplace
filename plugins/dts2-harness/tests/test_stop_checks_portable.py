"""Stop hook on a machine without GNU timeout (stock macOS): checks still run, and a missing binary is never red."""
from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT, make_tmp_home

HOOK: Final[Path] = PLUGIN_ROOT / "hooks" / "stop-checks.sh"
GIT_IDENT: Final[list[str]] = ["-c", "user.email=t@example.invalid", "-c", "user.name=tester"]
MARKER: Final[str] = "PORTABLE-CHECKS-RAN"
HIDDEN: Final[frozenset[str]] = frozenset({"timeout", "gtimeout"})
FAKE_GTIMEOUT: Final[str] = '#!/usr/bin/env bash\necho used >> "$GT_LOG"\nshift\nexec "$@"\n'


def path_without_timeout(dest: Path) -> str:
    """A PATH holding links to every tool on the current PATH except timeout and gtimeout."""
    dest.mkdir()
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory or not os.path.isdir(directory):
            continue
        for name in os.listdir(directory):
            target = Path(directory) / name
            link = dest / name
            if name in HIDDEN or link.exists() or not os.access(target, os.X_OK) or target.is_dir():
                continue
            link.symlink_to(target)
    return str(dest)


class StopChecksWithoutTimeout(unittest.TestCase):
    def setUp(self) -> None:
        self.repo: Path = make_tmp_home()
        self.tmp: Path = make_tmp_home()
        self.addCleanup(shutil.rmtree, self.repo, True)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        subprocess.run(["git", *GIT_IDENT, "init", "-q"], cwd=str(self.repo), check=True, capture_output=True)
        (self.repo / ".harness").mkdir()
        (self.repo / ".harness" / "checks.sh").write_text(f"echo {MARKER}\n", encoding="utf-8")
        (self.repo / ".gitignore").write_text(".harness/handoff/\n.harness/cache/\n", encoding="utf-8")
        (self.repo / "a.txt").write_text("one\n", encoding="utf-8")
        self.path: str = path_without_timeout(self.tmp / "bin")

    def run_hook(self, extra_path: str = "") -> subprocess.CompletedProcess[str]:
        env: dict[str, str] = {k: v for k, v in os.environ.items() if not k.startswith("DTS2_SON")}
        env["PATH"] = f"{extra_path}{os.pathsep}{self.path}" if extra_path else self.path
        env["TMPDIR"] = str(self.tmp)
        env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
        env["GT_LOG"] = str(self.tmp / "gt.log")
        return subprocess.run(["bash", str(HOOK)], cwd=str(self.repo), env=env, input="",
                              capture_output=True, text=True, check=False)

    def fingerprint(self) -> str:
        return (self.repo / ".harness" / "cache" / "stop-fingerprint").read_text(encoding="utf-8")

    def test_checks_run_and_pass_without_any_timeout_binary(self) -> None:
        result = self.run_hook()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(MARKER, result.stderr)
        self.assertNotIn("partial", self.fingerprint())
        self.assertEqual(result.stdout.strip(), "")

    def test_gtimeout_is_used_when_present(self) -> None:
        extra: Path = self.tmp / "gt"
        extra.mkdir()
        (extra / "gtimeout").write_text(FAKE_GTIMEOUT, encoding="utf-8")
        (extra / "gtimeout").chmod(0o755)
        result = self.run_hook(str(extra))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(MARKER, result.stderr)
        self.assertTrue((self.tmp / "gt.log").exists(), "gtimeout was not used")
        self.assertNotIn("partial", self.fingerprint())


if __name__ == "__main__":
    unittest.main()
