"""CHANGELOG.md, ARCHITECTURE.md, the dev requirements file and the setup dependency-update templates."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT
from skill_text import read_skill

README: Final[Path] = PLUGIN_ROOT / "README.md"
CHANGELOG: Final[Path] = PLUGIN_ROOT / "CHANGELOG.md"
ARCHITECTURE: Final[Path] = PLUGIN_ROOT / "ARCHITECTURE.md"
VERSION_HEADING: Final[re.Pattern[str]] = re.compile(r"^## \[(\d+\.\d+\.\d+)\]$", re.MULTILINE)


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class ChangelogTests(unittest.TestCase):
    def test_changelog_follows_keep_a_changelog(self) -> None:
        body = text(CHANGELOG)
        self.assertTrue(body.startswith("# Changelog\n"))
        self.assertIn("keepachangelog.com", body)
        versions = VERSION_HEADING.findall(body)
        self.assertIn("3.9.1", versions)
        self.assertIn("2.0.0", versions)
        self.assertEqual(versions, sorted(versions, key=lambda v: tuple(map(int, v.split("."))), reverse=True))

    def test_released_sections_moved_out_of_readme(self) -> None:
        readme = text(README)
        self.assertNotRegex(readme, r"(?m)^- \d+\.\d+\.\d+ ")
        self.assertIn("(CHANGELOG.md)", readme)
        for version in VERSION_HEADING.findall(text(CHANGELOG)):
            self.assertNotIn(f"- {version} —", readme)

    def test_unreleased_stays_in_readme_after_the_changelog_heading(self) -> None:
        readme = text(README)
        self.assertLess(readme.index("\n## Changelog\n"), readme.index("\n## Unreleased\n"))
        self.assertNotIn("## Unreleased", text(CHANGELOG).replace("`## Unreleased`", ""))

    def test_readme_documents_dev_requirements(self) -> None:
        self.assertIn("pip install -r requirements-dev.txt", text(README))
        self.assertIn("hypothesis", text(PLUGIN_ROOT / "requirements-dev.txt").lower())


class ArchitectureTests(unittest.TestCase):
    def test_has_mermaid_diagram(self) -> None:
        body = text(ARCHITECTURE)
        self.assertIn("```mermaid\nflowchart", body)
        for node in ("lead", "builders", "reviewers", "verifier", "ship"):
            self.assertIn(node, body)

    def test_names_every_agent_and_hook(self) -> None:
        body = text(ARCHITECTURE)
        for agent in (PLUGIN_ROOT / "agents").glob("*.md"):
            self.assertIn(f"| {agent.stem} |", body, agent.name)
        hooks = json.loads(text(PLUGIN_ROOT / "hooks" / "hooks.json"))["hooks"]
        for event, groups in hooks.items():
            self.assertIn(event, body)
            for group in groups:
                for hook in group["hooks"]:
                    script = re.search(r"hooks/([\w-]+\.sh)", hook["command"])
                    self.assertIsNotNone(script)
                    self.assertIn(script.group(1) if script else "", body)

    def test_referenced_scripts_exist(self) -> None:
        for name in set(re.findall(r"`((?:scripts/)?[\w-]+\.py)`", text(ARCHITECTURE))):
            path = PLUGIN_ROOT / "scripts" / Path(name).name
            self.assertTrue(path.exists(), name)
        for name in set(re.findall(r"`(hooks/[\w-]+\.sh)`", text(ARCHITECTURE))):
            self.assertTrue((PLUGIN_ROOT / name).exists(), name)


class DependencyUpdateTemplateTests(unittest.TestCase):
    def test_renovate_template_is_valid_json(self) -> None:
        data = json.loads(text(PLUGIN_ROOT / "templates" / "renovate.json"))
        self.assertIn("extends", data)

    def test_dependabot_template_has_version_and_updates(self) -> None:
        body = text(PLUGIN_ROOT / "templates" / "dependabot.yml")
        self.assertRegex(body, r"(?m)^version: 2$")
        self.assertRegex(body, r"(?m)^updates:$")
        self.assertIn("__ECOSYSTEM__", body)

    def test_setup_body_offers_both_after_frontmatter(self) -> None:
        skill = read_skill("setup")
        frontmatter, body = skill.split("\n---\n", 1)
        self.assertNotIn("dependabot", frontmatter.lower())
        for needle in ("templates/dependabot.yml", "templates/renovate.json", "default yes"):
            self.assertIn(needle, body)


if __name__ == "__main__":
    unittest.main()


class CiDevRequirementsTests(unittest.TestCase):
    def test_ci_installs_dev_requirements_so_property_tests_run(self) -> None:
        workflow: Path = PLUGIN_ROOT.parent.parent / ".github" / "workflows" / "test.yml"
        text: str = workflow.read_text(encoding="utf-8")
        self.assertIn("pip install -r requirements-dev.txt", text)
