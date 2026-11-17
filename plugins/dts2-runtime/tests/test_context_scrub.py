from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from helpers import PLUGIN_ROOT

SCRIPT: Path = PLUGIN_ROOT / "scripts" / "context_scrub.py"
STAMP: str = "20260101-000000"
CODEX_TOML: str = '''model = "x"

[mcp_servers.github]
command = "npx"
args = ["-y", "gh-mcp"]

[mcp_servers.gh-twin]
command = "npx"
args = ["-y", "gh-mcp"]

[mcp_servers.gh-twin.env]
TOKEN = "env"

[plugins."alpha@one"]
enabled = true

[plugins."alpha@two"]
enabled = true
'''


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def mcp(**servers: str) -> str:
    return json.dumps({"mcpServers": {n: {"command": c, "args": ["-y", "same"]} for n, c in servers.items()}})


def build_machine(root: Path) -> tuple[Path, Path]:
    """Claude, Codex and Cursor homes with planted duplicates; returns (home, project)."""
    home, project = root / "home", root / "repo"
    claude = home / ".claude"
    write(claude / "settings.json", json.dumps({"enabledPlugins": {"dup@mkt-a": True, "dup@mkt-b": True,
                                                                     "kept@mkt-a": True, "kept@mkt-b": True}}))
    write(claude / "skills" / "pdf" / "SKILL.md", "user pdf")
    write(claude / "agents" / "lead.md", "user lead")
    write(claude / "plugins" / "installed_plugins.json",
          json.dumps({"plugins": {"dup@mkt-a": [{"version": "1"}]}}))
    write(claude / "plugins" / "cache" / "mkt-a" / "dup" / "1" / "skills" / "pdf" / "SKILL.md", "plugin pdf")
    write(claude / "plugins" / "cache" / "mkt-a" / "dup" / "1" / "agents" / "lead.md", "plugin lead")
    write(project / ".mcp.json", mcp(one="npx", two="npx"))
    write(project / ".harness" / "keep.yaml", "plugins:\n  - kept@mkt-b\nskills:\n  - name: pdf\n")
    write(home / ".codex" / "config.toml", CODEX_TOML)
    write(home / ".codex" / "skills" / "tool" / "SKILL.md", "a")
    write(home / ".codex" / "agents" / "rev.toml", "a")
    write(home / ".cursor" / "mcp.json", mcp(a="uvx", b="uvx"))
    write(project / ".cursor" / "rules" / "style.mdc", "r")
    write(home / ".cursor" / "skills" / "style" / "SKILL.md", "s")
    return home, project



def run(home: Path, project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["python3", "-I", str(SCRIPT), *args, "--home", str(home), "--project", str(project)],
                          capture_output=True, text=True, check=False, cwd=str(project))


