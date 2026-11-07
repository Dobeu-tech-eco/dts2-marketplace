"""scripts/composio-setup.py: `map` falls back to `connections list`, and the CLI is found inside WSL on Windows."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import unittest
import unittest.mock as mock
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import test_composio_setup as base
from helpers import PLUGIN_ROOT

WSL_PATH: Final[str] = "/home/x/.local/bin/composio"
FALLBACK_CLI: Final[str] = """#!/bin/sh
echo "$*" >> "$FAKE_LOG"
case "$*" in
  "dev toolkits list") cat "$FAKE_TOOLKITS" ;;
  "dev connected-accounts list") echo "No developer project configured for this directory. Run \\`composio dev init\\`." >&2; exit 1 ;;
  "connections list") cat "$FAKE_CONNECTIONS" ;;
  *) echo "unexpected: $*" >&2; exit 9 ;;
esac
"""
BOTH_FAIL_CLI: Final[str] = """#!/bin/sh
case "$*" in
  "dev toolkits list") cat "$FAKE_TOOLKITS" ;;
  *) exit 1 ;;
esac
"""
CONNECTIONS: Final[str] = json.dumps([
    {"toolkit": {"slug": "github"}, "status": "ACTIVE"},
    {"toolkit": {"slug": "slack"}, "status": "active"},
    {"toolkit": {"slug": "notion"}, "status": "EXPIRED"},
    {"toolkit": {"slug": "linear"}, "status": "INITIATED"},
    {"toolkit": {"slug": "jira"}},
])


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("composio_setup_under_test", base.SCRIPT)
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FallbackCase(base.ComposioCase):
    def fallback_cli(self, connections: str = CONNECTIONS, body: str = FALLBACK_CLI) -> Path:
        binary: Path = self.fake_cli(base.JSON_TOOLKITS, "[]", body=body)
        base.write(self.bin_dir / "connections.txt", connections)
        self.env.update({"FAKE_CONNECTIONS": str(self.bin_dir / "connections.txt"),
                         "FAKE_LOG": str(self.bin_dir / "calls.log")})
        return binary


class MapFallbackTests(FallbackCase):
    def test_falls_back_when_dev_connected_accounts_fails(self) -> None:
        self.fallback_cli()
        out = self.run_cli("map", scoped=False)
        self.assertEqual((out["source"], out["connected_source"]), ("cli", "connections"))
        self.assertEqual(out["toolkits"], 4)
        saved = json.loads((self.state / "composio-tools.json").read_text())
        self.assertEqual(saved["connected_source"], "connections")

    def test_only_active_rows_are_kept(self) -> None:
        self.fallback_cli()
        out = self.run_cli("map", scoped=False)
        self.assertEqual(out["connected"], ["github", "jira", "slack"])

    def test_never_runs_dev_init(self) -> None:
        self.fallback_cli()
        self.run_cli("map", scoped=False)
        calls: list[str] = (self.bin_dir / "calls.log").read_text().splitlines()
        self.assertEqual(calls, ["dev toolkits list", "dev connected-accounts list", "connections list"])

    def test_dev_connected_accounts_still_preferred_when_it_works(self) -> None:
        self.fake_cli(base.JSON_TOOLKITS, base.JSON_CONNECTED)
        out = self.run_cli("map", scoped=False)
        self.assertEqual((out["connected_source"], out["connected"]), ("dev-connected-accounts", ["github", "slack"]))

    def test_import_records_its_source(self) -> None:
        source = base.write(self.bin_dir / "meta.json", json.dumps({"toolkits": ["github"], "connected": ["github"]}))
        out = self.run_cli("map", "--from-json", str(source), scoped=False)
        self.assertEqual(out["connected_source"], "import")

    def test_both_commands_failing_is_a_failure_naming_both(self) -> None:
        self.fallback_cli(body=BOTH_FAIL_CLI)
        out = self.run_cli("map", expect=1, scoped=False)
        self.assertIn("dev connected-accounts list", out["error"])
        self.assertIn("connections list", out["error"])
        self.assertFalse((self.state / "composio-tools.json").exists())


class StatusFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module: ModuleType = load_module()

    def test_status_is_case_insensitive_and_missing_status_is_kept(self) -> None:
        rows: list[dict[str, Any]] = [
            {"slug": "a", "status": "Active"}, {"slug": "b", "status": " ACTIVE "}, {"slug": "c", "status": "failed"},
            {"slug": "d"}, {"slug": "e", "status": None}]
        kept = [r["slug"] for r in self.module.active_rows(rows)]
        self.assertEqual(kept, ["a", "b", "d", "e"])


class WslDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module: ModuleType = load_module()
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("DTS2_COMPOSIO_BIN", None)

    def which(self, present: set[str]) -> Any:
        return lambda name: f"C:/bin/{name}.exe" if name in present else None

    def wsl_result(self, stdout: str = WSL_PATH + "\n", code: int = 0) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["wsl"], code, stdout=stdout, stderr="")

    def test_is_windows_checks_os_name_and_platform(self) -> None:
        with mock.patch.object(self.module.sys, "platform", "win32"):
            self.assertTrue(self.module.is_windows())
        with mock.patch.object(self.module.sys, "platform", "linux"), mock.patch.object(self.module.os, "name", "posix"):
            self.assertFalse(self.module.is_windows())

    def test_windows_without_path_binary_uses_wsl(self) -> None:
        with mock.patch.object(self.module, "is_windows", return_value=True), \
                mock.patch.object(self.module.shutil, "which", side_effect=self.which({"wsl"})), \
                mock.patch.object(self.module.subprocess, "run", return_value=self.wsl_result()) as run:
            prefix = self.module.find_binary()
        self.assertEqual(prefix, ["wsl", "-e", WSL_PATH])
        self.assertEqual(run.call_args.args[0], ["wsl", "-e", "sh", "-lc", "command -v composio"])
        self.assertEqual(run.call_args.kwargs["timeout"], self.module.WSL_TIMEOUT)
        self.assertEqual(self.module.binary_label(prefix), f"wsl:{WSL_PATH}")

    def test_run_listing_prefixes_the_wsl_command(self) -> None:
        with mock.patch.object(self.module.subprocess, "run", return_value=self.wsl_result("[]")) as run:
            self.module.run_listing(["wsl", "-e", WSL_PATH], self.module.TOOLKITS_WORDS, 5)
        self.assertEqual(run.call_args.args[0], ["wsl", "-e", WSL_PATH, "dev", "toolkits", "list"])

    def test_windows_path_binary_wins_over_wsl(self) -> None:
        with mock.patch.object(self.module, "is_windows", return_value=True), \
                mock.patch.object(self.module.shutil, "which", side_effect=self.which({"composio", "wsl"})), \
                mock.patch.object(self.module.subprocess, "run") as run:
            self.assertEqual(self.module.find_binary(), ["C:/bin/composio.exe"])
        run.assert_not_called()

    def test_windows_without_wsl_or_cli_in_wsl_is_none(self) -> None:
        with mock.patch.object(self.module, "is_windows", return_value=True):
            with mock.patch.object(self.module.shutil, "which", side_effect=self.which(set())):
                self.assertIsNone(self.module.find_binary())
            with mock.patch.object(self.module.shutil, "which", side_effect=self.which({"wsl"})), \
                    mock.patch.object(self.module.subprocess, "run", return_value=self.wsl_result("", 1)):
                self.assertIsNone(self.module.find_binary())

    def test_wsl_errors_and_timeouts_are_swallowed(self) -> None:
        for error in (OSError("boom"), subprocess.TimeoutExpired("wsl", 10)):
            with mock.patch.object(self.module, "is_windows", return_value=True), \
                    mock.patch.object(self.module.shutil, "which", side_effect=self.which({"wsl"})), \
                    mock.patch.object(self.module.subprocess, "run", side_effect=error):
                self.assertIsNone(self.module.find_binary())

    def test_non_windows_never_tries_wsl(self) -> None:
        looked_up: list[str] = []

        def which(name: str) -> None:
            looked_up.append(name)

        with mock.patch.object(self.module, "is_windows", return_value=False), \
                mock.patch.object(self.module.shutil, "which", side_effect=which), \
                mock.patch.object(self.module.subprocess, "run") as run:
            self.assertIsNone(self.module.find_binary())
        self.assertEqual(looked_up, ["composio"])
        run.assert_not_called()

    def test_override_binary_is_unchanged_and_skips_wsl(self) -> None:
        os.environ["DTS2_COMPOSIO_BIN"] = str(PLUGIN_ROOT / "nope")
        with mock.patch.object(self.module, "is_windows", return_value=True), \
                mock.patch.object(self.module.subprocess, "run") as run:
            self.assertIsNone(self.module.find_binary())
        run.assert_not_called()
        self.assertEqual(self.module.binary_label(["/usr/bin/composio"]), "/usr/bin/composio")
        self.assertIsNone(self.module.binary_label(None))


if __name__ == "__main__":
    unittest.main()
