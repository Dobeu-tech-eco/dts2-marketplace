"""improve-scan suppresses MCP recommendations that the Composio tool map already covers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT

SCRIPT: Final[Path] = PLUGIN_ROOT / "scripts" / "improve-scan.py"


class ComposioDedupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.repo: Path = root / "repo"
        self.home: Path = root / "home"
        self.dts2: Path = root / "dts2"
        for path in (self.repo, self.home, self.dts2):
            path.mkdir()
        (self.repo / ".git").mkdir()
        (self.repo / ".git" / "config").write_text(
            '[remote "origin"]\n url = https://github.com/a/b.git\n', encoding="utf-8"
        )
        (self.repo / "vercel.json").write_text("{}", encoding="utf-8")

    def scan(self) -> dict[str, Any]:
        env = {**os.environ, "DTS2_HOME": str(self.dts2)}
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                str(SCRIPT),
                "--cwd",
                str(self.repo),
                "--home",
                str(self.home),
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data: dict[str, Any] = json.loads(result.stdout)
        return data

    def ids(self, data: dict[str, Any]) -> set[str]:
        return {item["id"] for item in data["recommendations"]}

    def test_connected_toolkits_suppress_recommendations(self) -> None:
        (self.dts2 / "composio-tools.json").write_text(
            json.dumps(
                {"version": 1, "toolkits": [], "connected": ["github", "vercel"]}
            ),
            encoding="utf-8",
        )
        data = self.scan()
        self.assertNotIn("mcp-github", self.ids(data))
        self.assertNotIn("mcp-vercel", self.ids(data))
        titles = {item["title"] for item in data["info"]}
        self.assertEqual(
            titles, {"covered by Composio (github)", "covered by Composio (vercel)"}
        )

    def test_unconnected_toolkit_is_still_recommended(self) -> None:
        (self.dts2 / "composio-tools.json").write_text(
            json.dumps({"connected": ["github"]}), encoding="utf-8"
        )
        data = self.scan()
        self.assertIn("mcp-vercel", self.ids(data))
        self.assertNotIn("mcp-github", self.ids(data))

    def test_missing_map_is_unchanged(self) -> None:
        data = self.scan()
        self.assertIn("mcp-github", self.ids(data))
        self.assertIn("mcp-vercel", self.ids(data))
        self.assertNotIn("info", data)

    def test_corrupt_map_is_unchanged(self) -> None:
        (self.dts2 / "composio-tools.json").write_text("{not json", encoding="utf-8")
        data = self.scan()
        self.assertIn("mcp-github", self.ids(data))
        self.assertNotIn("info", data)


if __name__ == "__main__":
    unittest.main()
