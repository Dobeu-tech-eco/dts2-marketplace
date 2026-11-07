"""Follow-ups: lessons_max honoured, compact pointer, learn prune gate, lane wall clock, disjoint lanes, lead brief env rows."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT, make_tmp_home

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import briefs  # noqa: E402
import run_metrics  # noqa: E402
import run_report  # noqa: E402

HOOK: Final[Path] = PLUGIN_ROOT / "hooks" / "session-lessons.sh"
TAIL: Final[str] = "(seen 1x, last 2026-10-01, source: run x)"


def hook(repo: Path, stdin: str = "") -> str:
    return subprocess.run(["bash", str(HOOK)], cwd=str(repo), input=stdin, capture_output=True, text=True, check=False).stdout


def lessons_repo(count: int, settings: str = "") -> Path:
    repo: Path = make_tmp_home()
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    (repo / ".harness").mkdir()
    body: str = "".join(f"- [L-{n:03d}] Lesson number {n}. {TAIL}\n" for n in range(1, count + 1))
    (repo / ".harness" / "lessons.md").write_text("# Lessons\n\n" + body, encoding="utf-8")
    (repo / ".harness" / "config.yaml").write_text("x: 1\n", encoding="utf-8")
    if settings:
        (repo / ".claude").mkdir()
        (repo / ".claude" / "dts2-harness.local.md").write_text(settings, encoding="utf-8")
    return repo


class SessionLessons(unittest.TestCase):
    def test_default_prints_newest_five(self) -> None:
        out: str = hook(lessons_repo(8))
        self.assertIn("Lesson number 8.", out)
        self.assertIn("Lesson number 4.", out)
        self.assertNotIn("Lesson number 3.", out)

    def test_lessons_max_setting_is_honoured(self) -> None:
        out: str = hook(lessons_repo(8, "---\nlessons_max: 2\n---\n"))
        self.assertIn("Lesson number 8.", out)
        self.assertIn("Lesson number 7.", out)
        self.assertNotIn("Lesson number 6.", out)

    def test_compact_pointer_skips_unstamped_dirs_and_names_latest_handoff(self) -> None:
        repo: Path = lessons_repo(1)
        runs: Path = repo / ".harness" / "runs"
        (runs / "20261101-120000").mkdir(parents=True)
        (runs / "scratch").mkdir()
        out: str = hook(repo, '{"source":"compact"}')
        self.assertIn("stamp 20261101-120000", out)
        self.assertIn("read .harness/handoff/latest.md", out)
        self.assertNotIn("read .harness/handoff.md", out)


class LearnSkill(unittest.TestCase):
    def test_prune_runs_only_after_approval(self) -> None:
        text: str = (PLUGIN_ROOT / "skills" / "learn" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Do not prune yet", text)
        self.assertLess(text.index("wait for approval"), text.index("lessons.py\" <repo> prune"))


class RunReportWallClock(unittest.TestCase):
    def test_missing_lane_start_shows_dash(self) -> None:
        self.assertEqual(run_report.wall_clock({"heartbeat": 1754}), "-")

    def test_lane_start_gives_minutes(self) -> None:
        self.assertEqual(run_report.wall_clock({"started": 1000, "heartbeat": 1754}), "12m34s")


class DisjointLanes(unittest.TestCase):
    def test_order_independent(self) -> None:
        lanes = [{"files": ["a.py", "b.py"]}, {"files": ["b.py"]}, {"files": ["c.py"]}]
        self.assertEqual(run_metrics.disjoint_lane_count(lanes), 1)
        self.assertEqual(run_metrics.disjoint_lane_count(list(reversed(lanes))), 1)

    def test_all_disjoint(self) -> None:
        self.assertEqual(run_metrics.disjoint_lane_count([{"files": ["a"]}, {"files": ["./b"]}]), 2)


class LeadBriefChecks(unittest.TestCase):
    def test_env_rows_reach_the_brief_with_and_without_checks(self) -> None:
        env = {"kind": "env", "missing": ["TOKEN"]}
        check = {"kind": "check", "name": "t", "status": "pass"}
        self.assertIn("Missing env vars (names only): TOKEN", "\n".join(briefs.check_lines([env])))
        self.assertIn("Missing env vars (names only): TOKEN", "\n".join(briefs.check_lines([check, env])))


if __name__ == "__main__":
    unittest.main()
