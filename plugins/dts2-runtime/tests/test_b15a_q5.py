"""Q-5: lessons carry optional paths: globs; scope-check and session-lessons print only matching lessons, newest 5."""
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, make_tmp_home

SCOPE: Final[Path] = PLUGIN_ROOT / "scripts" / "scope-check.py"
HOOK: Final[Path] = PLUGIN_ROOT / "hooks" / "session-lessons.sh"
TAIL: Final[str] = "(seen 1x, last 2026-10-01, source: run x)"


def make_repo(lessons: list[str], changed: list[str]) -> Path:
    repo: Path = make_tmp_home()
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    (repo / ".harness").mkdir()
    (repo / ".harness" / "lessons.md").write_text("# Lessons\n\n" + "".join(f"{line}\n" for line in lessons), encoding="utf-8")
    (repo / ".harness" / "config.yaml").write_text("x: 1\n", encoding="utf-8")
    for name in changed:
        path: Path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n", encoding="utf-8")
    return repo


def scope_lessons(repo: Path, *extra: str) -> list[str]:
    out = subprocess.run(["python3", "-I", str(SCOPE), "--lessons", *extra, str(repo)], capture_output=True, text=True, check=False)
    data: dict[str, Any] = json.loads(out.stdout)
    lessons: list[str] = data["lessons"]
    return lessons


def hook_out(repo: Path) -> str:
    return subprocess.run(["bash", str(HOOK)], cwd=str(repo), input="", capture_output=True, text=True, check=False).stdout


class LessonPathsTests(unittest.TestCase):
    def test_lesson_without_paths_always_matches(self) -> None:
        repo = make_repo([f"- [L-001] Check inputs. {TAIL}"], [])
        self.assertEqual(len(scope_lessons(repo)), 1)

    def test_path_scoped_lesson_needs_a_matching_changed_file(self) -> None:
        line = f"- [L-002] Validate webhook signatures. {TAIL} {{paths: src/api/**, *.ts}}"
        hit = make_repo([line], ["src/api/hooks/stripe.py"])
        self.assertEqual(scope_lessons(hit), [line])
        top = make_repo([line], ["index.ts"])
        self.assertEqual(scope_lessons(top), [line])
        miss = make_repo([line], ["docs/readme.md"])
        self.assertEqual(scope_lessons(miss), [])

    def test_single_star_does_not_cross_directories(self) -> None:
        line = f"- [L-003] Mind the top level. {TAIL} {{paths: *.ts}}"
        repo = make_repo([line], ["src/deep/file.ts"])
        self.assertEqual(scope_lessons(repo), [])

    def test_prints_only_the_newest_five_matching(self) -> None:
        lines = [f"- [L-{i:03d}] Rule {i}. {TAIL} {{paths: src/**}}" for i in range(1, 9)]
        repo = make_repo(lines, ["src/a.py"])
        self.assertEqual(scope_lessons(repo), lines[-5:])

    def test_files_override_replaces_git_detection(self) -> None:
        line = f"- [L-004] Docs only. {TAIL} {{paths: docs/**}}"
        repo = make_repo([line], ["src/a.py"])
        self.assertEqual(scope_lessons(repo, "--files", "docs/x.md"), [line])
        self.assertEqual(scope_lessons(repo, "--files", "src/a.py"), [])

    def test_session_lessons_prints_only_matching_newest_five(self) -> None:
        scoped = f"- [L-010] Only for api code. {TAIL} {{paths: src/api/**}}"
        always = [f"- [L-{i:03d}] Global rule {i}. {TAIL}" for i in range(20, 27)]
        repo = make_repo([scoped, *always], ["web/page.tsx"])
        out = hook_out(repo)
        self.assertNotIn("Only for api code", out)
        self.assertEqual(out.count("Global rule"), 5)
        self.assertIn("Global rule 26", out)
        self.assertNotIn("Global rule 21", out)

    def test_session_lessons_shows_scoped_lesson_when_files_match(self) -> None:
        scoped = f"- [L-010] Only for api code. {TAIL} {{paths: src/api/**}}"
        repo = make_repo([scoped], ["src/api/x.py"])
        self.assertIn("Only for api code", hook_out(repo))


if __name__ == "__main__":
    unittest.main()
