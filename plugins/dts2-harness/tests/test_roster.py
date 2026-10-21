"""Tests for agent profiles and scripts/roster.py."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

from helpers import PLUGIN_ROOT, run_script

PROFILE_DIR: Final[Path] = PLUGIN_ROOT / "profiles" / "agents"
PROFILE_NAMES: Final[tuple[str, ...]] = (
    "claude", "codex", "gemini", "opencode", "copilot", "cursor", "antigravity",
)
SCHEMA_KEYS: Final[frozenset[str]] = frozenset({
    "name", "displayName", "form", "rulesFile", "invocation", "command",
    "headlessFlag", "roles", "specialty", "verified",
})
VERIFIED: Final[frozenset[str]] = frozenset({"claude", "codex", "gemini", "opencode"})
ROSTER: Final[Path] = PLUGIN_ROOT / "scripts" / "roster.py"


def write_config(text: str) -> str:
    folder: Path = Path(tempfile.mkdtemp(prefix="dts2-roster-"))
    path: Path = folder / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def raw_run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(ROSTER), *args],
        capture_output=True, text=True, cwd=str(PLUGIN_ROOT), env=env,
    )


class ProfileTests(unittest.TestCase):
    def test_every_profile_has_schema(self) -> None:
        for name in PROFILE_NAMES:
            data: dict[str, Any] = json.loads((PROFILE_DIR / f"{name}.json").read_text())
            self.assertEqual(set(data), SCHEMA_KEYS, name)
            self.assertEqual(data["name"], name)
            self.assertEqual(data["verified"], name in VERIFIED, name)

    def test_claude_roles(self) -> None:
        data: dict[str, Any] = json.loads((PROFILE_DIR / "claude.json").read_text())
        self.assertIn("lead", data["roles"])
        self.assertIn("verifier", data["roles"])

    def test_ide_profiles_are_handoff(self) -> None:
        for name in ("cursor", "antigravity"):
            data: dict[str, Any] = json.loads((PROFILE_DIR / f"{name}.json").read_text())
            self.assertEqual(data["invocation"], "handoff")
            self.assertIsNone(data["command"])


class DetectTests(unittest.TestCase):
    def test_empty_path_is_claude_only(self) -> None:
        empty: str = tempfile.mkdtemp(prefix="dts2-path-")
        project: str = tempfile.mkdtemp(prefix="dts2-proj-")
        result = raw_run("detect", "--project", project, env={"PATH": empty})
        data: dict[str, Any] = json.loads(result.stdout)
        self.assertEqual(data["installed"], ["claude"])
        self.assertTrue(data["claudeOnly"])

    def test_fake_binary_and_ide_marker(self) -> None:
        bindir: Path = Path(tempfile.mkdtemp(prefix="dts2-bin-"))
        fake: Path = bindir / "codex"
        fake.write_text("#!/bin/sh\n")
        fake.chmod(0o755)
        project: Path = Path(tempfile.mkdtemp(prefix="dts2-proj-"))
        (project / ".cursor").mkdir()
        result = raw_run("detect", "--project", str(project), env={"PATH": str(bindir)})
        data: dict[str, Any] = json.loads(result.stdout)
        self.assertEqual(data["installed"], ["claude", "codex", "cursor"])
        self.assertFalse(data["claudeOnly"])


class ResolveTests(unittest.TestCase):
    def test_no_roster_is_claude_on_all_roles(self) -> None:
        missing: str = str(Path(tempfile.mkdtemp()) / "nope.yaml")
        data: dict[str, Any] = run_script("roster.py", "resolve", "--config", missing)
        self.assertEqual(data["enabled"], ["claude"])
        for role in ("lead", "verifier", "builder", "reviewer"):
            self.assertEqual(data["assignments"][role], ["claude"])
        self.assertEqual(data["handoff"], [])
        self.assertEqual(data["live"], ["claude"])

    def test_cursor_builder_is_handoff(self) -> None:
        cfg: str = write_config(
            "roster:\n  - name: claude\n  - name: cursor\n    roles: [builder]\n"
        )
        data: dict[str, Any] = run_script("roster.py", "resolve", "--config", cfg)
        self.assertEqual(data["handoff"], ["cursor"])
        self.assertEqual(data["live"], ["claude"])
        self.assertIn("cursor", data["assignments"]["builder"])

    def test_cursor_lead_rejected(self) -> None:
        cfg: str = write_config("roster:\n  - name: cursor\n    roles: [lead]\n")
        result = raw_run("resolve", "--config", cfg)
        self.assertEqual(result.returncode, 1)
        self.assertIn("lead", result.stderr + result.stdout)

    def test_unknown_agent_rejected(self) -> None:
        cfg: str = write_config("roster:\n  - name: nonesuch\n")
        self.assertEqual(raw_run("resolve", "--config", cfg).returncode, 1)

    def test_config_without_roster_block(self) -> None:
        cfg: str = write_config("other: 1\n")
        data: dict[str, Any] = run_script("roster.py", "resolve", "--config", cfg)
        self.assertEqual(data["enabled"], ["claude"])


if __name__ == "__main__":
    unittest.main()
