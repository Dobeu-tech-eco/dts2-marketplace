"""The Cursor instruction package stays aligned with the generator and stays read-only."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT

REPO: Final[Path] = PLUGIN_ROOT.parent.parent
SURFACE: Final[Path] = PLUGIN_ROOT / "scripts" / "cursor_surface.py"
MISSING: Final[str] = "No end state yet; /dt:setup interviews to one."


def _load():
    import importlib.util
    spec = importlib.util.spec_from_file_location("cursor_surface", SURFACE)
    if spec is None or spec.loader is None:
        raise RuntimeError("cursor_surface could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CursorSurfaceTests(unittest.TestCase):
    def test_generator_check_passes(self) -> None:
        result = subprocess.run(
            ["python3", str(SURFACE), "--check"],
            capture_output=True, text=True, cwd=str(REPO), check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"ok": true', result.stdout)

    def test_manifest_identity_and_relative_paths(self) -> None:
        plugin = json.loads(
            (REPO / "plugins" / "dt-cursor" / ".cursor-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        market = json.loads((REPO / ".cursor-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual(plugin["name"], "dt")
        self.assertEqual(plugin["license"], "MIT")
        self.assertEqual(plugin["author"]["name"], "Dobeu Tech Solutions LLC")
        self.assertEqual(plugin["version"], "6.0.0")
        self.assertIn("DT: Init to Ship Auto Agent Orchestrator", plugin["description"])
        self.assertNotIn("Claude Code harness", plugin["description"])
        for key in ("skills", "commands", "rules", "logo"):
            value = plugin[key]
            self.assertFalse(value.startswith("/"))
            self.assertNotIn("..", value)
            self.assertTrue((REPO / "plugins" / "dt-cursor" / value).exists())
        entry = market["plugins"][0]
        self.assertEqual(entry["name"], "dt")
        self.assertEqual(entry["source"], "plugins/dt-cursor")
        self.assertTrue((REPO / entry["source"] / ".cursor-plugin" / "plugin.json").is_file())

    def test_command_slugs_match_runtime_skills_and_not_the_colon_form(self) -> None:
        runtime = {path.parent.name for path in (PLUGIN_ROOT / "skills").glob("*/SKILL.md")}
        commands = {path.stem for path in (REPO / "plugins" / "dt-cursor" / "commands").glob("*.md")}
        project = {path.stem for path in (REPO / ".cursor" / "commands").glob("*.md")}
        self.assertEqual(commands, {f"dt-{name}" for name in runtime})
        self.assertEqual(commands, project)
        self.assertEqual(len(commands), 27)
        for stem in commands:
            self.assertNotIn(":", stem)
            plugin_file = REPO / "plugins" / "dt-cursor" / "commands" / f"{stem}.md"
            project_file = REPO / ".cursor" / "commands" / f"{stem}.md"
            self.assertEqual(plugin_file.read_bytes(), project_file.read_bytes())
            text = plugin_file.read_text(encoding="utf-8")
            self.assertIn(f"name: {stem}", text)
            self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", text)
            self.assertNotIn("gh pr merge", text)
        self.assertFalse((REPO / "plugins" / "dt-cursor" / "commands" / "dt-respond.md").exists())
        run_text = (REPO / "plugins" / "dt-cursor" / "commands" / "dt-run.md").read_text(encoding="utf-8")
        self.assertIn("as a read-only smoke", run_text)
        self.assertIn("does not pass `--yes`", run_text)
        fleet_text = (REPO / "plugins" / "dt-cursor" / "commands" / "dt-fleet.md").read_text(encoding="utf-8")
        self.assertIn("one computer", fleet_text)
        self.assertIn("does not discover or message sessions", fleet_text)

    def test_skill_is_explicit_invoke_and_matches_the_project_copy(self) -> None:
        plugin = (REPO / "plugins" / "dt-cursor" / "skills" / "dt" / "SKILL.md").read_text(encoding="utf-8")
        project = (REPO / ".cursor" / "skills" / "dt" / "SKILL.md").read_text(encoding="utf-8")
        self.assertEqual(plugin, project)
        self.assertIn("name: dt", plugin)
        self.assertIn("disable-model-invocation: true", plugin)
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", plugin)

    def test_claude_skill_tree_is_not_the_cursor_skill_tree(self) -> None:
        cursor_skills = list((REPO / "plugins" / "dt-cursor" / "skills").glob("*/SKILL.md"))
        self.assertEqual([path.parent.name for path in cursor_skills], ["dt"])
        self.assertFalse((REPO / "plugins" / "dt-cursor" / "hooks").exists())
        self.assertFalse((REPO / "plugins" / "dt-cursor" / "scripts").exists())

    def test_check_in_on_this_repo_writes_nothing(self) -> None:
        surface = _load()
        before = set((REPO / ".harness").rglob("*")) if (REPO / ".harness").exists() else set()
        report = surface.check_in_report(REPO)
        after = set((REPO / ".harness").rglob("*")) if (REPO / ".harness").exists() else set()
        self.assertEqual(report, MISSING)
        self.assertEqual(before, after)
        self.assertFalse((REPO / ".harness" / "end-state.md").exists())

    def test_check_in_counts_a_fixture_without_writing(self) -> None:
        surface = _load()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            harness = root / ".harness"
            harness.mkdir()
            (harness / "end-state.md").write_text(
                "\n".join([
                    "## Sections",
                    "| # | section | status |",
                    "|---|---|---|",
                    "| 1 | data model | done |",
                    "| 2 | api | todo |",
                    "## Acceptance criteria",
                    "- [x] shipped",
                    "- [ ] billed",
                    "## Goal",
                    "- [ ] not an acceptance box",
                ]),
                encoding="utf-8",
            )
            (harness / "action-items.md").write_text(
                "\n".join([
                    "## Secrets",
                    "| name | status |",
                    "|---|---|",
                    "| STRIPE_KEY | open |",
                    "| OTHER | done |",
                ]),
                encoding="utf-8",
            )
            before = {path: path.read_bytes() for path in harness.iterdir()}
            report = surface.check_in_report(root)
            after = {path: path.read_bytes() for path in harness.iterdir()}
        self.assertEqual(before, after)
        self.assertIn("2 of 5 complete (40%)", report)
        self.assertIn("[x] section: data model", report)
        self.assertIn("[ ] section: api", report)
        self.assertIn("[x] shipped", report)
        self.assertIn("[ ] billed", report)
        self.assertIn("[ ] Secrets: STRIPE_KEY", report)
        self.assertNotIn("OTHER", report)
        self.assertNotIn("not an acceptance box", report)


if __name__ == "__main__":
    unittest.main()
