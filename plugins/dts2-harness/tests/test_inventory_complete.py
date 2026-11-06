"""docs/INVENTORY.md must list every skill, agent, hook script, CLI script and lanes.py subcommand, so it cannot drift."""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path
from types import ModuleType
from typing import Final

from helpers import PLUGIN_ROOT

INVENTORY: Final[Path] = PLUGIN_ROOT / "docs" / "INVENTORY.md"
SCRIPTS: Final[Path] = PLUGIN_ROOT / "scripts"
LANES_CLI: Final[Path] = SCRIPTS / "lanes.py"
HOOKS_JSON: Final[Path] = PLUGIN_ROOT / "hooks" / "hooks.json"
HOOK_SCRIPT: Final[re.Pattern[str]] = re.compile(r"hooks/([\w-]+\.sh)")
# scripts/lanes.py is a module and scripts/lanes/ a package of the same name; the CLI loads under another name.
LANES_MODULE_NAME: Final[str] = "lanes_cli_for_inventory_test"


def inventory_text() -> str:
    return INVENTORY.read_text(encoding="utf-8")


def load_lanes_cli() -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(LANES_MODULE_NAME, LANES_CLI)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lanes_subcommands() -> list[str]:
    parser: argparse.ArgumentParser = load_lanes_cli().build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return list(action.choices)
    return []


def has_table_row(text: str, name: str) -> bool:
    """A table row whose first cell starts with `name` (followed by a space, for its arguments, or the closing tick)."""
    return re.search(rf"^\| `{re.escape(name)}[ `]", text, re.MULTILINE) is not None


class InventoryCompleteTests(unittest.TestCase):
    def test_every_lanes_subcommand_has_a_row(self) -> None:
        text = inventory_text()
        names = lanes_subcommands()
        self.assertGreaterEqual(len(names), 30, "lanes.py should expose its subcommands")
        missing = [name for name in names if not has_table_row(text, name)]
        self.assertEqual(missing, [], f"lanes.py subcommands missing from docs/INVENTORY.md: {missing}")

    def test_every_skill_directory_is_listed(self) -> None:
        text = inventory_text()
        skills = sorted(path.name for path in (PLUGIN_ROOT / "skills").iterdir() if (path / "SKILL.md").is_file())
        self.assertGreaterEqual(len(skills), 18)
        missing = [name for name in skills if f"`/dt:{name}`" not in text]
        self.assertEqual(missing, [], f"skills missing from docs/INVENTORY.md: {missing}")

    def test_every_agent_is_listed(self) -> None:
        text = inventory_text()
        missing = [path.stem for path in sorted((PLUGIN_ROOT / "agents").glob("*.md"))
                   if f"`dt:{path.stem}`" not in text]
        self.assertEqual(missing, [], f"agents missing from docs/INVENTORY.md: {missing}")

    def test_every_registered_hook_script_is_listed(self) -> None:
        text = inventory_text()
        hooks = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))["hooks"]
        scripts = {match.group(1) for groups in hooks.values() for group in groups for hook in group["hooks"]
                   if (match := HOOK_SCRIPT.search(hook["command"]))}
        self.assertTrue(scripts)
        missing = sorted(name for name in scripts if f"`hooks/{name}" not in text)
        self.assertEqual(missing, [], f"hook scripts missing from docs/INVENTORY.md: {missing}")

    def test_every_script_is_listed(self) -> None:
        text = inventory_text()
        missing = sorted(path.name for path in SCRIPTS.glob("*.py") if f"`{path.name}`" not in text)
        self.assertEqual(missing, [], f"scripts missing from docs/INVENTORY.md: {missing}")

    def test_every_makefile_target_is_listed(self) -> None:
        text = inventory_text()
        makefile = PLUGIN_ROOT.parent.parent / "Makefile"
        if not makefile.is_file():
            self.skipTest("the plugin is not inside the repository that holds the Makefile")
        phony = re.search(r"^\.PHONY:(.*)$", makefile.read_text(encoding="utf-8"), re.MULTILINE)
        self.assertIsNotNone(phony)
        targets = phony.group(1).split() if phony else []
        missing = [target for target in targets if f"`make {target}`" not in text]
        self.assertEqual(missing, [], f"Makefile targets missing from docs/INVENTORY.md: {missing}")


if __name__ == "__main__":
    unittest.main()
