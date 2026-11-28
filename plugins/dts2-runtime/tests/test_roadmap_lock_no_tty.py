"""lock-roadmap never blocks when no agent is detected and no interactive terminal exists (Codex, Gemini, WSL, Windows)."""
from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from typing import Final
from unittest import mock

from helpers import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import approvals  # noqa: E402
import roadmap  # noqa: E402
from test_roadmap_lock import make_repo  # noqa: E402

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "approvals.py"
STRIPPED: Final[tuple[str, ...]] = ("CLAUDECODE", "GEMINI_CLI", "DTS2_SON", "CODEX_HOME", "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED")
FAST_SECONDS: Final[float] = 10.0


def clean_env(**extra: str) -> dict[str, str]:
    env: dict[str, str] = {k: v for k, v in os.environ.items() if k not in STRIPPED}
    env.update(extra)
    return env


REAL_READ_TEXT = Path.read_text


def proc_unavailable(self: Path, *args: object, **kwargs: object) -> str:
    """Path.read_text with /proc missing, as on Windows."""
    if self.as_posix().startswith("/proc"):
        raise OSError("no /proc")
    return REAL_READ_TEXT(self, *args, **kwargs)  # type: ignore[arg-type]


class NoTtyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo: Path = make_repo()
        self.key: str = roadmap.status(self.repo)["key"]

    def sign(self, *providers: str) -> None:
        for provider in providers:
            self.assertEqual(approvals.sign_roadmap(self.repo, self.key, provider)[0], 0)

    def run_cli(self, env: dict[str, str], *args: str) -> tuple[subprocess.CompletedProcess[str], float]:
        started: float = time.monotonic()
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(self.repo), "lock-roadmap", *args],
            capture_output=True, text=True, env=env, check=False, stdin=subprocess.DEVNULL, timeout=20,
            start_new_session=os.name != "nt",
        )
        return result, time.monotonic() - started

    def test_codex_like_env_locks_from_signoffs(self) -> None:
        self.sign("codex", "gemini")
        result, _ = self.run_cli(clean_env(CODEX_HOME="/nonexistent"), self.key)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(roadmap.status(self.repo)["approved"])

    def test_gemini_env_and_no_markers_lock(self) -> None:
        for env in (clean_env(GEMINI_CLI="1"), clean_env()):
            self.repo = make_repo()
            self.key = roadmap.status(self.repo)["key"]
            self.sign("codex", "gemini")
            result, _ = self.run_cli(env, self.key)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(roadmap.status(self.repo)["approved"])

    def test_missing_signoffs_exit_3_fast(self) -> None:
        self.sign("codex")
        result, elapsed = self.run_cli(clean_env(CODEX_HOME="/nonexistent"), self.key)
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertLess(elapsed, FAST_SECONDS)
        self.assertIn("nothing locked", result.stdout)
        self.assertFalse(roadmap.status(self.repo)["approved"])

    def test_no_key_exit_2_fast(self) -> None:
        result, elapsed = self.run_cli(clean_env())
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertLess(elapsed, FAST_SECONDS)
        self.assertIn(self.key, result.stdout)
        self.assertFalse(roadmap.status(self.repo)["approved"])

    def test_claude_path_unchanged(self) -> None:
        result, _ = self.run_cli(clean_env(CLAUDECODE="1"), self.key)
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.sign("claude", "codex")
        result, _ = self.run_cli(clean_env(CLAUDECODE="1"), self.key)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(roadmap.status(self.repo)["approved"])

    def test_simulated_windows(self) -> None:
        self.sign("codex")
        with mock.patch.dict(os.environ, clean_env(), clear=True), \
                mock.patch.object(approvals.os, "getppid", return_value=4242), \
                mock.patch.object(approvals.Path, "read_text", proc_unavailable), \
                mock.patch.object(approvals, "open_terminal", return_value=None):
            self.assertIsNone(approvals.agent_ancestor())
            code, message = approvals.lock_roadmap(self.repo, self.key)
        self.assertEqual(code, 3, message)
        self.assertIn("1 more", message)
        self.sign("gemini")
        with mock.patch.dict(os.environ, clean_env(), clear=True), \
                mock.patch.object(approvals.os, "getppid", return_value=4242), \
                mock.patch.object(approvals, "open_terminal", return_value=None):
            code, message = approvals.lock_roadmap(self.repo, self.key)
        self.assertEqual(code, 0, message)
        self.assertIn("codex, gemini", message)
        self.assertTrue(roadmap.status(self.repo)["approved"])

    def test_timeout_value_falls_back_on_bad_input(self) -> None:
        for raw, expected in (("5", 5), ("abc", approvals.LOCK_TTY_TIMEOUT_DEFAULT), ("0", approvals.LOCK_TTY_TIMEOUT_DEFAULT)):
            with mock.patch.dict(os.environ, {approvals.LOCK_TTY_TIMEOUT_ENV: raw}):
                self.assertEqual(approvals.lock_tty_timeout(), expected)

    @unittest.skipIf(os.name == "nt", "POSIX select")
    def test_read_line_with_timeout_on_a_pipe(self) -> None:
        read_fd, write_fd = os.pipe()
        try:
            with os.fdopen(read_fd, "r", closefd=False) as stream:
                started: float = time.monotonic()
                self.assertIsNone(approvals.read_line_with_timeout(stream, 0.5))
                self.assertLess(time.monotonic() - started, FAST_SECONDS)
                os.write(write_fd, b"yes\n")
                self.assertEqual(approvals.read_line_with_timeout(stream, 5), "yes\n")
        finally:
            os.close(read_fd)
            os.close(write_fd)


if __name__ == "__main__":
    unittest.main()
