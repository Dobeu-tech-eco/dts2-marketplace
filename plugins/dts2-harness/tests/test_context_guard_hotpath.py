"""Context guard hot path: byte-offset transcript counting, session scope cache, single python process."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, make_tmp_home

GUARD_HOOK: Final[Path] = PLUGIN_ROOT / "hooks" / "context-guard.sh"
MANIFEST: Final[str] = ".harness-workspace.yaml"
SETTINGS_REL: Final[str] = ".claude/dts2-harness.local.md"
TOOL_LINE: Final[str] = '{"type":"assistant","message":{"content":[{"type": "tool_use","name":"Bash"}]}}\n'
THRESHOLD: Final[int] = 3
SESSION: Final[str] = "hot1"
EXEC_BIT: Final[int] = 0o755


def write_settings(cwd: Path, body: str) -> None:
    (cwd / ".claude").mkdir(exist_ok=True)
    (cwd / SETTINGS_REL).write_text(f"---\n{body}\n---\n", encoding="utf-8")


def run_guard(cwd: Path, transcript: Path, session: str, tmp: Path,
              extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    payload: str = json.dumps({"transcript_path": str(transcript), "session_id": session, "cwd": str(cwd)})
    env: dict[str, str] = {**os.environ, "TMPDIR": str(tmp), **(extra_env or {})}
    return subprocess.run(["bash", str(GUARD_HOOK)], input=payload, cwd=str(cwd), env=env,
                          capture_output=True, text=True, check=False)


class HotPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp: Path = Path(tempfile.mkdtemp())
        self.cwd: Path = make_tmp_home().resolve()
        write_settings(self.cwd, f"context_guard_tool_calls: {THRESHOLD}")
        self.transcript: Path = self.cwd / "transcript.jsonl"

    def offset_state(self, session: str = SESSION) -> dict[str, Any]:
        return json.loads((self.tmp / f"dts2-guard-{session}-offset.json").read_text(encoding="utf-8"))

    def test_offset_records_size(self) -> None:
        self.transcript.write_text(TOOL_LINE * 2, encoding="utf-8")
        run_guard(self.cwd, self.transcript, SESSION, self.tmp)
        state: dict[str, Any] = self.offset_state()
        self.assertEqual(state["offset"], self.transcript.stat().st_size)
        self.assertEqual((state["calls"], state["path"]), (2, str(self.transcript)))

    def test_reads_only_new_bytes(self) -> None:
        filler: str = "x" * (len(TOOL_LINE) - 1) + "\n"
        self.transcript.write_text(TOOL_LINE + filler * 3, encoding="utf-8")
        self.assertEqual(run_guard(self.cwd, self.transcript, SESSION, self.tmp).stdout, "")
        self.transcript.write_text(TOOL_LINE * 4, encoding="utf-8")  # same length, prefix already counted
        self.assertEqual(run_guard(self.cwd, self.transcript, SESSION, self.tmp).stdout, "")
        self.assertEqual(self.offset_state()["calls"], 1)
        with open(self.transcript, "a", encoding="utf-8") as handle:
            handle.write(TOOL_LINE * 2)
        out: str = run_guard(self.cwd, self.transcript, SESSION, self.tmp).stdout
        self.assertIn("CONTEXT GUARD (spike)", out)
        self.assertIn("3 tool calls", out)

    def test_truncation_resets_counting(self) -> None:
        self.transcript.write_text(TOOL_LINE * 2, encoding="utf-8")
        run_guard(self.cwd, self.transcript, SESSION, self.tmp)
        self.transcript.write_text(TOOL_LINE, encoding="utf-8")
        run_guard(self.cwd, self.transcript, SESSION, self.tmp)
        state: dict[str, Any] = self.offset_state()
        self.assertEqual((state["calls"], state["offset"]), (1, len(TOOL_LINE)))

    def test_partial_trailing_line_waits_for_newline(self) -> None:
        self.transcript.write_text(TOOL_LINE + TOOL_LINE.rstrip("\n"), encoding="utf-8")
        run_guard(self.cwd, self.transcript, SESSION, self.tmp)
        state: dict[str, Any] = self.offset_state()
        self.assertEqual((state["calls"], state["offset"]), (1, len(TOOL_LINE)))
        with open(self.transcript, "a", encoding="utf-8") as handle:
            handle.write("\n")
        run_guard(self.cwd, self.transcript, SESSION, self.tmp)
        self.assertEqual(self.offset_state()["calls"], 2)

    def test_scope_cache_reused_within_session(self) -> None:
        member: Path = self.cwd / "api"
        member.mkdir()
        self.transcript.write_text(TOOL_LINE, encoding="utf-8")
        self.assertEqual(run_guard(member, self.transcript, "keep", self.tmp).stdout, "")
        (self.cwd / MANIFEST).write_text("repos: []\n", encoding="utf-8")
        self.assertEqual(run_guard(member, self.transcript, "keep", self.tmp).stdout, "")
        fresh: str = run_guard(member, self.transcript, "other", self.tmp).stdout
        self.assertIn("CONTEXT GUARD (misplaced)", fresh)

    def test_scope_cache_recomputed_when_cwd_changes(self) -> None:
        (self.cwd / MANIFEST).write_text("repos: []\n", encoding="utf-8")
        member: Path = self.cwd / "api"
        member.mkdir()
        self.transcript.write_text(TOOL_LINE, encoding="utf-8")
        self.assertEqual(run_guard(self.cwd, self.transcript, "move", self.tmp).stdout, "")
        self.assertIn("(misplaced)", run_guard(member, self.transcript, "move", self.tmp).stdout)

    def test_one_python_process(self) -> None:
        bin_dir: Path = Path(tempfile.mkdtemp())
        counter: Path = bin_dir / "count.txt"
        wrapper: Path = bin_dir / "python3"
        wrapper.write_text(f'#!/bin/sh\necho run >> "{counter}"\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
        wrapper.chmod(EXEC_BIT)
        self.transcript.write_text(TOOL_LINE * THRESHOLD, encoding="utf-8")
        result = run_guard(self.cwd, self.transcript, "one", self.tmp,
                           {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"})
        self.assertIn("CONTEXT GUARD (spike)", result.stdout)
        self.assertEqual(len(counter.read_text(encoding="utf-8").splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
