"""scripts/improve-scan.py and the broadened find-skills skill."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "improve-scan.py"
SKILL: Final[Path] = PLUGIN_ROOT / "skills" / "find-skills" / "SKILL.md"
CATEGORIES: Final[tuple[str, ...]] = (
    "skills", "database", "hooks", "mcp", "plugins", "commands", "subagents", "permissions", "ci", "docs",
)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class ScanCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root: Path = Path(self._tmp.name)
        self.repo: Path = self.root / "repo"
        self.home: Path = self.root / "home"
        self.repo.mkdir()
        self.home.mkdir()

    def run_scan(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "--cwd", str(self.repo), "--home", str(self.home)],
            capture_output=True, text=True,
        )

    def scan(self) -> dict[str, Any]:
        result = self.run_scan()
        self.assertEqual(result.returncode, 0, result.stderr)
        data: dict[str, Any] = json.loads(result.stdout)
        return data

    def ids(self) -> dict[str, dict[str, Any]]:
        return {item["id"]: item for item in self.scan()["recommendations"]}


class EmptyRepoTests(ScanCase):
    def test_empty_dir_recommends_the_basics_sorted(self) -> None:
        data = self.scan()
        found = {item["id"] for item in data["recommendations"]}
        for ident in ("add-ci", "add-agent-docs", "add-recommended-hooks", "suggest-skills"):
            self.assertIn(ident, found)
        keys = [(r["priority"], CATEGORIES.index(r["category"]), r["id"]) for r in data["recommendations"]]
        self.assertEqual(keys, sorted(keys))
        for rec in data["recommendations"]:
            self.assertEqual(set(rec), {"category", "id", "title", "why", "how", "priority"})
            self.assertIn(rec["category"], CATEGORIES)

    def test_skills_item_carries_the_facts(self) -> None:
        how = self.ids()["suggest-skills"]["how"]
        self.assertIn("skill-suggest.py", how)
        self.assertIn('"has_ci": false', how)

    def test_deterministic(self) -> None:
        self.assertEqual(self.run_scan().stdout, self.run_scan().stdout)

    def test_never_creates_files(self) -> None:
        write(self.repo / "package.json", "{}")
        before = sorted(str(p) for p in self.root.rglob("*"))
        self.run_scan()
        self.assertEqual(before, sorted(str(p) for p in self.root.rglob("*")))


class SatisfiedRepoTests(ScanCase):
    def test_react_repo_with_setup_drops_items(self) -> None:
        write(self.repo / "package.json", json.dumps({"dependencies": {"react": "18"}, "scripts": {}}))
        write(self.repo / ".github" / "workflows" / "ci.yml", "steps:\n  - run: npm test\n")
        write(self.repo / "CLAUDE.md", "# docs\n")
        write(self.repo / ".mcp.json", json.dumps({"mcpServers": {"playwright": {}}}))
        write(self.repo / ".claude" / "settings.json", json.dumps({
            "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "true"}]}]},
        }))
        write(self.repo / ".git" / "config", '[remote "origin"]\n url = https://github.com/a/b.git\n')
        data = self.scan()
        found = {item["id"] for item in data["recommendations"]}
        for ident in ("add-ci", "ci-run-tests", "add-agent-docs", "add-recommended-hooks", "mcp-playwright"):
            self.assertNotIn(ident, found)
        self.assertIn("mcp-github", found)
        self.assertTrue(data["facts"]["has_frontend"])
        self.assertTrue(data["facts"]["has_ci"])
        self.assertEqual(data["inventory"]["hooks"]["project"], 1)
        self.assertEqual(data["inventory"]["mcp_servers"], ["playwright"])


class SettingsTests(ScanCase):
    def test_broad_allow_is_priority_one(self) -> None:
        write(self.repo / ".claude" / "settings.json", json.dumps({"permissions": {"allow": ["Bash(*)"]}}))
        item = self.ids()["remove-broad-allow"]
        self.assertEqual(item["priority"], 1)
        self.assertNotIn("allowlist-read-only", self.ids())

    def test_invalid_mcp_json_is_a_fix_item(self) -> None:
        write(self.repo / ".mcp.json", "{nope")
        result = self.run_scan()
        self.assertEqual(result.returncode, 0)
        item = {r["id"]: r for r in json.loads(result.stdout)["recommendations"]}["fix-mcp-json"]
        self.assertEqual((item["priority"], item["category"]), (1, "mcp"))

    def test_home_is_isolated_and_read(self) -> None:
        write(self.home / ".claude" / "settings.json", json.dumps({
            "enabledPlugins": {"x@y": True}, "permissions": {"allow": ["Bash(ls:*)"], "deny": ["Read(./.env*)"]},
        }))
        data = self.scan()
        self.assertEqual(data["inventory"]["plugins"], ["x@y"])
        self.assertEqual(data["inventory"]["allow"], 1)
        self.assertIn("pin-plugins-in-project", {r["id"] for r in data["recommendations"]})
        self.assertNotIn("deny-secrets-read", {r["id"] for r in data["recommendations"]})


class DatabaseTests(ScanCase):
    def db_ids(self) -> set[str]:
        return {r["id"] for r in self.scan()["recommendations"] if r["category"] == "database"}

    def test_no_db_repo_has_no_database_recs(self) -> None:
        write(self.repo / "package.json", json.dumps({"dependencies": {"react": "18"}}))
        data = self.scan()
        self.assertFalse(data["facts"]["has_database"])
        self.assertEqual(self.db_ids(), set())
        self.assertEqual(data["inventory"]["database"], {"engines": [], "orms": [], "migrations_dirs": []})

    def test_prisma_repo(self) -> None:
        write(self.repo / "package.json", json.dumps({"dependencies": {"@prisma/client": "5"}}))
        write(self.repo / "prisma" / "schema.prisma", "datasource db {}\n")
        write(self.repo / "prisma" / "migrations" / "1.sql", "select 1;\n")
        data = self.scan()
        self.assertTrue(data["facts"]["has_prisma"])
        self.assertTrue(data["facts"]["has_database"])
        self.assertEqual(data["inventory"]["database"]["migrations_dirs"], ["prisma/migrations"])
        for ident in ("db-guard-hook", "mcp-prisma", "db-deny-destructive", "db-migration-ci", "db-skills"):
            self.assertIn(ident, self.db_ids())
        self.assertIn("db-guard,migration-check", self.ids()["db-guard-hook"]["how"])
        self.assertIn('"has_prisma": true', self.ids()["db-skills"]["how"])

    def test_supabase_repo_and_satisfied_items(self) -> None:
        write(self.repo / "supabase" / "config.toml", "")
        write(self.repo / ".mcp.json", json.dumps({"mcpServers": {"supabase": {}}}))
        write(self.repo / ".claude" / "settings.json", json.dumps({"permissions": {"deny": ["Bash(*supabase db reset*)"]}}))
        data = self.scan()
        self.assertTrue(data["facts"]["has_supabase"])
        self.assertTrue(data["facts"]["has_postgres"])
        ids = self.db_ids()
        self.assertNotIn("mcp-supabase", ids)
        self.assertNotIn("mcp-postgres", ids)
        self.assertNotIn("db-deny-destructive", ids)
        self.assertIn("db-migration-ci", ids)

    def test_database_items_are_ahead_of_other_priority_two(self) -> None:
        write(self.repo / "supabase" / "config.toml", "")
        recs = self.scan()["recommendations"]
        twos = [r["category"] for r in recs if r["priority"] == 2]
        self.assertLess(twos.index("database"), twos.index("permissions"))

    def test_scan_does_not_write(self) -> None:
        write(self.repo / "supabase" / "config.toml", "")
        before = sorted(str(p) for p in self.root.rglob("*"))
        self.run_scan()
        self.assertEqual(before, sorted(str(p) for p in self.root.rglob("*")))


class SkillTests(unittest.TestCase):
    def test_skill_mentions_scripts_and_categories(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        for needle in ("improve-scan.py", "hooks-setup.py", "database tooling", *CATEGORIES):
            self.assertIn(needle, text)

    def test_description_has_no_angle_brackets(self) -> None:
        line = next(x for x in SKILL.read_text(encoding="utf-8").splitlines() if x.startswith("description:"))
        self.assertNotIn("<", line)
        self.assertNotIn(">", line)


if __name__ == "__main__":
    unittest.main()
