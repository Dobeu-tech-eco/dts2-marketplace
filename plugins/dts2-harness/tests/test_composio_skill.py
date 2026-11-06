"""The /dt:composio skill and its wiring: text contracts only. Does not import scripts/composio-setup.py."""

from __future__ import annotations

import re
import unittest
from typing import Final

from helpers import PLUGIN_ROOT

SUBCOMMANDS: Final[tuple[str, ...]] = ("status", "decide", "map", "overlap", "disable")


def _read(relative: str) -> str:
    return (PLUGIN_ROOT / relative).read_text(encoding="utf-8")


class ComposioSkill(unittest.TestCase):
    def setUp(self) -> None:
        self.text: str = _read("skills/composio/SKILL.md")

    def test_user_only_frontmatter(self) -> None:
        self.assertIn("name: composio", self.text)
        self.assertIn("disable-model-invocation: true", self.text)

    def test_yes_no_question_and_signup(self) -> None:
        self.assertIn("Do you have a Composio account?", self.text)
        self.assertIn("https://composio.dev", self.text)
        self.assertIn("decide --account no", self.text)

    def test_references_script_subcommands(self) -> None:
        self.assertIn("composio-setup.py", self.text)
        for command in SUBCOMMANDS:
            self.assertIn(f"composio-setup.py {command}", self.text, command)
        self.assertIn("--from-json", self.text)
        self.assertIn("--always-use", self.text)

    def test_install_steps(self) -> None:
        for needle in (
            "/plugin marketplace add ComposioHQ/composio-plugin-cc",
            "/plugin install composio@composio",
            "curl -fsSL https://composio.dev/install | sh",
            "composio login",
            "https://connect.composio.dev/mcp",
            "duplicate_connection",
        ):
            self.assertIn(needle, self.text)

    def test_never_delete_and_backups(self) -> None:
        self.assertIn("never delete", self.text.lower())
        self.assertIn("backup", self.text.lower())
        self.assertIn("Ask once", self.text)

    def test_mentions_machine_prep_and_memory_split(self) -> None:
        self.assertIn("/dt:machine-prep", self.text)
        self.assertIn("/dt:knowledge", self.text)

    def test_routing_rule(self) -> None:
        for needle in (
            "COMPOSIO_SEARCH_TOOLS",
            "COMPOSIO_MULTI_EXECUTE_TOOL",
            "COMPOSIO_REMOTE_WORKBENCH",
            "COMPOSIO_REMOTE_BASH_TOOL",
            "up to 50",
            "180 s",
        ):
            self.assertIn(needle, self.text)

    def test_no_api_key_literals(self) -> None:
        for name in (
            "skills/composio/SKILL.md",
            "skills/onboard/SKILL.md",
            "templates/discipline.md",
        ):
            text: str = _read(name)
            self.assertIsNone(
                re.search(r"\b(ak_|sk-|ck_)[A-Za-z0-9_-]{8,}", text), name
            )
            self.assertIsNone(re.search(r"(?i)x-api-key\s*[:=]\s*\S{8,}", text), name)


class ComposioWiring(unittest.TestCase):
    def test_onboard_offers_composio_before_hooks(self) -> None:
        text: str = _read("skills/onboard/SKILL.md")
        self.assertIn("## Composio (optional)", text)
        self.assertIn("/dt:composio", text)
        self.assertLess(
            text.index("## Composio (optional)"),
            text.index("## Hooks (optional last step)"),
        )

    def test_machine_prep_includes_overlap(self) -> None:
        text: str = _read("skills/machine-prep/SKILL.md")
        self.assertIn("composio-tools.json", text)
        self.assertIn("composio-setup.py", text)
        self.assertIn("overlap", text)
        self.assertIn("never delete", text)

    def test_discipline_has_composio_routing(self) -> None:
        text: str = _read("templates/discipline.md")
        self.assertIn("## Composio routing", text)
        for needle in (
            "COMPOSIO_SEARCH_TOOLS",
            "COMPOSIO_MULTI_EXECUTE_TOOL",
            "COMPOSIO_REMOTE_WORKBENCH",
        ):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
