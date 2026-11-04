"""harness-lock.py: head-only locks on shared .harness records, stale reclaim, son role refusal."""
from __future__ import annotations

import json
import subprocess
import time
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, make_tmp_home

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "harness-lock.py"
STATE: Final[str] = ".harness/state.md"
TWO_HOURS: Final[int] = 7200
SHORT_TTL: Final[str] = "60"


def run(lock_dir: Path, *args: str) -> tuple[int, dict[str, Any]]:
    result = subprocess.run(["python3", "-I", str(SCRIPT), *args, "--lock-dir", str(lock_dir)],
                            capture_output=True, text=True, check=False)
    return result.returncode, json.loads(result.stdout)


class HarnessLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lock_dir: Path = make_tmp_home() / "locks"

    def test_acquire_then_second_acquire_fails(self) -> None:
        code, first = run(self.lock_dir, "acquire", "--file", STATE, "--holder", "head-a")
        self.assertEqual((code, first["ok"]), (0, True))
        code, second = run(self.lock_dir, "acquire", "--file", STATE, "--holder", "head-b")
        self.assertEqual((code, second["ok"], second["holder"]), (1, False, "head-a"))

    def test_release_frees_lock(self) -> None:
        run(self.lock_dir, "acquire", "--file", STATE, "--holder", "head-a")
        _, released = run(self.lock_dir, "release", "--file", STATE, "--holder", "head-a")
        self.assertTrue(released["ok"])
        _, again = run(self.lock_dir, "acquire", "--file", STATE, "--holder", "head-b")
        self.assertTrue(again["ok"])

    def test_release_by_other_holder_refused(self) -> None:
        run(self.lock_dir, "acquire", "--file", STATE, "--holder", "head-a")
        code, data = run(self.lock_dir, "release", "--file", STATE, "--holder", "head-b")
        self.assertEqual((code, data["ok"]), (1, False))

    def test_stale_lock_is_reclaimed_after_ttl(self) -> None:
        run(self.lock_dir, "acquire", "--file", STATE, "--holder", "dead-head")
        lock_file: Path = next(self.lock_dir.iterdir())
        stale: dict[str, Any] = json.loads(lock_file.read_text())
        stale["created"] = time.time() - TWO_HOURS
        lock_file.write_text(json.dumps(stale))
        _, data = run(self.lock_dir, "acquire", "--file", STATE, "--holder", "new-head", "--ttl-sec", SHORT_TTL)
        self.assertEqual((data["ok"], data["holder"], data["reason"]), (True, "new-head", "reclaimed stale lock"))

    def test_son_role_rejected_on_shared_file(self) -> None:
        code, data = run(self.lock_dir, "check", "--file", STATE, "--holder", "son-a", "--role", "son")
        self.assertEqual((code, data["ok"]), (1, False))
        self.assertIn("son may not write shared records", data["reason"])
        _, lessons = run(self.lock_dir, "acquire", "--file", ".harness/lessons.md", "--holder", "son-a", "--role", "son")
        self.assertFalse(lessons["ok"])

    def test_son_role_allowed_in_own_run_dir(self) -> None:
        code, data = run(self.lock_dir, "check", "--file", ".harness/runs/s/a/report.md", "--holder", "son-a",
                         "--role", "son")
        self.assertEqual((code, data["ok"]), (0, True))

    def test_head_role_allowed_on_shared_file(self) -> None:
        code, data = run(self.lock_dir, "check", "--file", STATE, "--holder", "head", "--role", "head")
        self.assertEqual((code, data["ok"]), (0, True))


if __name__ == "__main__":
    unittest.main()
