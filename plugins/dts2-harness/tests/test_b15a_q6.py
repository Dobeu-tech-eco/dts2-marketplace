"""Q-6: promoted_at, the regressed metric, and dropping stale lessons (scripts/lessons.py)."""
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, make_tmp_home

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "lessons.py"
HOOK: Final[Path] = PLUGIN_ROOT / "hooks" / "session-lessons.sh"
TODAY: Final[str] = "2026-11-05"


def make_repo(lines: list[str]) -> Path:
    repo: Path = make_tmp_home()
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    (repo / ".harness").mkdir()
    (repo / ".harness" / "lessons.md").write_text("# Lessons\n\n" + "".join(f"{line}\n" for line in lines), encoding="utf-8")
    return repo


def lessons_text(repo: Path) -> str:
    return (repo / ".harness" / "lessons.md").read_text(encoding="utf-8")


def run(repo: Path, *args: str) -> dict[str, Any]:
    out = subprocess.run(["python3", "-I", str(SCRIPT), str(repo), *args], capture_output=True, text=True, check=False)
    parsed: dict[str, Any] = json.loads(out.stdout)
    return parsed


class PromoteTests(unittest.TestCase):
    def test_promote_records_promoted_at_and_lives_at(self) -> None:
        repo = make_repo(["- [L-001] Validate input. (seen 2x, last 2026-10-17, source: run a)"])
        result = run(repo, "promote", "L-001", "--lives-at", ".harness/checks.sh", "--today", TODAY)
        self.assertTrue(result["ok"])
        self.assertIn("promoted_at: 2026-11-05", lessons_text(repo))
        self.assertIn("lives at .harness/checks.sh", lessons_text(repo))

    def test_promote_unknown_id_changes_nothing(self) -> None:
        repo = make_repo(["- [L-001] Validate input. (seen 2x, last 2026-10-17, source: run a)"])
        before = lessons_text(repo)
        self.assertFalse(run(repo, "promote", "L-009", "--today", TODAY)["ok"])
        self.assertEqual(lessons_text(repo), before)

    def test_promote_twice_keeps_one_promoted_at(self) -> None:
        repo = make_repo(["- [L-001] Validate input. (seen 2x, last 2026-10-17, source: run a)"])
        run(repo, "promote", "L-001", "--today", "2026-11-01")
        run(repo, "promote", "L-001", "--today", TODAY)
        self.assertEqual(lessons_text(repo).count("promoted_at:"), 1)


class RegressTests(unittest.TestCase):
    def test_regress_counts_up_on_a_promoted_lesson(self) -> None:
        repo = make_repo(["- [L-001] Validate input. (seen 2x, last 2026-10-17, source: run a, promoted_at: 2026-10-20)"])
        self.assertEqual(run(repo, "regress", "L-001", "--today", TODAY)["regressed"], 1)
        self.assertEqual(run(repo, "regress", "L-001", "--today", TODAY)["regressed"], 2)
        self.assertIn("regressed: 2", lessons_text(repo))

    def test_regress_refuses_an_unpromoted_lesson(self) -> None:
        repo = make_repo(["- [L-001] Validate input. (seen 2x, last 2026-10-17, source: run a)"])
        self.assertFalse(run(repo, "regress", "L-001", "--today", TODAY)["ok"])
        self.assertNotIn("regressed", lessons_text(repo))

    def test_stats_reports_promoted_and_regressed(self) -> None:
        repo = make_repo([
            "- [L-001] A. (seen 2x, last 2026-10-17, source: r, promoted_at: 2026-10-20, regressed: 2)",
            "- [L-002] B. (seen 2x, last 2026-10-17, source: r, promoted_at: 2026-10-20)",
            "- [L-003] C. (seen 1x, last 2026-10-17, source: r)",
        ])
        stats = run(repo, "stats")
        self.assertEqual((stats["lessons"], stats["promoted"], stats["regressed"]), (3, 2, 1))


class PruneTests(unittest.TestCase):
    def test_prune_drops_stale_unpromoted_lessons_only(self) -> None:
        stale = "- [L-001] Old one. (seen 1x, last 2026-05-01, source: r)"
        fresh = "- [L-002] Fresh one. (seen 1x, last 2026-10-30, source: r)"
        promoted = "- [L-003] Old but promoted. (seen 2x, last 2026-05-01, source: r, promoted_at: 2026-05-02)"
        nodate = "- [L-004] No date. (source: r)"
        repo = make_repo([stale, fresh, promoted, nodate])
        result = run(repo, "prune", "--today", TODAY, "--stale-days", "90")
        self.assertEqual(result["dropped"], ["L-001"])
        text = lessons_text(repo)
        self.assertNotIn("Old one", text)
        for kept in (fresh, promoted, nodate):
            self.assertIn(kept, text)

    def test_prune_keeps_a_stale_lesson_that_regressed(self) -> None:
        line = "- [L-001] Regressed. (seen 3x, last 2026-05-01, source: r, promoted_at: 2026-05-02, regressed: 1)"
        repo = make_repo([line])
        self.assertEqual(run(repo, "prune", "--today", TODAY)["dropped"], [])

    def test_prune_keeps_headings_and_other_text(self) -> None:
        repo = make_repo(["- [L-001] Old. (seen 1x, last 2026-01-01, source: r)"])
        run(repo, "prune", "--today", TODAY)
        self.assertTrue(lessons_text(repo).startswith("# Lessons\n"))


class InjectionTests(unittest.TestCase):
    def test_promoted_lessons_are_not_injected_until_they_regress(self) -> None:
        repo = make_repo([
            "- [L-001] Enforced by a check. (seen 2x, last 2026-10-17, source: r, promoted_at: 2026-10-20)",
            "- [L-002] Came back. (seen 3x, last 2026-10-17, source: r, promoted_at: 2026-10-20, regressed: 1)",
            "- [L-003] Still plain. (seen 1x, last 2026-10-17, source: r)",
        ])
        out = subprocess.run(["bash", str(HOOK)], cwd=str(repo), input="", capture_output=True, text=True, check=False).stdout
        self.assertNotIn("Enforced by a check", out)
        self.assertIn("Came back", out)
        self.assertIn("Still plain", out)

    def test_skill_documents_the_commands(self) -> None:
        body = (PLUGIN_ROOT / "skills" / "learn" / "SKILL.md").read_text(encoding="utf-8")
        for needle in ("lessons.py", "promoted_at", "regressed", "prune"):
            self.assertIn(needle, body)


if __name__ == "__main__":
    unittest.main()