def run_json(home: Path, project: Path, *args: str) -> dict[str, Any]:
    result = run(home, project, *args, "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def snapshot(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): p.read_text(encoding="utf-8") for p in sorted(root.rglob("*")) if p.is_file()}


class ContextScrubTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.home, self.project = build_machine(self.root)
        self.roster = "claude,codex,cursor"

    def groups(self, plan: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
        return {(g["keep"]["agent"], g["category"], g["name"]): g for g in plan["groups"]}

    def test_inventory_lists_every_category_per_agent(self) -> None:
        report = run_json(self.home, self.project, "inventory", "--roster", self.roster)
        agents = report["agents"]
        self.assertEqual({"claude", "codex", "cursor"}, set(agents))
        self.assertEqual(4, len(agents["claude"]["plugins"]))
        self.assertEqual(2, len(agents["claude"]["mcp"]))
        self.assertEqual(["github", "gh-twin"], [m["name"] for m in agents["codex"]["mcp"]])
        self.assertEqual(["rev"], [a["name"] for a in agents["codex"]["agents"]])
        self.assertEqual(2, len(agents["cursor"]["mcp"]))
        self.assertEqual(2, len(agents["cursor"]["skills"]))

    def test_unknown_agent_is_reported_not_an_error(self) -> None:
        result = run(self.home, self.project, "plan", "--roster", "claude,mystery", "--json")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["mystery"], [n["agent"] for n in json.loads(result.stdout)["notInspectable"]])
        text = run(self.home, self.project, "inventory", "--roster", "mystery")
        self.assertEqual(0, text.returncode)
        self.assertIn("not inspectable", text.stdout)

    def test_plan_applies_the_same_rules_to_every_agent(self) -> None:
        groups = self.groups(run_json(self.home, self.project, "plan", "--roster", self.roster))
        plugins = groups[("claude", "plugins", "kept")]
        self.assertEqual("kept@mkt-b", plugins["keep"]["source"], "keep.yaml wins over the first copy")
        self.assertEqual(["kept@mkt-a"], [i["source"] for i in plugins["disable"]])
        self.assertEqual("dup@mkt-a", groups[("claude", "plugins", "dup")]["keep"]["source"])
        self.assertEqual("github", groups[("codex", "mcp", "github")]["keep"]["name"])
        self.assertEqual(["gh-twin"], [i["name"] for i in groups[("codex", "mcp", "github")]["disable"]])
        self.assertEqual("alpha@one", groups[("codex", "plugins", "alpha")]["keep"]["source"])
        self.assertEqual(["b"], [i["name"] for i in groups[("cursor", "mcp", "a")]["disable"]])
        self.assertEqual("dup", groups[("claude", "skills", "pdf")]["keep"]["source"].split("@")[0])
        self.assertEqual(["lead"], [i["name"] for i in groups[("claude", "agents", "lead")]["disable"]])

    def test_keep_yaml_entry_is_never_disabled(self) -> None:
        write(self.project / ".harness" / "keep.yaml", "plugins:\n  - kept@mkt-a\n  - kept@mkt-b\n")
        groups = self.groups(run_json(self.home, self.project, "plan", "--roster", "claude"))
        group = groups[("claude", "plugins", "kept")]
        self.assertEqual([], group["disable"])
        self.assertEqual(1, len(group["protected"]))

    def test_dry_run_writes_nothing(self) -> None:
        before = snapshot(self.root)
        result = run(self.home, self.project, "apply", "--roster", self.roster)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Dry run", result.stdout)
        self.assertEqual(before, snapshot(self.root))

    def test_apply_backs_up_and_disables_without_deleting(self) -> None:
        before = snapshot(self.root)
        result = run(self.home, self.project, "apply", "--roster", self.roster, "--yes")
        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["backups"])
        for backup in report["backups"]:
            self.assertIn(".bak-", backup)
            self.assertTrue(Path(backup).exists())
        settings = json.loads((self.home / ".claude" / "settings.json").read_text())
        self.assertFalse(settings["enabledPlugins"]["kept@mkt-a"])
        self.assertTrue(settings["enabledPlugins"]["kept@mkt-b"])
        claude_project = json.loads((self.project / ".claude" / "settings.json").read_text())
        self.assertEqual(["two"], claude_project["disabledMcpjsonServers"])
        self.assertIn("enabled = false", (self.home / ".codex" / "config.toml").read_text())
        self.assertTrue(json.loads((self.home / ".cursor" / "mcp.json").read_text())["mcpServers"]["b"]["disabled"])
        self.assertTrue((self.home / ".claude" / "agents-disabled" / "lead.md").exists())
        self.assertFalse((self.home / ".claude" / "agents" / "lead.md").exists())
        self.assertEqual(before[str(Path("repo/.harness/keep.yaml"))],
                         (self.project / ".harness" / "keep.yaml").read_text())
        after = snapshot(self.root)
        self.assertTrue(all(any(text == t for t in after.values()) for text in before.values() if text.strip()),
                        "every original content still exists somewhere")

    def test_apply_is_idempotent(self) -> None:
        run(self.home, self.project, "apply", "--roster", self.roster, "--yes")
        second = run_json(self.home, self.project, "plan", "--roster", self.roster)
        self.assertEqual(0, second["disableCount"], second)


if __name__ == "__main__":
    unittest.main()
