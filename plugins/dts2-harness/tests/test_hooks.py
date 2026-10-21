"""Run hooks/stop-checks.sh and hooks/session-lessons.sh in a temp git repo."""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT, make_tmp_home

HOOKS: Final[Path] = PLUGIN_ROOT / "hooks"


def run_hook(name: str, repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(HOOKS / name)], cwd=str(repo), capture_output=True, text=True, check=False)


def make_repo() -> Path:
    repo: Path = make_tmp_home()
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    (repo / ".harness").mkdir()
    return repo


class HookTests(unittest.TestCase):
    def test_stop_checks_runs_repo_local_checks_without_package_json(self) -> None:
        repo: Path = make_repo()
        (repo / ".harness" / "checks.sh").write_text("echo CHECKS-RAN\n", encoding="utf-8")
        result = run_hook("stop-checks.sh", repo)
        self.assertEqual(result.returncode, 0)
        self.assertIn("CHECKS-RAN", result.stderr)

    def test_session_lessons_prints_open_items(self) -> None:
        repo: Path = make_repo()
        state: str = "# Harness state\n\n## Decisions\n- 2026-10-21 chose X\n\n## Open items\n- 2026-10-21 alpha item\n- 2026-10-21 beta item\n"
        (repo / ".harness" / "state.md").write_text(state, encoding="utf-8")
        result = run_hook("session-lessons.sh", repo)
        self.assertEqual(result.returncode, 0)
        self.assertIn("dts2-harness state (open items):", result.stdout)
        self.assertIn("alpha item", result.stdout)
        self.assertIn("beta item", result.stdout)
        self.assertNotIn("chose X", result.stdout)

    def test_open_items_capped_at_five(self) -> None:
        repo: Path = make_repo()
        items: str = "".join(f"- 2026-10-21 item{i}\n" for i in range(8))
        (repo / ".harness" / "state.md").write_text(f"## Open items\n{items}", encoding="utf-8")
        out: str = run_hook("session-lessons.sh", repo).stdout
        self.assertEqual(out.count("- 2026-10-21 item"), 5)


    def test_session_lessons_prints_open_action_items(self) -> None:
        repo: Path = make_repo()
        rows: str = "".join(f"| KEY_{i} | feature {i} | src/a.ts | .env | open |\n" for i in range(4))
        items: str = (
            "# Action items\n\n## Secrets\n\n| name | unlocks | consumed in | how to add | status |\n"
            "|---|---|---|---|---|\n| DONE_KEY | x | y | .env | done |\n" + rows +
            "\n## Decisions\n\n| item | context | status |\n|---|---|---|\n| pick domain | launch | open |\n| pick theme | site | open |\n"
        )
        (repo / ".harness" / "action-items.md").write_text(items, encoding="utf-8")
        out: str = run_hook("session-lessons.sh", repo).stdout
        self.assertIn("dts2-harness action items (open):", out)
        self.assertNotIn("DONE_KEY", out)
        self.assertNotIn("| name |", out)
        self.assertNotIn("|---", out)
        self.assertIn("pick domain", out)
        self.assertNotIn("pick theme", out)
        self.assertEqual(out.count("| open |"), 5)

if __name__ == "__main__":
    unittest.main()
