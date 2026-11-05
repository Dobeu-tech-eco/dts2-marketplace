"""Stop hook skips unchanged diffs and runs the local tsc incrementally under .harness/cache."""
from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT, make_tmp_home

HOOK: Final[Path] = PLUGIN_ROOT / "hooks" / "stop-checks.sh"
GIT_IDENT: Final[list[str]] = ["-c", "user.email=t@example.invalid", "-c", "user.name=tester"]
CHECKS_MARKER: Final[str] = "CHECKS-RAN"
FAKE_NPX: Final[str] = '#!/usr/bin/env bash\necho "$*" >> "$NPX_LOG"\nexit 0\n'


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *GIT_IDENT, *args], cwd=str(repo), check=True, capture_output=True)


class Env:
    def __init__(self) -> None:
        self.repo: Path = make_tmp_home()
        self.tmp: Path = make_tmp_home()
        self.bin: Path = self.tmp / "bin"
        self.bin.mkdir()
        self.npx_log: Path = self.tmp / "npx.log"
        npx: Path = self.bin / "npx"
        npx.write_text(FAKE_NPX, encoding="utf-8")
        npx.chmod(0o755)

    def run(self) -> subprocess.CompletedProcess[str]:
        env: dict[str, str] = dict(os.environ)
        env["PATH"] = f"{self.bin}{os.pathsep}{env['PATH']}"
        env["TMPDIR"] = str(self.tmp)
        env["NPX_LOG"] = str(self.npx_log)
        return subprocess.run(["bash", str(HOOK)], cwd=str(self.repo), env=env, capture_output=True, text=True, check=False)

    def npx_calls(self) -> list[str]:
        if not self.npx_log.exists():
            return []
        return self.npx_log.read_text(encoding="utf-8").splitlines()


def make_env(with_ts: bool = False) -> Env:
    env = Env()
    repo: Path = env.repo
    git(repo, "init", "-q")
    (repo / ".harness").mkdir()
    (repo / ".harness" / "checks.sh").write_text(f"echo {CHECKS_MARKER}\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".harness/handoff/\n.harness/cache/\n", encoding="utf-8")
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    if with_ts:
        (repo / "package.json").write_text("{}\n", encoding="utf-8")
        (repo / "tsconfig.json").write_text("{}\n", encoding="utf-8")
        local_bin: Path = repo / "node_modules" / ".bin"  # G-32: the hook runs the local tsc, never npx
        local_bin.mkdir(parents=True)
        (local_bin / "tsc").write_text(FAKE_NPX.replace('"$*"', '"tsc $*"'), encoding="utf-8")
        (local_bin / "tsc").chmod(0o755)
    git(repo, "add", "-A", "-f")
    git(repo, "commit", "-q", "-m", "base")
    return env


class StopChecksIncrementalTests(unittest.TestCase):
    def test_clean_tree_skips_everything(self) -> None:
        env = make_env(with_ts=True)
        result = env.run()
        self.assertEqual(result.returncode, 0)
        self.assertNotIn(CHECKS_MARKER, result.stderr)
        self.assertEqual(env.npx_calls(), [])

    def test_same_diff_skips_and_new_edit_runs_again(self) -> None:
        env = make_env()
        (env.repo / "a.txt").write_text("two\n", encoding="utf-8")
        self.assertIn(CHECKS_MARKER, env.run().stderr)
        self.assertNotIn(CHECKS_MARKER, env.run().stderr)
        (env.repo / "a.txt").write_text("two\nthree\n", encoding="utf-8")
        self.assertIn(CHECKS_MARKER, env.run().stderr)

    def test_same_line_count_edits_each_run(self) -> None:
        env = make_env()
        (env.repo / "a.txt").write_text("x = 1\n", encoding="utf-8")
        self.assertIn(CHECKS_MARKER, env.run().stderr)
        (env.repo / "a.txt").write_text("x = 2\n", encoding="utf-8")
        self.assertIn(CHECKS_MARKER, env.run().stderr)
        (env.repo / "a.txt").write_text("x = 'oops'\n", encoding="utf-8")
        self.assertIn(CHECKS_MARKER, env.run().stderr)
        self.assertNotIn(CHECKS_MARKER, env.run().stderr)

    def test_untracked_file_edit_reruns(self) -> None:
        env = make_env()
        (env.repo / "new.txt").write_text("aaa\n", encoding="utf-8")
        self.assertIn(CHECKS_MARKER, env.run().stderr)
        self.assertNotIn(CHECKS_MARKER, env.run().stderr)
        (env.repo / "new.txt").write_text("bbb\n", encoding="utf-8")
        self.assertIn(CHECKS_MARKER, env.run().stderr)

    def test_handoff_rewrite_alone_still_skips(self) -> None:
        env = make_env()
        (env.repo / "a.txt").write_text("two\n", encoding="utf-8")
        self.assertIn(CHECKS_MARKER, env.run().stderr)
        latest: Path = env.repo / ".harness" / "handoff" / "latest.md"
        latest.parent.mkdir(parents=True, exist_ok=True)
        latest.write_text("rewritten handoff\n", encoding="utf-8")
        self.assertNotIn(CHECKS_MARKER, env.run().stderr)

    def test_tsc_runs_incrementally_under_harness_cache(self) -> None:
        env = make_env(with_ts=True)
        (env.repo / "a.txt").write_text("two\n", encoding="utf-8")
        env.run()
        calls: list[str] = env.npx_calls()
        self.assertEqual(len(calls), 1)
        self.assertIn("tsc --noEmit --incremental --tsBuildInfoFile", calls[0])
        self.assertIn(".harness/cache/tsbuildinfo", calls[0])

    def test_cache_files_do_not_change_fingerprint(self) -> None:
        env = make_env()
        (env.repo / "a.txt").write_text("two\n", encoding="utf-8")
        env.run()
        self.assertTrue((env.repo / ".harness" / "cache" / "stop-fingerprint").exists())
        (env.repo / ".harness" / "cache" / "extra").write_text("x\n", encoding="utf-8")
        self.assertNotIn(CHECKS_MARKER, env.run().stderr)

    def test_handoff_refreshes_when_checks_are_skipped(self) -> None:
        env = make_env()
        latest: Path = env.repo / ".harness" / "handoff" / "latest.md"
        self.assertFalse(latest.exists())
        env.run()
        self.assertTrue(latest.exists())
        latest.unlink()
        result = env.run()
        self.assertNotIn(CHECKS_MARKER, result.stderr)
        self.assertTrue(latest.exists())


if __name__ == "__main__":
    unittest.main()
