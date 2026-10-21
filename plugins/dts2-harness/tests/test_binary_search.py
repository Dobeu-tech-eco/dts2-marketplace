"""Tests for roster.py binary resolution: off-PATH search paths and the DTS2_BIN_<NAME> override."""
from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Final

PLUGIN_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
ROSTER_PATH: Final[Path] = PLUGIN_ROOT / "scripts" / "roster.py"


def load_roster() -> Any:
    spec = importlib.util.spec_from_file_location("roster_under_test", ROSTER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_binary(name: str) -> Path:
    folder: Path = Path(tempfile.mkdtemp(prefix="dts2-bin-"))
    binary: Path = folder / name
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    return binary


class BinaryResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.roster = load_roster()

    def test_override_key_sanitizes(self) -> None:
        self.assertEqual(self.roster.override_key("agy"), "DTS2_BIN_AGY")
        self.assertEqual(self.roster.override_key("gh-copilot"), "DTS2_BIN_GH_COPILOT")

    def test_found_on_path(self) -> None:
        binary: Path = make_binary("agy")
        env: dict[str, str] = {"PATH": str(binary.parent)}
        self.assertEqual(self.roster.resolve_binary("agy", env, []), str(binary))

    def test_missing_binary_returns_none(self) -> None:
        self.assertIsNone(self.roster.resolve_binary("agy", {"PATH": ""}, []))

    def test_search_path_finds_off_path_binary(self) -> None:
        binary: Path = make_binary("agy")
        env: dict[str, str] = {"PATH": ""}
        self.assertEqual(
            self.roster.resolve_binary("agy", env, [str(binary.parent)]), str(binary)
        )

    def test_override_as_file_wins(self) -> None:
        binary: Path = make_binary("agy")
        env: dict[str, str] = {"PATH": "", self.roster.override_key("agy"): str(binary)}
        self.assertEqual(self.roster.resolve_binary("agy", env, []), str(binary))

    def test_override_as_directory(self) -> None:
        binary: Path = make_binary("grok")
        env: dict[str, str] = {"PATH": "", self.roster.override_key("grok"): str(binary.parent)}
        self.assertEqual(self.roster.resolve_binary("grok", env, []), str(binary))

    def test_search_path_expands_user_and_vars(self) -> None:
        binary: Path = make_binary("agy")
        env: dict[str, str] = {"PATH": "", "DTS2_TESTDIR": str(binary.parent)}
        os.environ["DTS2_TESTDIR"] = str(binary.parent)
        try:
            self.assertEqual(
                self.roster.resolve_binary("agy", env, ["$DTS2_TESTDIR"]), str(binary)
            )
        finally:
            os.environ.pop("DTS2_TESTDIR", None)

    def test_gemini_profile_is_agy_with_search_paths(self) -> None:
        profiles: dict[str, Any] = self.roster.load_profiles()
        gemini: dict[str, Any] = profiles["gemini"]
        self.assertEqual(gemini["command"][0], "agy")
        self.assertEqual(gemini["statusCommand"][0], "agy")
        self.assertTrue(gemini["searchPaths"])

    def test_availability_uses_search_path(self) -> None:
        binary: Path = make_binary("grok")
        env: dict[str, str] = {"PATH": ""}
        profile: dict[str, Any] = {
            "statusCommand": ["grok", "version"], "searchPaths": [str(binary.parent)],
        }
        available, reason = self.roster.availability(profile, env)
        self.assertTrue(available)
        self.assertEqual(reason, "ok")


if __name__ == "__main__":
    unittest.main()
