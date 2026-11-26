"""The directory listing stays policy-clean relative to the runtime harness."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Final

from helpers import PLUGIN_ROOT

REPO: Final[Path] = PLUGIN_ROOT.parent.parent
LISTING: Final[Path] = REPO / "plugins" / "dts2-harness"


class DirectoryEditionTests(unittest.TestCase):
    def test_listing_release_notes_keep_version_order(self) -> None:
        changelog = (LISTING / "CHANGELOG.md").read_text(encoding="utf-8")
        versions = re.findall(r"^## \[(\d+\.\d+\.\d+)\]$", changelog, re.MULTILINE)
        self.assertEqual(versions[0], "6.0.1")
        self.assertIn("5.2.0", versions)
        self.assertEqual(versions, sorted(versions, key=lambda value: tuple(map(int, value.split("."))), reverse=True))

    def test_listing_has_no_hooks_or_scripts(self) -> None:
        self.assertFalse((LISTING / "hooks").exists())
        self.assertFalse((LISTING / "scripts").exists())
        self.assertTrue((PLUGIN_ROOT / "hooks" / "hooks.json").is_file())
        self.assertTrue((PLUGIN_ROOT / "scripts" / "directory_edition.py").is_file())

    def test_listing_version_is_independent_of_the_runtime(self) -> None:
        listing = json.loads((LISTING / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        runtime = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(listing["version"], "6.0.1")
        self.assertEqual(listing["name"], "dt")
        self.assertNotEqual(listing["version"], runtime["version"])
        self.assertNotIn("hooks", listing)

    def test_knowledge_credential_is_only_bound_to_the_remote_mcp_header(self) -> None:
        manifest = json.loads((LISTING / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        option = manifest["userConfig"]["knowledge_token"]
        self.assertIs(option["sensitive"], True)
        self.assertNotIn("default", option)
        server = manifest["mcpServers"]["knowledge"]
        self.assertEqual(server["type"], "http")
        self.assertEqual(server["url"], "${user_config.knowledge_endpoint}")
        self.assertEqual(server["headers"], {"Authorization": "Bearer ${user_config.knowledge_token}"})
        for profile in (LISTING / "profiles" / "agents").glob("*.json"):
            self.assertNotIn("apiKeyEnv", json.loads(profile.read_text(encoding="utf-8")))

    def test_agents_drop_experimental_frontmatter(self) -> None:
        builder = (LISTING / "agents" / "builder.md").read_text(encoding="utf-8")
        for key in ("experimental", "maxTurns", "effort", "color", "omitClaudeMd"):
            self.assertNotRegex(builder.split("---", 2)[1], rf"(?m)^{key}:")
        self.assertIn("name: builder", builder)
        self.assertIn("tools: Read, Write, Edit, Grep, Glob, Bash", builder)
        runtime = (PLUGIN_ROOT / "agents" / "builder.md").read_text(encoding="utf-8")
        self.assertIn("\nexperimental:\n  cacheTtl: 1h\n", runtime)


if __name__ == "__main__":
    unittest.main()
