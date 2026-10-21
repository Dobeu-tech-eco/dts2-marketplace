"""action-items.py: list, done, add, assign on temp repos; plus skill text contract."""
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, make_tmp_home

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "action-items.py"
SKILL: Final[Path] = PLUGIN_ROOT / "skills" / "action-items" / "SKILL.md"
SECRET_VALUE: Final[str] = "sk-test-NEVER-PRINT"
ITEMS: Final[str] = """# Action items

## Secrets

| name | unlocks | consumed in | how to add | status | owner | added |
|---|---|---|---|---|---|---|
| STRIPE_KEY | payments | src/pay.ts | .env | open | | 2026-10-01 |
| DONE_KEY | mail | src/mail.ts | .env | done | | 2026-10-02 |

## Decisions

| item | context | status | owner | added |
|---|---|---|---|---|
| pick domain | launch | open | claude | 2026-10-10 |

## Handoff

| item | context | status | owner | added |
|---|---|---|---|---|
| codex builder 2 | .harness/handoff/codex/2.md | open | codex | 2026-10-15 |

## Deploy

| item | context | status | owner | added |
|---|---|---|---|---|
| confirm vercel is live | PR 4 | open | | 2026-10-18 |

## Promotions

| item | context | status | owner | added |
|---|---|---|---|---|
| promote L-007 to checks.sh | seen twice | open | | 2026-10-19 |
"""


def make_repo(text: str = ITEMS) -> Path:
    repo: Path = make_tmp_home()
    (repo / ".harness").mkdir()
    (repo / ".harness" / "action-items.md").write_text(text, encoding="utf-8")
    (repo / ".env").write_text(f"STRIPE_KEY={SECRET_VALUE}\n", encoding="utf-8")
    return repo


def run(repo: Path, *args: str) -> tuple[int, dict[str, Any], str]:
    result = subprocess.run(["python3", "-I", str(SCRIPT), str(repo), *args],
                            capture_output=True, text=True, check=False)
    return result.returncode, json.loads(result.stdout), result.stdout + result.stderr


def by_id(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in items}


class ListTests(unittest.TestCase):
    def test_ids_and_resolve_commands(self) -> None:
        _, data, _ = run(make_repo(), "list")
        rows = by_id(data["items"])
        self.assertEqual(sorted(rows), ["D1", "H1", "P1", "S1", "Y1"])
        self.assertEqual(rows["S1"]["resolve_command"], "run add secret STRIPE_KEY")
        self.assertEqual(rows["P1"]["resolve_command"], "learn promote L-007")
        self.assertEqual(rows["H1"]["resolve_command"], "open .harness/handoff/codex/2.md")
        self.assertEqual(rows["Y1"]["resolve_command"], "run")
        self.assertEqual(rows["D1"]["resolve_command"], "run")

    def test_default_subcommand_is_list(self) -> None:
        code, data, _ = run(make_repo())
        self.assertEqual(code, 0)
        self.assertEqual(len(data["items"]), 5)

    def test_owner_and_age(self) -> None:
        _, data, _ = run(make_repo(), "list")
        rows = by_id(data["items"])
        self.assertEqual(rows["D1"]["owner"], "claude")
        self.assertEqual(rows["S1"]["owner"], "")
        self.assertIsInstance(rows["S1"]["age_days"], int)
        self.assertGreater(rows["S1"]["age_days"], 0)

    def test_done_rows_hidden_but_ids_stable(self) -> None:
        _, data, _ = run(make_repo(), "list")
        self.assertNotIn("S2", by_id(data["items"]))

    def test_legacy_rows_without_owner(self) -> None:
        legacy: str = ("## Secrets\n\n| name | unlocks | consumed in | how to add | status |\n|---|---|---|---|---|\n"
                       "| OLD_KEY | x | y | .env | open, deferred wiring |\n")
        _, data, _ = run(make_repo(legacy), "list")
        row = data["items"][0]
        self.assertEqual((row["id"], row["owner"], row["age_days"]), ("S1", "", None))
        self.assertEqual(row["status"], "open, deferred wiring")

    def test_missing_file_is_empty(self) -> None:
        repo: Path = make_tmp_home()
        code, data, _ = run(repo, "list")
        self.assertEqual((code, data["items"]), (0, []))


class MutationTests(unittest.TestCase):
    def test_done_marks_row(self) -> None:
        repo: Path = make_repo()
        code, data, _ = run(repo, "done", "D1")
        self.assertEqual((code, data["status"]), (0, "done"))
        _, listed, _ = run(repo, "list")
        self.assertNotIn("D1", by_id(listed["items"]))
        self.assertIn("pick domain | launch | done", (repo / ".harness" / "action-items.md").read_text())

    def test_add_appends_with_next_id(self) -> None:
        repo: Path = make_repo()
        _, data, _ = run(repo, "add", "Decisions", "choose theme")
        self.assertEqual(data["id"], "D2")
        rows = by_id(run(repo, "list")[1]["items"])
        self.assertEqual(rows["D2"]["item"], "choose theme")
        self.assertEqual(rows["D2"]["status"], "open")
        self.assertEqual(rows["D2"]["age_days"], 0)

    def test_add_secret_uses_name_column(self) -> None:
        repo: Path = make_repo()
        _, data, _ = run(repo, "add", "Secrets", "RESEND_KEY")
        self.assertEqual(data["id"], "S3")
        self.assertEqual(by_id(run(repo, "list")[1]["items"])["S3"]["resolve_command"], "run add secret RESEND_KEY")

    def test_add_creates_missing_group(self) -> None:
        repo: Path = make_repo("# Action items\n")
        _, data, _ = run(repo, "add", "Deploy", "point DNS")
        self.assertEqual(data["id"], "Y1")

    def test_assign_sets_owner(self) -> None:
        repo: Path = make_repo()
        _, data, _ = run(repo, "assign", "S1", "gemini")
        self.assertEqual(data["owner"], "gemini")
        self.assertEqual(by_id(run(repo, "list")[1]["items"])["S1"]["owner"], "gemini")

    def test_assign_on_legacy_row_adds_owner(self) -> None:
        legacy: str = ("## Decisions\n\n| item | context | status |\n|---|---|---|\n| a | b | open |\n")
        repo: Path = make_repo(legacy)
        run(repo, "assign", "D1", "codex")
        self.assertEqual(by_id(run(repo, "list")[1]["items"])["D1"]["owner"], "codex")

    def test_unknown_row_and_group_fail(self) -> None:
        repo: Path = make_repo()
        code, data, _ = run(repo, "done", "S9")
        self.assertEqual(code, 1)
        self.assertIn("error", data)
        code, data, _ = run(repo, "add", "Bogus", "x")
        self.assertEqual(code, 1)
        self.assertIn("error", data)

    def test_never_prints_secret_values(self) -> None:
        repo: Path = make_repo()
        for args in (("list",), ("add", "Secrets", "NEW_KEY"), ("assign", "S1", "claude"), ("done", "S1")):
            self.assertNotIn(SECRET_VALUE, run(repo, *args)[2])


class SkillTextTests(unittest.TestCase):
    def test_skill_contract(self) -> None:
        text: str = SKILL.read_text(encoding="utf-8")
        for needle in ("name: action-items", "action-items.py", "done", "assign", "add", "resolve_command",
                       "Secrets", "Promotions", "never print a value"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
