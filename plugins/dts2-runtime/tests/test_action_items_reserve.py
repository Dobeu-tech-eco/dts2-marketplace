"""Central id reservation for parallel lanes: placeholders fix ids before any lane writes."""
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, make_tmp_home

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "action-items.py"
BASE: Final[str] = """# Action items

## Decisions

| item | context | status | owner | added |
| --- | --- | --- | --- | --- |
| pick a queue | run | open |  | 2026-11-01 |
| old choice | run | done |  | 2026-10-01 |
"""
LANE: Final[str] = """# Lane items

## Decisions

| item | context | status | owner | added |
| --- | --- | --- | --- | --- |
| lane needs a flag | son | open |  | 2026-11-04 |
| lane needs a key | son | open |  | 2026-11-04 |

## Secrets

| name | unlocks | consumed in | how to add | status | owner | added |
| --- | --- | --- | --- | --- | --- | --- |
| API_KEY | login | auth.py | dashboard | open |  | 2026-11-04 |
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


def ids(repo: Path) -> list[str]:
    return [item["id"] for item in run(repo, "list")["items"]]


class ReserveTests(unittest.TestCase):
    def test_reserve_returns_fixed_ids_hidden_from_list(self) -> None:
        repo: Path = make_repo()
        out: dict[str, Any] = run(repo, "reserve", "Decisions", "2", "--holder", "lane-a")
        self.assertEqual(out["ids"], ["D3", "D4"])
        self.assertEqual(ids(repo), ["D1"])

    def test_two_lanes_never_share_an_id(self) -> None:
        repo: Path = make_repo()
        first: list[str] = run(repo, "reserve", "Decisions", "2", "--holder", "lane-a")["ids"]
        second: list[str] = run(repo, "reserve", "Decisions", "2", "--holder", "lane-b")["ids"]
        self.assertEqual(set(first) & set(second), set())
        self.assertEqual(second, ["D5", "D6"])

    def test_add_with_id_fills_only_own_placeholder(self) -> None:
        repo: Path = make_repo()
        run(repo, "reserve", "Decisions", "1", "--holder", "lane-a")
        wrong: dict[str, Any] = run(repo, "add", "Decisions", "x", "--id", "D3", "--holder", "lane-b")
        self.assertEqual(wrong["_code"], 1)
        self.assertIn("reserved by lane-a", wrong["error"])
        good: dict[str, Any] = run(repo, "add", "Decisions", "choose db", "--id", "D3", "--holder", "lane-a")
        self.assertEqual(good["id"], "D3")
        self.assertEqual(ids(repo), ["D1", "D3"])

    def test_add_with_unreserved_id_is_refused(self) -> None:
        repo: Path = make_repo()
        out: dict[str, Any] = run(repo, "add", "Decisions", "x", "--id", "D1", "--holder", "lane-a")
        self.assertEqual(out["_code"], 1)
        self.assertIn("not reserved", out["error"])

    def test_release_keeps_rows_so_later_ids_do_not_shift(self) -> None:
        repo: Path = make_repo()
        run(repo, "reserve", "Decisions", "2", "--holder", "lane-a")
        run(repo, "reserve", "Decisions", "1", "--holder", "lane-b")
        self.assertEqual(run(repo, "release", "--holder", "lane-a")["released"], ["D3", "D4"])
        run(repo, "add", "Decisions", "b item", "--id", "D5", "--holder", "lane-b")
        self.assertEqual(ids(repo), ["D1", "D5"])
        self.assertIn("(released)", (repo / ".harness" / "action-items.md").read_text())

    def test_fold_uses_reserved_ids_then_appends_then_releases(self) -> None:
        repo: Path = make_repo()
        lane: Path = make_repo(LANE) / ".harness" / "action-items.md"
        run(repo, "reserve", "Decisions", "1", "--holder", "lane-a")
        run(repo, "reserve", "Decisions", "3", "--holder", "lane-a")
        out: dict[str, Any] = run(repo, "fold", str(lane), "--holder", "lane-a")
        self.assertEqual(out["folded"], {"D1": "D3", "D2": "D4", "S1": "S1"})
        self.assertEqual(out["released"], ["D5", "D6"])
        self.assertEqual(ids(repo), ["S1", "D1", "D3", "D4"])

    def test_existing_commands_unchanged(self) -> None:
        repo: Path = make_repo()
        self.assertEqual(run(repo, "add", "Decisions", "plain", "add")["id"], "D3")
        self.assertEqual(run(repo, "done", "D1")["status"], "done")
        self.assertEqual(ids(repo), ["D3"])


if __name__ == "__main__":
    unittest.main()
