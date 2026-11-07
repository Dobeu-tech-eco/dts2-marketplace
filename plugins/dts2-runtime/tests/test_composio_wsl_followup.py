"""scripts/composio-setup.py: object-keyed `connections list`, the DTS2_COMPOSIO_WSL toggle, and the WSL login check."""
from __future__ import annotations

import json
import os
import subprocess
import unittest
import unittest.mock as mock
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from test_composio_map_fallback import load_module

WSL_BINARY: Final[list[str]] = ["wsl", "-e", "/home/x/.local/bin/composio"]
LOCAL_BINARY: Final[list[str]] = ["/usr/bin/composio"]
PROBE: Final[list[str]] = ["wsl", "-e", "sh", "-c", 'test -d "$HOME/.composio"']
KEYS: Final[tuple[str, ...]] = ("toolkit", "slug")


class ModuleCase(unittest.TestCase):
    def setUp(self) -> None:
        self.module: ModuleType = load_module()
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("DTS2_COMPOSIO_BIN", "DTS2_COMPOSIO_WSL", "COMPOSIO_CACHE_DIR"):
            os.environ.pop(name, None)


class ConnectionsShapeTests(ModuleCase):
    def slugs(self, data: Any) -> list[str]:
        return [row["slug"] for row in self.module.connections_rows(json.dumps(data), KEYS)]

    def test_active_accounts_are_kept(self) -> None:
        self.assertEqual(self.slugs({"github": [{"id": "c1", "status": "ACTIVE"}]}), ["github"])

    def test_expired_only_toolkits_are_dropped(self) -> None:
        self.assertEqual(self.slugs({"gmail": [{"status": "EXPIRED"}, {"status": "FAILED"}]}), [])

    def test_mixed_accounts_keep_the_toolkit(self) -> None:
        self.assertEqual(self.slugs({"slack": [{"status": "EXPIRED"}, {"status": "ACTIVE"}]}), ["slack"])

    def test_lowercase_active_and_missing_status(self) -> None:
        self.assertEqual(self.slugs({"a": [{"status": "active"}], "b": [{"id": "x"}], "c": ["raw"]}), ["a", "b", "c"])

    def test_rows_hold_only_the_slug(self) -> None:
        rows = self.module.connections_rows(json.dumps({"github": [{"id": "secret", "status": "ACTIVE"}]}), KEYS)
        self.assertEqual(rows, [{"slug": "github"}])

    def test_list_wrapped_list_and_text_still_work(self) -> None:
        listed = [{"toolkit": {"slug": "a"}, "status": "ACTIVE"}, {"toolkit": {"slug": "b"}, "status": "EXPIRED"}]
        self.assertEqual(self.slugs(listed), ["a"])
        self.assertEqual(self.slugs({"items": listed}), ["a"])
        self.assertEqual([r["slug"] for r in self.module.connections_rows("github\nslack\n", KEYS)], ["github", "slack"])

    def test_fetch_connected_uses_the_object_shape(self) -> None:
        outputs = {self.module.DEV_CONNECTED_WORDS: None,
                   self.module.CONNECTIONS_WORDS: json.dumps({"github": [{"status": "ACTIVE"}], "gmail": [{"status": "EXPIRED"}]})}

        def fake_listing(_binary: list[str], words: tuple[str, ...], _timeout: int) -> str:
            text = outputs[words]
            if text is None:
                raise RuntimeError("no project")
            return text

        with mock.patch.object(self.module, "run_listing", side_effect=fake_listing):
            rows, source = self.module.fetch_connected(LOCAL_BINARY, 1)
        self.assertEqual((rows, source), ([{"slug": "github"}], "connections"))


class WslToggleTests(ModuleCase):
    def test_zero_disables_the_lookup(self) -> None:
        os.environ["DTS2_COMPOSIO_WSL"] = "0"
        with mock.patch.object(self.module.shutil, "which", return_value="C:/wsl.exe"), \
                mock.patch.object(self.module.subprocess, "run") as run:
            self.assertIsNone(self.module.wsl_binary())
        run.assert_not_called()

    def test_other_values_keep_the_lookup(self) -> None:
        os.environ["DTS2_COMPOSIO_WSL"] = "1"
        done = subprocess.CompletedProcess(["wsl"], 0, stdout="/home/x/.local/bin/composio\n", stderr="")
        with mock.patch.object(self.module.shutil, "which", return_value="C:/wsl.exe"), \
                mock.patch.object(self.module.subprocess, "run", return_value=done):
            self.assertEqual(self.module.wsl_binary(), WSL_BINARY)


class LoggedInTests(ModuleCase):
    def setUp(self) -> None:
        super().setUp()
        self.home = Path("/nonexistent-home")

    def probe(self, **kwargs: Any) -> tuple[bool, mock.MagicMock]:
        with mock.patch.object(self.module.subprocess, "run", **kwargs) as run:
            return self.module.logged_in(self.home, WSL_BINARY), run

    def test_wsl_binary_success(self) -> None:
        result, run = self.probe(return_value=subprocess.CompletedProcess(PROBE, 0))
        self.assertTrue(result)
        self.assertEqual(run.call_args.args[0], PROBE)
        self.assertEqual(run.call_args.kwargs["timeout"], self.module.WSL_TIMEOUT)

    def test_wsl_binary_missing_directory(self) -> None:
        result, _run = self.probe(return_value=subprocess.CompletedProcess(PROBE, 1))
        self.assertFalse(result)

    def test_wsl_binary_timeout_and_os_error(self) -> None:
        self.assertFalse(self.probe(side_effect=subprocess.TimeoutExpired(PROBE, 10))[0])
        self.assertFalse(self.probe(side_effect=OSError("no wsl"))[0])

    def test_local_binary_checks_the_local_directory(self) -> None:
        with mock.patch.object(self.module.subprocess, "run") as run, \
                mock.patch.object(self.module, "credential_dir") as cred:
            cred.return_value.is_dir.return_value = True
            self.assertTrue(self.module.logged_in(self.home, LOCAL_BINARY))
        run.assert_not_called()

    def test_cache_dir_override_skips_the_wsl_probe(self) -> None:
        os.environ["COMPOSIO_CACHE_DIR"] = "/nonexistent-cache"
        with mock.patch.object(self.module.subprocess, "run") as run:
            self.assertFalse(self.module.logged_in(self.home, WSL_BINARY))
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
