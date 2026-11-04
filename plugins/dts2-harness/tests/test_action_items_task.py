"""TASK_-linked action items: an item that needs user input points back at the onboard task it came from."""
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, make_tmp_home

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "action-items.py"
BASE: Final[str] = """# Action items

## Secrets

| name | unlocks | consumed in | how to add | status | owner | added |
| --- | --- | --- | --- | --- | --- | --- |
| OLD_KEY | legacy | old.py | dashboard | done |  | 2026-10-01 |
"""


def make_repo(text: str = BASE) -> Path:
    repo: Path = make_tmp_home()
    path: Path = repo / ".harness" / "action-items.md"
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")
    return repo


def run(repo: Path, *args: str) -> dict[str, Any]:
    result = subprocess.run(
        ["python3", "-I", str(SCRIPT), str(repo), *args], capture_output=True, text=True, check=False,
    )
    parsed: dict[str, Any] = json.loads(result.stdout)
    parsed["_code"] = result.returncode
    return parsed


class TaskLinkTests(unittest.TestCase):
    def test_add_with_task_prefixes_title(self) -> None:
        repo = make_repo()
        added = run(repo, "add", "secrets", "stripe secret", "--task", "A1")
        self.assertEqual(added["id"], "S2")
        self.assertEqual(added["task"], "A1")
        text: str = (repo / ".harness" / "action-items.md").read_text(encoding="utf-8")
        self.assertIn("| TASK_A1_S2-stripe secret |", text)

    def test_add_without_task_is_unchanged(self) -> None:
        repo = make_repo()
        run(repo, "add", "secrets", "plain key")
        text: str = (repo / ".harness" / "action-items.md").read_text(encoding="utf-8")
        self.assertIn("| plain key |", text)
        self.assertNotIn("TASK_", text)

    def test_done_reports_linked_task(self) -> None:
        repo = make_repo()
        run(repo, "add", "decisions", "pick region", "--task", "B3")
        done = run(repo, "done", "D1")
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["task"], "B3")
        plain = run(repo, "done", "S1")
        self.assertNotIn("task", plain)

    def test_fill_reserved_with_task(self) -> None:
        repo = make_repo()
        reserved = run(repo, "reserve", "secrets", "1", "--holder", "a")
        row_id: str = reserved["ids"][0]
        filled = run(repo, "add", "secrets", "api key", "--id", row_id, "--holder", "a", "--task", "C2")
        self.assertEqual(filled["task"], "C2")
        text: str = (repo / ".harness" / "action-items.md").read_text(encoding="utf-8")
        self.assertIn(f"| TASK_C2_{row_id}-api key |", text)

    def test_list_keeps_task_title(self) -> None:
        repo = make_repo()
        run(repo, "add", "secrets", "stripe secret", "--task", "A1")
        items = run(repo, "list")["items"]
        titles: list[str] = [item["item"] for item in items]
        self.assertIn("TASK_A1_S2-stripe secret", titles)


if __name__ == "__main__":
    unittest.main()
