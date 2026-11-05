"""Q-7: PreCompact writes the handoff only; SessionStart after a compact prints a short pointer, not the lessons digest."""
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT, make_tmp_home

HOOKS: Final[Path] = PLUGIN_ROOT / "hooks"
MAX_POINTER_CHARS: Final[int] = 1200  # 300 tokens at about 4 characters each
STAMP: Final[str] = "20261104-0900"


def make_repo() -> Path:
    repo: Path = make_tmp_home()
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    (repo / ".harness").mkdir()
    return repo


def run_hook(name: str, repo: Path, stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(HOOKS / name)], cwd=str(repo), input=stdin, capture_output=True, text=True, check=False)


class PreCompactTests(unittest.TestCase):
    def test_hooks_json_registers_precompact_for_auto_and_manual(self) -> None:
        groups = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))["hooks"]["PreCompact"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["matcher"], "auto|manual")
        commands = [hook["command"] for hook in groups[0]["hooks"]]
        self.assertEqual(len(commands), 1)
        self.assertIn("hooks/pre-compact.sh", commands[0])

    def test_pre_compact_runs_only_the_handoff_script(self) -> None:
        body: str = (HOOKS / "pre-compact.sh").read_text(encoding="utf-8")
        self.assertIn("scripts/handoff-write.py", body)
        self.assertNotIn("lessons", body)
        self.assertNotIn("typecheck", body)

    def test_pre_compact_writes_the_handoff_and_exits_zero(self) -> None:
        repo: Path = make_repo()
        result = run_hook("pre-compact.sh", repo, '{"trigger":"auto"}')
        self.assertEqual(result.returncode, 0)
        self.assertTrue((repo / ".harness" / "handoff" / "latest.md").is_file())

    def test_pre_compact_never_fails_without_a_harness(self) -> None:
        repo: Path = make_tmp_home()
        self.assertEqual(run_hook("pre-compact.sh", repo).returncode, 0)


class CompactPointerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo: Path = make_repo()
        lease: Path = self.repo / ".harness" / "runs" / STAMP / "lane-a" / "lease.json"
        lease.parent.mkdir(parents=True)
        lease.write_text(json.dumps({"stamp": STAMP, "lane": "lane-a", "status": "active", "epoch": 3}), encoding="utf-8")
        (self.repo / ".harness" / "runs" / STAMP / "3-review.md").write_text("review\n", encoding="utf-8")
        lessons = "".join(f"- [L-{i:03d}] Validate input number {i}. (seen 1x, last 2026-10-01, source: run x)\n" for i in range(1, 8))
        (self.repo / ".harness" / "lessons.md").write_text(lessons, encoding="utf-8")

    def test_compact_prints_pointer_with_stamp_epoch_lane_phase(self) -> None:
        out: str = run_hook("session-lessons.sh", self.repo, '{"source":"compact"}').stdout
        for needle in (STAMP, "epoch 3", "lane-a", "review", "read .harness/handoff.md"):
            self.assertIn(needle, out)

    def test_compact_pointer_is_short_with_three_rules_and_no_digest(self) -> None:
        out: str = run_hook("session-lessons.sh", self.repo, '{"source":"compact"}').stdout
        self.assertLessEqual(len(out), MAX_POINTER_CHARS)
        self.assertEqual(sum(1 for line in out.splitlines() if line.startswith("rule ")), 3)
        self.assertNotIn("Validate input", out)
        self.assertNotIn("lessons for this repo", out)

    def test_other_sources_still_print_the_digest(self) -> None:
        for payload in ('{"source":"startup"}', '{"source":"resume"}', ""):
            out: str = run_hook("session-lessons.sh", self.repo, payload).stdout
            self.assertIn("Validate input", out, payload)
            self.assertNotIn("read .harness/handoff.md", out, payload)

    def test_compact_without_a_run_still_prints_a_pointer(self) -> None:
        repo: Path = make_repo()
        out: str = run_hook("session-lessons.sh", repo, '{"source":"compact"}').stdout
        self.assertIn("read .harness/handoff.md", out)
        self.assertIn("stamp none", out)


if __name__ == "__main__":
    unittest.main()
